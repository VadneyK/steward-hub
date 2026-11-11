Daily self-improvement pass for the steward hub at <hub>.

1. Collect today's corrections from the owner: their typed messages in today's session transcripts under
   ~/.claude/projects, comments on artifacts updated today, and ANSWERED entries in handoffs/board-inbox.
   Use a small, cheap subagent for the collection.
2. For each correction not already covered by a memory note or a skill: write one memory note with the exact
   quote, what was wrong, and how to apply it. If a script could check it, add a test or a hook rule in the
   hub's shared/ folder and run `make check` there.
3. Write log/self-improve/<date>-daily.md: one line per correction, the memory it went to. No private content.
4. Commit with tools/hub_push.sh. If there were no corrections, write one line with the count per source and stop.
