"""OpenAI-compatible chat-completions backend (local llama.cpp, Gemini).

What this module does
---------------------
Implements ``_query_openai_compat``: builds the ``/chat/completions`` payload,
flattens structured content to plain strings, streams the SSE response, and
returns the concatenated text. Honours cooperative cancellation mid-stream.

Why it exists
-------------
The default local llama.cpp backend and the Gemini OpenAI-compatible endpoint
share this exact wire format. The Anthropic backend differs enough to warrant its
own module (see ``llm.anthropic``).

How it fits the architecture
----------------------------
Part of the ``llm`` subpackage. Depends on: ``config`` (URL/model/key/flags),
``lifecycle`` (``_check_cancel``), ``llm.content`` (``_flatten_content``), and
``llm.transport`` (``_post_with_retry``). Selected by ``llm.client.query_llm``
when neither Anthropic nor … (Gemini still routes here).

Known limitation (flagged, unchanged): when ``stream=False`` this still parses
SSE ``data:`` lines, so the non-streaming path is effectively broken. Every
current caller uses ``stream=True``.
"""

import json
from typing import Any, List

from ara import config, lifecycle
from ara.llm.content import _flatten_content
from ara.llm.transport import _post_with_retry


def _query_openai_compat(messages: List[dict], stream: bool, temp: float,
                         quiet: bool = False) -> str:
    """Stream a chat completion from an OpenAI-compatible backend.

    When ``quiet=True``, streaming chunks are not printed to stdout — the caller
    prints the full response with a per-agent prefix once it returns. Parallel
    agents (CodeGen, SelfHealer) use this to avoid character-level interleave
    across concurrent threads writing to the same stdout.
    """
    headers = {"Content-Type": "application/json"}
    if config.USE_GEMINI:
        headers["Authorization"] = f"Bearer {config.API_KEY}"

    # Flatten any structured content blocks — cache_control is silently dropped
    # because llama.cpp / Gemini do not honour Anthropic's ephemeral-cache API.
    # The stable-prefix layout still helps llama.cpp's automatic KV-prefix cache.
    flat_messages = [
        {"role": m["role"], "content": _flatten_content(m["content"])}
        for m in messages
    ]

    payload: dict[str, Any] = {
        "model": config.MODEL,
        "messages": flat_messages,
        "temperature": temp,
        "stream": stream,
    }

    response = _post_with_retry(config.LLM_URL, headers, payload, stream)
    full_response = ""
    if not quiet:
        print("\033[96m", end="")  # Cyan text for LLM output
    try:
        for line in response.iter_lines():
            lifecycle._check_cancel(response, "mid-stream")
            if line:
                line_str = line.decode("utf-8")
                if line_str.startswith("data: "):
                    data_str = line_str[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        content = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
                        if content is not None:
                            if not quiet:
                                print(content, end="", flush=True)
                            full_response += content
                    except json.JSONDecodeError:
                        pass
    finally:
        if not quiet:
            print("\033[0m\n")
    return full_response
