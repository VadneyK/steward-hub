---
name: values-check
description: Check a draft the owner will send or post, and any money step, against the owner's own written values before it reaches them. Returns at most a short note, a suggested rewrite in their voice, and one thing to learn, or nothing. Use before putting any send on the board and before preparing any purchase, subscription or transfer.
---

# Values check

The owner's values live in `principles.md` beside this file. Out of the box it holds a short, neutral set.
Replace it with your own. An optional faith-based example pack ships in the kit under `examples/`.

This check adds to Claude's built-in safety rules and every standing rule. It never replaces them. It guides
and never blocks: the owner decides and can always send their original.

## What it returns

At most three lines, or nothing:

```
Note: <what to change and why, naming the principle>
Rewrite: <the full suggested text, in the owner's voice>
Learn: <one line to carry to the next message>
```

- If nothing needs changing, say nothing. Most drafts pass.
- One issue per draft: the one that matters most.
- Never change the meaning: same facts, same ask, same length or shorter.
- The note is for the owner only. It never goes to the recipient.
