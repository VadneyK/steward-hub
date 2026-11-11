#!/bin/bash
# Create a new private hub from this kit.
#   ./init.sh ~/my-hub [--machine NAME] [--tz Area/City]
# Copies tools/, the hub template, and the shared skills and hooks into a new git repo. It does not push
# anywhere and does not touch ~/.claude; run `python3 tools/sync.py` inside the hub for that.
set -eu
kit=$(cd "$(dirname "$0")" && pwd)
dest=${1:-}
[ -n "$dest" ] || { echo "usage: ./init.sh <new hub folder> [--machine NAME] [--tz Area/City]" >&2; exit 64; }
shift
machine=$(hostname -s | tr 'A-Z' 'a-z')
tzname=UTC
while [ $# -gt 0 ]; do
  case "$1" in
    --machine) machine=$2; shift 2;;
    --tz) tzname=$2; shift 2;;
    *) echo "unknown option $1" >&2; exit 64;;
  esac
done
if [ -e "$dest" ] && [ -n "$(ls -A "$dest" 2>/dev/null)" ]; then
  echo "init: $dest exists and is not empty; pick a new folder" >&2; exit 1
fi
mkdir -p "$dest"
cp -R "$kit/template/." "$dest/"
mkdir -p "$dest/tools" "$dest/shared/hooks" "$dest/shared/skills"
cp "$kit"/tools/*.py "$kit"/tools/*.sh "$dest/tools/"
cp "$kit"/hooks/*.py "$kit"/hooks/settings.hooks.json "$dest/shared/hooks/"
cp -R "$kit/skills/." "$dest/shared/skills/"
cp "$kit/template/shared-CLAUDE.md" "$dest/shared/CLAUDE.md" && rm -f "$dest/shared-CLAUDE.md"
python3 - "$dest/steward.json" "$machine" "$tzname" <<'PY'
import json, sys
path, machine, tz = sys.argv[1:]
cfg = json.load(open(path))
cfg["timezone"] = tz
cfg["machines"] = {machine: {"hostname_contains": [machine]}}
json.dump(cfg, open(path, "w"), indent=1)
open(path, "a").write("\n")
PY
cd "$dest"
git init -q -b main
git add -A
git commit -q -m "hub: start from steward-hub kit"
echo "hub ready at $dest"
echo "next: create an EMPTY PRIVATE remote, then:"
echo "  cd $dest && git remote add origin <private repo url> && git push -u origin main"
echo "  python3 tools/sync.py --dry-run && python3 tools/sync.py"
