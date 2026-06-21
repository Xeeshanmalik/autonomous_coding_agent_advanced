# Agent Coordination Log

Append-only. See AGENTS.md §9 for entry format and rules.

---

## 2026-05-21T00:00:00Z | dir | BRANCH_CREATED

AGENTS.md and agent_log.md initialized on `main`.
All agents: read AGENTS.md before opening any branch or PR.
Dependency graph and merge order are defined in AGENTS.md §6.

---

## 2026-05-21T00:01:00Z | dir | UNBLOCKED

Three service agents instantiated. Per-service CLAUDE.md files created:
- `autoresearch_agent/CLAUDE.md` → ara agent, Phases 1–10
- `frontend/CLAUDE.md`           → fe agent, Phase 11
- `inference_server/CLAUDE.md`   → inf agent, Dockerfile maintenance

Root `CLAUDE.md` created with shared hard rules.
AGENTS.md updated with the three-service agent roster.

ara, fe, inf: you are now unblocked. Read your CLAUDE.md and begin Phase work
in priority order from implementation.md.

---

## 2026-05-21T21:15:32Z | inf | BRANCH_CREATED

Creating branch agent/inf/config-parallel-slots to add --parallel 4 flag to llama-server ENTRYPOINT, supporting Phase 1 parallel candidate generation.

---

## 2026-05-21T21:16:45Z | inf | PR_OPENED

PR #2: config(inf): add --parallel 4 to llama-server
https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/2
Adds --parallel 4 to ENTRYPOINT so Phase 1 K=3 concurrent candidates are served in parallel.

---

## 2026-05-21T21:26:10Z | inf | PR_MERGED

PR #2 merged into main: config(inf): add --parallel 4 to llama-server

---

## 2026-05-22T00:00:00Z | ara | BRANCH_CREATED

Branch `agent/ara/phase-1-parallel-candidates` created from `main`.
Phase 1 — Parallel Candidate Generation. Adds `run_in_sandbox`, `run_candidate_pool`,
`CandidateResult` dataclass, and `CANDIDATE_POOL_SIZE` constant to `autoresearch.py`.
Replaces single-candidate inner loop with K-parallel sandbox evaluation.
Depends on: none. Blocks: Phase 2 (pop), Phase 8 (hlr).

---

## 2026-05-22T00:00:00Z | fe | BRANCH_CREATED

Branch `agent/fe/phase-11-loss-sparkline` created from `main`.
Phase 11 work begins: __EVENT__ stream parsing, lossHistory SVG sparkline, client-side Myers diff + Champion tab.
NOTE: Phase 9 (ara) not yet merged. PR will be held until ara logs MERGE_COMPLETED for Phase 9.

---

## 2026-05-21T21:26:10Z | inf | PR_MERGED

PR #2 merged into main: config(inf): add --parallel 4 to llama-server

---

## 2026-05-22T00:01:00Z | ara | PR_OPENED

PR #3 opened for Phase 1 — Parallel Candidate Generation.
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/3
Depends on: none. Blocks: Phase 2 (pop), Phase 8 (hlr).
Awaiting Research Director review. No other agent action required.

---

## 2026-05-22T00:01:00Z | fe | PR_OPENED

PR #4 opened: "[Phase 11] Frontend improvements — loss sparkline + champion diff tab"
Branch: agent/fe/phase-11-loss-sparkline → main
BLOCKED on merge: waiting for ara to log MERGE_COMPLETED for Phase 9 before this can be merged.

---

## 2026-05-22T00:02:00Z | ara | BRANCH_CREATED

Branch `agent/ara/phase-5-adaptive-temperature` created from `main`.
Phase 5 — Adaptive Temperature + Exploration Schedule.
Adds `temp` parameter to `query_llm`; computes cosine annealing base_temp per cycle
(0.8→0.1); derives per-candidate spread [low=0.5×, mid=1×, high=1.5×] for pool.
Depends on: none. Blocks: Phase 2 (together with Phase 1 merge).

---

## 2026-05-22T00:03:00Z | ara | PR_OPENED

PR #5 opened for Phase 5 — Adaptive Temperature + Exploration Schedule.
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/5
Depends on: none. Blocks: Phase 2 (needs Phase 1 + Phase 5 both merged).
Awaiting Research Director review.

---

## 2026-05-22T00:12:00Z | ara | BRANCH_CREATED

Branch `agent/ara/phase-6-checkpointing` created from `main`.
Phase 6 — State Persistence & Resumability.
Adds `save_checkpoint`, `load_checkpoint`, `git_commit_champion` to `autoresearch.py`.
`main()` checks for `checkpoint.json` on startup and resumes; saves checkpoint after
every cycle; commits `train.py` to git after each breakthrough.
Depends on: none. Blocks: none.

---

## 2026-05-22T00:13:00Z | ara | PR_OPENED

PR #8 opened for Phase 6 — Checkpointing and Run Resumability.
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/8
Depends on: none. Blocks: none.
Awaiting Research Director review.

---

## 2026-05-22T00:14:00Z | ara | BRANCH_CREATED

