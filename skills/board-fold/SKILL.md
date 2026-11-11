---
name: board-fold
description: Fold the lanes' asks from handoffs/board-inbox/*.md onto the owner's board (board/BOARD.md in the steward hub) and mark them FOLDED. Use when the main session runs its board tick, or when asked to "fold the board", "what is waiting for me", or "what asks are open".
---

# Board fold (main session only)

One writer builds the board. Lanes append asks to `handoffs/board-inbox/<lane>.md`.

1. Pull the hub: `cd "$(cat ~/.claude/steward/hub)" && git pull --rebase -q` (never `--autostash`; if it
   refuses, commit your own files first with hub-commit).
2. `python3 tools/lock.py dupes`. Merge any person with two open sends into one entry with labelled parts.
3. For each OPEN send entry: `python3 tools/lock.py preflight person:<To> --action send --grep <address>`.
   Exit 1: another machine holds that person; leave the entry. Exit 3: it already went; run
   `python3 tools/board.py done <id> --ref <ref>`.
4. `python3 tools/board.py fold`, then commit `board/` and `handoffs/board-inbox/` with hub-commit.
5. Show the owner the new cards. Every send card is shown in full (To, Cc, Subject, body) right above the
   question. Their answer goes back with `python3 tools/board.py answer <id> "<answer>"`, so the lane that
   wrote it acts on it. Approved sends: the lane sends, records with `lock.py record`, then `board.py done`.

Done means gone the same tick: when the work behind a card is done, mark it done in that tick.
