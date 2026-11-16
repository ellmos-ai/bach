"""Tests fuer die StarLease-Fassade in ``writer.py``."""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_writer():
    """Laedt writer.py direkt als Modul (unabhaengig von der Paketstruktur)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("writer_facade", ROOT / "system" / "hub" / "writer.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


writer = _load_writer()
StarLease = writer.StarLease


def test_acquire_liefert_true_und_fence(tmp_path):
    lease = StarLease(tmp_path)
    assert lease.acquire() is True
    assert lease.is_held is True
    assert lease.fence
    assert lease.release() is True


def test_append_und_check_fence_happy_path(tmp_path):
    decision = writer.DecisionWriter(tmp_path)
    fence = decision.decide()
    assert fence
    decision.append(fence, "entscheidung A")
    assert decision._lease.check_fence() is True

    log = (tmp_path / "decision.txt").read_text(encoding="utf-8")
    assert "entscheidung A" in log
    decision.undo()
    assert decision._lease.is_held is False


def test_zweite_instanz_wird_abgewiesen(tmp_path):
    erste = StarLease(tmp_path)
    erste.acquire()
    try:
        zweite = StarLease(tmp_path)
        try:
            zweite.acquire()
        except writer.LeaseDeniedError:
            pass
        else:  # pragma: no cover
            raise AssertionError("LeaseDeniedError erwartet")
    finally:
        erste.release()


def test_abgelaufene_lease_wird_uebernommen(tmp_path):
    erste = StarLease(tmp_path)
    erste.acquire(ttl=0.1)
    time.sleep(0.3)

    zweite = StarLease(tmp_path)
    assert zweite.acquire() is True
    assert zweite.is_held is True
    zweite.release()


def test_fence_mismatch_loest_violation_aus(tmp_path):
    decision = writer.DecisionWriter(tmp_path)
    decision.decide()
    try:
        try:
            decision.append("falscher-fence-wert", "darf nicht erscheinen")
        except writer.LeaseViolation:
            pass
        else:  # pragma: no cover
            raise AssertionError("LeaseViolation erwartet")
    finally:
        decision.undo()


def test_append_mit_falschem_fence_schreibt_nicht(tmp_path):
    decision = writer.DecisionWriter(tmp_path)
    decision.decide()
    log = tmp_path / "decision.txt"
    try:
        try:
            decision.append("falscher-fence-wert", "darf nicht erscheinen")
        except writer.LeaseViolation:
            pass
        else:  # pragma: no cover
            raise AssertionError("LeaseViolation erwartet")
    finally:
        decision.undo()
    assert not log.exists() or "darf nicht erscheinen" not in log.read_text(
        encoding="utf-8"
    )


def test_release_setzt_status_zurueck(tmp_path):
    lease = StarLease(tmp_path)
    lease.acquire()
    assert lease.release() is True
    assert lease.is_held is False
    assert lease.status()["exists"] is False


def test_kontextmanager_gibt_frei(tmp_path):
    lease = StarLease(tmp_path)
    with lease:
        lease.acquire()
        assert lease.is_held is True
        assert lease.fence
    assert lease.is_held is False
    assert lease.status()["exists"] is False


def test_status_liefert_erwartete_schluessel(tmp_path):
    lease = StarLease(tmp_path)
    lease.acquire()
    try:
        status = lease.status()
        for key in ("held", "exists", "fence"):
            assert key in status
        assert status["exists"] is True
    finally:
        lease.release()


def test_instanziierbar_ohne_argumente(tmp_path):
    lease = StarLease()
    for name in ("acquire", "check_fence", "release", "status", "renew"):
        assert hasattr(lease, name)
    assert not hasattr(lease, "append")
    assert not hasattr(lease, "base_dir")

    # lock_path ist erst mit resource_dir aufloesbar
    assert isinstance(StarLease(tmp_path).lock_path.parent, Path)
