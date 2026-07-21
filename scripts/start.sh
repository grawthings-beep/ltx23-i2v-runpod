#!/usr/bin/env bash
set -Eeuo pipefail

COMFYUI_ROOT="${COMFYUI_ROOT:-/opt/ComfyUI}"
DATA_ROOT="${DATA_ROOT:-/workspace}"
BOOTSTRAP_ROOT="${BOOTSTRAP_ROOT:-/opt/bootstrap}"
COMFY_PORT="${COMFY_PORT:-8188}"
MODEL_PROFILE="${MODEL_PROFILE:-workflow}"

log() {
  printf '[bootstrap] %s\n' "$*" >&2
}

link_dir() {
  local persistent="$1"
  local target="$2"
  mkdir -p "${persistent}"
  if [[ -L "${target}" ]]; then
    local resolved
    resolved="$(readlink -f "${target}" || true)"
    if [[ "${resolved}" == "$(readlink -f "${persistent}")" ]]; then
      return
    fi
    rm -f "${target}"
  elif [[ -e "${target}" ]]; then
    rm -rf "${target}"
  fi
  ln -s "${persistent}" "${target}"
}

mkdir -p \
  "${DATA_ROOT}/models" \
  "${DATA_ROOT}/input" \
  "${DATA_ROOT}/output" \
  "${DATA_ROOT}/user/default/workflows" \
  "${DATA_ROOT}/cache/huggingface" \
  "${DATA_ROOT}/cache/torch" \
  "${DATA_ROOT}/cache/downloads" \
  "${DATA_ROOT}/logs" \
  "${DATA_ROOT}/.bootstrap" \
  /tmp/comfy

link_dir "${DATA_ROOT}/models" "${COMFYUI_ROOT}/models"
link_dir "${DATA_ROOT}/input" "${COMFYUI_ROOT}/input"
link_dir "${DATA_ROOT}/output" "${COMFYUI_ROOT}/output"
link_dir "${DATA_ROOT}/user" "${COMFYUI_ROOT}/user"
link_dir /tmp/comfy "${COMFYUI_ROOT}/temp"

for workflow in "${BOOTSTRAP_ROOT}"/workflows/*.json; do
  [[ -e "${workflow}" ]] || continue
  destination="${DATA_ROOT}/user/default/workflows/$(basename "${workflow}")"
  if [[ ! -e "${destination}" ]]; then
    cp "${workflow}" "${destination}"
    log "installed workflow: ${destination}"
  fi
done

export HF_HOME="${HF_HOME:-${DATA_ROOT}/cache/huggingface}"
export TORCH_HOME="${TORCH_HOME:-${DATA_ROOT}/cache/torch}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-${DATA_ROOT}/cache}"
export PYTHONUNBUFFERED=1
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
export MALLOC_TRIM_THRESHOLD_="${MALLOC_TRIM_THRESHOLD_:-65536}"

if [[ "${SKIP_MODEL_DOWNLOAD:-0}" != "1" ]]; then
  exec 9>"${DATA_ROOT}/.bootstrap/models.lock"
  flock 9
  log "ensuring model profile '${MODEL_PROFILE}'"
  log "ComfyUI will start after model download and doctor checks complete"
  python "${BOOTSTRAP_ROOT}/scripts/download_models.py" \
    --manifest "${BOOTSTRAP_ROOT}/manifest/models.json" \
    --data-root "${DATA_ROOT}" \
    --profile "${MODEL_PROFILE}"
  flock -u 9
else
  log "SKIP_MODEL_DOWNLOAD=1; model download skipped"
fi

doctor_args=(
  --manifest-root "${BOOTSTRAP_ROOT}/manifest"
  --data-root "${DATA_ROOT}"
  --comfy-root "${COMFYUI_ROOT}"
  --profile "${MODEL_PROFILE}"
  --workflow "${DATA_ROOT}/user/default/workflows/MrXin LTX 2.3 I2V EROS V6.1.json"
)
if [[ "${SKIP_MODEL_DOWNLOAD:-0}" == "1" ]]; then
  doctor_args+=(--skip-models)
fi
python "${BOOTSTRAP_ROOT}/scripts/doctor.py" "${doctor_args[@]}"

default_args=(
  --listen 0.0.0.0
  --port "${COMFY_PORT}"
  --disable-auto-launch
  --preview-method auto
)

extra_args=()
if [[ -n "${COMFY_ARGS:-}" ]]; then
  # COMFY_ARGS is intentionally shell-word-split so RunPod users can pass flags.
  read -r -a extra_args <<< "${COMFY_ARGS}"
fi

log "starting ComfyUI on port ${COMFY_PORT}"
cd "${COMFYUI_ROOT}"
exec python main.py "${default_args[@]}" "${extra_args[@]}"
