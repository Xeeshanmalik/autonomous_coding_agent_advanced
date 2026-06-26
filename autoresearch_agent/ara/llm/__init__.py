"""LLM client subpackage — talking to the language model.

Public API
----------
``query_llm`` — the one function the rest of the agent calls to get a model
completion. Backend selection (Anthropic / OpenAI-compatible / Gemini), prompt
caching, streaming, retries and cooperative cancellation all live behind it.

Internal layout
---------------
- ``content``   — reshape message content per backend.
- ``transport`` — shared HTTP POST with 429 backoff.
- ``openai_compat`` / ``anthropic`` — the two wire formats.
- ``client``    — ``query_llm`` dispatcher (re-exported here).

Monkeypatch point
-----------------
Tests and callers reference ``ara.llm.query_llm`` (via ``from ara import llm``
then ``llm.query_llm(...)``) so replacing this name redirects every caller.
"""

from ara.llm.client import query_llm

__all__ = ["query_llm"]
