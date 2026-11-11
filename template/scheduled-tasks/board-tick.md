Board tick for the steward hub at <hub>. Only the main machine runs this.

1. git pull the hub (never with --autostash).
2. python3 tools/lock.py dupes: merge any person with two open sends into one entry.
3. For each OPEN send entry: python3 tools/lock.py preflight person:<To> --action send. Exit 1: leave it for
   the lane that holds it. Exit 3: mark it done with tools/board.py done <id> --ref <ref>.
4. python3 tools/board.py fold, then commit board/ and handoffs/board-inbox/ with tools/hub_push.sh.
5. Show the owner what is new on the board, sends in full, and stop. Never send from a tick.
