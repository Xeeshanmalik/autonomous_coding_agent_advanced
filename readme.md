Running LLM agent

# Autonomous Coding Agent

An AI-powered system that autonomously evolves machine learning code through iterative improvements using large language models. The agent can take a baseline implementation and automatically refine it to optimize performance metrics, with built-in self-healing capabilities for runtime errors.

## Features

- **Self-Evolving Research**: Iteratively improves ML code using LLM-driven suggestions
- **Self-Healing**: Automatically fixes runtime errors in generated code
- **Web Interface**: Modern React UI for task definition and monitoring
- **Local LLM Support**: Runs inference servers locally with llama.cpp
- **Flexible Models**: Support for local models (DeepSeek, Qwen) or cloud APIs (Gemini)
- **Dataset Upload**: Support for custom datasets
- **Real-time Streaming**: Live logs and progress updates

## Architecture

- **Frontend**: React application served via Nginx
- **Backend**: FastAPI server handling evolution loops
- **Inference**: llama.cpp-based servers for local LLM inference
- **Evolution Engine**: Python-based agent with self-healing inner loop

## Prerequisites

- Docker and Docker Compose
- At least 16GB RAM (for model loading)
- NVIDIA GPU with CUDA support (recommended for inference acceleration)
- 50GB+ free disk space for models and containers

## Quick Start

### 1. Clone the Repository

```bash
git clone <repository-url>
cd autonomous_coding_agent
```

### 2. Build the Docker Images

Build all required images:

```bash
# Build the reasoning inference server (DeepSeek model)
docker build -t inference-server-reasoning ./inference_server_reasoning

# Build the autoresearch agent backend
docker build -t ai-researcher ./autoresearch_agent

# Build the frontend UI
docker build -t ai-frontend-ui ./frontend
```

### 3. Create Docker Network

```bash
docker network create research-net
```

### 4. Start the Inference Server

Launch the local LLM backend:

```bash
docker run -d \
  --name local-deepseek-backend \
  --network research-net \
  --gpus all \
  -p 8085:8080 \
  inference-server-reasoning:latest \
  --host 0.0.0.0 \
  --port 8080 \
  -m /models/model.gguf \
  -c 4096 \
  -ngl 56
```

**Note**: The `-ngl 99` flag enables full GPU offloading. Adjust based on your GPU memory.

### 5. Start the Research Agent

Launch the backend that handles the evolution:

```bash
docker run -d \
  --name ai-researcher \
  --network research-net \
  -e LLM_BASE_URL="http://local-deepseek-backend:8080/v1" \
  -e LLM_MODEL="deepSeek-R1-Distill-Qwen-32B" \
  ai-researcher:latest
```

### 6. Start the Frontend

Launch the web interface:

```bash
docker run -d \
  --name ai-frontend-ui \
  --network research-net \
  -p 3000:8080 \
  ai-frontend-ui:latest
```

### 7. Access the Application

Open your browser and navigate to `http://localhost:3000`

## Usage

1. **Define Your Task**: Use the "Generate" tab to describe your ML research idea in plain language. The synthesis engine will create a structured task definition.

2. **Set Baseline**: Provide initial Python code in the "Baseline" tab that implements a basic solution.

3. **Configure**: In the "Config" tab:
   - Set number of evolution iterations
   - Choose model (local or Gemini)
   - Upload dataset if needed
   - Enter API key for Gemini if selected

4. **Run Evolution**: Click "Start" to begin the autonomous improvement process. Monitor progress in real-time through the streaming logs.

5. **Review Results**: The final optimized code will be available in the container's `train.py` file.

## Configuration

### Environment Variables

For the research agent (`ai-researcher`):

- `LLM_BASE_URL`: URL of the local inference server (default: `http://local-deepseek-backend:8080/v1`)
- `LLM_MODEL`: Model name for API calls (default: `deepSeek-R1-Distill-Qwen-32B`)
- `MAX_ITERATIONS`: Maximum evolution cycles (default: 5)

### Model Options

- **Local Models**:
  - DeepSeek-R1-Distill-Qwen-32B (reasoning-focused)
  - Qwen2.5-Coder-7B (code-focused)

- **Cloud Models**:
  - Google Gemini 2.0 Flash (requires API key)

### Alternative Inference Servers

For different models, build and run alternative servers:

```bash
# Qwen Coder model
docker build -t inference-server-coder ./inference_server
docker run -d --name local-qwen-backend --network research-net --gpus all -p 8086:8080 inference-server-coder:latest --host 0.0.0.0 --port 8080 -m /models/model.gguf -c 4096 -ngl 99
```

## Troubleshooting

### Common Issues

1. **Out of Memory**: If the model fails to load, reduce context size (`-c`) or GPU layers (`-ngl`)

2. **Network Issues**: Ensure containers are on the same Docker network and can communicate

3. **Build Failures**: Make sure you have sufficient disk space and internet connection for downloading models

4. **GPU Not Detected**: Verify NVIDIA drivers and Docker GPU support with `docker run --gpus all nvidia/cuda:11.0-base nvidia-smi`

### Logs

Check container logs for debugging:

```bash
docker logs ai-researcher
docker logs local-deepseek-backend
docker logs ai-frontend-ui
```

### Stopping the System

```bash
docker stop ai-frontend-ui ai-researcher local-deepseek-backend
docker rm ai-frontend-ui ai-researcher local-deepseek-backend
docker network rm research-net
```

## Development

### Local Development Setup

For frontend development:

```bash
cd frontend
npm install
npm run dev
```

For backend development:

```bash
cd autoresearch_agent
pip install -r requirements.txt
python server.py
```

### Building Custom Models

To use different GGUF models:

1. Download your model to `models/`
2. Update the Dockerfile's `RUN wget` command
3. Rebuild the inference server image

## License

[Add license information]

## Contributing

[Add contribution guidelines] 