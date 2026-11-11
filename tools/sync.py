#!/usr/bin/env python3
"""Install the hub's shared/ config into ~/.claude on this machine. Run it on every machine after a pull.

    python3 tools/sync.py [--dry-run] [--if-changed]

What it installs (source under <hub>/shared/, target under ~/.claude):
  CLAUDE.md                  -> the block between STEWARD markers in ~/.claude/CLAUDE.md (rest of the file kept)
  skills/<name>/...          -> ~/.claude/skills/<name>/...
  hooks/*                    -> ~/.claude/hooks/steward/
  hooks/settings.hooks.json  -> missing hook entries merged into ~/.claude/settings.json (never removes one)
  and writes ~/.claude/steward/hub (this hub's path, so the hooks can find it)

Safety:
  - Every file it overwrites is copied first to ~/.claude/steward/backup/<stamp>/.
  - It never deletes a file.
  - A manifest records the hash of each file it installed. If a local file changed since the last install,
    the shared copy goes beside it as <file>.from-shared and the run prints CONFLICT instead of overwriting
    your local edit. Edit in the hub, not in ~/.claude.
  - --dry-run prints the plan and writes nothing.
  - --if-changed exits at once when shared/ is unchanged since the last run and that run is under 7 days old.
Env: CLAUDE_HOME overrides ~/.claude (tests).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

HUB = Path(os.environ.get("STEWARD_HUB") or Path(__file__).resolve().parent.parent)
SHARED = HUB / "shared"
CL = Path(os.environ.get("CLAUDE_HOME") or Path.home() / ".claude")
STATE = CL / "steward"
MANIFEST = STATE / "sync-manifest.json"
STAMP_FILE = STATE / "sync-stamp.json"
BEGIN = "<!-- STEWARD BEGIN: installed from the hub's shared/CLAUDE.md by tools/sync.py; edit it there -->"
END = "<!-- STEWARD END -->"
SKIP = {".DS_Store", "__pycache__", "node_modules"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and not (set(p.parts) & SKIP):
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


class Sync:
    def __init__(self, dry: bool):
        self.dry = dry
        self.stamp = time.strftime("%Y%m%d-%H%M%S")
        self.backup = STATE / "backup" / self.stamp
        try:
            self.old = json.loads(MANIFEST.read_text())
        except (OSError, ValueError):
            self.old = {}
        self.new = dict(self.old)
        self.counts = {"added": 0, "updated": 0, "same": 0, "conflict": 0}

    def say(self, s: str) -> None:
        print(("[dry-run] " if self.dry else "") + s)

    def put(self, target: Path, data: bytes) -> None:
        key = str(target)
        if target.exists():
            cur = target.read_bytes()
            if cur == data:
                self.counts["same"] += 1
                self.new[key] = sha(data)
                return
            if key in self.old and self.old[key] != sha(cur):
                self.counts["conflict"] += 1
                self.say("CONFLICT %s changed locally; shared copy written beside it as .from-shared" % target)
                if not self.dry:
                    Path(key + ".from-shared").write_bytes(data)
                return
            self.counts["updated"] += 1
            self.say("update %s" % target)
            if not self.dry:
                dest = self.backup / target.relative_to(CL)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, dest)
        else:
            self.counts["added"] += 1
            self.say("add %s" % target)
        if not self.dry:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            if target.suffix in (".py", ".sh"):
                target.chmod(0o755)
        self.new[key] = sha(data)

    def copy_tree(self, src: Path, dst: Path) -> None:
        if not src.is_dir():
            return
        for p in sorted(src.rglob("*")):
            if p.is_file() and not (set(p.parts) & SKIP) and p.name != "settings.hooks.json":
                self.put(dst / p.relative_to(src), p.read_bytes())

    def claude_md(self) -> None:
        src = SHARED / "CLAUDE.md"
        if not src.exists():
            return
        block = "%s\n%s\n%s\n" % (BEGIN, src.read_text().rstrip("\n"), END)
        target = CL / "CLAUDE.md"
        cur = target.read_text() if target.exists() else ""
        if BEGIN in cur and END in cur:
            a = cur.index(BEGIN)
            b = cur.index(END) + len(END)
            new = cur[:a] + block.rstrip("\n") + cur[b:]
        else:
            new = (cur.rstrip("\n") + "\n\n" if cur.strip() else "") + block
        if new == cur:
            self.counts["same"] += 1
            return
        self.counts["updated" if cur else "added"] += 1
        self.say("%s steward block in %s" % ("update" if BEGIN in cur else "add", target))
        if not self.dry:
            if cur:
                dest = self.backup / "CLAUDE.md"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(cur)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(new)

    def settings(self) -> None:
        src = SHARED / "hooks" / "settings.hooks.json"
        if not src.exists():
            return
        want = json.loads(src.read_text()).get("hooks", {})
        target = CL / "settings.json"
        try:
            cur = json.loads(target.read_text()) if target.exists() else {}
        except ValueError:
            self.say("CONFLICT %s is not valid JSON; hooks not merged" % target)
            self.counts["conflict"] += 1
            return
        hooks = cur.setdefault("hooks", {})
        added = 0
        for event, groups in want.items():
            have = hooks.setdefault(event, [])
            have_cmds = {h.get("command") for g in have for h in g.get("hooks", [])}
            for g in groups:
                missing = [h for h in g.get("hooks", []) if h.get("command") not in have_cmds]
                if missing:
                    have.append(dict(g, hooks=missing))
                    added += len(missing)
        if not added:
            return
        self.counts["updated"] += 1
        self.say("merge %d hook entries into %s" % (added, target))
        if not self.dry:
            if target.exists():
                dest = self.backup / "settings.json"
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, dest)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(cur, indent=2) + "\n")

    def run(self) -> int:
        self.claude_md()
        self.copy_tree(SHARED / "skills", CL / "skills")
        self.copy_tree(SHARED / "hooks", CL / "hooks" / "steward")
        self.settings()
        self.put(STATE / "hub", (str(HUB) + "\n").encode())
        if not self.dry:
            STATE.mkdir(parents=True, exist_ok=True)
            MANIFEST.write_text(json.dumps(self.new, indent=1, sort_keys=True) + "\n")
            STAMP_FILE.write_text(json.dumps({"hash": tree_hash(SHARED) if SHARED.exists() else "",
                                              "at": int(time.time())}) + "\n")
        c = self.counts
        print("sync: %d added, %d updated, %d same, %d conflict%s" % (
            c["added"], c["updated"], c["same"], c["conflict"], " (dry run, nothing written)" if self.dry else ""))
        return 1 if c["conflict"] else 0


def main(argv: list) -> int:
    if "--if-changed" in argv and SHARED.exists():
        try:
            st = json.loads(STAMP_FILE.read_text())
            if st.get("hash") == tree_hash(SHARED) and time.time() - st.get("at", 0) < 7 * 86400:
                print("sync: shared/ unchanged, nothing to do")
                return 0
        except (OSError, ValueError):
            pass
    return Sync("--dry-run" in argv).run()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
