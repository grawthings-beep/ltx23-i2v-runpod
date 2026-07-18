# LTX 2.3 I2V / ComfyUI / RunPod

The repository is a deterministic RunPod image for the supplied
`MrXin LTX 2.3 I2V EROS V2` ComfyUI workflow.

It does four things and nothing else:

1. Builds ComfyUI `v0.17.2`.
2. Installs the custom-node repositories at pinned commits.
3. Downloads model files into persistent `/workspace` storage with parallel,
   resumable `aria2c` transfers.
4. Starts ComfyUI on port `8188`.

Models are deliberately **not** baked into the container image. The image remains
small enough to update normally, while models survive Pod replacement on the
network volume.

## Repository layout

```text
.
├── Dockerfile
├── manifest/
│   ├── models.json          # model URLs, exact filenames, profiles and destinations
│   └── nodes.json           # custom-node repositories and pinned commits
├── scripts/
│   ├── download_models.py   # parallel/resumable downloader
│   ├── install_nodes.py     # deterministic custom-node installer
│   ├── doctor.py            # GPU, disk, model and node preflight
│   ├── validate_repo.py     # workflow/manifest consistency check
│   └── start.sh             # idempotent RunPod bootstrap and ComfyUI launch
├── workflows/
│   └── MrXin_LTX_2.3_I2V_EROS_V2.json
├── runpod/
│   ├── README.md
│   └── template-settings.json
└── .github/workflows/
    ├── build-image.yml
    └── validate.yml
```

## Model download sources

Every model enabled by the default `MODEL_PROFILE=workflow` has a pinned download
URL and SHA-256 where available. RunPod only needs `HF_TOKEN` and `CIVITAI_TOKEN`;
the downloader applies them only at runtime and redacts credentials from error logs.

The disabled LoRAs included only by `MODEL_PROFILE=all` still require:

```text
MODEL_URL_LTX23_NSFW_FURRY
MODEL_URL_CUM_SHOT
MODEL_URL_TITFUCK
MODEL_URL_ORGASM
```

With `MODEL_PROFILE=all`, startup fails clearly when one of those optional URLs is
absent. To inspect ComfyUI without concept LoRAs, use `MODEL_PROFILE=public`.

## GitHub → GHCR

Create a repository named `ltx23-i2v-runpod`, copy these files, and push to `main`.
The included workflow publishes:

```text
ghcr.io/<github-owner>/ltx23-i2v-runpod:latest
ghcr.io/<github-owner>/ltx23-i2v-runpod:sha-<commit>
```

For a versioned release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

Use the immutable version tag in production rather than `latest`.

## RunPod template

Use the values in [`runpod/template-settings.json`](runpod/template-settings.json).

Recommended baseline:

| Setting | Value |
|---|---|
| Image | `ghcr.io/<owner>/ltx23-i2v-runpod:v1.0.0` |
| Container disk | 35 GB |
| Network volume | 250 GB |
| Volume mount | `/workspace` |
| HTTP port | `8188` |
| Start command | empty |

Create RunPod secrets and reference them in template environment variables:

```text
HF_TOKEN={{ RUNPOD_SECRET_HF_TOKEN }}
CIVITAI_TOKEN={{ RUNPOD_SECRET_CIVITAI_TOKEN }}
```

Create the RunPod secrets with those exact names, then use the key icon in the
template environment-variable editor to select each secret.

Do not put tokens into `.env`, Docker build arguments, GitHub files or the image.

## Storage behavior

Persistent:

```text
/workspace/models
/workspace/input
/workspace/output
/workspace/user
/workspace/cache
/workspace/logs
```

Ephemeral:

```text
/tmp/comfy
```

The workflow is copied once to:

```text
/workspace/user/default/workflows/MrXin_LTX_2.3_I2V_EROS_V2.json
```

User edits are never overwritten on restart.

## Model download profiles

| Profile | Contents |
|---|---|
| `public` | Checkpoint, Gemma encoder, spatial upscaler, preview VAE and distilled LoRA |
| `workflow` | `public` plus every LoRA currently enabled in the workflow |
| `all` | Every referenced model plus the RIFE interpolation model |

Transfers are concurrent, validate safetensors headers, and resume from `.aria2` state. Existing complete files
are skipped. Tune with:

```text
DOWNLOAD_CONCURRENCY=5
DOWNLOAD_CONNECTIONS=16
DOWNLOAD_MAX_TRIES=10
```

Higher values do not always improve throughput and may trigger host rate limits.

## GPU guidance

The supplied graph loads a large LTX 2.3 checkpoint, a 12B text encoder, audio/video
VAEs, multiple LoRAs, a two-pass latent upscale and tiled final decode. A 48 GB GPU
is the practical default.

On a 24 GB GPU, first test with a shorter duration and a smaller longer-side value.
`COMFY_ARGS=--lowvram` can be added if needed, but it is not enabled globally
because it trades speed for memory and is unnecessary on larger GPUs.

The optional NVIDIA RTX Video Super Resolution editor node requires an NVIDIA RTX
GPU. The video-editor group is disabled in the supplied workflow, so it does not
affect the primary I2V run.

## Local validation

No network access is required for the static checks:

```bash
make validate
```

Build locally:

```bash
cp .env.example .env
docker compose build
docker compose up
```

Open `http://localhost:8188`.

The first start downloads the selected model profile. To build and inspect the UI
without downloading models:

```bash
SKIP_MODEL_DOWNLOAD=1 docker compose up
```

## Operational commands

Inside the Pod:

```bash
python /opt/bootstrap/scripts/doctor.py \
  --manifest-root /opt/bootstrap/manifest \
  --data-root /workspace \
  --comfy-root /opt/ComfyUI \
  --profile workflow

python /opt/bootstrap/scripts/doctor.py \
  --server-url http://127.0.0.1:8188
```

Re-download a missing file by deleting only that file and restarting. Partial
downloads resume automatically.

## Security and licensing

The container runs only ComfyUI; it does not start Jupyter or an SSH daemon.
RunPod's web terminal remains available for recovery.

The repository's infrastructure code is MIT-licensed. The workflow, ComfyUI,
custom nodes and model files retain their respective upstream licenses and usage
terms. Model tokens and private download URLs are not distributable repository
content.
