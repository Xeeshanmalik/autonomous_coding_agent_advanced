# Autonomous Coding Agent — Technical Documentation

**Audience:** Engineering management / technical stakeholders
**Scope:** Full codebase review (`autoresearch_agent/`, `frontend/`, `inference_server/`, `inference_server_reasoning/`, governance docs)
**Status as of:** 2026-06-18

---

## 1. Executive Summary

This repository implements a **self-hosted, autonomous ML research system**: given a task definition and a dataset, it iteratively writes, runs, evaluates, and rewrites Python training scripts — using an LLM as the "researcher" — until it converges on a champion model. It is a closed-loop, evolutionary code-optimization system, not a static ML pipeline.

It is composed of three deployable services:

| Service | Role | Tech |
|---|---|---|
| `frontend/` | Web UI to configure tasks, start/stop runs, watch live progress, inspect the winning code | React (Vite) + nginx |
| `autoresearch_agent/` | The evolutionary engine — generates, sandboxes, scores, and evolves candidate ML scripts | Python, FastAPI |
| `inference_server/` + `inference_server_reasoning/` | Self-hosted LLM backends (no external API dependency required) | llama.cpp (`llama-server`) on CUDA |

A second, equally notable artifact of this project is **how it was built**: the codebase itself was developed by a small fleet of autonomous coding agents (one per service) coordinating through a written governance protocol (`AGENTS.md`) and an append-only audit trail (`agent_log.md`), rather than by a single engineer or a traditional human team. That log shows 21+ PRs merged across 11 planned phases plus several post-launch hotfixes, which is itself a useful data point on the maturity and traceability of the system.

**Bottom line for management:** the core algorithm is sound, reasonably sophisticated (population-based search, two-stage prompting, prompt caching, checkpoint/resume, self-healing), and has already been hardened through real production incidents (documented below). The main open risks are operational/infra polish, not algorithmic — see §7.

---

## 2. System Architecture

```
                         ┌─────────────────────────────────────────┐
                         │              Browser (User)              │
                         └───────────────────┬───────────────────────┘
                                              │ HTTPS
                         ┌────────────────────▼────────────────────┐
                         │   frontend (nginx, unprivileged, :8080)   │
                         │   React SPA: task synthesis, run control, │
                         │   live log/loss stream, "Champion" diff   │
                         └──────────┬─────────────────┬─────────────┘
                     /agent/ →      │                 │   /autoresearch/ →
                                    ▼                 ▼
                  ┌──────────────────────┐   ┌──────────────────────────┐
                  │ inference_server(s)   │   │ autoresearch_agent        │
                  │ llama-server (8080)   │   │ FastAPI server.py (8000)  │
                  │ - Qwen2.5-Coder-7B    │   │ → spawns autoresearch.py  │
                  │ - DeepSeek-R1-Distill │   │   per run, streams stdout │
                  │   -Qwen-32B (Q3_K_M)   │   └──────────────────────────┘
                  └──────────────────────┘
        All containers share a Docker bridge network ("research-net")
```

- The frontend never talks to the LLM or the evolutionary engine directly from the browser — nginx terminates the connection and reverse-proxies to two distinct upstream paths:
  - `/agent/` → the DeepSeek backend, used for **task synthesis** (turning a vague prompt into a structured task definition).
  - `/autoresearch/` → `autoresearch_agent`'s FastAPI server, which owns the actual run lifecycle (`POST /run`, `POST /cancel/{run_id}`).
- `autoresearch_agent` itself talks to an LLM backend (local llama.cpp, or optionally Gemini/Anthropic if an API key is supplied) to generate and refine candidate training scripts, and to a local Python subprocess sandbox to execute them.
- The two inference containers are independent deployable units, each with their own `Dockerfile`, GPU offload tuning, and context window — they are not interchangeable without coordinated config changes (see §6).

---

## 3. The Evolutionary Engine (`autoresearch_agent/autoresearch.py`, ~1,600 lines)

This is the intellectual core of the project. It is best understood as a **genetic algorithm over source code**, where the "mutation operator" is an LLM call instead of a random bit-flip.

### 3.1 Core loop, at a glance

