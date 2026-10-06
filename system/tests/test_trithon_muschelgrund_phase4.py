"""Tests fuer Trithon Phase 4: kuratierte Muschelgrund-Projektion.

Deckt ab:
  a) Blocked-Receipts erzeugen keine Facts; Outbox existiert (leer).
  b) Evidence-Redaktion ueber privacy_allowlist samt Provenienz.
  c) Voll-Allowlist (redacted=False) und fail-closed ohne Allowlist.
  d) Idempotenz ueber Dedupe-Key (zweiter Lauf ohne Duplikate).
  e) Outbox-Retry nach Zustellfehler (Write-Ahead, kein Rollback).
  f) Epochenwechsel via reset_epoch (Provenienz-Epoche, kein Re-Projizieren).
"""

import json

from hub._services.trithon.muschelgrund import project_ledger, reset_epoch
from hub._services.trithon.routing_contract import (
    ExecutionReceipt,
    claim_contract,
    create_pending_contract,
    record_receipt,
)

OCCURRED_AT = "2026-09-28T10:00:00+00:00"


def _finish(ledger, tid, sig, status="done", evidence=None):
    """Schreibt einen kompletten Vertragszyklus (pending -> claimed -> receipt)."""
    create_pending_contract(ledger, tid)
    claim_contract(ledger, tid, "host1", "runner1", assignment_id="a1", run_id="r1")
    record_receipt(
        ledger,
        tid,
        ExecutionReceipt(
            signature=sig,
            status=status,
            executed_by="e",
            actual_provider="p",
            actual_model="m",
            occurred_at=OCCURRED_AT,
            evidence=evidence if evidence is not None else {"note": "n"},
        ),
    )


def _read_facts(state_dir):
    path = state_dir / "facts.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _read_outbox(state_dir):
    path = state_dir / "outbox.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_blocked_receipts_werden_nicht_projiziert(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    state_dir = tmp_path / "state"
    _finish(ledger, "t1", "sig-x1", status="blocked")

    stats = project_ledger(ledger, "t1", state_dir=state_dir)

    assert stats["facts_new"] == 0
    assert stats["skipped_duplicates"] == 0
    assert stats["facts_total"] == 0
    assert not (state_dir / "facts.jsonl").exists()
    # Outbox wird immer (atomar) geschrieben, auch wenn sie leer ist.
    outbox = state_dir / "outbox.jsonl"
    assert outbox.exists()
    assert outbox.read_text().strip() == ""