Branch `agent/ara/phase-9-server-process-mgmt` created from `main`.
Phase 9 — Process Management in Server (Cancel + Isolation).
server.py: per-request UUID workdir, `active_runs` registry, `preexec_fn=os.setsid`,
`__RUN_ID__` first stream line, `POST /cancel/{run_id}` via SIGTERM to process group.
autoresearch.py: `_handle_sigterm` flag + loop exit check.
Depends on: none. Blocks: fe (cancel button wiring, run_id capture).

---

## 2026-05-22T00:15:00Z | ara | PR_OPENED

PR #9 opened for Phase 9 — Server Process Management, Cancel Endpoint, Isolation.
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/9
Depends on: none. Blocks: fe (cancel button + run_id wiring).
Awaiting Research Director review.

---

## 2026-05-22T06:00:00Z | fe | MERGE_COMPLETED

PR #4 merged: [Phase 11] Frontend improvements — loss sparkline + champion diff tab.
Phase 11 is the only fe-assigned phase. All fe phases are now complete.
NOTE: When Phase 9 (ara — process management) merges, fe will need a follow-up update:
  - Parse run_id from first streamed line (server will emit it per Phase 9 spec)
  - Store run_id in state
  - Update handleStop() to POST /cancel/{run_id} instead of just closing the reader
  fe will create branch agent/fe/phase-9-cancel-integration at that time.

---

## 2026-05-22T06:00:00Z | fe | UNBLOCKED

fe session-start status check (2026-05-22):
  PRs merged since last log: #3 (Phase 1), #4 (Phase 11), #5 (Phase 5), #6 (Phase 3), #7 (inf mlock)
  ara Phase 2 (population): UNBLOCKED — Phase 1 + Phase 5 both merged. ara can open PR now.
  ara Phase 4 (prompt caching): UNBLOCKED — Phase 3 merged.
  ara Phase 6 (checkpointing): IN PROGRESS — branch open, PR #8 awaiting review.
  ara Phase 9 (process mgmt): IN PROGRESS — branch open, PR #9 awaiting review.
  fe: no remaining assigned phases until Phase 9 merges (see above).

---

## 2026-05-22T00:16:00Z | ara | BRANCH_CREATED

Branch `agent/ara/phase-7-experiment-history` created from `main`.
Phase 7 — Richer Experiment History Context.
Adds `compress_history`, `format_history_hint`, `HISTORY_COMPRESS_AFTER` to `autoresearch.py`.
`save_checkpoint`/`load_checkpoint` extended to persist `experiment_log` + `history_prefix`.
History hint injected into Stage B research prompt each cycle. Compresses every 10 cycles.
Depends on: Phase 6 (checkpoint extended). Blocks: none.

---

## 2026-05-22T00:17:00Z | ara | PR_OPENED

PR #11 opened for Phase 7 — Experiment History Context and LLM Compression.
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/11
Depends on: Phase 6 (merged). Blocks: none.
Awaiting Research Director review.

---

## 2026-05-22T06:30:00Z | ara | MERGE_COMPLETED

PR #9 merged into main: feat(ara): phase 9 — server process management, cancel endpoint, isolation.
fe: UNBLOCKED for cancel integration. Stream now emits `__RUN_ID__:{run_id}` as first line.
fe should create branch agent/fe/phase-9-cancel-integration immediately.

---

## 2026-05-22T06:31:00Z | fe | BRANCH_CREATED

