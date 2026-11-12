# SPDX-License-Identifier: MIT
"""Unit tests for PB-6 Follow-up: Module Automations Adapter and GET /api/automations.

Ticket: T-20261107-206833979
Verifies:
1. `list_module_automations`:
   - Extraction from `automation_routines`, `scheduler_jobs`, and `automation_triggers` tables.
   - Extraction from `.SYNC/_automations` manifests.
   - Stable IDs formatted as `<source>:<id>`.
   - All 9 required contract fields: `id`, `name`, `title`, `schedule`, `last_run`, `last_result`,
     `next_run`, `enabled`, `source`.
   - Resilience against missing or corrupted DBs.
2. FastAPI endpoint `GET /api/automations`:
   - Returns 200 OK without token requirement (exempt public path).
   - Expected payload: `{"ok": True, "source": "automation-master", "automations": [...], "items": [...], "count": ...}`.
   - Filtering via `?source=...`.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gui import server
from gui.server import app
from hub._services.automation_master_adapter import list_module_automations


def _init_test_db(db_path: Path) -> None:
    """Create a sample sqlite database with automation tables."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS automation_routines (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        type TEXT NOT NULL,
        condition TEXT NOT NULL,
        condition_config TEXT,
        action TEXT NOT NULL,
        action_config TEXT,
        interval TEXT,
        last_run TEXT,
        next_run TEXT,
        priority INTEGER DEFAULT 50,
        is_active BOOLEAN DEFAULT 1,
        updated_at TEXT
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS scheduler_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT,
        job_type TEXT NOT NULL,
        schedule TEXT,
        command TEXT NOT NULL,
        is_active INTEGER DEFAULT 0,
        last_run TIMESTAMP,
        next_run TIMESTAMP,
        last_result TEXT
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS automation_triggers (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        phrases TEXT NOT NULL,
        skill_name TEXT,
        action TEXT NOT NULL,
        priority INTEGER DEFAULT 50,
        is_active BOOLEAN DEFAULT 1,
        updated_at TEXT
    );
    """)

    # Populate routines
    cursor.execute("""
    INSERT INTO automation_routines (id, name, type, condition, action, interval, last_run, next_run, is_active)
    VALUES (1, 'morning_briefing', 'periodic', 'always', 'generate_briefing', 'daily', '2026-11-08T08:00:00Z', '2026-11-09T08:00:00Z', 1);
    """)
    cursor.execute("""
    INSERT INTO automation_routines (id, name, type, condition, action, interval, last_run, next_run, is_active)
    VALUES (2, 'evening_cleanup', 'periodic', 'always', 'cleanup_temp', 'alle 24 Std.', NULL, '2026-11-08T22:00:00Z', 0);
    """)

    # Populate scheduler jobs
    cursor.execute("""
    INSERT INTO scheduler_jobs (id, name, description, job_type, schedule, command, is_active, last_run, next_run, last_result)
    VALUES (101, 'db_vacuum', 'Wöchentliches DB-Vakuum', 'cron', '0 3 * * 0', 'bach vacuum', 1, '2026-11-02T03:00:00Z', '2026-11-09T03:00:00Z', 'success');
    """)
    cursor.execute("""
    INSERT INTO scheduler_jobs (id, name, description, job_type, schedule, command, is_active, last_run, next_run, last_result)
    VALUES (102, 'sync_external', 'Externer Abgleich', 'interval', 'alle 1 Std.', 'bach sync', 1, '2026-11-08T12:00:00Z', '2026-11-08T13:00:00Z', 'failed');
    """)

    # Populate triggers
    cursor.execute("""
    INSERT INTO automation_triggers (id, name, phrases, action, is_active)
    VALUES (10, 'on_file_changed', '["file_change"]', 'scan', 1);
    """)

    conn.commit()
    conn.close()


def test_adapter_empty_db(tmp_path: Path) -> None:
    """An empty sqlite db without automation tables returns no items without raising."""
    empty_db = tmp_path / "empty.db"
    conn = sqlite3.connect(str(empty_db))
    conn.execute("CREATE TABLE foo (id INT);")
    conn.commit()
    conn.close()

    items = list_module_automations(
        empty_db,
        include_sync=False,
        include_manifests=False,
        include_package=False,
    )
    assert items == []


def test_adapter_automation_routines(tmp_path: Path) -> None:
    """Extraction from automation_routines produces stable IDs and all required fields."""
    db_path = tmp_path / "test.db"
    _init_test_db(db_path)

    items = list_module_automations(
        db_path,
        include_sync=False,
        include_manifests=False,
        include_package=False,
    )
    routines = [it for it in items if it["source"] == "automation-routine"]
    assert len(routines) == 2

    first = next(it for it in routines if it["name"] == "morning_briefing")
    assert first["id"] == "automation-routine:1"
    assert first["title"] == "morning_briefing"
    assert first["schedule"] == "daily"
    assert first["last_run"] == "2026-11-08T08:00:00Z"
    assert first["next_run"] == "2026-11-09T08:00:00Z"
    assert first["enabled"] is True
    assert first["source"] == "automation-routine"

    second = next(it for it in routines if it["name"] == "evening_cleanup")
    assert second["id"] == "automation-routine:2"
    assert second["schedule"] == "alle 24 Std."
    assert second["last_run"] is None
    assert second["next_run"] == "2026-11-08T22:00:00Z"
    assert second["enabled"] is False


def test_adapter_scheduler_jobs(tmp_path: Path) -> None:
    """Extraction from scheduler_jobs produces stable IDs, description as title and last_result."""
    db_path = tmp_path / "test.db"
    _init_test_db(db_path)

    items = list_module_automations(
        db_path,
        include_sync=False,
        include_manifests=False,
        include_package=False,
    )
    jobs = [it for it in items if it["source"] == "scheduler"]
    assert len(jobs) == 2

    vacuum = next(it for it in jobs if it["name"] == "db_vacuum")
    assert vacuum["id"] == "scheduler:101"
    assert vacuum["title"] == "Wöchentliches DB-Vakuum"
    assert vacuum["schedule"] == "0 3 * * 0"
    assert vacuum["last_run"] == "2026-11-02T03:00:00Z"
    assert vacuum["next_run"] == "2026-11-09T03:00:00Z"
    assert vacuum["last_result"] == "success"
    assert vacuum["enabled"] is True

    sync_job = next(it for it in jobs if it["name"] == "sync_external")
    assert sync_job["id"] == "scheduler:102"
    assert sync_job["last_result"] == "failed"


def test_adapter_automation_triggers(tmp_path: Path) -> None:
    """Extraction from automation_triggers produces event schedule and stable ID."""
    db_path = tmp_path / "test.db"
    _init_test_db(db_path)

    items = list_module_automations(
        db_path,
        include_sync=False,
        include_manifests=False,
        include_package=False,
    )
    triggers = [it for it in items if it["source"] == "automation-trigger"]
    assert len(triggers) == 1
    trig = triggers[0]
    assert trig["id"] == "automation-trigger:10"
    assert trig["name"] == "on_file_changed"
    assert trig["schedule"] == "bei Ereignis"
    assert trig["enabled"] is True


def test_adapter_sync_dir(tmp_path: Path) -> None:
    """Extraction from .SYNC/_automations manifests."""
    sync_dir = tmp_path / "_automations"
    sync_dir.mkdir(parents=True)
    manifest = sync_dir / "laptop.json"
    manifest.write_text(
        json.dumps({
            "schema": "ellmos.automation-adoption.v1",
            "slot": "laptop",
            "zellen": [
                {
                    "id": "pages-karten-maintainer@antigravity",
                    "bereich": "1. Pages-Karten",
                    "zeitplan": "0 6 * * *",
                    "status": "enabled",
                    "letzter_nachweis": "2026-09-23T01:01:25Z pushed=true",
                },
                {
                    "id": "paused-job@codex",
                    "bereich": "2. Pausiert",
                    "zeitplan": "0 18 * * *",
                    "status": "disabled",
                    "letzter_nachweis": None,
                },
            ],
        }),
        encoding="utf-8",
    )

    items = list_module_automations(
        db_path=None,
        include_sync=True,
        sync_dir=sync_dir,
        include_manifests=False,
        include_package=False,
    )
    assert len(items) == 2
    first = next(it for it in items if it["name"] == "pages-karten-maintainer@antigravity")
    assert first["id"] == "sync:pages-karten-maintainer@antigravity"
    assert first["title"] == "1. Pages-Karten"
    assert first["schedule"] == "0 6 * * *"
    assert first["enabled"] is True
    assert first["last_run"] == "2026-09-23T01:01:25Z pushed=true"
    assert first["last_result"] == "success"

    paused = next(it for it in items if it["name"] == "paused-job@codex")
    assert paused["id"] == "sync:paused-job@codex"
    assert paused["enabled"] is False


def test_adapter_stable_ids_and_required_contract_fields(tmp_path: Path) -> None:
    """Every single item strictly conforms to the required fields and <source>:<id> format."""
    db_path = tmp_path / "test.db"
    _init_test_db(db_path)

    sync_dir = tmp_path / "_automations"
    sync_dir.mkdir(parents=True)
    manifest = sync_dir / "ideapad.json"
    manifest.write_text(
        json.dumps({
            "schema": "ellmos.automation-adoption.v1",
            "slot": "ideapad",
            "zellen": [
                {
                    "id": "ideapad-worker@gemini",
                    "bereich": "Worker Check",
                    "zeitplan": "alle 30 Min.",
                    "status": "active",
                    "letzter_nachweis": "2026-11-08T10:00:00Z ok",
                }
            ],
        }),
        encoding="utf-8",
    )

    items = list_module_automations(
        db_path=db_path,
        include_sync=True,
        sync_dir=sync_dir,
        include_manifests=False,
        include_package=False,
    )
    assert len(items) == 6  # 2 routines + 2 jobs + 1 trigger + 1 sync

    required_keys = {
        "id",
        "name",
        "title",
        "schedule",
        "last_run",
        "last_result",
        "next_run",
        "enabled",
        "source",
    }

    seen_ids = set()
    for item in items:
        # Check required fields
        for key in required_keys:
            assert key in item, f"Missing required key '{key}' in item: {item}"

        # Stable ID must match <source>:<id>
        assert ":" in item["id"], f"Item ID '{item['id']}' does not contain ':' delimiter"
        prefix, ident = item["id"].split(":", 1)
        assert prefix == item["source"], f"Item ID prefix '{prefix}' does not match source '{item['source']}'"
        assert len(ident) > 0, f"Item ID identifier is empty: {item['id']}"

        # Check unique IDs
        assert item["id"] not in seen_ids, f"Duplicate item ID detected: {item['id']}"
        seen_ids.add(item["id"])

        # Name and title must be non-empty strings
        assert isinstance(item["name"], str) and item["name"].strip()
        assert isinstance(item["title"], str) and item["title"].strip()

        # Enabled must be bool
        assert isinstance(item["enabled"], bool)


def test_adapter_default_source_override(tmp_path: Path) -> None:
    """Using default_source sets the source and prefix uniformly."""
    db_path = tmp_path / "test.db"
    _init_test_db(db_path)

    items = list_module_automations(
        db_path,
        include_sync=False,
        include_manifests=False,
        include_package=False,
        default_source="module",
    )
    assert len(items) > 0
    for item in items:
        assert item["source"] == "module"
        assert item["id"].startswith("module:")


def test_adapter_resilience_missing_and_corrupt(tmp_path: Path) -> None:
    """Missing and corrupt DBs are handled fail-soft without exceptions."""
    nonexistent = tmp_path / "does_not_exist.db"
    items = list_module_automations(
        nonexistent,
        include_sync=False,
        include_manifests=False,
        include_package=False,
    )
    assert items == []

    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"NOT A SQLITE FILE HELLO")
    items_corrupt = list_module_automations(
        corrupt,
        include_sync=False,
        include_manifests=False,
        include_package=False,
    )
    assert items_corrupt == []


def test_fastapi_endpoint_get_automations(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """FastAPI endpoint GET /api/automations returns ok, source, items, automations and count."""
    test_db = tmp_path / "bach.db"
    _init_test_db(test_db)
    monkeypatch.setattr(server, "BACH_DB", test_db)

    client = TestClient(app)

    # 1. Unauthenticated request to /api/automations (exempt public path)
    response = client.get("/api/automations")
    assert response.status_code == 200
    data = response.json()

    assert data.get("ok") is True
    assert data.get("source") == "automation-master"
    assert "automations" in data
    assert "items" in data
    assert "count" in data
    assert data["automations"] == data["items"]
    assert data["count"] == len(data["automations"])
    assert data["count"] >= 5

    # Check contracts on items returned by API
    for item in data["items"]:
        assert ":" in item["id"]
        prefix, _ = item["id"].split(":", 1)
        assert prefix == item["source"]
        assert "schedule" in item
        assert "last_run" in item
        assert "last_result" in item
        assert "next_run" in item
        assert "enabled" in item
        assert "source" in item
        assert "name" in item
        assert "title" in item

    # 2. Filter by source query parameter
    res_filtered = client.get("/api/automations?source=scheduler")
    assert res_filtered.status_code == 200
    filtered_data = res_filtered.json()
    assert filtered_data.get("ok") is True
    assert filtered_data["count"] == 2
    for item in filtered_data["items"]:
        assert item["source"] == "scheduler"
        assert item["id"].startswith("scheduler:")
