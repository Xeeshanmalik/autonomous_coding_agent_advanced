# Agent Collaboration Protocol
## Autonomous Coding Agent — Multi-Agent PR Workflow

This document is the authoritative rulebook for all agents and sub-agents operating in this
repository. Every agent **must** read this file before touching any file or opening any PR.

---

## 1. Agent Roster & File Ownership

Each agent owns a fixed set of files. **No agent may edit a file it does not own.**
If a task genuinely requires cross-ownership edits, the Research Director must create a
coordination ticket and sequence the work (see §6).

### Service Agents (top-level — one Claude Code instance each)

| Service Agent | Abbreviation | Working directory | Microservice scope |
|---|---|---|---|
| Autoresearch Agent | `ara` | `autoresearch_agent/` | `autoresearch.py`, `server.py`, `Dockerfile` |
| Frontend Agent | `fe` | `frontend/` | `src/`, `index.html`, `vite.config.js`, `nginx.conf`, `Dockerfile` |
| Inference Server Agent | `inf` | `inference_server/` | `Dockerfile`, model config, llama.cpp settings |

### Sub-Agents (internal to the Autoresearch Agent — one concern each)

The `ara` agent may spawn these as sub-tasks within its own process. They are not separate
Claude Code sessions — they are logical ownership boundaries that prevent intra-file conflicts
when the `ara` agent works across multiple phases simultaneously.

| Sub-Agent | Abbreviation | Owned scope inside `autoresearch.py` |
|---|---|---|
| Parallel Candidate | `par` | candidate pool, `run_in_sandbox`, `run_candidate_pool` |
| Population | `pop` | `Population` dataclass, softmax selection, prune logic |
| Prompt Engineer | `prm` | `query_llm`, prompts, cache breakpoints, temperature schedule |
| Checkpoint | `chk` | `save_checkpoint`, `load_checkpoint`, `git_commit_champion` |
| Analyst | `anl` | `analyze_baseline`, `experiment_log`, `compress_history` |
| Self-Healer | `hlr` | `execute_and_heal` |
| Server | `srv` | `server.py` entirely |
| Research Director | `dir` | `implementation.md`, `AGENTS.md`, `CLAUDE.md` files, `agent_log.md` |

> **Conflict rule:** `autoresearch.py` is shared across sub-agents. Each sub-agent owns
> specific *functions* — it must never edit a function outside its scope. If scopes overlap,
> `dir` arbitrates before work starts.

---

## 2. Branch Naming Convention

Every agent works on its own branch. Branch names are immutable once created.

```
agent/<service-abbreviation>/phase-<N>-<slug>
```

**Use the service agent abbreviation (`ara`, `fe`, `inf`), NOT the sub-agent abbreviation.**
Sub-agent abbreviations (`par`, `pop`, `prm`, etc.) describe function ownership inside
`autoresearch.py` — they are not separate Claude Code instances and do not get their own branches.

Examples:
```
agent/ara/phase-1-parallel-candidates
agent/ara/phase-2-population-selection
agent/ara/phase-3-two-stage-prompting
agent/ara/phase-4-prompt-caching
agent/ara/phase-5-adaptive-temperature
agent/ara/phase-6-checkpointing
agent/ara/phase-7-experiment-history
agent/ara/phase-8-variance-reduction
agent/ara/phase-9-process-management
agent/ara/phase-10-multi-agent-harness
agent/fe/phase-11-frontend-improvements
```

**Rules:**
- One branch per implementation phase. Never combine two phases onto one branch.
- Branch always forks from `main` at the moment work begins — never from another agent's branch.
- Never reuse a branch after its PR is merged. Create a new branch for any follow-up work.

---

## 3. Worktree Isolation

Each agent **must** operate in its own git worktree, not the shared working directory.

