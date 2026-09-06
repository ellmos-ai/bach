# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Direkte Unit-Tests fuer hub/task_audit.py (apply_task_field_changes).

Die Funktion wird inzwischen von vier Aufrufern geteilt (system/gui/server.py,
system/gui/api/headless.py, system/hub/task.py, system/hub/_services/chat/
chat_runtime.py -- T-20260906-985973908, T-20260906-240256515, T-20260906-833218904).
Bisher nur indirekt ueber diese vier Integrationstests abgedeckt; dieser Datei testet
die Kernlogik isoliert, inkl. der 'done'/'completed'-Vokabular-Entscheidung.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.task_audit import (
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
