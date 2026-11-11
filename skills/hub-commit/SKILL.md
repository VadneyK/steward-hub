---
name: hub-commit
description: Commit and push to the steward hub from a session that shares the checkout with other sessions. Use for any hub commit from a lane or the main session instead of git pull --rebase by hand; it names every path, never stashes, never forces, and handles status.json conflicts and push races.
---

# Hub commit

The hub path is in `~/.claude/steward/hub`.

```bash
HUB=$(cat ~/.claude/steward/hub)
cd "$HUB" && tools/hub_push.sh -m "<lane>: <what>" <path> [<path>...]
```

- Name every path you changed. Never `git add -A` in the hub: other sessions have uncommitted files there.
- Exit 0 pushed. 2 network (commit stays local, retry next pass). 3 conflict (commit stays local, tree as it
  was; read the conflict, fix your own file, retry). 4 the checkout is mid merge or rebase: leave it, tell the
  owner. 5 a banned character (steward.json) is in a named file: fix the text, retry.
- Never stash, reset, or switch branches in the shared checkout.
