"""Shared helper for the steward hooks: find the hub and load its tools. Never raises."""
import importlib.util
import json
import os
from pathlib import Path


def hub_path():
    env = os.environ.get("STEWARD_HUB")
    if env:
        return Path(env).expanduser()
    f = Path.home() / ".claude" / "steward" / "hub"
    try:
        return Path(f.read_text().strip()).expanduser()
    except OSError:
        return None


def load_tool(name):
    hub = hub_path()
    if not hub:
        return None
    path = hub / "tools" / (name + ".py")
    if not path.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location("steward_" + name, str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def banned_chars():
    hub = hub_path()
    if not hub:
        return []
    try:
        cfg = json.loads((hub / "steward.json").read_text())
    except (OSError, ValueError):
        return []
    out = []
    for c in cfg.get("banned_chars") or []:
        c = c.encode().decode("unicode_escape") if c.startswith("\\u") else c
        if c:
            out.append(c)
    return out
