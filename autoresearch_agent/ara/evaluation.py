"""Candidate evaluation with variance reduction (Phases 1 & 8).

What this module does
---------------------
Turns candidate code into a trustworthy fitness score:
  - ``robust_eval`` — evaluate once, and only re-run near-frontier candidates K
    times (taking the median) to suppress lucky-seed false breakthroughs (Phase 8).
  - ``run_candidate_pool`` — evaluate a whole pool in parallel sandboxes and
    return the best (legacy Phase-1 entry point; see note below).

Why it exists
-------------
A single run of a stochastic script can beat the champion by luck. Re-evaluating
only the candidates that look like breakthroughs buys statistical robustness
without paying K× cost on the many candidates that miss the threshold.

How it fits the architecture
----------------------------
Depends on ``config`` (``ROBUST_EVAL_K`` / ``ROBUST_EVAL_MARGIN``), ``sandbox``
(``run_in_sandbox`` via attribute access, ``classify_candidate_failure``).
``robust_eval`` is the unit the Phase-10 ``EvalWorker`` agents call.

Note (flagged, unchanged): ``run_candidate_pool`` is **not called** anywhere in
the current Phase-10 flow — the orchestrator dispatches ``eval_worker`` →
``robust_eval`` directly. It is retained as the original Phase-1 implementation.
"""

import math
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from typing import List, Optional

from ara import config, sandbox
from ara.sandbox import CandidateResult, classify_candidate_failure


def robust_eval(code: str, workdir: str, threshold_loss: float,
                k: int = config.ROBUST_EVAL_K) -> CandidateResult:
    """Evaluate ``code`` once; re-evaluate near-frontier candidates K times.

    If the first result is within ``ROBUST_EVAL_MARGIN`` of ``threshold_loss``,
    re-run ``k-1`` more times in the same workdir and return the median-loss
    result; otherwise return the single eval untouched — most candidates miss the
    threshold, so the K× overhead is only paid near the frontier.

    ``threshold_loss=inf`` (e.g. first cycle, no champion yet) disables
    re-evaluation because ``inf * (1 + margin) == inf`` and the short-circuit
    always fires.
    """
    initial = sandbox.run_in_sandbox(code, workdir)
    if not math.isfinite(threshold_loss) or initial.loss > threshold_loss * (1 + config.ROBUST_EVAL_MARGIN):
        return initial
    if k <= 1 or not math.isfinite(initial.loss):
        return initial

    extra = [sandbox.run_in_sandbox(code, workdir) for _ in range(k - 1)]
    losses = sorted(r.loss for r in [initial] + extra)
    median_loss = losses[len(losses) // 2]
    print(f"[*] robust_eval: near-frontier candidate re-run {k}x, "
          f"losses={['%.6f' % l for l in losses]}, median={median_loss:.6f}")
    return replace(initial, loss=median_loss)


def run_candidate_pool(candidates: List[str],
                       threshold_loss: float = float("inf")) -> Optional[CandidateResult]:
    """Run each candidate in an isolated sandbox in parallel, return the best.

    Each candidate is wrapped in ``robust_eval`` — near-frontier candidates
    (within ``ROBUST_EVAL_MARGIN`` of ``threshold_loss``) are re-evaluated k
    times to suppress false breakthroughs from lucky random seeds (Phase 8).
    Returns ``None`` if no candidate produced a finite loss.

    NOTE: legacy Phase-1 path, unused by the current Phase-10 orchestrator.
    """
    worktrees: List[str] = []
    results: List[CandidateResult] = []
    try:
        worktrees = [tempfile.mkdtemp(prefix=f"run_{i}_") for i in range(len(candidates))]
        with ThreadPoolExecutor(max_workers=len(candidates)) as executor:
            futures = {
                executor.submit(robust_eval, code, wdir, threshold_loss): i
                for i, (code, wdir) in enumerate(zip(candidates, worktrees))
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    result = future.result()
                    if math.isfinite(result.loss):
                        print(f"[*] Candidate {idx + 1}/{len(candidates)}: val_loss={result.loss:.6f}")
                    else:
                        reason = classify_candidate_failure(result.output)
                        print(f"[-] Candidate {idx + 1}/{len(candidates)}: val_loss=inf — {reason}")
                    results.append(result)
                except Exception as e:
                    print(f"[-] Candidate {idx + 1} raised an exception: {e}")
    finally:
        for wdir in worktrees:
            shutil.rmtree(wdir, ignore_errors=True)

    valid = [r for r in results if r.loss < float("inf")]
    if not valid:
        return None
    return min(valid, key=lambda r: r.loss)
