#!/usr/bin/env python3
"""Exercise the real entrypoint and tiny RIFE/SPAN inference without LTX weights/GPU."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def request_json(path, data=None):
    request = urllib.request.Request("http://127.0.0.1:8188" + path,
                                     data=json.dumps(data).encode() if data is not None else None,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{path}: {exc.read().decode()}") from exc


def download_postprocess_models(bootstrap, data_root, env):
    manifest = json.loads((bootstrap / "manifest/models.json").read_bytes())
    manifest["models"] = [m for m in manifest["models"] if m["id"] in ("rife-v426-core", "nomosuni-span-2x")]
    assert len(manifest["models"]) == 2
    path = data_root / "postprocess-models.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    subprocess.run([sys.executable, str(bootstrap / "scripts/download_models.py"),
                    "--manifest", str(path), "--data-root", str(data_root), "--profile", "dasiwa"],
                   env=env, check=True, timeout=300)


def check_postprocess(bootstrap, data_root):
    workflow = json.loads((bootstrap / "workflows/DaSiWa RIFE SPAN.json").read_bytes())
    selected = {3910, 3911, 3904, 3377, 3383, 3710}
    graph = {n["id"]: n for n in workflow["nodes"]}
    links = {e[0]: e for e in workflow["links"]}
    prompt = {"1": {"class_type": "EmptyImage", "inputs": {"width": 128, "height": 128,
                                                          "batch_size": 2, "color": 0x336699}}}
    for ident in selected:
        node = graph[ident]
        values = node.get("widgets_values_named", node.get("widgets_values", {})).copy()
        for name in ("video_preview", "free_memory_if_needed"):
            values.pop(name, None)
        for port in node["inputs"]:
            if port.get("link") is None:
                continue
            link = links[port["link"]]
            if link[1] in selected:
                values[port["name"]] = [str(link[1]), link[2]]
        prompt[str(ident)] = {"class_type": node["type"], "inputs": values}
    prompt["3911"]["inputs"]["images"] = ["1", 0]
    prompt["3904"]["inputs"]["values.a"] = 24
    prompt["3710"]["inputs"].update(filename_prefix="smoke/rife_span", save_metadata=False,
                                    codec="H.264", bit_depth="8-bit")
    job = request_json("/prompt", {"prompt": prompt})
    assert not job.get("node_errors"), job
    prompt_id = job["prompt_id"]
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        history = request_json("/history/" + prompt_id).get(prompt_id)
        if history:
            assert history["status"]["status_str"] == "success", history
            break
        time.sleep(1)
    else:
        raise RuntimeError("RIFE/SPAN CPU smoke timed out")
    videos = list((data_root / "output/smoke").glob("*.mp4"))
    assert len(videos) == 1, videos
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=width,height,nb_frames,r_frame_rate", "-of", "json", str(videos[0])]))["streams"][0]
    assert (probe["width"], probe["height"], probe["nb_frames"], probe["r_frame_rate"]) == (256, 256, "3", "48/1"), probe
    print("PASS: verified real RIFE/SPAN weights; 2x128x128@24 -> RIFE -> SPAN -> MP4 3x256x256@48 (CPU synthetic frames)")


def main():
    bootstrap = Path(os.environ.get("BOOTSTRAP_ROOT", "/opt/bootstrap"))
    subprocess.run([sys.executable, str(bootstrap / "scripts/check_runtime.py"), "--cpu-smoke"], check=True)
    with tempfile.TemporaryDirectory(prefix="ltx-smoke-") as directory:
        env = {**os.environ, "DATA_ROOT": directory, "SKIP_MODEL_DOWNLOAD": "1",
               "COMFY_PORT": "8188", "COMFY_ARGS": "--cpu --offline --disable-assets"}
        download_postprocess_models(bootstrap, Path(directory), env)
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
                                "--skip-models", "--cpu-smoke", "--server-url", "http://127.0.0.1:8188"],
                               env=env, check=True)
                for source in (bootstrap / "workflows").glob("*.json"):
                    installed = Path(directory) / "user/default/workflows" / source.name
                    assert installed.read_bytes() == source.read_bytes(), source.name
                check_postprocess(bootstrap, Path(directory))
                print("PASS: real entrypoint, HTTP API, CPU-loadable workflow node schemas, exact workflow installation; GPU-only RTX checked for bundled SDK dependencies")
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