def test_evidence_redaktion_mit_allowlist(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    state_dir = tmp_path / "state"
    _finish(ledger, "t1", "sig-x1", evidence={"a": 1, "secret": "x"})

    stats = project_ledger(ledger, "t1", state_dir=state_dir, privacy_allowlist={"a"})

    assert stats["facts_new"] == 1
    facts = _read_facts(state_dir)
    assert len(facts) == 1
    fact = facts[0]
    assert fact["evidence"] == {"a": 1}
    assert fact["redacted"] is True
    assert fact["fact_id"] == "t1:sig-x1"
    assert fact["kind"] == "fact"
    assert fact["assignment_id"] == "a1"
    assert fact["run_id"] == "r1"
    assert fact["provenance"]["source"] == "routing_contract.ledger"
    assert fact["provenance"]["signature"] == "sig-x1"
    assert fact["provenance"]["status"] == "done"
    assert fact["provenance"]["epoch"] == 0
    assert fact["provenance"]["ledger_line"] > 0


def test_allowlist_voll_und_fail_closed_ohne_allowlist(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _finish(ledger, "t1", "sig-x1", evidence={"a": 1})

    # Alle Evidence-Schluessel erlaubt -> keine Redaktion.
    state_full = tmp_path / "state_full"
    stats = project_ledger(
        ledger, "t1", state_dir=state_full, privacy_allowlist={"a", "secret"}
    )
    assert stats["facts_new"] == 1
    facts = _read_facts(state_full)
    assert facts[0]["evidence"] == {"a": 1}
    assert facts[0]["redacted"] is False

    # Ohne Allowlist: fail-closed (leere Evidence, redacted=True).
    state_none = tmp_path / "state_none"
    stats = project_ledger(ledger, "t1", state_dir=state_none, privacy_allowlist=None)
    assert stats["facts_new"] == 1
    facts = _read_facts(state_none)
    assert facts[0]["evidence"] == {}
    assert facts[0]["redacted"] is True


def test_projektion_idempotent_ohne_deliver(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    state_dir = tmp_path / "state"
    _finish(ledger, "t1", "sig-x1")

    stats1 = project_ledger(ledger, "t1", state_dir=state_dir, deliver=None)
    assert stats1["facts_new"] == 1
    assert stats1["delivered"] == 0
    assert stats1["outbox_pending"] == 1

    stats2 = project_ledger(ledger, "t1", state_dir=state_dir, deliver=None)
    assert stats2["facts_new"] == 0
    assert stats2["skipped_duplicates"] == 1
    assert stats2["facts_total"] == 1

    facts = _read_facts(state_dir)
    assert len(facts) == 1


def test_outbox_retry_nach_zustellfehler(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    state_dir = tmp_path / "state"
    _finish(ledger, "t1", "sig-x1")

    def failing_deliver(_record):
        raise RuntimeError("boom")

    stats1 = project_ledger(ledger, "t1", state_dir=state_dir, deliver=failing_deliver)
    # Write-Ahead: Fact bleibt trotz Zustellfehler persistiert.
    assert stats1["facts_new"] == 1
    assert stats1["delivered"] == 0
    assert stats1["outbox_pending"] == 1
    outbox = _read_outbox(state_dir)
    assert len(outbox) == 1
    assert outbox[0]["attempts"] == 1
    assert outbox[0]["delivered_at"] is None
    assert outbox[0]["last_error"].startswith("RuntimeError")

    # Zweiter Lauf: Outbox-Replay stellt nach, kein erneutes Projizieren.
    collected = []
    stats2 = project_ledger(ledger, "t1", state_dir=state_dir, deliver=collected.append)
    assert len(collected) == 1
    assert collected[0]["fact_id"] == "t1:sig-x1"
    assert stats2["facts_new"] == 0
    assert stats2["skipped_duplicates"] == 1
    assert stats2["delivered"] == 1
    assert stats2["outbox_pending"] == 0
    outbox = _read_outbox(state_dir)
    assert outbox[0]["delivered_at"] is not None
    assert outbox[0]["last_error"] is None
    # Write-Ahead ohne Rollback: weiterhin genau ein Fact.
    assert len(_read_facts(state_dir)) == 1


def test_epochenwechsel_via_reset_epoch(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    state_dir = tmp_path / "state"
    _finish(ledger, "t1", "sig-x1")

    stats1 = project_ledger(ledger, "t1", state_dir=state_dir)
    assert stats1["facts_new"] == 1
    assert stats1["epoch"] == 0
    facts = _read_facts(state_dir)
    assert facts[0]["provenance"]["epoch"] == 0

    new_epoch = reset_epoch(state_dir, reason="test")
    assert new_epoch == 1
    cursor = json.loads((state_dir / "cursor.json").read_text())
    assert cursor["epoch"] == 1
    # Epochenmarker wird append-only protokolliert.
    epochs = [
        json.loads(line)
        for line in (state_dir / "epochs.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert len(epochs) == 1
    assert epochs[0]["epoch"] == 1
    assert epochs[0]["reason"] == "test"
    assert epochs[0]["marked_at"]

    # Neues Ticket in derselben Ledger-Datei (altes Ticket ist finalisiert).
    _finish(ledger, "t2", "sig-x2")
    stats2 = project_ledger(ledger, "t2", state_dir=state_dir)
    assert stats2["facts_new"] == 1
    assert stats2["skipped_duplicates"] == 0
    assert stats2["epoch"] == 1

    facts = _read_facts(state_dir)
    assert len(facts) == 2
    assert facts[1]["fact_id"] == "t2:sig-x2"
    assert facts[1]["provenance"]["epoch"] == 1

    # Alte Receipts duerfen ueber Epochen hinweg nie erneut projiziert werden.
    stats3 = project_ledger(ledger, "t1", state_dir=state_dir)
    assert stats3["facts_new"] == 0
    assert stats3["skipped_duplicates"] == 1
