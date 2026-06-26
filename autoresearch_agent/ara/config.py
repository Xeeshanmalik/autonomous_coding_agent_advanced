"""Central configuration for the AutoResearch agent.

What this module does
---------------------
Reads every environment-driven setting and fixed constant the agent needs —
LLM backend selection and credentials, evolutionary-search tunables, on-disk
state paths, and frontend-telemetry constants — and exposes them as plain
module-level values.

Why it exists
-------------
The original single-file agent scattered ``os.environ.get(...)`` reads across the
file, so the effective configuration was impossible to see at a glance. Pulling
them here gives one authoritative place to read or override behaviour.

How it fits the architecture
----------------------------
Leaf module: it imports nothing from the rest of the package and everything else
imports *from* it. All values are resolved once, at import time, exactly as the
original module did — so the environment must be set before the package is
imported (the server subprocess sets it via ``env=`` in ``Popen``, then imports
fresh).

Access pattern note
-------------------
Modules that may need a value overridden at runtime (e.g. tests patching
``CANDIDATE_POOL_SIZE`` or ``ENABLE_SELF_HEALER``) read it as ``config.NAME`` via
``from ara import config`` rather than binding the name at import. That keeps a
single source of truth a monkeypatch can redirect.
"""

import os

# ---------------------------------------------------------------------------
# LLM endpoint configuration
# ---------------------------------------------------------------------------
# Three mutually exclusive backends, selected by environment flags. Each sets
# the request URL, model id and API key; the Anthropic branch additionally
# exposes the version + max-tokens knobs its native /v1/messages API needs.
USE_ANTHROPIC: bool = os.environ.get("USE_ANTHROPIC") == "true"
USE_GEMINI: bool = os.environ.get("USE_GEMINI") == "true"

if USE_ANTHROPIC:
    # Native /v1/messages endpoint — the only backend that honours
    # cache_control breakpoints (Phase 4 prompt caching).
    LLM_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1") + "/messages"
    MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    ANTHROPIC_VERSION = os.getenv("ANTHROPIC_VERSION", "2023-06-01")
    ANTHROPIC_MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", 4096))
elif USE_GEMINI:
    LLM_URL = "https://generativelanguage.googleapis.com/v1beta/openai/v1/chat/completions"
    MODEL = "models/gemini-2.0-flash"
    API_KEY = os.environ.get("GEMINI_API_KEY", "")
else:
    LLM_URL = os.getenv("LLM_BASE_URL", "http://local-qwen-backend:8080/v1") + "/chat/completions"
    MODEL = os.getenv("LLM_MODEL", "deepSeek-R1-Distill-Qwen-32B")
    API_KEY = "dummy"

# ---------------------------------------------------------------------------
# Evolutionary-search tunables
# ---------------------------------------------------------------------------
# How many candidate scripts each cycle generates (Phase 1) and how many
# members the population keeps (Phase 2).
CANDIDATE_POOL_SIZE: int = int(os.environ.get("CANDIDATE_POOL_SIZE", 3))
POPULATION_SIZE: int = int(os.environ.get("POPULATION_SIZE", 3))

# Softmax sharpness for parent selection — higher = greedier (Phase 2).
SELECT_PARENT_BETA: float = 4.0

# Variance-reduction re-evaluation (Phase 8): near-frontier candidates are
# re-run K times and the median loss is kept; MARGIN defines "near-frontier".
ROBUST_EVAL_K: int = int(os.environ.get("ROBUST_EVAL_K", 3))
ROBUST_EVAL_MARGIN: float = float(os.environ.get("ROBUST_EVAL_MARGIN", 0.05))

# Bootstrap retries when the baseline does not print a finite val_loss.
BOOTSTRAP_MAX_ATTEMPTS: int = int(os.environ.get("BOOTSTRAP_MAX_ATTEMPTS", 3))

# Experiment history is summarised by an LLM once it exceeds this length (Phase 7).
HISTORY_COMPRESS_AFTER: int = 10

# Whether crashed candidates get a parallel SelfHealer repair pass (Phase 10).
ENABLE_SELF_HEALER: bool = os.environ.get("ENABLE_SELF_HEALER", "true").lower() == "true"

# ---------------------------------------------------------------------------
# On-disk state paths (relative to the per-run working directory)
# ---------------------------------------------------------------------------
POPULATION_PATH: str = "population.json"
CHECKPOINT_PATH: str = "checkpoint.json"

# ---------------------------------------------------------------------------
# Frontend telemetry
# ---------------------------------------------------------------------------
# The frontend stream splits on newlines and routes lines prefixed with
# EVENT_PREFIX through its event dispatcher. Chart series are capped to
# DASHBOARD_MAX_POINTS points before being emitted.
EVENT_PREFIX: str = "__EVENT__"
DASHBOARD_MAX_POINTS: int = 500
