
---

## 2026-05-22T00:00:00Z | ara | BRANCH_CREATED

Branch `agent/ara/phase-1-parallel-candidates` created from `main`.
Phase 1 — Parallel Candidate Generation. Adds `run_in_sandbox`, `run_candidate_pool`,
`CandidateResult` dataclass, and `CANDIDATE_POOL_SIZE` constant to `autoresearch.py`.
Replaces single-candidate inner loop with K-parallel sandbox evaluation.
Depends on: none. Blocks: Phase 2 (pop), Phase 8 (hlr).
