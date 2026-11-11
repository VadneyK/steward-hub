#!/bin/bash
# Push main, then clone the remote fresh and run the tests there. If that smoke test fails, push a revert.
# The smoke clone goes in a new temp folder that the OS clears; nothing is deleted here.
set -eu
git fetch -q origin
old=$(git rev-parse origin/main 2>/dev/null || echo "")
git push -q origin main
tmp=$(mktemp -d)
url=$(git remote get-url origin)
if git clone -q "$url" "$tmp/smoke" && (cd "$tmp/smoke" && python3 -m unittest discover -s tests >/dev/null 2>&1); then
  echo "ship: pushed $(git rev-parse --short HEAD), fresh clone passes"
  exit 0
fi
echo "ship: smoke test failed on a fresh clone" >&2
if [ -n "$old" ]; then
  git revert --no-edit "$old..HEAD"
  git push -q origin main
  echo "ship: reverted to the tree of $old and pushed the revert" >&2
fi
exit 1
