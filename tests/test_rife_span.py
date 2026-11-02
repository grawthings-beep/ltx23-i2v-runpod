import hashlib
import itertools
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_rife_span import OUTPUT, REFINED_OUTPUT, SOURCE, SOURCE_SHA256, SPAN, build_workflow, edges
from scripts.workflow_contract import all_nodes, graphs, model_references, validate_links


class RifeSpanTests(unittest.TestCase):
    refine = False
    filename = OUTPUT

    @classmethod
    def setUpClass(cls):
        cls.source = json.loads((ROOT / "workflows" / SOURCE).read_bytes())
        cls.workflow = json.loads((ROOT / "workflows" / cls.filename).read_bytes())
        cls.nodes = {n["id"]: n for n in all_nodes(cls.workflow)}
        parent = cls.nodes[3676]
        cls.render = next(g for g in graphs(cls.workflow) if g.get("id") == parent["type"])

    def upstream(self, graph, node_id, input_name):
        node = next(n for n in graph["nodes"] if n["id"] == node_id)
        slot = next(i for i, p in enumerate(node["inputs"]) if p["name"] == input_name)
        link = next(e for e in edges(graph) if e[3:5] == [node_id, slot])
        return link[1:3]

    def test_deterministic_derivative_and_original_untouched(self):
        self.assertEqual(hashlib.sha256((ROOT / "workflows" / SOURCE).read_bytes()).hexdigest(), SOURCE_SHA256)
        self.assertEqual(build_workflow(self.source, refine=self.refine), self.workflow)
        original_ids = {g["id"] for g in graphs(self.source)}
        self.assertFalse(original_ids & {g["id"] for g in graphs(self.workflow)})

    def test_pass_count_and_no_latent_upscale_or_mosaic(self):
        types = [n["type"] for n in self.nodes.values()]
        self.assertEqual(types.count("SamplerCustomAdvanced"), 3 if self.refine else 1)
        self.assertEqual(types.count("LTXDirectorGuide"), 3 if self.refine else 1)
        self.assertNotIn("LTXVLatentUpsampler", types)
        self.assertNotIn("LatentUpscaleModelLoader", types)
        self.assertFalse(any("mosaic" in t.lower() for t in types))
        self.assertEqual(self.nodes[3643]["widgets_values"], ["linear_quadratic", 8, 1])
        self.assertEqual(self.nodes[3640]["widgets_values"], [1])
        self.assertEqual(self.nodes[3652]["widgets_values_named"]["scale_by"], 0.5)
        preview = self.nodes[3339]
        self.assertIsNone(next(p for p in preview["inputs"] if p["name"] == "latent_upscale_model")["link"])

    def test_guides_removed_before_full_and_tiled_decode(self):
        passes = [(3632, 3646, 3652)]
        if self.refine:
            passes += [(3647, 3648, 3651), (3654, 3653, 3663)]
        for crop, separate, guide in passes:
            self.assertEqual(self.nodes[crop]["type"], "LTXDirectorCropGuides")
            self.assertEqual(self.upstream(self.render, crop, "latent"), [separate, 0])
            self.assertEqual(self.upstream(self.render, crop, "positive"), [guide, 0])
            self.assertEqual(self.upstream(self.render, crop, "negative"), [guide, 1])
        self.assertEqual(self.upstream(self.render, 3628, "samples"), [passes[-1][0], 2])
        self.assertEqual(self.upstream(self.render, 3631, "latents"), [passes[-1][0], 2])
        self.assertEqual(self.upstream(self.render, 3629, "samples"), [passes[-1][1], 1])

    def test_rife_then_span_then_encode_once_with_doubled_fps(self):
        w = self.workflow
        self.assertEqual(self.upstream(w, 3911, "images"), [3676, 0])
        self.assertEqual(self.upstream(w, 3383, "image"), [3911, 0])
        self.assertEqual(self.upstream(w, 3710, "images"), [3383, 0])
        self.assertEqual(self.upstream(w, 3911, "interp_model"), [3910, 0])
        self.assertEqual(self.upstream(w, 3383, "upscale_model"), [3377, 0])
        self.assertEqual(self.nodes[3911]["widgets_values"], [2])
        self.assertEqual(self.nodes[3910]["widgets_values"], ["rife_v4.26.safetensors"])
        self.assertEqual(self.nodes[3377]["widgets_values"], [SPAN])
        self.assertEqual(self.nodes[3904]["widgets_values"], ["a * 2"])
        self.assertEqual(self.upstream(w, 3904, "values.a"), [3678, 6])
        self.assertEqual(self.upstream(w, 3710, "frame_rate"), [3904, 0])
        self.assertEqual(self.upstream(w, 3710, "audio"), [3676, 1])
        for kind in ("FrameInterpolate", "ImageUpscaleWithModel", "DaSiWa_EnhancedVideoCombine"):
            selected = [n for n in self.nodes.values() if n["type"] == kind]
            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0]["mode"], 0)
        self.assertEqual(self.nodes[3710]["widgets_values_named"]["container"], "MP4")
        self.assertEqual(self.nodes[3710]["widgets_values"], list(self.nodes[3710]["widgets_values_named"].values()))

    def test_director_loras_seed_and_first_pass_settings_retained(self):
        original = {n["id"]: n for n in all_nodes(self.source)}
        for ident in (3678, 3589, 3720, 3523, 3652, 3640, 3643, 3600):
            self.assertEqual(self.nodes[ident]["widgets_values"], original[ident]["widgets_values"])
        for ident in (3678, 3589):
            self.assertEqual(self.nodes[ident]["properties"], original[ident]["properties"])

    def test_exact_models_are_in_default_profile(self):
        manifest = json.loads((ROOT / "manifest/models.json").read_bytes())
        models = [m for m in manifest["models"] if "dasiwa" in m["profiles"]]
        names = {"/".join(p.split("/")[2:]) for m in models for p in [m["relative_path"], *m.get("aliases", [])]}
        self.assertFalse(model_references(self.workflow) - names)
        span = next(m for m in models if m["id"] == "nomosuni-span-2x")
        self.assertEqual(span["filename"], SPAN)
        self.assertEqual(span["exact_bytes"], 4461056)
        self.assertEqual(span["sha256"], "bee2a9c082f2b8f6e7f5db504b36593c24a1a959511f587114c399ca58b9c92c")

    def test_all_link_endpoints_and_subgraph_interfaces_match(self):
        self.assertEqual(validate_links(self.workflow), 0)
        link_ids = []
        for graph in graphs(self.workflow):
            links = edges(graph)
            link_ids.extend(e[0] for e in links)
            if "inputNode" not in graph:
                continue
            parent = next(n for n in self.workflow["nodes"] if n["type"] == graph["id"])
            for direction, endpoint, endpoint_slot, external_slot in (
                ("inputs", -10, 1, 2), ("outputs", -20, 3, 4)
            ):
                self.assertEqual([p["name"] for p in graph[direction]], [p["name"] for p in parent[direction]])
                for index, port in enumerate(graph[direction]):
                    self.assertEqual(port["linkIds"], [e[0] for e in links if e[endpoint_slot] == endpoint and e[external_slot] == index])
        self.assertEqual(len(link_ids), len(set(link_ids)))

    def test_layout_has_no_overlaps_or_ungrouped_nodes(self):
        def overlap(a, b):
            return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]

        for graph in graphs(self.workflow):
            bounds = [(n["id"], [n["pos"][0], n["pos"][1] - 30, n["size"][0], n["size"][1] + 30]) for n in graph["nodes"]]
            for key in ("inputNode", "outputNode"):
                if key in graph:
                    bounds.append((key, graph[key]["bounding"]))
            for a, b in itertools.combinations(bounds, 2):
                self.assertFalse(overlap(a[1], b[1]), (graph.get("name"), a[0], b[0]))
            for a, b in itertools.combinations(graph["groups"], 2):
                self.assertFalse(overlap(a["bounding"], b["bounding"]))
            for n in graph["nodes"]:
                x, y = n["pos"]
                width, height = n["size"]
                self.assertEqual(sum(gx <= x and gy + 30 <= y - 30 and gx + gw >= x + width and gy + gh >= y + height
                                     for gx, gy, gw, gh in (g["bounding"] for g in graph["groups"])), 1, n["id"])


