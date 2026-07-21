import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts import download_models  # noqa: E402


class RedirectingOpener:
    def __init__(self, location: str):
        self.location = location
        self.requests = []

    def open(self, request, timeout):  # noqa: ANN001
        self.requests.append((request, timeout))
        raise urllib.error.HTTPError(
            request.full_url,
            307,
            "Temporary Redirect",
            {"Location": self.location},
            None,
        )


class FakeProcess:
    def __init__(self, *args, **kwargs):
        self.stdout = iter(
            [
                "token=secret-value&X-Amz-Signature=signed-value\n",
                "Authorization: Bearer secret-value\n",
                "progress 20%\n",
            ]
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def wait(self):
        return 0


class DownloadModelsTests(unittest.TestCase):
    def test_exact_size_is_enforced_for_completed_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.bin"
            path.write_bytes(b"abc")

            with self.assertRaisesRegex(RuntimeError, "expected exactly 4"):
                download_models.validate_model_file(
                    {"min_bytes": 1, "exact_bytes": 4}, path
                )

    def test_civitai_redirect_is_resolved_before_aria2(self):
        direct_url = (
            "https://b2.civitai.com/file/model.safetensors"
            "?Authorization=signed-value&b2ContentDisposition=attachment"
        )
        opener = RedirectingOpener(direct_url)
        model = {"auth": "CIVITAI_TOKEN"}
        with patch.dict(os.environ, {"CIVITAI_TOKEN": "api-token"}), patch(
            "scripts.download_models.urllib.request.build_opener",
            return_value=opener,
        ):
            url, headers = download_models.add_auth(
                "https://civitai.com/api/download/models/2747549",
                model,
            )

        self.assertEqual(url, direct_url)
        self.assertTrue(any(header.startswith("User-Agent: ") for header in headers))
        self.assertFalse(any(header.startswith("Authorization: ") for header in headers))
        request, timeout = opener.requests[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer api-token")
        self.assertEqual(timeout, 30)

    def test_streamed_output_redacts_api_and_signed_url_credentials(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"HF_TOKEN": "secret-value"}), patch(
            "scripts.download_models.shutil.which", return_value="aria2c"
        ), patch("scripts.download_models.subprocess.Popen", FakeProcess), patch(
            "sys.stdout", output
        ):
            download_models.run_aria2(
                [("https://example.com/model", Path("model.bin"), [])]
            )

        log = output.getvalue()
        self.assertNotIn("secret-value", log)
        self.assertNotIn("signed-value", log)
        self.assertIn("X-Amz-Signature=<redacted>", log)
        self.assertIn("progress 20%", log)

    def test_civitai_login_redirect_reports_rejected_token(self):
        opener = RedirectingOpener("/login?reason=download-auth")
        with patch(
            "scripts.download_models.urllib.request.build_opener",
            return_value=opener,
        ):
            with self.assertRaisesRegex(RuntimeError, "rejected CIVITAI_TOKEN"):
                download_models.resolve_civitai_download_url(
                    "https://civitai.com/api/download/models/2747549",
                    "invalid-token",
                )


if __name__ == "__main__":
    unittest.main()
