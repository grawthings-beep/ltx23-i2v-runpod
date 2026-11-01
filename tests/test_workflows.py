import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import download_models, validate_repo
from scripts.workflow_contract import backend_types, model_path, model_references, validate_links


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((ROOT / "manifest/workflows.json").read_text())
        self.manifest = json.loads((ROOT / "manifest/models.json").read_text())
        self.workflow = json.loads((ROOT / "workflows" / self.catalog["workflows"][0]["filename"]).read_bytes())

    def test_locked_originals_and_all_serialized_links(self):
        self.assertEqual(validate_repo.main(), 0)

    def test_dasiwa_profile_covers_exact_model_paths_without_old_checkpoint(self):
        models = download_models.selected_models(self.manifest, "dasiwa")
        names = {"/".join(p.split("/")[2:]) for m in models
                 for p in [m["relative_path"], *m.get("aliases", [])]}
        self.assertFalse(model_references(self.workflow) - names)
        self.assertEqual(len(models), 13)
        self.assertNotIn("ltx2310eros-v1-fp8", {m["id"] for m in models})

    def test_original_profiles_and_loras_remain(self):
        self.assertEqual(len(download_models.selected_models(self.manifest, "public")), 9)
        self.assertEqual(len(download_models.selected_models(self.manifest, "workflow")), 14)
        self.assertEqual(len(download_models.selected_models(self.manifest, "all")), 23)

    def test_user_loras_are_downloaded_without_enabling_workflow_slots(self):
        expected = {"FOOT.safetensors", "LTX2.3_reasoning_I2V_V3.safetensors"}
        private = [m for m in self.manifest["models"] if m.get("resolve_hf_metadata")]
        self.assertEqual({m["filename"] for m in private}, expected)
        for model in private:
            self.assertEqual(set(model["profiles"]), {"dasiwa", "workflow", "all"})
            self.assertEqual(model["relative_path"], "models/loras/LTX2/User/" + model["filename"])
            self.assertEqual(model["auth"], "HF_TOKEN")
        loader = next(n for n in self.workflow["nodes"] if n["type"] == "DaSiWa_LTX2LoraLoader")
        self.assertTrue(all(slot["lora"] == "None" for slot in json.loads(loader["widgets_values"][0])))

    def test_subgraph_ids_and_frontend_labels_are_not_missing_backend_nodes(self):
        types = backend_types(self.workflow, self.catalog)
        self.assertIn("LTXDirector", types)
        self.assertIn("PatchTritonVAE", types)
        self.assertNotIn("Lable (DaSiWa)", types)
        self.assertIn("easy getNode", self.catalog["frontend_types"])
        self.assertEqual(self.catalog["gpu_only_types"], ["RTXVideoSuperResolution"])
        self.assertNotIn(self.workflow["definitions"]["subgraphs"][0]["id"], types)

    def test_broken_serialized_link_is_rejected(self):
        broken = copy.deepcopy(self.workflow)
        broken["links"][0][4] = 999
        with self.assertRaises((AssertionError, IndexError)):
            validate_links(broken)

    def test_defaults_match_deployment(self):
        settings = json.loads((ROOT / "runpod/template-settings.json").read_text())
        self.assertEqual(settings["environment_variables"]["MODEL_PROFILE"], "dasiwa")
        self.assertIn('MODEL_PROFILE="${MODEL_PROFILE:-dasiwa}"', (ROOT / "scripts/start.sh").read_text())

    def test_container_uses_venv_and_preserves_cuda_before_node_install(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn('python3 -m venv --system-site-packages "${VIRTUAL_ENV}"', dockerfile)
        self.assertIn("PATH=/opt/venv/bin:${PATH}", dockerfile)
        self.assertIn("https://download.pytorch.org/whl/cu130", dockerfile)
        self.assertLess(dockerfile.index('packages = ("torch"'), dockerfile.index('/requirements.txt'))
        self.assertIn("Real entrypoint and node registration smoke test",
                      (ROOT / ".github/workflows/build-image.yml").read_text())


class ModelAliasTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = {"id": "test", "relative_path": "models/vae/source.bin",
                      "aliases": ["models/vae/LTX2/source.bin"], "exact_bytes": 3,
                      "sha256": hashlib.sha256(b"abc").hexdigest()}
        self.source = model_path(self.root, self.model["relative_path"])
        self.source.parent.mkdir(parents=True)

    def test_alias_is_zero_copy_and_idempotent(self):
        self.source.write_bytes(b"abc")
        download_models.create_model_aliases(self.model, self.root)
        download_models.create_model_aliases(self.model, self.root)
        self.assertTrue((self.root / self.model["aliases"][0]).samefile(self.source))

    def test_different_user_file_is_not_overwritten(self):
        self.source.write_bytes(b"abc")
        alias = self.root / self.model["aliases"][0]
        alias.parent.mkdir(parents=True)
        alias.write_bytes(b"xyz")
        with self.assertRaisesRegex(RuntimeError, "SHA256 mismatch"):
            download_models.create_model_aliases(self.model, self.root)
        self.assertEqual(alias.read_bytes(), b"xyz")

    def test_unsafe_paths_are_rejected(self):
        for value in ("../escape", "models/../escape", "/models/x", "C:/models/x", "models\\x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                model_path(self.root, value)

    def test_missing_secret_stops_before_any_download(self):
        self.model.update(gated=True, auth="HF_TOKEN", url="https://huggingface.co/example")
        with patch.dict(os.environ, {"HF_TOKEN": ""}), self.assertRaisesRegex(RuntimeError, "HF_TOKEN is required"):
            download_models.check_gated_access([self.model], self.root)

    def test_cached_file_does_not_require_secret(self):
        self.source.write_bytes(b"abc")
        self.model.update(gated=True, auth="HF_TOKEN")
        with patch.dict(os.environ, {"HF_TOKEN": ""}):
            download_models.check_gated_access([self.model], self.root)

    def test_rejected_secret_is_not_in_error(self):
        self.model.update(gated=True, auth="HF_TOKEN", url="https://huggingface.co/example")
        with patch.dict(os.environ, {"HF_TOKEN": "private-value"}), patch(
            "scripts.download_models.urllib.request.build_opener"
        ) as build:
            build.return_value.open.side_effect = urllib.error.HTTPError(
                self.model["url"], 403, "private-value", {}, None)
            with self.assertRaises(RuntimeError) as caught:
                download_models.check_gated_access([self.model], self.root)
            self.assertIn("HTTP 403", str(caught.exception))
            self.assertNotIn("private-value", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
