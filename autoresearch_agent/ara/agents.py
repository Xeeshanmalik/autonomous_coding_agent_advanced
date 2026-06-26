"""Specialised async agents for the multi-agent harness (Phase 10).

What this module does
---------------------
The four worker roles the Research Director fans out each cycle:
  - ``analyst_agent``     — analyse the parent, produce weakness bullets.
  - ``code_gen_agent``    — generate one candidate script from the research prompt.
  - ``eval_worker``       — sandbox-evaluate one candidate via ``robust_eval``.
  - ``self_healer_agent`` — one repair attempt for a crashed candidate.
Plus ``_emit_with_prefix``, which prints an agent's buffered output without
character-level interleave across concurrent agents.

Why it exists
-------------
All LLM calls are blocking (``requests`` + streaming); these thin async wrappers
bridge to ``asyncio`` via ``asyncio.to_thread`` so K candidate calls overlap on
the event loop. That overlap is the dominant per-cycle speedup (~1× LLM wall-time
instead of K×). Parallel agents call ``query_llm(quiet=True)`` and print once,
afterward, to keep stdout readable.

How it fits the architecture
----------------------------
Depends on ``llm`` (``query_llm`` via attribute access), ``analysis``
(``analyze_baseline``), ``evaluation`` (``robust_eval``), ``sandbox``
(``classify_candidate_failure``), ``parsing`` (``extract_code_block``) and
``prompts`` (``SYSTEM_PROMPT``). Orchestrated by ``orchestrator.director_one_cycle``.
"""

import asyncio
import math
from typing import List, Optional

from ara import llm
from ara.analysis import analyze_baseline
from ara.evaluation import robust_eval
from ara.parsing import extract_code_block
from ara.prompts import SYSTEM_PROMPT
from ara.sandbox import CandidateResult, classify_candidate_failure


async def analyst_agent(parent_code: str, program_instructions: str) -> str:
    """Single Analyst: return the weakness bullet report (or raise).

    Runs the blocking ``analyze_baseline`` in a thread so the Director can await
    it on the event loop.
    """
    return await asyncio.to_thread(analyze_baseline, parent_code, program_instructions)


def _emit_with_prefix(prefix: str, body: str) -> None:
    """Print ``body`` to stdout with ``prefix`` on every line, plus blank padding.

    Used by parallel agents to surface their LLM output without character-level
    interleave. The whole call runs in the asyncio event-loop thread
    (single-threaded), so concurrent agents emit their blocks one after another,
    not mixed together.
    """
    print(f"\033[96m{prefix}\033[0m")
    for line in body.splitlines() or [""]:
        print(f"  {prefix}  {line}")
    print()


async def code_gen_agent(messages: List[dict], temp: float, agent_id: int) -> Optional[str]:
    """One CodeGen worker: return extracted candidate code, or ``None`` on failure.

    Calls ``query_llm`` in quiet mode (buffered), prints the response with a
    per-agent prefix, then extracts the ```python block.
    """
    print(f"[*] CodeGen {agent_id} (temp={temp:.2f}): requesting…")
    try:
        response = await asyncio.to_thread(llm.query_llm, messages, True, temp, True)
    except Exception as e:
        print(f"[-] CodeGen {agent_id} failed: {e}")
        return None
    _emit_with_prefix(f"[CodeGen {agent_id}]", response)
    code = extract_code_block(response)
    if not code:
        print(f"[-] CodeGen {agent_id}: no parseable code block.")
        return None
    print(f"[+] CodeGen {agent_id}: got candidate ({len(code)} chars)")
    return code


async def eval_worker(code: str, workdir: str, threshold_loss: float,
                      agent_id) -> CandidateResult:
    """One EvalWorker: sandbox-evaluate a candidate via ``robust_eval``.

    Runs the blocking evaluation in a thread and logs the resulting loss (or the
    classified failure reason on ``inf``).
    """
    result = await asyncio.to_thread(robust_eval, code, workdir, threshold_loss)
    if math.isfinite(result.loss):
        print(f"[+] EvalWorker {agent_id}: val_loss={result.loss:.6f}")
    else:
        reason = classify_candidate_failure(result.output)
        print(f"[-] EvalWorker {agent_id}: val_loss=inf — {reason}")
    return result


async def self_healer_agent(code: str, error_output: str, agent_id) -> Optional[str]:
    """SelfHealer: one repair attempt for a crashed candidate.

    Returns healed code or ``None``. Mirrors the repair prompt that
    ``healing.execute_and_heal`` uses but is invoked async and per-candidate so
    multiple failures can be repaired concurrently. Only fired when the failure
    output contains a traceback — a candidate that ran cleanly but didn't print
    val_loss is not repairable from the output alone.
    """
    error_lines = error_output.strip().splitlines()
    error_snippet = "\n".join(error_lines[-80:]) if error_lines else error_output
    repair_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            "The following Python script crashed. Return the corrected version "
            "inside a ```python block. Fix ONLY the specific bug — do not change "
            "the algorithm.\n\n"
            f"=== BROKEN CODE ===\n```python\n{code}\n```\n\n"
            f"=== TRACEBACK ===\n{error_snippet}\n\n"
            "Return the complete, corrected Python script now."
        )},
    ]
    print(f"[*] SelfHealer {agent_id}: requesting repair…")
    try:
        response = await asyncio.to_thread(llm.query_llm, repair_messages, True, 0.2, True)
    except Exception as e:
        print(f"[-] SelfHealer {agent_id} failed: {e}")
        return None
    _emit_with_prefix(f"[SelfHealer {agent_id}]", response)
    healed = extract_code_block(response)
    if healed:
        print(f"[+] SelfHealer {agent_id}: got patched code")
    else:
        print(f"[-] SelfHealer {agent_id}: no parseable code block")
    return healed
