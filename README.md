# DaSiWa LTX 2.3 OmniForge C V5.1 on RunPod

RunPod image for the unmodified user-supplied
`DasiwaLTX23WorkflowsI2VFLF2V_omniforgeCLTX23V51.json` workflow.
The existing `MrXin LTX 2.3 I2V EROS V6.1.json` is retained unchanged.
`DaSiWa Last Frame.json` adds a dedicated final-frame preview to the original DaSiWa graph.
`DaSiWa RIFE SPAN.json` is a separate comparison workflow with pixel-domain upscaling.
`DaSiWa RIFE SPAN Refine.json` adds low-resolution video/audio refinement for comparison.

The image:

1. builds ComfyUI `v0.43.0` at a fixed commit on PyTorch 2.10.0 / CUDA 13.0;
2. installs 18 custom-node repositories at full commit SHAs;
3. downloads the selected model profile into `/workspace` storage;
4. installs all five workflows once without overwriting later user edits;
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

## DaSiWa Last Frame

Open **DaSiWa Last Frame** for the original OmniForge generation settings with a
separate **Last Frame** preview node to the right of Video Output. No SPAN processing
is added. Models, LoRAs, prompts, seed, resolution, audio, sampling, latent upscaling,
post-processing switches and the video encoder are unchanged from the author file.

```text
Final IMAGE frames -> existing video encoder
                   -> Get Image from Batch (-1, length 1) -> Last Frame (Preview Image)
```

Run the workflow and right-click the still image in **Last Frame** to save it to
your computer. There is no need to browse the Pod output directory or enable
`Save last frame` in the video encoder. The standard preview node uses a temporary
PNG, so download it before discarding the Pod. This branch runs with generation;
it does not extract an image from a previously saved MP4. Re-queuing may regenerate
the video if the seed changes or upstream caches are no longer available.

Only one frame is cloned for preview; `pass_frames` stays off and no extra model or
custom node is installed. The original and the older RIFE/SPAN comparisons remain
unchanged. This separate filename is installed even on a volume containing the old
workflows, without overwriting user edits. An existing compatible Pod can import
the JSON directly; no image or environment-variable change is required for that.

`scripts/prepare_last_frame.py` reproduces this derivative. Tests verify that only
the two preview nodes, their wiring/layout and graph identities differ from the
original. Container CI executes the branch with one- and three-frame synthetic
batches, checks the exact final-frame pixels and checks the UI image response and
download URL. It does not inspect the user's generated video.

## DaSiWa RIFE SPAN

Open **DaSiWa RIFE SPAN** to compare against the untouched OmniForge workflow:

```text
LTX Director -> first pass (8 steps, CFG 1, scale 0.5)
-> remove image-guide latent frames -> VAE Decode
-> RIFE 4.26 (2x frames) -> 2x NomosUni SPAN (2x width/height) -> MP4
```

There is no latent upscaler, second/third diffusion pass, RTX processing,
watermark or mosaic in this derivative. Models, LoRA slots, prompts, seed,
Director timeline and the original 900p resolution budget are retained.
The preview uses TAE without loading a latent upscaler. Both full and tiled VAE
decode receive the guide-cropped first-pass latent, not appended guide frames.
The original workflow's first pass runs at half the Director's resolved dimensions;
SPAN doubles those completed frames. The resolution preset is therefore still
the target-size budget, not the first-pass size. Aspect-ratio fitting and Div32
rounding can change the exact dimensions. For example, 512x704 completed frames
become 1024x1408; selecting 512x704 as the Director's target is not the same thing.

RIFE runs **before** SPAN at the smaller resolution. Its multiplier is 2 and the
save FPS is wired to `Director FPS * 2` (24 -> 48), so interpolation does not create
slow motion. Audio comes from the first pass without time stretching. Native RIFE
preserves endpoints: N frames become `(N - 1) * 2 + 1`, e.g. 121 -> 241. The endpoint
time is unchanged; file duration differs by half one original frame interval.
Generated files use the `rife_span/` prefix. Use the same input, fixed seed, prompts,
duration and final resolution for A/B tests. This is not a proven quality upgrade:
latent refinement can synthesize details, while SPAN can sharpen or change texture,
and frame-wise upscaling can introduce shimmer. GPU speed/quality need a real A/B run.

