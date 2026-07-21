# RunPod template settings

Use `template-settings.json` when creating the Pod template.

| Field | Value |
|---|---|
| Container image | `ghcr.io/grawthings-beep/ltx23-i2v-runpod:latest` |
| Container disk | 35 GB |
| Network volume | 250 GB recommended |
| Persistent storage | Network volume |
| Mount path | `/workspace` |
| HTTP port label | `ComfyUI` |
| HTTP port | `8188` |
| Start command | Leave empty |

Create a RunPod secret named exactly `HF_TOKEN`. Add the `HF_TOKEN` environment
variable and select that secret using the key icon. The raw representation is:

```text
HF_TOKEN={{ RUNPOD_SECRET_HF_TOKEN }}
```

No quotes are needed. `CIVITAI_TOKEN` and `MODEL_URL_*` variables are not required
by the V6.1 manifest.

Add the ordinary environment variables from `template-settings.json`. Keep
`MODEL_PROFILE=workflow`, `SKIP_MODEL_DOWNLOAD=0`, and `COMFY_PORT=8188` for the
normal deployment. Do not override the container start command.

The first start downloads about 60.39 GB (56.24 GiB) before ComfyUI listens on
port 8188. A temporary RunPod proxy 404 is expected during this phase. Watch the
Pod logs; later starts reuse complete files and resume `.aria2` partial files from
the same `/workspace` volume.

The image installs only `MrXin LTX 2.3 I2V EROS V6.1.json`. It copies the file
once and never overwrites user edits. A V2 workflow left on an existing volume is
not automatically deleted; remove it manually if it should no longer appear.

An NVIDIA A40 48 GB is a comfortable choice. Leave `COMFY_ARGS` empty initially.
