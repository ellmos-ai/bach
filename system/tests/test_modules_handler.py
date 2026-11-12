# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit tests for ModulesHandler and modular core update endpoints."""

import json
import zipfile
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from hub.modules import ModulesHandler, parse_semver
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


def test_parse_semver():
    assert parse_semver("1.0.0") == (1, 0, 0)
    assert parse_semver("v2.15.3") == (2, 15, 3)
    assert parse_semver("0.1.0-alpha") == (0, 1, 0)
    assert parse_semver("3") == (3, 0, 0)


def test_modules_handler_basics():
    system_root = Path(__file__).parent.parent
    handler = ModulesHandler(system_root)

    assert handler.profile_name == "modules"
    assert handler.target_file.is_dir()
    ops = handler.get_operations()
    assert "list" in ops
    assert "status" in ops
    assert "check" in ops
    assert "check-updates" in ops
    assert "auto-update" in ops
    assert "install" in ops
    assert "update" in ops
    assert "export" in ops
    assert "wire" in ops


def test_modules_list_and_status():
    system_root = Path(__file__).parent.parent
    handler = ModulesHandler(system_root)

    ok_list, msg_list = handler.handle("list")
    assert ok_list is True
    assert "STANDALONE MODULES" in msg_list
    assert "session" in msg_list
    assert "cache" in msg_list
    assert "scheduler" in msg_list
    assert "plugins" in msg_list
    assert "hooks" in msg_list
    assert "memory" in msg_list
    assert "skills" in msg_list
    assert "tools" in msg_list
    assert "agents" in msg_list

    ok_status, msg_status = handler.handle("status")
    assert ok_status is True
    assert "MODULARER CORE" in msg_status
    assert "Gebunden als Standalone" in msg_status

    status_data = handler.get_status_data()
    assert status_data["schema"] == "bach.modules-status.v1"
    assert status_data["modularized_services_total"] >= 30
    assert status_data["standalone_bound_count"] >= 30
    assert status_data["coverage_percent"] == 100.0


def test_modules_check():
    system_root = Path(__file__).parent.parent
    handler = ModulesHandler(system_root)

    ok_check, msg_check = handler.handle("check", ["prompt"])
    assert ok_check is True
    assert "prompt" in msg_check
    assert "[OK]" in msg_check

    # Non-existent module check
    ok_bad, msg_bad = handler.handle("check", ["non_existent_module_xyz"])
    assert ok_bad is False
    assert "nicht in .MODULES/ gefunden" in msg_bad


def test_modules_export_and_install(tmp_path: Path):
    system_root = Path(__file__).parent.parent
    handler = ModulesHandler(system_root)

    out_dir = tmp_path / "exports"
    ok_exp, msg_exp = handler.handle("export", ["cache", "--out", str(out_dir)])
    assert ok_exp is True
    assert "[OK]" in msg_exp

    zips = list(out_dir.glob("cache_*.zip"))
    assert len(zips) == 1
    zip_file = zips[0]

    # Verify zip content
    with zipfile.ZipFile(zip_file, "r") as zf:
        namelist = zf.namelist()
        assert "manifest.json" in namelist
        assert "src/cache.py" in namelist

    # Dry-run install
    ok_dry, msg_dry = handler.handle("install", [str(zip_file)], dry_run=True)
    assert ok_dry is True
    assert "[DRY-RUN]" in msg_dry


def test_modules_wire_and_update_dry_run():
    system_root = Path(__file__).parent.parent
    handler = ModulesHandler(system_root)

    ok_wire, msg_wire = handler.handle("wire")
    assert ok_wire is True
    assert "HOT-WIRING" in msg_wire

    ok_upd, msg_upd = handler.handle("update", ["--dry-run"])
    assert ok_upd is True
    assert "MODUL-UPDATE-SCAN" in msg_upd


