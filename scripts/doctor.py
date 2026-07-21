#!/usr/bin/env python3
"""Runtime preflight checks for RunPod/ComfyUI."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-root", type=Path, default=Path("/opt/bootstrap/manifest"))
    parser.add_argument("--data-root", type=Path, default=Path(os.environ.get("DATA_ROOT", "/workspace")))
    parser.add_argument("--comfy-root", type=Path, default=Path(os.environ.get("COMFYUI_ROOT", "/opt/ComfyUI")))
    parser.add_argument("--profile", default=os.environ.get("MODEL_PROFILE", "workflow"))
    parser.add_argument("--workflow", type=Path)
    parser.add_argument("--server-url")
    parser.add_argument("--skip-models", action="store_true")
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []

    nodes = json.loads((args.manifest_root / "nodes.json").read_text(encoding="utf-8"))
    models = json.loads((args.manifest_root / "models.json").read_text(encoding="utf-8"))

    workflow_path = args.workflow or (
        args.data_root / "user/default/workflows/MrXin LTX 2.3 I2V EROS V6.1.json"
    )
    if not workflow_path.is_file():
        errors.append(f"missing workflow: {workflow_path}")
    else:
        try:
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            if not isinstance(workflow, dict) or not isinstance(workflow.get("nodes"), list):
                errors.append(f"workflow has no nodes array: {workflow_path}")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"invalid workflow JSON: {workflow_path}: {exc}")

    for node in nodes["nodes"]:
        path = args.comfy_root / "custom_nodes" / node["directory"]
        if not path.is_dir():
            errors.append(f"missing custom node directory: {path}")

    allow_missing = os.environ.get("ALLOW_MISSING_MODEL_URLS", "0") == "1"
    if not args.skip_models:
        for model in models["models"]:
            if args.profile not in model.get("profiles", []):
                continue
            path = args.data_root / model["relative_path"]
            if not path.is_file() or path.stat().st_size == 0:
                message = f"missing model: {path}"
                (warnings if allow_missing and model.get("url_env") else errors).append(message)
                continue
            if Path(str(path) + ".aria2").exists():
                errors.append(f"incomplete model download: {path}")
                continue
            expected_size = model.get("exact_bytes")
            if expected_size is not None and path.stat().st_size != int(expected_size):
                errors.append(
                    f"wrong model size: {path} "
                    f"({path.stat().st_size} bytes; expected {int(expected_size)})"
                )

    usage = shutil.disk_usage(args.data_root)
    print(f"Disk free: {usage.free / 1024**3:.1f} GiB / {usage.total / 1024**3:.1f} GiB")

    if shutil.which("nvidia-smi"):
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            print("GPU: " + result.stdout.strip().replace("\n", "; "))
        else:
            warnings.append("nvidia-smi returned a non-zero exit code")
    else:
        warnings.append("nvidia-smi not found")

    if args.server_url:
        try:
            with urllib.request.urlopen(args.server_url.rstrip("/") + "/object_info", timeout=20) as response:
                object_info = json.load(response)
            required_types = {name for node in nodes["nodes"] for name in node.get("provides", [])}
            missing_types = sorted(required_types - set(object_info))
            if missing_types:
                errors.append("server missing node types: " + ", ".join(missing_types))
        except Exception as exc:
            errors.append(f"could not query ComfyUI object_info: {exc}")

    for warning in warnings:
        print(f"WARN: {warning}", file=sys.stderr)
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)

    if errors:
        return 1
    print("Doctor: all required checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
