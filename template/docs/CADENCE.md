# Self-improvement cadence

The steward gets better from the owner's corrections, not from grading itself. Two findings shape this: agents
use raw examples far better than condensed lessons, and self-critique without an outside signal does not help.
So every lesson keeps the owner's exact words, and anything a script can check becomes a test or a hook.

| Cadence | Suggested time | What it does | Output |
|---|---|---|---|
| Daily | evening | Collect every correction the owner gave today (typed messages, artifact comments, board answers). For each one not already covered: write one memory note with the exact quote and what was wrong; if checkable, add a test or a hook rule. Exit in one line on a quiet day. | `log/self-improve/<date>-daily.md` |
| Weekly | end of week | Friction scan of the week's transcripts: top tool errors, hook blocks, loops that died, permission prompts. Merge duplicate memories without shortening away quotes. Every second week, ship one skill or hook change for the top friction, with a test on past cases. | `log/self-improve/<date>-weekly.md` |
| Monthly | first of the month | Judgment pass against the standing rules: where the steward overstated, promised for the owner, contacted people too often, or made the owner do manual work. Retire dead rules. At most three asks for the owner, on one board card. Changes to standing rules are proposed there and made in `shared/CLAUDE.md` only after a yes. | `log/self-improve/<YYYY-MM>-monthly.md` |

Prompts for these jobs: `scheduled-tasks/`. Register them with the Claude desktop app's scheduled tasks or any
cron that can start `claude -p`. Scheduled tasks run only while the app is open; a missed run happens at next
launch.

Cost rules: one task per cadence; the daily job exits after a cheap collector pass when nothing was found;
private content (health, money, family) never goes into the hub log, only "private: memory <name>".
