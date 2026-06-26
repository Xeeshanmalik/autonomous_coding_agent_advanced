# ==========================================
# STAGE 1: The Secure Researcher Builder
# ==========================================
FROM registry.access.redhat.com/ubi9/ubi:latest AS builder

RUN dnf install -y --allowerasing gcc-c++ make cmake git && \
    dnf clean all

WORKDIR /app

# Clone the repository
RUN git clone https://github.com/karpathy/autoresearch.git .

# Comprehensive requirements list for Karpathy's research scripts + FastAPI Backend
RUN echo "requests" > requirements.txt && \
    echo "numpy" >> requirements.txt && \
    echo "torch" >> requirements.txt && \
    echo "tqdm" >> requirements.txt && \
    echo "pyarrow" >> requirements.txt && \
    echo "pandas" >> requirements.txt && \
    echo "tiktoken" >> requirements.txt && \
    echo "openai" >> requirements.txt && \
    echo "anthropic" >> requirements.txt && \
    echo "dirtyjson" >> requirements.txt && \
    echo "fastapi" >> requirements.txt && \
    echo "uvicorn" >> requirements.txt && \
    echo "python-multipart" >> requirements.txt && \
    echo "scikit-learn" >> requirements.txt && \
    echo "scipy" >> requirements.txt && \
    echo "imbalanced-learn" >> requirements.txt && \
    echo "sdv" >> requirements.txt && \
    echo "copulas" >> requirements.txt && \
    echo "ctgan" >> requirements.txt

# ==========================================
# STAGE 2: Secure Runtime (The Optimized Sandbox)
# ==========================================
FROM registry.access.redhat.com/ubi9/ubi-minimal:latest

# Essential runtimes and Git for the research loop
RUN microdnf install -y python3 python3-pip git libstdc++ libgcc libgomp ca-certificates vim-minimal && \
    microdnf clean all && \
    ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /research

# Copy 'uv' for high-speed package management (Directly to runtime for visibility)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy research logic and dependencies from builder
COPY --from=builder /app /research

# Install all dependencies (including FastAPI stack) using uv for speed and reliability
RUN uv pip install --no-cache -r requirements.txt --system

# Create isolated researcher user
RUN echo "researcher:x:10002:10002:AI Researcher:/research:/sbin/nologin" >> /etc/passwd && \
    echo "researchgroup:x:10002:" >> /etc/group


# Set up Git context (Essential for the logic in autoresearch.py)
RUN git config --global user.email "researcher@internal.local" && \
    git config --global user.name "AI Researcher" && \
    git config --global init.defaultBranch master && \
    git init && \
    git add . && \
    git commit -m "Initial baseline"

# Environment Configuration
ENV LLM_BASE_URL="http://local-qwen-backend:8080/v1"
ENV LLM_MODEL="qwen2.5-coder-7b"
ENV PYTHONUNBUFFERED=1

# Security and Permissions hardening
RUN chown -R 10002:10002 /research && \
    chmod -R 755 /research && \
    chmod 644 /research/prepare.py

COPY ./autoresearch.py /research/autoresearch.py
# The agent implementation lives in the `ara` package; the shim above imports it.
COPY ./ara /research/ara
COPY ./server.py /research/server.py
# dashboard_export.py is staged into each per-run workdir by autoresearch.py so
# champion scripts can `import dashboard_export`; it must be present in the image.
COPY ./dashboard_export.py /research/dashboard_export.py

USER 10002:10002

# We expose 8000 here assuming you will run uvicorn on its default port
EXPOSE 8000

# Entrypoint: Keeps container alive for SSH/exec
CMD ["python3", "server.py"]