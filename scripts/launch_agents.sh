#!/usr/bin/env bash
# launch_agents.sh — launches the four agents, each in its own pane/tab
#
# Usage:
#   bash scripts/launch_agents.sh           # split screen inside VS Code's integrated
#                                           #   terminal when run there; else gnome-terminal tabs
#   bash scripts/launch_agents.sh --vscode  # force the VS Code split-screen layout (tmux tiled)
#   bash scripts/launch_agents.sh --tabs    # force gnome-terminal tabs
#   bash scripts/launch_agents.sh --tmux    # tmux session in separate windows (mouse-enabled)
#   bash scripts/launch_agents.sh --attach  # re-attach to existing tmux session

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"

# Default: split screen inside VS Code if we're in its integrated terminal,
# otherwise fall back to opening gnome-terminal tabs.
if [[ "${TERM_PROGRAM:-}" == "vscode" ]]; then
  MODE="vscode"
else
  MODE="tabs"
fi

for arg in "$@"; do
  case "$arg" in
    --vscode) MODE="vscode" ;;
    --tabs)   MODE="tabs" ;;
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
# MODE: VS Code integrated terminal — four tiled panes (split screen)
# ════════════════════════════════════════════════════════════════════════════
# Runs a tmux session of 4 tiled panes *in the current terminal*, so all four
# agents appear side-by-side inside VS Code's integrated terminal panel.
if [[ "$MODE" == "vscode" ]]; then
  if ! command -v tmux &>/dev/null; then
    echo "tmux not found (needed for the VS Code split layout) — falling back to tabs"
    echo "Install it with: sudo apt install tmux   (or run: bash scripts/setup.sh)"
    MODE="tabs"
  else
    SESSION="agents"
    tmux kill-session -t "$SESSION" 2>/dev/null || true

    echo ""
    echo "Opening 4 agents as tiled panes inside this VS Code terminal..."
    echo "  ┌── ara ──┬── fe ──┐"
    echo "  ├── inf ──┴── log ─┤   (click a pane to focus it; mouse is enabled)"
    echo "  └──────────────────┘"
    echo ""

    # Pane 0: ara — then split three more and tile into a 2x2 grid.
    tmux new-session  -d -s "$SESSION" -n "agents" \
                      -c "$REPO_ROOT/autoresearch_agent" "bash -c '$ARA_CMD'"
    tmux split-window -h -t "$SESSION" -c "$REPO_ROOT/frontend"         "bash -c '$FE_CMD'"
    tmux split-window -v -t "$SESSION" -c "$REPO_ROOT/inference_server" "bash -c '$INF_CMD'"
    tmux select-pane  -t "$SESSION:agents.0"
    tmux split-window -v -t "$SESSION" -c "$REPO_ROOT"                  "bash -c '$LOG_CMD'"
    tmux select-layout -t "$SESSION" tiled
    tmux set-option   -t "$SESSION" mouse on
    tmux select-pane  -t "$SESSION:agents.0"

    tmux attach-session -t "$SESSION"
    exit 0
  fi
fi

# ════════════════════════════════════════════════════════════════════════════
# MODE: gnome-terminal tabs (default outside VS Code)
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
