"""Message-content normalisation for the LLM backends.

What this module does
---------------------
Helpers that reshape the agent's structured message content (lists of text
blocks, some carrying Anthropic ``cache_control`` markers) into the form each
backend expects:
  - ``_flatten_content`` collapses block lists to a plain string for
    OpenAI-compatible backends (dropping cache markers they don't understand).
  - ``_split_system`` lifts the system message out of the list so the Anthropic
    backend can place it in its top-level ``system`` field.

Why it exists
-------------
The agent authors messages once, in a cache-friendly block layout (Phase 4), then
each backend adapts them differently. Isolating that adaptation keeps the backend
modules focused on transport.

How it fits the architecture
----------------------------
Leaf of the ``llm`` subpackage: pure functions, no imports. Used by
``llm.openai_compat`` and ``llm.anthropic``.
"""

from typing import Any, List, Optional, Tuple


def _flatten_content(content: Any) -> str:
    """Normalise a message's content to a plain string for OpenAI-compatible backends.

    Accepts either a ``str`` (returned as-is) or a list of
    ``{"type": "text", "text": str, ...}`` blocks (joined with blank lines). Any
    ``cache_control`` marker is dropped because only Anthropic honours it.
    """
    if isinstance(content, str):
        return content
    parts: List[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif isinstance(block, str):
            parts.append(block)
    return "\n\n".join(parts)


def _split_system(messages: List[dict]) -> Tuple[Optional[Any], List[dict]]:
    """Return ``(system_content, non_system_messages)``.

    Used to lift the system role into Anthropic's top-level ``system`` field.
    Only the first system message is extracted; everything else is preserved
    in order.
    """
    system: Optional[Any] = None
    rest: List[dict] = []
    for m in messages:
        if m.get("role") == "system" and system is None:
            system = m.get("content")
        else:
            rest.append(m)
    return system, rest
