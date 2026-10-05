# -*- coding: utf-8 -*-
"""Pytest-Suite für den Trithon Dispatch-Layer (Phase 3).

Diese Tests validieren den No-op-E2E-Pfad von execute_intent_v1 über
atomares Claiming, Besetzungsnachweis, Receipt-Erzeugung bis zum Ledger-
Abschluss. Alle Zustände werden lokal in einer temporären SQLite-DB und einer
JSON-Lines-Ledger-Datei geprüft.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from hub._services.chat.slots_config import initialize_slots_config
from hub._services.trithon.transport_contract import create_pending_contract
from hub._services.trithon_dispatch import SyntheticTicket, execute_intent_v1

TEST_ASSIGNMENT = {
    "agent_instance_id": "agent-dispatch-test-001",
    "backend_id": "backend-local",
    "model_id": "model-noop",
    "slot_id": "buddha_always_on",
    "session_id": "session-dispatch-test",
    "initiated_by": "pytest",
}


def _create_test_db(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'open',
            priority TEXT DEFAULT 'P3',
            category TEXT DEFAULT 'general',
            assigned_to TEXT DEFAULT 'user',
            created_by TEXT DEFAULT 'user',
            depends_on TEXT,
            claim_host TEXT,
            claim_started_at TEXT,
            claim_finished_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            due_date TEXT,
            claimed_by TEXT,
            claimed_at TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
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
    conn.execute(
        "INSERT INTO tasks (title, description, status, priority, category) "
        "VALUES (?, ?, ?, ?, ?)",
        ("open dispatch task", "test payload", "open", "P3", "trithon"),
    )
    task_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return task_id


@pytest.fixture
def dispatch_setup(tmp_path: Path):
    db_path = tmp_path / "tasks.db"
    ledger_path = tmp_path / "ledger.jsonl"
    slots_path = tmp_path / "slots.json"

    initialize_slots_config(str(slots_path))
    task_id = _create_test_db(db_path)

    work_item_id = "work-item-dispatch-001"
    create_pending_contract(ledger_path, work_item_id)

    ticket = SyntheticTicket(
        work_item_id=work_item_id,
        ledger_path=ledger_path,
        db_path=db_path,
        slots_path=slots_path,
        task_id=task_id,
        intent={"action": "noop", "payload": "success run"},
    )
    return ticket


def _ledger_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _task_status(db_path: Path, task_id: int) -> str | None:
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT status FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def test_execute_intent_v1_e2e_success(dispatch_setup: SyntheticTicket):
    """E2E: Ein offener Task wird durch execute_intent_v1 erfolgreich
    abgeschlossen. DB-Status und Ledger-Endstatus müssen done sein."""
    ticket = dispatch_setup
    result = execute_intent_v1(ticket, **TEST_ASSIGNMENT)

    assert result["success"] is True
    assert result["status"] == "done"
    assert result.get("receipt_signature"), "Receipt-Signatur muss vorhanden sein"

    assert _task_status(ticket.db_path, ticket.task_id) == "done"

    ledger = _ledger_entries(ticket.ledger_path)
    assert any(entry.get("status") == "done" for entry in ledger)
    assert any(entry.get("status") == "claimed" for entry in ledger)


def test_execute_intent_v1_double_submit(dispatch_setup: SyntheticTicket):
    """Double-Submit: Ein bereits abgeschlossener Task kann nicht erneut
    geclaimed werden. Zweiter Aufruf liefert success=False mit
    status=claim_failed."""
    ticket = dispatch_setup

    first = execute_intent_v1(ticket, **TEST_ASSIGNMENT)
    assert first["success"] is True
    assert first["status"] == "done"

    second = execute_intent_v1(ticket, **TEST_ASSIGNMENT)
    assert second["success"] is False
    assert second["status"] == "claim_failed"


def test_execute_intent_v1_invalid_role(tmp_path: Path):
    """Ungültige role_id: Der Ausführer besitzt keine Rechte für den
    Task-Pfad. execute_intent_v1 muss success=False und
    status=role_denied zurückgeben."""
    db_path = tmp_path / "tasks.db"
    ledger_path = tmp_path / "ledger.jsonl"
    slots_path = tmp_path / "slots.json"

    initialize_slots_config(str(slots_path))
    task_id = _create_test_db(db_path)

    work_item_id = "work-item-role-denied"
    create_pending_contract(ledger_path, work_item_id)

    ticket = SyntheticTicket(
        work_item_id=work_item_id,
        ledger_path=ledger_path,
        db_path=db_path,
        slots_path=slots_path,
        task_id=task_id,
        intent={"action": "noop", "payload": "should be denied"},
    )

    result = execute_intent_v1(
        ticket,
        role_id="nonexistent_role",
        **TEST_ASSIGNMENT,
    )
    assert result["success"] is False
    assert result["status"] == "role_denied"
