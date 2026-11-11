# steward-hub

A kit for running a personal "digital life steward" on Claude Code: long-running sessions (lanes) that work
your email, job search, side projects and paperwork on their own, coordinate through one private git repo
(the hub), and never send anything without your yes.

It is built from a setup the author has run daily across two Macs. Everything personal was left out; what is
here is the plumbing: leases so two sessions or two machines never work the same thing, a ledger so nothing
goes out twice, a board of asks for you, hooks that gate sends, and a cadence that turns your corrections
into rules.

Requirements: Claude Code (CLI or desktop app), git, Python 3.9 or newer, a private git remote you can push
to (a private GitHub repo works). macOS or Linux. One machine is enough; a second is optional.

## Pieces

| Piece | What it does | What it does not do |
|---|---|---|
| `tools/lock.py` | Leases on any resource key (`person:ada@example.com`, `lane:taxes`, `thread:<id>`), taken by a git push to the hub. The earlier push wins; leases expire; fencing tokens tell a sleeper it lost the lease. `preflight` before a send says "held elsewhere" or "already sent". | It is not a real-time lock: it is as fast as a git push (a second or two). It cannot stop a session that ignores it; the hooks and the brief are what make sessions use it. |
| ledger (`ledger/*.jsonl`) | Append-only record of what went out, one file per machine per day, written by `lock.py record` and by the outbound gate after an MCP send. | It does not read your Sent folder. Check that too. |
| `tools/lane.py` | One file per lane (`lanes/<name>.md`) with state, what, next; rebuilds `status.json`. A claim takes the `lane:<name>` lease. Private lanes keep only state and time in the hub. | It does not start or schedule sessions. You start lanes in Claude Code. |
| `tools/board.py` | Lanes append asks (send, decide, do) to `handoffs/board-inbox/<lane>.md`; `fold` builds `board/BOARD.md`, refuses two open sends to the same person, and records your answers. | No web UI. The board is a Markdown file; render it wherever you like. |
| `tools/hub_push.sh` | Commits only the paths you name and pushes, with no stash and no force, safe when several sessions share one checkout. Refuses banned characters. | It does not resolve real conflicts; it stops and leaves your commit local. |
| `tools/sync.py` | Installs the hub's `shared/` folder (standing rules, skills, hooks) into `~/.claude` on each machine, with backups, a manifest, and `.from-shared` files instead of overwriting your local edits. Merges hook registrations without removing any. | It never deletes files and does not manage MCP servers, logins or scheduled tasks. |
| `hooks/outbound-gate.py` | Every MCP send tool asks you, even in auto mode, and names any lease or ledger record for that recipient. Blocks banned characters in sends, drafts, commits and PRs, and in Claude's own last reply. | It only knows tools whose names look like sends; add yours with `STEWARD_SEND_TOOLS`. Shell scripts that send mail are not caught. |
| `hooks/ship-guard.py` | On repos you list, `make ship` is the only release path: direct merges, pushes to main or prod, and hand deploys are blocked. | Repos not in the list are untouched. |
| `hooks/no-browser-guard.py` | Unattended sessions read the web with WebFetch; live browser tools and "open a URL / play a sound" shell commands are denied unless you create `~/.claude/browser-ok` yourself. Localhost stays allowed. | It is a guard for unattended work, not a security boundary. |
| `hooks/lane-loop-guard.py` | A self-paced `/loop` pass that ends without `ScheduleWakeup` is asked once to schedule it, so lanes stop dying on "I'll check back at 5". | It never traps a normal session. |
| `skills/` | `hub-commit`, `lane-brief` (a brief template that keeps lanes alive), `board-fold`, `cdp-browser` (read a logged-in page in your own browser over CDP, interactive only), `values-check`. | Skills are instructions; Claude follows them well, not perfectly. |
| `template/docs/` | `RULES.md` (locks, idempotency, hand-offs, what needs you), `CADENCE.md` (daily, weekly, monthly self-improvement), `SPLIT.md` (two machines). | Rules on paper. The hooks enforce the parts a script can check. |
| `examples/values-pack-scripture/` | Optional example of a values check grounded in scripture, from the author's own setup. Off by default. | Not installed unless you copy it in. |

## Quickstart (about 10 minutes)

1. Get the kit.

   ```bash
   git clone https://github.com/VadneyK/steward-hub.git ~/steward-hub-kit
   cd ~/steward-hub-kit && make test
   ```

2. Create your hub. It holds your lanes and asks, so it must be private.

   ```bash
   ./init.sh ~/my-hub --machine a --tz America/New_York
   ```

3. Make an empty private repo (for example on GitHub), then push the hub to it.

   ```bash
   cd ~/my-hub && git remote add origin <your private repo url> && git push -u origin main
   ```

4. Install the standing rules, skills and hooks into `~/.claude` (look at the dry run first).

   ```bash
   python3 tools/sync.py --dry-run
   python3 tools/sync.py
   ```

5. Read `shared/CLAUDE.md` in the hub and make it yours: what needs your yes, which characters you never want
   in your writing (`steward.json` "banned_chars"), your send hours. Edit it in the hub, commit with
   `tools/hub_push.sh`, run `tools/sync.py` again.

6. Start your first lane. In Claude Code, ask: "Use the lane-brief skill to write a brief for a lane called
   inbox-zero that drafts replies to my unread mail and puts them on the board", then start a session with
   that brief and `/loop`.

7. See what needs you.

   ```bash
   python3 tools/board.py fold && cat board/BOARD.md
   python3 tools/lane.py --list
   python3 tools/lock.py list
   ```

## A second machine

Clone the same private hub on the second machine, run `python3 tools/sync.py`, and set the machine name
(`STEWARD_MACHINE=b`, or add a `hostname_contains` entry under "machines" in `steward.json`). Write the default
split in `docs/SPLIT.md`. Machines hand work to each other through `handoffs/REQUESTS.md` and the leases: the
giver releases, the receiver acquires and gets a new fencing token. Rules in `docs/RULES.md`.

## Self-improvement

`docs/CADENCE.md` and the prompts in `scheduled-tasks/` describe a daily, weekly and monthly pass that collects
your corrections, keeps your exact words in a memory note, and turns anything checkable into a test or a hook.
Register them as scheduled tasks in the Claude desktop app or any cron that can run `claude -p`.

## Honest limits

- This is coordination and guard rails, not an agent framework. The work is done by Claude Code sessions
  following their briefs; the kit makes them collide less, ask before sending, and remember corrections.
- Hooks see tool calls, not intent. A send through a shell script or a browser click is not gated by the
  outbound gate. Keep send-capable tools behind MCP where the gate sees them.
- Leases need network access to your git remote. Offline, `preflight` reads the last fetched state and says so.
- Nothing here moves money, signs in, or merges to production. That is on purpose.
- Keep the hub private. It will hold names, drafts and plans.

## Development

```bash
make check   # tests and the leak scan
make ship    # check, push main, smoke-test a fresh clone, revert if it fails
```

`scripts/leak_scan.py` checks for tokens, keys, real email addresses and phone numbers, runs gitleaks when it is
installed, and reads an optional private denylist from outside the repo (`~/.config/steward-hub/denylist.txt`)
so a fork can scan for its own names without committing them.

## License

MIT. Author: Kentaro Vadney.
