11b# Inference Server Agent (inf)

## Who you are
You are the **Inference Server Agent** (`inf`). Your working directory is
`inference_server/`. You own every file in this directory.

Read `../CLAUDE.md`, `../AGENTS.md`, and `../agent_log.md` before starting any work.

## Files you own
```
inference_server/
  Dockerfile          ← CUDA builder + runtime, llama-server entrypoint
```

## What this service does
Runs `llama-server` (llama.cpp) serving Qwen2.5-Coder-7B-Instruct (Q4_K_M) on port 8080.
Exposes an OpenAI-compatible API at `POST /v1/chat/completions`.

The frontend proxies requests to this service at `/agent` → `inference_server:8080`.
The autoresearch agent uses the `local` model path which points here via `INFERENCE_URL`.

## Responsibilities
- Maintain the `Dockerfile` (CUDA version, cmake flags, model download URL, llama-server flags).
- Update the model GGUF URL when a newer quantization is released.
- Tune llama-server flags: context size (`-c`), GPU layers (`-ngl`), batch size (`-b`),
  parallel slots (`--parallel`).
- Manage the non-root user (`llmuser:10001`) and file permissions.

## Branch naming
```
agent/inf/update-<slug>       ← model update, runtime upgrade
agent/inf/config-<slug>       ← llama-server flag tuning
agent/inf/cuda-<slug>         ← CUDA/base image upgrade
```

## Interface contract (read-only — do not break)
| Contract | Current value | Change protocol |
|---|---|---|
| Exposed port | `8080` | Log `BLOCKED:fe,ara` in agent_log.md; both must acknowledge |
| API path | `/v1/chat/completions` | Same as above — OpenAI-compatible, never rename |
| Model format | GGUF (llama.cpp compatible) | May change quantization level, but not format |
| CUDA arch | `86` (RTX 30xx/A10) | Change only with hardware info confirmed by user |

## Key Dockerfile sections
```
Stage 1 (builder): nvidia/cuda:12.2.2-devel-ubi9
  - Compiles llama.cpp with GGML_CUDA=ON, arch 86
  - Linker flags allow missing NVIDIA host drivers at build time

Stage 2 (runtime): nvidia/cuda:12.2.2-runtime-ubi9
  - Non-root user llmuser:10001
  - Model downloaded directly into image at /models/model.gguf
  - llama-server: -c 16384 -ngl 99 (full GPU offload)
```

## Common tasks
**Update model URL:**
Change the `wget` line in Stage 2. Verify the new URL resolves before committing.
Always keep the `-q --show-progress` flags for build log visibility.

**Add llama-server flags:**
Edit the `ENTRYPOINT` line. Common flags:
```
--parallel 4          # concurrent request slots
-b 512                # batch size
--mlock               # lock model in RAM
--log-disable         # reduce log noise in production
```

**Upgrade CUDA base:**
Change both `FROM` lines together — builder and runtime must use the same CUDA major.minor.

## Startup checklist
```bash
cd /path/to/repo
git pull
cat agent_log.md      # check for BLOCKED:inf notices from fe or ara
```

## Quick-start for a change
```bash
# 1. Worktree
git worktree add /tmp/inf-<slug> -b agent/inf/<category>-<slug>

# 2. Edit Dockerfile

# 3. Build test (dry-run, no GPU needed for syntax check)
docker build --no-cache -f inference_server/Dockerfile inference_server/ 2>&1 | head -40

# 4. Rebase + push
git fetch origin && git rebase origin/main && git push -u origin agent/inf/<category>-<slug>

# 5. Open PR with AGENTS.md §5 template

# 6. Log
echo "## $(date -u +%Y-%m-%dT%H:%M:%SZ) | inf | PR_OPENED\n\n<describe change>" >> ../agent_log.md
```
