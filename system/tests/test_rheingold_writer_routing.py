"""Regressionstests: Rheingold Handler-first Writer-Routing.

Deckt ``TaskManager._propagate_to_rheingold_lead`` ab:
Writer-first-Aufruf gegen den Lead, kollisionssicherer Readback,
Provenienz-Schreibung (``source``/``creation_origin``) sowie Audit
in ``task_history``. Alle Fehlerpfade muessen fail-closed sein und
eine Auditzeile hinterlassen.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub import task as task_module  # noqa: E402
from hub.task import TaskManager  # noqa: E402


LEAD_URL = "http://lead"


# --------------------------------------------------------------------------
# Fixtures / Helfer
# --------------------------------------------------------------------------


def _make_conn() -> sqlite3.Connection:
    """In-Memory-DB mit minimalem Schema fuer die Routing-Logik."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            source TEXT,
            creation_origin TEXT,
            status TEXT,
            claimed_by TEXT,
            assigned_to TEXT,
            delegated_to TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE task_history (
            task_id INTEGER,
            action TEXT,
            field_changed TEXT,
            old_value TEXT,
            new_value TEXT,
            changed_by TEXT,
            changed_at TEXT
        )
        """
    )
    conn.commit()
    return conn


def _insert_task(conn, task_id=1, **columns):
    allowed = {"source", "creation_origin", "status", "claimed_by", "assigned_to", "delegated_to"}
    values = {k: v for k, v in columns.items() if k in allowed}
    names = ["id"] + list(values)
    placeholders = ", ".join("?" for _ in names)
    conn.execute(
        f"INSERT INTO tasks ({', '.join(names)}) VALUES ({placeholders})",
        [task_id] + list(values.values()),
    )
    conn.commit()


def _get_task(conn, task_id=1) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    assert row is not None
    return row


def _history(conn, task_id=1):
    return conn.execute(
        "SELECT * FROM task_history WHERE task_id = ? ORDER BY rowid",
        (task_id,),
    ).fetchall()


def _actions(conn, task_id=1):
    return [row["action"] for row in _history(conn, task_id)]


def _monkeypatch_lead(monkeypatch, *, mutate_result, readback_result):
    """Lead-Konfiguration und Remote-I/O ersetzen, Aufrufe mitschreiben."""
    calls = {"mutate": [], "readback": []}

    def fake_get_lead_config():
        return {"mode": "worker", "lead_url": LEAD_URL}

    def fake_get_rheingold_url():
        return LEAD_URL

    def fake_mutate(base_url, task_id, payload, timeout=5.0, **kwargs):
        calls["mutate"].append((base_url, task_id, payload))
        return mutate_result

    def fake_readback(base_url, task_id, timeout=3.0, **kwargs):
        calls["readback"].append((base_url, task_id))
        return readback_result

    monkeypatch.setattr(task_module, "get_lead_config", fake_get_lead_config)
    monkeypatch.setattr(task_module, "get_rheingold_url", fake_get_rheingold_url)
    monkeypatch.setattr(task_module, "mutate_task_on_rheingold", fake_mutate)
    monkeypatch.setattr(task_module, "readback_task_from_rheingold", fake_readback)
    return calls


def _call(conn, task_id=1, payload=None):
    """Ungebundener Aufruf: ``self`` wird vom neuen Code nicht genutzt."""
    row = _get_task(conn, task_id)
    return TaskManager._propagate_to_rheingold_lead(
        None, conn, task_id, row, payload or {"assigned_to": "worker-1"}
    )


# --------------------------------------------------------------------------
# (a) lokale Row nicht remote-verwaltet -> kein Routing
# --------------------------------------------------------------------------


def test_local_row_without_provenance_is_not_routed(monkeypatch):
    calls = _monkeypatch_lead(
        monkeypatch,
        mutate_result=(True, {"assigned_to": "worker-1"}),
        readback_result={"assigned_to": "worker-1"},
    )
    conn = _make_conn()
    _insert_task(conn, source="draft:task-1", creation_origin="local", status="pending")

    assert _call(conn) is None
    assert calls["mutate"] == []
    assert _history(conn) == []


# --------------------------------------------------------------------------
# (b) Lead-Modus nicht "worker" -> kein Routing
# --------------------------------------------------------------------------


def test_non_worker_mode_is_not_routed(monkeypatch):
    calls = _monkeypatch_lead(
        monkeypatch,
        mutate_result=(True, {"assigned_to": "worker-1"}),
        readback_result={"assigned_to": "worker-1"},
    )
    monkeypatch.setattr(
        task_module,
        "get_lead_config",
        lambda: {"mode": "isolated", "lead_url": LEAD_URL},
    )
    conn = _make_conn()
    _insert_task(
        conn, source="rheingold:http://lead", creation_origin="remote", status="pending"
    )

    assert _call(conn) is None
    assert calls["mutate"] == []
    assert _history(conn) == []


# --------------------------------------------------------------------------
# (c) Lead-URL nicht ermittelbar -> BLOCKED + Audit
# --------------------------------------------------------------------------


def test_missing_lead_url_blocks_and_audits(monkeypatch):
    calls = _monkeypatch_lead(
        monkeypatch,
        mutate_result=(True, {"assigned_to": "worker-1"}),
        readback_result={"assigned_to": "worker-1"},
    )
    monkeypatch.setattr(task_module, "get_rheingold_url", lambda: None)
    conn = _make_conn()
    _insert_task(
        conn, source="rheingold:http://lead", creation_origin="remote", status="pending"
    )

    ok, message = _call(conn)

    assert ok is False
    assert message.startswith("[BLOCKED]")
    assert calls["mutate"] == []
    actions = _actions(conn)
    assert any("blocked" in action for action in actions), actions


# --------------------------------------------------------------------------
# (d) Writer-Fehler -> ERROR + Audit (auch bei nicht-dict Body)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("mutate_result", [
    (False, "[ERROR] lead down"),
    (False, None),
    (False, "raw text response"),
])
def test_mutate_failure_errors_and_audits(monkeypatch, mutate_result):
    calls = _monkeypatch_lead(
        monkeypatch,
        mutate_result=mutate_result,
        readback_result={"assigned_to": "worker-1"},
    )
    conn = _make_conn()
    _insert_task(
        conn, source="rheingold:http://lead", creation_origin="remote", status="pending"
    )

    ok, message = _call(conn)

    assert ok is False
    assert message.startswith("[ERROR]")
    assert len(calls["mutate"]) == 1
    actions = _actions(conn)
    assert any("error" in action for action in actions), actions
    # Provenienz bleibt unangetastet, Aufgabe bleibt remote-verwaltet.
    row = _get_task(conn)
    assert row["source"] == "rheingold:http://lead"
    assert row["creation_origin"] == "remote"


# --------------------------------------------------------------------------
# (e) Readback leer -> COLLISION + Audit
# --------------------------------------------------------------------------


def test_empty_readback_is_collision(monkeypatch):
    calls = _monkeypatch_lead(
        monkeypatch,
        mutate_result=(True, {"assigned_to": "worker-1"}),
        readback_result=None,
    )
    conn = _make_conn()
    _insert_task(
        conn, source="rheingold:http://lead", creation_origin="remote", status="pending"
    )

    ok, message = _call(conn)

    assert ok is False
    assert message.startswith("[COLLISION]")
    assert len(calls["readback"]) == 1
    actions = _actions(conn)
    assert any("collision" in action for action in actions), actions


# --------------------------------------------------------------------------
# (f) Readback weicht im Feld ab -> COLLISION + Audit
# --------------------------------------------------------------------------


def test_field_mismatch_is_collision(monkeypatch):
    _monkeypatch_lead(
        monkeypatch,
        mutate_result=(True, {"assigned_to": "worker-1"}),
        readback_result={"assigned_to": "someone-else"},
    )
    conn = _make_conn()
    _insert_task(
        conn, source="rheingold:http://lead", creation_origin="remote", status="pending"
    )

    ok, message = _call(conn)

    assert ok is False
    assert message.startswith("[COLLISION]")
    actions = _actions(conn)
    assert any("collision" in action for action in actions), actions


# --------------------------------------------------------------------------
# (g) Erfolgsfall: Provenienz + Audit
# --------------------------------------------------------------------------


def test_success_writes_provenance_and_audit(monkeypatch):
    calls = _monkeypatch_lead(
        monkeypatch,
        mutate_result=(True, {"assigned_to": "worker-1"}),
        readback_result={"assigned_to": "worker-1"},
    )
    conn = _make_conn()
    _insert_task(conn, source="promoted:draft:task-1", creation_origin="local", status="pending")

    ok, remote = _call(conn, payload={"assigned_to": "worker-1"})

    assert ok is True
    assert remote == {"assigned_to": "worker-1"}
    assert len(calls["mutate"]) == 1
    assert len(calls["readback"]) == 1

    row = _get_task(conn)
    assert row["source"] == f"rheingold:{LEAD_URL}"
    assert row["creation_origin"] == "remote"

    history = _history(conn)
    assert history, "Erfolgsfall muss Auditzeilen schreiben"
    assert all(entry["changed_by"] == "rheingold-lead" for entry in history)
    changed_fields = {entry["field_changed"] for entry in history}
    assert "source" in changed_fields
    assert "creation_origin" in changed_fields


def test_success_keeps_existing_rheingold_prefix(monkeypatch):
    _monkeypatch_lead(
        monkeypatch,
        mutate_result=(True, {"assigned_to": "worker-1"}),
        readback_result={"assigned_to": "worker-1"},
    )
    conn = _make_conn()
    _insert_task(
        conn,
        source="rheingold:http://other-lead",
        creation_origin="local",
        status="pending",
    )

    ok, _remote = _call(conn)

    assert ok is True
    row = _get_task(conn)
    # Bestehende Rheingold-Provenienz wird nicht ueberschrieben.
    assert row["source"] == "rheingold:http://other-lead"
    assert row["creation_origin"] == "remote"
