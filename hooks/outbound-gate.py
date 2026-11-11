#!/usr/bin/env python3
"""Outbound gate: every send asks the human, and nothing banned goes out.

PreToolUse (matcher Bash|mcp__.*):
  - Any MCP send tool (names ending in send_message, send_gmail_message, send_email, reply, forward,
    post_message) returns permissionDecision "ask", so a send always prompts, even in auto mode. Claude app
    tools (mcp__ccd_*) are exempt. Add more names with STEWARD_SEND_TOOLS (a regex on the part after the
    last "__").
  - The ask names any live hub lock another machine holds on the recipient or thread, and any ledger record
    that the same message already went out (tools/lock.py; read offline, fails open).
  - Outgoing text (MCP send and draft tools; gh pr/issue create/edit/comment; git commit, including -F files)
    containing a character from steward.json "banned_chars" is blocked (exit 2) with the reason.
PostToolUse (--post, async): after a send that did not error, record it in the hub ledger.
Stop (--stop): if the last reply contains a banned character, block once so it is restated.
"""
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _hub  # noqa: E402

SEND_NAMES = r"send_message|send_gmail_message|send_email|reply|forward|post_message"
DRAFT_NAMES = r"create_draft|update_draft|draft_gmail_message|create_comment|manage_document_comment"
EXTRA = os.environ.get("STEWARD_SEND_TOOLS", "")
SEND_TOOL = re.compile(r"^mcp__(?!ccd_).+__(%s%s)$" % (SEND_NAMES, "|" + EXTRA if EXTRA else ""))
TEXT_TOOL = re.compile(r"^mcp__(?!ccd_).+__(%s|%s%s)$" % (SEND_NAMES, DRAFT_NAMES, "|" + EXTRA if EXTRA else ""))
OUTBOUND_BASH = re.compile(r"\bgh\s+(pr|issue)\s+(create|edit|comment|review)\b|\bgit\s+commit\b|\bgh\s+release\s+(create|edit)\b")
FILE_FLAGS = ("-F", "--body-file", "--file")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def found(text, chars):
    return sorted({"U+%04X" % ord(c) for c in chars if c in (text or "")})


def body_files(command):
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return []
    files = []
    for i, tok in enumerate(tokens):
        for flag in FILE_FLAGS:
            if tok == flag and i + 1 < len(tokens):
                files.append(tokens[i + 1])
            elif tok.startswith(flag + "="):
                files.append(tok.split("=", 1)[1])
    return [f for f in files if f not in ("-", "")]


def send_fields(ti):
    to = []
    for k in ("to", "cc", "recipient", "recipients", "email"):
        v = ti.get(k)
        if v:
            to += EMAIL.findall(v if isinstance(v, str) else json.dumps(v))
    thread = ""
    for k in ("thread_id", "threadId"):
        if ti.get(k):
            thread = "thread:mail:" + str(ti[k])
            break
    if not thread and ti.get("channel"):
        thread = "thread:chat:" + str(ti["channel"])
    subject = str(ti.get("subject") or "")
    body = ""
    for k in ("body", "htmlBody", "text", "message"):
        if ti.get(k):
            body = ti[k] if isinstance(ti[k], str) else json.dumps(ti[k])
            break
    return {"to": [t.lower() for t in to], "thread": thread, "subject": subject, "body": body}


def idem_for(mod, f):
    return mod.idem_key(",".join(sorted(f["to"])) or f["thread"], f["subject"], f["body"])


