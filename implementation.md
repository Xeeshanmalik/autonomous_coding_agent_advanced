# Implementation Plan: Autonomous Coding Agent — Agent Harness Enhancements

## Current Architecture Baseline

| Component | Current behaviour | Core weakness |
|---|---|---|
| `autoresearch.py` | Sequential loop: generate → run → score → keep/revert | One candidate per cycle; no memory across cycles |
| `execute_and_heal` | Linear retry (up to 3 heals) | Sequential; no parallel fix strategies |
| `query_llm` | Always sends raw baseline + temp=0.3 | No caching, no adaptive exploration |
| `server.py` | Spawns subprocess, streams stdout | No cancel, no isolation, single request at a time |
| Frontend | Single-stream log view | No per-cycle diff, no live loss chart |

---

## Phase 1 — Parallel Candidate Generation (Highest impact, ~3–5× throughput)

**Problem:** Cycles are fully sequential. One LLM call + one 300s eval = one data point per cycle.

**Fix:** Use `concurrent.futures.ProcessPoolExecutor` to run K candidates in parallel inside each cycle. Each candidate gets its own temp directory (`/tmp/run_{id}/`) so they never touch each other's `train.py`.

```
Cycle N (current):  [generate → run → score]        → 1 result / cycle
Cycle N (proposed): [gen₁ ─┐
                    gen₂ ──┼─ run all ─ score all]  → K results / cycle, pick best
                    gen₃ ─┘
```

**Where to change:** `autoresearch_agent/autoresearch.py` — replace the inner body of the `while iteration <= max_iterations` loop with a `run_candidate_pool(k=3)` function.

**Specific implementation:**
- Create `run_in_sandbox(code, workdir)` that copies env + `train.py` to an isolated tempdir and runs it there.
- Call it via `ThreadPoolExecutor(max_workers=K)`.
- Pick the minimum-loss result with `min(results, key=lambda r: r.loss)`.
- Discard the rest.

---

## Phase 2 — Population-Based Champion Selection (Diversity, escapes local minima)

**Problem:** Single greedy champion → every cycle mutates the same code → converges early.

**Fix:** Maintain a **population of P=3 best scripts**. Each cycle, sample one parent from the population using softmax-weighted selection (lower loss = higher probability), mutate it, evaluate K children, add the best child to the population if it beats the worst current member, prune population back to P.

```python
# Population entry
{"code": str, "loss": float, "cycle": int, "description": str}
```

**Where to change:** `autoresearch_agent/autoresearch.py` — replace `best_loss` + `best_code` scalars with a `Population` dataclass. Save population state to `population.json` for resumability (see Phase 6).

---

## Phase 3 — Structured Two-Stage Prompting (Better code quality)

**Problem:** The LLM jumps straight from task description to code. No analysis step means it often proposes changes that are algorithmically wrong for the task type.

**Fix:** Split each cycle into **two LLM calls**:

**Stage A — Analysis call** (cheap, ~200 tokens output):
```
"Analyze this baseline. In 3 bullet points, identify the top 3 specific mathematical
 weaknesses. Output ONLY the bullet list."
```

**Stage B — Coding call** (normal, uses Stage A output as additional context):
```
"Given these identified weaknesses: {stage_a_output}
 Implement exactly ONE targeted fix addressing weakness #N.
 Output complete corrected code in ```python block."
```

This forces focused, scoped improvements and reduces the "hallucinate a new algorithm" failure mode from ~30% to near-zero.

**Where to change:** `autoresearch_agent/autoresearch.py` — add `analyze_baseline(code)` function returning a structured weakness report; pass its output into `query_llm` as an extra user message.

---

## Phase 4 — Prompt Caching via Anthropic SDK (Cost + latency reduction)

**Problem:** The 800-token system prompt + baseline code are re-sent to the LLM on **every single call** — both outer research calls and inner healing calls. With Gemini/Claude APIs this costs money and adds latency on every request.

**Fix:** Add `cache_control: {"type": "ephemeral"}` breakpoints at:
1. After the system prompt (it never changes across the run)
2. After the baseline code block (it never changes — already frozen as `baseline_code`)

```python
# Before (all messages sent fresh each time):
messages = [{"role": "system", "content": SYSTEM_PROMPT}, ...]

