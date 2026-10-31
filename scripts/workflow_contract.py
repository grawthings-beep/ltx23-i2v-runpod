"""Shared workflow inspection, without reserializing author-supplied JSON."""

from pathlib import Path, PurePosixPath


def graphs(workflow):
    return [workflow, *workflow.get("definitions", {}).get("subgraphs", [])]


def all_nodes(workflow):
    return [node for graph in graphs(workflow) for node in graph.get("nodes", [])]


def backend_types(workflow, catalog):
    subgraphs = {g["id"] for g in workflow.get("definitions", {}).get("subgraphs", [])}
    return {n["type"] for n in all_nodes(workflow)} - subgraphs - set(catalog["frontend_types"])


def model_path(root, relative):
    path = PurePosixPath(relative)
    if (path.is_absolute() or ".." in path.parts or "\\" in relative or ":" in relative
            or not path.parts or path.parts[0] != "models"):
        raise ValueError(f"unsafe model path: {relative}")
    destination = root / Path(*path.parts)
    if not destination.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"model path escapes data root: {relative}")
    return destination


def model_references(workflow):
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)

    return {
        value.replace("\\", "/")
        for node in all_nodes(workflow)
        for value in strings(node.get("widgets_values", []))
        if "\n" not in value and value.lower().endswith((".safetensors", ".pkl", ".gguf"))
        and value != "placeholder.gguf"
    }


def validate_links(workflow):
    placeholders = 0
    for graph in graphs(workflow):
        nodes = {node["id"]: node for node in graph["nodes"]}
        links = {}
        for link in graph.get("links", []):
            # The untouched V5.1 source contains one empty editor placeholder.
            if link == {"origin_id": "undefined", "target_id": "undefined"}:
                placeholders += 1
                continue
            if isinstance(link, dict):
                link = [link[key] for key in ("id", "origin_id", "origin_slot", "target_id", "target_slot", "type")]
            ident, origin, output, target, slot, _ = link
            if ident in links:
                raise ValueError(f"duplicate link {ident}")
            links[ident] = link
            if origin == -10:
                assert 0 <= output < len(graph["inputs"]), link
            else:
                assert ident in (nodes[origin]["outputs"][output].get("links") or []), link
            if target == -20:
                assert 0 <= slot < len(graph["outputs"]), link
            else:
                assert nodes[target]["inputs"][slot].get("link") == ident, link
        for node in nodes.values():
            for slot, port in enumerate(node.get("inputs", [])):
                ident = port.get("link")
                if ident is not None:
                    assert links[ident][3:5] == [node["id"], slot], (node["id"], ident)
            for slot, port in enumerate(node.get("outputs", [])):
                for ident in port.get("links") or []:
                    assert links[ident][1:3] == [node["id"], slot], (node["id"], ident)
    return placeholders
