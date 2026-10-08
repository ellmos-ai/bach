"""Pinned GUI declarations and hostile distribution manifests."""
import hashlib
import json
from types import SimpleNamespace

import pytest
from hub._services.gui_contract_service import DIST_SCHEMA, KIT_SCHEMA, get_pinned_kit_manifest, verify_installed_dist
from gui.api.gui_capabilities import declaration


def dist(tmp_path, **changes):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<h1>Übersicht</h1>", encoding="utf-8")
    record = {"schema": DIST_SCHEMA, "source_commit": "a" * 40,
              "files": {"index.html": hashlib.sha256((root / "index.html").read_bytes()).hexdigest()}, **changes}
    (root / "dist-manifest.json").write_text(json.dumps(record))
    return root


def test_full_file_identity_and_unlisted_bytes(tmp_path):
    root = dist(tmp_path)
    assert verify_installed_dist(root, "a" * 40)["verified"]
    assert not verify_installed_dist(root, "b" * 40)["verified"]
    (root / "extra.js").write_text("foreign")
    assert verify_installed_dist(root, "a" * 40)["reason_code"] == "integrity_mismatch"


@pytest.mark.parametrize("name", ["../private", "/private", "C:/private", "x\\private", "a/../private", "a//b", "./index.html"])
def test_unsafe_distribution_paths_fail_closed(tmp_path, name):
    root = dist(tmp_path, files={name: "a" * 64})
    assert verify_installed_dist(root, "a" * 40)["reason_code"] == "invalid_dist_entry"


def test_symlink_and_non_file_are_not_verified(tmp_path):
    root = dist(tmp_path)
    outside = tmp_path / "private"
    outside.write_text("secret")
    try:
        (root / "linked").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable on this host")
    assert verify_installed_dist(root)["reason_code"] == "dist_symlink"


@pytest.mark.parametrize("changes", [{"source_commit": None}, {"files": {}}, {"files": {"index.html": "bad"}}])
def test_incomplete_identity_is_never_verified(tmp_path, changes):
    assert verify_installed_dist(dist(tmp_path, **changes))["verified"] is False


def test_schema_alone_cannot_verify_a_release(tmp_path):
    file = tmp_path / "kit.json"
    file.write_text(json.dumps({"schema": KIT_SCHEMA}))
    assert not get_pinned_kit_manifest(file)["verified"]
    file.write_text("[]")
    assert not get_pinned_kit_manifest(file)["verified"]


def test_consumer_catalog_preserves_modules_and_does_not_claim_readiness():
    route = SimpleNamespace(path="/api/tasks", methods={"GET", "POST"})
    result = declaration([route], {"verified": False}, {}, {"tasks": {"adapter_registered": True}})
    assert result["schema"] == "ellmos.gui.capabilities.v1" and isinstance(result["modules"], dict)
    assert len(result["pages"]) == 21 and result["gui"]["status"] == "unverified"
    assert all(e["verification_scope"] == "adapter" and not e["runtime_verified"] for e in result["endpoints"])
    tasks = next(p for p in result["pages"] if p["path"] == "/tasks")
    assert tasks["status"] == "unavailable" and tasks["missing"] == ["GET /api/task-assignees"]
    assert result["module_sources"] == []


def test_explicit_release_precedes_legacy_build_even_if_it_is_missing(tmp_path):
    from hub._services.gui_contract_service import resolve_gui_distribution
    legacy = tmp_path / "gui" / "web" / "dist"
    legacy.mkdir(parents=True)
    selected = tmp_path / "shared-release" / "dist"
    assert resolve_gui_distribution(tmp_path / "gui", str(selected)) == selected
    assert not selected.exists()
    assert resolve_gui_distribution(tmp_path / "gui") == legacy


def test_configured_release_expands_host_home(monkeypatch, tmp_path):
    from hub._services.gui_contract_service import resolve_gui_distribution
    monkeypatch.setenv("GUI_RELEASE_ROOT", str(tmp_path))
    assert resolve_gui_distribution(tmp_path / "gui", "$GUI_RELEASE_ROOT/dist") == tmp_path / "dist"
