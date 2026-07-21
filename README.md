# MrXin LTX 2.3 I2V EROS V6.1 on RunPod

Deterministic RunPod image for the unmodified
`MrXin LTX 2.3 I2V EROS V6.1.json` ComfyUI workflow.

The image:

1. builds ComfyUI `v0.17.2`;
2. installs 15 custom-node repositories at full commit SHAs;
3. downloads 15 verified model artifacts into persistent `/workspace` storage;
4. installs the workflow once without overwriting later user edits;
5. runs doctor checks, then starts ComfyUI on `0.0.0.0:8188`.

Models are not baked into the Docker image. Downloads use parallel, resumable
`aria2c` transfers and survive Pod replacement when the same network volume is
reused.

## Workflow provenance

- File: `workflows/MrXin LTX 2.3 I2V EROS V6.1.json`
- Source: [MrXin V6.1 archive](https://huggingface.co/ThirdTimesTheCiarc/workflows/resolve/main/2488266/2962842/mrxinLTX23I2VEros12GBVRAM_i2vV61.zip)
- Source archive SHA-256: `46ab86520ffb28dd3e131f48727402146d372d3585896cc52efe3ed777c3962f`
- Workflow JSON SHA-256: `a29ff5b4cecfe2cc399b6590fae299038996169e742e7a4c4a8ae40376aa50cd`

The workflow content and filename are preserved exactly. The repository contains
V6.1 only; the former V2 workflow is not included.

## RunPod template

Use `runpod/template-settings.json` as the source of truth.

| Setting | Value |
|---|---|
| Container image | `ghcr.io/grawthings-beep/ltx23-i2v-runpod:latest` |
| Container disk | 35 GB |
| Network volume | about 250 GB |
| Volume mount | `/workspace` |
| HTTP port | `8188` |
| Start command | leave empty |

Create a RunPod secret named exactly `HF_TOKEN`. In the template environment
variable editor, add a variable named `HF_TOKEN`, select the secret with the key
icon, and let RunPod render its reference. In raw form it is:

```text
HF_TOKEN={{ RUNPOD_SECRET_HF_TOKEN }}
```

Do not add quotes around the reference. The current V6.1 manifest uses pinned
Hugging Face and GitHub mirrors, so `CIVITAI_TOKEN` and private `MODEL_URL_*`
variables are not required. The downloader still supports `CIVITAI_TOKEN` for
future manifest entries.

Use these environment variables:

```text
MODEL_PROFILE=workflow
DOWNLOAD_CONCURRENCY=5
DOWNLOAD_CONNECTIONS=16
DOWNLOAD_MAX_TRIES=10
NODE_CLONE_CONCURRENCY=6
ALLOW_MISSING_MODEL_URLS=0
SKIP_MODEL_DOWNLOAD=0
COMFY_PORT=8188
COMFY_ARGS=
```

An NVIDIA A40 has ample VRAM for this graph. Leave `COMFY_ARGS` empty initially;
`--lowvram` is intended only for smaller cards or troubleshooting.

## First start

The default `workflow` profile downloads 12 files totaling about 60.39 GB
(56.24 GiB). ComfyUI starts only after downloads and doctor checks pass,
so the RunPod HTTP proxy can return 404 during the initial download. Follow the
Pod logs for live aria2 progress.

Completed files are validated by exact byte count, safetensors header, and
SHA-256, then skipped on later starts. `.aria2` partial files are resumed.

The workflow is copied once to:

```text
/workspace/user/default/workflows/MrXin LTX 2.3 I2V EROS V6.1.json
```

User edits are never overwritten. If the same volume still contains the old V2
workflow, delete it manually in ComfyUI or from `/workspace`; bootstrap does not
delete persistent user files.

## Persistent layout

```text
/workspace/models
/workspace/input
/workspace/output
/workspace/user
/workspace/cache
/workspace/logs
```

Only `/tmp/comfy` is intentionally ephemeral.

## Download profiles

| Profile | Files | Size | Contents |
|---|---:|---:|---|
| `public` | 9 | 55.79 GB | V6.1 models enabled by the graph |
| `workflow` | 12 | 60.39 GB | `public` plus the three optional concept LoRAs |
| `all` | 15 | 85.49 GB | every reference, including bypassed alternate loaders and RIFE |

The concept LoRAs referenced by V6.1 are included in `workflow`, even though their
slots are initially off, so enabling them does not require another URL. `all`
also downloads the bypassed alternate transformer and upscaler loaders.

## Local validation

```bash
python scripts/validate_repo.py
python -m compileall scripts
python -m unittest discover -s tests -v
bash -n scripts/start.sh
make validate
```

Build locally when Docker is available:

```bash
docker build -t ltx23-i2v-runpod:test .
```

For UI-only diagnostics without downloading models:

```bash
SKIP_MODEL_DOWNLOAD=1 docker compose up --build
```

## GitHub Actions and GHCR

Pushes and pull requests run static validation. Pushes to `main` and `v*` tags
build and publish with Docker metadata/build-push actions. The default-branch
image is:

```text
ghcr.io/grawthings-beep/ltx23-i2v-runpod:latest
```

## Security and licensing

Tokens are runtime RunPod secrets. They must not be committed, passed as Docker
build arguments, or embedded in model URLs. The infrastructure code is MIT
licensed; the workflow, ComfyUI, custom nodes, and models retain their respective
upstream licenses and usage terms.
