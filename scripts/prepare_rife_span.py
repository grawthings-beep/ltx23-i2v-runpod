#!/usr/bin/env python3
"""Derive a first-pass/RIFE/SPAN workflow without rewriting either original."""

import copy
import hashlib
import json
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "DasiwaLTX23WorkflowsI2VFLF2V_omniforgeCLTX23V51.json"
OUTPUT = "DaSiWa RIFE SPAN.json"
SOURCE_SHA256 = "d826b97f4076025b3b6b6c5f8ac2e2f61f64f5ae5dcd359a2a12a9c5f1356841"
SPAN = "2xNomosUni_span_multijpg.safetensors"
LINK_KEYS = ("id", "origin_id", "origin_slot", "target_id", "target_slot", "type")


def edges(graph):
    return [list(link) if isinstance(link, list) else [link[k] for k in LINK_KEYS]
            for link in graph.get("links", []) if not isinstance(link, dict) or "id" in link]


def set_edges(graph, links):
    nodes = {node["id"]: node for node in graph["nodes"]}
    for node in nodes.values():
        for port in node.get("inputs", []):
            port["link"] = None
        for port in node.get("outputs", []):
            port["links"] = []
    for port in [*graph.get("inputs", []), *graph.get("outputs", [])]:
        port["linkIds"] = []
    valid = []
    for link in links:
        ident, origin, output, target, slot, kind = link
        if origin not in nodes and origin != -10 or target not in nodes and target != -20:
            continue
        if origin == -10:
            graph["inputs"][output]["linkIds"].append(ident)
        else:
            nodes[origin]["outputs"][output]["links"].append(ident)
        if target == -20:
            graph["outputs"][slot]["linkIds"].append(ident)
        else:
            assert nodes[target]["inputs"][slot]["link"] is None, (target, slot)
            nodes[target]["inputs"][slot]["link"] = ident
        valid.append(dict(zip(LINK_KEYS, link)) if "inputNode" in graph else link)
    graph["links"] = valid


def normalize_parent(root, graph):
    parent = next(n for n in root["nodes"] if n["type"] == graph["id"])
    old = parent["inputs"]
    by_name = {port["name"]: copy.deepcopy(port) for port in old}
    new = []
    for port in graph["inputs"]:
        new.append(by_name.get(port["name"], {
            "name": port["name"], "type": port["type"],
            "widget": {"name": port["name"]}, "link": None,
        }))
    links = edges(root)
    for link in links:
        if link[3] == parent["id"]:
            link[4] = next(i for i, p in enumerate(new) if p["name"] == old[link[4]]["name"])
    parent["inputs"] = new
    parent["properties"] = {"previewExposures": []}
    set_edges(root, links)
    return parent


def remove_ports(root, graph, input_slots=(), output_slots=()):
    parent = next(n for n in root["nodes"] if n["type"] == graph["id"])
    in_map = {old: new for new, old in enumerate(i for i in range(len(graph["inputs"])) if i not in input_slots)}
    out_map = {old: new for new, old in enumerate(i for i in range(len(graph["outputs"])) if i not in output_slots)}
    for obj in (graph, parent):
        obj["inputs"] = [obj["inputs"][i] for i in in_map]
        obj["outputs"] = [obj["outputs"][i] for i in out_map]
    inner = []
    for link in edges(graph):
        if link[1] == -10:
            if link[2] not in in_map:
                continue
            link[2] = in_map[link[2]]
        if link[3] == -20:
            if link[4] not in out_map:
                continue
            link[4] = out_map[link[4]]
        inner.append(link)
    outer = []
    for link in edges(root):
        if link[3] == parent["id"]:
            if link[4] not in in_map:
                continue
            link[4] = in_map[link[4]]
        if link[1] == parent["id"]:
            if link[2] not in out_map:
                continue
            link[2] = out_map[link[2]]
        outer.append(link)
    set_edges(graph, inner)
    set_edges(root, outer)


def group(graph, title, members, ident):
    left = min(n["pos"][0] for n in members) - 30
    top = min(n["pos"][1] for n in members) - 70
    right = max(n["pos"][0] + n["size"][0] for n in members) + 30
    bottom = max(n["pos"][1] + n["size"][1] for n in members) + 30
    graph["groups"].append({"id": ident, "title": title,
                            "bounding": [left, top, right - left, bottom - top],
                            "color": "#3f789e", "font_size": 24, "flags": {}})


