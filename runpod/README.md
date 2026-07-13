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

Create RunPod secrets for the token and private model URL values, then reference them with
`{{ RUNPOD_SECRET_secret_name }}`. Do not paste tokens into the repository or Docker image.

The image intentionally runs ComfyUI only. Jupyter and SSH daemons are not started, which reduces
startup work and attack surface. RunPod's web terminal remains the normal recovery path.

## Profiles

- `public`: downloads the five URLs embedded in the workflow plus no private LoRAs.
- `workflow`: downloads every model currently enabled in the workflow. This is the default.
- `all`: downloads all referenced LoRAs and the RIFE interpolation model.

A missing required private URL stops startup instead of launching a silently broken workflow.
