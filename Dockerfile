# syntax=docker/dockerfile:1.7
ARG BASE_IMAGE=pytorch/pytorch:2.10.0-cuda12.8-cudnn9-runtime@sha256:b85566342b86d13a67712e9315d40cdc2dad7f8d86df1aff3831f80835edbcca
FROM ${BASE_IMAGE}

ARG COMFYUI_REF=426f5eea52a7ece1dd599fff4cb6cd1f352ddd24
ARG DEBIAN_FRONTEND=noninteractive

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV COMFYUI_ROOT=/opt/ComfyUI \
    BOOTSTRAP_ROOT=/opt/bootstrap \
    DATA_ROOT=/workspace \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      aria2 \
      ca-certificates \
      build-essential \
      cmake \
      curl \
      ffmpeg \
      file \
      git \
      git-lfs \
      jq \
      libgl1 \
      libglib2.0-0 \
      tini \
      util-linux \
      unzip \
    && rm -rf /var/lib/apt/lists/* \
    && git lfs install --system

RUN git init "${COMFYUI_ROOT}" \
    && git -C "${COMFYUI_ROOT}" remote add origin https://github.com/Comfy-Org/ComfyUI.git \
    && git -C "${COMFYUI_ROOT}" fetch --depth=1 origin "${COMFYUI_REF}" \
    && git -C "${COMFYUI_ROOT}" checkout --detach FETCH_HEAD

RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install torch==2.10.0 torchvision==0.25.0 torchaudio==2.10.0 \
      --index-url https://download.pytorch.org/whl/cu128

# Preserve the CUDA/PyTorch stack before installing either core or custom nodes.
# A custom-node requirement that requests an incompatible core package fails
# during the image build instead of silently replacing the GPU runtime.
RUN python - <<'PY'
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
packages = ("torch", "torchvision", "torchaudio", "triton")
lines = []
for package in packages:
    try:
        lines.append(f"{package}=={version(package)}")
    except PackageNotFoundError:
        pass
Path("/opt/bootstrap").mkdir(parents=True, exist_ok=True)
Path("/opt/bootstrap/core-constraints.txt").write_text("\n".join(lines) + "\n")
PY

RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --constraint /opt/bootstrap/core-constraints.txt \
      -r "${COMFYUI_ROOT}/requirements.txt"

COPY manifest/nodes.json /opt/bootstrap/manifest/nodes.json
COPY scripts/install_nodes.py /opt/bootstrap/scripts/install_nodes.py

RUN --mount=type=cache,target=/root/.cache/pip \
    python /opt/bootstrap/scripts/install_nodes.py \
      --manifest /opt/bootstrap/manifest/nodes.json \
      --comfy-root "${COMFYUI_ROOT}" \
      --constraints /opt/bootstrap/core-constraints.txt

COPY manifest/models.json manifest/workflows.json /opt/bootstrap/manifest/
COPY workflows /opt/bootstrap/workflows
COPY scripts/download_models.py scripts/doctor.py scripts/start.sh scripts/workflow_contract.py scripts/smoke_test.py /opt/bootstrap/scripts/

RUN chmod +x /opt/bootstrap/scripts/*.py /opt/bootstrap/scripts/*.sh \
    && python -m compileall -q /opt/bootstrap/scripts \
    && mkdir -p /workspace

RUN python -c "import torch, torchvision, torchaudio, triton; assert torch.__version__.startswith('2.10.0'); assert torch.version.cuda == '12.8'"

EXPOSE 8188

HEALTHCHECK --interval=30s --timeout=5s --start-period=2h --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${COMFY_PORT:-8188}/system_stats" >/dev/null || exit 1

ENTRYPOINT ["/usr/bin/tini", "-s", "--"]
CMD ["/opt/bootstrap/scripts/start.sh"]
