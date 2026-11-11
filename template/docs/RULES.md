# Stewardship rules

How sessions share one person's digital life across lanes and machines. These add to `shared/CLAUDE.md` and
never loosen it.

## 1. Who owns what

A default split lives in `docs/SPLIT.md` (which machine runs which lanes). A lease beats the default: whoever
holds the live lease owns the resource until it is released or expires.

## 2. Locks: claim before work, check before acting

| When | Do |
|---|---|
| Starting work on anything another machine could touch | `lock.py acquire <key> --session <lane> --ttl 2h --note "what"`. Exit 1: held, leave it or ask in `handoffs/REQUESTS.md` |
| Each pass while working | `lock.py renew <key> --session <lane>`. A lane claim takes `lane:<name>` for 8 hours |
| Finished or handing over | `lock.py release <key> --session <lane>`. `lane.py <name> done` releases `lane:<name>` |
| Before any send, submit, apply or post | `lock.py preflight <key> --action send --grep <address>`. 0 clear, 1 held elsewhere, 3 already done |
| Right after it went out | `lock.py record <key> --action send --ref <id>` (the outbound gate does this for MCP sends) |
| A lease is stuck and its holder is gone | Wait for expiry (plus 2 minutes grace), then acquire. `release --force --reason` only when the holder agreed |

Keys, one spelling per resource (`lock.py key "<anything>"` prints it): `person:<email>`, `thread:<id>`,
`role:<company>:<role>`, `lane:<name>`, `artifact:<id>`, `doc:<id>`. Lock the person, not only the thread.

## 3. Already done (idempotency)

- The ledger (`ledger/<date>-<machine>.jsonl`, append only, one file per machine per day) records what went out.
- Check the real Sent folder too. A search by sender can match drafts that never went.
- Count applications and sends by ledger records, never by entry numbers.

## 4. Handing work across machines

1. The giver releases the lease (or lets it expire) and writes one line in `handoffs/REQUESTS.md`.
2. The receiver acquires the key, which gives a new fencing token, and confirms under that line.
3. Never work a key you do not hold, even if a note says it is yours.

## 5. What needs the owner (never automatic)

Every send, post or submit (their yes on the exact text); production merges and deploys; money; passwords,
sign-ins, IDs and CAPTCHAs; work about people and judgment (interview first). A lock never grants permission
to send. It only says who may prepare the send.

## 6. What a lane does without asking

Take, renew and release leases. Read, research, draft into its board-inbox file. Run preflight. Record what
went out after the owner's yes. Commit with `tools/hub_push.sh`.
