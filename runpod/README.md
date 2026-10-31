# RunPod template settings

Use `template-settings.json` when creating the Pod template.

| Field | Value |
|---|---|
| Container image | `ghcr.io/grawthings-beep/ltx23-i2v-runpod:latest` |
| Container disk | 35 GB |
| Local Volume Disk | 120 GB recommended for DaSiWa |
| Network Volume | Not required; optional |
| Mount path | `/workspace` |
| HTTP port label | `ComfyUI` |
| HTTP port | `8188` |
| Start command | Leave empty |

Accept the model access terms at https://huggingface.co/darksidewalker/DaSiWa-LTX2.3.
Create a RunPod secret named exactly `HF_TOKEN` containing a Hugging Face read
token authorized for that gated repository and the private `uwgm/nikke-loras`
repository containing the two optional user LoRAs. Add the `HF_TOKEN` environment
variable and select that secret using the key icon. The raw representation is:

```text
HF_TOKEN={{ RUNPOD_SECRET_HF_TOKEN }}
```

No quotes are needed. `CIVITAI_TOKEN` and `MODEL_URL_*` variables are not required
by these manifests.

Add the ordinary environment variables from `template-settings.json`. Keep
`MODEL_PROFILE=dasiwa`, `SKIP_MODEL_DOWNLOAD=0`, and `COMFY_PORT=8188` for the
normal deployment. Do not override the container start command.

The first start downloads about 48.32 GB plus `FOOT.safetensors` and
`LTX2.3_reasoning_I2V_V3.safetensors` before ComfyUI listens on
port 8188. A temporary RunPod proxy 404 is expected during this phase. Watch the
Pod logs; later starts reuse complete files and resume `.aria2` partial files from
the same `/workspace` volume.

The image installs `DasiwaLTX23WorkflowsI2VFLF2V_omniforgeCLTX23V51.json` and
retains `MrXin LTX 2.3 I2V EROS V6.1.json`. It copies each file
once and never overwrites user edits. An older workflow left on an existing volume is
not automatically deleted; remove it manually if it should no longer appear.

A local Volume Disk does not restrict GPU region selection. Its contents are
lost when the Pod is terminated. To use both workflows select `MODEL_PROFILE=all`
and allocate at least 200 GB for models and output. Existing LoRAs are never deleted.

The same CUDA 13.0 image targets both 4090 and 5090; choose a host whose driver
supports CUDA 13.0 or newer. CUDA 12.x disables ComfyUI 0.43's optimized INT8
CUDA kernels. Startup checks the GPU and VFX SDK before downloading models.
Leave `COMFY_ARGS` empty initially. The original 900p preset is
unchanged; CPU build tests do not measure VRAM usage or generation speed.
