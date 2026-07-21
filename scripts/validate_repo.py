#!/usr/bin/env python3
"""Static consistency checks for the repository and supplied workflow."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_NAME = "MrXin LTX 2.3 I2V EROS V6.1.json"
WORKFLOW = ROOT / "workflows" / WORKFLOW_NAME
NODES = ROOT / "manifest" / "nodes.json"
MODELS = ROOT / "manifest" / "models.json"
EXPECTED_WORKFLOW_SHA256 = "a29ff5b4cecfe2cc399b6590fae299038996169e742e7a4c4a8ae40376aa50cd"
EXPECTED_WORKFLOW_NODES = 154
EXPECTED_NODE_REPOS = 15
EXPECTED_MODEL_ENTRIES = 15


def all_nodes(workflow: dict) -> list[dict]:
    nodes = list(workflow.get("nodes", []))
    for subgraph in workflow.get("definitions", {}).get("subgraphs", []):
        nodes.extend(subgraph.get("nodes", []))
    return nodes


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    workflow_files = sorted((ROOT / "workflows").glob("*.json"))
    if workflow_files != [WORKFLOW]:
        fail(
            f"workflows directory must contain only {WORKFLOW_NAME!r}; "
            f"found {[path.name for path in workflow_files]}"
        )

    workflow_bytes = WORKFLOW.read_bytes()
    workflow_digest = hashlib.sha256(workflow_bytes.rstrip(b"\r\n")).hexdigest()
    if workflow_digest != EXPECTED_WORKFLOW_SHA256:
        fail(
            f"workflow content changed: expected SHA256 {EXPECTED_WORKFLOW_SHA256}, "
            f"got {workflow_digest}"
        )

    workflow = json.loads(workflow_bytes)
    node_manifest = json.loads(NODES.read_text(encoding="utf-8"))
    model_manifest = json.loads(MODELS.read_text(encoding="utf-8"))

    if len(all_nodes(workflow)) != EXPECTED_WORKFLOW_NODES:
        fail(
            f"expected {EXPECTED_WORKFLOW_NODES} workflow nodes, "
            f"found {len(all_nodes(workflow))}"
        )
    if len(node_manifest["nodes"]) != EXPECTED_NODE_REPOS:
        fail(
            f"expected {EXPECTED_NODE_REPOS} custom-node repos, "
            f"found {len(node_manifest['nodes'])}"
        )
    if len(model_manifest["models"]) != EXPECTED_MODEL_ENTRIES:
        fail(
            f"expected {EXPECTED_MODEL_ENTRIES} model entries, "
            f"found {len(model_manifest['models'])}"
        )

    if node_manifest["comfyui"]["expected_version"] != "0.17.2":
        fail("ComfyUI version must match workflow core version 0.17.2")

    for node in node_manifest["nodes"]:
        if not re.fullmatch(r"[0-9a-f]{40}", node.get("ref", "")):
            fail(f"custom node is not pinned to a full commit: {node['id']}")

    custom_sources: set[str] = set()
    for node in all_nodes(workflow):
        props = node.get("properties") or {}
        source = props.get("aux_id") or props.get("cnr_id")
        if source and source != "comfy-core":
            custom_sources.add(source)

    aliases = {
        alias
        for item in node_manifest["nodes"]
        for alias in [item["id"], *item.get("aliases", [])]
    }
    missing_sources = sorted(source for source in custom_sources if source not in aliases)
    if missing_sources:
        fail(f"custom node sources absent from manifest: {missing_sources}")

    provided = {name for item in node_manifest["nodes"] for name in item.get("provides", [])}
    ignored_types = {"Note", "MarkdownNote"}
    custom_types = {
        str(node.get("type"))
        for node in all_nodes(workflow)
        if ((node.get("properties") or {}).get("cnr_id") != "comfy-core")
        and str(node.get("type")) not in ignored_types
        and not re.fullmatch(r"[0-9a-f-]{36}", str(node.get("type")))
    }
    missing_types = sorted(custom_types - provided)
    if missing_types:
        fail(f"custom node types absent from provides lists: {missing_types}")

    model_names = {item["filename"] for item in model_manifest["models"]}

    def scalar_strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for nested in value.values():
                yield from scalar_strings(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from scalar_strings(nested)

    referenced = set()
    for node in all_nodes(workflow):
        for value in scalar_strings(node.get("widgets_values", [])):
            candidate = value.strip()
            if "\\n" in candidate or not candidate.lower().endswith(".safetensors"):
                continue
            referenced.add(candidate.replace("/", "\\").split("\\")[-1])

    missing_models = sorted(name for name in referenced if name not in model_names)
    if missing_models:
        fail(f"model filenames absent from manifest: {missing_models}")

    ids = [item["id"] for item in model_manifest["models"]]
    if len(ids) != len(set(ids)):
        fail("duplicate model IDs")
    paths = [item["relative_path"] for item in model_manifest["models"]]
    if len(paths) != len(set(paths)):
        fail("duplicate model destinations")
    for path in paths:
        p = Path(path)
        if p.is_absolute() or ".." in p.parts:
            fail(f"unsafe relative model path: {path}")

    for model in model_manifest["models"]:
        if not re.fullmatch(r"[0-9a-f]{64}", model.get("sha256", "")):
            fail(f"model is missing a full SHA256: {model['id']}")
        if not isinstance(model.get("exact_bytes"), int) or model["exact_bytes"] <= 0:
            fail(f"model is missing a positive exact_bytes value: {model['id']}")
        if not model.get("url") and not model.get("archive_url"):
            fail(f"model is missing a pinned download URL: {model['id']}")
        if model.get("url_env"):
            fail(f"V6.1 must not require a private MODEL_URL variable: {model['id']}")

    print(
        f"OK: {len(all_nodes(workflow))} workflow nodes, "
        f"{len(node_manifest['nodes'])} custom-node repos, "
        f"{len(model_manifest['models'])} model entries."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
