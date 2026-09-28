"""Tests für Trithon / open-ocean T3 Seam- und Routing-Verträge.

Deckt ab (Task #1489):
  1. Legacy-API:
     - create_pending_contract
     - claim_contract
     - record_receipt
     - read_ledger
  2. Neutral-API:
     - TaskTransportContract, WorkItem, ExecutorReceipt Aliase
     - Kompatibilität und Austauschbarkeit der Datenstrukturen
  3. Host-Partitioning & Isolation:
     - Tickets auf unterschiedlichen Hosts beanspruchen (z. B. mac-studio vs. asus-laptop)
     - Schutz vor Fremdübernahme (ContractAlreadyClaimed bei abweichendem Host/Runner)
     - Idempotenter Re-Claim durch denselben Host/Runner
     - Separate Ledger-Dateien / Partitions-Routing
  4. End-to-End-Projektion in Muschelgrund:
     - Fakten- und Lesson-Klassifizierung für receipts aus verteilten Hosts
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from hub._services.trithon.muschelgrund import project_ledger
from hub._services.trithon.routing_contract import (
    ContractAlreadyClaimed,
    ContractNotFound,
    ExecutionReceipt,
    ExecutorReceipt,
    InvalidReceipt,
    LedgerEntry,
    RoutingError,
    TaskTransportContract,
    WorkItem,
    claim_contract,
    create_pending_contract,
    read_ledger,
    record_receipt,
)


class TestLegacyRoutingContractAPI:
    """Prüft die Kernoperationen der Transportzustandsmaschine."""

    def test_complete_lifecycle(self, tmp_path: Path):
        ledger = tmp_path / "tickets.ledger"
        ticket_id = "TASK-1001"

        # 1. Pending anlegen
        p = create_pending_contract(ledger, ticket_id, host="*", runner="*")
        assert p.ticket_id == ticket_id
        assert p.status == "pending"

        # 2. Claimen
        c = claim_contract(
            ledger,
            ticket_id,
            host="mac-studio",
            runner="buddha-worker-1",
            assignment_id="asg-01",
            run_id="run-01",
        )
        assert c.status == "claimed"
        assert c.host == "mac-studio"
        assert c.runner == "buddha-worker-1"
        assert c.assignment_id == "asg-01"

        # 3. Abschließen mit Receipt
        receipt = ExecutionReceipt(
            signature="sig-sha256-abc123",
            status="done",
            executed_by="buddha-worker-1",
            actual_provider="ollama",
            actual_model="qwen3.8:27b-mlx",
            occurred_at="2026-09-28T20:00:00Z",
            evidence={"exit_code": 0, "summary": "Task erfolgreich ausgeführt"},
        )
        done_entry = record_receipt(ledger, ticket_id, receipt)
        assert done_entry.status == "done"
        assert done_entry.signature == "sig-sha256-abc123"

        # 4. Ledger lesen und Reihenfolge verifizieren
        entries = read_ledger(ledger, ticket_id)
        assert len(entries) == 3
        assert [e.status for e in entries] == ["pending", "claimed", "done"]

    def test_claim_nonexistent_raises_not_found(self, tmp_path: Path):
        ledger = tmp_path / "empty.ledger"
        with pytest.raises(ContractNotFound):
            claim_contract(ledger, "NONEXISTENT", host="h1", runner="r1")

    def test_record_receipt_without_claim_raises_error(self, tmp_path: Path):
        ledger = tmp_path / "pending_only.ledger"
        create_pending_contract(ledger, "TASK-1002")

        receipt = ExecutionReceipt(
            signature="sig-1002",
            status="done",
            executed_by="r",
            actual_provider="p",
            actual_model="m",
            occurred_at="2026-09-28T20:00:00Z",
            evidence={"ok": True},
        )
        with pytest.raises(RoutingError, match="muss 'claimed' sein"):
            record_receipt(ledger, "TASK-1002", receipt)

    def test_invalid_receipt_validation(self, tmp_path: Path):
        ledger = tmp_path / "tickets.ledger"
        create_pending_contract(ledger, "TASK-1003")
        claim_contract(ledger, "TASK-1003", host="h1", runner="r1")

        # Ungültiger Status (weder done noch blocked)
        bad_receipt = ExecutionReceipt(
            signature="sig-bad",
            status="in_progress",
            executed_by="r",
            actual_provider="p",
            actual_model="m",
            occurred_at="2026-09-28T20:00:00Z",
            evidence={"ok": True},
        )
        with pytest.raises(InvalidReceipt, match="status muss 'done' oder 'blocked' sein"):
            record_receipt(ledger, "TASK-1003", bad_receipt)


class TestNeutralAPICompatibility:
    """Prüft Neutral-API Typ-Aliase und Interoperabilität."""

    def test_type_aliases_identity(self):
        assert TaskTransportContract is LedgerEntry
        assert WorkItem is LedgerEntry
        assert ExecutorReceipt is ExecutionReceipt

    def test_instantiation_via_neutral_types(self, tmp_path: Path):
        ledger = tmp_path / "neutral.ledger"
        ticket_id = "NEUTRAL-01"

        create_pending_contract(ledger, ticket_id)
        claimed = claim_contract(ledger, ticket_id, host="host-x", runner="runner-y")

        # Sicherstellen, dass claimed Instanz von WorkItem / TaskTransportContract ist
        assert isinstance(claimed, WorkItem)
        assert isinstance(claimed, TaskTransportContract)

        neutral_receipt = ExecutorReceipt(
            signature="neutral-sig-999",
            status="done",
            executed_by="runner-y",
            actual_provider="codex",
            actual_model="o4-mini",
            occurred_at="2026-09-28T20:30:00Z",
            evidence={"artifacts": ["data.json"]},
        )
        res = record_receipt(ledger, ticket_id, neutral_receipt)
        assert isinstance(res, WorkItem)
        assert res.signature == "neutral-sig-999"


class TestHostPartitioningAndIsolation:
    """Prüft das Verhalten bei mehreren Hosts und Runnern."""

    def test_different_host_cannot_claim_already_claimed_ticket(self, tmp_path: Path):
        ledger = tmp_path / "cluster.ledger"
        ticket_id = "TASK-CROSS-HOST"

        create_pending_contract(ledger, ticket_id)
        # Host A (mac-studio) beansprucht das Ticket
        claim_contract(ledger, ticket_id, host="mac-studio", runner="ollama-daemon")

        # Host B (asus-laptop) versucht denselben Claim -> abgelehnt
        with pytest.raises(ContractAlreadyClaimed, match="bereits von mac-studio/ollama-daemon claimed"):
            claim_contract(ledger, ticket_id, host="asus-laptop", runner="antigravity-worker")

    def test_same_host_and_runner_reclaim_is_idempotent(self, tmp_path: Path):
        ledger = tmp_path / "idempotent.ledger"
        ticket_id = "TASK-IDEMPOTENT"

        create_pending_contract(ledger, ticket_id)
        c1 = claim_contract(ledger, ticket_id, host="mac-studio", runner="buddha-slot-1")
        c2 = claim_contract(ledger, ticket_id, host="mac-studio", runner="buddha-slot-1")

        assert c1.ticket_id == c2.ticket_id
        assert c1.status == c2.status
        assert c1.host == c2.host
        assert c1.runner == c2.runner
        # Es darf keine zweite Zeile im Ledger erzeugt worden sein
        entries = read_ledger(ledger, ticket_id)
        assert len(entries) == 2  # pending + claimed

    def test_directory_partitioned_ledgers_per_ticket(self, tmp_path: Path):
        ledger_dir = tmp_path / "ledgers_by_host"
        ledger_dir.mkdir()

        # Mehrere Tickets in einem Verzeichnis werden in separate Dateien <ticket_id>.ledger abgelegt
        t1 = "HOST1-TICKET-A"
        t2 = "HOST2-TICKET-B"

        create_pending_contract(ledger_dir, t1, host="mac-studio")
        create_pending_contract(ledger_dir, t2, host="asus-laptop")

        claim_contract(ledger_dir, t1, host="mac-studio", runner="r1")
        claim_contract(ledger_dir, t2, host="asus-laptop", runner="r2")

        assert (ledger_dir / f"{t1}.ledger").exists()
        assert (ledger_dir / f"{t2}.ledger").exists()

        entries_t1 = read_ledger(ledger_dir, t1)
        entries_t2 = read_ledger(ledger_dir, t2)

        assert len(entries_t1) == 2
        assert entries_t1[-1].host == "mac-studio"
        assert len(entries_t2) == 2
        assert entries_t2[-1].host == "asus-laptop"


class TestMuschelgrundIntegrationWithDistributedReceipts:
    """Verifiziert die Projektion von Host-Receipts in Fakten und Lessons."""

    def test_project_receipts_with_lessons_and_facts(self, tmp_path: Path):
        ledger = tmp_path / "multi_host.ledger"
        state_dir = tmp_path / "muschelgrund_state"

        # Ticket 1: Normaler Fakt von Host A
        t1 = "T-FACT-01"
        create_pending_contract(ledger, t1)
        claim_contract(ledger, t1, host="mac-studio", runner="worker-alpha")
        record_receipt(
            ledger,
            t1,
            ExecutionReceipt(
                signature="sig-fact-01",
                status="done",
                executed_by="worker-alpha",
                actual_provider="ollama",
                actual_model="qwen3.8:27b-mlx",
                occurred_at="2026-09-28T21:00:00Z",
                evidence={"data_processed": 42},
            ),
        )

        # Ticket 2: Lesson (mit lesson_learned) von Host B
        t2 = "T-LESSON-02"
        create_pending_contract(ledger, t2)
        claim_contract(ledger, t2, host="asus-laptop", runner="worker-beta")
        record_receipt(
            ledger,
            t2,
            ExecutionReceipt(
                signature="sig-lesson-02",
                status="done",
                executed_by="worker-beta",
                actual_provider="claude",
                actual_model="claude-3-7-sonnet",
                occurred_at="2026-09-28T21:05:00Z",
                evidence={"lesson": "Fail-closed bei fehlenden API-Keys beachten", "score": 10},
            ),
        )

        # Projektion von Ticket 1
        stats1 = project_ledger(ledger, t1, state_dir=state_dir, privacy_allowlist={"data_processed"})
        assert stats1["facts_new"] == 1

        # Projektion von Ticket 2
        stats2 = project_ledger(ledger, t2, state_dir=state_dir, privacy_allowlist={"lesson", "score"})
        assert stats2["facts_new"] == 1

        # Facts-Datei prüfen
        facts_path = state_dir / "facts.jsonl"
        assert facts_path.exists()
        lines = [json.loads(line) for line in facts_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) == 2

        f1 = next(f for f in lines if f["ticket_id"] == t1)
        assert f1["kind"] == "fact"
        assert f1["evidence"]["data_processed"] == 42

        f2 = next(f for f in lines if f["ticket_id"] == t2)
        assert f2["kind"] == "lesson"
        assert f2["evidence"]["lesson"] == "Fail-closed bei fehlenden API-Keys beachten"
