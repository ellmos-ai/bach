# SPDX-License-Identifier: MIT
"""Tests für Trithon Lease-Integration und Fencing (BACH #1722, T793 LEASE 3/4)."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from hub._services.chat.slots_config import initialize_slots_config
from hub._services.task_lease import ensure_task_lease_schema
from hub._services.trithon.routing_contract import create_pending_contract
from hub._services.trithon_dispatch import SyntheticTicket, execute_intent_v1


TEST_ASSIGNMENT = {
    "agent_instance_id": "trithon-agent-01",
    "backend_id": "backend-local",
    "model_id": "model-noop",
    "slot_id": "buddha_always_on",
    "session_id": "session-lease-test",
    "initiated_by": "pytest",
}


def _create_test_db(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'open',
            priority TEXT DEFAULT 'P3',
            category TEXT DEFAULT 'trithon',
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
    cur = conn.execute(
        "INSERT INTO tasks (title, description, status) VALUES (?, ?, ?)",
        ("Test Trithon Lease Task", "payload", "open"),
    )
    task_id = cur.lastrowid
    conn.commit()
    conn.close()
    return task_id


@pytest.fixture
def trithon_ticket(tmp_path: Path):
    db_path = tmp_path / "tasks.db"
    ledger_path = tmp_path / "ledger.jsonl"
    slots_path = tmp_path / "slots.json"

    initialize_slots_config(str(slots_path))
    task_id = _create_test_db(db_path)

    ticket_id = "ticket-trithon-lease-001"
    create_pending_contract(ledger_path, ticket_id)

    return SyntheticTicket(
        ticket_id=ticket_id,
        ledger_path=ledger_path,
        db_path=db_path,
        slots_path=slots_path,
        task_id=task_id,
        intent={"action": "noop", "payload": "lease verified run"},
        host="host-trithon",
    )


def test_trithon_lease_success_and_evidence(trithon_ticket: SyntheticTicket):
    """Prüft, dass execute_intent_v1 den Task leaset, abschliesst und
    Fencing-Werte (lease_id, claim_fence) im ExecutionReceipt und Return abbildet."""
    result = execute_intent_v1(trithon_ticket, **TEST_ASSIGNMENT)

    assert result["success"] is True
    assert result["status"] == "done"
    assert "lease_id" in result
    assert result["fence"] == 1

    # DB-Prüfung: Status ist done, Lease-Spalten geleert, claim_fence bleibt
    conn = sqlite3.connect(trithon_ticket.db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (trithon_ticket.task_id,)).fetchone()
    conn.close()

    assert row["status"] == "done"
    assert row["claim_id"] is None
    assert row["claim_fence"] == 1

    # Ledger-Prüfung: Evidence im Receipt enthält Fencing-Felder
    ledger_lines = [json.loads(line) for line in trithon_ticket.ledger_path.read_text().splitlines() if line.strip()]
    done_entry = next(e for e in ledger_lines if e.get("status") == "done")
    evidence = done_entry.get("evidence", {})
    assert evidence.get("claim_fence") == 1
    assert evidence.get("lease_id") == result["lease_id"]
    assert evidence.get("worker_id") == f"{TEST_ASSIGNMENT['agent_instance_id']}@{trithon_ticket.host}"


def test_trithon_lease_stale_fence_fails_closed(trithon_ticket: SyntheticTicket, monkeypatch):
    """Wenn der Fence vor Abschluss manipuliert oder durch eine fremde Übernahme erhöht wird,
    muss execute_intent_v1 fail-closed abbrechen und darf den Task nicht auf done setzen."""
    from hub._services import trithon_dispatch

    orig_propose = trithon_dispatch.propose_outcome

    def tamper_fence_before_release(run, evidence):
        # Simuliere fremde Übernahme / Fence-Erhöhung in der DB vor Release
        conn = sqlite3.connect(trithon_ticket.db_path)
        conn.execute("UPDATE tasks SET claim_fence = claim_fence + 1 WHERE id = ?", (trithon_ticket.task_id,))
        conn.commit()
        conn.close()
        return orig_propose(run, evidence)

    monkeypatch.setattr(trithon_dispatch, "propose_outcome", tamper_fence_before_release)

    result = execute_intent_v1(trithon_ticket, **TEST_ASSIGNMENT)

    # Fail-closed
    assert result["success"] is False
    assert result["status"] == "release_failed"
    assert result["reason"] == "stale_fence"

    # Status in DB darf NICHT done sein!
    conn = sqlite3.connect(trithon_ticket.db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (trithon_ticket.task_id,)).fetchone()
    conn.close()
    assert row["status"] != "done"
