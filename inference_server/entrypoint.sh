#!/bin/sh
# ==========================================================================
# llama-server entrypoint with a hard GPU guard.
#
# Why this exists:
#   A 7B model with no visible CUDA device makes llama.cpp print a warning and
#   silently fall back to CPU — it ignores -ngl, loads the model into ~22 GB of
#   RAM, and crawls so slowly that requests look like they "never return a
#   token". To stop that failure mode from masquerading as a hang, we refuse to
#   start CPU-only by default and tell the operator how to fix the launch.
#
# Tuning (context size, gpu layers, parallel slots) lives HERE, in the image,
# NOT in a `docker run`/compose `command:` override. Overriding the launch is
# the foot-gun that produced the old `-c 1024` / `-ngl 58` CPU launches (see
# docker-compose.yml). Any extra args passed to the container are ignored.
# ==========================================================================
set -e

if [ "$#" -gt 0 ]; then
  echo "[entrypoint] WARNING: ignoring container args ($*)." >&2
  echo "[entrypoint] llama-server flags are fixed in entrypoint.sh (inf-owned)." >&2
fi

# Hard GPU guard. /dev/nvidiactl is created inside the container by the NVIDIA
# Container Toolkit only when the GPU is actually passed in (compose `deploy`
# block, or `docker run --gpus all`). Set LLAMA_ALLOW_CPU=1 to opt into a
# (much slower) CPU-only run on purpose.
if [ "${LLAMA_ALLOW_CPU:-0}" != "1" ]; then
  if [ ! -e /dev/nvidiactl ]; then
    echo "[entrypoint] FATAL: no NVIDIA GPU visible inside the container." >&2
    echo "[entrypoint] Refusing to start: llama-server would silently run the 7B" >&2
    echo "[entrypoint] model on CPU (-ngl ignored), loading it into RAM and" >&2
    echo "[entrypoint] stalling on every request." >&2
    echo "[entrypoint]" >&2
    echo "[entrypoint] Launch WITH the GPU:" >&2
    echo "[entrypoint]   cd inference_server && docker compose up -d --build" >&2
    echo "[entrypoint]   (or: docker run --gpus all ... )" >&2
    echo "[entrypoint]" >&2
    echo "[entrypoint] To run CPU-only on purpose: set LLAMA_ALLOW_CPU=1." >&2
    exit 1
  fi
  echo "[entrypoint] NVIDIA GPU detected; starting llama-server with full offload (-ngl 99)." >&2
fi

# Full GPU offload for Qwen2.5-Coder-7B Q4_K_M (~4.6 GB weights). Flash
# attention (-fa on) keeps the 16384-token KV cache within a 16 GB card.
exec /usr/local/bin/llama-server \
  --host 0.0.0.0 \
  --port 8080 \
  -m /models/model.gguf \
  -c 16384 \
  -ngl 99 \
  --parallel 4 \
  --mlock \
  -fa on
