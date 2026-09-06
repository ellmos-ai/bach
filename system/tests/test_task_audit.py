# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Direkte Unit-Tests fuer hub/task_audit.py (apply_task_field_changes).

Die Funktion wird von vier Aufrufern geteilt (system/gui/server.py,
system/gui/api/headless.py, system/hub/task.py, system/hub/_services/chat/
chat_runtime.py -- T-20260906-985973908, T-20260906-240256515,
T-20260906-833218904, T-20260906-382894453). Bisher nur indirekt ueber diese
Integrationstests abgedeckt; diese Datei testet die Kernlogik isoliert, inkl.
der 'done'/'completed'-Vokabular-Entscheidung, der Spalten-Allowlist (Reviewer-
Fund PR #22) und des clear_fields-Parameters (fuer task.py's _reopen).
"""

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.task_audit import (
    ALLOWED_COLUMNS,
    CLEARABLE_COLUMNS,
    COMPLETED_STATUSES,
    IN_PROGRESS_STATUSES,
    apply_task_field_changes,
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            title TEXT,
            status TEXT DEFAULT 'open',
            priority TEXT DEFAULT 'P3',
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE task_history (
            id INTEGER PRIMARY KEY,
            task_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            field_changed TEXT,
            old_value TEXT,
            new_value TEXT,
            changed_by TEXT DEFAULT 'user',
            changed_at TEXT NOT NULL
        );
        INSERT INTO tasks (id, title, status, priority) VALUES (1, 'T', 'open', 'P2');
        """
    )
    c.commit()
    return c


def _row(conn, task_id=1):
    return dict(conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())


def _history(conn, task_id=1):
    rows = conn.execute(
        "SELECT * FROM task_history WHERE task_id = ? ORDER BY id", (task_id,)
    ).fetchall()
    return [dict(r) for r in rows]


class TestNoOp:
    def test_empty_field_values_returns_false_and_writes_nothing(self, conn):
        existing = _row(conn)
        changed = apply_task_field_changes(conn, 1, existing, {})
        assert changed is False
        assert _history(conn) == []
        assert _row(conn)["updated_at"] is None  # kein UPDATE ausgefuehrt

    def test_same_value_again_updates_row_but_writes_no_history(self, conn):
        existing = _row(conn)
        changed = apply_task_field_changes(conn, 1, existing, {"status": "open"}, now="T1")
        assert changed is True  # UPDATE laeuft trotzdem (updated_at), nur keine History-Zeile
        assert _history(conn) == []
        assert _row(conn)["updated_at"] == "T1"


class TestStatusChangeHistory:
    def test_status_change_is_marked_as_status_change(self, conn):
        apply_task_field_changes(conn, 1, _row(conn), {"status": "in_progress"}, now="T1")
        rows = _history(conn)
        assert len(rows) == 1
        assert rows[0]["action"] == "status_change"
        assert rows[0]["old_value"] == "open"
        assert rows[0]["new_value"] == "in_progress"

    def test_non_status_field_is_marked_as_field_change(self, conn):
        apply_task_field_changes(conn, 1, _row(conn), {"priority": "P1"}, now="T1")
        rows = _history(conn)
        assert len(rows) == 1
        assert rows[0]["action"] == "field_change"
        assert rows[0]["field_changed"] == "priority"

    def test_changed_by_default_and_override(self, conn):
        apply_task_field_changes(conn, 1, _row(conn), {"priority": "P1"}, now="T1")
        assert _history(conn)[0]["changed_by"] == "api"  # Funktions-Default

        apply_task_field_changes(
            conn, 1, _row(conn), {"priority": "P4"}, changed_by="cli-task", now="T2"
        )
        assert _history(conn)[1]["changed_by"] == "cli-task"


class TestStartedAt:
    def test_in_progress_sets_started_at_once(self, conn):
        apply_task_field_changes(conn, 1, _row(conn), {"status": "in_progress"}, now="T1")
        assert _row(conn)["started_at"] == "T1"

        # Rueckfall und erneutes in_progress darf den Erststart nicht ueberschreiben.
        apply_task_field_changes(conn, 1, _row(conn), {"status": "open"}, now="T2")
        apply_task_field_changes(conn, 1, _row(conn), {"status": "in_progress"}, now="T3")
        assert _row(conn)["started_at"] == "T1"


class TestCompletedVocabulary:
    """T-20260906-833218904: 'done' (CLI task.py, chat_runtime.py, headless.py) und
    'completed' (server.py) sind zwei gewachsene Vokabulare fuer denselben Endzustand.

    ENTSCHEIDUNG (siehe PR/Ticket): MAPPEN statt VEREINHEITLICHEN. Eine Umbenennung auf
    einen gemeinsamen Wert wuerde eine Migration der PRODUKTIV-Tabelle `tasks` (Spalte
    `status`) verlangen und jeden Statusfilter in mind. vier Dateien (server.py, headless.py,
    task.py, chat_runtime.py) anfassen -- das ist keine Test-/Code-Aenderung mehr, sondern ein
    Dateneingriff, den kein Agent ohne Nutzerentscheidung fahren darf (CLAUDE.md: nie direkt
    auf bach.db, Migrationen brauchen Freigabe). Stattdessen behandelt COMPLETED_STATUSES
    beide Werte gleich (completed_at wird fuer beide gesetzt) -- keine Datenmigration,
    keine Aenderung an bestehenden Statusfiltern noetig. Diese Tests fixieren die
    Entscheidung, damit sie nicht versehentlich wieder auseinanderdriftet.
    """

    def test_both_vocabularies_are_recognized(self):
        assert COMPLETED_STATUSES == frozenset({"completed", "done"})

    @pytest.mark.parametrize("status_value", ["completed", "done"])
    def test_either_value_sets_completed_at(self, conn, status_value):
        apply_task_field_changes(conn, 1, _row(conn), {"status": status_value}, now="T1")
        assert _row(conn)["completed_at"] == "T1"

    def test_in_progress_is_not_treated_as_completed(self):
        assert IN_PROGRESS_STATUSES.isdisjoint(COMPLETED_STATUSES)


