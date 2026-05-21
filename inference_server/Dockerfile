# ==========================================
# STAGE 1: The CUDA Builder 
# ==========================================
FROM nvidia/cuda:12.2.2-devel-ubi9 AS builder

RUN dnf install -y gcc-c++ make cmake git && \
    dnf clean all

WORKDIR /build

# BELT AND SUSPENDERS: 
# 1. Copy the fake driver stub directly into the core Linux library folder
RUN cp /usr/local/cuda/lib64/stubs/libcuda.so /usr/lib64/libcuda.so.1 || true
ENV LIBRARY_PATH="/usr/local/cuda/lib64/stubs:$LIBRARY_PATH"

# 2. Force the linker to ignore missing NVIDIA host drivers during the build
RUN git clone --depth 1 https://github.com/ggerganov/llama.cpp.git . && \
    cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=86 \
    -DCMAKE_SHARED_LINKER_FLAGS="-Wl,--allow-shlib-undefined" \
    -DCMAKE_EXE_LINKER_FLAGS="-Wl,--allow-shlib-undefined" \
    -DCMAKE_INSTALL_PREFIX=/opt/llama && \
    cmake --build build --config Release --target install -j4

# ==========================================
# STAGE 2: Secure CUDA Runtime & Model Download
# ==========================================
FROM nvidia/cuda:12.2.2-runtime-ubi9

# Added 'wget' so we can download the model directly into the image
RUN dnf install -y libstdc++ libgcc libgomp wget && \
    dnf clean all

WORKDIR /app

RUN echo "llmuser:x:10001:10001:LLM User:/app:/sbin/nologin" >> /etc/passwd && \
    echo "llmgroup:x:10001:" >> /etc/group

RUN mkdir -p /models && chown -R 10001:10001 /models

# Download the Qwen 2.5 Coder 7B directly into the image (Corrected URL)
RUN wget -q --show-progress -O /models/model.gguf https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf && \
    chown 10001:10001 /models/model.gguf

COPY --from=builder /opt/llama /usr/local/


ENV LD_LIBRARY_PATH=/usr/local/lib:/usr/local/lib64:$LD_LIBRARY_PATH

RUN chown root:root /usr/local/bin/llama-server && \
    chmod 755 /usr/local/bin/llama-server

USER 10001:10001
EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/llama-server", "--host", "0.0.0.0", "--port", "8080", "-m", "/models/model.gguf", "-c", "16384", "-ngl", "99", "--parallel", "4"]