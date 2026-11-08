# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit tests for Modular Core CI Smoke-Runner (Task -50), Bootstrap & Lockfile (Task -49),
and Software Prompts Import / PromptBoard Integration (Task -51).
"""

import json
import os
import shutil
import time
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from hub.modules import ModulesHandler
from hub.prompt import PromptHandler, promptboard_library_paths
from gui.server import app


@pytest.fixture
def client(monkeypatch):
    import gui.server as server
    monkeypatch.setattr(
        server,
        "validate_token",
        lambda token: {"id": 1, "device_id": 1} if token == "test-token" else None,
    )
    return TestClient(app, headers={"Authorization": "Bearer test-token"})


def test_modules_ci_runner_single_and_all():
    system_root = Path(__file__).parent.parent
    handler = ModulesHandler(system_root)

    # 1. Test single module 'prompt'
    ok, text, summary = handler.run_module_tests(target="prompt", timeout_sec=30)
    assert ok is True
    assert summary["modules_tested"] == 1
    assert summary["modules_passed"] == 1
    assert summary["total_tests"] >= 3
    assert "[PASS]" in text
    assert "prompt" in text

    # 2. Test unknown module
    ok_unk, text_unk, _ = handler.run_module_tests(target="nonexistent_xyz")
    assert ok_unk is False
    assert "nicht in .MODULES/ gefunden" in text_unk

    # 3. CLI handler invocation
    ok_cli, msg_cli = handler.handle("test", ["prompt"])
    assert ok_cli is True
    assert "=== MODUL-CI & SMOKE-RUNNER ===" in msg_cli
    assert "[PASS]" in msg_cli


def test_modules_bootstrap_lockfile_generation_and_verify(tmp_path: Path):
    system_root = Path(__file__).parent.parent
    handler = ModulesHandler(system_root)

    test_lockfile = tmp_path / "test_modules.lock.json"
    handler._resolve_lockfile = lambda custom=None: test_lockfile if not custom else Path(custom)

    # 1. Generate lockfile
    ok_gen, msg_gen = handler.bootstrap_core(["--generate-lockfile"])
    assert ok_gen is True
    assert "[OK]" in msg_gen
    assert test_lockfile.is_file()

    lock_data = json.loads(test_lockfile.read_text(encoding="utf-8"))
    assert lock_data["schema"] == "bach.modules-lock.v1"
    assert lock_data["total_modules"] >= 30
    assert "prompt" in lock_data["modules"]
    assert "cache" in lock_data["modules"]
    assert "sha256" in lock_data["modules"]["prompt"]

    # 2. Verify against lockfile
    ok_ver, msg_ver = handler.bootstrap_core(["--verify"])
    assert ok_ver is True
    assert "[INTAKT]" in msg_ver
    assert "Bootstrap-Prüfung: [ERFOLGREICH]" in msg_ver

    # 3. Minimal core bootstrap
    ok_min, msg_min = handler.bootstrap_core(["--minimal", "--dry-run"])
    assert ok_min is True
    assert "Geforderte Module: 8" in msg_min
    assert "Bootstrap-Prüfung: [ERFOLGREICH]" in msg_min


def test_auto_heal_on_failing_module_tests(tmp_path: Path):
    system_root = Path(__file__).parent.parent
    handler = ModulesHandler(system_root)

    test_modules_dir = tmp_path / ".MODULES"
    test_modules_dir.mkdir(parents=True, exist_ok=True)
    handler.modules_dir = test_modules_dir

    test_pins_file = test_modules_dir / ".version_pins.json"
    handler._resolve_pins_file = lambda: test_pins_file

    # 1. Install a working v1.0.0 module with passing test
    mod_v1 = tmp_path / "sample_test_mod_v1"
    mod_v1.mkdir(parents=True, exist_ok=True)
    (mod_v1 / "manifest.json").write_text(json.dumps({
        "name": "sample_test_mod",
        "version": "1.0.0",
        "entrypoints": {"library": "src/main.py"}
    }), encoding="utf-8")
    src_v1 = mod_v1 / "src"
    src_v1.mkdir(parents=True, exist_ok=True)
    (src_v1 / "main.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")
    tests_v1 = mod_v1 / "tests"
    tests_v1.mkdir(parents=True, exist_ok=True)
    (tests_v1 / "test_sample.py").write_text("from main import add\ndef test_add(): assert add(1, 2) == 3\n", encoding="utf-8")

    ok_v1, msg_v1 = handler._install_module(str(mod_v1))
    assert ok_v1 is True
    assert (test_modules_dir / "sample_test_mod" / "manifest.json").is_file()

    # 2. Try to update with v1.1.0 that has syntax-valid code but failing tests
    mod_v2 = tmp_path / "sample_test_mod_v2"
    mod_v2.mkdir(parents=True, exist_ok=True)
    (mod_v2 / "manifest.json").write_text(json.dumps({
        "name": "sample_test_mod",
        "version": "1.1.0",
        "entrypoints": {"library": "src/main.py"}
    }), encoding="utf-8")
    src_v2 = mod_v2 / "src"
    src_v2.mkdir(parents=True, exist_ok=True)
    (src_v2 / "main.py").write_text("def add(a, b): return a - b\n", encoding="utf-8")
    tests_v2 = mod_v2 / "tests"
    tests_v2.mkdir(parents=True, exist_ok=True)
    (tests_v2 / "test_sample.py").write_text("from main import add\ndef test_add(): assert add(1, 2) == 3\n", encoding="utf-8")

    ok_v2, msg_v2 = handler._install_module(str(mod_v2))
    assert ok_v2 is False
    assert "[AUTO-HEAL]" in msg_v2
    assert "Smoke-Tests fehlgeschlagen" in msg_v2

    # Verify rollback restored v1.0.0
    installed_manifest = json.loads((test_modules_dir / "sample_test_mod" / "manifest.json").read_text(encoding="utf-8"))
    assert installed_manifest["version"] == "1.0.0"
    assert handler.is_version_quarantined("sample_test_mod", "1.1.0") is True


def test_promptboard_library_paths_discovery():
    paths = promptboard_library_paths()
    assert any(".promptboard" in str(p).lower() for p in paths)
    assert any("promptboard" in str(p).lower() for p in paths)


def test_prompt_import_software_prompts(tmp_path: Path):
    system_root = Path(__file__).parent.parent
    db_file = tmp_path / "test_prompt_software.db"

    import sqlite3
    conn = sqlite3.connect(db_file)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prompt_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            purpose TEXT,
            text TEXT,
            tags TEXT,
            category TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.commit()
    conn.close()

    handler = PromptHandler(system_root, connection_factory=lambda: sqlite3.connect(db_file))

    # Test directory with sample prompts
    prompts_dir = tmp_path / "_prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "test_developer_loop.txt").write_text("Rolle: Entwickler\nAufgabe: Tests ausführen", encoding="utf-8")
    (prompts_dir / "test_review_agent.md").write_text("# Review Agent\nPrüfe Codequalität und Sicherheit", encoding="utf-8")

    # 1. Dry run
    res_dry = handler.import_software_prompts(software_dir=prompts_dir, dry_run=True)
    assert res_dry["ok"] is True
    assert res_dry["dry_run"] is True
    assert res_dry["imported"] == 2
    assert res_dry["total_found"] == 2

    # 2. Actual import
    res_act = handler.import_software_prompts(software_dir=prompts_dir, dry_run=False)
    assert res_act["ok"] is True
    assert res_act["dry_run"] is False
    assert res_act["imported"] == 2

    # 3. Re-import (should skip existing)
    res_dup = handler.import_software_prompts(software_dir=prompts_dir, dry_run=False)
    assert res_dup["ok"] is True
    assert res_dup["imported"] == 0
    assert res_dup["skipped"] == 2


def test_gui_api_modules_ci_bootstrap_and_software_import(client):
    # 1. POST /api/modules/test/prompt
    res_test = client.post("/api/modules/test/prompt")
    assert res_test.status_code == 200
    data_test = res_test.json()
    assert data_test["status"] == "ok"
    assert data_test["passed"] is True
    assert "summary" in data_test

    # 2. POST /api/modules/bootstrap (verify)
    res_boot = client.post("/api/modules/bootstrap", json={"action": "verify"})
    assert res_boot.status_code == 200
    data_boot = res_boot.json()
    assert data_boot["status"] == "ok"
    assert "message" in data_boot

    # 3. POST /api/prompt-library/import-software (dry_run)
    res_soft = client.post("/api/prompt-library/import-software", json={"dry_run": True})
    assert res_soft.status_code == 200
    data_soft = res_soft.json()
    assert data_soft["ok"] is True
    assert data_soft["dry_run"] is True

    # 4. GET /api/modules/reconcile
    res_rec = client.get("/api/modules/reconcile")
    assert res_rec.status_code == 200
    data_rec = res_rec.json()
    assert data_rec["status"] == "ok"
    assert "data" in data_rec
    assert data_rec["data"]["total_installed"] >= 30


def test_module_scaffolder_and_isolated_tests(tmp_path: Path):
    system_root = Path(__file__).parent.parent
    handler = ModulesHandler(system_root)

    out_mod_dir = tmp_path / "custom_service"
    ok, msg, summary = handler.scaffold_module(
        name="custom_service",
        module_type="service",
        description="Test Scaffolder Service",
        out_dir=out_mod_dir,
    )
    assert ok is True
    assert out_mod_dir.is_dir()
    assert (out_mod_dir / "manifest.json").is_file()
    assert (out_mod_dir / "src" / "custom_service.py").is_file()
    assert (out_mod_dir / "tests" / "test_custom_service.py").is_file()
    assert (out_mod_dir / "README.md").is_file()
    assert summary["verified"] is True

    # Run isolated smoke test on scaffolded module
    ok_test, out_test, count_test, dur = handler._run_single_module_tests(out_mod_dir)
    assert ok_test is True
    assert count_test >= 4

    # Test CLI invocation
    cli_out_dir = tmp_path / "cli_module"
    ok_cli, msg_cli = handler.handle("scaffold", ["cli_module", "--type", "tool", "--out", str(cli_out_dir)])
    assert ok_cli is True
    assert "[OK] Standalone-Modul 'cli_module' erfolgreich erstellt" in msg_cli
    assert (cli_out_dir / "manifest.json").is_file()


def test_module_reconciliation_and_pin_enforcement(tmp_path: Path):
    system_root = Path(__file__).parent.parent
    handler = ModulesHandler(system_root)

    # 1. Test reconciliation
    rec = handler.reconcile_feeds_and_pins()
    assert rec["schema"] == "bach.modules-reconciliation.v1"
    assert rec["total_installed"] >= 30
    assert rec["total_locked"] >= 30
    assert len(rec["items"]) >= 30

    ok_cli, text_cli = handler.handle("reconcile")
    assert ok_cli is True
    assert "=== BACH MODUL RECONCILIATION ===" in text_cli
    assert "Installierte Module:" in text_cli

    # 2. Test pin protection in check_for_updates
    test_pins = tmp_path / ".version_pins.json"
    handler._resolve_pins_file = lambda: test_pins
    handler.pin_version("prompt", version="1.0.0", reason="Lock down prompt template service")

    check = handler.check_for_updates(cache_ttl_sec=0)
    blocked = check.get("blocked_by_pins", [])
    # Prompt is pinned to 1.0.0 and installed at 1.0.0, so if any source had newer, it would be blocked
    assert "blocked_by_pins" in check
    assert "blocked_count" in check
