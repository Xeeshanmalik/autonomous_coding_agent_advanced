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
