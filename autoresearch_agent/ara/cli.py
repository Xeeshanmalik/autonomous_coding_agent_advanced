"""Entrypoint — synchronous setup that hands off to the async director.

What this module does
---------------------
``main`` performs the one-time setup for a run: stage the dashboard helper, read
``program.md``, resume from checkpoint/population or evaluate (and possibly
bootstrap) a fresh baseline, then ``asyncio.run`` the Research Director and stream
the final champion's chart data. ``run`` wraps ``main`` with the cancellation
handler so SIGTERM exits 0.

Why it exists
-------------
This is the seam between the blocking process world (the server spawns
``python -u autoresearch.py`` in a per-run cwd) and the async per-cycle harness.
Keeping setup/resume logic here keeps the orchestrator focused on cycles.

How it fits the architecture
----------------------------
Top of the package. Depends on ``dashboard``, ``checkpoint``, ``population``,
``bootstrap``, ``sandbox``, ``parsing`` and ``orchestrator``. Invoked by the
top-level ``autoresearch.py`` shim (entrypoint) and by ``python -m ara``.

Working-directory contract
--------------------------
``main`` reads ``program.md`` and ``train.py`` by relative path: the server runs
this process with ``cwd`` set to the per-run workdir it populated. Running it from
any other directory raises ``FileNotFoundError``.
"""

import asyncio
import datetime
import os

from ara.bootstrap import bootstrap_baseline_if_needed
from ara.checkpoint import load_checkpoint
from ara.dashboard import _ensure_dashboard_helper, emit_dashboard_data
from ara.orchestrator import research_director
from ara.parsing import extract_val_loss
from ara.population import Population, PopulationMember, load_population
from ara.sandbox import run_cmd


def main() -> None:
    """Synchronous setup + bootstrap, then hand off to the async director.

    Fans out CodeGen / EvalWorker / SelfHealer agents in parallel via the
    Research Director (Phase 10). Resumes from ``checkpoint.json`` /
    ``population.json`` when present, otherwise evaluates the user baseline and
    bootstraps one if it does not print a finite val_loss.
    """
    print("[*] Booting AutoResearch Agent (Phase 10: Multi-Agent Harness)…")

    # Stage the dashboard export helper so champions can import it (here and in
    # every candidate sandbox) instead of inlining json-dump boilerplate.
    _ensure_dashboard_helper()

    max_iterations = int(os.environ.get("MAX_ITERATIONS", 5))

    # program_instructions is needed by both branches (bootstrap on fresh
    # runs, weakness analysis in the loop) so read it once up-front.
    with open("program.md", "r") as f:
        program_instructions = f.read()

    # --- Resume from checkpoint / population, or run fresh baseline ---
    checkpoint = load_checkpoint()
    population = load_population()
    iteration = 1
    if checkpoint:
        iteration = checkpoint["iteration"] + 1
        baseline_code = checkpoint["baseline_code"]
        started_at = checkpoint["started_at"]
        experiment_log = checkpoint["experiment_log"]
        history_prefix = checkpoint["history_prefix"]
        if population:
            best_loss = population.best().loss
        else:
            with open("train.py", "r") as f:
                champ_code = f.read()
            print("[*] population.json missing on resume — re-evaluating train.py to seed best_loss.")
            best_loss = extract_val_loss(run_cmd("python train.py"))
            population = Population()
            population.members.append(PopulationMember(code=champ_code, loss=best_loss, cycle=0))
        print(f"[*] Resumed: cycle {iteration}, pop={len(population.members)}, "
              f"best_loss={best_loss:.6f}, {len(experiment_log)} history entries")
    else:
        iteration = 1
        print("[*] Running initial baseline evaluation…")
        baseline_output = run_cmd("python train.py")
        initial_loss = extract_val_loss(baseline_output)
        best_loss, baseline_code = bootstrap_baseline_if_needed(
            initial_loss, program_instructions
        )
        print(f"[*] Baseline val_loss established: {best_loss}")
        started_at = datetime.datetime.utcnow().isoformat() + "Z"
        experiment_log = []
        history_prefix = ""
        population = Population()
        population.members.append(PopulationMember(code=baseline_code, loss=best_loss, cycle=0))

    asyncio.run(research_director(
        iteration, max_iterations, population, best_loss, baseline_code,
        started_at, experiment_log, history_prefix, program_instructions,
    ))

    # Evolution finished normally — run the final champion once more so it emits
    # dashboard.json, and stream that chart data to the frontend. Skipped on
    # cancellation (KeyboardInterrupt propagates past this to run()).
    emit_dashboard_data()


def run() -> None:
    """Process entrypoint: run ``main`` and exit cleanly on cancellation.

    ``KeyboardInterrupt`` is raised by ``query_llm`` when SIGTERM arrives; we exit
    0 so the parent ``/run`` stream sees a normal EOF and still emits the
    ``[FINAL_CODE_*]`` block.
    """
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Cancellation received — exiting cleanly.")
