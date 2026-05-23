# Autonomous Coding Agent — Root Instructions

## Identity check
Before doing anything, read `AGENTS.md` and `agent_log.md` in the repo root.
They are the authoritative source of truth for branch naming, file ownership, PR rules,
and merge sequencing. These instructions complement them — they do not override them.

## Repository layout
```
autoresearch_agent/   ← owned by the Autoresearch Service Agent (ara)
frontend/             ← owned by the Frontend Service Agent (fe)
inference_server/     ← owned by the Inference Server Agent (inf)
implementation.md     ← owned by Research Director (dir) — read-only for all service agents
AGENTS.md             ← owned by Research Director (dir) — read-only for all service agents
agent_log.md          ← append-only coordination log — every agent writes here
```

## Hard rules (apply to every agent in this repo)
1. Never edit files outside your microservice directory without explicit Director approval
   recorded in `agent_log.md`.
2. Always fork branches from `main`, never from another service agent's branch.
3. Log every branch creation, PR open, rebase, and merge to `agent_log.md` before acting.
4. Rebase onto `main` immediately after any other agent's PR merges — check `agent_log.md`
   at the start of every work session.
5. Never force-push without `--force-with-lease`.
6. One phase per branch, one branch per PR. Do not combine phases.
7. Never merge your own PR.

## Coordination
- Read `agent_log.md` at the start of every session (`git pull && cat agent_log.md`).
- Append your own log entries in the format defined in `AGENTS.md §9`.
- If you are blocked waiting for another service agent, log `BLOCKED` and stop — do not
  attempt workarounds that touch files outside your ownership.
