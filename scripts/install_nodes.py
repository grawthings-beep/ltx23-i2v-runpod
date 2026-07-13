#!/usr/bin/env python3
"""Install pinned ComfyUI custom nodes from manifest/nodes.json."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Sequence


def run(cmd: Sequence[str], *, cwd: Path | None = None, attempts: int = 3) -> None:
    rendered = " ".join(str(part) for part in cmd)
    for attempt in range(1, attempts + 1):
        print(f"+ {rendered}", flush=True)
        result = subprocess.run(
            list(cmd),
            cwd=str(cwd) if cwd else None,
            env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"},
        )
        if result.returncode == 0:
            return
        if attempt == attempts:
            raise subprocess.CalledProcessError(result.returncode, list(cmd))
        delay = attempt * 3
        print(f"Command failed; retrying in {delay}s ({attempt}/{attempts})", file=sys.stderr)
        time.sleep(delay)


def git_head(path: Path) -> str | None:
    if not (path / ".git").is_dir():
        return None
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=False,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def clone_pinned(repo: str, ref: str, target: Path) -> None:
    current = git_head(target)
    if current == ref:
        print(f"[skip] {target.name} already at {ref}")
        return

    if target.exists():
        print(f"[replace] {target} (current={current or 'not-a-git-repo'})")
        shutil.rmtree(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "init", str(target)])
    run(["git", "-C", str(target), "remote", "add", "origin", repo])
    # A full SHA or tag/branch is accepted. Fetch only the requested object.
    run(["git", "-C", str(target), "fetch", "--depth=1", "origin", ref], attempts=4)
    run(["git", "-C", str(target), "checkout", "--detach", "FETCH_HEAD"])

    resolved = git_head(target)
    if len(ref) == 40 and resolved != ref:
        raise RuntimeError(f"{target.name}: expected {ref}, got {resolved}")


def install_requirements(
    node_dir: Path, python: str, constraints: Path | None = None
) -> None:
    req = node_dir / "requirements.txt"
    if not (req.is_file() and req.stat().st_size):
        return
    cmd = [python, "-m", "pip", "install"]
    if constraints:
        cmd.extend(["--constraint", str(constraints)])
    cmd.extend(["-r", str(req)])
    run(cmd, attempts=2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--comfy-root", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--skip-deps", action="store_true")
    parser.add_argument("--constraints", type=Path)
    parser.add_argument(
        "--clone-concurrency",
        type=int,
        default=int(os.environ.get("NODE_CLONE_CONCURRENCY", "6")),
    )
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    custom_nodes = args.comfy_root / "custom_nodes"
    custom_nodes.mkdir(parents=True, exist_ok=True)

    workers = max(1, min(args.clone_concurrency, len(manifest["nodes"])))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                clone_pinned,
                node["repository"],
                node["ref"],
                custom_nodes / node["directory"],
            ): node["id"]
            for node in manifest["nodes"]
        }
        for future in as_completed(futures):
            node_id = futures[future]
            try:
                future.result()
            except Exception as exc:
                raise RuntimeError(f"failed to install custom node {node_id}") from exc

    # Resolve Python requirements sequentially. Concurrent pip processes can
    # corrupt the environment and waste bandwidth; the BuildKit pip cache keeps
    # this stage fast without sacrificing determinism.
    if not args.skip_deps:
        for node in manifest["nodes"]:
            install_requirements(
                custom_nodes / node["directory"], args.python, args.constraints
            )

    print(f"Installed {len(manifest['nodes'])} pinned custom-node repositories.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
