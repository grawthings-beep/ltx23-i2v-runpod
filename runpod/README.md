# RunPod template settings

Use `template-settings.json` as the source of truth when creating a custom Pod template.

## Required settings

| Field | Value |
|---|---|
| Container image | `ghcr.io/grawthings-beep/ltx23-i2v-runpod:latest` |
| Container disk | 35 GB |
| Network volume | 250 GB recommended |
| Volume mount path | `/workspace` |
| HTTP port | `8188` |
| Container start command | Leave empty; the image has its own `CMD` |

Create RunPod secrets named exactly `HF_TOKEN` and `CIVITAI_TOKEN`. In the template
environment-variable editor, use the key icon to map them as follows:

```text
HF_TOKEN={{ RUNPOD_SECRET_HF_TOKEN }}
CIVITAI_TOKEN={{ RUNPOD_SECRET_CIVITAI_TOKEN }}
```

The default workflow profile needs no model URL variables.
Do not paste tokens into the repository or Docker image.

The image intentionally runs ComfyUI only. Jupyter and SSH daemons are not started, which reduces
startup work and attack surface. RunPod's web terminal remains the normal recovery path.

## Profiles

- `public`: downloads the core checkpoint, encoder, upscaler, preview VAE and distilled LoRA.
- `workflow`: adds every concept LoRA currently enabled in the workflow from pinned URLs. This is the default.
- `all`: downloads all referenced LoRAs and RIFE; disabled optional LoRAs still need their URL variables.

A missing optional URL under `MODEL_PROFILE=all` stops startup instead of launching a silently broken workflow.