class RifeSpanRefineTests(RifeSpanTests):
    refine = True
    filename = REFINED_OUTPUT

    def test_refinement_uses_original_settings_without_spatial_scaling(self):
        original = {n["id"]: n for n in all_nodes(self.source)}
        for ident in (3635, 3658, 3645, 3655, 3651, 3663):
            self.assertEqual(self.nodes[ident]["widgets_values"], original[ident]["widgets_values"])
        self.assertEqual(self.nodes[3635]["widgets_values"], ["linear_quadratic", 4, 0.4])
        self.assertEqual(self.nodes[3658]["widgets_values"], ["linear_quadratic", 2, 0.2])
        for ident in (3651, 3663):
            self.assertEqual(self.nodes[ident]["widgets_values_named"]["scale_by"], 1)
        self.assertFalse(any(n["type"] in ("LatentUpscale", "LatentUpscaleBy", "LTXVCropGuides") for n in self.nodes.values()))

    def test_video_and_audio_stay_paired_through_all_passes(self):
        for guide, crop, concat, separate, sampler in (
            (3651, 3632, 3633, 3646, 3649), (3663, 3647, 3657, 3648, 3656)
        ):
            for name, slot in (("positive", 0), ("negative", 1), ("latent", 2)):
                self.assertEqual(self.upstream(self.render, guide, name), [crop, slot])
            self.assertEqual(self.upstream(self.render, concat, "video_latent"), [guide, 2])
            self.assertEqual(self.upstream(self.render, concat, "audio_latent"), [separate, 1])
            self.assertEqual(self.upstream(self.render, sampler, "latent_image"), [concat, 0])
        self.assertEqual(self.upstream(self.render, 3648, "av_latent"), [3649, 0])
        self.assertEqual(self.upstream(self.render, 3653, "av_latent"), [3656, 0])
        self.assertFalse(any(n["type"] == "PrimitiveBoolean" and n["id"] in (3683, 3684) for n in self.nodes.values()))

    def test_fast_variant_is_unchanged_and_refine_has_separate_identity_and_output(self):
        raw = (ROOT / "workflows" / OUTPUT).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), "f301c5c50df8e06fca7b67279c740406052e4151e01303ebb2ea5523531ed886")
        fast_ids = {g["id"] for g in graphs(json.loads(raw))}
        self.assertFalse(fast_ids & {g["id"] for g in graphs(self.workflow)})
        self.assertTrue(self.nodes[3710]["widgets_values_named"]["filename_prefix"].startswith("rife_span_refine/"))


if __name__ == "__main__":
    unittest.main()
