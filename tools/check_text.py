#!/usr/bin/env python3
"""Fail when a file contains a character you never want in your writing.

The list lives in steward.json as "banned_chars" (each entry a single character or a \\uXXXX escape).
Example: ["\\u2014"] bans the em dash, a common tell of model-written text.

Usage: check_text.py FILE [FILE...]      exit 0 clean, 1 hits (printed as path:line), 64 usage
       check_text.py --stdin              read text from stdin
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lock  # noqa: E402


def banned() -> list:
    out = []
    for c in lock.config().get("banned_chars") or []:
        c = c.encode().decode("unicode_escape") if c.startswith("\\u") else c
        if c:
            out.append(c)
    return out


def hits(text: str, chars: list) -> list:
    return [(n, c) for n, line in enumerate(text.splitlines(), 1) for c in chars if c in line]


def main(argv: list) -> int:
    chars = banned()
    if not argv:
        print(__doc__)
        return 64
    bad = 0
    if argv == ["--stdin"]:
        for n, c in hits(sys.stdin.read(), chars):
            print("stdin:%d: banned character U+%04X" % (n, ord(c)))
            bad = 1
        return bad
    for p in argv:
        try:
            text = Path(p).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for n, c in hits(text, chars):
            print("%s:%d: banned character U+%04X" % (p, n, ord(c)))
            bad = 1
    return bad


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
