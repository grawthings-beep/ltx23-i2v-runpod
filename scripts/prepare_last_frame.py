#!/usr/bin/env python3
"""Add an in-node last-frame preview without changing DaSiWa generation settings."""

import copy
import hashlib
import json
from pathlib import Path
import uuid

if __package__:
    from .workflow_contract import all_nodes, graphs
else:
    from workflow_contract import all_nodes, graphs

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "DasiwaLTX23WorkflowsI2VFLF2V_omniforgeCLTX23V51.json"
SOURCE_SHA256 = "d826b97f4076025b3b6b6c5f8ac2e2f61f64f5ae5dcd359a2a12a9c5f1356841"
OUTPUT = "DaSiWa Last Frame.json"


def build_workflow(source):
    workflow = copy.deepcopy(source)
    encoder = next(n for n in workflow["nodes"] if n["type"] == "DaSiWa_EnhancedVideoCombine")
    image_link = next(p["link"] for p in encoder["inputs"] if p["name"] == "images")
    edge = next(link for link in workflow["links"] if link[0] == image_link)
    upstream = next(n for n in workflow["nodes"] if n["id"] == edge[1])
    next_node = max(workflow["last_node_id"], *(n["id"] for n in all_nodes(workflow))) + 1
    next_link = max(workflow["last_link_id"], *(
        link["id"] if isinstance(link, dict) else link[0]
        for graph in graphs(workflow) for link in graph.get("links", [])
        if not isinstance(link, dict) or "id" in link
    )) + 1
    right = max([n["pos"][0] + n["size"][0] for n in workflow["nodes"]]
                + [g["bounding"][0] + g["bounding"][2] for g in workflow["groups"]])
    x, y = right + 160, encoder["pos"][1]
    order = max(n["order"] for n in workflow["nodes"]) + 1
    extract = {
        "id": next_node, "type": "ImageFromBatch", "title": "Extract Last Frame",
        "pos": [x, y], "size": [550, 110], "flags": {}, "order": order, "mode": 0,
        "inputs": [{"name": "image", "type": "IMAGE", "link": next_link}],
        "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [next_link + 1]}],
        "properties": {"Node name for S&R": "ImageFromBatch", "cnr_id": "comfy-core"},
        "widgets_values": [-1, 1], "widgets_values_named": {"batch_index": -1, "length": 1},
    }
    preview = {
        "id": next_node + 1, "type": "PreviewImage", "title": "Last Frame",
        "pos": [x, y + 220], "size": [550, 900], "flags": {}, "order": order + 1, "mode": 0,
        "inputs": [{"name": "images", "type": "IMAGE", "link": next_link + 1}],
        "outputs": [], "properties": {"Node name for S&R": "PreviewImage", "cnr_id": "comfy-core"},
        "widgets_values": [],
    }
    # Branch before encoding; do not retain the entire video through pass_frames.
    upstream["outputs"][edge[2]]["links"].append(next_link)
    workflow["links"].extend([
        [next_link, edge[1], edge[2], next_node, 0, "IMAGE"],
        [next_link + 1, next_node, 0, next_node + 1, 0, "IMAGE"],
    ])
    workflow["nodes"].extend([extract, preview])
    workflow["groups"].append({
        "id": max(g["id"] for g in workflow["groups"]) + 1, "title": "Last Frame",
        "bounding": [x - 30, y - 70, 610, 1220], "color": "#3f789e", "font_size": 24, "flags": {},
    })
    # Distinct subgraph identities let the original and this copy coexist in tabs.
    ids = {g["id"]: str(uuid.uuid5(uuid.NAMESPACE_URL, OUTPUT + "/" + g["id"]))
           for g in workflow["definitions"]["subgraphs"]}
    for node in all_nodes(workflow):
        if node["type"] in ids:
            node["type"] = ids[node["type"]]
    for graph in workflow["definitions"]["subgraphs"]:
        graph["id"] = ids[graph["id"]]
    workflow["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, OUTPUT))
    workflow["last_node_id"] = next_node + 1
    workflow["last_link_id"] = next_link + 1
    return workflow


def main():
    raw = (ROOT / "workflows" / SOURCE).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SOURCE_SHA256, "Source changed; review before regenerating"
    workflow = build_workflow(json.loads(raw))
    output = (json.dumps(workflow, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (ROOT / "workflows" / OUTPUT).write_bytes(output)
    print(f"{OUTPUT}: sha256={hashlib.sha256(output).hexdigest()}, nodes={len(all_nodes(workflow))}")


if __name__ == "__main__":
    main()