# After (cache the stable prefix):
messages = [
    {"role": "system", "content": [
        {"type": "text", "text": SYSTEM_PROMPT,
         "cache_control": {"type": "ephemeral"}}   # cache breakpoint
    ]},
    {"role": "user", "content": [
        {"type": "text", "text": f"Baseline:\n```python\n{baseline_code}\n```",
         "cache_control": {"type": "ephemeral"}},   # cache breakpoint
        {"type": "text", "text": program_instructions}
    ]}
]
```

Anthropic's prompt cache has a 5-min TTL. Since research cycles take 2–10 minutes and the system prompt is stable, cache hit rate is ~85%+, reducing per-cycle token cost by ~75%.

**Where to change:** `autoresearch_agent/autoresearch.py` — in `query_llm`, detect if using Anthropic SDK and restructure `messages` with cache breakpoints. The existing Gemini/OpenAI path uses plain dicts and is unchanged.

---

## Phase 5 — Adaptive Temperature + Exploration Schedule

**Problem:** `temperature=0.3` is fixed for every cycle. Early cycles need diversity (high temp), late cycles need exploitation (low temp).

**Fix:** Pass `cycle_number / max_cycles` as a ratio into `query_llm` and compute:

```python
# Cosine annealing from 0.8 to 0.1
import math
temp = 0.1 + 0.7 * 0.5 * (1 + math.cos(math.pi * cycle_ratio))
```

Also use **different temperatures per candidate** in the parallel pool (Phase 1):
- Candidate 0: low temp (exploitation, refine champion)
- Candidate 1: mid temp (balanced)
- Candidate 2: high temp (exploration, try something new)

This implements a natural explore/exploit trade-off without any extra LLM calls.

**Where to change:** `autoresearch_agent/autoresearch.py` — add `temp` parameter to `query_llm`; compute per-cycle temperature in the outer loop.

---

## Phase 6 — State Persistence & Resumability

**Problem:** If the Docker container crashes or the user stops the run, all progress is lost. The agent must restart from scratch.

**Fix:** Write a `checkpoint.json` after every cycle:
```json
{
  "iteration": 7,
  "best_loss": 0.142,
  "population": [...],
  "history": [
    {"cycle": 1, "loss": 0.31, "description": "added polynomial features"},
    ...
  ],
  "baseline_code": "...",
  "started_at": "2026-05-21T..."
}
```

On startup, `main()` checks for `checkpoint.json`. If found, loads state and resumes from `iteration + 1`.

Also integrate with the **Git baseline already configured in the Dockerfile**: after each improvement, `git commit -m "cycle {N}: loss {best_loss}"` the winning `train.py`. This gives a full improvement timeline that is queryable and human-readable.

**Where to change:** `autoresearch_agent/autoresearch.py` — add `save_checkpoint()`, `load_checkpoint()`, and a `git_commit_champion()` call after each breakthrough.

---

## Phase 7 — Richer Experiment History Context (LLM learns from its own past)

**Problem:** The LLM receives the same context every cycle — it has no idea what was already tried and failed. This causes it to re-propose the same improvements.

**Fix:** Build a running `experiment_log` and include a compressed summary in each research prompt:

```
Previous attempts (do NOT re-propose these):
- Cycle 2: Added StandardScaler → loss 0.31 (no improvement)
- Cycle 4: Switched to GradientBoosting → loss 0.18 (BREAKTHROUGH)
- Cycle 5: Added feature interactions → loss 0.21 (regression)
Champion method: GradientBoosting. Weakness: no hyperparameter tuning.
```

Cap the history summary at 500 tokens using a "compression LLM call" every 5 cycles to avoid context overflow.

**Where to change:** `autoresearch_agent/autoresearch.py` — add `experiment_log: List[dict]` to checkpoint; add `compress_history()` function; inject top 5 most recent entries into the research prompt.

---

## Phase 8 — Multi-Run Variance Reduction

**Problem:** ML training is stochastic. A script might report `val_loss=0.15` on one run and `val_loss=0.21` on the next (random seed, data shuffling). The agent currently crowns a "breakthrough" based on a single noisy measurement.

**Fix:** For candidates that come within 5% of `best_loss`, run them **3 times and take the median**:

```python
def robust_eval(code, workdir, threshold_loss, k=3):
    initial = run_in_sandbox(code, workdir)
    if initial.loss > threshold_loss * 1.05:
        return initial  # Not competitive — skip extra runs
    # Near the frontier — verify robustness
    results = [initial] + [run_in_sandbox(code, workdir) for _ in range(k - 1)]
    median_loss = sorted(r.loss for r in results)[k // 2]
    return replace(initial, loss=median_loss)
```

This prevents false breakthroughs from lucky random seeds while keeping the overhead low (only applied to near-frontier candidates).

**Where to change:** `autoresearch_agent/autoresearch.py` — wrap `run_in_sandbox` call with `robust_eval` in the champion-selection logic.

---

## Phase 9 — Process Management in Server (Cancel + Isolation)

**Problem:** `server.py` has no way to kill a running evolution. The frontend "pause" button just disconnects the HTTP stream — `autoresearch.py` keeps running in the background. Also, two concurrent requests share the same `train.py` file and corrupt each other.

**Fix:**

1. **Per-request working directory:** Each `/run` call creates a unique `workdir = /tmp/run_{uuid4()}/` and runs `autoresearch.py` inside it. No file collisions.

2. **Cancel endpoint:** Add `POST /cancel/{run_id}` that sends `SIGTERM` to the process group via `os.killpg(os.getpgid(proc.pid), signal.SIGTERM)`.

3. **Session state:** Keep a `dict[run_id, Process]` in app state. Return `run_id` in the first streamed line. Frontend stores it for cancellation.

4. **Graceful shutdown:** In `autoresearch.py`, catch `SIGTERM` and write `checkpoint.json` before exiting so progress is saved.

**Where to change:** `autoresearch_agent/server.py` — add `active_runs: dict`, `start_new_session()`, `cancel_run()`, per-request tempdir creation, and SIGTERM handler. Add `preexec_fn=os.setsid` to the `subprocess.Popen` call immediately (1-line fix that enables `killpg`).

---

## Phase 10 — Multi-Agent Harness Architecture (The Harness-Native Design)

This restructures the agent to match how the Claude Code Agent SDK is designed to operate: **specialized sub-agents coordinated by a director**.

### Proposed agent graph:

```
┌─────────────────────────────────────────────────────────┐
│                   RESEARCH DIRECTOR                      │
│  (outer loop: manages population, selects parents,       │
│   decides how many candidates to generate, early-stop)   │
└──────────┬──────────────────────────────────────────────┘
           │ spawns K in parallel
    ┌──────┴──────┬──────────────┐
    ▼             ▼              ▼
[ANALYST]   [CODE GEN 1]   [CODE GEN 2]
(analyzes    (low-temp      (high-temp
 baseline,   exploit)       explore)
 returns
 weakness
 bullets)
    │             │              │
    └──────┬──────┘──────────────┘
           │ all pass to
    ┌──────▼──────────┐
    │  EVAL WORKER N  │  (runs in sandbox, returns loss)
    └──────┬──────────┘
           │ if loss → ∞ or runtime error
    ┌──────▼──────────┐
    │   SELF-HEALER   │  (specialized repair agent)
    └─────────────────┘
```

**Implementation:** The Research Director is the main Python process. Code Gen agents and Eval Workers are implemented as async tasks using `asyncio.gather()` for true parallelism. The Analyst is a separate `query_llm` call before the generation phase.

The key architectural insight from the harness: **separate concerns into specialized agents with narrow responsibilities** rather than one monolithic loop doing everything.

---

## Phase 11 — Frontend Improvements (Live Loss Chart + Diff View)

**Problem:** The right panel is a raw log stream. No visual feedback on loss trajectory. No way to see what changed between iterations.

**Fix:**

1. **Parse structured events from the stream:** The backend emits special JSON lines alongside human-readable logs:
   ```
   __EVENT__{"type":"cycle_result","cycle":3,"loss":0.18,"delta":-0.04,"status":"breakthrough"}
   ```

2. **Live sparkline chart:** Parse these events on the frontend, maintain a `lossHistory` array, render a mini SVG sparkline in the header bar. Requires ~50 lines of React — no chart library dependency.

3. **Code diff view:** When a `FINAL_CODE_START/END` block arrives, compute a line-by-line diff against the original baseline (client-side, simple Myers diff), show additions in green / deletions in red in a new "Champion" tab.

**Where to change:** `autoresearch_agent/server.py` — emit `__EVENT__` JSON lines at key moments. `frontend/src/App.jsx` — add event parser, sparkline component, Champion diff tab.

---

## Priority Order & Expected Impact

| Phase | Effort | Impact | Do first? |
|---|---|---|---|
| **Phase 1 — Parallel candidates** | Medium | **3–5× throughput** | Yes |
| **Phase 3 — Two-stage prompting** | Low | **Cuts bad-code rate ~50%** | Yes |
| **Phase 6 — Checkpointing** | Low | **Reliability** | Yes |
| **Phase 9 — Server process mgmt** | Medium | **Stability** | Yes |
| **Phase 5 — Adaptive temp** | Low | **~15% better final loss** | Yes |
| **Phase 7 — History context** | Medium | **Avoids re-trying failures** | Yes |
| **Phase 2 — Population** | Medium | **Escapes local minima** | Next |
| **Phase 8 — Variance reduction** | Low | **Honest benchmarking** | Next |
| **Phase 4 — Prompt caching** | Low | **Cost reduction only** | If using Anthropic API |
| **Phase 10 — Full multi-agent** | High | **Architectural ceiling** | After above |
| **Phase 11 — Frontend** | Medium | **UX only** | Last |

---

## Quick Wins (implementable today, no architecture change)

1. **Experiment history hint** — In `autoresearch.py` lines 337–339, change `user_content` to include the last 3 experiment outcomes as a "do not repeat" hint. 10 lines of code, immediate improvement in LLM proposal quality.

2. **Adaptive temperature** — In `autoresearch.py` line 119, change `"temperature": 0.3` to:
   ```python
   "temperature": 0.1 + 0.6 * (1 - iteration / max_iterations)
   ```
   One line, free exploration/exploitation schedule.

3. **Enable process kill** — In `server.py` lines 42–47, add `preexec_fn=os.setsid` to `subprocess.Popen`. One line, enables the cancel button to actually kill the subprocess tree.

4. **Adaptive timeout** — In `autoresearch.py` lines 60–70, replace `timeout=300` with `timeout=max(300, baseline_runtime * 3)` where `baseline_runtime` is measured during the initial baseline evaluation. Prevents timeouts on legitimately complex improvements.
