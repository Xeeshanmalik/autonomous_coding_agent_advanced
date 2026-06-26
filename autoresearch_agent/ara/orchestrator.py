"""Research Director — the per-cycle orchestrator (Phase 10).

What this module does
---------------------
Coordinates one full research cycle and the loop over cycles:
  - ``_build_research_messages`` — assemble the cacheable-prefix prompt every
    CodeGen receives (system + task cached; parent/weaknesses/history vary).
  - ``_record_failed_cycle`` — log a failed cycle and checkpoint.
  - ``director_one_cycle`` — Analyst → K×CodeGen → K×EvalWorker → SelfHealer →
    population update → champion persist → checkpoint/telemetry.
  - ``research_director`` — iterate cycles until done or SIGTERM.

Why it exists
-------------
This is the brain that turns the specialised agents and domain services into the
actual evolutionary search. It owns the per-cycle control flow, the adaptive
temperature schedule (Phase 5), and the breakthrough/no-improvement bookkeeping.

How it fits the architecture
----------------------------
Top of the dependency graph below ``cli``. Depends on ``config`` (pool size,
self-healer flag, history cadence via attribute access), ``lifecycle`` (SIGTERM),
``population``, ``agents``, ``history``, ``checkpoint``, ``dashboard`` and
``prompts``. Driven by ``cli.main`` via ``asyncio.run(research_director(...))``.
"""

import asyncio
import math
import shutil
import tempfile
from typing import List, Tuple

from ara import config, lifecycle
from ara.agents import analyst_agent, code_gen_agent, eval_worker, self_healer_agent
from ara.checkpoint import git_commit_champion, save_checkpoint
from ara.dashboard import emit_event
from ara.history import compress_history, format_history_hint
from ara.population import (
    Population,
    PopulationMember,
    select_parent,
    save_population,
    update_population,
)
from ara.prompts import SYSTEM_PROMPT


