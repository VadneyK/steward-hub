#!/usr/bin/env python3
"""Ship guard: on repos that opted in, `make ship` is the only release path.

Blocks `gh pr merge`, a `git push` to main, master, staging, prod or production, and a few hand deploy commands
on any repo listed (owner/name, one per line) in ~/.claude/steward/ship-repos.txt. Commands that run
`make ship` or `make check` pass. Repos not in the list are never touched.
Add your own deploy commands with STEWARD_DEPLOY_RE (a regex).
"""
import json
import os
import re
import subprocess
import sys

LIST = os.path.expanduser(os.environ.get("STEWARD_SHIP_REPOS", "~/.claude/steward/ship-repos.txt"))
DEPLOY = os.environ.get("STEWARD_DEPLOY_RE", r"\bfirebase\s+deploy\b|\bvercel\s+--prod\b|\bfly\s+deploy\b|\bnetlify\s+deploy\b[^;&|]*--prod")


def repos():
    try:
        return {l.strip().lower() for l in open(LIST) if l.strip() and not l.startswith("#")}
    except OSError:
        return set()


def target_repo(cmd, cwd):
    m = re.search(r"(?:--repo|-R)[ =]+['\"]?([\w.-]+/[\w.-]+)", cmd)
    if m:
        return m.group(1).lower()
    try:
        url = subprocess.run(["git", "-C", cwd, "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=3).stdout.strip()
    except Exception:
        return ""
    m = re.search(r"[:/]([\w.-]+/[\w.-]+?)(?:\.git)?$", url)
    return m.group(1).lower() if m else ""


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    cmd = (data.get("tool_input") or {}).get("command", "") or ""
    cwd = data.get("cwd") or os.getcwd()
    if re.search(r"(^|[;&|]\s*)make\s+(ship|check)\b", cmd):
        return 0
    risky = (re.search(r"\bgh\s+pr\s+merge\b", cmd)
             or re.search(r"\bgit\s+push\b[^;&|]*\b(main|master|staging|prod|production)\b", cmd)
             or re.search(DEPLOY, cmd))
    if not risky:
        return 0
    repo = target_repo(cmd, cwd)
    if repo and repo in repos():
        sys.stderr.write("BLOCKED by ship-guard: %s releases only through `make ship` (tests, merge, deploy, "
                         "smoke test, rollback). Run `make ship` in the repo instead.\n" % repo)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