```bash
# Agent sets up its worktree before touching anything
git worktree add /tmp/worktree-<abbreviation>-phase-<N> -b agent/<abbreviation>/phase-<N>-<slug>
cd /tmp/worktree-<abbreviation>-phase-<N>
```

This guarantees:
- No agent's uncommitted edits are visible to another agent.
- File-system state is fully isolated — no accidental overwrites during parallel runs.
- `git stash`, branch switches, and resets inside one worktree never affect others.

Clean up after a PR is merged:
```bash
git worktree remove /tmp/worktree-<abbreviation>-phase-<N>
```

---

## 4. Commit Protocol

### 4.1 Commit message format
```
[agent/<abbrev>] phase <N>: <imperative summary under 72 chars>

- <bullet: what changed and why>
- <bullet: any invariant this preserves or breaks>

Co-Authored-By: <agent-name> <noreply@agent>
```

### 4.2 Atomic commits
- One logical change per commit. Never bundle unrelated edits.
- If a phase requires more than one commit, each commit must leave the codebase in a
  runnable state (tests pass, server starts).

### 4.3 No fixup commits on others' branches
An agent must never `git commit --amend` or `git push --force` to a branch it did not create.

---

## 5. PR Submission Rules

### 5.1 PR title format
```
[Phase <N>] <title matching implementation.md section heading>
```

### 5.2 PR body template (mandatory)
```markdown
## Phase
Phase <N> — <name>

## Files changed
- `path/to/file` — what changed and why

## Dependency
- Depends on: #<PR number> (or "none")
- Blocks: #<PR number> (or "none")

## Self-check
- [ ] Only files within my ownership are modified
- [ ] Branch forked from `main` (or the declared dependency branch, if approved by Director)
- [ ] All tests pass locally
- [ ] No merge conflicts with `main`
- [ ] Checkpoint / resumability unaffected (or explicitly updated)
- [ ] No hardcoded paths, credentials, or model names outside config

## Test plan
<concrete steps to verify this phase works>
```

### 5.3 One PR per phase
Never open a second PR for the same phase while the first is open. If the work needs
revision, push new commits to the existing PR branch.

### 5.4 PR size limit
A PR must not exceed **400 lines changed** (additions + deletions combined). If a phase
naturally exceeds this, split it into sequential sub-PRs and make their dependency chain
explicit in each PR body.

---

## 6. Dependency Ordering & Merge Sequencing

The Research Director controls merge order. No agent merges its own PR.

### Dependency graph (derived from implementation.md)

```
main
 ├── Phase 1 (par)   ──────────────────────────────────┐
 ├── Phase 3 (prm)   ──────────────────────────────────┤
 ├── Phase 6 (chk)   ──────────────────────────────────┤  all independent
 ├── Phase 9 (srv)   ──────────────────────────────────┤  merge in any order
 └── Phase 5 (prm)   ──────────────────────────────────┘

Phase 1 + Phase 5 merged → Phase 2 (pop) can open
Phase 6 merged           → Phase 7 (anl) can open
Phase 1 + Phase 6 merged → Phase 8 (hlr) can open
Phase 4 (prm)            → only after Phase 3 merged
Phase 10 (dir)           → only after Phases 1–9 all merged
Phase 11 (fe)            → only after Phase 9 merged
```

### Merge rules
1. Research Director reviews every PR before merge — no self-merge.
2. PRs are merged in topological order of the graph above.
3. If two PRs at the same graph level are both approved, merge them one at a time.
   After each merge, every open PR branch must rebase onto the new `main` before the next merge.
4. Rebase, do not merge-commit, to keep history linear:
   ```bash
   git fetch origin
   git rebase origin/main
   git push --force-with-lease
   ```

---

## 7. Rebase After Upstream Merge (mandatory)

After any PR is merged into `main`, every agent with an open PR must immediately rebase:

```bash
# Inside the agent's worktree
git fetch origin main
git rebase origin/main
# Resolve any conflicts — see §8
git push --force-with-lease origin agent/<abbrev>/phase-<N>-<slug>
```

