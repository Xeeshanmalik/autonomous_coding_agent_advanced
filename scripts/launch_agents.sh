#!/usr/bin/env bash
# launch_agents.sh — opens each agent in its own gnome-terminal tab
#
# Usage:
#   bash scripts/launch_agents.sh           # 3 tabs in a new gnome-terminal window
#   bash scripts/launch_agents.sh --tmux    # tmux fallback (mouse-enabled)
#   bash scripts/launch_agents.sh --attach  # re-attach to existing tmux session

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"

MODE="tabs"   # default: gnome-terminal tabs
for arg in "$@"; do
  case "$arg" in
    --tmux)   MODE="tmux" ;;
    --attach) MODE="attach" ;;
  esac
done

# ── prerequisite check ────────────────────────────────────────────────────────
if ! command -v claude &>/dev/null; then
  echo "ERROR: claude not found. Run: bash scripts/setup.sh"; exit 1
fi
echo "claude : $(which claude)  [$(claude --version 2>/dev/null | head -1)]"

# ── per-agent shell snippet ───────────────────────────────────────────────────
# Sets PATH, moves to the right dir, launches claude, then drops to bash if it exits.
agent_cmd() {
  local dir="$1"
  echo "export PATH=$HOME/.npm-global/bin:\$PATH; cd '$dir'; claude; exec bash"
}

ARA_CMD="$(agent_cmd "$REPO_ROOT/autoresearch_agent")"
FE_CMD="$(agent_cmd "$REPO_ROOT/frontend")"
INF_CMD="$(agent_cmd "$REPO_ROOT/inference_server")"
LOG_CMD="cd '$REPO_ROOT'; tail -f agent_log.md; exec bash"

# ════════════════════════════════════════════════════════════════════════════
# MODE: gnome-terminal tabs (default)
# ════════════════════════════════════════════════════════════════════════════
if [[ "$MODE" == "tabs" ]]; then
  if ! command -v gnome-terminal &>/dev/null; then
    echo "gnome-terminal not found — falling back to tmux"
    MODE="tmux"
  else
    echo ""
    echo "Opening 4 separate terminal windows (one per agent)..."
    echo ""
    echo "  Window 1 — ara  (Autoresearch Agent)"
    echo "  Window 2 — fe   (Frontend Agent)"
    echo "  Window 3 — inf  (Inference Server Agent)"
    echo "  Window 4 — log  (Live agent_log.md)"
    echo ""

    gnome-terminal --title="ara — Autoresearch Agent" -- bash -c "$ARA_CMD" &
    sleep 0.3
    gnome-terminal --title="fe — Frontend Agent"      -- bash -c "$FE_CMD"  &
    sleep 0.3
    gnome-terminal --title="inf — Inference Server"   -- bash -c "$INF_CMD" &
    sleep 0.3
    gnome-terminal --title="log — agent_log.md"       -- bash -c "$LOG_CMD" &

    echo "Done. Switch agents by clicking each window in the taskbar."
    exit 0
  fi
fi

# ════════════════════════════════════════════════════════════════════════════
# MODE: tmux (fallback or --tmux flag)
# ════════════════════════════════════════════════════════════════════════════
SESSION="agents"

if [[ "$MODE" == "attach" ]]; then
  tmux attach-session -t "$SESSION" 2>/dev/null \
    || { echo "No session '$SESSION'. Run without --attach to start one."; exit 1; }
  exit 0
fi

if ! command -v tmux &>/dev/null; then
  echo "ERROR: tmux not found. Run: bash scripts/setup.sh"; exit 1
fi

tmux kill-session -t "$SESSION" 2>/dev/null || true

# Enable mouse so you can click to switch windows — no key combos needed
tmux \
  new-session  -d -s "$SESSION" -n "ara" -c "$REPO_ROOT/autoresearch_agent" "bash -c '$ARA_CMD'" \;\
  new-window       -t "$SESSION" -n "fe"  -c "$REPO_ROOT/frontend"           "bash -c '$FE_CMD'"  \;\
  new-window       -t "$SESSION" -n "inf" -c "$REPO_ROOT/inference_server"   "bash -c '$INF_CMD'" \;\
  new-window       -t "$SESSION" -n "log" -c "$REPO_ROOT"                    "bash -c '$LOG_CMD'" \;\
  set-option       -t "$SESSION" mouse on \;\
  select-window    -t "$SESSION:ara"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   agents session — click tabs at bottom to switch   ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  ara  fe  inf  log   ← click any tab                ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Ctrl+B, d  →  detach (agents keep running)         ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

tmux attach-session -t "$SESSION"
