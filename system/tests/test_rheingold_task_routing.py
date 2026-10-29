# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Lead-first Writer-Routing-Tests (T-1694).

Belege: _propagate_to_rheingold_lead hub/task.py:853-876; Aufrufstellen
task.py:1016 (edit), task.py:1260 (done), task.py:1369 (claim),
task.py:1906 (assign); _delete ohne Routing (Regression): task.py:1785-1805;
remote-Kriterium: hub/rheingold.py:390-394.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.task import TaskHandler


def _create_tasks_table(conn):
    conn.execute("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'P3',
            category TEXT DEFAULT 'general',
            description TEXT DEFAULT '',
            assigned_to TEXT,
            delegated_to TEXT,
            depends_on TEXT,
            created_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE task_history (
            id INTEGER PRIMARY KEY,
            task_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            field_changed TEXT,
            old_value TEXT,
            new_value TEXT,
            changed_by TEXT DEFAULT 'user',
            changed_at TEXT NOT NULL
        )
    """)
    conn.commit()


def _add_remote_columns(conn):
    conn.execute("ALTER TABLE tasks ADD COLUMN source TEXT")
    conn.execute("ALTER TABLE tasks ADD COLUMN creation_origin TEXT")
    conn.commit()


def _mark_remote(conn, ids, source="rheingold:lead:1694"):
    for tid in ids:
        conn.execute("UPDATE tasks SET source = ? WHERE id = ?", (source, tid))
    conn.commit()


@pytest.fixture
def remote_env(tmp_path, monkeypatch):
    """Minimal env (Muster test_task_handler.fake_task_env) + remote-Spalten."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(db_path)
    _create_tasks_table(conn)
    _add_remote_columns(conn)
    conn.execute(
        "INSERT INTO tasks (id, title, status, priority, category, created_at) "
        "VALUES (1, 'Lead owned task', 'pending', 'P2', 'test', '2026-02-01 10:00')"
    )
    conn.execute(
        "INSERT INTO tasks (id, title, status, priority, category, created_at) "
        "VALUES (2, 'Second lead task', 'pending', 'P3', 'test', '2026-02-02 10:00')"
    )
    conn.commit()
    _mark_remote(conn, [1, 2])
    conn.close()
    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
    return tmp_path, db_path


@pytest.fixture
def remote_handler(remote_env):
    base, _db_path = remote_env
    return TaskHandler(base)


def _task_row(db_path, task_id):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _history_rows(db_path, task_id):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM task_history WHERE task_id = ? ORDER BY id", (task_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _patch_lead_success(monkeypatch):
    calls = []
    payload_ref = {"payload": None}
    monkeypatch.setattr("hub.task.get_lead_config", lambda: {"mode": "worker"})
    monkeypatch.setattr("hub.task.get_rheingold_url", lambda: "http://lead.example")

    def fake_mutate(*args):
        calls.append(("mutate", args[1], dict(args[2])))
        payload_ref["payload"] = dict(args[2])
        return True, {"ok": 1}

    def fake_readback(*args):
        calls.append(("readback", args[1], None))
        return {k: str(v) for k, v in payload_ref["payload"].items()}

    monkeypatch.setattr("hub.task.mutate_task_on_rheingold", fake_mutate)
    monkeypatch.setattr("hub.task.readback_task_from_rheingold", fake_readback)
    return calls


def _patch_lead_fail(monkeypatch):
    calls = []
    monkeypatch.setattr("hub.task.get_lead_config", lambda: {"mode": "worker"})
    monkeypatch.setattr("hub.task.get_rheingold_url", lambda: "http://lead.example")

    def fake_mutate(*args):
        calls.append(("mutate", args[1], dict(args[2])))
        return False, {"error": "boom"}

    def fake_readback(*args):
        calls.append(("readback", args[1], None))
        return {}

    monkeypatch.setattr("hub.task.mutate_task_on_rheingold", fake_mutate)
    monkeypatch.setattr("hub.task.readback_task_from_rheingold", fake_readback)
    return calls


def _stage(calls):
    return [c[0] for c in calls]


# ── edit ──────────────────────────────────────────────────────────

def test_edit_lead_success_routes_to_lead(remote_handler, remote_env, monkeypatch):
    base, db_path = remote_env
    calls = _patch_lead_success(monkeypatch)
    ok, output = remote_handler.handle("edit", ["1", "--title", "Neuer Titel"])
    assert ok is True
    assert "[OK]" in output
    assert "bearbeitet" in output
    assert _task_row(db_path, 1)["title"] == "Neuer Titel"
    assert calls[0] == ("mutate", 1, {"title": "Neuer Titel"})
    assert _stage(calls) == ["mutate", "readback"]
    assert len(_history_rows(db_path, 1)) >= 1


def test_edit_fails_closed_on_lead_mutation_error(remote_handler, remote_env, monkeypatch):
    base, db_path = remote_env
    calls = _patch_lead_fail(monkeypatch)
    ok, output = remote_handler.handle("edit", ["1", "--title", "Neuer Titel"])
    assert ok is False
    assert "[ERROR]" in output
    assert "boom" in output
    assert _task_row(db_path, 1)["title"] == "Lead owned task"
    assert _history_rows(db_path, 1) == []
    assert _stage(calls) == ["mutate"]


# ── done ──────────────────────────────────────────────────────────

def test_done_lead_success_routes_to_lead(remote_handler, remote_env, monkeypatch):
    base, db_path = remote_env
    calls = _patch_lead_success(monkeypatch)
    ok, output = remote_handler.handle("done", ["1"])
    assert ok is True
    assert "[OK]" in output
    row = _task_row(db_path, 1)
    assert row["status"] == "done"
    assert row.get("completed_at") is not None
    assert calls[0] == ("mutate", 1, {"status": "done"})
    assert _stage(calls) == ["mutate", "readback"]
    assert len(_history_rows(db_path, 1)) >= 1


def test_done_fails_closed_on_lead_mutation_error(remote_handler, remote_env, monkeypatch):
    base, db_path = remote_env
    calls = _patch_lead_fail(monkeypatch)
    ok, output = remote_handler.handle("done", ["1"])
    assert ok is True  # Multi-ID-Pfad sammelt Fail-Text in results
    assert "[ERROR]" in output
    assert "boom" in output
    row = _task_row(db_path, 1)
    assert row["status"] == "pending"
    assert row.get("completed_at") is None
    assert _history_rows(db_path, 1) == []
    assert _stage(calls) == ["mutate"]


# ── claim ─────────────────────────────────────────────────────────

def test_claim_lead_success_routes_to_lead(remote_handler, remote_env, monkeypatch):
    base, db_path = remote_env
    calls = _patch_lead_success(monkeypatch)
    ok, output = remote_handler.handle("claim", ["1", "--by", "Gemini"])
    assert ok is True
    assert "[OK]" in output
    assert "beansprucht" in output
    assert _task_row(db_path, 1).get("claimed_by") == "Gemini"
    assert calls[0] == ("mutate", 1, {"claimed_by": "Gemini"})


def test_claim_fails_closed_on_lead_mutation_error(remote_handler, remote_env, monkeypatch):
    base, db_path = remote_env
    calls = _patch_lead_fail(monkeypatch)
    ok, output = remote_handler.handle("claim", ["1", "--by", "Gemini"])
    assert ok is False
    assert "[ERROR]" in output
    assert "boom" in output
    assert _task_row(db_path, 1)["status"] == "pending"
    assert _history_rows(db_path, 1) == []
    assert _stage(calls) == ["mutate"]


# ── assign ────────────────────────────────────────────────────────

def test_assign_lead_success_routes_to_lead(remote_handler, remote_env, monkeypatch):
    base, db_path = remote_env
    calls = _patch_lead_success(monkeypatch)
    ok, output = remote_handler.handle("assign", ["1", "--to", "Gemini"])
    assert ok is True
    assert "[OK]" in output
    assert "->" in output
    row = _task_row(db_path, 1)
    assert row["assigned_to"] == "Gemini"
    assert row["delegated_to"] == "Gemini"
    assert calls[0] == ("mutate", 1, {"assigned_to": "Gemini"})
    assert len(_history_rows(db_path, 1)) >= 1


def test_assign_fails_closed_on_lead_mutation_error(remote_handler, remote_env, monkeypatch):
    base, db_path = remote_env
    calls = _patch_lead_fail(monkeypatch)
    ok, output = remote_handler.handle("assign", ["1", "--to", "Gemini"])
    assert ok is True  # Multi-ID-Pfad: [BLOCKED] in results
    assert "[BLOCKED]" in output
    row = _task_row(db_path, 1)
    assert row["assigned_to"] is None
    assert row["delegated_to"] is None
    assert _history_rows(db_path, 1) == []
    assert _stage(calls) == ["mutate"]


# ── delete (Regression: kein Routing, kein NameError bei Remote-Rows) ──

def test_delete_multi_ids_on_remote_rows_regression(remote_handler, remote_env):
    base, db_path = remote_env
    ok, output = remote_handler.handle("delete", ["1", "2"])
    assert ok is True
    assert "geloescht" in output
    assert output.count("geloescht") == 2
    conn = sqlite3.connect(str(db_path))
    remaining = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    conn.close()
    assert remaining == 0
    ok2, output2 = remote_handler.handle("delete", ["1"])
    assert ok2 is True
    assert "[WARN]" in output2
    assert "nicht gefunden" in output2