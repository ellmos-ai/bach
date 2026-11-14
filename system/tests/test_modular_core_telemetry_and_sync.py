# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tests for Modular Core Telemetry & Drift Dashboard (Task -57),
PromptBoard Live Tag-Filter-Matrix & Multi-Category Board (Task -56),
and Auto-Export & Multi-Repo Sync Pipeline (Task -55).
"""
import json
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from gui.server import app
from hub.modules import ModulesHandler


@pytest.fixture
def client(monkeypatch):
    import gui.server as server
    monkeypatch.setattr(
        server,
        "validate_token",
        lambda token: {"id": 1, "device_id": 1} if token == "test-token" else None,
    )
    return TestClient(app, headers={"Authorization": "Bearer test-token"})


def _make_isolated_module(modules_dir: Path, name: str, version: str = "1.0.0", extra: dict = None) -> Path:
    mod_dir = modules_dir / name
    (mod_dir / "src").mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "version": version,
        "type": "module",
        "description": f"Test module {name}",
        "selfcontained": True,
        "entrypoints": {"library": f"src/{name}.py"},
    }
    if extra:
        manifest.update(extra)
    (mod_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (mod_dir / "src" / f"{name}.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    return mod_dir


def test_telemetry_and_drift_detection(tmp_path: Path):
    base_dir = tmp_path / "system"
    modules_dir = base_dir / ".MODULES"
    modules_dir.mkdir(parents=True)

    mod_a = _make_isolated_module(
        modules_dir,
        "alpha_mod",
        version="1.2.0",
        extra={"required_modules": ["missing_dep"]},
    )
    _make_isolated_module(modules_dir, "beta_mod", version="2.0.0")

    handler = ModulesHandler(base_dir)
    handler.modules_dir = modules_dir
    lockfile = modules_dir / "modules.lock.json"

    ok_lock, _ = handler._generate_lockfile(lockfile)
    assert ok_lock is True

    # Baseline report: both intact, 1 missing required module dependency
    rep_clean = handler.get_telemetry_and_drift_report()
    assert rep_clean["schema"] == "bach.modules-telemetry.v1"
    assert rep_clean["summary"]["total_installed"] == 2
    assert rep_clean["summary"]["intact_count"] == 2
    assert rep_clean["summary"]["drift_count"] == 0
    assert rep_clean["summary"]["missing_deps_count"] == 1

    # Induce checksum drift in alpha_mod without bumping version
    (mod_a / "src" / "alpha_mod.py").write_text('__version__ = "1.2.0"\n# drift edit\n', encoding="utf-8")
    # Pin beta_mod & quarantine a version
    handler.pin_version("beta_mod", version="2.0.0", reason="Pin test")
    handler.quarantine_version("alpha_mod", version="1.2.1", reason="Broken upstream")

    rep_drift = handler.get_telemetry_and_drift_report()
    s = rep_drift["summary"]
    assert s["checksum_drift_count"] == 1
    assert s["drift_count"] == 1
    assert s["pinned_count"] == 1
    assert s["quarantined_count"] == 1

    items_by_name = {it["name"]: it for it in rep_drift["items"]}
    assert items_by_name["alpha_mod"]["drift_status"] == "checksum_drift"
    assert items_by_name["alpha_mod"]["checksum_match"] is False
    assert items_by_name["alpha_mod"]["missing_dependencies"] == ["missing_dep"]
    assert "1.2.1" in items_by_name["alpha_mod"]["quarantined_versions"]
    assert items_by_name["beta_mod"]["drift_status"] == "intact"
    assert items_by_name["beta_mod"]["pinned_version"] == "2.0.0"

    ok_cli, cli_text = handler.handle("telemetry")
    assert ok_cli is True
    assert "=== BACH MODUL TELEMETRIE & DEPENDENCY-DRIFT ===" in cli_text
    assert "checksum_drift" in cli_text


def test_auto_export_and_multi_repo_sync_pipeline(tmp_path: Path):
    base_dir = tmp_path / "system"
    modules_dir = base_dir / ".MODULES"
    modules_dir.mkdir(parents=True)

    _make_isolated_module(modules_dir, "gamma_mod", version="1.1.0")

    sibling_root = tmp_path / "repos"
    sibling_mod = sibling_root / "gamma_mod"
    (sibling_mod / "src").mkdir(parents=True)
    (sibling_mod / "manifest.json").write_text(
        json.dumps({"name": "gamma_mod", "version": "1.3.0"}, indent=2),
        encoding="utf-8",
    )

    handler = ModulesHandler(base_dir)
    handler.modules_dir = modules_dir
    handler._resolve_source_dirs = lambda: [sibling_root]
    export_dir = tmp_path / "exports" / "modules"

    # 1. Dry-run detects export candidate + sibling repo version drift
    dry_res = handler.sync_repos(dry_run=True, out_dir=export_dir)
    assert dry_res["dry_run"] is True
    assert dry_res["exported_count"] == 1
    assert dry_res["exported"][0]["status"] == "would_export"
    assert dry_res["repo_drift_count"] == 1
    assert dry_res["repo_drift"][0]["direction"] == "import_newer_from_repo"
    assert not (export_dir / "manifest_feed.json").exists()

    # 2. Apply auto-export creates zip, sha256 and manifest_feed.json
    apply_res = handler.sync_repos(dry_run=False, out_dir=export_dir)
    assert apply_res["dry_run"] is False
    assert apply_res["errors_count"] == 0
    assert apply_res["exported_count"] == 1
    assert apply_res["feed_written"] is True
    feed_file = export_dir / "manifest_feed.json"
    assert feed_file.is_file()
    feed_data = json.loads(feed_file.read_text(encoding="utf-8"))
    assert feed_data["schema"] == "bach.manifest-feed.v1"
    pkg_name = apply_res["exported"][0]["package_file"]
    assert (export_dir / pkg_name).is_file()
    assert (export_dir / f"{pkg_name}.sha256").is_file()

    # 3. Re-run with unchanged module skips redundant packing
    rerun_res = handler.sync_repos(dry_run=False, out_dir=export_dir)
    assert rerun_res["exported_count"] == 0
    assert rerun_res["skipped_count"] == 1

    # 4. CLI dry-run smoke check
    ok_cli, cli_out = handler.handle("auto-export", ["--out", str(export_dir), "--dry-run"])
    assert ok_cli is True
    assert "BACH AUTO-EXPORT & MULTI-REPO SYNC PIPELINE" in cli_out


def test_gui_api_telemetry_auto_export_and_promptboard_matrix(client):
    # 1. GET /api/modules/telemetry
    res_tel = client.get("/api/modules/telemetry")
    assert res_tel.status_code == 200
    tel = res_tel.json()
    assert tel["status"] == "ok"
    assert tel["data"]["schema"] == "bach.modules-telemetry.v1"
    assert tel["data"]["summary"]["total_installed"] >= 30

    # 2. POST /api/modules/auto-export (dry_run)
    res_exp = client.post("/api/modules/auto-export", json={"dry_run": True, "modules": ["prompt"]})
    assert res_exp.status_code == 200
    exp = res_exp.json()
    assert exp["status"] == "ok"
    assert exp["data"]["dry_run"] is True
    assert exp["data"]["total_evaluated"] >= 1

    # 3. PromptBoard Live Tag-Filter-Matrix & Multi-Category Board API
    c1 = client.post("/api/prompt-library", json={
        "name": "MatrixPromptOne",
        "text": "Analysiere Moduldrift",
        "category": "DevOps",
        "tags": "qa, review, favorite",
        "purpose": "Drift-Prüfung",
    })
    assert c1.status_code == 200
    pid1 = c1.json()["id"]

    c2 = client.post("/api/prompt-library", json={
        "name": "MatrixPromptTwo",
        "text": "Schreibe Doku",
        "category": "Docs",
        "tags": "qa, docs",
        "purpose": "Doku",
    })
    assert c2.status_code == 200

    # Multi-tag AND filter
    list_all = client.get("/api/prompt-library")
    assert list_all.status_code == 200
    body_all = list_all.json()
    assert "tag_counts" in body_all
    assert "boards" in body_all

    list_qa_rev = client.get("/api/prompt-library", params={"tags": "qa,review"})
    assert list_qa_rev.status_code == 200
    names = [p["name"] for p in list_qa_rev.json()["prompts"]]
    assert "MatrixPromptOne" in names
    assert "MatrixPromptTwo" not in names

    # Move category + assign board
    assign_res = client.post("/api/prompt-library/boards/assign", json={
        "prompt_id": pid1,
        "category": "Architecture",
        "board_title": "Core Sprint Board",
    })
    assert assign_res.status_code == 200
    assert assign_res.json()["ok"] is True
    assert assign_res.json()["category"] == "Architecture"

    boards_res = client.get("/api/prompt-library/boards")
    assert boards_res.status_code == 200
    boards_list = boards_res.json()["boards"]
    assert any(b["title"] == "Core Sprint Board" and pid1 in b["prompt_ids"] for b in boards_list)

    by_board = client.get("/api/prompt-library", params={"board": "Core Sprint Board"})
    assert by_board.status_code == 200
    assert [p["name"] for p in by_board.json()["prompts"]] == ["MatrixPromptOne"]


def test_gui_templates_telemetry_and_board_elements():
    templates_dir = Path(__file__).resolve().parent.parent / "gui" / "templates"

    index_html = (templates_dir / "index.html").read_text(encoding="utf-8")
    assert "modules-telemetry-bar" in index_html
    assert "/api/modules/telemetry" in index_html
    assert "data.prompts || data.items" in index_html
    assert "data.prompt || data.item" in index_html

    pl_html = (templates_dir / "prompt-library.html").read_text(encoding="utf-8")
    assert "pl-tag-matrix" in pl_html
    assert "pl-board-view" in pl_html
    assert "pl-view-toggle" in pl_html
    assert "toggleTagMatrixChip" in pl_html
    assert "renderBoardView" in pl_html
    assert "movePromptCategory" in pl_html
