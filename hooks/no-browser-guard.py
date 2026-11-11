#!/usr/bin/env python3
"""No-browser guard: unattended lanes read the web with WebFetch, not a live browser.

Why: a browser tab opened by a background session can play audio, steal focus, or sit on a sign-in page for
the rest of the day. This hook denies browser-driving tools (the in-app browser pane and the Chrome extension)
and shell commands that open URLs or play sound, unless the switch file ~/.claude/browser-ok exists.
Closing tabs stays allowed. Local dev servers (localhost, 127.0.0.1) stay allowed.
Only the human creates the switch file, from their own terminal; the hook denies a session that tries.
"""
import json
import re
import sys
from pathlib import Path

SWITCH = Path.home() / ".claude" / "browser-ok"
BROWSER_TOOL = re.compile(r"^mcp__(Claude_Browser|claude-in-chrome)__")
ALLOWED_TOOL = re.compile(r"__(tabs_close|tabs_close_mcp|tabs_context|tabs_context_mcp|preview_list|preview_logs|preview_stop)$")
LOCAL = re.compile(r"^(https?://)?(localhost|127\.0\.0\.1|\[::1\]|[\w.-]+\.localhost)(:\d+)?(/|$)", re.I)
SHELL = re.compile(r"(^|[;&|(]\s*)(open\s+(-a\s+\S+\s+)?['\"]?https?://|afplay\b|say\b|python3?\s+-m\s+webbrowser\b)")


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    return 0


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    text = json.dumps(ti)
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit", "Bash") and "browser-ok" in text and (
            tool != "Bash" or re.search(r"(touch|>|cp|mv|ln)\b[^;&|]*browser-ok", ti.get("command", ""))):
        return deny("Only the owner creates ~/.claude/browser-ok, from their own terminal.")
    if SWITCH.exists():
        return 0
    if BROWSER_TOOL.match(tool):
        if ALLOWED_TOOL.search(tool):
            return 0
        url = ti.get("url") or ""
        actions = ti.get("actions") or []
        urls = [url] + [((a.get("input") or {}).get("url") or "") for a in actions if isinstance(a, dict)]
        urls = [u for u in urls if u and u not in ("back", "forward")]
        if urls and all(LOCAL.match(u) for u in urls):
            return 0
        if not urls and tool.endswith("preview_start") and ti.get("name"):
            return 0
        return deny("no-browser-guard: use WebFetch or WebSearch for outside pages. The owner can allow the "
                    "browser with `touch ~/.claude/browser-ok` in their own terminal.")
    if tool == "Bash" and SHELL.search(ti.get("command", "") or ""):
        return deny("no-browser-guard: no opening URLs or playing sound from a session. Put the link in your "
                    "reply for the owner instead.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
