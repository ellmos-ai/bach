# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Task #2065: offizieller, auditierter Setter fuer ``tasks.tags``.

Deckt den gemeinsamen Choke-Point (``normalize_task_tags`` / ``apply_task_field_changes``),
den fenced Lease-Update-Pfad und die HTTP-PUT-Routen ab. Kein direkter SQLite-Bypass:
geschrieben wird ausschliesslich ueber die produktiven Schreibpfade.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.task_lease import (  # noqa: E402
    LeaseConfig,
    LeaseValidationError,
    acquire_lease,
    update_lease,
)
from hub.task_audit import (  # noqa: E402
    ALLOWED_COLUMNS,
    MAX_TAGS,
    apply_task_field_changes,
    normalize_task_tags,
)

try:
    from fastapi.testclient import TestClient
    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False

T0 = datetime(2026, 10, 18, 6, 0, 0, tzinfo=timezone.utc)
CFG = LeaseConfig(creator_window_seconds=0)


def _create_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.executescript("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            priority TEXT DEFAULT 'P3',
            status TEXT DEFAULT 'pending',
            category TEXT DEFAULT 'general',
            tags TEXT,
            assigned_to TEXT DEFAULT 'user',
            created_by TEXT DEFAULT 'user',
            depends_on TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            started_at TEXT,
            completed_at TEXT,
            due_date TEXT,
            claimed_by TEXT,
            claimed_at TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE task_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            field_changed TEXT,
            old_value TEXT,
            new_value TEXT,
            changed_by TEXT DEFAULT 'user',
            changed_at TEXT NOT NULL
        );
        INSERT INTO tasks (id, title) VALUES (1, 'Testtask');
    """)
    conn.commit()
    conn.close()


@pytest.fixture
def db_path(tmp_path) -> Path:
    path = tmp_path / "data" / "bach.db"
    _create_db(path)
    return path


@pytest.fixture
def conn(db_path):
    c = sqlite3.connect(str(db_path), timeout=10.0)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def _row(conn, task_id=1) -> dict:
    return dict(conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())


def _tags_history(conn, task_id=1) -> list[tuple]:
    return [tuple(r) for r in conn.execute(
        "SELECT old_value, new_value, changed_by FROM task_history "
        "WHERE task_id = ? AND field_changed = 'tags' ORDER BY id", (task_id,))]


# ---------------------------------------------------------------- Normalisierer

@pytest.mark.parametrize("value, expected", [
    (["githubbot-ocean"], '["githubbot-ocean"]'),
    ("githubbot-ocean", '["githubbot-ocean"]'),
    (" a , b ,a", '["a","b"]'),                       # trimmen + Duplikate
    ('["x","y"]', '["x","y"]'),                       # JSON-Array bleibt kanonisch
    (("T793", "worker-ops"), '["T793","worker-ops"]'),
    (["Größe:ä/1+2.x_y"], '["Größe:ä/1+2.x_y"]'),     # Unicode-Wortzeichen erlaubt
    (None, None), ("", None), ("   ", None), ([], None), ("[]", None),
])
def test_normalize_canonical_form(value, expected):
    assert normalize_task_tags(value) == expected


def test_normalize_is_idempotent():
    once = normalize_task_tags("b, a")
    assert normalize_task_tags(once) == once


@pytest.mark.parametrize("value", [
    ["has space"], ["x" * 65], [""], ["-leading"], [1], [None], ["a,b;c"],
    "[not json", 5, {"a": 1}, ["a"] * 2 + [f"t{i}" for i in range(MAX_TAGS)],
    "a,,b",
])
def test_normalize_rejects_invalid(value):
    with pytest.raises(ValueError):
        normalize_task_tags(value)


# ------------------------------------------------------------ Audit-Choke-Point

def test_tags_is_an_allowed_column():
    assert "tags" in ALLOWED_COLUMNS


def test_apply_writes_canonical_tags_with_history(conn):
    changed = apply_task_field_changes(conn, 1, _row(conn), {"tags": "githubbot-ocean, T793"}, changed_by="claude-code@ASUS-GEI")
    conn.commit()
    assert changed is True
    assert _row(conn)["tags"] == '["githubbot-ocean","T793"]'
    assert _tags_history(conn) == [(None, '["githubbot-ocean","T793"]', "claude-code@ASUS-GEI")]


def test_apply_same_tags_in_other_spelling_writes_no_history(conn):
    apply_task_field_changes(conn, 1, _row(conn), {"tags": ["a", "b"]})
    conn.commit()
    apply_task_field_changes(conn, 1, _row(conn), {"tags": "a,b"})
    conn.commit()
    assert len(_tags_history(conn)) == 1


def test_apply_clears_tags_with_null(conn):
    apply_task_field_changes(conn, 1, _row(conn), {"tags": ["a"]})
    conn.commit()
    apply_task_field_changes(conn, 1, _row(conn), {"tags": None})
    conn.commit()
    assert _row(conn)["tags"] is None
    assert _tags_history(conn)[-1][1] is None


def test_apply_invalid_tags_leaves_row_untouched(conn):
    before = _row(conn)
    with pytest.raises(ValueError):
        apply_task_field_changes(conn, 1, before, {"title": "neu", "tags": ["bad tag"]})
    conn.rollback()
    assert _row(conn) == before
    assert _tags_history(conn) == []


# --------------------------------------------------------------- Lease-Update

def _lease(conn):
    ack = acquire_lease(conn, 1, worker_id="claude-code@ASUS-GEI", host="ASUS-GEI",
                        request_id="req-" + uuid.uuid4().hex, now=T0, config=CFG).payload
    return ack


def test_lease_update_sets_tags_audited_and_versioned(conn):
    ack = _lease(conn)
    result = update_lease(conn, 1, lease_id=ack["lease_id"], fence=ack["fence"], task_version=ack["task_version"],
                          changes={"tags": ["githubbot-ocean"]}, config=CFG, now=T0 + timedelta(seconds=5))
    assert result.http_status == 200, result.payload
    assert result.payload["fields"] == ["tags"]
    assert result.payload["task_version"] != ack["task_version"]
    assert _row(conn)["tags"] == '["githubbot-ocean"]'
    assert _tags_history(conn) == [(None, '["githubbot-ocean"]', "claude-code@ASUS-GEI")]
    assert conn.execute("SELECT COUNT(*) FROM task_history WHERE action = 'lease_update'").fetchone()[0] == 1


def test_lease_update_rejects_invalid_tags(conn):
    ack = _lease(conn)
    before = _row(conn)
    with pytest.raises(LeaseValidationError):
        update_lease(conn, 1, lease_id=ack["lease_id"], fence=ack["fence"], task_version=ack["task_version"],
                     changes={"tags": ["bad tag"]}, config=CFG, now=T0 + timedelta(seconds=5))
    assert _row(conn) == before


def test_lease_update_denies_stale_fence_without_writing(conn):
    ack = _lease(conn)
    result = update_lease(conn, 1, lease_id=ack["lease_id"], fence=ack["fence"] + 1, task_version=ack["task_version"],
                          changes={"tags": ["x"]}, config=CFG, now=T0 + timedelta(seconds=5))
    assert result.http_status == 409
    assert _row(conn)["tags"] is None


# ------------------------------------------------------------------ HTTP-PUT

@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="fastapi nicht installiert")
class TestPutRoutes:
    @pytest.fixture
    def client(self, db_path, tmp_path, monkeypatch):
        import gui.server as srv
        monkeypatch.setattr(srv, "BACH_DB", db_path)
        monkeypatch.setattr(srv, "USER_DB", db_path)
        monkeypatch.setattr(srv, "DATA_DIR", tmp_path / "data")
        monkeypatch.setattr(srv, "BACH_DIR", tmp_path)
        monkeypatch.setattr(srv, "GUI_DIR", tmp_path / "gui")
        monkeypatch.setattr(srv, "validate_token",
                            lambda token: {"id": 1, "name": "test-device"} if token == "tags-fixture" else None)
        return TestClient(srv.app, raise_server_exceptions=False,
                          headers={"Authorization": "Bearer tags-fixture"})

    def test_put_sets_lists_and_clears_tags(self, client, db_path):
        r = client.put("/api/tasks/1", json={"tags": ["githubbot-ocean", "worker-ops"], "changed_by": "api-test"})
        assert r.status_code == 200, r.text
        with sqlite3.connect(str(db_path)) as c:
            assert c.execute("SELECT tags FROM tasks WHERE id = 1").fetchone()[0] == '["githubbot-ocean","worker-ops"]'
            assert c.execute("SELECT new_value, changed_by FROM task_history WHERE field_changed = 'tags'").fetchall() == [
                ('["githubbot-ocean","worker-ops"]', "api-test")]
        # GET liefert die kanonische Form zurueck (Readback)
        assert client.get("/api/tasks/1").json()["tags"] == '["githubbot-ocean","worker-ops"]'
        assert client.put("/api/tasks/1", json={"tags": None}).status_code == 200
        assert client.get("/api/tasks/1").json()["tags"] is None

    def test_put_without_tags_keeps_existing_tags(self, client, db_path):
        client.put("/api/tasks/1", json={"tags": "keep"})
        assert client.put("/api/tasks/1", json={"priority": "P1"}).status_code == 200
        assert client.get("/api/tasks/1").json()["tags"] == '["keep"]'

    def test_put_invalid_tags_is_422_and_changes_nothing(self, client, db_path):
        r = client.put("/api/tasks/1", json={"title": "soll nicht greifen", "tags": ["bad tag"]})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "tags_invalid"
        snap = client.get("/api/tasks/1").json()
        assert snap["title"] == "Testtask" and snap["tags"] is None
