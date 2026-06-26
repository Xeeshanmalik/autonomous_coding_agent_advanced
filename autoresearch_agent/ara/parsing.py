"""Output-parsing utilities for LLM responses and script output.

What this module does
---------------------
Two small, pure parsers used everywhere a free-form text blob has to be turned
into something structured:
  - ``extract_code_block`` pulls the Python code out of an LLM reply.
  - ``extract_val_loss`` reads the ``val_loss`` score a candidate script prints.

Why it exists
-------------
Both are needed by multiple layers (bootstrap, healing, the Phase-10 agents, the
sandbox evaluator). Keeping them as dependency-free helpers avoids import cycles
and makes them trivially testable.

How it fits the architecture
----------------------------
Leaf module: only depends on the standard library. The fitness signal the whole
evolutionary loop optimises (``val_loss``) is produced here.

Known limitation (flagged, unchanged)
-------------------------------------
``extract_val_loss``'s regex ``[0-9.]+`` does not match negative or
scientific-notation losses (e.g. ``-0.5`` or ``1e-3``); such scripts are treated
as ``inf``. Preserved as-is from the original.
"""

import re
from typing import Optional


def extract_val_loss(output: str) -> float:
    """Parse the ``val_loss`` score from a script's stdout/stderr.

    Returns ``inf`` when no ``val_loss`` line is found — the value the whole
    loop treats as "this candidate is unusable", so a missing print is
    indistinguishable from a crash for ranking purposes.
    """
    match = re.search(r"val_loss[\s:=]+([0-9.]+)", output, re.IGNORECASE)
    return float(match.group(1)) if match else float("inf")


def extract_code_block(llm_text: str) -> Optional[str]:
    """Pull the first ```python … ``` block out of an LLM reply.

    Strips any ``<think>…</think>`` reasoning first, then falls back to the raw
    text after a closing ``</think>`` tag for reasoning models that don't fence
    their code. Returns the code string, or ``None`` if nothing usable is found.
    """
    # Strip <think>…</think> reasoning before searching
    text = re.sub(r"<think>.*?</think>", "", llm_text, flags=re.DOTALL)

    match = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Fallback: raw text after </think>
    if "</think>" in llm_text:
        tail = llm_text.split("</think>")[-1].strip()
        if tail:
            return tail

    return None
