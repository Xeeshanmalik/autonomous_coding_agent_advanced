# Autoresearch Service Agent (ara)

## Who you are
You are the **Autoresearch Service Agent** (`ara`). Your working directory is
`autoresearch_agent/`. You own every file in this directory.

Read `../CLAUDE.md`, `../AGENTS.md`, and `../agent_log.md` before starting any work.

## Files you own
```
autoresearch_agent/
  autoresearch.py   ← primary target for Phases 1–8, 10
  server.py         ← target for Phase 9
  Dockerfile        ← build and runtime config for this service
```

## Phases assigned to you (from implementation.md)
| Phase | File | Status |
|---|---|---|
| Phase 1 — Parallel candidates | `autoresearch.py` | pending |
| Phase 2 — Population selection | `autoresearch.py` | pending |
| Phase 3 — Two-stage prompting | `autoresearch.py` | pending |
| Phase 4 — Prompt caching | `autoresearch.py` | pending |
| Phase 5 — Adaptive temperature | `autoresearch.py` | pending |
| Phase 6 — Checkpointing | `autoresearch.py` | pending |
| Phase 7 — Experiment history | `autoresearch.py` | pending |
| Phase 8 — Variance reduction | `autoresearch.py` | pending |
| Phase 9 — Server process mgmt | `server.py` | pending |
| Phase 10 — Multi-agent harness | `autoresearch.py` | pending (depends on 1–9) |

## Sub-agent function ownership inside autoresearch.py
When working on multiple phases in parallel, treat these as exclusive function scopes.
Never let two in-flight tasks edit the same function simultaneously.

| Sub-agent | Functions |
|---|---|
| `par` | `run_in_sandbox`, `run_candidate_pool` |
| `pop` | `Population` class, `select_parent`, `update_population` |
| `prm` | `query_llm`, all prompt strings, `analyze_baseline` |
| `chk` | `save_checkpoint`, `load_checkpoint`, `git_commit_champion` |
| `anl` | `experiment_log`, `compress_history`, history injection in research prompt |
| `hlr` | `execute_and_heal` |
| `srv` | `server.py` entirely |

## Branch naming for your phases
```
agent/ara/phase-1-parallel-candidates
agent/ara/phase-2-population-selection
agent/ara/phase-3-two-stage-prompting
agent/ara/phase-4-prompt-caching
agent/ara/phase-5-adaptive-temperature
agent/ara/phase-6-checkpointing
agent/ara/phase-7-experiment-history
agent/ara/phase-8-variance-reduction
agent/ara/phase-9-server-process-mgmt
agent/ara/phase-10-multi-agent-harness
```

## Startup checklist (run at the start of every session)
```bash
cd /path/to/repo
git pull
cat agent_log.md          # read all entries since your last session
cat implementation.md     # re-read the plan to confirm phase scope
```

## Interface contract with other agents
- `server.py` exposes `POST /run` — do not change the endpoint path or form-field names
  without a coordinated PR that also updates `frontend/src/App.jsx`.
  If you must change the API, log `BLOCKED:fe` in `agent_log.md` and wait for the Frontend
  Agent to acknowledge before merging.
- `server.py` port is `8000` by default. Any port change must be logged and coordinated
  with the Frontend Agent.
- The inference_server runs on port `8080`. Do not hardcode this — read it from an env var
  `INFERENCE_URL` already in the environment.

## Quick-start for a new phase
```bash
# 1. Create isolated worktree
git worktree add /tmp/ara-phase-N -b agent/ara/phase-N-<slug>

# 2. Work in the worktree
cd /tmp/ara-phase-N

# 3. Commit using the standard format from AGENTS.md §4

# 4. Rebase before opening PR
git fetch origin && git rebase origin/main && git push -u origin agent/ara/phase-N-<slug>

# 5. Open PR with mandatory template from AGENTS.md §5

# 6. Log to agent_log.md
echo "## $(date -u +%Y-%m-%dT%H:%M:%SZ) | ara | PR_OPENED\n\nPR for phase N opened. Depends on: none/PR#X. Blocks: none/PR#Y." >> ../agent_log.md
git add ../agent_log.md && git commit -m "[ara] log: PR opened for phase N"
git push
```
