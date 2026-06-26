#!/bin/sh
# ==========================================================================
# llama-server entrypoint (reasoning variant: DeepSeek-R1-Distill-Qwen-32B).
#
# Why this exists:
#   With no visible CUDA device, llama.cpp prints a warning and silently falls
#   back to CPU: it ignores -ngl, loads the full ~14.8 GB model into RAM, and
#   crawls so slowly that requests look like they "never return a token". That
#   is exactly the failure this image hit (nvidia-smi: 0% GPU, ~22 GB RAM).
#   We refuse to start CPU-only by default so the misconfiguration is loud.
#
# VRAM note (16 GB card, e.g. RTX 3080):
#   A 32B Q3_K_M (~14.8 GB of weights) does NOT fully offload. After the CUDA
#   context (~1 GB), KV cache (-c 4096 ≈ 1 GB) and compute buffers, only ~55 of
#   the 65 layers fit. The rest spill to CPU. Push LLAMA_NGL up while watching
#   `nvidia-smi`; back off if you hit a CUDA out-of-memory at load.
#
# Tunable via env (no `docker run`/compose command override needed):
#   LLAMA_NGL   GPU layers to offload   (default 55)
#   LLAMA_CTX   context size            (default 4096)
#   LLAMA_ALLOW_CPU=1  run CPU-only on purpose (skips the GPU guard)
# ==========================================================================
set -e

NGL="${LLAMA_NGL:-55}"
CTX="${LLAMA_CTX:-4096}"

if [ "$#" -gt 0 ]; then
  echo "[entrypoint] WARNING: ignoring container args ($*); tune via LLAMA_NGL / LLAMA_CTX env." >&2
fi

# Hard GPU guard. /dev/nvidiactl is created inside the container by the NVIDIA
# Container Toolkit only when the GPU is actually passed in (`--gpus all` or a
# compose `deploy` block). Set LLAMA_ALLOW_CPU=1 to opt into a CPU-only run.
if [ "${LLAMA_ALLOW_CPU:-0}" != "1" ]; then
  if [ ! -e /dev/nvidiactl ]; then
    echo "[entrypoint] FATAL: no NVIDIA GPU visible inside the container." >&2
    echo "[entrypoint] Refusing to start: llama-server would silently run the 32B" >&2
    echo "[entrypoint] model on CPU (-ngl ignored), loading ~14.8 GB into RAM and" >&2
    echo "[entrypoint] stalling on every request." >&2
    echo "[entrypoint]" >&2
    echo "[entrypoint] Launch WITH the GPU:" >&2
    echo "[entrypoint]   docker run -d --gpus all -p 8085:8080 inference-server-reasoning:latest" >&2
    echo "[entrypoint]" >&2
    echo "[entrypoint] To run CPU-only on purpose: set LLAMA_ALLOW_CPU=1." >&2
    exit 1
  fi
  echo "[entrypoint] NVIDIA GPU detected; offloading ${NGL} layers (-c ${CTX})." >&2
fi

# -fa on (flash attention) keeps the KV cache small; -np 1 keeps a single slot
# so the whole context budget goes to one request (matches autoresearch usage).
exec /usr/local/bin/llama-server \
  --host 0.0.0.0 \
  --port 8080 \
  -m /models/model.gguf \
  -c "${CTX}" \
  -ngl "${NGL}" \
  -fa on \
  -np 1
