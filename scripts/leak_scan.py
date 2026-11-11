#!/usr/bin/env python3
"""Leak scan for this repo: secrets, personal data patterns, and an optional private denylist.

    python3 scripts/leak_scan.py [--denylist FILE]

1. Secret patterns (tokens, keys, private keys) in every tracked or untracked-not-ignored file.
2. Email addresses other than example.com, example.org and GitHub noreply.
3. Phone-number shapes.
4. Characters listed in template/steward.json "banned_chars".
5. A private denylist, one regex per line, kept OUTSIDE the repo (default ~/.config/steward-hub/denylist.txt,
   or STEWARD_DENYLIST). Put your own name, employer, family names and machine names there. Allowed hits
   are listed in scripts/leak_allow.txt as <file>:<regex> (for example the author line in LICENSE).
6. gitleaks, when it is installed (`gitleaks dir` on the tree and `gitleaks git` on the history).
Exit 0 clean, 1 findings.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = {
    "github token": r"\bgh[pousr]_[A-Za-z0-9]{30,}",
    "anthropic key": r"\bsk-ant-[A-Za-z0-9_-]{20,}",
    "openai key": r"\bsk-[A-Za-z0-9]{32,}",
    "aws key": r"\bAKIA[0-9A-Z]{16}\b",
    "google key": r"\bAIza[0-9A-Za-z_-]{35}\b",
    "slack token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "bearer": r"(?i)authorization:\s*bearer\s+[A-Za-z0-9._-]{20,}",
}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
OK_DOMAINS = {"example.com", "example.org", "users.noreply.github.com"}
PHONE = re.compile(r"(?<![\w.])(\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?![\w.])")


def files():
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True,
                         text=True).stdout.split("\n")
    return [ROOT / f for f in out if f and (ROOT / f).is_file()]


def main(argv):
    deny_path = Path(os.environ.get("STEWARD_DENYLIST") or Path.home() / ".config/steward-hub/denylist.txt")
    if "--denylist" in argv:
        deny_path = Path(argv[argv.index("--denylist") + 1])
    deny = []
    if deny_path.exists():
        deny = [l.strip() for l in deny_path.read_text().splitlines() if l.strip() and not l.startswith("#")]
    allow = []
    allow_file = ROOT / "scripts/leak_allow.txt"
    if allow_file.exists():
        for l in allow_file.read_text().splitlines():
            if l.strip() and not l.startswith("#") and ":" in l:
                f, rx = l.split(":", 1)
                allow.append((f.strip(), rx.strip()))
    banned = []
    try:
        for c in json.loads((ROOT / "template/steward.json").read_text()).get("banned_chars", []):
            banned.append(c.encode().decode("unicode_escape") if c.startswith("\\u") else c)
    except (OSError, ValueError):
        pass

    findings = []
    for p in files():
        rel = str(p.relative_to(ROOT))
        if rel == "scripts/leak_allow.txt":
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for name, rx in SECRETS.items():
                if re.search(rx, line):
                    findings.append("%s:%d: %s" % (rel, n, name))
            for m in EMAIL.finditer(line):
                if m.group(1).lower() not in OK_DOMAINS:
                    findings.append("%s:%d: email %s" % (rel, n, m.group(0)))
            if PHONE.search(line):
                findings.append("%s:%d: phone-like number" % (rel, n))
            for c in banned:
                if c in line and rel != "template/steward.json":
                    findings.append("%s:%d: banned character U+%04X" % (rel, n, ord(c)))
            for rx in deny:
                if re.search(rx, line, re.I) and not any(f == rel and re.search(a, line, re.I) for f, a in allow):
                    findings.append("%s:%d: denylist /%s/" % (rel, n, rx))
    print("leak scan: %d files, %d denylist terms (%s), %d findings" % (
        len(files()), len(deny), deny_path if deny else "no denylist found", len(findings)))
    for f in findings:
        print("  " + f)

    gl = shutil.which("gitleaks")
    if gl:
        for args in (["dir", str(ROOT)], ["git", str(ROOT)]):
            r = subprocess.run([gl, *args, "--no-banner", "--redact", "-v"], capture_output=True, text=True)
            tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
            print("gitleaks %s: %s" % (args[0], tail[0]))
            if r.returncode != 0:
                findings.append("gitleaks %s found leaks" % args[0])
                print(r.stdout[-3000:])
    else:
        print("gitleaks: not installed, skipped (brew install gitleaks)")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