class TestAllowedColumns:
    """Reviewer-Fund PR #22 (merge-reviewer-bach22): field_values-Keys landen per
    f-string im UPDATE-Statement. Allowlist statt Vertrauen -- vor allem jetzt, wo
    mit task.py/chat_runtime.py mehr Aufrufer dazugekommen sind (T-20260906-833218904)."""

    def test_disallowed_column_in_field_values_raises(self, conn):
        with pytest.raises(ValueError, match="ALLOWED_COLUMNS"):
            apply_task_field_changes(conn, 1, _row(conn), {"id": 999})

    def test_sql_injection_attempt_as_column_name_raises(self, conn):
        """Ein Spaltenname ist keine Nutzereingabe in den bisherigen Aufrufern --
        die Allowlist ist Verteidigung in der Tiefe fuer den Fall, dass sich das
        aendert. Ein klassischer Injection-Versuch als 'Spaltenname' muss hart
        abgelehnt werden, nicht stillschweigend ins SQL wandern."""
        with pytest.raises(ValueError, match="ALLOWED_COLUMNS"):
            apply_task_field_changes(conn, 1, _row(conn), {"status = 'x'; DROP TABLE tasks;--": "y"})
        # Tabelle muss unversehrt sein.
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1

    def test_started_at_completed_at_not_settable_via_field_values(self, conn):
        """started_at/completed_at sind Ergebnis der Status-Uebergangslogik, nicht
        direkt ueber field_values setzbar -- nur ueber clear_fields loeschbar."""
        with pytest.raises(ValueError, match="ALLOWED_COLUMNS"):
            apply_task_field_changes(conn, 1, _row(conn), {"completed_at": "2026-01-01"})

    def test_all_currently_used_columns_are_allowed(self):
        """Regressionsschutz: jede Spalte, die server.py/headless.py/task.py
        tatsaechlich per field_values setzen, muss in der Allowlist stehen."""
        used_by_all_callers = {
            "title", "description", "priority", "status", "category",
            "assigned_to", "created_by", "depends_on",
        }
        assert used_by_all_callers <= ALLOWED_COLUMNS


class TestClearFields:
    """T-20260906-382894453: task.py's _reopen ('done' -> 'pending') muss
    completed_at wieder auf NULL setzen -- die urspruengliche Funktion konnte nur
    Zeitstempel SETZEN, nicht zuruecksetzen."""

    def test_clear_fields_sets_column_to_null(self, conn):
        apply_task_field_changes(conn, 1, _row(conn), {"status": "done"}, now="T1")
        assert _row(conn)["completed_at"] == "T1"

        apply_task_field_changes(
            conn, 1, _row(conn), {"status": "pending"},
            clear_fields=("completed_at",), now="T2",
        )
        assert _row(conn)["completed_at"] is None

    def test_clear_fields_writes_field_change_history_when_value_was_set(self, conn):
        apply_task_field_changes(conn, 1, _row(conn), {"status": "done"}, now="T1")
        apply_task_field_changes(
            conn, 1, _row(conn), {"status": "pending"},
            clear_fields=("completed_at",), changed_by="cli-task", now="T2",
        )
        rows = _history(conn)
        clear_row = next(r for r in rows if r["field_changed"] == "completed_at")
        assert clear_row["action"] == "field_change"
        assert clear_row["old_value"] == "T1"
        assert clear_row["new_value"] is None
        assert clear_row["changed_by"] == "cli-task"

    def test_clear_fields_no_history_row_when_already_null(self, conn):
        """War completed_at schon leer, ist das Loeschen kein Wertwechsel."""
        apply_task_field_changes(
            conn, 1, _row(conn), {"priority": "P1"},
            clear_fields=("completed_at",), now="T1",
        )
        rows = _history(conn)
        assert all(r["field_changed"] != "completed_at" for r in rows)

    def test_disallowed_clear_field_raises(self, conn):
        with pytest.raises(ValueError, match="CLEARABLE_COLUMNS"):
            apply_task_field_changes(conn, 1, _row(conn), {}, clear_fields=("status",))

    def test_clear_fields_alone_without_field_values_is_not_a_no_op(self, conn):
        apply_task_field_changes(conn, 1, _row(conn), {"status": "done"}, now="T1")
        changed = apply_task_field_changes(
            conn, 1, _row(conn), {}, clear_fields=("completed_at",), now="T2"
        )
        assert changed is True
        assert _row(conn)["completed_at"] is None

    def test_clearable_columns_are_the_timestamp_columns(self):
        assert CLEARABLE_COLUMNS == frozenset({"started_at", "completed_at"})
