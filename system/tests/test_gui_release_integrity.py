"""Pinned GUI declarations and hostile distribution manifests."""
import hashlib
import json
from pathlib import Path
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
    assert result["pages"] == [] and result["gui"]["status"] == "unverified"
    assert result["gui"]["page_reads"]["state"] == "unavailable"
    assert result["gui"]["page_reads"]["reason_code"] == "gui_kit_not_verified"
    assert all(e["verification_scope"] == "adapter" and not e["runtime_verified"] for e in result["endpoints"])
    tasks = next(p for p in result["pages"] if p["path"] == "/tasks")
    assert tasks["status"] == "unavailable" and tasks["missing"] == ["GET /api/task-assignees"]
    assert result["module_sources"] == []
    subscription = next(p for p in result["pages"] if p["path"] == "/agenten/subscription-agents")
    assert subscription["status"] == "unavailable"
    assert "POST /api/agent-studio/subscription-agents/compose" in subscription["requires"]
    assert "POST /api/agent-studio/subscription-agents/compose" in subscription["missing"]



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


def test_gui_consumer_and_kit_pin_bind_same_029_release():
    repo = Path(__file__).resolve().parents[2]
    consumer = json.loads((repo / "system/gui/gui-consumer.v1.json").read_text(encoding="utf-8"))
    kit = get_pinned_kit_manifest(repo / "system/gui/kit_manifest.json")

    assert consumer["schema"] == "ellmos.bach.gui-consumer.v1"
    assert consumer["id"] == "ellmos-system-gui"
    assert consumer["status"] == "pinned_release"
    assert consumer["version"] == "0.2.30"
    assert consumer["source"] == {
        "repository": "ellmos-ai/ellmos-system-gui",
        "commit": "eb0251ac4b85574087ad934611d19dc3df1f9c4c",
        "archive_sha256": "ff07b55656349da60cb18b5ead867da3f03d43d81e6964bc6448212d7412b188",
        "dist_manifest_schema": "ellmos-system-gui.dist.v1",
    }
    assert kit["verified"] is True  # Identity metadata only; installed bytes are verified separately.
    assert kit["version"] == consumer["version"]
    assert kit["pinned_source_commit"] == consumer["source"]["commit"]
    assert kit["release_archive_sha256"] == consumer["source"]["archive_sha256"]
    assert kit["release_archive"] == "ellmos-system-gui-0.2.30-eb0251ac4b85.zip"
    assert kit["dist_manifest_schema"] == "ellmos-system-gui.dist.v1"
    assert kit["expected_page_count"] == 39
    assert "installed" not in kit
    assert consumer["required_backend_routes"] == [
        "/api/gui/brand",
        "/api/gui/backend-origin",
        "/api/gui/capabilities",
    ]
    assert "/api/agent-studio/subscription-agents/compose" not in consumer["required_backend_routes"]
