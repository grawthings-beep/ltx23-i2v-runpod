#!/usr/bin/env python3
"""Exercise the real entrypoint and tiny RIFE/SPAN inference without LTX weights/GPU."""

import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import wave


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


def write_test_audio(path):
    # Different stereo tones expose channel swaps, pitch changes and clipping.
    samples = bytearray()
    for i in range(48000):
        samples.extend(struct.pack("<hh", round(32767 * 0.25 * math.sin(2 * math.pi * 440 * i / 48000)),
                                   round(32767 * 0.125 * math.sin(2 * math.pi * 880 * i / 48000))))
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(48000)
        out.writeframes(samples)


def check_audio_roundtrip(video):
    import numpy as np

    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
        "stream=sample_rate,channels,duration,codec_name", "-of", "json", str(video)]))["streams"][0]
    assert (probe["sample_rate"], probe["channels"], probe["codec_name"]) == ("48000", 2, "aac"), probe
    assert abs(float(probe["duration"]) - 1.0) <= 0.05, probe
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(video), "-map", "0:a:0",
                                   "-f", "f32le", "-acodec", "pcm_f32le", "pipe:1"])
    decoded = np.frombuffer(raw, dtype="<f4").reshape(-1, 2)
    assert abs(len(decoded) - 48000) <= 2048, len(decoded)
    assert np.isfinite(decoded).all() and np.max(np.abs(decoded)) < 0.95
    center = decoded[4800:43200].astype(np.float64)
    time_axis = np.arange(len(center)) / 48000
    for channel, frequency, amplitude in ((0, 440, 0.25), (1, 880, 0.125)):
        signal = center[:, channel]
        peak = np.fft.rfftfreq(len(signal), 1 / 48000)[np.argmax(np.abs(np.fft.rfft(signal)))]
        rms = np.sqrt(np.mean(signal ** 2))
        basis = np.column_stack([np.sin(2 * np.pi * frequency * time_axis),
                                 np.cos(2 * np.pi * frequency * time_axis)])
        fit = basis @ np.linalg.lstsq(basis, signal, rcond=None)[0]
        snr = 10 * np.log10(np.mean(fit ** 2) / max(np.mean((signal - fit) ** 2), 1e-20))
        assert abs(peak - frequency) <= 2, (channel, peak)
        assert abs(rms / (amplitude / math.sqrt(2)) - 1) < 0.08, (channel, rms)
        assert snr > 25, (channel, snr)
        print(f"PASS: encoded audio channel {channel}: {peak:.1f} Hz, RMS={rms:.5f}, SNR={snr:.1f} dB")
    print("PASS: AAC stereo audio retains duration, pitch, channel order and level after RIFE/SPAN; no clipping")


def check_postprocess(bootstrap, data_root, *, refine=False):
    filename = "DaSiWa RIFE SPAN Refine.json" if refine else "DaSiWa RIFE SPAN.json"
    workflow = json.loads((bootstrap / "workflows" / filename).read_bytes())
    prefix = "rife_span_refine" if refine else "rife_span"
    frames = 25 if refine else 2
    selected = {3910, 3911, 3904, 3377, 3383, 3710}
    graph = {n["id"]: n for n in workflow["nodes"]}
    links = {e[0]: e for e in workflow["links"]}
    prompt = {"1": {"class_type": "EmptyImage", "inputs": {"width": 128, "height": 128,
                                                          "batch_size": frames, "color": 0x336699}}}
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
    prompt["3710"]["inputs"].update(filename_prefix="smoke/" + prefix, save_metadata=False,
                                    codec="H.264", bit_depth="8-bit")
    if refine:
        tone_path = data_root / "input" / "smoke-stereo.wav"
        write_test_audio(tone_path)
        prompt["2"] = {"class_type": "LoadAudio", "inputs": {"audio": tone_path.name}}
        prompt["3710"]["inputs"]["audio"] = ["2", 0]
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
    videos = list((data_root / "output/smoke").glob(prefix + "_*.mp4"))
    assert len(videos) == 1, videos
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=width,height,nb_frames,r_frame_rate", "-of", "json", str(videos[0])]))["streams"][0]
    expected_frames = (frames - 1) * 2 + 1
    assert (probe["width"], probe["height"], probe["nb_frames"], probe["r_frame_rate"]) == (256, 256, str(expected_frames), "48/1"), probe
    print(f"PASS: {filename}: {frames}x128x128@24 -> RIFE -> SPAN -> MP4 {expected_frames}x256x256@48 (CPU synthetic frames)")
    if refine:
        check_audio_roundtrip(videos[0])


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
                check_postprocess(bootstrap, Path(directory), refine=True)
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
