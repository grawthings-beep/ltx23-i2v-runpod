#!/usr/bin/env python3
"""Validate locked workflows, model paths and node ownership before building."""

import hashlib
import json
from pathlib import Path
import re

if __package__:
    from .download_models import hf_metadata_source
    from .workflow_contract import all_nodes, backend_types, model_path, model_references, validate_links
else:
    from download_models import hf_metadata_source
    from workflow_contract import all_nodes, backend_types, model_path, model_references, validate_links

ROOT = Path(__file__).resolve().parents[1]


def main():
    catalog = json.loads((ROOT / "manifest/workflows.json").read_text())
    nodes = json.loads((ROOT / "manifest/nodes.json").read_text())
    models = json.loads((ROOT / "manifest/models.json").read_text())
    expected_files = {entry["filename"] for entry in catalog["workflows"]}
    assert {p.name for p in (ROOT / "workflows").glob("*.json")} == expected_files
    assert re.fullmatch(r"[0-9a-f]{40}", nodes["comfyui"]["ref"])
    provided = set(catalog["core_types"])
    for node in nodes["nodes"]:
        assert re.fullmatch(r"[0-9a-f]{40}", node["ref"]), node["id"]
        provided.update(node["provides"])
    ids, destinations, model_names = set(), set(), set()
    for model in models["models"]:
        assert model["id"] not in ids, model["id"]
        ids.add(model["id"])
        assert set(model["profiles"]) <= set(models["profiles"]), model["id"]
        url = model.get("url") or model.get("archive_url")
        assert url and not model.get("url_env"), model["id"]
        if model.get("resolve_hf_metadata"):
            assert model["resolve_hf_metadata"] is True
            assert model["source"] == "huggingface" and model["auth"] == "HF_TOKEN"
            assert model["relative_path"].startswith("models/loras/")
            assert not model.get("archive_url")
            hf_metadata_source(model)
        else:
            assert re.fullmatch(r"[0-9a-f]{64}", model["sha256"]), model["id"]
            assert isinstance(model["exact_bytes"], int) and model["exact_bytes"] > 0
            assert re.search(r"/[0-9a-f]{40}/", url), f"unpinned URL: {model['id']}"
        assert Path(model["relative_path"]).name == model["filename"]
        for relative in [model["relative_path"], *model.get("aliases", [])]:
            model_path(ROOT, relative)
            assert relative not in destinations, relative
            destinations.add(relative)
            model_names.add("/".join(relative.split("/")[2:]))
    for entry in catalog["workflows"]:
        raw = (ROOT / "workflows" / entry["filename"]).read_bytes()
        digest_bytes = raw.rstrip(b"\r\n") if entry.get("strip_trailing_newlines") else raw
        assert hashlib.sha256(digest_bytes).hexdigest() == entry["sha256"], entry["filename"]
        workflow = json.loads(raw)
        assert len(all_nodes(workflow)) == entry["node_count"], entry["filename"]
        assert validate_links(workflow) == entry["empty_link_placeholders"]
        missing_nodes = backend_types(workflow, catalog) - provided
        assert not missing_nodes, f"unknown node types: {sorted(missing_nodes)}"
        missing_models = model_references(workflow) - model_names
        assert not missing_models, f"missing exact model selector paths: {sorted(missing_models)}"
        print(f"OK: {entry['filename']} ({entry['node_count']} nodes; original SHA256 preserved)")
    runtime_metadata = sum(bool(m.get("resolve_hf_metadata")) for m in models["models"])
    print(f"OK: {len(nodes['nodes'])} pinned node packs, {len(ids)} model artifacts "
          f"({runtime_metadata} private LoRAs verified at runtime)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
