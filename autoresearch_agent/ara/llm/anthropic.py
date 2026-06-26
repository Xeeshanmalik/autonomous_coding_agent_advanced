"""Native Anthropic /v1/messages backend with prompt caching (Phase 4).

What this module does
---------------------
Implements ``_query_anthropic``: lifts the system message into Anthropic's
top-level ``system`` field, posts to ``/v1/messages``, streams the event-based
response, accumulates text, and reports cache hit/creation token counts.

Why it exists
-------------
Anthropic is the only backend that honours ``cache_control`` breakpoints, so it
needs message handling distinct from the OpenAI-compatible path. Callers declare
breakpoints as ``cache_control: {"type": "ephemeral"}`` on text blocks; Anthropic
caches every prefix up to and including each marked block (5-minute TTL), which
keeps the system prompt + task description hot and cuts per-cycle prompt tokens by
roughly 75%.

How it fits the architecture
----------------------------
Part of the ``llm`` subpackage. Depends on: ``config`` (URL/model/key/version/
max-tokens), ``lifecycle`` (``_check_cancel``), ``llm.content`` (``_split_system``),
and ``llm.transport`` (``_post_with_retry``). Selected by ``llm.client.query_llm``
when ``config.USE_ANTHROPIC`` is true.
"""

import json
from typing import Any, List

from ara import config, lifecycle
from ara.llm.content import _split_system
from ara.llm.transport import _post_with_retry


def _query_anthropic(messages: List[dict], stream: bool, temp: float,
                     quiet: bool = False) -> str:
    """Stream a completion from Anthropic's native messages API.

    ``quiet=True`` suppresses streaming prints — same semantics as the
    OpenAI-compat path: the caller buffers and prints with a per-agent prefix
    afterward. After the stream, logs cache read/creation token counts when the
    server reports them.
    """
    headers = {
        "Content-Type": "application/json",
        "x-api-key": config.API_KEY,
        "anthropic-version": config.ANTHROPIC_VERSION,
    }

    system_content, user_messages = _split_system(messages)

    # Anthropic accepts either a string or a list of blocks for `system`.
    # Normalise to the block form when a cache_control marker is present so the
    # system prompt becomes a cache breakpoint.
    if system_content is None:
        system_field = None
    elif isinstance(system_content, str):
        system_field = system_content
    else:
        system_field = system_content  # already a list of blocks

    payload: dict[str, Any] = {
        "model": config.MODEL,
        "max_tokens": config.ANTHROPIC_MAX_TOKENS,
        "messages": user_messages,
        "temperature": temp,
        "stream": stream,
    }
    if system_field is not None:
        payload["system"] = system_field

    response = _post_with_retry(config.LLM_URL, headers, payload, stream)
    full_response = ""
    cache_stats = {"cache_creation_input_tokens": None, "cache_read_input_tokens": None}
    if not quiet:
        print("\033[96m", end="")
    try:
        for line in response.iter_lines():
            lifecycle._check_cancel(response, "mid-stream")
            if not line:
                continue
            line_str = line.decode("utf-8")
            if not line_str.startswith("data: "):
                continue
            data_str = line_str[6:]
            try:
                evt = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            etype = evt.get("type")
            if etype == "content_block_delta":
                delta = evt.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    if not quiet:
                        print(text, end="", flush=True)
                    full_response += text
            elif etype == "message_start":
                usage = evt.get("message", {}).get("usage", {})
                cache_stats["cache_creation_input_tokens"] = usage.get("cache_creation_input_tokens")
                cache_stats["cache_read_input_tokens"] = usage.get("cache_read_input_tokens")
            elif etype == "message_stop":
                break
    finally:
        if not quiet:
            print("\033[0m\n")
    if cache_stats["cache_read_input_tokens"] is not None and not quiet:
        print(f"[*] Anthropic cache: read={cache_stats['cache_read_input_tokens']} "
              f"created={cache_stats['cache_creation_input_tokens']} tokens")
    return full_response