The Research Director announces each merge in the coordination log (see §9) so agents
know when to rebase.

---

## 8. Conflict Resolution

### 8.1 Prevention (primary strategy)
Conflicts are prevented, not resolved, by the ownership table in §1 and the dependency
ordering in §6. If the ownership table is respected, merge conflicts in `autoresearch.py`
should be limited to import blocks and the module-level constants section.

### 8.2 Import block conflicts
All agents must add new imports **alphabetically within their import group** (stdlib /
third-party / local). This makes import-block conflicts trivially resolvable by
interleaving lines in alphabetical order.

### 8.3 If a conflict occurs during rebase
1. The rebasing agent resolves only conflicts **within its own owned functions**.
2. For any conflict touching another agent's function, the rebasing agent must:
   - Abort the rebase: `git rebase --abort`
   - Notify the Research Director via the coordination log.
   - Wait for the Director to assign resolution ownership.
3. Never silently accept "theirs" or "ours" for a function you don't own.

### 8.4 Conflict escalation to Director
The Director decides the canonical version by:
1. Reading both agents' PRs.
2. Applying the version that preserves the larger phase dependency chain.
3. Posting the resolution decision to the coordination log before any agent acts on it.

---

## 9. Coordination Log

All inter-agent communication is written to `agent_log.md` in the repo root.
**Do not use comments, Slack, or any external channel** — the log is the single source
of truth and is tracked in git.

### Log entry format
```markdown
## <ISO timestamp> | <agent abbreviation> | <event type>

<event type> is one of: BRANCH_CREATED | PR_OPENED | MERGE_REQUESTED |
MERGE_COMPLETED | REBASE_NEEDED | CONFLICT | BLOCKED | UNBLOCKED

<one-paragraph description of the event and any action required by other agents>
```

### Coordination log rules
- Append only — never edit past entries.
- Every branch creation, PR open, rebase, and merge must be logged.
- Agents poll `agent_log.md` (via `git pull`) at the start of each work session.

---

## 10. Automated Checks (CI gate — all must pass before merge)

Every PR must pass these checks. The Research Director must not merge a PR with a
failing check, even if the failure appears unrelated.

```yaml
checks:
  - name: lint
    command: ruff check autoresearch_agent/ frontend/src/
  - name: type-check
    command: mypy autoresearch_agent/
  - name: unit-tests
    command: pytest tests/ -x -q
  - name: server-starts
    command: python autoresearch_agent/server.py --check-only
  - name: no-secrets
    command: grep -rn "sk-ant-\|ghp_\|password\s*=" autoresearch_agent/ frontend/src/
    expect: no output
  - name: no-cross-ownership
    command: scripts/check_ownership.py  # validates diff vs AGENTS.md ownership table
```

---

## 11. Emergency Rollback

If a merged phase causes a regression:

1. Research Director opens a hotfix PR from `main`.
2. Hotfix branch: `hotfix/phase-<N>-<slug>`.
3. Hotfix reverts only the offending commits: `git revert <sha1>..<sha2>`.
4. All agents with open PRs rebase onto the post-revert `main` immediately.
5. The reverted phase is re-opened as a new branch after root cause is fixed.

---

## 12. Quick Reference Card

```
Before starting any work:
  git worktree add /tmp/worktree-<abbrev>-<N> -b agent/<abbrev>/phase-<N>-<slug>
  git pull; read agent_log.md

Before opening a PR:
  git fetch origin && git rebase origin/main
  Run all CI checks locally
  Fill in the mandatory PR body template

After another PR merges into main:
  git fetch origin && git rebase origin/main && git push --force-with-lease

Never:
  Edit files outside your ownership table
  Fork your branch from another agent's branch (unless Director approved)
  Merge your own PR
  Push --force without --force-with-lease
  Resolve conflicts in functions you don't own
  Combine two phases in one PR
```