def lock_notes(ti):
    try:
        mod = _hub.load_tool("lock")
        if not mod:
            return []
        f = send_fields(ti)
        keys = ["person:" + t for t in f["to"]] + ([f["thread"]] if f["thread"] else [])
        if not keys:
            return []
        hub = str(_hub.hub_path())
        machine = mod.this_machine(hub)
        idem = idem_for(mod, f)
        notes = []
        for i, key in enumerate(keys):
            r = mod.preflight(mod.Store(repo=hub), key, "send", machine, None, idem if i == 0 else "", "", offline=True)
            if r.get("lock"):
                notes.append("HUB LOCK: " + mod.describe(r["lock"]))
            for e in r.get("done") or []:
                if i == 0:
                    notes.append("ALREADY SENT per hub ledger: %s by %s at %s" % (e.get("key"), e.get("machine"), e.get("time")))
        return notes
    except Exception:
        return []


def block(reason):
    print(reason, file=sys.stderr)
    sys.exit(2)


def pre_tool_use(data):
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    chars = _hub.banned_chars()
    if tool == "Bash":
        command = ti.get("command", "") or ""
        if not chars or not OUTBOUND_BASH.search(command):
            return
        hits = ["command text"] if found(command, chars) else []
        cwd = Path(data.get("cwd") or ".")
        for f in body_files(command):
            p = Path(f).expanduser()
            p = p if p.is_absolute() else cwd / p
            try:
                if found(p.read_text(errors="replace"), chars):
                    hits.append(f)
            except OSError:
                pass
        if hits:
            block("BLOCKED by outbound-gate: banned character (%s) in %s. Rewrite and retry."
                  % (", ".join(found(command + "".join(chars), chars)), "; ".join(hits)))
        return
    if TEXT_TOOL.match(tool) and chars:
        payload = json.dumps(ti, ensure_ascii=False)
        if found(payload, chars):
            block("BLOCKED by outbound-gate: %s input has a banned character (%s). Rewrite and retry."
                  % (tool, ", ".join(found(payload, chars))))
    if SEND_TOOL.match(tool):
        notes = lock_notes(ti)
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": "Steward rule: every send needs the owner's yes on this exact message."
            + ((" " + " ".join(notes)) if notes else ""),
        }}))


def post_tool_use(data):
    tool = data.get("tool_name", "")
    if not SEND_TOOL.match(tool):
        return
    resp = data.get("tool_response")
    text = resp if isinstance(resp, str) else json.dumps(resp)
    if re.search(r'"?(error|isError)"?\s*[:=]\s*(true|"[^"]+")', text or "", re.I):
        return
    f = send_fields(data.get("tool_input") or {})
    key = ("person:" + f["to"][0]) if f["to"] else f["thread"]
    hub = _hub.hub_path()
    mod = _hub.load_tool("lock")
    if not key or not hub or not mod:
        return
    m = re.search(r'"(?:id|messageId|message_id)"\s*:\s*"([^"]{4,120})"', (text or "").replace('\\"', '"'))
    subprocess.Popen([sys.executable, str(hub / "tools/lock.py"), "record", key, "--action", "send",
                      "--ref", m.group(1) if m else "", "--idem", idem_for(mod, f), "--note", f["subject"][:80],
                      "--session", os.environ.get("STEWARD_SESSION") or "outbound-gate"],
                     cwd=str(hub), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def last_assistant_text(data):
    text = data.get("last_assistant_message")
    if isinstance(text, str):
        return text
    path = data.get("transcript_path")
    if not path:
        return ""
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        msg = rec.get("message") or {}
        if rec.get("type") != "assistant":
            continue
        parts = [c.get("text", "") for c in msg.get("content") or [] if isinstance(c, dict) and c.get("type") == "text"]
        if parts:
            return "\n".join(parts)
    return ""


def stop(data):
    if data.get("stop_hook_active"):
        return
    chars = _hub.banned_chars()
    hit = found(last_assistant_text(data), chars)
    if hit:
        block("Your last reply contains a banned character (%s). Restate it in full without it." % ", ".join(hit))


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    if "--stop" in sys.argv:
        stop(data)
    elif "--post" in sys.argv:
        try:
            post_tool_use(data)
        except Exception:
            pass
    else:
        pre_tool_use(data)


if __name__ == "__main__":
    main()
