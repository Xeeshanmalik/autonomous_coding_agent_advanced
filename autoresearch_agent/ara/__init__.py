"""AutoResearch agent — a self-evolving autonomous coding/research loop.

The agent takes a task (``program.md``), a baseline script (``train.py``) and an
optional dataset, then runs an evolutionary search that repeatedly asks an LLM to
improve the script, evaluates each candidate in a CPU-only sandbox, and keeps the
lowest ``val_loss`` champion — streaming progress + chart data to the frontend.

Read ``ARCHITECTURE.md`` (next to this package) for the phase map and the
per-cycle data-flow diagram. Module-by-module, the layering is:

    config / lifecycle / prompts / parsing      ← leaves (settings, signals, text)
        ↓
    llm (query_llm)                             ← talk to the model
        ↓
    sandbox · evaluation · population ·         ← domain services
    analysis · dataset_introspect · bootstrap ·
    checkpoint · history · healing · dashboard
        ↓
    agents → orchestrator                       ← Phase-10 multi-agent harness
        ↓
    cli                                         ← entrypoint (run/main)

Public API
----------
The names below are re-exported for convenience. Note the canonical monkeypatch
points used by tests are the defining modules — ``ara.llm.query_llm`` and
``ara.sandbox.run_in_sandbox`` — not these aliases.
"""

from ara import config
from ara.cli import main, run
from ara.evaluation import robust_eval, run_candidate_pool
from ara.llm import query_llm
from ara.orchestrator import director_one_cycle, research_director
from ara.population import (
    Population,
    PopulationMember,
    select_parent,
    update_population,
)
from ara.sandbox import CandidateResult, run_cmd, run_in_sandbox

__all__ = [
    "config",
    "main",
    "run",
    "query_llm",
    "run_in_sandbox",
    "run_cmd",
    "CandidateResult",
    "robust_eval",
    "run_candidate_pool",
    "Population",
    "PopulationMember",
    "select_parent",
    "update_population",
    "director_one_cycle",
    "research_director",
]
