#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests fuer Tasks -61 (Board-Runner + Live-Tray-Refresh), -62 (bach update stack) und -63 (Legacy-Audit)."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SYSTEM_DIR = Path(__file__).resolve().parent.parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))


def _init_prompt_tables(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS prompt_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            category TEXT,
            text TEXT NOT NULL,
            purpose TEXT,
            tags TEXT,
            is_default INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS prompt_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt_id INTEGER NOT NULL,
            version_number INTEGER NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS prompt_boards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT UNIQUE NOT NULL,
            description TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS prompt_board_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board_id INTEGER NOT NULL,
            prompt_id INTEGER NOT NULL,
            added_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def isolated_prompt_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import gui.server as srv
    from gui import device_auth

    db_path = tmp_path / "prompt_test.db"
    _init_prompt_tables(db_path)

    def _get_db():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    token = "test-tasks-61-63-token"
    monkeypatch.setattr(device_auth, "GET_CONNECTION", _get_db)
    conn = _get_db()
    try:
        device_auth.init_devices_db(conn)
        conn.execute(
            "INSERT INTO devices (name, token_hash, status) VALUES (?, ?, 'active')",
            ("tasks-61-63-fixture", device_auth._hash_token(token)),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(srv, "get_bach_db", _get_db)
    with TestClient(srv.app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client, db_path


def test_task_61_board_runner_api_and_templates(isolated_prompt_client):
    client, _ = isolated_prompt_client

    r1 = client.post(
        "/api/prompt-library",
        json={
            "name": "StepOne",
            "text": "Schritt 1 ausfuehren",
            "category": "Workflow",
            "tags": "runner, qa",
            "purpose": "First",
        },
    )
    r2 = client.post(
        "/api/prompt-library",
        json={
            "name": "StepTwo",
            "text": "Schritt 2 ausfuehren",
            "category": "Workflow",
            "tags": "runner",
            "purpose": "Second",
        },
    )
    assert r1.status_code == 200 and r2.status_code == 200
    pid1, pid2 = r1.json()["id"], r2.json()["id"]

    a1 = client.post(
        "/api/prompt-library/boards/assign",
        json={"prompt_id": pid1, "board_title": "Release Sprint"},
    )
    a2 = client.post(
        "/api/prompt-library/boards/assign",
        json={"prompt_id": pid2, "board_title": "Release Sprint"},
    )
    assert a1.status_code == 200 and a2.status_code == 200
    board_id = a1.json()["board_id"]

    # Fetch by numeric ID and by case-insensitive title
    by_id = client.get(f"/api/prompt-library/boards/{board_id}")
    assert by_id.status_code == 200
    b_data = by_id.json()["board"]
    assert b_data["title"] == "Release Sprint"
    assert [p["name"] for p in b_data["prompts"]] == ["StepOne", "StepTwo"]

    by_title = client.get("/api/prompt-library/boards/release sprint")
    assert by_title.status_code == 200
    assert by_title.json()["board"]["id"] == board_id

    missing = client.get("/api/prompt-library/boards/999999")
    assert missing.status_code == 404

    # UI Template assertions
    templates_dir = SYSTEM_DIR / "gui" / "templates"
    pl_html = (templates_dir / "prompt-library.html").read_text(encoding="utf-8")
    assert "pl-run-board-btn" in pl_html
    assert "runSelectedBoardInChat" in pl_html

    chat_html = (templates_dir / "chat.html").read_text(encoding="utf-8")
    assert "chat-board-runner" in chat_html
    assert "initBoardRunner" in chat_html
    assert "runBoardRunnerLoop" in chat_html
    assert "toggleBoardRunnerPause" in chat_html
    assert "stepBoardRunnerNext" in chat_html
    assert "cancelBoardRunner" in chat_html
    assert chat_html.count("loadLibraryDraft()") == 2  # definition + single init call


def test_task_61_tray_live_refresh_and_board_runner_action(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from hub._services.chat import chat_tray

    fake_root = tmp_path / "sys"
    (fake_root / "data").mkdir(parents=True)
    db_path = fake_root / "data" / "bach.db"
    _init_prompt_tables(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO prompt_templates (name, category, text, tags, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("InitialPrompt", "Allg", "Hallo Welt", "qa", "2026-11-14T10:00:00"),
    )
    conn.execute(
        "INSERT INTO prompt_boards (id, title, description, created_at) VALUES (1, 'Ops Board', 'Desc', '2026-11-14T10:00:00')"
    )
    conn.execute(
        "INSERT INTO prompt_board_items (board_id, prompt_id, added_at) VALUES (1, 1, '2026-11-14T10:00:00')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(chat_tray, "BACH_DB", db_path)
    tray = chat_tray.BACHTray(gui_port=8000)

    snap = tray.promptboard_smoke_snapshot()
    assert snap["board_runner_supported"] is True
    assert snap["live_tray_refresh_supported"] is True
    assert tray._check_prompt_boards_refresh() is False  # Baseline initialized
    assert len(tray.prompt_boards) == 1

    # Simulate DB edit (new board item)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO prompt_templates (name, category, text, tags, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("SecondPrompt", "Allg", "Zweiter Prompt", "qa", "2026-11-14T10:05:00"),
    )
    conn.execute(
        "INSERT INTO prompt_board_items (board_id, prompt_id, added_at) VALUES (1, 2, '2026-11-14T10:05:00')"
    )
    conn.commit()
    conn.close()

    assert tray._check_prompt_boards_refresh() is True
    assert len(tray.prompt_boards[0]["prompts"]) == 2

    # Verify board run action opens /chat?board_id=...&board_autorun=1
    opened_urls = []
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda url: opened_urls.append(url))
    tray._make_board_run_in_chat_action(1, "Ops Board")()
    assert len(opened_urls) == 1
    assert "board_id=1" in opened_urls[0]
    assert "board_autorun=1" in opened_urls[0]


def test_task_62_stack_update_cli_and_api(isolated_prompt_client):
    client, _ = isolated_prompt_client
    from hub.modules import ModulesHandler
    from hub.update import UpdateHandler

    upd = UpdateHandler(SYSTEM_DIR)
    assert "stack" in upd.get_operations()

    ok_cli, cli_out = upd.handle("stack", ["--dry-run", "--json"])
    assert ok_cli is True
    parsed = json.loads(cli_out)
    assert parsed["schema"] == "bach.stack-update.v1"
    assert parsed["dry_run"] is True
    assert "drift_count" in parsed

    mod_h = ModulesHandler(SYSTEM_DIR)
    assert "stack-update" in mod_h.get_operations()
    ok_strict, strict_rep = mod_h.run_stack_update(apply_updates=False, dry_run=True, strict=True)
    assert ok_strict is True
    assert strict_rep["drift_count"] == 0

    api_resp = client.post("/api/modules/stack-update", json={"dry_run": True, "strict": True})
    assert api_resp.status_code == 200
    body = api_resp.json()
    assert body["status"] == "ok"
    assert body["data"]["schema"] == "bach.stack-update.v1"


def test_task_63_legacy_audit_and_new_standalone_modules():
    from hub.modules import ModulesHandler
    from hub._services import ocean_stack_bridge as bridge

    mod_h = ModulesHandler(SYSTEM_DIR)
    assert "audit-legacy" in mod_h.get_operations()

    audit = mod_h.audit_legacy_candidates(["permissions", "config", "backup", "connector"])
    assert audit["schema"] == "bach.legacy-candidates-audit.v1"
    assert audit["total_audited"] == 4
    assert audit["standalone_bound_count"] == 4
    for item in audit["candidates"]:
        assert item["readiness"] == "standalone_bound"
        assert item["has_standalone_module"] is True
        assert item["bridge_bound_standalone"] is True

    ok_cli, cli_json = mod_h.handle("audit-legacy", ["--json"])
    assert ok_cli is True
    assert json.loads(cli_json)["standalone_bound_count"] == 4

    status = bridge.ocean_modularized_services_status()
    for name in ("permissions", "config", "backup", "connector"):
        assert name in status
        assert status[name]["bound"] is True
        assert status[name]["standalone"] is True

    # Smoke-call each newly hot-wired standalone module
    p_mod = bridge.load_permissions_module()
    assert p_mod.PermissionPolicy(allow_rules=["Read(*)"]).evaluate("Read(a.txt)").allowed is True

    c_mod = bridge.load_config_module()
    assert c_mod.resolve_backend_config()["type"] == "ollama"

    b_mod = bridge.load_backup_module()
    assert "compute_sha256" in dir(b_mod)

    k_mod = bridge.load_connector_module()
    assert k_mod.compute_backoff_seconds(1, base_seconds=5.0) == 10.0
