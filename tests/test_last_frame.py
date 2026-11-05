import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_last_frame import OUTPUT, SOURCE, SOURCE_SHA256, build_workflow
from scripts.workflow_contract import all_nodes, backend_types, graphs, model_references, validate_links


class LastFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = json.loads((ROOT / "workflows" / SOURCE).read_bytes())
        cls.workflow = json.loads((ROOT / "workflows" / OUTPUT).read_bytes())
        original_ids = {n["id"] for n in all_nodes(cls.source)}
        cls.added = [n for n in cls.workflow["nodes"] if n["id"] not in original_ids]
        cls.extract = next(n for n in cls.added if n["type"] == "ImageFromBatch")
        cls.preview = next(n for n in cls.added if n["type"] == "PreviewImage")

    def test_reproducible_derivative_and_original_hash(self):
        self.assertEqual(hashlib.sha256((ROOT / "workflows" / SOURCE).read_bytes()).hexdigest(), SOURCE_SHA256)
        self.assertEqual(build_workflow(self.source), self.workflow)
        self.assertEqual(len(self.added), 2)
        self.assertFalse({g["id"] for g in graphs(self.source)} & {g["id"] for g in graphs(self.workflow)})

    def test_extracts_one_last_frame_from_encoder_input_without_changing_video(self):
        self.assertEqual(validate_links(self.workflow), 1)
        nodes = {n["id"]: n for n in self.workflow["nodes"]}
        links = {link[0]: link for link in self.workflow["links"]}
        encoder = next(n for n in nodes.values() if n["type"] == "DaSiWa_EnhancedVideoCombine")
        image_link = next(p["link"] for p in encoder["inputs"] if p["name"] == "images")
        branch = links[self.extract["inputs"][0]["link"]]
        self.assertEqual(branch[1:3], links[image_link][1:3])
        self.assertEqual(links[self.preview["inputs"][0]["link"]][1:3], [self.extract["id"], 0])
        self.assertEqual(self.extract["widgets_values"], [-1, 1])
        self.assertEqual(self.extract["widgets_values_named"], {"batch_index": -1, "length": 1})
        self.assertEqual(self.preview["title"], "Last Frame")
        self.assertTrue(all(n["mode"] == 0 for n in self.added))
        self.assertFalse(encoder["widgets_values_named"]["pass_frames"])
        self.assertFalse(encoder["widgets_values_named"]["save_last_frame"])

    def test_only_preview_branch_and_graph_identities_change(self):
        restored = copy.deepcopy(self.workflow)
        extra_nodes = {n["id"] for n in self.added}
        extra_links = {e[0] for e in restored["links"] if e[3] in extra_nodes}
        restored["nodes"] = [n for n in restored["nodes"] if n["id"] not in extra_nodes]
        restored["links"] = [e for e in restored["links"] if e[0] not in extra_links]
        restored["groups"].pop()
        ids = {new["id"]: old["id"] for old, new in zip(
            self.source["definitions"]["subgraphs"], restored["definitions"]["subgraphs"])}
        for node in all_nodes(restored):
            if node["type"] in ids:
                node["type"] = ids[node["type"]]
            for port in node.get("outputs", []):
                if port.get("links"):
                    port["links"] = [link for link in port["links"] if link not in extra_links]
        for graph in restored["definitions"]["subgraphs"]:
            graph["id"] = ids[graph["id"]]
        for key in ("id", "last_node_id", "last_link_id"):
            restored[key] = self.source[key]
        self.assertEqual(restored, self.source)

    def test_no_added_models_custom_nodes_or_span(self):
        catalog = json.loads((ROOT / "manifest/workflows.json").read_bytes())
        self.assertEqual(model_references(self.workflow), model_references(self.source))
        self.assertFalse(any("nomos" in name.lower() or "span" in name.lower()
                             for name in model_references(self.workflow)))
        self.assertEqual(backend_types(self.workflow, catalog) - backend_types(self.source, catalog),
                         {"ImageFromBatch", "PreviewImage"} - backend_types(self.source, catalog))
        self.assertTrue({n["type"] for n in self.added} <= set(catalog["core_types"]))

    def test_preview_group_is_separate_and_nodes_do_not_overlap(self):
        def overlaps(a, b):
            return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]

        group = self.workflow["groups"][-1]["bounding"]
        for previous in self.source["groups"]:
            self.assertFalse(overlaps(group, previous["bounding"]))
        for node in self.added:
            bounds = [node["pos"][0], node["pos"][1] - 30, node["size"][0], node["size"][1] + 30]
            self.assertTrue(group[0] <= bounds[0] and group[1] <= bounds[1])
            self.assertTrue(bounds[0] + bounds[2] <= group[0] + group[2])
            self.assertTrue(bounds[1] + bounds[3] <= group[1] + group[3])
            for other in self.workflow["nodes"]:
                if other["id"] != node["id"]:
                    other_bounds = [other["pos"][0], other["pos"][1] - 30, other["size"][0], other["size"][1] + 30]
                    self.assertFalse(overlaps(bounds, other_bounds), (node["id"], other["id"]))


if __name__ == "__main__":
    unittest.main()
