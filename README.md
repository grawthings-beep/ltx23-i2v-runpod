# DaSiWa LTX 2.3 OmniForge C V5.1 on RunPod

RunPod image for the unmodified user-supplied
`DasiwaLTX23WorkflowsI2VFLF2V_omniforgeCLTX23V51.json` workflow.
The existing `MrXin LTX 2.3 I2V EROS V6.1.json` is retained unchanged.

The image:

1. builds ComfyUI `v0.43.0` at a fixed commit on PyTorch 2.10.0 / CUDA 12.8;
2. installs 18 custom-node repositories at full commit SHAs;
3. downloads the selected model profile into `/workspace` storage;
4. installs both original workflows once without overwriting later user edits;
5. runs doctor checks, then starts ComfyUI on `0.0.0.0:8188`.

Models are not baked into the Docker image. Downloads use parallel, resumable
`aria2c` transfers. A local Pod Volume Disk is supported; a Network Volume is
not required. Local files survive stop/start but not termination of the Pod.

## Workflow provenance

- DaSiWa file: `workflows/DasiwaLTX23WorkflowsI2VFLF2V_omniforgeCLTX23V51.json`
- SHA-256: `d826b97f4076025b3b6b6c5f8ac2e2f61f64f5ae5dcd359a2a12a9c5f1356841`
- 116 nodes including four subgraphs; no model, seed, prompt, sampler, timing,
  resolution, wiring or layout changes. The original 900p preset is retained.
- The author file contains one empty editor link placeholder. It is preserved;
  all real serialized links are checked in both directions.

- File: `workflows/MrXin LTX 2.3 I2V EROS V6.1.json`
- Source: [MrXin V6.1 archive](https://huggingface.co/ThirdTimesTheCiarc/workflows/resolve/main/2488266/2962842/mrxinLTX23I2VEros12GBVRAM_i2vV61.zip)
- Source archive SHA-256: `46ab86520ffb28dd3e131f48727402146d372d3585896cc52efe3ed777c3962f`
- Workflow JSON SHA-256: `a29ff5b4cecfe2cc399b6590fae299038996169e742e7a4c4a8ae40376aa50cd`

Both workflow contents and filenames are hash-locked in `manifest/workflows.json`.
DaSiWa uses DragonLeap V4 INT8 ConvRot, LTX Director and DaSiWa nodes, not the
MrXin 10Eros model. Model files are installed at the original selector paths;
shared Gemma/VAE files use zero-copy aliases, not duplicate downloads.

The DaSiWa source bypasses DMD LoRA, RIFE, AnimeSharp, RTX and watermark post-processing.
Their selected model files are included, but those switches remain unchanged.
`placeholder.gguf` is an intentionally bypassed author placeholder, not a model:
select real GGUF files before switching to that branch. Optional watermark images
are user inputs, not downloaded assets. Upload your own image in LTX Director.

## RunPod template

Use `runpod/template-settings.json` as the source of truth.

| Setting | Value |
|---|---|
| Container image | `ghcr.io/grawthings-beep/ltx23-i2v-runpod:latest` |
| Container disk | 35 GB |
| Local Volume Disk | 120 GB recommended; more for both model profiles |
| Network Volume | optional, not required |
| Volume mount | `/workspace` |
| HTTP port | `8188` |
| Start command | leave empty |

First accept access terms at [DaSiWa-LTX2.3](https://huggingface.co/darksidewalker/DaSiWa-LTX2.3).
Create a Hugging Face read token with access to that gated repository, then a
RunPod secret named exactly `HF_TOKEN`. In the template environment
variable editor, add a variable named `HF_TOKEN`, select the secret with the key
icon, and let RunPod render its reference. In raw form it is:

```text
HF_TOKEN={{ RUNPOD_SECRET_HF_TOKEN }}
```

Do not add quotes around the reference. The manifests use pinned
Hugging Face and GitHub mirrors, so `CIVITAI_TOKEN` and private `MODEL_URL_*`
variables are not required. The downloader still supports `CIVITAI_TOKEN` for
future manifest entries.

Use these environment variables:

```text
MODEL_PROFILE=dasiwa
DOWNLOAD_CONCURRENCY=5
DOWNLOAD_CONNECTIONS=16
DOWNLOAD_MAX_TRIES=10
NODE_CLONE_CONCURRENCY=6
ALLOW_MISSING_MODEL_URLS=0
SKIP_MODEL_DOWNLOAD=0
COMFY_PORT=8188
COMFY_ARGS=
```

CUDA 12.8 supports both RTX 4090 and 5090 with a compatible host driver; the same
image is used. The original 900p preset's GPU memory fit and generation speed
are not validated by CPU CI. Leave `COMFY_ARGS` empty initially and use
`--lowvram` only if needed. A 48 GB GPU gives more headroom.

## First start

The default `dasiwa` profile downloads 10 files totaling about 48.32 GB.
Gated-repository access is checked before starting large downloads.
ComfyUI starts only after downloads and doctor checks pass,
so the RunPod HTTP proxy can return 404 during the initial download. Follow the
Pod logs for live aria2 progress.

Completed files are validated by exact byte count, safetensors header, and
SHA-256, then skipped on later starts. `.aria2` partial files are resumed.

The new workflow is copied once to:

```text
/workspace/user/default/workflows/DasiwaLTX23WorkflowsI2VFLF2V_omniforgeCLTX23V51.json
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
| `dasiwa` | 10 | 48.32 GB | all real DaSiWa V5.1 model references |
| `public` | 9 | 55.79 GB | V6.1 models enabled by the graph |
| `workflow` | 12 | 60.39 GB | `public` plus the three optional concept LoRAs |
| `all` | 20 | 116.45 GB | both workflows, including bypassed alternate loaders and LoRAs |

The concept LoRAs referenced by V6.1 are included in `workflow`, even though their
slots are initially off, so enabling them does not require another URL. `all`
also downloads the bypassed alternate transformer and upscaler loaders.
Existing local LoRAs are not removed. Use `MODEL_PROFILE=workflow` to download
MrXin's original profile, or `all` to make both workflows' models available.

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

Pushes and pull requests run workflow/hash/link/model-path tests. Image builds
launch the real entrypoint in a disposable CPU container and check `/object_info`
for every backend type in both workflows before publishing. This does not run
video inference or verify GPU kernels, quality, optional RTX effects or timing.
Pushes to `main` and `v*` tags publish with Docker metadata/build-push actions. The default-branch
image is:

```text
ghcr.io/grawthings-beep/ltx23-i2v-runpod:latest
```

## Security and licensing

Tokens are runtime RunPod secrets. They must not be committed, passed as Docker
build arguments, or embedded in model URLs. The infrastructure code is MIT
licensed; the workflow, ComfyUI, custom nodes, and models retain their respective
upstream licenses and usage terms.
