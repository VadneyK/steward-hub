#!/usr/bin/env python3
"""Leases on shared resources, stored in the hub repo and taken by a git push.

A lock is a lease on one resource key, stored as locks/<key>.json on the hub's remote branch. The push is the
compare-and-swap: the commit is built on the fetched tip with git plumbing (a temporary index, never the
working tree), so if another machine pushed first the push is rejected as non-fast-forward, and we re-read and
decide again. The earlier push wins. Nothing here stashes, merges or touches uncommitted files.

Leases expire (default 2h, plus 2 minutes of clock grace); the holder renews each pass. An expired lease may be
taken by anyone. Every acquire or takeover raises the key's fencing token by one, so a holder that slept past
its lease can tell, right before an irreversible step, that its token is no longer current.

Sends and submits also write one line to an append-only ledger (ledger/<date>-<machine>.jsonl, one file per
machine per day, so two machines never write the same file). Before any send or submit, `preflight` asks:
(1) is this resource locked by someone else, and (2) was it already sent or applied.

Usage:
  lock.py key "person:Ada Example <ada@example.com>"
  lock.py acquire KEY --session S [--ttl 2h] [--note TEXT]
  lock.py renew   KEY --session S [--token N]
  lock.py release KEY --session S [--token N] | --force --reason TEXT
  lock.py check   KEY [--session S] [--offline]
  lock.py list    [--all] [--offline]
  lock.py record  KEY --action send --ref <message id> [--idem K] [--note TEXT]
  lock.py preflight KEY --action send [--idem K] [--grep TEXT] [--session S] [--offline]
  lock.py dupes   (people with more than one open send entry across handoffs/board-inbox)

Key kinds: person:<email or name>, thread:<id>, role:<company>:<role>, lane:<name>, artifact:<id>, doc:<id>,
or any other kind:<value>.
Exit: 0 ok or clear; 1 held by someone else; 2 network or git error (nothing changed); 3 already sent or
applied (preflight) or not the holder (renew, release); 64 usage.

Machine name: STEWARD_MACHINE, else steward.json "machines" hostname match, else the short hostname.
Env: STEWARD_HUB (hub path), STEWARD_BRANCH (main), STEWARD_GH_USER (pin pushes to this gh login),
STEWARD_TZ (else steward.json "timezone", else UTC), STEWARD_NOW (tests).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

GRACE = 120
DEFAULT_TTL = 2 * 3600
MAX_TTL = 7 * 24 * 3600
TRIES = 6
LOCK_REF = "refs/steward-lock/main"  # private fetch ref, so a fetch here never moves origin/main
DONE_WORDS = re.compile(r"\b(SENT|SUBMITTED|APPLIED|DONE)\b")
KEEP_CASE = {"artifact", "doc"}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


# ---------- config ----------

def hub_dir() -> str:
    return os.environ.get("STEWARD_HUB") or str(Path(__file__).resolve().parent.parent)


def config(hub: str | None = None) -> dict:
    try:
        return json.loads(Path(hub or hub_dir(), "steward.json").read_text())
    except (OSError, ValueError):
        return {}


def tz():
    name = os.environ.get("STEWARD_TZ") or config().get("timezone") or "UTC"
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def this_machine(hub: str | None = None) -> str | None:
    env = (os.environ.get("STEWARD_MACHINE") or "").strip()
    if env:
        return _slug(env)
    host = socket.gethostname().lower()
    for name, spec in (config(hub).get("machines") or {}).items():
        for frag in (spec or {}).get("hostname_contains", []):
            if frag and frag.lower() in host:
                return _slug(name)
    short = host.split(".")[0]
    return _slug(short) if short else None


# ---------- keys ----------

def _slug(text: str) -> str:
    """NFKC plus casefold; Unicode letters and digits kept so names in any script stay distinct."""
    text = unicodedata.normalize("NFKC", text).strip().casefold()
    text = re.sub(r"[^\w@.+]+", "-", text)
    return text.strip("-.") or "x"


def _ascii_slug(text: str) -> str:
    text = re.sub(r"[^a-z0-9@._+]+", "-", text.strip().lower())
    return text.strip("-.") or "x"


def normalize_key(raw: str) -> str:
    """One spelling per resource, so every machine computes the same key."""
    raw = (raw or "").strip()
    if ":" not in raw:
        raise ValueError("a key is kind:value, for example person:ada@example.com or lane:taxes")
    kind, value = raw.split(":", 1)
    kind = _slug(kind).replace("@", "")
    value = value.strip()
    if not value:
        raise ValueError("empty key value")
    if kind == "person":
        m = EMAIL.search(value)
        return "person:" + (m.group(0).lower() if m else _slug(value))
    if kind == "thread":
        parts = [p.strip() for p in value.split(":") if p.strip()]
        if len(parts) == 1:
            parts = ["mail"] + parts
        return "thread:" + ":".join([_slug(parts[0])] + [p.lower() for p in parts[1:]])
    if kind in KEEP_CASE:
        return kind + ":" + re.sub(r"\s+", "", value)
    return kind + ":" + ":".join(_slug(p) for p in value.split(":") if p.strip())


def lock_path(key: str) -> str:
    """Readable, safe on a case-insensitive disk, unique (hash suffix)."""
    h = hashlib.sha1(key.encode()).hexdigest()[:8]
    return "locks/%s-%s.json" % (_ascii_slug(key.replace(":", "-"))[:60].strip("-."), h)


def idem_key(*parts: str) -> str:
    """Same recipient, subject and body (spacing and case ignored) give the same key."""
    norm = "\x1f".join(re.sub(r"\s+", " ", (p or "")).strip().lower() for p in parts)
    return hashlib.sha256(norm.encode()).hexdigest()[:16]


# ---------- git store ----------

class GitError(Exception):
    pass


class Store:
    def __init__(self, repo: str | None = None, branch: str | None = None):
        self.repo = repo or hub_dir()
        self.branch = branch or os.environ.get("STEWARD_BRANCH") or "main"
        self.base: str | None = None

    def git(self, *args: str, input: str | None = None, env: dict | None = None, check: bool = True):
        cmd = ["git"]
        user = os.environ.get("STEWARD_GH_USER")
        if user:
            cmd += ["-c", "credential.helper=",
                    "-c", 'credential.helper=!f(){ echo username=%s; echo "password=$(gh auth token -u %s)"; }; f'
                    % (user, user)]
        cmd += list(args)
        full_env = dict(os.environ)
        full_env.update(env or {})
        p = subprocess.run(cmd, cwd=self.repo, input=input, capture_output=True, text=True, env=full_env, timeout=60)
        if check and p.returncode != 0:
            raise GitError(p.stderr.strip() or p.stdout.strip() or "git %s failed" % args[0])
        return p

    def fetch(self) -> str:
        self.git("fetch", "-q", "origin", "+refs/heads/%s:%s" % (self.branch, LOCK_REF))
        self.base = self.git("rev-parse", LOCK_REF).stdout.strip()
        return self.base

    def offline_base(self) -> str | None:
        """Newest state already on disk, no network: the private ref or origin/<branch>, whichever is newer."""
        refs = []
        for ref in (LOCK_REF, "refs/remotes/origin/%s" % self.branch):
            p = self.git("rev-parse", "--verify", "-q", ref, check=False)
            if p.returncode == 0:
                refs.append(p.stdout.strip())
        if not refs:
            return None
        best = refs[0]
        for other in refs[1:]:
            if other != best and self.git("merge-base", "--is-ancestor", best, other, check=False).returncode == 0:
                best = other
        self.base = best
        return best

    def read(self, path: str) -> str | None:
        if not self.base:
            return None
        p = self.git("show", "%s:%s" % (self.base, path), check=False)
        return p.stdout if p.returncode == 0 else None

    def ls(self, folder: str) -> list:
        if not self.base:
            return []
        p = self.git("ls-tree", "--name-only", self.base, folder + "/", check=False)
        return [x for x in p.stdout.splitlines() if x]

    def write(self, files: dict, message: str) -> str:
        """Commit files on top of self.base and push. Returns 'ok' or 'lost' (someone pushed first)."""
        fd, index = tempfile.mkstemp(prefix="steward-lock-index-")
        os.close(fd)
        os.unlink(index)
        env = {"GIT_INDEX_FILE": index}
        try:
            self.git("read-tree", self.base, env=env)
            for path, text in files.items():
                blob = self.git("hash-object", "-w", "--stdin", input=text).stdout.strip()
                self.git("update-index", "--add", "--cacheinfo", "100644,%s,%s" % (blob, path), env=env)
            tree = self.git("write-tree", env=env).stdout.strip()
            commit = self.git("commit-tree", tree, "-p", self.base, "-m", message, env=env).stdout.strip()
        finally:
            if os.path.exists(index):
                os.unlink(index)
        p = self.git("push", "-q", "origin", "%s:refs/heads/%s" % (commit, self.branch), check=False)
        if p.returncode == 0:
            self.git("update-ref", LOCK_REF, commit, check=False)
            self.base = commit
            return "ok"
        err = (p.stderr or "") + (p.stdout or "")
        if re.search(r"rejected|non-fast-forward|fetch first|stale info", err):
            return "lost"
        raise GitError(err.strip() or "push failed")


# ---------- lease logic (pure, tested without git) ----------

def now() -> int:
    return int(os.environ.get("STEWARD_NOW") or time.time())


def fmt(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz()).strftime("%Y-%m-%d %H:%M %Z")
    except (TypeError, ValueError, OverflowError):
        return "?"


def parse_ttl(text) -> int:
    if text is None:
        return DEFAULT_TTL
    m = re.fullmatch(r"\s*(\d+)\s*([smhd]?)\s*", str(text).lower())
    if not m:
        raise ValueError("ttl like 90m, 2h, 1d or seconds")
    n = int(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]
    if n < 60 or n > MAX_TTL:
        raise ValueError("ttl must be between 1 minute and 7 days")
    return n


def is_live(lock: dict | None, at: int | None = None) -> bool:
    if not lock or lock.get("state") != "held":
        return False
    return (at if at is not None else now()) <= int(lock.get("expires", 0)) + GRACE


def same_holder(lock: dict, machine: str | None, session: str | None) -> bool:
    h = lock.get("holder") or {}
    if machine and h.get("machine") != machine:
        return False
    if session is not None and h.get("session") != session:
        return False
    return bool(machine) or session is not None


def describe(lock: dict) -> str:
    h = lock.get("holder") or {}
    s = "%s held by %s/%s, token %s, until %s" % (lock.get("key"), h.get("machine"), h.get("session"),
                                                    lock.get("token"), fmt(lock.get("expires")))
    if lock.get("note"):
        s += " (%s)" % lock["note"]
    return s


def decide_acquire(cur: dict | None, key: str, machine: str, session: str, ttl: int, note: str, at: int):
    """Returns (new_lock, None) or (None, reason). The same holder acquiring again is a renew."""
    if is_live(cur, at) and not same_holder(cur, machine, session):
        return None, "held: " + describe(cur)
    prev_token = int((cur or {}).get("token", 0))
    renew = is_live(cur, at) and same_holder(cur, machine, session)
    lock = {
        "key": key,
        "state": "held",
        "holder": {"machine": machine, "session": session},
        "token": prev_token if renew else prev_token + 1,
        "acquired": int(cur["acquired"]) if renew else at,
        "renewed": at,
        "expires": at + ttl,
        "ttl": ttl,
        "note": note or ((cur or {}).get("note", "") if renew else ""),
    }
    if cur and not renew:
        lock["previous"] = {"holder": cur.get("holder"), "token": cur.get("token"),
                            "state": "expired" if cur.get("state") == "held" else cur.get("state"),
                            "expires": cur.get("expires")}
    return lock, None


def decide_owner_change(cur: dict | None, machine: str, session: str, token, at: int, action: str, ttl=None,
                        force: bool = False, reason: str = ""):
    """renew or release by the holder (token must match when given). A forced release needs a reason."""
    if not cur or cur.get("state") != "held":
        return None, "not held"
    if not force:
        if not same_holder(cur, machine, session):
            return None, "not the holder: " + describe(cur)
        if token is not None and int(token) != int(cur.get("token", -1)):
            return None, "token %s is not current (current %s): a newer holder took it" % (token, cur.get("token"))
        if action == "renew" and not is_live(cur, at):
            return None, "lease expired at %s; acquire again" % fmt(cur.get("expires"))
    elif not reason:
        return None, "--force needs --reason"
    lock = dict(cur)
    if action == "renew":
        lock["renewed"] = at
        lock["expires"] = at + (ttl or int(cur.get("ttl") or DEFAULT_TTL))
    else:
        lock["state"] = "released"
        lock["released"] = at
        if force:
            lock["released_by"] = {"machine": machine, "session": session, "reason": reason}
    return lock, None


# ---------- operations ----------

def load(store: Store, key: str) -> dict | None:
    text = store.read(lock_path(key))
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _dump(obj) -> str:
    return json.dumps(obj, indent=1, sort_keys=True) + "\n"


def acquire(store: Store, key: str, machine: str, session: str, ttl: int = DEFAULT_TTL, note: str = ""):
    key = normalize_key(key)
    for _ in range(TRIES):
        store.fetch()
        cur = load(store, key)
        lock, why = decide_acquire(cur, key, machine, session, ttl, note, now())
        if not lock:
            return None, why
        verb = "renew" if cur and lock["token"] == cur.get("token") and cur.get("state") == "held" else "take"
        if store.write({lock_path(key): _dump(lock)},
                       "lock: %s %s %s token %s" % (machine, verb, key, lock["token"])) == "ok":
            return lock, None
    return None, "lost the push race %d times; try again next pass" % TRIES


def change(store: Store, key: str, machine: str, session: str, action: str, token=None, ttl=None,
           force: bool = False, reason: str = ""):
    key = normalize_key(key)
    for _ in range(TRIES):
        store.fetch()
        cur = load(store, key)
        lock, why = decide_owner_change(cur, machine, session, token, now(), action, ttl, force, reason)
        if not lock:
            return None, why
        msg = "lock: %s %s %s token %s%s" % (machine, action, key, lock.get("token"),
                                             " (force: %s)" % reason if force else "")
        if store.write({lock_path(key): _dump(lock)}, msg) == "ok":
            return lock, None
    return None, "lost the push race %d times; try again next pass" % TRIES


def all_locks(store: Store) -> list:
    out = []
    for path in store.ls("locks"):
        if not path.endswith(".json"):
            continue
        try:
            out.append(json.loads(store.read(path) or ""))
        except ValueError:
            continue
    return out


def ledger_path(machine: str, at: int) -> str:
    return "ledger/%s-%s.jsonl" % (datetime.fromtimestamp(at, tz()).strftime("%Y-%m-%d"), machine.lower())


def ledger_entries(store: Store) -> list:
    out = []
    for path in store.ls("ledger"):
        if not path.endswith(".jsonl"):
            continue
        for line in (store.read(path) or "").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def record(store: Store, key: str, machine: str, session: str, action: str, ref: str = "", idem: str = "",
           note: str = "", token=None):
    key = normalize_key(key)
    for _ in range(TRIES):
        store.fetch()
        at = now()
        path = ledger_path(machine, at)
        entry = {"ts": at, "time": fmt(at), "machine": machine, "session": session, "key": key, "action": action,
                 "ref": ref, "idem": idem, "note": note}
        if token is not None:
            entry["token"] = int(token)
        text = (store.read(path) or "") + json.dumps(entry, sort_keys=True) + "\n"
        if store.write({path: text}, "ledger: %s %s %s" % (machine, action, key)) == "ok":
            return entry
    raise GitError("lost the push race %d times" % TRIES)


def find_done(entries: list, key: str, action: str | None, idem: str = "") -> list:
    hits = []
    for e in entries:
        if idem and e.get("idem") == idem:
            hits.append(e)
        elif not idem and e.get("key") == key and (action is None or e.get("action") == action):
            hits.append(e)
    return hits


def _inbox_blocks(repo: str):
    for f in sorted(Path(repo, "handoffs/board-inbox").glob("*.md")):
        if f.name.lower() == "readme.md":
            continue
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for b in re.split(r"(?m)^(?=## )", text):
            if b.startswith("## "):
                yield f.name, b


def grep_inbox(repo: str, text: str) -> list:
    """Board-inbox entries whose heading says SENT, SUBMITTED, APPLIED or DONE and whose body mentions text."""
    if not text:
        return []
    needle = text.lower()
    hits = []
    for name, b in _inbox_blocks(repo):
        head = b.split("\n", 1)[0]
        if DONE_WORDS.search(head) and needle in b.lower():
            hits.append("%s: %s" % (name, head[3:].strip()[:140]))
    return hits


def preflight(store: Store, key: str, action: str, machine: str | None, session: str | None = None,
              idem: str = "", grep: str = "", offline: bool = False) -> dict:
    """The one check before every send or submit. status: clear | locked | done."""
    key = normalize_key(key)
    try:
        if offline:
            store.offline_base()
        else:
            store.fetch()
    except GitError:
        store.offline_base()
    res = {"key": key, "status": "clear", "lock": None, "done": [], "inbox": [], "stale_view": not store.base}
    cur = load(store, key)
    if is_live(cur) and not same_holder(cur, machine, session):
        res["status"] = "locked"
        res["lock"] = cur
    res["done"] = find_done(ledger_entries(store), key, action, idem)
    res["inbox"] = grep_inbox(store.repo, grep)
    if (res["done"] or res["inbox"]) and res["status"] == "clear":
        res["status"] = "done"
    return res


def open_send_dupes(repo: str) -> dict:
    """Recipients with more than one open send entry across the board inbox."""
    by_person: dict = {}
    for name, b in _inbox_blocks(repo):
        head = b.split("\n", 1)[0]
        parts = [p.strip() for p in head[3:].split("|")]
        if len(parts) < 4 or parts[1].lower() != "send":
            continue
        status = parts[3].split()[0].upper() if parts[3] else ""
        if status not in ("OPEN", "FOLDED", "DRAFT", "NEW", "HELD"):
            continue
        m = re.search(r"(?mi)^\s*To:\s*(.+)$", b)
        if not m:
            continue
        for e in EMAIL.findall(m.group(1)) or [m.group(1).strip()]:
            by_person.setdefault(normalize_key("person:" + e), []).append("%s: %s" % (name, parts[0]))
    return {k: v for k, v in by_person.items() if len(v) > 1}


# ---------- cli ----------

def main(argv: list) -> int:
    ap = argparse.ArgumentParser(prog="lock.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("key")
    p.add_argument("key")
    for name in ("acquire", "renew", "release", "check", "record", "preflight"):
        p = sub.add_parser(name)
        p.add_argument("key")
        p.add_argument("--machine")
        p.add_argument("--session", default=None, help="lane or session name; default STEWARD_SESSION or 'main'")
        p.add_argument("--json", action="store_true")
        if name in ("acquire", "renew"):
            p.add_argument("--ttl")
        if name == "acquire":
            p.add_argument("--note", default="")
        if name in ("renew", "release", "record"):
            p.add_argument("--token", type=int)
        if name == "release":
            p.add_argument("--force", action="store_true")
            p.add_argument("--reason", default="")
        if name in ("check", "preflight"):
            p.add_argument("--offline", action="store_true", help="read the last fetched state, no network")
        if name in ("record", "preflight"):
            p.add_argument("--action", required=True, help="send, submit, apply, post, publish")
            p.add_argument("--idem", default="")
        if name == "record":
            p.add_argument("--ref", default="", help="message id, application id or URL")
            p.add_argument("--note", default="")
        if name == "preflight":
            p.add_argument("--grep", default="", help="also look for SENT/APPLIED/DONE board-inbox entries naming this")
    p = sub.add_parser("list")
    p.add_argument("--all", action="store_true", help="include released and expired")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--json", action="store_true")
    sub.add_parser("dupes")
    args = ap.parse_args(argv)

    if not args.cmd:
        ap.print_help()
        return 64
    try:
        if args.cmd == "key":
            print(normalize_key(args.key))
            return 0
        store = Store()
        if args.cmd == "dupes":
            d = open_send_dupes(store.repo)
            for k, v in sorted(d.items()):
                print("%s has %d open send entries: %s" % (k, len(v), "; ".join(v)))
            if d:
                print("merge them into one message per person before folding")
            return 1 if d else 0
        if args.cmd == "list":
            store.offline_base() if args.offline else store.fetch()
            locks = [l for l in all_locks(store) if args.all or is_live(l)]
            if args.json:
                print(json.dumps(locks, indent=1))
                return 0
            for l in sorted(locks, key=lambda x: x.get("key", "")):
                state = "live" if is_live(l) else l.get("state") if l.get("state") != "held" else "expired"
                print("%-8s %s" % (state, describe(l)))
            if not locks:
                print("no live locks")
            return 0
        session = args.session or os.environ.get("STEWARD_SESSION") or "main"
        machine = _slug(args.machine) if args.machine else this_machine(store.repo)
        if not machine:
            print("cannot tell this machine; pass --machine or set STEWARD_MACHINE", file=sys.stderr)
            return 64
        if args.cmd == "acquire":
            lock, why = acquire(store, args.key, machine, session, parse_ttl(args.ttl), args.note)
            if not lock:
                print(why)
                return 1
            print("acquired %s token %s until %s" % (lock["key"], lock["token"], fmt(lock["expires"])))
            return 0
        if args.cmd in ("renew", "release"):
            lock, why = change(store, args.key, machine, session, args.cmd, getattr(args, "token", None),
                               parse_ttl(args.ttl) if getattr(args, "ttl", None) else None,
                               getattr(args, "force", False), getattr(args, "reason", ""))
            if not lock:
                print(why)
                return 3
            print("%sd %s token %s%s" % (args.cmd.rstrip("e"), lock["key"], lock["token"],
                                         " until " + fmt(lock["expires"]) if args.cmd == "renew" else ""))
            return 0
        if args.cmd == "check":
            store.offline_base() if args.offline else store.fetch()
            key = normalize_key(args.key)
            cur = load(store, key)
            if is_live(cur) and not same_holder(cur, machine, args.session):
                print(describe(cur))
                return 1
            print("%s: %s" % (key, "yours, " + describe(cur) if is_live(cur) else "free"))
            return 0
        if args.cmd == "record":
            e = record(store, args.key, machine, session, args.action, args.ref, args.idem, args.note, args.token)
            print("recorded %s %s at %s" % (e["action"], e["key"], e["time"]))
            return 0
        if args.cmd == "preflight":
            r = preflight(store, args.key, args.action, machine, args.session, args.idem, args.grep, args.offline)
            if args.json:
                print(json.dumps(r, indent=1))
            if r["lock"]:
                print("LOCKED: " + describe(r["lock"]))
            for e in r["done"]:
                print("ALREADY %s: %s by %s at %s ref %s" % (e.get("action", "").upper(), e.get("key"),
                                                          e.get("machine"), e.get("time"), e.get("ref")))
            for h in r["inbox"]:
                print("BOARD-INBOX says done: " + h)
            if r["stale_view"]:
                print("warning: no fetched hub state; result is from nothing")
            if r["status"] == "clear":
                print("clear: %s. Still check the Sent folder of the right account." % r["key"])
                return 0
            return 1 if r["status"] == "locked" else 3
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 64
    except GitError as e:
        print("git: %s (nothing changed)" % e, file=sys.stderr)
        return 2
    return 64


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
