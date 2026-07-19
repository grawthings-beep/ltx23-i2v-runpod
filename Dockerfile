# syntax=docker/dockerfile:1.7
ARG BASE_IMAGE=runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404
FROM ${BASE_IMAGE}

ARG COMFYUI_REF=v0.17.2
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
      curl \
      ffmpeg \
      file \
      git \
      git-lfs \
      jq \
      libgl1 \
      libglib2.0-0 \
      tini \
      unzip \
    && rm -rf /var/lib/apt/lists/* \
    && git lfs install --system

RUN git clone --depth=1 --branch "${COMFYUI_REF}" \
      https://github.com/Comfy-Org/ComfyUI.git "${COMFYUI_ROOT}"

RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -r "${COMFYUI_ROOT}/requirements.txt"

# Preserve the CUDA/PyTorch stack supplied by the tested RunPod base image.
# A custom-node requirement that requests an incompatible core package fails
# during the image build instead of silently replacing the GPU runtime.
RUN python - <<'PY'
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
packages = ("torch", "torchvision", "torchaudio")
lines = []
for package in packages:
    try:
        lines.append(f"{package}=={version(package)}")
    except PackageNotFoundError:
        pass
Path("/opt/bootstrap").mkdir(parents=True, exist_ok=True)
Path("/opt/bootstrap/core-constraints.txt").write_text("\n".join(lines) + "\n")
PY

COPY manifest/nodes.json /opt/bootstrap/manifest/nodes.json
COPY scripts/install_nodes.py /opt/bootstrap/scripts/install_nodes.py

RUN --mount=type=cache,target=/root/.cache/pip \
    python /opt/bootstrap/scripts/install_nodes.py \
      --manifest /opt/bootstrap/manifest/nodes.json \
      --comfy-root "${COMFYUI_ROOT}" \
      --constraints /opt/bootstrap/core-constraints.txt

COPY manifest/models.json /opt/bootstrap/manifest/models.json
COPY workflows /opt/bootstrap/workflows
COPY scripts/download_models.py scripts/doctor.py scripts/start.sh /opt/bootstrap/scripts/

RUN chmod +x /opt/bootstrap/scripts/*.py /opt/bootstrap/scripts/*.sh \
    && python -m compileall -q /opt/bootstrap/scripts \
    && mkdir -p /workspace

EXPOSE 8188

HEALTHCHECK --interval=30s --timeout=5s --start-period=30m --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${COMFY_PORT:-8188}/system_stats" >/dev/null || exit 1

ENTRYPOINT ["/usr/bin/tini", "-s", "--"]
CMD ["/opt/bootstrap/scripts/start.sh"]