def arrange_subgraph(graph):
    nodes = {n["id"]: n for n in graph["nodes"]}
    parents = {ident: set() for ident in nodes}
    for _, origin, _, target, _, _ in edges(graph):
        if origin in nodes and target in nodes:
            parents[target].add(origin)
    levels = {}
    while len(levels) < len(nodes):
        ready = [i for i in nodes if i not in levels and parents[i] <= levels.keys()]
        if not ready:
            raise ValueError(f"Cycle in {graph['name']}")
        for ident in ready:
            levels[ident] = max((levels[p] + 1 for p in parents[ident]), default=0)
    graph["groups"] = []
    x = 500
    for level in sorted(set(levels.values())):
        members = [nodes[i] for i in nodes if levels[i] == level]
        y = 140
        for n in members:
            if n["type"] != "Reroute":
                n["size"][0] = max(n["size"][0], 320)
            n["pos"] = [x, y]
            y += n["size"][1] + 100
        group(graph, f"{level + 1:02d} / {graph['name']}", members, level + 1)
        x += max(n["size"][0] for n in members) + 160
    for key, ports, px in (("inputNode", "inputs", 20), ("outputNode", "outputs", x)):
        graph[key]["bounding"] = [px, 140, 350, 60 + 24 * len(graph[ports])]
        for i, p in enumerate(graph[ports]):
            p["pos"] = [px + (326 if ports == "inputs" else 24), 164 + i * 24]


