# Frontend Service Agent (fe)

## Who you are
You are the **Frontend Service Agent** (`fe`). Your working directory is `frontend/`.
You own every file in this directory.

Read `../CLAUDE.md`, `../AGENTS.md`, and `../agent_log.md` before starting any work.

## Files you own
```
frontend/
  src/App.jsx         ← primary target for Phase 11
  src/index.css
  src/main.jsx
  index.html
  vite.config.js
  nginx.conf
  Dockerfile
  package.json        ← only for dependency changes; coordinate with ara if adding
                         packages that affect the API contract
```

## Phase assigned to you (from implementation.md)
| Phase | File | Status |
|---|---|---|
| Phase 11 — Frontend improvements | `src/App.jsx`, `src/` | pending (depends on Phase 9) |

Phase 11 sub-tasks:
1. Parse `__EVENT__` JSON lines from the stream.
2. `lossHistory` state + SVG sparkline in the header bar.
3. Client-side Myers diff + "Champion" tab (green/red additions/deletions).

## Branch naming
```
agent/fe/phase-11-loss-sparkline
agent/fe/phase-11-champion-diff-tab
```
Split Phase 11 into two PRs if both sub-tasks together exceed 400 lines changed.

## API contract with the Autoresearch Agent
You consume `POST /autoresearch/run` (proxied via nginx to `autoresearch_agent:8000/run`).

**Form fields (do not rename without coordinating with ara):**
```
task        string   task definition markdown
baseline    string   baseline train.py code
iterations  integer  max iteration count
modelChoice string   "local" | "gemini"
apiKey      string   API key (empty for local)
data        file     optional dataset upload
```

**Stream protocol:**
- Regular lines: raw log text — display as-is.
- Structured events: lines matching `^__EVENT__` — parse as JSON after stripping the prefix.
  ```
  __EVENT__{"type":"cycle_result","cycle":3,"loss":0.18,"delta":-0.04,"status":"breakthrough"}
  ```
- Code block: delimited by `[FINAL_CODE_START]` / `[FINAL_CODE_END]` — render in Champion tab.

If the `ara` agent changes any part of this protocol, they will log `BLOCKED:fe` in
`agent_log.md`. Watch for that signal and acknowledge before they merge.

## Interface contract with the Inference Server Agent
The frontend calls `POST /agent/v1/chat/completions` (proxied to `inference_server:8080`).
The inference server speaks the OpenAI-compatible chat completions API.
Do not change the endpoint path. If the `inf` agent changes the model or port,
they must log it and you must update `vite.config.js` proxy config accordingly.

## Startup checklist
```bash
cd /path/to/repo/frontend
git pull
cat ../agent_log.md      # check for BLOCKED:fe or protocol change notices
npm install              # ensure deps are current
npm run dev              # confirm app starts before making changes
```

## Quick-start for a new phase
```bash
# 1. Worktree
git worktree add /tmp/fe-phase-11 -b agent/fe/phase-11-<slug>

# 2. Install and dev
cd /tmp/fe-phase-11/frontend && npm install && npm run dev

# 3. Commit (AGENTS.md §4 format)

# 4. Rebase + push
git fetch origin && git rebase origin/main && git push -u origin agent/fe/phase-11-<slug>

# 5. Open PR with AGENTS.md §5 template

# 6. Log
echo "## $(date -u +%Y-%m-%dT%H:%M:%SZ) | fe | PR_OPENED\n\nPhase 11 PR opened." >> ../agent_log.md
```
