#!/usr/bin/env python3
"""Exercise the real container entrypoint and node schemas without a GPU/model download."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def main():
    bootstrap = Path(os.environ.get("BOOTSTRAP_ROOT", "/opt/bootstrap"))
    with tempfile.TemporaryDirectory(prefix="ltx-smoke-") as directory:
        env = {**os.environ, "DATA_ROOT": directory, "SKIP_MODEL_DOWNLOAD": "1",
               "COMFY_PORT": "8188", "COMFY_ARGS": "--cpu --disable-api-nodes --disable-assets"}
        log_path = Path(directory) / "entrypoint.log"
        with log_path.open("w+") as log:
            process = subprocess.Popen(["bash", str(bootstrap / "scripts/start.sh")], env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 240
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError(f"entrypoint exited with {process.returncode}")
                    try:
                        with urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=3) as response:
                            json.load(response)
                        break
                    except (OSError, urllib.error.URLError):
                        time.sleep(2)
                else:
                    raise RuntimeError("entrypoint did not become ready within 240s")
                subprocess.run([sys.executable, str(bootstrap / "scripts/doctor.py"),
                                "--skip-models", "--server-url", "http://127.0.0.1:8188"],
                               env=env, check=True)
                for source in (bootstrap / "workflows").glob("*.json"):
                    installed = Path(directory) / "user/default/workflows" / source.name
                    assert installed.read_bytes() == source.read_bytes(), source.name
                print("PASS: real entrypoint, HTTP API, both workflow node schemas, exact workflow installation")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                log.seek(0)
                print(log.read())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