def test_modules_check_for_updates():
    system_root = Path(__file__).parent.parent
    handler = ModulesHandler(system_root)

    check = handler.check_for_updates(cache_ttl_sec=0)
    assert check["schema"] == "bach.modules-update-check.v1"
    assert "has_updates" in check
    assert "updates_count" in check
    assert check["total_installed"] >= 27

    ok_cli, msg_cli = handler.handle("check-updates")
    assert ok_cli is True
    assert "MODUL-UPDATE-CHECK" in msg_cli


def test_gui_api_modules_endpoints(client):
    res_list = client.get("/api/modules/list")
    assert res_list.status_code == 200
    data_list = res_list.json()
    assert data_list["status"] == "ok"
    assert len(data_list["modules"]) >= 30

    res_status = client.get("/api/modules/status")
    assert res_status.status_code == 200
    data_status = res_status.json()
    assert data_status["status"] == "ok"
    assert data_status["standalone_count"] >= 30

    res_upd_chk = client.get("/api/modules/update-check")
    assert res_upd_chk.status_code == 200
    data_upd_chk = res_upd_chk.json()
    assert data_upd_chk["status"] == "ok"
    assert "has_updates" in data_upd_chk

    res_wire = client.post("/api/modules/wire")
    assert res_wire.status_code == 200
    data_wire = res_wire.json()
    assert data_wire["status"] == "ok"

    res_upd = client.post("/api/modules/update?dry_run=true")
    assert res_upd.status_code == 200
    data_upd = res_upd.json()
    assert data_upd["status"] == "ok"
    assert data_upd["dry_run"] is True


def test_modules_auto_update_cycle():
    system_root = Path(__file__).parent.parent
    handler = ModulesHandler(system_root)

    ok_auto, msg_auto = handler.handle("auto-update", ["--dry-run"])
    assert ok_auto is True
    assert "MODUL AUTO-UPDATE RUNNER" in msg_auto

    from hub.modules import run_modules_auto_update_runner
    res = run_modules_auto_update_runner(system_root, dry_run=True)
    assert res["success"] is True
    assert "MODUL AUTO-UPDATE RUNNER" in res["message"]
    assert "has_updates" in res


def test_modules_pack_and_checksum_verification(tmp_path):
    system_root = Path(__file__).parent.parent
    handler = ModulesHandler(system_root)

    ok_pack, msg_pack = handler.handle("pack", ["skills", "--bundle-deps", "--out", str(tmp_path)])
    assert ok_pack is True
    assert "erfolgreich gepackt" in msg_pack
    assert "Prüfsumme" in msg_pack

    zips = list(tmp_path.glob("skills_*_bundle_*.zip"))
    assert len(zips) == 1
    zip_p = zips[0]

    sha_p = tmp_path / f"{zip_p.name}.sha256"
    assert sha_p.is_file()
    expected_sha = sha_p.read_text(encoding="utf-8").split()[0].strip()

    import hashlib
    hasher = hashlib.sha256()
    with open(zip_p, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    assert hasher.hexdigest().lower() == expected_sha.lower()

    with zipfile.ZipFile(zip_p, "r") as zf:
        names = zf.namelist()
        assert "package_receipt.json" in names
        assert "manifest.json" in names
        assert "vendor/__init__.py" in names


def test_modules_scheduler_auto_update_job_registration(tmp_path):
    import sqlite3
    from hub.modules import ensure_scheduler_auto_update_job

    db_p = tmp_path / "test_scheduler.db"
    with sqlite3.connect(db_p) as conn:
        conn.execute("""
            CREATE TABLE scheduler_jobs (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                job_type TEXT DEFAULT 'interval',
                schedule TEXT DEFAULT '',
                command TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1,
                timeout_seconds INTEGER DEFAULT 60,
                retry_on_fail INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 0
            )
        """)

    res = ensure_scheduler_auto_update_job(conn_or_db_path=db_p, interval_hours=8)
    assert res["created"] is True
    assert res["name"] == "Modular Core Auto-Update"
    assert res["schedule"] == "8h"

    # Re-call updates without creating duplicate
    res2 = ensure_scheduler_auto_update_job(conn_or_db_path=db_p, interval_hours=12)
    assert res2["created"] is False
    assert res2["schedule"] == "12h"
    assert res2["job_id"] == res["job_id"]

