# Steward standing rules

These lines load in every Claude Code session on every machine (installed by `tools/sync.py` from the hub's
`shared/CLAUDE.md`). Edit them in the hub, commit, sync. Never edit the installed copy by hand.

They add to Claude's built-in safety rules and never replace or loosen them.

## Who decides

- Sends: nothing goes to a person (email, chat, post, comment, form) without the owner's yes on that exact
  text, shown in full (To, Cc, Subject, body) right above the question. One yes may cover a named batch.
- Money, passwords, sign-ins, account and security settings, production merges and deploys: the owner's hands
  only. Prepare, never perform.
- Work about people, purpose or judgment: ask the owner a few precise questions first, then build.

## How lanes work

- A lane is one area of work a session runs on its own. Claim it: `python3 <hub>/tools/lane.py <name> working
  --what "..." --next "..."`. Report each pass the same way. `done` releases it.
- Before touching anything another machine or lane could also touch (a person, a thread, an artifact), take a
  lease: `python3 <hub>/tools/lock.py acquire <key> --session <lane>`. Exit 1 means someone holds it: leave it.
- Before any send or submit: `python3 <hub>/tools/lock.py preflight <key> --action send`. Exit 3 means it
  already went out.
- Anything that needs the owner goes in `<hub>/handoffs/board-inbox/<lane>.md` (`tools/board.py add`), and the
  lane continues with its next item. One blocked item never stops a lane.
- Commit to the hub only with `<hub>/tools/hub_push.sh -m "<lane>: <what>" <paths>`: it names every path,
  never stashes, never forces.

## Corrections become rules the same day

When the owner corrects something, write it down that day: a memory note with their exact words, and a test
or a hook when the rule can be checked by a script. See `<hub>/docs/CADENCE.md`.

## Writing

- Never sign work as Claude unless the owner wants that (no AI byline or co-author trailer by default).
- Characters in `steward.json` "banned_chars" never appear in anything that goes out; the outbound gate
  blocks them.
