#!/bin/bash
# Commit named paths in a hub checkout that several sessions share, and get them onto origin:
# no stash, no force, never touching other sessions' uncommitted files.
# Usage: hub_push.sh -m "message" path [path...]
# Exit: 0 pushed; 2 network, commit stays local; 3 conflict (commit stays local, tree as it was);
# 4 checkout is mid merge or rebase, nothing done; 5 banned character in a named path, nothing committed; 64 usage.
# Env: STEWARD_GH_USER pins the push to that gh login.
set -u
msg=""
[ "${1:-}" = "-m" ] && { msg=${2:-}; shift 2; }
[ -n "$msg" ] && [ $# -gt 0 ] || { echo "usage: hub_push.sh -m message path [path...]" >&2; exit 64; }
cd "$(git rev-parse --show-toplevel)" || exit 64
here=$(cd "$(dirname "$0")" && pwd)

CRED=()
if [ -n "${STEWARD_GH_USER:-}" ]; then
  CRED=(-c credential.helper= -c "credential.helper=!f(){ echo username=$STEWARD_GH_USER; echo \"password=\$(gh auth token -u $STEWARD_GH_USER)\"; }; f")
fi
G() { if [ ${#CRED[@]} -gt 0 ]; then git "${CRED[@]}" "$@"; else git "$@"; fi; }

midway() {
  [ -e "$(git rev-parse --git-path MERGE_HEAD)" ] || [ -d "$(git rev-parse --git-path rebase-merge)" ] || [ -d "$(git rev-parse --git-path rebase-apply)" ]
}
midway && { echo "hub_push: checkout is mid merge or rebase, not touching it" >&2; exit 4; }

if [ -f "$here/check_text.py" ]; then
  STEWARD_HUB="$(pwd)" python3 "$here/check_text.py" "$@" || exit 5
fi

git add -- "$@" || exit 64
if ! git diff --cached --quiet -- "$@"; then
  git commit -q -m "$msg" -- "$@" || exit 64
fi

only_generated_conflicts() {
  local f any=1
  while IFS= read -r f; do
    any=0
    case "$f" in status.json) ;; *) return 1;; esac
  done < <(git diff --name-only --diff-filter=U)
  return $any
}

sync_merge() {
  git merge -q --no-edit "origin/$branch" 2>/dev/null && return 0
  if [ -e "$(git rev-parse --git-path MERGE_HEAD)" ]; then
    if only_generated_conflicts; then
      git checkout -q --theirs status.json 2>/dev/null && git add status.json 2>/dev/null
      git commit -q --no-edit && return 0
    fi
    git merge --abort
  fi
  return 1
}

sync_rebase() {
  git rebase -q "origin/$branch" 2>/dev/null && return 0
  while [ -d "$(git rev-parse --git-path rebase-merge)" ] || [ -d "$(git rev-parse --git-path rebase-apply)" ]; do
    if only_generated_conflicts; then
      git checkout -q --ours status.json 2>/dev/null && git add status.json 2>/dev/null
      GIT_EDITOR=true git rebase --continue >/dev/null 2>&1 && continue
      [ -n "$(git diff --name-only --diff-filter=U)" ] && continue
      GIT_EDITOR=true git rebase --skip >/dev/null 2>&1 && continue
    fi
    git rebase --abort
    return 1
  done
  return 0
}

branch=$(git symbolic-ref --short HEAD) || exit 64
for try in 1 2 3 4; do
  if ! G fetch -q origin "$branch" 2>/dev/null; then
    sleep $((try * 2)); continue
  fi
  git update-ref "refs/remotes/origin/$branch" FETCH_HEAD
  if ! git merge-base --is-ancestor "origin/$branch" HEAD; then
    git checkout -q -- status.json 2>/dev/null && rebuilt=1
    if git diff --quiet && git diff --cached --quiet; then
      sync_rebase || { echo "hub_push: conflict with origin, rebase aborted, commit is local" >&2; exit 3; }
    else
      sync_merge || { echo "hub_push: a dirty file or a real conflict blocks the merge, commit is local" >&2; exit 3; }
    fi
  fi
  if G push -q origin "HEAD:$branch" 2>/dev/null; then
    [ -n "${rebuilt:-}" ] && [ -f tools/lane.py ] && python3 -c 'import sys; sys.path.insert(0,"tools"); import lane; lane.build_status()' >/dev/null 2>&1
    git log --oneline -1
    exit 0
  fi
  sleep $((try * 2))
done
echo "hub_push: could not reach or update origin after 4 tries, commit is local" >&2
exit 2
