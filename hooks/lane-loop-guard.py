#!/usr/bin/env python3
"""Lane loop guard (Stop hook): re-arm a self-paced lane loop that ended on a promise.

Why: in one two-week sample, most self-paced loop turns ended with a text summary ("next check at 5 pm") and
no ScheduleWakeup, so the loop fell to its fallback wakeup and died. This hook blocks that stop once, with a
reason that tells the lane to call ScheduleWakeup (or ScheduleWakeup stop:true to end the loop).

It never traps an ordinary session:
  - stop_hook_active true (already continuing because of a stop hook): allow.
  - session_crons present and non-empty (a wakeup is armed): allow.
  - the current turn already called ScheduleWakeup, armed or stop:true: allow.
  - the loop is not live: allow. Live means the previous turn re-armed it with ScheduleWakeup, or the
    current turn was started by a loop fire (the /loop prompt, a keeper nudge, "continue your lane").
    A session whose loop died turns ago and is now interactive is left alone.
  - LANE_LOOP_GUARD=off in the environment, or no readable transcript: allow.
Only a live loop whose current turn forgot the wakeup is blocked, and only once per turn.

Tests: tests/test_hooks.py in the steward-hub kit.
"""
import json
import os
import re
import sys

TAIL_BYTES = int(os.environ.get("LANE_LOOP_GUARD_TAIL", 16_000_000))
# A loop fire is the /loop skill prompt (what a ScheduleWakeup re-injects), the autonomous-loop sentinel,
# or a keeper nudge AT THE START of the message. A prompt that merely quotes the nudge text is not a fire.
FIRE = re.compile(
    r"<command-name>/?loop</command-name>|^\s*# /loop\b|<<autonomous-loop|\A\s*Keeper nudge:|\A\s*Keeper: continue your lane",
    re.I | re.M,
)
SKIP = (b'"api-request', b'file-history', b'"attachment"', b'"queue-operation"', b'"artifact-')
REASON = (
    "This is a self-paced lane: end the pass with ScheduleWakeup (delaySeconds, prompt, reason), or "
    "ScheduleWakeup stop:true to end the loop on purpose. A time promise in prose is not a schedule. "
    "Park anything that needs the owner in handoffs/board-inbox/<lane>.md and continue with the next item."
)


def read_tail(path):
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        start = max(0, size - TAIL_BYTES)
        fh.seek(start)
        data = fh.read()
    lines = data.split(b"\n")
    if start > 0 and lines:
        lines = lines[1:]  # drop the partial first line
    return lines


def turn_text(content):
    """The text of a user message that starts a turn, or None for a tool_result message."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                return None
            if block.get("type") == "text":
                texts.append(block.get("text", ""))
        return "\n".join(texts) if texts else None
    return None


def analyse(lines):
    """Return (live, turn_wakeup, turn_stop) for the current (last) turn in the tail."""
    prev_wakeup = False   # the turn before the current one re-armed the loop
    turn_wakeup = False
    turn_stop = False
    fire_started = False  # the current turn began with a loop fire or a keeper nudge
    for raw in lines:
        if not raw or raw[:1] != b"{":
            continue
        head = raw[:200]
        if any(s in head for s in SKIP):
            continue
        if b'"type":"user"' not in raw and b'"type": "user"' not in raw and b"ScheduleWakeup" not in raw:
            continue
        try:
            d = json.loads(raw)
        except Exception:
            continue
        kind = d.get("type")
        msg = d.get("message") or {}
        content = msg.get("content")
        if kind == "user":
            text = turn_text(content)
            if text is not None:
                prev_wakeup = turn_wakeup
                turn_wakeup = False
                turn_stop = False
                fire_started = bool(FIRE.search(text[:2000]))
        elif kind == "assistant" and isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "ScheduleWakeup":
                    if (block.get("input") or {}).get("stop"):
                        turn_stop = True
                    else:
                        turn_wakeup = True
    live = prev_wakeup or fire_started
    return live, turn_wakeup, turn_stop


def main():
    if os.environ.get("LANE_LOOP_GUARD", "").lower() == "off":
        return 0
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if data.get("stop_hook_active"):
        return 0
    crons = data.get("session_crons")
    if isinstance(crons, list) and crons:
        return 0
    path = data.get("transcript_path") or ""
    path = os.path.expanduser(path)
    if not path or not os.path.isfile(path):
        return 0
    try:
        live, turn_wakeup, turn_stop = analyse(read_tail(path))
    except Exception:
        return 0
    if not live or turn_wakeup or turn_stop:
        return 0
    print(json.dumps({"decision": "block", "reason": REASON}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
