# -*- coding: utf-8 -*-
"""Tests für SALT-Lease-Contract: Fencing, TTL, Fail-closed, Readback.

Task #1722: Claim-Readback über ≥ 1 BACH-Client UND Trithon.
Alle Tests in ``tmp_path`` (pytest fixture) – KEIN Produktiv-Claim.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hub._services.trithon.transport_contract import (
    ContractAlreadyClaimed,
    ContractNotFound,
    ExecutionReceipt,
    LedgerEntry,
    _append_line,
    _ensure_dir,
    _ledger_path,
    read_ledger,
    record_receipt,
)
from hub._services.trithon.lease_contract import (
    TTL_PROFILE_SECONDS,
    LeaseEntry,
    claim_lease,
    release_lease,
    renew_lease,
)

# ------------------------------------------------------------------ #
#  Konstanten
# ------------------------------------------------------------------ #

A_HOST = "mac-studio"
A_RUNNER = "agy-opus"
B_HOST = "idle-w2"
B_RUNNER = "agy-opus"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _past(seconds_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def _future(seconds_ahead: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds_ahead)).isoformat()


def _write_pending(ledger_dir: Path, task_id: str) -> None:
    """Schreibt einen ``pending``-Ledger-Eintrag für *task_id*."""
    lp = _ledger_path(ledger_dir, task_id)
    _ensure_dir(lp)
    entry = LedgerEntry(
        work_item_id=task_id,
        status="pending",
        host="",
        runner="",
        occurred_at=_now(),
    )
    _append_line(lp, entry)


# ------------------------------------------------------------------ #
#  T1 – Erst-Claim
# ------------------------------------------------------------------ #

class TestLeaseClaim:
    """Grundlegende Claim-Tests."""

    def test_t1_first_claim_succeeds(self, tmp_path: Path) -> None:
        """A claimt Task-1 mit fence=1 → OK; Readback bestätigt."""
        _write_pending(tmp_path, "task-1")
        lease = claim_lease(
            str(tmp_path), "task-1", A_HOST, A_RUNNER,
            lease_id="L-001", fence=1, ttl_profile="M",
        )
        assert lease.status == "claimed"
        assert lease.fence == 1
        assert lease.host == A_HOST
        assert lease.runner == A_RUNNER
        assert lease.lease_id == "L-001"
        assert lease.ttl_profile == "M"
        assert lease.expires_at is not None

        # Readback über read_ledger
        entries = read_ledger(str(tmp_path), "task-1")
        claimed = [e for e in entries if e.status == "claimed"]
        assert len(claimed) == 1
        assert claimed[0].host == A_HOST
        assert claimed[0].fence == 1
        assert claimed[0].lease_id == "L-001"

    def test_t2_foreign_claim_blocked(self, tmp_path: Path) -> None:
        """B claimt Task-1 (bereits von A) → ``ContractAlreadyClaimed``."""
        _write_pending(tmp_path, "task-1")
        claim_lease(
            str(tmp_path), "task-1", A_HOST, A_RUNNER,
            lease_id="L-001", fence=1, ttl_profile="M",
        )
        with pytest.raises(ContractAlreadyClaimed):
            claim_lease(
                str(tmp_path), "task-1", B_HOST, B_RUNNER,
                lease_id="L-002", fence=1, ttl_profile="M",
            )

    def test_t3_expired_foreign_fail_closed(self, tmp_path: Path) -> None:
        """A claimt mit abgelaufenem TTL → B ist fail-closed."""
        _write_pending(tmp_path, "task-2")
        # A claimt mit now in der Vergangenheit → expires_at liegt in der Vergangenheit
        past = _past(3600)
        claim_lease(
            str(tmp_path), "task-2", A_HOST, A_RUNNER,
            lease_id="L-100", fence=1, ttl_profile="S", now=past,
        )
        # B versucht jetzt → fail-closed (abgelaufen + fremd)
        with pytest.raises(ContractAlreadyClaimed):
            claim_lease(
                str(tmp_path), "task-2", B_HOST, B_RUNNER,
                lease_id="L-101", fence=2, ttl_profile="M",
            )

    def test_t4_reclaim_higher_fence(self, tmp_path: Path) -> None:
        """A re-claimt Task-3 mit fence=2 > fence=1 → OK."""
        _write_pending(tmp_path, "task-3")
        claim_lease(
            str(tmp_path), "task-3", A_HOST, A_RUNNER,
            lease_id="L-200", fence=1, ttl_profile="M",
        )
        lease2 = claim_lease(
            str(tmp_path), "task-3", A_HOST, A_RUNNER,
            lease_id="L-201", fence=2, ttl_profile="M",
        )
        assert lease2.fence == 2
        assert lease2.status == "claimed"

    def test_t4b_reclaim_equal_fence_fails(self, tmp_path: Path) -> None:
        """A re-claimt mit gleichem Fence → ``ContractAlreadyClaimed``."""
        _write_pending(tmp_path, "task-4")
        claim_lease(
            str(tmp_path), "task-4", A_HOST, A_RUNNER,
            lease_id="L-300", fence=1, ttl_profile="M",
        )
        with pytest.raises(ContractAlreadyClaimed):
            claim_lease(
                str(tmp_path), "task-4", A_HOST, A_RUNNER,
                lease_id="L-301", fence=1, ttl_profile="M",
            )

    def test_t4c_reclaim_lower_fence_fails(self, tmp_path: Path) -> None:
        """A re-claimt mit niedrigerem Fence → ``ContractAlreadyClaimed``."""
        _write_pending(tmp_path, "task-4c")
        claim_lease(
            str(tmp_path), "task-4c", A_HOST, A_RUNNER,
            lease_id="L-302", fence=5, ttl_profile="M",
        )
        with pytest.raises(ContractAlreadyClaimed):
            claim_lease(
                str(tmp_path), "task-4c", A_HOST, A_RUNNER,
                lease_id="L-303", fence=3, ttl_profile="M",
            )


# ------------------------------------------------------------------ #
#  T5 – Renew
# ------------------------------------------------------------------ #

class TestLeaseRenew:
    """Renew-Tests."""

    def test_renew_valid(self, tmp_path: Path) -> None:
        """Gültige renew → OK; expires_at UNVERÄNDERT (TTL nie verkürzen)."""
        _write_pending(tmp_path, "task-r1")
        lease = claim_lease(
            str(tmp_path), "task-r1", A_HOST, A_RUNNER,
            lease_id="L-400", fence=1, ttl_profile="M",
        )
        orig_expires = lease.expires_at
        renewed = renew_lease(str(tmp_path), "task-r1", "L-400")
        assert renewed.status == "claimed"
        assert renewed.expires_at == orig_expires  # TTL NIE verkürzt
        assert renewed.heartbeat_at is not None
        assert renewed.fence == 1

    def test_renew_expired_fails(self, tmp_path: Path) -> None:
        """Abgelaufene renew → ``ContractAlreadyClaimed``."""
        _write_pending(tmp_path, "task-r2")
        past = _past(3600)
        claim_lease(
            str(tmp_path), "task-r2", A_HOST, A_RUNNER,
            lease_id="L-500", fence=1, ttl_profile="S", now=past,
        )
        with pytest.raises(ContractAlreadyClaimed):
            renew_lease(str(tmp_path), "task-r2", "L-500")  # now = jetzt > expires_at

    def test_renew_not_found(self, tmp_path: Path) -> None:
        """Renew nicht existierender lease_id → ``ContractNotFound``."""
        _write_pending(tmp_path, "task-r3")
        with pytest.raises(ContractNotFound):
            renew_lease(str(tmp_path), "task-r3", "NONEXISTENT")


# ------------------------------------------------------------------ #
#  Release
# ------------------------------------------------------------------ #

class TestLeaseRelease:
    """Release-Tests."""

    def test_release_valid(self, tmp_path: Path) -> None:
        """Gültige release → ``status=released`` im Ledger."""
        _write_pending(tmp_path, "task-rel")
        claim_lease(
            str(tmp_path), "task-rel", A_HOST, A_RUNNER,
            lease_id="L-600", fence=1, ttl_profile="M",
        )
        released = release_lease(str(tmp_path), "task-rel", "L-600")
        assert released.status == "released"
        # Readback
        entries = read_ledger(str(tmp_path), "task-rel")
        released_entries = [e for e in entries if e.status == "released"]
        assert len(released_entries) == 1
        assert released_entries[0].lease_id == "L-600"

    def test_release_not_found(self, tmp_path: Path) -> None:
        """Release nicht existierender Lease → ``ContractNotFound``."""
        with pytest.raises(ContractNotFound):
            release_lease(str(tmp_path), "nonexistent", "L-999")


# ------------------------------------------------------------------ #
#  T5 – Readback-Beleg (BACH-Client ≡ Trithon)
# ------------------------------------------------------------------ #

class TestReadback:
    """T5: Readback über denselben JSONL-Ledger."""

    def test_readback_consistency(self, tmp_path: Path) -> None:
        """Zwei 'Clients' lesen denselben Ledger → identische Daten."""
        _write_pending(tmp_path, "task-rb")
        claim_lease(
            str(tmp_path), "task-rb", A_HOST, A_RUNNER,
            lease_id="L-700", fence=3, ttl_profile="M",
            salt_ref="SALT-REF-42",
        )
        # BACH-Client 'liest' den Ledger
        entries_bach = read_ledger(str(tmp_path), "task-rb")
        claimed_bach = [e for e in entries_bach if e.status == "claimed"]
        assert len(claimed_bach) == 1

        # Trithon 'liest' denselben Ledger
        entries_trithon = read_ledger(str(tmp_path), "task-rb")
        claimed_trithon = [e for e in entries_trithon if e.status == "claimed"]

        # Identisch
        assert len(claimed_bach) == len(claimed_trithon)
        assert claimed_bach[0].host == claimed_trithon[0].host
        assert claimed_bach[0].fence == claimed_trithon[0].fence
        assert claimed_bach[0].lease_id == claimed_trithon[0].lease_id
        assert claimed_bach[0].salt_ref == "SALT-REF-42"
        assert claimed_trithon[0].salt_ref == "SALT-REF-42"

    def test_ledger_file_valid_json(self, tmp_path: Path) -> None:
        """JSONL-Datei existiert und jede Zeile ist gültiges JSON."""
        _write_pending(tmp_path, "task-f")
        claim_lease(
            str(tmp_path), "task-f", A_HOST, A_RUNNER,
            lease_id="L-800", fence=1, ttl_profile="M",
        )
        lp = _ledger_path(tmp_path, "task-f")
        assert lp.exists()
        lines = lp.read_text(encoding="utf-8").splitlines()
        assert len(lines) >= 2  # pending + claimed
        for line in lines:
            parsed = json.loads(line)
            assert "status" in parsed
            assert "work_item_id" in parsed


# ------------------------------------------------------------------ #
#  Finalisiert → blockiert
# ------------------------------------------------------------------ #

class TestFinalStatusBlocks:
    """Finalisierte Tasks blockieren neue Claims."""

    def test_done_blocks_claim(self, tmp_path: Path) -> None:
        """done-Status → neuer Claim ist blockiert."""
        _write_pending(tmp_path, "task-done")
        claim_lease(
            str(tmp_path), "task-done", A_HOST, A_RUNNER,
            lease_id="L-900", fence=1, ttl_profile="M",
        )
        # Simuliere done via record_receipt
        receipt = ExecutionReceipt(
            signature="sig-1",
            status="done",
            executed_by=A_HOST,
            actual_provider="test",
            actual_model="test",
            occurred_at=_now(),
        )
        record_receipt(str(tmp_path), "task-done", receipt)
        with pytest.raises(ContractAlreadyClaimed):
            claim_lease(
                str(tmp_path), "task-done", B_HOST, B_RUNNER,
                lease_id="L-901", fence=2, ttl_profile="M",
            )

    def test_blocked_blocks_claim(self, tmp_path: Path) -> None:
        """blocked-Status → neuer Claim ist blockiert."""
        _write_pending(tmp_path, "task-blk")
        claim_lease(
            str(tmp_path), "task-blk", A_HOST, A_RUNNER,
            lease_id="L-910", fence=1, ttl_profile="M",
        )
        receipt = ExecutionReceipt(
            signature="sig-2",
            status="blocked",
            executed_by=A_HOST,
            actual_provider="test",
            actual_model="test",
            occurred_at=_now(),
        )
        record_receipt(str(tmp_path), "task-blk", receipt)
        with pytest.raises(ContractAlreadyClaimed):
            claim_lease(
                str(tmp_path), "task-blk", B_HOST, B_RUNNER,
                lease_id="L-911", fence=2, ttl_profile="M",
            )


# ------------------------------------------------------------------ #
#  TTL-Profile
# ------------------------------------------------------------------ #

class TestTTLProfiles:
    """TTL-Profil-Validität."""

    def test_all_profiles_defined(self) -> None:
        """Alle vier Profile existieren und sind positiv."""
        for key in ("S", "M", "L", "XL"):
            assert key in TTL_PROFILE_SECONDS
            assert TTL_PROFILE_SECONDS[key] > 0

    def test_default_profile_is_m(self, tmp_path: Path) -> None:
        """Ohne ttl_profile-Arg → 'M' (1800 s)."""
        _write_pending(tmp_path, "task-ttl")
        lease = claim_lease(
            str(tmp_path), "task-ttl", A_HOST, A_RUNNER,
            lease_id="L-TTL", fence=1,
        )
        assert lease.ttl_profile == "M"


# ------------------------------------------------------------------ #
#  Eigen-abgelaufen → Fencing-Aufstieg
# ------------------------------------------------------------------ #

class TestExpiredSelfReclaim:
    """Eigen abgelaufen → Fencing-Aufstieg erlaubt."""

    def test_self_expired_reclaim_with_higher_fence(self, tmp_path: Path) -> None:
        """A claimt abgelaufen, re-claimt mit höherem Fence → OK."""
        _write_pending(tmp_path, "task-se")
        past = _past(3600)
        claim_lease(
            str(tmp_path), "task-se", A_HOST, A_RUNNER,
            lease_id="L-SE1", fence=1, ttl_profile="S", now=past,
        )
        # A re-claimt mit höherem Fence → OK (eigen, abgelaufen, fence > 1)
        lease2 = claim_lease(
            str(tmp_path), "task-se", A_HOST, A_RUNNER,
            lease_id="L-SE2", fence=2, ttl_profile="M",
        )
        assert lease2.fence == 2
        assert lease2.status == "claimed"

    def test_self_expired_reclaim_same_fence_fails(self, tmp_path: Path) -> None:
        """A claimt abgelaufen, re-claimt mit gleichem Fence → fail."""
        _write_pending(tmp_path, "task-se2")
        past = _past(3600)
        claim_lease(
            str(tmp_path), "task-se2", A_HOST, A_RUNNER,
            lease_id="L-SE3", fence=1, ttl_profile="S", now=past,
        )
        with pytest.raises(ContractAlreadyClaimed):
            claim_lease(
                str(tmp_path), "task-se2", A_HOST, A_RUNNER,
                lease_id="L-SE4", fence=1, ttl_profile="M",
            )