The extra model is [2x NomosUni SPAN multijpg](https://huggingface.co/Phips/2xNomosUni_span_multijpg)
by Philip Hofmann / Helaman ([CC-BY-4.0 model card](https://openmodeldb.info/models/2x-NomosUni-span-multijpg)).
It adds 4,461,056 bytes to the existing parallel downloader with a pinned revision,
exact size and SHA-256. It uses ComfyUI's existing model-managed, tiled upscale node;
no additional custom-node pack or environment variable is needed. The native IMAGE
batch still occupies RAM and some GPU memory; this is not a streaming-video pipeline.

### RIFE SPAN Refine comparison

Open **DaSiWa RIFE SPAN Refine** to restore the original second/third video-and-audio
sampling passes without restoring latent spatial upscaling:

```text
LTX Director -> first pass (8 steps, scale 0.5)
-> remove guides -> second pass (4 steps, denoise 0.4, same resolution)
-> remove guides -> third pass (2 steps, denoise 0.2, same resolution)
-> remove guides -> final-pass video/audio decode
-> RIFE 2x -> NomosUni SPAN 2x -> MP4 with final-pass audio
```

All passes retain CFG 1 and the original linear-quadratic scheduler settings.
Each refinement pass receives the preceding pass's cropped video latent and audio
latent together. Director guide metadata is removed after every pass, before
re-guiding or decoding. Second/third guide scale is 1.0: there is no latent
upscaler or high-resolution diffusion. RIFE, SPAN, doubled save FPS and model/LoRA
selectors are the same as the fast version. Files use `rife_span_refine/`.

This experiment addresses the loss of later audio refinement, but that loss has
not been established as the cause of reported audio distortion. It is not a
guaranteed audio fix. It adds six low-resolution sampling steps relative to the
fast version; GPU runtime and output quality must be compared on the Pod. Use
the same fixed seed, image, prompts, LoRAs, duration and resolution in both files.
The fast version and both original workflows remain byte-for-byte unchanged.
There are no additional model downloads, node packs or environment variables.

`scripts/prepare_rife_span.py` reproducibly generates only the two derivatives. Tests
check both ends of every link, subgraph interfaces, guide removal, pass count,
RIFE/SPAN order, FPS/audio wiring, model coverage and non-overlapping layouts.
Container CI additionally executes RIFE and SPAN with their real verified weights
on a tiny synthetic batch and checks the encoded MP4 dimensions/frame count/FPS.
The Refine post-processing test includes a synthetic stereo tone and verifies AAC
duration, pitch, channel order, level, distortion and absence of clipping. This
tests encoding, not the quality of LTX-generated sound or GPU refinement.

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

The token also needs read access to `uwgm/nikke-loras` and
`uwgm/nikke-civitai-backup` for the four user-requested LoRAs. If using a fine-grained
token, include both repositories. No additional environment variable is needed.

Do not add quotes around the reference. Models use
Hugging Face and GitHub sources, so `CIVITAI_TOKEN` and private `MODEL_URL_*`
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

CUDA 13.0 supports both RTX 4090 and 5090 with a CUDA 13-compatible host driver;
the same image is used. ComfyUI 0.43 disables optimized comfy-kitchen CUDA kernels
on CUDA 12.x, so this INT8 ConvRot workflow intentionally uses CUDA 13.0.
Before downloading models, startup checks real GPU computation and the NVIDIA
VFX SDK import. The original 900p preset's GPU memory fit and generation speed
are not validated by CPU CI. Leave `COMFY_ARGS` empty initially and use
`--lowvram` only if needed. A 48 GB GPU gives more headroom.

## First start

The default `dasiwa` profile downloads 15 files: about 48.32 GB of workflow models
plus the four user LoRAs. Their sizes are reported at startup.
Gated/private-repository access is checked before starting large downloads.
ComfyUI starts only after downloads and doctor checks pass,
so the RunPod HTTP proxy can return 404 during the initial download. Follow the
Pod logs for live aria2 progress.

Completed files are validated by exact byte count, safetensors header, and
SHA-256, then skipped on later starts. `.aria2` partial files are resumed.

The following user LoRAs are installed in `/workspace/models/loras/LTX2/User/`:

- `FOOT.safetensors` and `LTX2.3_reasoning_I2V_V3.safetensors` from `uwgm/nikke-loras`.
- `LTX2.3_CREAMPIE.safetensors` and `TentacleMotion.safetensors` from `uwgm/nikke-civitai-backup`.

They appear in the LoRA selector but are not automatically enabled. Existing LoRAs
and all workflow JSON files remain unchanged.
On first use, startup obtains their exact size, SHA-256 and commit from the
authenticated Hugging Face metadata API, then downloads the commit-pinned URLs
with the existing parallel downloader and verifies all files. Metadata is
cached in `/workspace/cache/model-metadata/` without credentials and reused on
restart, including after an interrupted download. Upstream `main` changes do
not silently replace the cached version. Missing access or integrity metadata
stops startup; it never falls back to an unverified download.

The DaSiWa workflows are copied once to:

```text
/workspace/user/default/workflows/DasiwaLTX23WorkflowsI2VFLF2V_omniforgeCLTX23V51.json
/workspace/user/default/workflows/DaSiWa Last Frame.json
/workspace/user/default/workflows/DaSiWa RIFE SPAN.json
/workspace/user/default/workflows/DaSiWa RIFE SPAN Refine.json
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
| `dasiwa` | 15 | 48.32 GB + user LoRAs | DaSiWa V5.1, Last Frame, both RIFE SPAN derivatives and four user LoRAs |
| `public` | 9 | 55.79 GB | V6.1 models enabled by the graph |
| `workflow` | 16 | 60.39 GB + user LoRAs | `public` plus the three optional concept LoRAs and four user LoRAs |
| `all` | 25 | 116.45 GB + user LoRAs | all workflows, including bypassed alternate loaders and LoRAs |

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
for every CPU-loadable backend type in all workflows before publishing. The
legacy GPU-only `RTXVideoSuperResolution` requires host `libcuda.so.1`, so CPU CI
audits its bundled SDK libraries and their dependencies instead of pretending to
execute it. Easy-Use Get/Set and DaSiWa Label are frontend nodes, not missing
Python classes. This does not run
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
