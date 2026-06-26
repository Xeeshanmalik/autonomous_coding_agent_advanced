"""Experiment history — memory of what's been tried (Phase 7).

What this module does
---------------------
Turns the running experiment log into prompt context so the search doesn't repeat
itself:
  - ``compress_history`` — LLM-summarise a long log into a short paragraph.
  - ``format_history_hint`` — render the (optionally summarised) log into the
    prompt block injected into each research request.

Why it exists
-------------
Feeding recent attempts back to the code generator stops it re-proposing failed
ideas. Compressing old entries keeps that context cheap once the log grows past
``HISTORY_COMPRESS_AFTER`` cycles.

How it fits the architecture
----------------------------
Depends on ``llm`` (``query_llm`` for compression). ``format_history_hint`` is
pure. The orchestrator calls ``format_history_hint`` when building research
messages and ``compress_history`` periodically.
"""

from typing import List

from ara import llm


def compress_history(experiment_log: List[dict]) -> str:
    """LLM call to compress a long experiment log into a short summary paragraph.

    The summary highlights which approaches worked, which failed, and what the
    current champion uses, so a future code-gen prompt can avoid repeating failed
    approaches without carrying the full log.
    """
    entries = "\n".join(
        "- Cycle {cycle}: {status} | loss={loss} (delta={delta}) | targeted: {target}".format(
            cycle=e["cycle"],
            status=e["status"],
            loss=f"{e['loss']:.4f}" if e["loss"] is not None else "N/A",
            delta=f"{e['delta']:+.4f}" if e["delta"] is not None else "N/A",
            target=e["target"],
        )
        for e in experiment_log
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You are a concise research summarizer. "
                "Output ONLY a 3–5 sentence paragraph — no lists, no headers."
            ),
        },
        {
            "role": "user",
            "content": (
                "Summarize the following ML optimization experiment history. "
                "Highlight which approaches worked, which failed, and what the "
                "current champion method uses. A future LLM will read this summary "
                "to avoid repeating failed approaches.\n\n"
                f"{entries}"
            ),
        },
    ]
    print("[*] Compressing experiment history…")
    return llm.query_llm(messages).strip()


def format_history_hint(experiment_log: List[dict], history_prefix: str = "") -> str:
    """Format experiment history into a concise prompt block.

    Combines the compressed summary (``history_prefix``) with the last 5 raw
    entries, tagged so the code generator is explicitly told not to re-propose
    them. Returns "" when there is nothing to show.
    """
    if not experiment_log and not history_prefix:
        return ""
    lines = []
    if history_prefix:
        lines.append(f"Summary of earlier cycles:\n{history_prefix}")
    recent = experiment_log[-5:]
    if recent:
        lines.append("Recent attempts (do NOT re-propose these exact approaches):")
        for e in recent:
            if e["status"] == "breakthrough":
                icon = "[BREAKTHROUGH]"
            elif e["status"] == "failed":
                icon = "[FAILED]"
            else:
                icon = "[no improvement]"
            loss_str = f"{e['loss']:.4f}" if e["loss"] is not None else "N/A"
            delta_str = f"{e['delta']:+.4f}" if e["delta"] is not None else "N/A"
            lines.append(
                f"  - Cycle {e['cycle']}: {icon} loss={loss_str} (delta={delta_str}) | targeted: {e['target']}"
            )
    return "\n".join(lines)
