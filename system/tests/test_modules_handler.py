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

    ok_status, msg_status = handler.handle("status")
    assert ok_status is True
    assert "MODULARER CORE" in msg_status
    assert "Gebunden als Standalone" in msg_status

    status_data = handler.get_status_data()
    assert status_data["schema"] == "bach.modules-status.v1"
    assert status_data["modularized_services_total"] >= 24
    assert status_data["standalone_bound_count"] >= 24
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


def test_gui_api_modules_endpoints(client):
    res_list = client.get("/api/modules/list")
    assert res_list.status_code == 200
    data_list = res_list.json()
    assert data_list["status"] == "ok"
    assert len(data_list["modules"]) >= 24

    res_status = client.get("/api/modules/status")
    assert res_status.status_code == 200
    data_status = res_status.json()
    assert data_status["status"] == "ok"
    assert data_status["standalone_count"] >= 24

    res_wire = client.post("/api/modules/wire")
    assert res_wire.status_code == 200
    data_wire = res_wire.json()
    assert data_wire["status"] == "ok"

    res_upd = client.post("/api/modules/update?dry_run=true")
    assert res_upd.status_code == 200
    data_upd = res_upd.json()
    assert data_upd["status"] == "ok"
    assert data_upd["dry_run"] is True
