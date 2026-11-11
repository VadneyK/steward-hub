#!/usr/bin/env python3
"""The board: one page of asks for the human, fed by every lane.

Lanes never edit the board itself (one writer). Each lane appends asks to its own file,
handoffs/board-inbox/<lane>.md, in the format in that folder's README. `fold` turns every OPEN entry into a card
on board/BOARD.md and marks the entry FOLDED, so nothing is shown twice and nothing is lost.

Usage:
  board.py add <lane> --kind send|decide|do --title TEXT [--why TEXT] [--p p1|p2|p3] [--body FILE]
  board.py list [--all]
  board.py fold
  board.py answer <id> TEXT     (write the human's answer under the entry, mark it ANSWERED)
  board.py done <id> [--ref TEXT]

Exit: 0 ok, 1 nothing found or a duplicate open send to the same person (fold refuses until merged), 64 usage.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lock  # noqa: E402

HEAD = re.compile(r"^## (?P<id>[^|]+?) \| (?P<kind>send|decide|do) \| (?P<p>p[123])[^|]*\| (?P<status>\S+)(?P<rest>.*)$")


def hub() -> Path:
    return Path(lock.hub_dir())


def inbox() -> Path:
    return hub() / "handoffs" / "board-inbox"


def stamp() -> str:
    return datetime.now(lock.tz()).strftime("%Y-%m-%d %H:%M %Z")


def entries():
    """Yield (file, start, end, match, block) for every entry, in file order."""
    for f in sorted(inbox().glob("*.md")):
        if f.name.lower() == "readme.md":
            continue
        text = f.read_text()
        starts = [m.start() for m in re.finditer(r"(?m)^## ", text)] + [len(text)]
        for a, b in zip(starts, starts[1:]):
            block = text[a:b]
            m = HEAD.match(block.split("\n", 1)[0])
            if m:
                yield f, a, b, m, block


def field(block: str, name: str) -> str:
    m = re.search(r"(?m)^%s:\s*(.*)$" % re.escape(name), block)
    return m.group(1).strip() if m else ""


def set_status(f: Path, entry_id: str, status: str, note: str = "") -> bool:
    text = f.read_text()
    pat = re.compile(r"(?m)^(## %s \| (?:send|decide|do) \| p[123][^|]*\| )\S+(.*)$" % re.escape(entry_id))
    m = pat.search(text)
    if not m:
        return False
    new = m.group(1) + status + m.group(2)
    end = text.find("\n## ", m.end())
    end = len(text) if end < 0 else end
    block = text[m.end():end]
    if note:
        block = block.rstrip("\n") + "\n" + note + "\n\n"
    f.write_text(text[:m.start()] + new + block + text[end:])
    return True


def next_id(lane: str) -> str:
    n = 0
    for _, _, _, m, _ in entries():
        mm = re.fullmatch(r"%s-(\d+)" % re.escape(lane), m.group("id").strip())
        if mm:
            n = max(n, int(mm.group(1)))
    return "%s-%d" % (lane, n + 1)


def cmd_add(a) -> int:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", a.lane):
        print("lane name: lower case letters, digits and hyphens")
        return 64
    inbox().mkdir(parents=True, exist_ok=True)
    f = inbox() / ("%s.md" % a.lane)
    eid = next_id(a.lane)
    lines = ["## %s | %s | %s | OPEN" % (eid, a.kind, a.p), "title: %s" % a.title]
    if a.why:
        lines.append("why: %s" % a.why)
    if a.kind == "send":
        if not a.body:
            print("a send ask needs --body FILE with To:, Subject: and the full text")
            return 64
        body = Path(a.body).read_text().rstrip("\n")
        lines.append("send:")
        lines += ["    " + l for l in body.splitlines()]
    with f.open("a") as fh:
        fh.write(("\n" if f.exists() and f.stat().st_size else "") + "\n".join(lines) + "\n")
    print(eid)
    return 0


def cmd_list(a) -> int:
    found = 0
    for f, _, _, m, block in entries():
        if not a.all and m.group("status") not in ("OPEN", "FOLDED", "HELD"):
            continue
        found += 1
        print("%-14s %-6s %s %-8s %s" % (m.group("id"), m.group("kind"), m.group("p"), m.group("status"),
                                         field(block, "title")))
    return 0 if found else 1


def cmd_fold(a) -> int:
    dupes = lock.open_send_dupes(str(hub()))
    if dupes:
        for k, v in sorted(dupes.items()):
            print("duplicate: %s has %d open sends: %s" % (k, len(v), "; ".join(v)))
        print("merge them into one message per person, then fold again")
        return 1
    board = hub() / "board" / "BOARD.md"
    board.parent.mkdir(exist_ok=True)
    cards = []
    folded = []
    for f, _, _, m, block in entries():
        if m.group("status") in ("OPEN", "FOLDED", "HELD"):
            body = block.split("\n", 1)[1] if "\n" in block else ""
            cards.append((m.group("p"), m.group("id").strip(), m.group("kind"), m.group("status"), body.strip()))
            if m.group("status") == "OPEN":
                folded.append((f, m.group("id").strip()))
    cards.sort()
    out = ["# Board", "", "Built %s. %d open asks." % (stamp(), len(cards)), ""]
    for p, eid, kind, status, body in cards:
        out += ["## %s %s (%s)%s" % (p, eid, kind, " HELD" if status == "HELD" else ""), "", body, ""]
    board.write_text("\n".join(out).rstrip() + "\n")
    for f, eid in folded:
        set_status(f, eid, "FOLDED " + stamp())
    print("board: %d cards, %d newly folded" % (len(cards), len(folded)))
    return 0


def _find(eid: str):
    for f, _, _, m, _ in entries():
        if m.group("id").strip() == eid:
            return f
    return None


def cmd_answer(a) -> int:
    f = _find(a.id)
    if not f:
        print("no entry %s" % a.id)
        return 1
    set_status(f, a.id, "ANSWERED", "answer, %s: %s" % (stamp(), a.text))
    print("answered %s" % a.id)
    return 0


def cmd_done(a) -> int:
    f = _find(a.id)
    if not f:
        print("no entry %s" % a.id)
        return 1
    set_status(f, a.id, "DONE " + stamp(), ("ref: %s" % a.ref) if a.ref else "")
    print("done %s" % a.id)
    return 0


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(prog="board.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("add")
    p.add_argument("lane")
    p.add_argument("--kind", choices=("send", "decide", "do"), required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--why", default="")
    p.add_argument("--p", choices=("p1", "p2", "p3"), default="p2")
    p.add_argument("--body")
    p = sub.add_parser("list")
    p.add_argument("--all", action="store_true")
    sub.add_parser("fold")
    p = sub.add_parser("answer")
    p.add_argument("id")
    p.add_argument("text")
    p = sub.add_parser("done")
    p.add_argument("id")
    p.add_argument("--ref", default="")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 64
    return {"add": cmd_add, "list": cmd_list, "fold": cmd_fold, "answer": cmd_answer, "done": cmd_done}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
