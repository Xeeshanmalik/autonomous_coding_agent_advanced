"""LLM dispatch — the single entry point every component calls.

What this module does
---------------------
Defines ``query_llm``, which checks for cancellation and routes the request to
the configured backend (Anthropic vs OpenAI-compatible), returning the model's
text reply.

Why it exists
-------------
Everything that talks to the model — baseline analysis, bootstrap, history
compression, self-healing, and all Phase-10 agents — goes through this one
function, so backend selection and cancellation live in exactly one place.

How it fits the architecture
----------------------------
Top of the ``llm`` subpackage. Depends on ``config`` (backend flag),
``lifecycle`` (pre-call cancel check), and the two backend modules. Re-exported
as ``ara.llm.query_llm`` (the canonical monkeypatch point for tests).

Note (flagged, unchanged): the original kept unreachable code after the
``return`` in this function (a write to ``last_llm_response.log`` referencing an
undefined name). It never executed and is omitted here — behaviour is identical.
"""

from typing import List

from ara import config, lifecycle
from ara.llm.anthropic import _query_anthropic
from ara.llm.openai_compat import _query_openai_compat


def query_llm(messages: List[dict], stream: bool = True, temp: float = 0.3,
              quiet: bool = False) -> str:
    """Dispatch a chat request to the configured backend and return its text.

    Backends:
      - Anthropic (``USE_ANTHROPIC=true``) — native /v1/messages with
        ``cache_control`` breakpoints.
      - Gemini (``USE_GEMINI=true``) — OpenAI-compatible endpoint, no explicit cache.
      - Default — OpenAI-compatible local llama.cpp (automatic KV prefix cache).

    Message content may be a plain string OR a list of text blocks. The Anthropic
    backend preserves the block structure (including any ``cache_control``
    markers); the other backends flatten the blocks into a single string.

    ``quiet=True`` suppresses the live streaming print so the caller can buffer
    and emit the response with its own prefix. Parallel agents (CodeGen,
    SelfHealer) use this to avoid character-level interleave on stdout when K
    threads stream concurrently.

    Cancellation: SIGTERM aborts before the request and again mid-stream by
    closing the socket so the inference server stops generation immediately
    (Phase 9).
    """
    lifecycle._check_cancel(None, "before LLM call")
    if config.USE_ANTHROPIC:
        return _query_anthropic(messages, stream, temp, quiet=quiet)
    return _query_openai_compat(messages, stream, temp, quiet=quiet)
