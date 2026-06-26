"""Low-level HTTP transport for LLM requests.

What this module does
---------------------
A single function, ``_post_with_retry``, that POSTs a payload to an LLM endpoint
with exponential backoff on HTTP 429 and rich error reporting on other non-2xx
responses (it includes the response body, which ``raise_for_status`` discards).

Why it exists
-------------
Both backends (OpenAI-compatible and Anthropic) need identical retry + error
semantics. Sharing one transport function keeps that behaviour consistent and in
one place.

How it fits the architecture
----------------------------
Bottom of the ``llm`` subpackage: depends only on ``requests`` and ``time``.
Used by ``llm.openai_compat`` and ``llm.anthropic``.
"""

import time
from typing import Any, Dict

import requests


def _post_with_retry(url: str, headers: Dict[str, str], payload: Dict[str, Any],
                     stream: bool) -> requests.Response:
    """POST with exponential backoff on HTTP 429. Shared across backends.

    Retries 429 up to 3 times (10s, 20s, 40s). On any other non-2xx status,
    raises ``HTTPError`` with the response body included — ``raise_for_status()``
    alone discards it, hiding diagnostics like llama.cpp's "prompt token count
    exceeds context". Returns the live ``Response`` (streaming or not).
    """
    retry_count, max_retries, backoff = 0, 3, 10
    while True:
        response = requests.post(url, json=payload, headers=headers, stream=stream)
        if response.status_code == 429 and retry_count < max_retries:
            print(f"\n[-] Rate limit hit (429). Retrying in {backoff}s… ({retry_count + 1}/{max_retries})")
            time.sleep(backoff)
            retry_count += 1
            backoff *= 2
            continue
        if not response.ok:
            # response.text would consume the streaming body, but on a
            # non-2xx the server has already finished writing the error
            # payload — safe to read here.
            try:
                body = response.text[:1000]
            except Exception:
                body = "<could not read response body>"
            raise requests.HTTPError(
                f"HTTP {response.status_code} from {url}\nResponse body: {body}",
                response=response,
            )
        return response
