# SPDX-License-Identifier: MIT
"""Tests für BACH CLI und bach_api.task Lease-Integration (BACH #1722, T793 LEASE 3/4)."""

import sqlite3
from pathlib import Path
import pytest

from hub.task import TaskHandler
from hub._services.task_lease import ensure_task_lease_schema


def _create_db(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'open',
            priority TEXT DEFAULT 'P3',
            category TEXT DEFAULT 'general',
            assigned_to TEXT DEFAULT 'user',
            created_by TEXT DEFAULT 'user',
            depends_on TEXT,
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT,
            due_date TEXT,
            source TEXT
        );

        CREATE TABLE IF NOT EXISTS task_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            field_changed TEXT,
            old_value TEXT,
            new_value TEXT,
            changed_by TEXT DEFAULT 'user',
            changed_at TEXT NOT NULL
        );
        """
    )
    ensure_task_lease_schema(conn)
    cur = conn.execute("INSERT INTO tasks (title, status) VALUES (?, ?)", ("CLI Test Task", "open"))
    tid = cur.lastrowid
    conn.commit()
    conn.close()
    return tid


def test_cli_lease_lifecycle(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "bach_test.db"
    tid = _create_db(db_path)

    # Handler instanziieren und _get_db monkeypatchen
    handler = TaskHandler(base_path=tmp_path)
    handler.db_path = db_path
    monkeypatch.setattr(handler, "_get_db", lambda: sqlite3.connect(db_path))

    # 1. bach task lease <tid> --by opus@ASUS-GEI --ttl M
    ok, msg = handler.handle("lease", [str(tid), "--by", "opus@ASUS-GEI", "--ttl", "M"])
    assert ok is True
    assert f"Task {tid} geleast an opus@ASUS-GEI" in msg
    assert "Lease-Capability:" in msg
    lease_id = msg.split("Lease-Capability: ")[1].strip()

    # 2. bach task lease-show <tid> --lease-id <uuid>
    ok, show_msg = handler.handle("lease-show", [str(tid), "--lease-id", lease_id])
    assert ok is True
    assert f"Task {tid}: Status=in_progress, Leased=True, Fence=1" in show_msg
    assert "[EIGENER LEASE BESTAETIGT]" in show_msg

    # 3. bach task lease-renew <tid> --lease-id <uuid> --fence 1
    ok, renew_msg = handler.handle("lease-renew", [str(tid), "--lease-id", lease_id, "--fence", "1"])
    assert ok is True
    assert "verlaengert" in renew_msg

    # 4. bach task lease-release <tid> --lease-id <uuid> --fence 1 --outcome done
    ok, rel_msg = handler.handle("lease-release", [str(tid), "--lease-id", lease_id, "--fence", "1", "--outcome", "done"])
    assert ok is True
    assert f"Task {tid} Lease freigegeben" in rel_msg

    # 5. Rücklesen: Task ist done
    ok, final_show = handler.handle("lease-show", [str(tid)])
    assert ok is True
    assert "Status=done, Leased=False" in final_show


def test_bach_api_lease_lifecycle(tmp_path: Path, monkeypatch):
    from bach_api import task as task_api

    db_path = tmp_path / "bach_api_test.db"
    tid = _create_db(db_path)

    # monkeypatche _connect auf task_api
    monkeypatch.setattr(task_api, "_connect", lambda: sqlite3.connect(db_path))

    # 1. lease_acquire
    ack = task_api.lease_acquire(tid, worker_id="gemini@ASUS-GEI", ttl_profile="S", intent="API Test")
    assert ack["granted"] is True
    assert ack["task_id"] == tid
    assert ack["fence"] == 1
    assert ack["worker_id"] == "gemini@ASUS-GEI"
    lease_id = ack["lease_id"]

    # 2. lease_read
    view = task_api.lease_read(tid, lease_id=lease_id)
    assert view["leased"] is True
    assert view["own"] is True
    assert view["holder"]["worker_id"] == "gemini@ASUS-GEI"

    # 3. lease_renew
    renewed = task_api.lease_renew(tid, lease_id=lease_id, fence=1)
    assert renewed["granted"] is True
    assert renewed["fence"] == 1

    # 4. lease_release
    released = task_api.lease_release(tid, lease_id=lease_id, fence=1, outcome="done", note="API test done")
    assert released["released"] is True
    assert released["status"] == "done"


def test_interop_cli_and_api(tmp_path: Path, monkeypatch):
    from bach_api import task as task_api

    db_path = tmp_path / "bach_interop_test.db"
    tid = _create_db(db_path)

    # 1. Acquire via CLI
    handler = TaskHandler(base_path=tmp_path)
    handler.db_path = db_path
    monkeypatch.setattr(handler, "_get_db", lambda: sqlite3.connect(db_path))

    ok, msg = handler.handle("lease", [str(tid), "--by", "interop-worker@ASUS-GEI", "--ttl", "M"])
    assert ok is True
    lease_id = msg.split("Lease-Capability: ")[1].strip()

    # 2. Read via bach_api
    monkeypatch.setattr(task_api, "_connect", lambda: sqlite3.connect(db_path))
    view = task_api.lease_read(tid, lease_id=lease_id)
    assert view["leased"] is True
    assert view["holder"]["worker_id"] == "interop-worker@ASUS-GEI"
    assert view["own"] is True
    assert view["fence"] == 1

    # 3. Renew via CLI
    ok, renew_msg = handler.handle("lease-renew", [str(tid), "--lease-id", lease_id, "--fence", "1"])
    assert ok is True

    # 4. Release via bach_api
    rel = task_api.lease_release(tid, lease_id=lease_id, fence=1, outcome="done", note="interop completed")
    assert rel["released"] is True
    assert rel["status"] == "done"

    # 5. CLI bestätigt Abschluss
    ok, final_show = handler.handle("lease-show", [str(tid)])
    assert ok is True
    assert "Status=done, Leased=False" in final_show