def _build_research_messages(parent: PopulationMember, weakness_report: str,
                             experiment_log: List[dict], history_prefix: str,
                             program_instructions: str) -> List[dict]:
    """Build the cacheable-prefix research messages handed to every CodeGen.

    The system prompt and task description are marked as ephemeral cache
    breakpoints (Phase 4); the parent code, history hint and weakness list form
    the variable tail that changes each cycle.
    """
    history_hint = format_history_hint(experiment_log, history_prefix)
    variable_tail = (
        f"\n\nParent script to improve (loss={parent.loss:.6f}, cycle {parent.cycle}):\n"
        f"```python\n{parent.code}\n```\n\n"
    )
    if history_hint:
        variable_tail += f"{history_hint}\n\n"
    variable_tail += (
        f"Identified weaknesses:\n{weakness_report}\n\n"
        "Implement exactly ONE targeted fix addressing one of the weaknesses above. "
        "Output the complete corrected script in a ```python block."
    )
    return [
        {"role": "system", "content": [
            {"type": "text", "text": SYSTEM_PROMPT,
             "cache_control": {"type": "ephemeral"}},
        ]},
        {"role": "user", "content": [
            {"type": "text", "text": program_instructions,
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": variable_tail},
        ]},
    ]


def _record_failed_cycle(iteration: int, best_loss: float, baseline_code: str,
                         started_at: str, experiment_log: List[dict],
                         history_prefix: str, target: str) -> None:
    """Append a 'failed' experiment-log entry and persist the checkpoint."""
    experiment_log.append({
        "cycle": iteration, "loss": None, "delta": None,
        "status": "failed", "target": target,
    })
    save_checkpoint(iteration, best_loss, baseline_code, started_at,
                    experiment_log, history_prefix)


async def director_one_cycle(iteration: int, max_iterations: int, population: Population,
                             best_loss: float, baseline_code: str, started_at: str,
                             experiment_log: List[dict], history_prefix: str,
                             program_instructions: str) -> Tuple[float, List[dict], str]:
    """Run one full cycle: Analyst → CodeGens → EvalWorkers → SelfHealer.

    Returns the updated ``(best_loss, experiment_log, history_prefix)``. The
    population, ``train.py``, ``population.json`` and ``checkpoint.json`` are
    mutated / written in place. The adaptive temperature schedule (Phase 5)
    spreads candidate temperatures around a cosine-annealed base temp.
    """
    print(f"\n{'='*50}")
    print(f"--- AutoResearch Cycle {iteration} ---")

    if iteration > 1 and config.USE_GEMINI:
        print("[*] Rate-limit mitigation: sleeping 5 s before next cycle…")
        await asyncio.sleep(5)

    cycle_ratio = (iteration - 1) / max_iterations
    base_temp = 0.1 + 0.7 * 0.5 * (1 + math.cos(math.pi * cycle_ratio))
    candidate_temps = [
        max(0.05, base_temp * 0.5),
        base_temp,
        min(1.0, base_temp * 1.5),
    ]

    parent = select_parent(population)
    print(f"[*] Director: parent (loss={parent.loss:.6f}, cycle {parent.cycle}); "
          f"base_temp={base_temp:.2f}")

    try:
        weakness_report = await analyst_agent(parent.code, program_instructions)
    except Exception as e:
        print(f"[-] Analyst failed ({e}). Skipping cycle.")
        _record_failed_cycle(iteration, best_loss, baseline_code, started_at,
                             experiment_log, history_prefix, "analysis_failed")
        return best_loss, experiment_log, history_prefix

    research_messages = _build_research_messages(
        parent, weakness_report, experiment_log, history_prefix, program_instructions
    )

    print(f"[*] Director: dispatching {config.CANDIDATE_POOL_SIZE} CodeGen agents in parallel…")
    codegen_tasks = [
        code_gen_agent(research_messages, candidate_temps[i % len(candidate_temps)], i + 1)
        for i in range(config.CANDIDATE_POOL_SIZE)
    ]
    candidates_raw = await asyncio.gather(*codegen_tasks)
    candidates = [c for c in candidates_raw if c]

    if not candidates:
        print("[-] No valid candidates generated. Skipping cycle.")
        _record_failed_cycle(iteration, best_loss, baseline_code, started_at,
                             experiment_log, history_prefix,
                             weakness_report.split("\n")[0][:100])
        return best_loss, experiment_log, history_prefix

    worktrees = [tempfile.mkdtemp(prefix=f"eval_{i}_") for i in range(len(candidates))]
    try:
        print(f"[*] Director: dispatching {len(candidates)} EvalWorkers in parallel…")
        eval_tasks = [
            eval_worker(code, wdir, best_loss, i + 1)
            for i, (code, wdir) in enumerate(zip(candidates, worktrees))
        ]
        results = await asyncio.gather(*eval_tasks)
    finally:
        for w in worktrees:
            shutil.rmtree(w, ignore_errors=True)

    healed_results = []
    if config.ENABLE_SELF_HEALER:
        crashed_indices = [
            i for i, r in enumerate(results)
            if not math.isfinite(r.loss) and "Traceback (most recent call last)" in r.output
        ]
        if crashed_indices:
            print(f"[*] Director: {len(crashed_indices)} candidate(s) crashed — "
                  f"launching SelfHealer(s) in parallel…")
            heal_tasks = [
                self_healer_agent(results[i].code, results[i].output, i + 1)
                for i in crashed_indices
            ]
            healed_codes = await asyncio.gather(*heal_tasks)
            heal_pairs = [
                (code, orig_idx) for code, orig_idx in zip(healed_codes, crashed_indices)
                if code
            ]
            if heal_pairs:
                heal_worktrees = [
                    tempfile.mkdtemp(prefix=f"heal_{orig_idx}_")
                    for _, orig_idx in heal_pairs
                ]
                try:
                    heal_eval_tasks = [
                        eval_worker(code, wdir, best_loss, f"heal{orig_idx + 1}")
                        for (code, orig_idx), wdir in zip(heal_pairs, heal_worktrees)
                    ]
                    healed_results = await asyncio.gather(*heal_eval_tasks)
                finally:
                    for w in heal_worktrees:
                        shutil.rmtree(w, ignore_errors=True)

    all_results = list(results) + list(healed_results)
    valid = [r for r in all_results if math.isfinite(r.loss)]

    if not valid:
        print("[-] All candidates failed evaluation. Keeping current champion.")
        champion = population.best()
        with open("train.py", "w") as f:
            f.write(champion.code)
        _record_failed_cycle(iteration, best_loss, baseline_code, started_at,
                             experiment_log, history_prefix,
                             weakness_report.split("\n")[0][:100])
        return best_loss, experiment_log, history_prefix

    best_result = min(valid, key=lambda r: r.loss)
    new_loss = best_result.loss
    print(f"[*] Director: best candidate val_loss={new_loss:.6f}")

    prev_loss = best_loss
    new_member = PopulationMember(code=best_result.code, loss=new_loss, cycle=iteration)
    admitted = update_population(population, new_member)
    champion = population.best()

    if champion.loss < best_loss:
        print(f"[+] BREAKTHROUGH! Loss improved: {best_loss:.6f} → {champion.loss:.6f}")
        best_loss = champion.loss
        with open("train.py", "w") as f:
            f.write(champion.code)
        git_commit_champion(iteration, best_loss)
        cycle_status = "breakthrough"
    elif admitted:
        print(f"[*] Population updated (new loss={new_loss:.6f}). "
              f"Champion at {best_loss:.6f}.")
        with open("train.py", "w") as f:
            f.write(champion.code)
        cycle_status = "no_improvement"
    else:
        print(f"[-] Candidate (loss={new_loss:.6f}) did not improve population. "
              f"Champion at {best_loss:.6f}.")
        with open("train.py", "w") as f:
            f.write(champion.code)
        cycle_status = "no_improvement"

    pop_summary = ", ".join(f"{m.loss:.4f}" for m in
                            sorted(population.members, key=lambda m: m.loss))
    print(f"[*] Population losses: [{pop_summary}]")
    save_population(population)

    experiment_log.append({
        "cycle": iteration,
        "loss": new_loss,
        "delta": round(new_loss - prev_loss, 6),
        "status": cycle_status,
        "target": weakness_report.split("\n")[0][:100],
    })

    if len(experiment_log) % config.HISTORY_COMPRESS_AFTER == 0:
        try:
            history_prefix = compress_history(experiment_log[:-5])
        except Exception as e:
            print(f"[!] History compression failed ({e}) — keeping raw log.")

    save_checkpoint(iteration, best_loss, baseline_code, started_at,
                    experiment_log, history_prefix)
    return best_loss, experiment_log, history_prefix


async def research_director(iteration: int, max_iterations: int, population: Population,
                            best_loss: float, baseline_code: str, started_at: str,
                            experiment_log: List[dict], history_prefix: str,
                            program_instructions: str) -> None:
    """Director outer loop. Iterates ``director_one_cycle`` until done or SIGTERM.

    After each cycle it emits a ``cycle_result`` event (the per-cycle champion
    loss for the frontend loss-over-cycles chart) — a single emission point that
    covers every cycle path inside ``director_one_cycle``.
    """
    while iteration <= max_iterations:
        if lifecycle._sigterm_received:
            print("[!] Shutdown requested — exiting director loop.")
            break
        best_loss, experiment_log, history_prefix = await director_one_cycle(
            iteration, max_iterations, population, best_loss, baseline_code,
            started_at, experiment_log, history_prefix, program_instructions
        )
        # Per-cycle champion loss for the frontend loss-over-cycles chart.
        # Single emission point covers every cycle path inside director_one_cycle.
        emit_event({"type": "cycle_result", "cycle": iteration, "loss": best_loss})
        iteration += 1
    print(f"\n{'='*50}")
    print(f"[*] AutoResearch Loop Completed! Final val_loss: {best_loss}")
