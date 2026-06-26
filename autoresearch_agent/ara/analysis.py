"""Stage-A baseline analysis (Phase 3, two-stage prompting).

What this module does
---------------------
``analyze_baseline`` asks the LLM to name the top-3 mathematical/algorithmic
weaknesses in the current parent script, returning a short bullet list. That list
becomes the steering signal for the code-generation stage.

Why it exists
-------------
Splitting "diagnose, then fix" into two prompts produces more targeted edits than
asking for an improvement blind. This module is the diagnose half; the fix half
lives in the Phase-10 ``agents`` / ``orchestrator``.

How it fits the architecture
----------------------------
Depends on ``llm`` (``query_llm`` via attribute access) and ``prompts``
(``ANALYSIS_SYSTEM_PROMPT``). Called once per cycle by the Analyst agent
(``agents.analyst_agent``). The messages use Phase-4 cacheable prefix blocks: the
system prompt and task context are marked ephemeral; only the candidate-code tail
varies per cycle.
"""

from ara import llm
from ara.prompts import ANALYSIS_SYSTEM_PROMPT


def analyze_baseline(baseline_code: str, program_instructions: str) -> str:
    """Identify the top 3 weaknesses in the baseline; return a bullet-point string.

    Messages are structured as cacheable prefix blocks (Phase 4): the system
    prompt and the task context are stable across the whole run, so
    ``cache_control`` marks them as ephemeral cache breakpoints. The
    candidate-code-to-analyze tail varies per cycle.
    """
    messages = [
        {"role": "system", "content": [
            {"type": "text", "text": ANALYSIS_SYSTEM_PROMPT,
             "cache_control": {"type": "ephemeral"}},
        ]},
        {"role": "user", "content": [
            {"type": "text", "text": f"Task context:\n{program_instructions}",
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": (
                f"\n\nBaseline script:\n```python\n{baseline_code}\n```\n\n"
                "In exactly 3 numbered bullet points, identify the top 3 specific mathematical "
                "or algorithmic weaknesses most likely to reduce val_loss if fixed. "
                "Be precise: name the exact technique, parameter, or formula that is suboptimal."
            )},
        ]},
    ]
    print("[*] Stage A: analyzing baseline for weaknesses…")
    return llm.query_llm(messages).strip()
