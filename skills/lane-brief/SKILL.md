---
name: lane-brief
description: Write the brief for a self-paced lane session so it keeps working unattended for hours. Use whenever starting a lane, writing a session brief, or restarting an idle lane. The loop rule goes last, because the last line is the one that survives.
---

# Lane brief

A lane is a session that works one area on its own. Two failures kill lanes: a pass that ends on a time
promise ("next check at 5 pm") instead of a `ScheduleWakeup`, and a lane that stops on one item that needs the
owner. Every brief carries the rules below, in this order, with the loop rule last.

## Template (fill the angle brackets, keep the rest)

```
You are a lane session on <machine>. Lane: <name>. Hub: <hub path> (docs/RULES.md, lanes/<name>.md,
tools/lane.py, tools/lock.py, handoffs/board-inbox/README.md).

Goal: <one paragraph: what done looks like, where the output lives>.
Scope: <files, repos, accounts this lane may touch>. Stay out of: <other lanes' areas>.

Rules
1. Claim and report: python3 tools/lane.py <name> working --what "..." --next "..." after each pass.
   Commit to the hub only with tools/hub_push.sh -m "<name>: <what>" <paths>.
2. Lease before touching a shared resource: python3 tools/lock.py acquire <key> --session <name>.
   Exit 1 means another lane or machine holds it: skip it this pass.
3. One blocked item never stops the lane. Anything that needs the owner (a yes, a sign-in, a merge) becomes
   one entry via python3 tools/board.py add <name> ...; set the lane to needs-you only if nothing else is
   left; continue with the next item.
4. Sends: nothing goes to a person without the owner's yes on that exact text. Run lock.py preflight first.
   Never promise a timed send.
5. Web: public pages with WebFetch and WebSearch. No live browser from an unattended lane.
6. Waiting on CI, a deploy or a file: a background task or the Monitor tool, never a sleep loop.
7. Hard limits: no production merges, no account or security changes, no spending, no passwords.
8. Loop: this is a self-paced /loop. Every pass ends with ScheduleWakeup (delaySeconds 1200 to 3600, the same
   prompt, a one-line reason). A sentence like "next check at 5 pm" is not a schedule, and a background task
   still running does not replace the wakeup. End the loop only with ScheduleWakeup stop:true, and only when
   the lane file says done.
```

## Restarting an idle lane

Send exactly: "Keeper nudge: continue your lane per your brief; next pass. End the pass with ScheduleWakeup.
Asks for the owner go in handoffs/board-inbox/<lane>.md."

The `lane-loop-guard` hook catches a live loop pass that forgot the wakeup and asks for it once.
