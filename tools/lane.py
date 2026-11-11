#!/usr/bin/env python3
"""Set one lane's state, stamp the time, rebuild status.json.

A lane is one area of work a Claude Code session runs on its own for hours (job search, taxes, a side project).
Each lane has a file lanes/<name>.md with a small header (name, machine, state, what, next, updated) and free
notes below it. status.json is rebuilt from the lane files after every change, so a board or a phone page can
read one file.

Usage:
  lane.py <name> <state> [--what TEXT] [--next TEXT] [--machine M] [--private]
  lane.py <name> --next TEXT          (keep the state, update next)
  lane.py --list [--active] [--mine M]

States: working, needs-you, waiting, blocked, done.
Locks: a claim (state working) takes the lease lane:<name> for this machine, and done releases it. A lane whose
live lease belongs to another machine is refused (exit 3) unless --force. --no-lock or STEWARD_LOCK_OFF=1 skips
the lease; a lock error only warns (the lane file is still written).
Private lanes keep only the state and the time in the hub; what and next stay out.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lock  # noqa: E402

STATES = ("working", "needs-you", "waiting", "blocked", "done")
FIELDS = ["name", "machine", "state", "private", "what", "next", "updated"]


def hub() -> Path:
    return Path(lock.hub_dir())


def stamp() -> str:
    return datetime.now(lock.tz()).strftime("%Y-%m-%d %H:%M %Z")


def read_lane(path: Path):
    """Header lines 'key: value' between two '---' lines, then the body."""
    text = path.read_text()
    data, body = {}, text
    m = re.match(r"\A---\n(.*?)\n---\n?(.*)\Z", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                data[k.strip()] = v.strip()
        body = m.group(2)
    return data, body


def write_lane(path: Path, data: dict, body: str) -> None:
    keys = [k for k in FIELDS if k in data] + [k for k in data if k not in FIELDS]
    head = "\n".join("%s: %s" % (k, str(data[k]).replace("\n", " ")) for k in keys)
    path.write_text("---\n%s\n---\n%s" % (head, body))


def load_lanes(root: Path | None = None) -> list:
    out = []
    for f in sorted((root or hub()).joinpath("lanes").glob("*.md")):
        data, _ = read_lane(f)
        data.setdefault("name", f.stem)
        out.append(data)
    return out


def build_status(root: Path | None = None) -> dict:
    root = root or hub()
    lanes = []
    for d in load_lanes(root):
        row = {k: d.get(k, "") for k in ("name", "machine", "state", "what", "next", "updated")}
        if d.get("private") == "yes":
            row["what"] = row["next"] = "private"
        lanes.append(row)
    status = {"built": stamp(), "lanes": lanes,
              "needs_you": [l["name"] for l in lanes if l["state"] == "needs-you"]}
    (root / "status.json").write_text(json.dumps(status, indent=1) + "\n")
    return status


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(prog="lane.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", nargs="?")
    ap.add_argument("state", nargs="?", choices=STATES)
    ap.add_argument("--what")
    ap.add_argument("--next")
    ap.add_argument("--machine")
    ap.add_argument("--private", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--active", action="store_true")
    ap.add_argument("--mine")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-lock", action="store_true")
    args = ap.parse_args(argv)

    if args.list:
        for l in load_lanes():
            if (args.active and l.get("state") == "done") or (args.mine and l.get("machine") != args.mine):
                continue
            print("%-10s %-20s %-9s %s" % (l.get("machine", ""), l["name"], l.get("state", ""), l.get("updated", "")))
        return 0
    if not args.name:
        ap.print_help()
        return 64
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", args.name):
        print("lane name: lower case letters, digits and hyphens")
        return 64

    lanes_dir = hub() / "lanes"
    lanes_dir.mkdir(exist_ok=True)
    path = lanes_dir / ("%s.md" % args.name)
    if path.exists():
        data, body = read_lane(path)
    else:
        if not args.state:
            print("no lane %s; to create it pass a state" % args.name)
            return 1
        data, body = {"name": args.name}, "\n## Notes\n"

    machine = lock._slug(args.machine) if args.machine else (data.get("machine") or lock.this_machine())
    use_lock = not (args.no_lock or os.environ.get("STEWARD_LOCK_OFF"))
    if use_lock and args.state == "working":
        try:
            got, why = lock.acquire(lock.Store(), "lane:" + args.name, machine, args.name,
                                    lock.DEFAULT_TTL * 4, "lane claim")
            if got:
                print("lock: lane:%s token %s until %s" % (args.name, got["token"], lock.fmt(got["expires"])))
            elif str(why).startswith("held") and not args.force:
                print("refused: %s. The earlier claim wins; --force only after a release" % why)
                return 3
            else:
                print("lock: %s" % why)
        except Exception as e:  # never block a lane update on the lock store
            print("lock warning: %s" % e)

    if args.private:
        data["private"] = "yes"
    private = data.get("private") == "yes"
    if private and (args.what or args.next):
        print("private lane: only the state and the time go in the hub")
        return 64
    data["machine"] = machine or ""
    for key in ("state", "what", "next"):
        value = getattr(args, key)
        if value is not None:
            data[key] = value
    data["updated"] = stamp()
    write_lane(path, data, body)
    print("%s: %s, stamped %s" % (args.name, data.get("state"), data["updated"]))
    build_status()

    if use_lock and args.state == "done":
        try:
            got, _ = lock.change(lock.Store(), "lane:" + args.name, machine, args.name, "release")
            if got:
                print("lock: released lane:%s" % args.name)
        except Exception as e:
            print("lock warning: %s" % e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
