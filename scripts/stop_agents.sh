#!/usr/bin/env bash
# stop_agents.sh — gracefully stops all agents and cleans up worktrees
#
# Usage:
#   bash scripts/stop_agents.sh            # kills the tmux session only
#   bash scripts/stop_agents.sh --clean    # also removes all agent worktrees

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION="agents"
CLEAN=false

for arg in "$@"; do
  [[ "$arg" == "--clean" ]] && CLEAN=true
done

echo "==> Stopping tmux session '$SESSION'"
tmux kill-session -t "$SESSION" 2>/dev/null && echo "    Stopped." || echo "    Session was not running."

if $CLEAN; then
  echo "==> Removing agent worktrees"
  git -C "$REPO_ROOT" worktree list --porcelain \
    | grep "^worktree " \
    | awk '{print $2}' \
    | grep "^/tmp/" \
    | while read -r wt; do
        echo "    Removing $wt"
        git -C "$REPO_ROOT" worktree remove --force "$wt" 2>/dev/null || true
      done
  git -C "$REPO_ROOT" worktree prune
  echo "    Done."
fi

echo ""
echo "Agents stopped. To restart: bash scripts/launch_agents.sh"