Branch `agent/fe/phase-9-cancel-integration` created from `main`.
Updates App.jsx to parse `__RUN_ID__:{run_id}` from first stream line, store it in state,
and call POST /autoresearch/cancel/{run_id} in handleStop() instead of closing the reader.
Depends on: Phase 9 (PR #9, now merged). Blocks: none.

---

## 2026-05-22T06:32:00Z | fe | PR_OPENED

PR #10 opened: "[Phase 9 fe] Cancel integration — run_id capture + POST /cancel/{run_id}"
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/10
Branch: agent/fe/phase-9-cancel-integration → main
Depends on: #9 (merged). Blocks: none.
Changes: runIdRef added; processLine intercepts __RUN_ID__: lines; handleStop POSTs /cancel/{run_id}.

---

## 2026-05-22T06:45:00Z | fe | MERGE_COMPLETED

PR #10 merged into main: [Phase 9 fe] Cancel integration — run_id capture + POST /cancel/{run_id}.
All fe phases complete. No further fe work pending.

---

## 2026-05-22T06:50:00Z | ara | MERGE_COMPLETED

PR #8 merged into main: feat(ara): phase 6 — checkpointing and run resumability.
(Merge occurred at commit 338568a, prior to Phase 9 work — logging retroactively.)
Phase 7 (experiment history) is now UNBLOCKED — depends on Phase 6 only.
Phase 8 (variance reduction) is now UNBLOCKED — depends on Phase 1 (merged) + Phase 6 (merged).

---

## 2026-05-22T07:00:00Z | ara | MERGE_COMPLETED

PR #11 merged into main: feat(ara): phase 7 — experiment history context and LLM compression.
Phase 8 (variance reduction) remains unblocked. Phase 2 (population) remains unblocked.

---

## 2026-05-22T00:18:00Z | ara | BRANCH_CREATED

Branch `agent/ara/phase-2-population-selection` created from `main`.
Phase 2 — Population-Based Champion Selection.
Adds `Population`, `PopulationMember`, `select_parent`, `update_population`,
`save_population`, `load_population` to `autoresearch.py`.
Stage A and Stage B now operate on the softmax-selected parent rather than the frozen
baseline. Population persisted to `population.json` each cycle.
Depends on: Phase 1 (merged), Phase 5 (merged). Blocks: none.

---

## 2026-05-22T07:10:00Z | ara | PR_OPENED

PR #12 opened for Phase 2 — Population-Based Champion Selection.
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/12
Depends on: #3 (Phase 1), #5 (Phase 5), #8 (Phase 6), #11 (Phase 7) — all merged.
Blocks: Phase 10 (final dependency).
Awaiting Research Director review.

---

## 2026-05-23T00:00:00Z | ara | BRANCH_CREATED

Branch `agent/ara/phase-9-cancel-hardening` created from `origin/main` (HEAD 7cb6660).
Hotfix: the existing Phase 9 cancel path was insufficient — `/cancel` sent only SIGTERM,
which `autoresearch.py` caught and turned into a soft flag checked once per cycle, so
the in-flight `query_llm` streaming request kept draining tokens from
`local-deepseek-backend:8080` and the GPU stayed pinned at 100% for the rest of the cycle.
Fix: `server.py /cancel` now escalates SIGTERM → SIGKILL after 2 s grace; `query_llm`
checks `_sigterm_received` before each request and inside `iter_lines()`, closes the
response (llama.cpp aborts generation on client disconnect), and raises `KeyboardInterrupt`;
`__main__` catches it for a clean exit. Files touched: `autoresearch_agent/server.py`,
`autoresearch_agent/autoresearch.py` — both within ara ownership.

---

## 2026-05-23T00:01:00Z | ara | PR_OPENED

PR #13 opened: "[Phase 9 hotfix] Cancel actually stops LLM generation (SIGKILL escalation + mid-stream abort)"
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/13
Branch: agent/ara/phase-9-cancel-hardening → main
Depends on: #9 (merged), #10 (merged). Blocks: none.
No frontend changes required — `__RUN_ID__` handshake and `/cancel/{run_id}` path are unchanged.
Awaiting Research Director review.

---

## 2026-05-23T00:30:00Z | ara | MERGE_COMPLETED

PR #13 merged into main as 124c19f: [Phase 9 hotfix] cancel actually stops LLM generation.
GPU now drops on Stop because /cancel escalates SIGTERM → SIGKILL and query_llm closes
the LLM stream on cancel.

---

## 2026-05-23T00:31:00Z | ara | BRANCH_CREATED

Branch `agent/ara/hotfix-iteration-init` created from `origin/main` (HEAD 124c19f).
Pre-existing Phase 6 regression discovered during user testing of PR #13:
`main()` only assigns `iteration` in the `if checkpoint:` branch, so a fresh run
(no checkpoint.json) crashes with `UnboundLocalError` at `while iteration <= max_iterations`
before any cycle starts. One-line fix: `iteration = 1` in the `else` branch.

---

## 2026-05-23T00:32:00Z | ara | PR_OPENED

PR #14 opened: "[Hotfix] Initialize iteration=1 on fresh run (Phase 6 UnboundLocalError)"
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/14
Branch: agent/ara/hotfix-iteration-init → main
Depends on: #8 (Phase 6, merged). Blocks: nothing functionally, but the user cannot test
the merged Phase 9 cancel work without this fix landing first.
Awaiting Research Director review.

---

## 2026-05-23T01:00:00Z | ara | BRANCH_CREATED

Branch `agent/ara/phase-4-prompt-caching` created from `origin/main` (HEAD 05bcc3a).
Phase 4 — Prompt Caching via Anthropic cache_control breakpoints.
Adds USE_ANTHROPIC backend (native /v1/messages, parses SSE deltas, logs per-call
cache_read / cache_creation token counts). Adds structured `content` blocks with
optional cache_control markers; preserved for Anthropic, flattened for OpenAI/Gemini.
analyze_baseline (Stage A) and main()'s research loop reshaped to put SYSTEM_PROMPT +
program_instructions in the cached prefix and per-cycle parent code / history /
weaknesses in the variable tail. Replaces the implementation.md baseline-code
breakpoint (no longer stable after Phase 2's per-cycle parent code) with
program_instructions, which IS stable per run.
Depends on: #6 (Phase 3, merged). Blocks: none directly; Phase 10 still waits on Phase 8.

---

## 2026-05-23T01:01:00Z | ara | PR_OPENED

PR #15 opened: "[Phase 4] Prompt caching via Anthropic cache_control breakpoints"
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/15
Branch: agent/ara/phase-4-prompt-caching → main
Depends on: #6 (merged). Blocks: none.
Wire format unchanged for OpenAI/Gemini callers — no server.py or frontend changes.
Awaiting Research Director review.

---

## 2026-05-23T12:30:00Z | ara | MERGE_COMPLETED

PR #15 merged into main as baa0db3: feat(ara): phase 4 — prompt caching via Anthropic cache_control breakpoints.
USE_ANTHROPIC backend now available; analyze_baseline + research loop emit stable-prefix
content blocks that benefit both Anthropic's ephemeral cache and llama.cpp's automatic KV prefix cache.
Remaining ara work: Phase 8 (variance reduction, unblocked) and Phase 10 (multi-agent harness, still waits on Phase 8).

---

## 2026-05-23T13:00:00Z | ara | BRANCH_CREATED

Branch `agent/ara/phase-8-variance-reduction` created from `origin/main` (HEAD e2a88ad).
Phase 8 — Multi-Run Variance Reduction.
Adds robust_eval(code, workdir, threshold_loss, k=3) per implementation.md §Phase 8.
run_candidate_pool now dispatches each candidate through robust_eval, which re-runs k
times and takes the median ONLY when the candidate is within ROBUST_EVAL_MARGIN (5%) of
threshold_loss. main() passes best_loss as threshold; first cycle is unchanged because
inf threshold short-circuits.
Depends on: #3 (Phase 1, merged), #8 (Phase 6, merged). Blocks: nothing in flight;
unblocks Phase 10 now that Phase 4 (#15) is also merged.

---

## 2026-05-23T13:01:00Z | ara | PR_OPENED

PR #16 opened: "[Phase 8] Multi-run variance reduction for near-frontier candidates"
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/16
Branch: agent/ara/phase-8-variance-reduction → main
Depends on: #3 (merged), #8 (merged). Blocks: none.
No server.py / frontend changes — wire formats and endpoint contracts unchanged.
Awaiting Research Director review.

---

## 2026-06-02T10:41:32Z | ara | BRANCH_CREATED

Branch `agent/ara/hotfix-select-parent-overflow` created from `origin/main` (HEAD 75e5f8d).
User-reported crash mid-evolution:
`OverflowError: math range error` in `select_parent` (autoresearch.py:495)
when population contains a crashed/divergent member (loss ≈ 1500) alongside healthy
members (loss ≈ 0.3) — `math.exp(max_loss - l)` overflows once the gap > ~709.

Same hotfix also wraps the previously-unwrapped `analyze_baseline` LLM call in main()
so a transient Stage-A failure no longer kills the run, and fixes the `best_loss`
NameError on resume-without-population.json.

Depends on: #5 (Phase 2, merged), #6 (Phase 3, merged), #8 (Phase 6, merged). Blocks: none.

---

## 2026-06-02T10:41:32Z | ara | PR_OPENED

PR #17 opened: "[Hotfix] select_parent overflow + analyze_baseline hardening"
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/17
Branch: agent/ara/hotfix-select-parent-overflow → main
Depends on: #5 (merged), #6 (merged), #8 (merged). Blocks: none.
No server.py / frontend changes — wire format and endpoint contracts unchanged.
Awaiting Research Director review.

---

## 2026-06-02T11:23:41Z | ara | BRANCH_CREATED

Branch `agent/ara/feat-baseline-bootstrap` created from `origin/main` (HEAD 4534307).
User-reported gap: a baseline that does not print `val_loss <float>` lets the
evolutionary loop start against val_loss=inf, burning every cycle on noise.
This branch gates the loop on a finite baseline and offers two recovery modes
via a new `bootstrapMode` form field on POST /run.

Depends on: none. Blocks: none functionally (works standalone via "manual"
default). Coordinates with fe — see BLOCKED:fe entry below.

---

## 2026-06-02T11:23:41Z | ara | PR_OPENED

PR #18 opened: "[Feature] Refuse to start at val_loss=inf; add bootstrapMode form field"
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/18
Branch: agent/ara/feat-baseline-bootstrap → main
Depends on: none. Blocks: none.

API change (additive, backward-compatible):
  POST /run gains optional form field `bootstrapMode: "" | "auto" | "manual"`.
  Default "" behaves as "manual" — refuse with an instructive error when
  val_loss is inf, never silently loop. Existing clients keep working unchanged.

Awaiting Research Director review.

---

## 2026-06-02T11:23:41Z | ara | BLOCKED:fe

PR #18 introduces a new optional form field on POST /run that needs a UI
counterpart so users can pick between the two recovery modes.

Contract:
  Field name: bootstrapMode
  Encoding:   multipart/form-data, string
  Values:
    "manual" — user supplies a baseline that already prints val_loss.
               If it doesn't, autoresearch refuses with a clear message.
    "auto"   — autoresearch asks the LLM to write a baseline from program.md
               and re-evaluates before the loop starts.
    ""       — same as "manual" (default).

Suggested UI (fe agent owns final form):
  A dropdown next to the baseline textarea labelled "Baseline source":
    • "Use my baseline (require finite val_loss)" → bootstrapMode="manual"
    • "Auto-generate from task description"        → bootstrapMode="auto"
  Default selection: "Use my baseline".

fe agent: please open a sibling PR in frontend/src/App.jsx that adds this
dropdown and includes the value in the FormData sent to /run. The backend
PR is mergeable independently — backend already refuses cleanly when the
field is absent — so there is no hard merge ordering requirement, but
landing them together gives the user the intended UX.

---

## 2026-06-02T16:42:44Z | ara | BRANCH_CREATED

Branch `agent/ara/phase-10-multi-agent-harness` created from `origin/main` (HEAD d0db6bf).
Final phase from implementation.md. Refactors the per-cycle work in `main()` into
specialised async agents (Analyst, CodeGen × K, EvalWorker × K, SelfHealer)
coordinated by a Research Director. Bridges to asyncio via asyncio.to_thread —
no rewrite of the streaming HTTP layer needed.

Depends on: all of Phases 1-9 (merged). Blocks: none.

---

## 2026-06-02T16:42:44Z | ara | PR_OPENED

PR #20 opened: "[Phase 10] Multi-agent harness — async Director + parallel CodeGen/EvalWorker/SelfHealer"
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/20
Branch: agent/ara/phase-10-multi-agent-harness → main
Depends on: Phases 1-9 (all merged). Blocks: none.

Key behavioural changes:
  - K CodeGen LLM calls now fire in parallel (asyncio.gather) — primary speedup.
  - SelfHealer integrated into the main flow per implementation.md §Phase 10
    diagram; previously the existing `execute_and_heal` was never called from
    main(). Crashed candidates now get one repair attempt before being dropped.
    Opt out via ENABLE_SELF_HEALER=false.
  - Phase 4 cache_control breakpoints, Phase 5 cosine annealing, Phase 6
    checkpoint shape, Phase 7 history compression, Phase 8 robust_eval, and
    Phase 9 SIGTERM all preserved.

Wire format unchanged — no server.py / frontend changes. Awaiting Research
Director review.

---

## 2026-06-02T17:10:15Z | ara | BRANCH_CREATED

Branch `agent/ara/fix-bootstrap-date-and-runtime-guidance` created from
`origin/main` (HEAD 0f9ec4d). User-reported failure on Walmart_Sales.csv:
auto bootstrap exhausted all 3 attempts. Attempt 3 hit
`ValueError: time data "19-02-2010" doesn't match format "%m-%d-%Y"`.

Root cause: bootstrap prompt gave the LLM a 5-row dataset preview but no
guidance on how to interpret date columns; pandas auto-inference picked
month-first for an ambiguous early row and crashed on day=19.

Fix is dataset-agnostic: a new `_detect_date_columns` helper scans the
preview for any column whose values match one of 16 common strftime
formats, and the bootstrap prompt now lists explicit `pd.to_datetime(...,
format='...')` snippets for each detected column. Plus stronger runtime
budget guidance (<90s, no large GridSearchCV) and bigger error tail.

Validated against 13 dataset shapes from different domains in
test_bootstrap_generality.py — retail, NYC taxi, ISO warehouses, IoT,
German finance, compact dates, multi-date, no-date numeric, etc.

Depends on: none (Phase 10 merged). Blocks: none.

---

## 2026-06-02T17:10:15Z | ara | PR_OPENED

PR #21 opened: "[Fix] Bootstrap: dataset-agnostic date detection + stronger LLM guidance"
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/21
Branch: agent/ara/fix-bootstrap-date-and-runtime-guidance → main
Depends on: PR #20 (merged). Blocks: none.

Wire format unchanged — no server.py / frontend changes. Awaiting Director review.

---

## 2026-06-03T12:54:09Z | dir | CROSS_AGENT_APPROVAL

User (acting as Director) authorises `ara` to add one new file to
`inference_server/` for the explicit purpose of codifying a reproducible
launch (avoid manual `docker run -c 1024` overrides). Scope is narrow:
add `inference_server/docker-compose.yml` only. Dockerfile and CLAUDE.md
are NOT in scope. Single PR; no follow-up cross-domain work authorised
under this approval.

Motivation: the running llama-server container has been launched with
`--ctx-size 1024`, which makes the autoresearch bootstrap impossible
(prompt alone is ~700 tokens; completion needs another ~500). The
Dockerfile ENTRYPOINT already declares `-c 16384`, so the fix is
deployment, not source. The new compose file locks in the correct
launch so the override can't happen again silently.

---

## 2026-06-03T12:54:09Z | ara | BRANCH_CREATED

Branch `agent/ara/hotfix-inf-codify-launch-ctx` created from `origin/main`.
Adds `inference_server/docker-compose.yml` under the Director approval
above. No other files touched. inf agent retains ownership of Dockerfile
and the actual flag values — compose just uses the existing ENTRYPOINT.

Depends on: none. Blocks: none.

---

## 2026-06-03T13:01:00Z | ara | PR_OPENED

PR #22 opened: "[Hotfix] Codify llama-server launch — prevent silent -c 1024 override"
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/22
Branch: agent/ara/hotfix-inf-codify-launch-ctx → main
Depends on: none. Blocks: none. Resolves runtime blocker for PR #21.

Cross-domain change under Director approval (logged above as CROSS_AGENT_APPROVAL).
Adds inference_server/docker-compose.yml only — Dockerfile and CLAUDE.md untouched.

Awaiting Research Director review.

---

## 2026-06-03T15:18:00Z | ara | BRANCH_CREATED

Branch `agent/ara/fix-parallel-stream-interleave` created from `origin/main`
(HEAD 36d219b). User-reported garble during Phase 10 cycle: three parallel
CodeGen worker threads were all streaming LLM tokens to a single global
stdout, producing character-level interleave (`importimportimport os os os`).

This is the UX issue flagged on PR #20 when Phase 10 shipped — the
candidates were correct, only the display was broken. Fix is per-agent
buffering via a new `quiet` parameter on query_llm.

Depends on: PR #20 (Phase 10, merged). Blocks: none.

---

## 2026-06-03T15:18:00Z | ara | PR_OPENED

PR #24 opened: "[Fix] Phase 10 — per-agent buffered output to stop parallel stream interleave"
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/24
Branch: agent/ara/fix-parallel-stream-interleave → main
Depends on: PR #20 (merged). Blocks: none.

Tradeoff disclosed in PR body: parallel agents (CodeGen, SelfHealer) no
longer stream live; their full responses print with a per-agent prefix
when the LLM call completes. Analyst still streams live. Total cycle
wall-time unchanged. Awaiting Director review.

---

## 2026-06-03T15:55:00Z | ara | BRANCH_CREATED + PR_OPENED

Branch `agent/ara/fix-bootstrap-task-dataset-mismatch` from `origin/main`
(HEAD 8116bde). PR #25 opened:
"[Fix] Bootstrap: detect task/dataset column-name mismatch"
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/25

User-reported scenario: program.md describes real-estate features
(`size`, `location`, `num_rooms`, target `price`) but the uploaded CSV
was crude-oil-price.csv. The bootstrap prompt included BOTH the stale
task description and the actual dataset preview, and the LLM hallucinated
real-estate column names.

Fix is fully dataset-agnostic: a new `_detect_task_column_mismatch`
detector flags backticked identifiers in the task that aren't in the
actual schema (case-insensitive, library/metric symbols allow-listed).
On mismatch: console warning + prompt block telling the LLM the dataset
is authoritative. New test_task_dataset_mismatch.py covers 6 cases.

Depends on: PR #21 (merged). Blocks: none.

---

## 2026-06-03T16:25:00Z | ara | BRANCH_CREATED + PR_OPENED

Branch `agent/ara/docs-generic-program-md-template` from `origin/main`
(HEAD 856502a). PR #26 opened:
"[Docs] Generic program.md template for any uploaded dataset"
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/26

Adds autoresearch_agent/PROGRAM_MD_TEMPLATE.md — a docs file with a
domain-vocabulary-free task description users can paste into the
frontend instead of starting from a stale real-estate / housing /
retail template. The template only requires the target column name
(optional — defaults to last column); everything else (features, date
formats, schema) comes from the uploaded CSV at runtime.

Pairs with PR #21 (merged) and PR #25 (open) which already make the
codebase dataset-agnostic. Pure docs, no code changes.

Depends on: PR #25 (open — referenced in the doc). Blocks: none.

Follow-up worth noting (not in this PR): setting this template as the
frontend's default task textarea placeholder. Requires Director
approval since it crosses into fe agent territory.

---

## 2026-06-19T19:58:33Z | ara | BRANCH_CREATED

Branch `agent/ara/feat-dashboard-chart-data` created from `origin/main`
(HEAD 502b788). User-requested feature: when evolution completes, the
frontend should pop up a results dashboard with two charts (top = raw
target column, bottom = actual vs predicted) and the validation MSE.

Backend half (ara, this branch) — wholly within ara ownership
(`autoresearch.py`), no LLM calls added, no server.py change:
  1. SYSTEM_PROMPT + bootstrap prompt now instruct every champion to also
     write `dashboard.json` {target_name, target[], y_true[], y_pred[], mse}
     alongside its `val_loss` print (wrapped in try/except; never affects
     val_loss). This rides on the LLM calls evolution already makes.
  2. The backend now emits TWO machine-readable `__EVENT__` lines fe can parse:
     a. Per cycle — `__EVENT__{"type":"cycle_result","cycle":N,"loss":<champion
        best_loss>}` (new `emit_event()` at the director call site). This is the
        REAL loss-over-cycles data; see the heads-up below.
     b. On completion — `emit_dashboard_data()` runs the final champion once
        (plain `python train.py`, NOT an LLM call), reads dashboard.json,
        downsamples each series to <=500 points, and emits ONE
        `__EVENT__{"type":"predictions",...}` line. server.py streams both
        through verbatim.
  Best-effort: a non-compliant champion or a cancelled run simply emits no
  predictions event.

## 2026-06-19T19:58:33Z | ara | BLOCKED:fe

The frontend (UI/UX) half is fe-owned (`frontend/src/App.jsx`). Requesting
fe open a sibling PR to build the completion dashboard against this contract.

Format reuses the parser fe ALREADY has: App.jsx processLine routes
`__EVENT__{json}` through `JSON.parse(line.slice("__EVENT__".length))` and
dispatches on `ev.type`. fe adds a `ev.type === "predictions"` case; the
existing `cycle_result` case now receives real data.

  IMPORTANT heads-up: before this branch the backend emitted NO `__EVENT__`
  lines at all — so the `cycle_result` → lossHistory branch (and anything fe
  believed was "already collected per cycle", incl. the loss sparkline / final
  MSE) was DEAD: nothing fed it. This branch is the first time the backend
  emits `cycle_result`, so fe's loss chart / final-MSE will now have real data
  instead of an empty array.

Stream contract — two event types:

  1. Per cycle (one per completed director cycle):
        __EVENT__{"type":"cycle_result","cycle":N,"loss":<float>}
     loss = champion best_loss after that cycle (== MSE for regression). Drives
     the loss-over-cycles chart; final entry is the final MSE.

  2. On completion (exactly one, BEFORE `[FINAL_CODE_START]…[FINAL_CODE_END]`):
        __EVENT__{"type":"predictions","target_name":...,"target":[...],
                  "y_true":[...],"y_pred":[...],"mse":...}
     SINGLE line, no embedded newlines. Fields (any may be [] / null; the whole
     event may be ABSENT — handle gracefully, no actual-vs-predicted panel if so):
        target_name: "price"   // label for the target column
        target:      [ ... ]   // raw target column, dataset order  → TOP chart
        y_true:      [ ... ]   // validation actuals                ┐ BOTTOM
        y_pred:      [ ... ]   // validation predictions (aligned)  ┘ chart
        mse:         0.0123    // validation MSE (redundant w/ final cycle_result)
     Every list is already capped to <=500 points server-side.

Suggested UI (fe owns final design):
  • Pop up a results modal automatically on stream end.
  • Final MSE — last cycle_result loss.
  • Loss-over-cycles chart — the cycle_result series (now real).
  • Actual-vs-Predicted panel — from the predictions event: top chart = `target`
    (titled `target_name`); bottom = `y_true` vs `y_pred` overlaid, `mse` bottom-right.
  • If the predictions event is absent/empty (classification, synthesis, cancelled
    run), show an honest "no predictions for this task" state — never fabricate.

No merge ordering requirement: both events are purely additive to the stream and
harmless to clients that ignore them. Landing both PRs together gives the intended
UX. fe: please create `agent/fe/<phase>-results-dashboard`.

---

## 2026-06-19T20:30:00Z | ara | PR_OPENED

PR #27 opened: "[Feature] Stream champion chart data (predictions + per-cycle
loss) for results dashboard".
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/27
Branch: agent/ara/feat-dashboard-chart-data → main
Depends on: none. Blocks: none.

Resolves the BLOCKED:fe coordination above. fe is now UNBLOCKED to build the
results-dashboard popup against the two `__EVENT__` contracts (cycle_result,
predictions). No server.py / frontend changes in this PR — purely additive
stream events. Awaiting Research Director review.

---

## 2026-06-19T20:40:00Z | fe | BRANCH_CREATED

Branch `agent/fe/phase-11-results-dashboard` from `origin/main` (HEAD ee9a3f0).
Phase 11 sub-task: completion results dashboard. Consumes ara's two
`__EVENT__` contracts (cycle_result, predictions) defined in the BLOCKED:fe
note above — acknowledging it as UNBLOCKED now that PR #27 is merged.

## 2026-06-19T20:41:00Z | fe | PR_OPENED

PR #28 opened: "[Phase 11] Frontend — champion results dashboard".
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/28
Branch: agent/fe/phase-11-results-dashboard → main
Depends on: #27 (merged). Blocks: none.

Pops up a results modal on stream end: final MSE, loss-over-cycles, raw
target column, and actual-vs-predicted overlay. Honest empty state when the
predictions event is absent — never fabricates. Source-only (App.jsx); built
dist/ intentionally excluded to respect the 400-line limit and avoid bundle
conflicts with the sibling logout PR. Awaiting Research Director review.

---

## 2026-06-19T20:45:00Z | fe | BRANCH_CREATED

Branch `agent/fe/phase-11-logout-button` from `origin/main` (HEAD ee9a3f0).
Phase 11 sub-task: header logout button. Follow-up to the login screen
already on `main` (commit 502b788). Independent of PR #28 (results dashboard).

## 2026-06-19T20:46:00Z | fe | PR_OPENED

PR #29 opened: "[Phase 11] Frontend — header logout button".
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/29
Branch: agent/fe/phase-11-logout-button → main
Depends on: none. Blocks: none.

Adds a header `⏻ Logout` button that clears the sessionStorage auth flag and
returns to the login screen. Source-only (App.jsx), 10 lines. Sibling to
PR #28 — no shared source hunks, no merge ordering requirement between them.
Awaiting Research Director review.

---

## 2026-06-19T21:14:46Z | ara | BRANCH_CREATED

Branch `agent/ara/refactor-dashboard-export-helper` from `origin/main`
(HEAD bed6cb9). Follow-up to PR #27 (merged as ee9a3f0).

Context: PR #27 was squash-merged BEFORE a follow-up helper-refactor commit was
pushed to its branch, so that refactor never reached `main` (a merged branch
can't be reused). Re-applying it cleanly on a fresh branch here.

Problem: the merged Dashboard Export contract asks each champion to inline an
~8-line `dashboard.json` json.dump block. Generated champion code is echoed to
the application console (CodeGen/SelfHealer via _emit_with_prefix) and shown in
the Champion tab, so that boilerplate clutters the user-facing output.

Fix (ara ownership only): new `autoresearch_agent/dashboard_export.py` holds the
tolist/subsample/try-except/json.dump logic; SYSTEM_PROMPT + bootstrap prompt now
ask the champion for ONE line — `import dashboard_export;
dashboard_export.dump(target_name=..., target=..., y_true=..., y_pred=..., mse=...)`.
`main()` stages the helper into the per-run cwd; run_in_sandbox copies it into
each candidate sandbox, so it's importable for candidates and the final run.

fe-facing contract UNCHANGED — same `cycle_result` + `predictions` events and
payload shape that PR #28 already consumes. No fe action required.
Depends on: none (origin/main already has the events). Blocks: none.

## 2026-06-19T21:16:00Z | ara | PR_OPENED

PR #31 opened: "[Refactor] Move dashboard export into helper module (de-noise
console)".
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/31
Branch: agent/ara/refactor-dashboard-export-helper → main
Depends on: none. Blocks: none. Re-lands the PR #27 follow-up that the squash
merge missed. No server.py / frontend changes. Awaiting Research Director review.

---

## 2026-06-19T21:15:00Z | fe | BRANCH_CREATED

Branch `agent/fe/phase-11-tab-title` from `origin/main` (HEAD bed6cb9, with
PR #28 + #29 already merged). Phase 11 chore: set the browser tab title.

## 2026-06-19T21:16:00Z | fe | PR_OPENED

PR #30 opened: "[Phase 11] Frontend — set browser tab title to \"Self-Evolving\"".
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/30
Branch: agent/fe/phase-11-tab-title → main
Depends on: none. Blocks: none.

Single-line change: `index.html` `<title>` from the Vite default `frontend`
to `Self-Evolving`. Awaiting Research Director review.

---

## 2026-06-20T12:42:32Z | ara | BRANCH_CREATED

Branch `agent/ara/fix-dockerfile-dashboard-helper` from `origin/main` (HEAD
f58483c). Runtime bug from merged PR #31.

Symptom (reported from a deployed container):
  `[*] Could not stage dashboard_export helper: [Errno 2] No such file or
   directory: '/research/dashboard_export.py'`

Root cause: PR #31 added `dashboard_export.py` to source and `main()` stages it
from the autoresearch.py directory (`/research/` in the image), but the
Dockerfile copies files individually — `COPY ./autoresearch.py` and
`COPY ./server.py` — and was never updated to copy the new helper. So the file
is in `main` but absent from the image; staging fails and no `dashboard.json`
(hence no `predictions` event) is produced.

Fix (ara ownership — Dockerfile): add
  `COPY ./dashboard_export.py /research/dashboard_export.py`
alongside the existing copies. The staging failure was already best-effort
(caught, non-fatal), so the run still completes — this restores the dashboard.

Depends on: PR #31 (merged). Blocks: none.

## 2026-06-20T12:44:00Z | ara | PR_OPENED

PR #32 opened: "[Fix] Dockerfile: copy dashboard_export.py into the image".
URL: https://github.com/Xeeshanmalik/autonomous_coding_agent_advanced/pull/32
Branch: agent/ara/fix-dockerfile-dashboard-helper → main
Depends on: PR #31 (merged). Blocks: none. Restores the dashboard.json ->
predictions path in the deployed container. Awaiting Research Director review.

NOTE: requires an image REBUILD to take effect — the running container must be
rebuilt/redeployed from this commit for the helper to appear at /research/.

## 2026-06-21T10:13:14Z | ara | BRANCH_CREATED

Branch agent/ara/fix-dashboard-target-validation-align created from origin/main
for a dashboard fix in autoresearch_agent/dashboard_export.py (ara ownership).
dump() now derives the exported `target` field from `y_true` so the Target
chart and the Actual-vs-Predicted "actual" line always show the same validation
rows, regardless of what the champion passes as `target`. No schema/key change,
so no frontend (fe) coordination required. Depends on: none. Blocks: none.

## 2026-06-21T11:35:31Z | fe | BRANCH_CREATED

Branch agent/fe/phase-11-chart-gap-rendering created from origin/main for a
frontend-only fix in frontend/src/App.jsx (fe ownership). ResultsChart was
dropping points in the bottom Actual-vs-Predicted chart: a null prediction
plotted at the floor and a shorter predicted series produced a NaN coordinate
that truncated the SVG polyline after the first gap. Fix renders each series as
contiguous finite segments so missing values leave a gap. Pure render change —
no API/stream/schema change, no ara/inf coordination required. Complements the
already-merged ara backend fix (5d6b5d1, target derived from y_true). Depends
on: none. Blocks: none. PR open pending (no gh/credentials in this
environment — opening via web compare URL).
