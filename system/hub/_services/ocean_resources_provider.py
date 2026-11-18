# SPDX-License-Identifier: MIT
"""Pinned canonical extracted distribution, shared by read-only and native adapters."""
from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import subprocess
import sys
from importlib import metadata, util
from pathlib import Path
from threading import RLock
from urllib.parse import unquote, urlsplit

REPOSITORY = "https://github.com/ellmos-ai/ocean-resources"
VERSION = "0.2.0"
PIN_PATH = Path(__file__).with_name("ocean_resources_pin.json")
_VERIFIED_ROOT = None
_PROVIDER_LOCK = RLock()


class PipelineProviderUnavailable(RuntimeError):
    pass


def _git(root, *args):
    binary = shutil.which("git")
    if binary is None:
        raise PipelineProviderUnavailable("resource_provider_git_unavailable")
    result = subprocess.run([binary, "-C", str(root), *args], capture_output=True,
                            text=True, timeout=5, check=False)
    if result.returncode:
        raise PipelineProviderUnavailable("resource_provider_revision_mismatch")
    return result.stdout.strip()


def _document(raw):
    def unique(pairs):
        values = {}
        for key, value in pairs:
            if key in values:
                raise ValueError("duplicate provider field")
            values[key] = value
        return values
    if len(raw) > 1024 * 1024:
        raise ValueError("provider metadata too large")
    return json.loads(raw, object_pairs_hook=unique)


def pin():
    value = _document(PIN_PATH.read_bytes())
    if (set(value) != {"schema", "version", "repository", "commit", "files"}
            or value["schema"] != "bach.ocean-resources-pin.v1"
            or value["version"] != VERSION or value["repository"] != REPOSITORY
            or not isinstance(value["commit"], str) or len(value["commit"]) != 40
            or any(c not in "0123456789abcdef" for c in value["commit"])
            or not isinstance(value["files"], dict) or not value["files"]):
        raise PipelineProviderUnavailable("resource_provider_pin_invalid")
    return value


def load_verified(names):
    with _PROVIDER_LOCK:
        return _load_verified(names)


def _load_verified(names):
    """Verify editable/native VCS installs and every shipped Python/data source.

    Editable installs need the pinned revision in their canonical repository,
    a clean package and exact pinned content. A name/version match alone never
    admits a provider. Verification failures do not fall back to open-ocean.
    """
    global _VERIFIED_ROOT
    try:
        expected = pin()
        dist = metadata.distribution("ocean-resources")
        direct = _document(dist.read_text("direct_url.json") or "{}")
        if dist.version != VERSION:
            raise PipelineProviderUnavailable("resource_provider_version_mismatch")
        url = urlsplit(direct.get("url", ""))
        if direct.get("dir_info", {}).get("editable") is True:
            if url.scheme != "file" or url.netloc not in {"", "localhost"} or url.query or url.fragment:
                raise PipelineProviderUnavailable("resource_provider_provenance_mismatch")
            root = Path(unquote(url.path))
            if not root.is_absolute() or root.resolve() != root:
                raise PipelineProviderUnavailable("resource_provider_provenance_mismatch")
            if _git(root, "remote", "get-url", "origin").removesuffix(".git") != REPOSITORY:
                raise PipelineProviderUnavailable("resource_provider_provenance_mismatch")
            _git(root, "merge-base", "--is-ancestor", expected["commit"], "HEAD")
            _git(root, "diff", "--quiet", "HEAD", "--", "ocean_resources")
        else:
            vcs = direct.get("vcs_info", {})
            if (url.scheme != "https" or url.netloc != "github.com" or url.query or url.fragment
                    or url.path.removesuffix(".git") != "/ellmos-ai/ocean-resources"
                    or vcs.get("vcs") != "git" or vcs.get("commit_id") != expected["commit"]):
                raise PipelineProviderUnavailable("resource_provider_provenance_mismatch")
            root = Path(dist.locate_file("ocean_resources/__init__.py")).resolve().parents[1]
        package = root / "ocean_resources"
        actual = {str(p.relative_to(root)): p for p in package.rglob("*")
                  if p.is_file() and p.suffix in {".py", ".json"}}
        if set(actual) != set(expected["files"]):
            raise PipelineProviderUnavailable("resource_provider_content_mismatch")
        for relative, path in actual.items():
            if (path.resolve() != path or path.is_symlink()
                    or hashlib.sha256(path.read_bytes()).hexdigest() != expected["files"][relative]):
                raise PipelineProviderUnavailable("resource_provider_content_mismatch")
        verified_identity = (str(root), hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest())
        spec = util.find_spec("ocean_resources")
        if not spec or not spec.origin or Path(spec.origin).resolve() != package / "__init__.py":
            raise PipelineProviderUnavailable("resource_provider_import_mismatch")
        if _VERIFIED_ROOT is None and any(n == "ocean_resources" or n.startswith("ocean_resources.") for n in sys.modules):
            raise PipelineProviderUnavailable("resource_provider_preloaded_unverified")
        if _VERIFIED_ROOT is not None and _VERIFIED_ROOT != verified_identity:
            raise PipelineProviderUnavailable("resource_provider_changed_in_process")
        modules = {}
        for name in names:
            if name != "ocean_resources" and not name.startswith("ocean_resources."):
                raise PipelineProviderUnavailable("resource_provider_import_mismatch")
            modules[name] = importlib.import_module(name)
        for name, module in tuple(sys.modules.items()):
            if name == "ocean_resources" or name.startswith("ocean_resources."):
                relative = name.replace(".", "/") + ".py" if "." in name else "ocean_resources/__init__.py"
                if relative not in actual or Path(module.__file__).resolve() != actual[relative]:
                    raise PipelineProviderUnavailable("resource_provider_import_mismatch")
        _VERIFIED_ROOT = verified_identity
        return modules
    except PipelineProviderUnavailable:
        raise
    except Exception as exc:
        raise PipelineProviderUnavailable("resource_provider_unavailable") from exc
