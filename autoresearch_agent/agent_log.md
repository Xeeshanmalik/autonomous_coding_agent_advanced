
---

## 2026-05-23T12:30:00Z | ara | MERGE_COMPLETED

PR #15 merged into main as baa0db3: feat(ara): phase 4 — prompt caching via Anthropic cache_control breakpoints.
USE_ANTHROPIC backend now available; analyze_baseline + research loop emit stable-prefix
content blocks that benefit both Anthropic's ephemeral cache and llama.cpp's automatic KV prefix cache.
Remaining ara work: Phase 8 (variance reduction, unblocked) and Phase 10 (multi-agent harness, still waits on Phase 8).