def build_workflow(source):
    w = copy.deepcopy(source)
    subgraphs = {g["name"]: g for g in w["definitions"]["subgraphs"]}
    model, render, post = (subgraphs[name] for name in ("Model Loader", "Rendering", "Post Processing"))
    model_parent = normalize_parent(w, model)
    render_parent = normalize_parent(w, render)

    # Preview keeps TAE, but neither preview nor generation loads a latent upscaler.
    model["nodes"] = [n for n in model["nodes"] if n["type"] != "LatentUpscaleModelLoader"]
    set_edges(model, edges(model))
    remove_ports(w, model, input_slots=(4, 14), output_slots=(3,))
    model_parent["widgets_values"].pop(4)

    # Crop the first pass's appended image guides before either VAE decode path.
    links = edges(render)
    for link in links:
        if (link[3], link[4]) in ((3628, 0), (3631, 1)):
            link[1:3] = [3632, 2]
        elif (link[3], link[4]) == (3629, 0):
            link[1:3] = [3646, 1]
    keep = {3627, 3629, 3706}
    while True:
        ancestors = {link[1] for link in links if link[3] in keep and link[1] != -10}
        if ancestors <= keep:
            break
        keep.update(ancestors)
    render["nodes"] = [n for n in render["nodes"] if n["id"] in keep]
    set_edges(render, links)
    remove_ports(w, render, input_slots=(7, 15, 16))
    render_parent["widgets_values"] = [True, False]
    render["name"] = "First Pass + Decode"
    render_parent["title"] = "First Pass + Decode (no latent upscale)"
    render_parent["size"] = [440, 370]

    # Reuse installed Comfy core nodes, with RIFE before the pixel-domain upscaler.
    post_nodes = {n["id"]: n for n in post["nodes"]}
    added = [copy.deepcopy(post_nodes[i]) for i in (3910, 3911, 3904, 3377, 3383)]
    for n in added:
        n["mode"] = 0
        n["properties"] = {"Node name for S&R": n["type"], "cnr_id": "comfy-core"}
    by_id = {n["id"]: n for n in added}
    by_id[3377]["widgets_values"] = [SPAN]
    by_id[3377]["widgets_values_named"] = {"model_name": SPAN}
    by_id[3377]["size"] = [460, 90]
    for ident, title in ((3910, "RIFE 4.26"), (3911, "RIFE 2x frames"),
                         (3904, "Output FPS = source FPS x 2"), (3377, "2x NomosUni SPAN"),
                         (3383, "SPAN 2x pixels (after RIFE)")):
        by_id[ident]["title"] = title
    w["nodes"] = [n for n in w["nodes"] if n["id"] in (3319, 3589, 3523, 3678, 3577, 3720, 3676, 3710)] + added
    w["definitions"]["subgraphs"].remove(post)
    links = edges(w)
    links.extend([
        [9000, 3676, 0, 3911, 1, "IMAGE"],
        [9001, 3910, 0, 3911, 0, "INTERP_MODEL"],
        [9002, 3911, 0, 3383, 1, "IMAGE"],
        [9003, 3377, 0, 3383, 0, "UPSCALE_MODEL"],
        [9004, 3383, 0, 3710, 0, "IMAGE"],
        [9005, 3678, 6, 3904, 0, "FLOAT"],
        [9006, 3904, 0, 3710, 3, "FLOAT"],
    ])
    note = {"id": 4000, "type": "MarkdownNote", "pos": [80, 930], "size": [660, 340],
            "flags": {}, "order": 0, "mode": 0, "inputs": [], "outputs": [],
            "properties": {}, "title": "DaSiWa RIFE SPAN / comparison",
            "widgets_values": ["First pass only (8 steps, CFG 1, scale 0.5).\n\n"
                               "No latent upscale, second/third pass or mosaic.\n\n"
                               "Decoded frames -> RIFE 2x -> NomosUni SPAN 2x -> MP4.\n\n"
                               "FPS is doubled automatically; audio is not stretched.\n\n"
                               "Model/LoRA/Director settings are retained from V5.1.\n"
                               "Resolution preset is the target-size budget, not the first-pass size.\n\n"
                               "For A/B tests, match image, prompts, seed, duration and output size."]}
    w["nodes"].append(note)
    set_edges(w, links)
    save = next(n for n in w["nodes"] if n["id"] == 3710)
    save["widgets_values_named"].update(filename_prefix="rife_span/%date:yyyy-MM-dd%/%date:hhmmss%",
                                        container="MP4", free_memory_if_needed=False)
    save["widgets_values"] = list(save["widgets_values_named"].values())
    save["title"] = "Save RIFE SPAN video"

    columns = [
        ("01 Models", [(3319, 80, 160, 660, 650), (4000, 80, 930, 660, 340)]),
        ("02 LoRA + Negative", [(3589, 900, 160, 660, 460), (3523, 900, 740, 660, 300)]),
        ("03 LTX Director", [(3678, 1720, 160, 1370, 1150)]),
        ("04 First pass", [(3577, 3250, 160, 440, 150), (3720, 3250, 430, 440, 200),
                           (3676, 3250, 750, 440, 370)]),
        ("05 RIFE 2x", [(3910, 3850, 160, 460, 90), (3911, 3850, 380, 460, 130),
                         (3904, 3850, 640, 460, 200)]),
        ("06 SPAN 2x", [(3377, 4470, 160, 460, 90), (3383, 4470, 380, 460, 150)]),
        ("07 MP4", [(3710, 5090, 160, 550, 1350)]),
    ]
    w["groups"] = []
    nodes = {n["id"]: n for n in w["nodes"]}
    for index, (title, specs) in enumerate(columns, 1):
        for ident, x, y, width, height in specs:
            nodes[ident]["pos"], nodes[ident]["size"] = [x, y], [width, height]
        group(w, title, [nodes[s[0]] for s in specs], index)

    for g in w["definitions"]["subgraphs"]:
        old = g["id"]
        g["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, OUTPUT + "/" + old))
        next(n for n in w["nodes"] if n["type"] == old)["type"] = g["id"]
        set_edges(g, edges(g))
        arrange_subgraph(g)
    # Unique link ids avoid collisions across serialized subgraphs.
    next_link = 10000
    for g in [w, *w["definitions"]["subgraphs"]]:
        links = edges(g)
        for link in links:
            link[0] = next_link
            next_link += 1
        set_edges(g, links)
        for order, n in enumerate(g["nodes"]):
            n["order"] = order
        if "state" in g:
            g["state"] = {"lastGroupId": len(g["groups"]), "lastNodeId": 4000,
                          "lastLinkId": next_link - 1, "lastRerouteId": 0}
    w["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, OUTPUT))
    w["last_node_id"], w["last_link_id"] = 4000, next_link - 1
    w["extra"]["ds"] = {"scale": 0.6, "offset": [0, 0]}
    w["extra"]["rife_span_source_sha256"] = SOURCE_SHA256
    return w


def main():
    raw = (ROOT / "workflows" / SOURCE).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SOURCE_SHA256, "Source changed; review before regenerating"
    workflow = build_workflow(json.loads(raw))
    output = (json.dumps(workflow, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (ROOT / "workflows" / OUTPUT).write_bytes(output)
    print(f"{OUTPUT}: sha256={hashlib.sha256(output).hexdigest()}, "
          f"nodes={sum(len(g['nodes']) for g in [workflow, *workflow['definitions']['subgraphs']])}")


if __name__ == "__main__":
    main()
