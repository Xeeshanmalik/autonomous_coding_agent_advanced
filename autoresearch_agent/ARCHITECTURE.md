# AutoResearch Agent — Architecture

The AutoResearch service runs a **self-evolving research loop**: given a task
(`program.md`), a baseline script (`train.py`), and an optional dataset, it
repeatedly asks an LLM to improve the script, evaluates each candidate in a
CPU-only sandbox, and keeps the lowest-`val_loss` champion — streaming progress
and chart data to the frontend the whole time.

The implementation lives in the **`ara`** package. The top-level `autoresearch.py`
is a thin entrypoint shim (so `server.py` and the Dockerfile invocation are
unchanged); `server.py` owns the HTTP surface; `dashboard_export.py` is a helper
staged into each run at runtime.

## Run lifecycle (process view)

```
frontend ──POST /run──► server.py
                          │  writes per-run workdir /tmp/run_<uuid>/:
                          │    program.md  (= task)
                          │    train.py    (= baseline)
                          │    <dataset>   (optional upload)
                          │
                          └─ Popen("python -u autoresearch.py", cwd=workdir)
                                       │
                          autoresearch.py (shim) ─► ara.cli.run() ─► ara.cli.main()
                                       │
                                       ▼
                          asyncio.run(ara.orchestrator.research_director(...))
                                       │
                          stream stdout ──► server.py ──► frontend
                          (plain logs + __EVENT__{json} telemetry lines)
```

Cancellation: `server.py /cancel` sends SIGTERM to the process group →
`ara.lifecycle` flips a flag → the LLM stream aborts and the cycle loop exits 0.

## Per-cycle data flow (one `director_one_cycle`)

```
            ┌─────────────────────── Research Director ───────────────────────┐
            │  (ara/orchestrator.py)                                            │
 parent ◄───┤  select_parent(population)            adaptive temps (Phase 5)    │
            │        │                                                          │
            │        ▼                                                          │
            │   Analyst ───────────────► weakness bullets   (ara/analysis.py)   │
            │        │                                                          │
            │        ▼  _build_research_messages (cacheable prefix, Phase 4)    │
            │   K × CodeGen  (parallel) ─► candidate scripts (ara/agents.py)    │
            │        │                                                          │
            │        ▼                                                          │
            │   K × EvalWorker (parallel) ─► robust_eval ─► sandbox (Phase 1/8) │
            │        │                         (ara/evaluation.py, ara/sandbox) │
            │        ▼                                                          │
            │   crashed? ─► SelfHealer (parallel, opt-in) ─► re-eval (Phase 10) │
            │        │                                                          │
            │        ▼                                                          │
            │   best valid candidate ─► update_population (Phase 2)             │
            │        │                                                          │
            │        ├─ breakthrough? ► write train.py + git_commit_champion    │
            │        ├─ save_population / save_checkpoint   (Phase 6)            │
            │        ├─ append experiment_log; compress every N (Phase 7)       │
            │        └─ emit __EVENT__ cycle_result ─► frontend chart           │
            └──────────────────────────────────────────────────────────────────┘
```

On normal completion, `cli.main` runs the champion once more and streams a
`predictions` event (`ara/dashboard.py`) for the Actual-vs-Predicted chart.

## Module map (where each phase lives)

| Phase / concern | Module | Key symbols |
|---|---|---|
| Configuration (all env settings, paths) | `ara/config.py` | `LLM_URL`, `MODEL`, `CANDIDATE_POOL_SIZE`, `ENABLE_SELF_HEALER`, … |
| Process lifecycle / cancellation (Phase 9) | `ara/lifecycle.py` | `_handle_sigterm`, `_check_cancel` |
| System prompts | `ara/prompts.py` | `SYSTEM_PROMPT`, `ANALYSIS_SYSTEM_PROMPT` |
| Output parsing | `ara/parsing.py` | `extract_code_block`, `extract_val_loss` |
| LLM transport + dispatch (Phase 4 caching) | `ara/llm/` | `query_llm`, backends, `_post_with_retry` |
| Sandboxed execution | `ara/sandbox.py` | `run_in_sandbox`, `run_cmd`, `CandidateResult`, `classify_candidate_failure` |
| Evaluation + variance reduction (Phase 1/8) | `ara/evaluation.py` | `robust_eval`, `run_candidate_pool` |
| Population selection (Phase 2) | `ara/population.py` | `Population`, `select_parent`, `update_population` |
| Stage-A analysis (Phase 3) | `ara/analysis.py` | `analyze_baseline` |
| Dataset introspection | `ara/dataset_introspect.py` | date inference, column extraction, mismatch detection |
| Baseline bootstrap | `ara/bootstrap.py` | `generate_baseline_from_task`, `bootstrap_baseline_if_needed` |
| Checkpointing + git (Phase 6) | `ara/checkpoint.py` | `save_checkpoint`, `load_checkpoint`, `git_commit_champion` |
| Experiment history (Phase 7) | `ara/history.py` | `compress_history`, `format_history_hint` |
| Self-healing (sync, legacy) | `ara/healing.py` | `execute_and_heal` *(currently unused)* |
| Dashboard telemetry | `ara/dashboard.py` | `emit_event`, `emit_dashboard_data` |
| Multi-agent harness (Phase 10) | `ara/agents.py` | `analyst_agent`, `code_gen_agent`, `eval_worker`, `self_healer_agent` |
| Orchestration (Phase 10) | `ara/orchestrator.py` | `director_one_cycle`, `research_director` |
| Entrypoint | `ara/cli.py` | `main`, `run` |

## Dependency layering (no import cycles)

```
config · lifecycle · prompts · parsing          (leaves: settings, signals, text)
        ↓
llm  (query_llm)                                 (talk to the model)
        ↓
sandbox · evaluation · population · analysis ·   (domain services)
dataset_introspect · bootstrap · checkpoint ·
history · healing · dashboard
        ↓
agents → orchestrator                            (Phase-10 harness)
        ↓
cli                                              (entrypoint)
```

## Conventions worth knowing

- **Patchable references go through the module object.** Code reads
  `llm.query_llm`, `sandbox.run_in_sandbox`, `config.ENABLE_SELF_HEALER`,
  `lifecycle._sigterm_received` via attribute access (not `from x import name`)
  so a single monkeypatch/override is seen everywhere. The smoke test relies on
  this; `ara.llm.query_llm` and `ara.sandbox.run_in_sandbox` are the canonical
  patch points.
- **Working-directory contract.** `cli.main` reads `program.md`/`train.py` by
  relative path — the process must run with `cwd` = the per-run workdir (set by
  `server.py`).
- **Telemetry never breaks a run.** Everything in `dashboard.py` is best-effort
  and swallows its own errors.

## Known smells (documented, not changed in the refactor)

- `extract_val_loss` regex doesn't match negative / scientific-notation losses.
- The non-streaming (`stream=False`) LLM path parses SSE lines; only the
  streaming path is exercised.
- `evaluation.run_candidate_pool` and `healing.execute_and_heal` are retained but
  unused by the current Phase-10 flow.
