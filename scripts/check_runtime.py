#!/usr/bin/env python3
"""Separate GPU runtime checks from CPU CI's SDK dependency audit."""

import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpu-smoke", action="store_true")
    args = parser.parse_args()
    import torch

    if torch.version.cuda != "13.0":
        raise RuntimeError("This image requires the pinned CUDA 13.0 PyTorch runtime")
    if args.cpu_smoke:
        if torch.cuda.is_available():
            raise RuntimeError("CPU smoke exemptions cannot be used on a GPU runner")
        spec = importlib.util.find_spec("nvvfx")
        if spec is None or not spec.origin:
            raise RuntimeError("nvidia-vfx is not installed")
        package = Path(spec.origin).parent
        libs = package / "libs"
        env = {**os.environ, "LD_LIBRARY_PATH": f"{libs}:{package.parent / 'nvidia_vfx.libs'}:{os.environ.get('LD_LIBRARY_PATH', '')}"}
        paths = [package / "_ext.abi3.so", *[libs / name for name in (
            "libVideoFX.so", "libVideoFXLocal.so", "libNVCVImage.so",
            "libnvVFXVideoSuperRes.so", "libnvVFXVideoFrameGeneration.so")]]
        for path in paths:
            if not path.is_file():
                raise RuntimeError(f"missing bundled NVIDIA SDK library: {path}")
            result = subprocess.run(["ldd", str(path)], env=env, capture_output=True, text=True, check=True)
            missing = set(re.findall(r"(\S+) => not found", result.stdout))
            # libcuda is supplied by the host NVIDIA driver, never by an image.
            unexpected = missing - {"libcuda.so.1"}
            if unexpected:
                raise RuntimeError(f"{path.name}: missing SDK dependencies: {sorted(unexpected)}")
        print("PASS: NVIDIA SDK libraries present; only host libcuda may be absent in CPU CI")
    else:
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable. Select a GPU host with a CUDA 13-compatible NVIDIA driver.")
        value = torch.ones(1, device="cuda") + 1
        torch.cuda.synchronize()
        if value.item() != 2:
            raise RuntimeError("CUDA computation check failed")
        import nvvfx
        print(f"GPU runtime ready: {torch.cuda.get_device_name()}, CUDA {torch.version.cuda}, nvidia-vfx {nvvfx.__version__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
