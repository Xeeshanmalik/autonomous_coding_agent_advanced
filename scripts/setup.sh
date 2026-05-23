#!/usr/bin/env bash
# setup.sh — installs tmux + Node 20 + Claude Code
# Run once as a user with sudo access: bash scripts/setup.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> [1/4] Installing tmux"
sudo apt-get update -qq
sudo apt-get install -y tmux

echo "==> [2/4] Installing Node.js 20 via NodeSource"
# Remove old Node 12 packages that conflict with Node 20
sudo apt-get remove -y nodejs libnode-dev libnode72 2>/dev/null || true
sudo apt-get autoremove -y 2>/dev/null || true
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
echo "    Node: $(node --version)  npm: $(npm --version)"

echo "==> [3/4] Installing Claude Code globally"
sudo npm install -g @anthropic-ai/claude-code
echo "    Claude Code: $(claude --version)"

echo "==> [4/4] Verifying git worktree support"
git -C "$REPO_ROOT" worktree list

echo ""
echo "All done. Run:  bash scripts/launch_agents.sh"
