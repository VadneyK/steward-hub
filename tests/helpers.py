"""Test helpers: a throwaway hub with a local bare repo as its origin, one clone per machine."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


class Hub:
    """origin.git plus clones a and b, both initialised from the kit with init.sh."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="steward-test-"))
        self.origin = self.root / "origin.git"
        git(self.root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.a = self.root / "a"
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        subprocess.run(["bash", str(KIT / "init.sh"), str(self.a), "--machine", "a"], check=True,
                       capture_output=True, env=env)
        self._ident(self.a)
        git(self.a, "remote", "add", "origin", str(self.origin))
        git(self.a, "push", "-q", "-u", "origin", "main")
        self.b = self.root / "b"
        git(self.root, "clone", "-q", str(self.origin), str(self.b))
        self._ident(self.b)

    @staticmethod
    def _ident(path):
        git(path, "config", "user.name", "t")
        git(path, "config", "user.email", "t@example.com")

    def env(self, clone: Path, machine: str, **extra) -> dict:
        e = dict(os.environ, STEWARD_HUB=str(clone), STEWARD_MACHINE=machine, STEWARD_TZ="UTC")
        e.pop("STEWARD_GH_USER", None)
        e.update({k: str(v) for k, v in extra.items()})
        return e

    def run(self, clone: Path, machine: str, *args, **extra):
        tool = clone / "tools" / args[0]
        cmd = (["bash", str(tool)] if args[0].endswith(".sh") else ["python3", str(tool)]) + list(args[1:])
        return subprocess.run(cmd, cwd=clone, capture_output=True, text=True, env=self.env(clone, machine, **extra))

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)
