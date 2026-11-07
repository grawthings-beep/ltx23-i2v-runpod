import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import download_models


class HuggingFaceMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = (2).to_bytes(8, "little") + b"{}" + b"test"
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.revision = "a" * 40
        self.models = [
            {"id": name, "filename": name, "relative_path": f"models/loras/LTX2/User/{name}",
             "url": f"https://huggingface.co/uwgm/nikke-loras/resolve/main/{name}",
             "resolve_hf_metadata": True, "auth": "HF_TOKEN", "profiles": ["dasiwa"]}
            for name in ("FOOT.safetensors", "LTX2.3_reasoning_I2V_V3.safetensors")
        ]
        self.info = {"sha": self.revision, "siblings": [
            {"rfilename": m["filename"], "size": len(self.payload),
             "lfs": {"size": len(self.payload), "sha256": self.digest}}
            for m in self.models
        ]}

    def response(self, info=None):
        return io.BytesIO(json.dumps(self.info if info is None else info).encode())

    def test_two_files_share_one_authenticated_lookup_and_cache_without_token(self):
        with patch.dict(os.environ, {"HF_TOKEN": "private-value"}), patch(
            "scripts.download_models.urllib.request.build_opener"
        ) as build:
            build.return_value.open.return_value = self.response()
            result = download_models.resolve_hf_models(self.models, self.root)
            build.return_value.open.assert_called_once()
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.get_header("Authorization"), "Bearer private-value")
            self.assertEqual(request.full_url,
                             "https://huggingface.co/api/models/uwgm/nikke-loras/revision/main?blobs=true")
        for model in result:
            self.assertIn(f"/resolve/{self.revision}/", model["url"])
            self.assertEqual(model["sha256"], self.digest)
            self.assertEqual(model["exact_bytes"], len(self.payload))
        for cache in self.root.glob("cache/model-metadata/*.json"):
            self.assertNotIn("private-value", cache.read_text())
        with patch.dict(os.environ, {"HF_TOKEN": ""}), patch(
            "scripts.download_models.urllib.request.build_opener"
        ) as build:
            self.assertEqual(download_models.resolve_hf_models(
                self.models, self.root, allow_network=False), result)
            build.assert_not_called()
        self.assertNotIn("sha256", self.models[0])

    def test_missing_token_or_offline_metadata_stops_before_network(self):
        with patch.dict(os.environ, {"HF_TOKEN": ""}), patch(
            "scripts.download_models.urllib.request.build_opener"
        ) as build:
            with self.assertRaisesRegex(RuntimeError, "HF_TOKEN must have read access"):
                download_models.resolve_hf_models(self.models, self.root)
            with self.assertRaisesRegex(RuntimeError, "missing verified metadata"):
                download_models.resolve_hf_models(self.models, self.root, allow_network=False)
            build.assert_not_called()

    def test_http_errors_do_not_expose_token_or_follow_redirects(self):
        for code in (401, 403, 404, 302):
            with self.subTest(code=code), patch.dict(os.environ, {"HF_TOKEN": "private-value"}), patch(
                "scripts.download_models.urllib.request.build_opener"
            ) as build:
                build.return_value.open.side_effect = urllib.error.HTTPError(
                    self.models[0]["url"], code, "private-value", {}, None)
                with self.assertRaisesRegex(RuntimeError, f"metadata HTTP {code}") as caught:
                    download_models.resolve_hf_models(self.models, self.root)
                self.assertNotIn("private-value", str(caught.exception))
                self.assertIsInstance(build.call_args.args[0], download_models.NoRedirectHandler)

    def test_incomplete_or_invalid_remote_integrity_metadata_is_rejected(self):
        invalid = []
        for field, value in (("sha", "main"), ("siblings", [])):
            info = copy.deepcopy(self.info)
            info[field] = value
            invalid.append(info)
        for field, value in (("sha256", "bad"), ("size", 999)):
            info = copy.deepcopy(self.info)
            info["siblings"][0]["lfs"][field] = value
            invalid.append(info)
        info = copy.deepcopy(self.info)
        info["siblings"][0]["size"] = info["siblings"][0]["lfs"]["size"] = True
        invalid.append(info)
        for info in invalid:
            with self.subTest(info=info), patch.dict(os.environ, {"HF_TOKEN": "private-value"}), patch(
                "scripts.download_models.urllib.request.build_opener"
            ) as build:
                build.return_value.open.return_value = self.response(info)
                with self.assertRaises(RuntimeError):
                    download_models.resolve_hf_models(self.models, self.root)
        self.assertFalse(list(self.root.glob("cache/model-metadata/*.json")))

    def test_sources_cannot_send_credentials_to_other_hosts(self):
        for url in ("https://example.com/uwgm/nikke-loras/resolve/main/FOOT.safetensors",
                    "http://huggingface.co/uwgm/nikke-loras/resolve/main/FOOT.safetensors",
                    "https://huggingface.co@evil.example/uwgm/nikke-loras/resolve/main/FOOT.safetensors",
                    self.models[0]["url"] + "?token=secret",
                    self.models[0]["url"].replace("FOOT.safetensors", "../FOOT.safetensors")):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                download_models.hf_metadata_source({**self.models[0], "url": url})

    def test_corrupt_cached_metadata_is_rejected_without_network(self):
        cache_key = hashlib.sha256(self.models[0]["url"].encode()).hexdigest()
        cache = self.root / "cache/model-metadata" / f"{cache_key}.json"
        cache.parent.mkdir(parents=True)
        for content in ("not-json", "[]", json.dumps({"source_url": "wrong"})):
            cache.write_text(content)
            with self.subTest(content=content), patch(
                "scripts.download_models.urllib.request.build_opener"
            ) as build, self.assertRaisesRegex(RuntimeError, "invalid metadata cache"):
                download_models.resolve_hf_models(self.models, self.root)
            build.assert_not_called()

    def test_main_downloads_pinned_urls_and_rejects_bad_checksums(self):
        for corrupt in (False, True):
            root = self.root / str(corrupt)
            root.mkdir()
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"models": self.models}))

            def transfer(items):
                self.assertEqual(len(items), 2)
                for url, path, headers in items:
                    self.assertIn(f"/resolve/{self.revision}/", url)
                    self.assertIn("Authorization: Bearer private-value", headers)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(self.payload[:-4] + (b"fail" if corrupt else b"test"))

            with self.subTest(corrupt=corrupt), patch.dict(os.environ, {"HF_TOKEN": "private-value"}), patch(
                "scripts.download_models.urllib.request.build_opener"
            ) as build, patch("scripts.download_models.run_aria2", side_effect=transfer), patch(
                "sys.argv", ["download_models.py", "--manifest", str(manifest),
                             "--data-root", str(root), "--profile", "dasiwa"]
            ):
                build.return_value.open.return_value = self.response()
                self.assertEqual(download_models.main(), 3 if corrupt else 0)
            for model in self.models:
                self.assertEqual((root / model["relative_path"]).exists(), not corrupt)

    def test_static_manifest_entries_do_not_need_network_or_token(self):
        model = {"id": "static", "sha256": self.digest, "exact_bytes": 123}
        with patch("scripts.download_models.urllib.request.build_opener") as build:
            self.assertEqual(download_models.resolve_hf_models([model], self.root), [model])
            build.assert_not_called()

    def test_manifest_user_loras_share_parallel_download_and_cache_across_two_repositories(self):
        manifest = json.loads((Path(__file__).resolve().parents[1] / "manifest/models.json").read_bytes())
        models = [m for m in manifest["models"] if m.get("resolve_hf_metadata")]
        self.assertEqual(len(models), 4)
        info_by_repo, payload_by_repo = {}, {}
        for index, repo in enumerate(("uwgm/nikke-loras", "uwgm/nikke-civitai-backup")):
            payload = self.payload + bytes([index])
            payload_by_repo[repo] = payload
            info_by_repo[repo] = {"sha": ("a" if index == 0 else "b") * 40, "siblings": [
                {"rfilename": m["filename"], "size": len(payload),
                 "lfs": {"size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}}
                for m in models if download_models.hf_metadata_source(m)[0] == repo
            ]}
        path = self.root / "manifest.json"
        path.write_text(json.dumps({"models": models}))

        def metadata(request, **kwargs):
            self.assertEqual(request.get_header("Authorization"), "Bearer private-value")
            for repo, info in info_by_repo.items():
                if request.full_url == f"https://huggingface.co/api/models/{repo}/revision/main?blobs=true":
                    return self.response(info)
            self.fail(f"unexpected metadata request: {request.full_url}")

        def transfer(items):
            self.assertEqual(len(items), 4)
            for url, destination, headers in items:
                model = next(m for m in models if destination == self.root / m["relative_path"])
                repo = download_models.hf_metadata_source(model)[0]
                self.assertEqual(url, f"https://huggingface.co/{repo}/resolve/{info_by_repo[repo]['sha']}/{model['filename']}")
                self.assertIn("Authorization: Bearer private-value", headers)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(payload_by_repo[repo])

        args = ["download_models.py", "--manifest", str(path), "--data-root", str(self.root), "--profile", "dasiwa"]
        with patch.dict(os.environ, {"HF_TOKEN": "private-value"}), patch(
            "scripts.download_models.urllib.request.build_opener"
        ) as build, patch("scripts.download_models.run_aria2", side_effect=transfer) as download, patch("sys.argv", args):
            build.return_value.open.side_effect = metadata
            self.assertEqual(download_models.main(), 0)
            self.assertEqual(build.return_value.open.call_count, 2)
            download.assert_called_once()
        caches = list(self.root.glob("cache/model-metadata/*.json"))
        self.assertEqual(len(caches), 4)
        self.assertTrue(all("private-value" not in cache.read_text() for cache in caches))
        with patch.dict(os.environ, {"HF_TOKEN": ""}), patch(
            "scripts.download_models.urllib.request.build_opener"
        ) as build, patch("scripts.download_models.run_aria2", wraps=download_models.run_aria2) as download, patch(
            "scripts.download_models.subprocess.Popen"
        ) as process, patch("sys.argv", args):
            self.assertEqual(download_models.main(), 0)
            build.return_value.open.assert_not_called()
            download.assert_called_once_with([])
            process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
