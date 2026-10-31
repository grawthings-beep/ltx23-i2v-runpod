#!/usr/bin/env python3
"""Parallel, resumable model downloader for the RunPod ComfyUI image."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

if __package__:
    from .workflow_contract import model_path
else:
    from workflow_contract import model_path


CIVITAI_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
)
CIVITAI_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Expose redirect responses so signed download URLs can be captured."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def selected_models(manifest: dict, profile: str) -> list[dict]:
    return [model for model in manifest["models"] if profile in model.get("profiles", [])]


def hf_metadata_source(model: dict) -> tuple[str, str, str]:
    parsed = urllib.parse.urlsplit(model["url"])
    parts = urllib.parse.unquote(parsed.path).strip("/").split("/", 4)
    if (parsed.scheme != "https" or parsed.netloc != "huggingface.co"
            or parsed.query or parsed.fragment or len(parts) != 5
            or parts[2] != "resolve"
            or not re.fullmatch(r"[\w.-]+/[\w.-]+", "/".join(parts[:2]))
            or not re.fullmatch(r"main|[0-9a-f]{40}", parts[3])
            or any(p in ("", ".", "..") for p in parts[4].split("/"))
            or any(c in parts[4] for c in "\\\r\n")):
        raise RuntimeError(f"{model['id']}: invalid Hugging Face metadata source")
    return "/".join(parts[:2]), parts[3], parts[4]


def apply_hf_metadata(model: dict, metadata: dict) -> dict:
    repo, requested_revision, filename = hf_metadata_source(model)
    revision = metadata.get("revision", "")
    digest = metadata.get("sha256", "")
    size = metadata.get("exact_bytes")
    if (metadata.get("source_url") != model["url"]
            or not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision)
            or (requested_revision != "main" and revision != requested_revision)
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or type(size) is not int or size <= 0):
        raise RuntimeError(f"{model['id']}: invalid Hugging Face integrity metadata")
    return {**model, "sha256": digest, "exact_bytes": size,
            "url": f"https://huggingface.co/{repo}/resolve/{revision}/"
                   + urllib.parse.quote(filename, safe="/")}


def resolve_hf_models(models: list[dict], data_root: Path, *, allow_network: bool = True) -> list[dict]:
    """Lock private files to Hub integrity metadata before any download or resume."""
    resolved, repositories = [], {}
    for model in models:
        if not model.get("resolve_hf_metadata"):
            resolved.append(model)
            continue
        repo, revision, filename = hf_metadata_source(model)
        cache_key = hashlib.sha256(model["url"].encode()).hexdigest()
        cache = data_root / "cache" / "model-metadata" / f"{cache_key}.json"
        if not cache.resolve().is_relative_to(data_root.resolve()):
            raise RuntimeError(f"{model['id']}: metadata cache escapes data root")
        if cache.is_file():
            try:
                metadata = json.loads(cache.read_text(encoding="utf-8"))
                resolved.append(apply_hf_metadata(model, metadata))
            except (ValueError, AttributeError, TypeError, RuntimeError):
                raise RuntimeError(f"{model['id']}: invalid metadata cache: {cache}") from None
            continue
        if not allow_network:
            raise RuntimeError(f"{model['id']}: missing verified metadata; run download_models.py first")
        token = os.environ.get("HF_TOKEN", "").strip()
        help_text = f"HF_TOKEN must have read access to the private repository {repo}."
        if not token:
            raise RuntimeError(f"{model['id']}: {help_text}")
        key = (repo, revision)
        if key not in repositories:
            request = urllib.request.Request(
                f"https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true",
                headers={"Authorization": f"Bearer {token}"},
            )
            try:
                with urllib.request.build_opener(NoRedirectHandler()).open(request, timeout=30) as response:
                    repositories[key] = json.load(response)
            except urllib.error.HTTPError as exc:
                status = exc.code
                exc.close()
                raise RuntimeError(f"{model['id']}: metadata HTTP {status}. {help_text}") from None
            except (urllib.error.URLError, TimeoutError, ValueError):
                raise RuntimeError(f"{model['id']}: could not read Hugging Face metadata; retry later") from None
        info = repositories[key]
        try:
            matches = [f for f in info["siblings"] if f["rfilename"] == filename]
            if len(matches) != 1:
                raise ValueError("missing or ambiguous file")
            file = matches[0]
            if file["size"] != file["lfs"]["size"]:
                raise ValueError("inconsistent file size")
            metadata = {"source_url": model["url"], "revision": info["sha"],
                        "sha256": file["lfs"]["sha256"], "exact_bytes": file["size"]}
            verified = apply_hf_metadata(model, metadata)
        except (KeyError, TypeError, ValueError):
            raise RuntimeError(f"{model['id']}: missing file or SHA256/size metadata on Hugging Face") from None
        cache.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=cache.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(metadata, handle)
        try:
            temporary.replace(cache)
        finally:
            temporary.unlink(missing_ok=True)
        print(f"[metadata] {model['id']}: {verified['exact_bytes']} bytes, revision {info['sha']}")
        resolved.append(verified)
    return resolved


def resolved_url(model: dict) -> str | None:
    if model.get("url"):
        return model["url"]
    env_name = model.get("url_env")
    return os.environ.get(env_name, "").strip() or None


def is_civitai_host(host: str) -> bool:
    return host == "civitai.com" or host.endswith(".civitai.com")


def is_civitai_download_api_host(host: str) -> bool:
    return host in {"civitai.com", "www.civitai.com"}


def resolve_civitai_download_url(url: str, token: str) -> str:
    """Resolve Civitai's authenticated redirect before handing off to aria2.

    aria2 does not reliably preserve RFC 9110 authentication semantics across
    Civitai's redirects. Resolve redirects while they remain on Civitai and
    return the first external signed storage URL without downloading its body.
    """
    opener = urllib.request.build_opener(NoRedirectHandler())
    current = url
    for _ in range(10):
        host = (urllib.parse.urlsplit(current).hostname or "").lower()
        if not is_civitai_download_api_host(host):
            return current

        request = urllib.request.Request(
            current,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": CIVITAI_USER_AGENT,
            },
            method="GET",
        )
        try:
            response = opener.open(request, timeout=30)
        except urllib.error.HTTPError as exc:
            if exc.code not in CIVITAI_REDIRECT_STATUSES:
                raise RuntimeError(
                    f"Civitai URL resolution failed with HTTP {exc.code}"
                ) from exc
            location = exc.headers.get("Location")
            exc.close()
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Civitai URL resolution failed: {exc.reason}") from exc
        else:
            with response:
                location = response.headers.get("Location")
                if not location:
                    return current

        if not location:
            raise RuntimeError("Civitai redirect did not include a Location header")
        next_url = urllib.parse.urljoin(current, location)
        next_parts = urllib.parse.urlsplit(next_url)
        next_host = (next_parts.hostname or "").lower()
        if next_host == "auth.civitai.com" or next_parts.path.startswith("/login"):
            raise RuntimeError("Civitai rejected CIVITAI_TOKEN")
        current = next_url

    raise RuntimeError("Civitai URL resolution exceeded 10 redirects")


def add_auth(url: str, model: dict) -> tuple[str, list[str]]:
    """Attach credentials without printing them in the process command line.

    Public manifest entries may declare an explicit auth variable. For private
    URL entries, the host is used to infer the appropriate RunPod secret.
    """
    headers: list[str] = []
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    auth_name = model.get("auth")
    if not auth_name:
        if host == "civitai.com" or host.endswith(".civitai.com"):
            auth_name = "CIVITAI_TOKEN"
        elif host == "huggingface.co" or host.endswith(".huggingface.co"):
            auth_name = "HF_TOKEN"

    token = os.environ.get(auth_name, "").strip() if auth_name else ""
    if is_civitai_host(host):
        # Civitai redirects downloads to Backblaze B2/Cloudflare, which rejects
        # aria2's default User-Agent for some files with HTTP 403.
        headers.append(f"User-Agent: {CIVITAI_USER_AGENT}")

    if token and is_civitai_download_api_host(host):
        url = resolve_civitai_download_url(url, token)
        resolved_host = (urllib.parse.urlsplit(url).hostname or "").lower()
        if is_civitai_download_api_host(resolved_host):
            headers.append(f"Authorization: Bearer {token}")
    elif token and (host == "huggingface.co" or host.endswith(".huggingface.co")):
        headers.append(f"Authorization: Bearer {token}")

    return url, headers


def redact_sensitive_output(output: str) -> str:
    """Remove credentials and signed-URL authorization values from logs."""
    redacted = output
    for env_name in ("CIVITAI_TOKEN", "HF_TOKEN"):
        token = os.environ.get(env_name, "").strip()
        if token:
            redacted = redacted.replace(token, "<redacted>")

    redacted = re.sub(
        r"(?i)([?&](?:token|authorization|x-amz-credential|x-amz-signature|"
        r"x-amz-security-token|policy|signature|key-pair-id)=)[^&\s]+",
        r"\1<redacted>",
        redacted,
    )
    redacted = re.sub(
        r"(?i)(authorization:\s*(?:bearer\s+)?)[^\s]+",
        r"\1<redacted>",
        redacted,
    )
    return redacted


def emit_sanitized(output: str, *, stream: object) -> None:
    if not output:
        return
    sanitized = redact_sensitive_output(output)
    print(sanitized, end="" if sanitized.endswith("\n") else "\n", file=stream)


def is_complete(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0 and not Path(str(path) + ".aria2").exists()


def validate_model_file(model: dict, path: Path) -> None:
    """Perform cheap, non-loading integrity checks on downloaded artifacts."""
    if not is_complete(path):
        raise RuntimeError(f"incomplete file: {path}")

    minimum = int(model.get("min_bytes", 1))
    size = path.stat().st_size
    if size < minimum:
        raise RuntimeError(f"file too small: {path} ({size} bytes; expected at least {minimum})")

    exact = model.get("exact_bytes")
    if exact is not None and size != int(exact):
        raise RuntimeError(
            f"wrong file size: {path} ({size} bytes; expected exactly {int(exact)})"
        )

    if path.suffix.lower() == ".safetensors":
        with path.open("rb") as handle:
            raw_length = handle.read(8)
            if len(raw_length) != 8:
                raise RuntimeError(f"invalid safetensors header: {path}")
            header_length = int.from_bytes(raw_length, "little", signed=False)
            if header_length < 2 or header_length > min(size - 8, 128 * 1024 * 1024):
                raise RuntimeError(f"invalid safetensors header length: {path}")
            try:
                header = json.loads(handle.read(header_length))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"invalid safetensors metadata: {path}") from exc
            if not isinstance(header, dict):
                raise RuntimeError(f"invalid safetensors metadata object: {path}")


def remove_invalid_existing(model: dict, path: Path) -> bool:
    """Return True for a valid existing artifact; delete invalid completed files."""
    if not is_complete(path):
        return False
    try:
        validate_model_file(model, path)
        return True
    except RuntimeError as exc:
        print(f"[repair] {exc}; deleting and downloading again", file=sys.stderr)
        path.unlink(missing_ok=True)
        return False

def write_aria2_input(items: list[tuple[str, Path, list[str]]], path: Path) -> None:
    blocks: list[str] = []
    for url, output, headers in items:
        output.parent.mkdir(parents=True, exist_ok=True)
        block = [
            url,
            f"  dir={output.parent}",
            f"  out={output.name}",
            "  continue=true",
            "  auto-file-renaming=false",
            "  allow-overwrite=true",
        ]
        block.extend(f"  header={header}" for header in headers)
        blocks.append("\n".join(block))
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def run_aria2(items: list[tuple[str, Path, list[str]]]) -> None:
    if not items:
        return
    if shutil.which("aria2c") is None:
        raise RuntimeError("aria2c is required but was not found")

    with tempfile.NamedTemporaryFile("w", suffix=".aria2.txt", delete=False) as handle:
        input_path = Path(handle.name)
    try:
        write_aria2_input(items, input_path)
        concurrency = os.environ.get("DOWNLOAD_CONCURRENCY", "5")
        connections = os.environ.get("DOWNLOAD_CONNECTIONS", "16")
        max_tries = os.environ.get("DOWNLOAD_MAX_TRIES", "10")
        cmd = [
            "aria2c",
            f"--input-file={input_path}",
            f"--max-concurrent-downloads={concurrency}",
            f"--max-connection-per-server={connections}",
            f"--split={connections}",
            "--min-split-size=1M",
            "--file-allocation=none",
            "--continue=true",
            "--auto-file-renaming=false",
            "--allow-overwrite=true",
            f"--max-tries={max_tries}",
            "--retry-wait=3",
            "--lowest-speed-limit=10K",
            "--max-resume-failure-tries=5",
            "--connect-timeout=20",
            "--timeout=60",
            "--check-certificate=true",
            "--console-log-level=notice",
            "--summary-interval=10",
        ]
        print("+ " + " ".join(str(x) for x in cmd), flush=True)
        # Keep progress visible during large first-run downloads while still
        # redacting credentials and signed-URL parameters before they reach logs.
        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        ) as process:
            if process.stdout is None:
                raise RuntimeError("failed to capture aria2c output")
            for line in process.stdout:
                emit_sanitized(line, stream=sys.stdout)
            returncode = process.wait()
        if returncode:
            raise subprocess.CalledProcessError(returncode, cmd)
    finally:
        input_path.unlink(missing_ok=True)


def extract_archive(archive: Path, destination: Path, member_basename: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        matches = [name for name in zf.namelist() if Path(name).name == member_basename]
        if len(matches) != 1:
            raise RuntimeError(
                f"{archive}: expected exactly one {member_basename!r}, found {len(matches)}"
            )
        with zf.open(matches[0]) as source, tempfile.NamedTemporaryFile(
            "wb", dir=destination.parent, delete=False
        ) as tmp:
            shutil.copyfileobj(source, tmp)
            tmp_path = Path(tmp.name)
    tmp_path.replace(destination)


def verify_sha256(path: Path, expected: str) -> None:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual.lower() != expected.lower():
        raise RuntimeError(f"SHA256 mismatch for {path}: expected {expected}, got {actual}")


def create_model_aliases(model: dict, data_root: Path) -> None:
    source = model_path(data_root, model["relative_path"])
    for relative in model.get("aliases", []):
        alias = model_path(data_root, relative)
        if alias.exists():
            if not alias.samefile(source):
                # Never replace a different user-supplied artifact silently.
                validate_model_file(model, alias)
                verify_sha256(alias, model["sha256"])
            continue
        if alias.is_symlink():
            raise RuntimeError(f"broken model alias: {alias}")
        alias.parent.mkdir(parents=True, exist_ok=True)
        try:
            alias.hardlink_to(source)
        except OSError:
            alias.symlink_to(os.path.relpath(source, alias.parent))


def check_gated_access(models: list[dict], data_root: Path) -> None:
    opener = urllib.request.build_opener(NoRedirectHandler())
    for model in models:
        if not model.get("gated"):
            continue
        destination = model_path(data_root, model["relative_path"])
        try:
            validate_model_file(model, destination)
            continue
        except RuntimeError:
            pass
        token = os.environ.get(model["auth"], "").strip()
        help_text = (
            "Accept the model terms at https://huggingface.co/darksidewalker/DaSiWa-LTX2.3 "
            "and provide HF_TOKEN using a RunPod Secret with gated-repository read access."
        )
        if not token:
            raise RuntimeError(f"{model['id']}: HF_TOKEN is required. {help_text}")
        request = urllib.request.Request(
            model["url"], headers={"Authorization": f"Bearer {token}"}, method="HEAD"
        )
        try:
            with opener.open(request, timeout=30):
                pass
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            if status not in CIVITAI_REDIRECT_STATUSES:
                raise RuntimeError(f"{model['id']}: HTTP {status}. {help_text}") from None
        except urllib.error.URLError:
            raise RuntimeError(f"{model['id']}: could not verify Hugging Face access; retry later") from None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument(
        "--profile",
        choices=("dasiwa", "public", "workflow", "all"),
        default=os.environ.get("MODEL_PROFILE", "dasiwa"),
    )
    parser.add_argument(
        "--allow-missing-urls",
        action="store_true",
        default=os.environ.get("ALLOW_MISSING_MODEL_URLS", "0") == "1",
    )
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    models = selected_models(manifest, args.profile)
    try:
        models = resolve_hf_models(models, args.data_root)
        check_gated_access(models, args.data_root)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    downloads: list[tuple[str, Path, list[str]]] = []
    archives: list[tuple[dict, Path, Path]] = []
    missing: list[str] = []
    missing_ids: set[str] = set()

    for model in models:
        destination = model_path(args.data_root, model["relative_path"])
        if remove_invalid_existing(model, destination):
            print(f"[skip] {model['id']}: {destination}")
            continue

        if model.get("archive_url"):
            archive_url, headers = add_auth(model["archive_url"], model)
            archive_path = args.data_root / "cache" / "downloads" / (
                model["id"] + Path(urllib.parse.urlsplit(archive_url).path).suffix
            )
            if not is_complete(archive_path):
                downloads.append((archive_url, archive_path, headers))
            archives.append((model, archive_path, destination))
            continue

        url = resolved_url(model)
        if not url:
            missing.append(f"{model['id']} ({model.get('url_env', 'no URL field')})")
            missing_ids.add(model["id"])
            continue
        url, headers = add_auth(url, model)
        downloads.append((url, destination, headers))

    if missing and not args.allow_missing_urls:
        print("Missing model download URLs:", file=sys.stderr)
        for item in missing:
            print(f"  - {item}", file=sys.stderr)
        print(
            "Set the listed environment variables to direct file/API download URLs, "
            "or set ALLOW_MISSING_MODEL_URLS=1 to start without them.",
            file=sys.stderr,
        )
        return 2

    if missing:
        for item in missing:
            print(f"[warn] skipping missing URL: {item}", file=sys.stderr)

    if downloads:
        print(f"[download] {len(downloads)} file(s) are not yet complete:", flush=True)
        for _, destination, _ in downloads:
            print(f"  - {destination}", flush=True)
    run_aria2(downloads)

    for model, archive_path, destination in archives:
        if not is_complete(destination):
            extract_archive(archive_path, destination, model["archive_member_basename"])
            print(f"[extract] {model['id']}: {destination}")

    failed: list[str] = []
    for model in models:
        destination = model_path(args.data_root, model["relative_path"])
        if not is_complete(destination):
            if model["id"] not in missing_ids:
                failed.append(f"{model['id']}: {destination}")
            continue
        try:
            validate_model_file(model, destination)
            if model.get("sha256"):
                verify_sha256(destination, model["sha256"])
        except RuntimeError as exc:
            destination.unlink(missing_ok=True)
            failed.append(f"{model['id']}: {exc}")

    if failed:
        print("Model download verification failed:", file=sys.stderr)
        for item in failed:
            print(f"  - {item}", file=sys.stderr)
        return 3

    for model in models:
        if model["id"] not in missing_ids:
            create_model_aliases(model, args.data_root)

    print(f"Model profile '{args.profile}' is ready ({len(models) - len(missing)}/{len(models)} files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
