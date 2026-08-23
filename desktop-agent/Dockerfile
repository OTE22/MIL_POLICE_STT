# syntax=docker/dockerfile:1.7
# Local AI Agent image. Build args:
#   COMPUTE=cpu  (default, development / CPU workstations)
#   COMPUTE=gpu  (NVIDIA CUDA 12.4 workstations - run with --gpus all)
ARG COMPUTE=cpu
ARG CUDA_BASE=nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

FROM python:3.11-slim AS base-cpu
FROM ${CUDA_BASE} AS base-gpu
RUN apt-get update && apt-get install -y --no-install-recommends python3.11 python3.11-venv python3-pip && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.11 /usr/local/bin/python

FROM base-${COMPUTE} AS final
ARG COMPUTE
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /agent
COPY requirements.txt requirements-cpu.txt requirements-gpu.txt requirements-dev.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements-${COMPUTE}.txt \
    && python -m pip install -r requirements.txt \
    && python -m pip install -r requirements-dev.txt \
    && apt-get purge -y build-essential && apt-get autoremove -y

COPY . .
RUN mkdir -p /models /data && useradd --uid 1000 --create-home agent && chown -R agent:agent /agent /data
USER agent
ENV AGENT_MODEL_DIR=/models AGENT_DATA_DIR=/data AGENT_BIND_HOST=0.0.0.0 AGENT_ALLOW_NON_LOOPBACK_BIND=true
EXPOSE 17117
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fsS http://127.0.0.1:17117/health || exit 1
CMD ["python", "-m", "app.main"]