1. **Bootstrap** — establish a baseline `train.py` and its `val_loss` (auto-generated if the user didn't supply one).
2. **Candidate generation** — an LLM proposes N candidate modifications to the current best code, in parallel.
3. **Sandboxed execution** — each candidate runs as an isolated subprocess; its stdout is parsed for a `val_loss` metric.
4. **Selection** — candidates are scored and a new "population" is formed using softmax-weighted sampling (not greedy argmin), so the search doesn't collapse onto a single local optimum too early.
5. **Repeat** — the loop runs for a configured number of iterations, periodically checkpointing so a crashed or interrupted run can resume exactly where it left off.

### 3.2 Notable engineering decisions (the "why" behind the phases)

| Capability | Mechanism | Why it matters |
|---|---|---|
| **Parallel candidates** | `ThreadPoolExecutor` fans out N candidate evaluations concurrently | Without this, evaluating N ideas per generation is N× slower — directly impacts wall-clock cost per experiment |
| **Population selection** | `Population` class + `select_parent` using Boltzmann/softmax sampling over fitness, with overflow-safe normalization | Prevents premature convergence — pure "keep only the best" search gets stuck; sampling preserves exploration |
| **Two-stage prompting** | A separate "Analyst" LLM call reasons about *why* the last result improved/regressed before a "CodeGen" call writes the next candidate | Splitting "diagnose" from "write code" measurably improves code-gen quality versus a single combined prompt, at the cost of one extra LLM round-trip |
| **Prompt caching** | Anthropic native `/v1/messages` calls use `cache_control: {"type": "ephemeral"}` breakpoints | Cuts token cost/latency materially on long-running sessions where most of the prompt (system instructions, history) repeats every turn |
| **Adaptive temperature** | Cosine-annealed sampling temperature across iterations | Encourages broad exploration early, convergence/exploitation late — a standard optimization heuristic applied to LLM sampling |
| **Checkpoint/resume** | `save_checkpoint` / `load_checkpoint` persist population + experiment state to disk | A multi-hour run surviving a container restart without losing progress is an operational necessity, not a nice-to-have |
| **Experiment history compression** | `compress_history` summarizes older iterations before they're re-injected into future prompts | Keeps the prompt within the model's context window as the run grows, without losing the "lessons learned" signal entirely |
| **Variance reduction** | `robust_eval` re-runs near-frontier candidates multiple times and takes the median | ML training runs have run-to-run noise; without this, the search can promote a "lucky" bad candidate over a consistently good one |
| **Self-healing repair loop** | `execute_and_heal` catches a crashing candidate and asks the LLM to fix the traceback before discarding it | Materially increases the fraction of LLM-generated code that survives to evaluation, instead of wasting an entire generation slot on a syntax error |
| **Async multi-agent harness (Phase 10)** | `asyncio.gather` coordinates Director / Analyst / CodeGen / EvalWorker / SelfHealer roles, bridging blocking HTTP/subprocess calls via `asyncio.to_thread` | The most structurally complex phase — turns the loop from a simple sequential script into a small internal multi-role pipeline, improving throughput further |
| **Graceful cancellation** | `server.py`'s `/cancel/{run_id}` sends SIGTERM to the run's process group, escalating to SIGKILL if it doesn't exit | Lets a user abort a long run from the UI without leaving orphaned subprocesses on the host |

### 3.3 Dataset-agnostic bootstrap robustness

Several hardening features exist specifically so the system can be pointed at an arbitrary CSV without per-dataset hand-tuning:

- **Date-format auto-detection** (`DATE_FORMATS_TO_TRY`, day-first preferred) — avoids silent mis-parsing of ambiguous date columns.
- **Task/dataset column-name mismatch detection** (`_detect_task_column_mismatch`) — catches the common failure mode where a user's task description references a column name that doesn't actually exist in the uploaded data, and surfaces it early instead of letting the LLM hallucinate around it.
- **Authoritative column-list injection** — the actual column names/dtypes are injected verbatim into prompts rather than relying on the LLM to infer them, reducing hallucinated-column errors.

### 3.4 The `val_loss` abstraction

`val_loss` is a deliberately generic, LLM-chosen, "lower is better" fitness signal, extracted from candidate stdout via a regex (`autoresearch.py:117-120`), not hardcoded to a specific metric like MSE. In practice, for regression tasks the LLM typically does emit MSE (this was confirmed by inspecting a live run during this review — a `GradientBoostingRegressor` baseline against a synthetic target column reported `val_loss=55.68`, which is the literal MSE on that column's scale, not a normalized 0–1 score). This is worth stating plainly to management: **MSE is not a percentage and is not bounded to [0,1]** — it scales with the variance of the target variable, so absolute val_loss numbers are only meaningful relative to other runs on the *same* dataset/target, not as a universal quality bar.

### 3.5 `server.py` (131 lines)

A thin FastAPI wrapper around the engine:
- `POST /run` — accepts task/baseline/iterations/model-choice/API-key/optional dataset file as multipart form data, creates a per-request `/tmp/run_{uuid}` working directory, launches `autoresearch.py` as a subprocess, and streams its stdout back to the client. The final winning code is wrapped in `[FINAL_CODE_START]...[FINAL_CODE_END]` sentinel markers for the frontend to extract.
- `POST /cancel/{run_id}` — terminates that run's process group.

---

## 4. Frontend (`frontend/src/App.jsx`, ~1,490 lines)

A single-page React app (Vite build, served by nginx) with no separate backend of its own — it is purely a client for the two proxied services described in §2.

Key features actually implemented:
- **Task Synthesiser** — an LLM-assisted flow that turns an informal description into a structured task definition, using the DeepSeek backend via `/agent/`.
- **Tabs** for Generate / Task / Baseline / Config, and a **Baseline Bootstrap modal** for triggering/inspecting the auto-generated baseline.
- **Streaming log parser** — manually buffers and parses the raw HTTP stream from `/autoresearch/run` line-by-line, recognizing three line types: plain log text, `__RUN_ID__:<id>` (captured once at stream start, used for cancellation), and `__EVENT__{json}` structured events (e.g. `{"type":"cycle_result","cycle":3,"loss":0.18,...}`).
- **Live loss sparkline** — an inline SVG chart driven by the parsed loss events, giving a real-time visual of convergence during a run.
- **"Champion" tab** — a client-side **Myers diff** implementation (`computeDiff`/`buildHunks`) renders a green/red line diff between the baseline and the final winning code, so a reviewer can see exactly what the agent changed without reading the whole file.
- **Run control** — `startEvolution` posts to `/autoresearch/run`; `handleStop` posts to `/autoresearch/cancel/{id}`.

---

## 5. Infrastructure / Deployment

### 5.1 Three+ container topology

| Container (image) | Base | Non-root user | Port | Purpose |
|---|---|---|---|---|
| `frontend` | `nginxinc/nginx-unprivileged:1.25-alpine-slim` (multi-stage, built from `node:20-alpine`) | UID 101 | 8080 | Static SPA + reverse proxy |
| `autoresearch_agent` (`ai-researcher`) | UBI9 → UBI9-minimal | `researcher:10002` | 8000 | Evolution engine + FastAPI |
| `inference_server` (Qwen) | `nvidia/cuda:12.2.2-devel/runtime-ubi9` | `llmuser:10001` | 8080 | Code-gen LLM, `-c 16384 -ngl 99 --parallel 4 --mlock` |
| `inference_server_reasoning` (DeepSeek, runs as `local-deepseek-backend`) | same CUDA base | `llmuser:10001` | 8080 | Reasoning LLM, `-c 8192 -ngl 61 -fa on -np 1 --no-warmup` |

All four are wired together by a shared Docker bridge network (`research-net`) and are each built with multi-stage Dockerfiles and non-root execution — a sensible security baseline (no container runs as root in its final stage).

### 5.2 GPU footprint

The DeepSeek-R1-Distill-Qwen-32B Q3_K_M model is ~14.8 GB on disk. The Dockerfile comment claims it's "guaranteed to fit 100% in your 16GB VRAM," but live `nvidia-smi` inspection during this engagement showed the actual card is a **24GB Quadro RTX 6000**, not a 16GB card — the in-repo comment is stale and should be corrected to avoid misleading future infra decisions. The current entrypoint partially offloads (`-ngl 61` out of the model's full layer count, deliberately "spilling" some layers to CPU) — that headroom is what allowed today's context-window fix (below) to land safely.

### 5.3 Multi-agent software development governance

This repository was built under a written multi-agent protocol (`AGENTS.md`, `agent_log.md`, and per-directory `CLAUDE.md` files), worth highlighting separately because it explains *why* the codebase is structured the way it is:

- Each service directory has exactly one owning "agent" (`ara` = autoresearch, `fe` = frontend, `inf` = inference server), with hard rules against editing outside one's own directory without a Director-approved log entry.
- Branches follow `agent/<abbrev>/phase-<N>-<slug>`; one phase per branch, one branch per PR (capped at 400 changed lines), and **no agent may merge its own PR**.
- A merge-dependency graph in `implementation.md`/`AGENTS.md` governs sequencing (e.g., Phase 2's population logic is blocked until Phase 1's parallel-candidate plumbing merges).
- `agent_log.md` is an append-only audit trail: every branch creation, PR open, rebase, and merge is logged before the action is taken, including explicit `BLOCKED:<agent>` markers when one service is waiting on another (e.g., a frontend stream-protocol change blocked on the autoresearch agent's API contract).

For management, the practical takeaway is that this isn't an ungoverned pile of agent output — there is a real (if informal) process model with traceability, and the log shows it being followed in practice across 21+ logged `PR_OPENED` events and the corresponding merges.

---

## 6. Issues Found and Fixed During This Review

Two live production defects were diagnosed and fixed as part of this engagement, both now committed:

1. **nginx upstream resolution failure** (`frontend/nginx.conf`) — the `/agent/` proxy pointed at a hostname (`local-qwen-backend`) that didn't match the container actually running on the shared network (`local-deepseek-backend`), causing `nginx: [emerg] host not found in upstream`. Fixed by correcting the `proxy_pass` target.
2. **LLM context-window overflow** (`inference_server_reasoning/Dockerfile`) — the DeepSeek backend was configured with `-c 4096`, but the bootstrap prompt the engine sends is consistently ~5,600+ tokens, producing an HTTP 400 ("request exceeds context size"). Root-caused via Dockerfile inspection, then verified against live `nvidia-smi` VRAM headroom (~7.6 GB free at the old settings) before bumping context to `-c 8192`, confirmed to fit with margin.

These are recorded here primarily as evidence of the system's current operational maturity: the architecture is sound, but it has been under active, hands-on tuning right up to recent runs — not a finished, "set and forget" product yet.

---

## 7. Known Risks, Limitations, and Recommendations

| # | Finding | Why it matters | Recommendation |
|---|---|---|---|
| 1 | `autoresearch_agent/Dockerfile` clones `github.com/karpathy/autoresearch.git` at build time, then immediately overwrites the two files that matter (`autoresearch.py`, `server.py`) with the repo's own versions (Dockerfile lines 12, 79–80). | The clone step is vestigial — it pulls an external, unpinned upstream repository whose only surviving artifact is a `prepare.py` file that the build `chmod`s but the current code never calls. This is a supply-chain and build-fragility risk (an unrelated upstream repo going private/renamed/force-pushed breaks the build) for zero functional benefit today. | Remove the `git clone` step; inline only the actual `requirements.txt` needed and drop dependencies the current code doesn't use (`torch`, `sdv`, `copulas`, `ctgan`, `imbalanced-learn` are installed but not referenced by `autoresearch.py`/`server.py`'s sandboxed-script constraints, which restrict candidates to scikit-learn). This will also shrink the image and reduce its dependency-vulnerability surface. |
| 2 | Stale hardware assumption in `inference_server_reasoning/Dockerfile` comments (claims 16GB VRAM card; actual hardware is 24GB). | Future tuning decisions (e.g., `-ngl`, `-c`) made by reading the comment instead of `nvidia-smi` could under-utilize available GPU memory or, worse, be applied unmodified to a genuinely 16GB deployment where they'd now overflow. | Correct the comment to reflect actual measured VRAM, and prefer a startup script that probes `nvidia-smi` over hardcoded assumptions if this is meant to run on heterogeneous hardware. |
| 3 | Two independent LLM backends (Qwen coder, DeepSeek reasoning) each have separately hand-tuned context/offload flags, with no automated check that they stay within VRAM budget when run together on the same card. | The context-size incident in §6 happened because a config change in one container's effective prompt size wasn't validated against the other container's resource footprint until it broke in production. | Add a lightweight CI/build-time check (or at least a documented VRAM budget table) that totals expected VRAM usage of both backends running concurrently, so future flag changes get caught before deployment. |
| 4 | `agent_log.md`-driven governance is currently a manual, convention-based protocol (agents are trusted to log before acting, not enforced by tooling). | Works today, but provides no hard guarantee against a future agent run skipping the log step, especially under context-window pressure or task interruption. | If this multi-agent development pattern is going to scale to more services/agents, consider a pre-commit or pre-push hook that mechanically blocks a push without a matching `agent_log.md` entry, rather than relying on every agent run to remember the convention. |
| 5 | `val_loss` is a free-form, LLM-emitted number with no enforced units or normalization across runs. | Cross-run/cross-dataset comparisons of "val_loss = X" are not meaningful without knowing what metric and target scale produced them (see §3.4). | If this system is going to be used to compare results across different datasets/tasks for a leaderboard or reporting purpose, consider standardizing on a normalized metric (e.g., R² or normalized RMSE) for cross-task comparability, while keeping raw `val_loss` for within-task optimization. |

---

## 8. Project Maturity Summary

- **Algorithmic core:** All 10 originally planned engine phases (parallel candidates, population selection, two-stage prompting, prompt caching, adaptive temperature, checkpointing, experiment history, variance reduction, server process management, multi-agent harness) are implemented and merged, per both direct code inspection and the `agent_log.md` audit trail.
- **Post-launch hardening:** At least five hotfixes have already shipped after initial launch — a `select_parent` numeric-overflow fix, baseline-bootstrap gating, bootstrap date-format detection, a stream-interleaving fix, and task/dataset column-mismatch detection — indicating the team (human + agents) is actively responding to real failure modes rather than treating the system as done.
- **This engagement** added two more real fixes (nginx upstream hostname, LLM context-window sizing) and surfaced five further findings (§7) that are recommended for the next iteration.

**Recommendation for management:** the system is functionally complete against its original design and already self-correcting in response to production issues. The highest-leverage next investments are the Dockerfile/dependency cleanup (item 1) and a VRAM/config budget check (item 3), both of which are small, contained changes that materially reduce operational surprise risk without touching the core algorithm.
