#!/usr/bin/env python3
# coding: utf-8
# SPDX-License-Identifier: MIT
"""Tests für die Stern-Lease mit Fence-Prüfung (Task #3743, D-20261012-001).

Deckt Exklusivität, Steal abgelaufener und korrupter Locks, Readback-Verifikation,
Fence-Prüfung, Renew, Release-Invarianten und die Zwei-Prozesse-Serialisierung ab.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
HUB_ROOT = SYSTEM_ROOT / "hub"
sys.path.insert(0, str(HUB_ROOT))

import star_lease  # noqa: E402
from star_lease import (  # noqa: E402
    LeaseDeniedError,
    LeaseUnavailableError,
    LeaseViolation,
    StarLease,
)


class _TamperReadback(StarLease):
    """Fälscht den nächsten Readback, um die Verifikation zu prüfen."""

    def __init__(self, *args, **kwargs):
        StarLease.__init__(self, *args, **kwargs)
        self.tamper_next = False

    def _read_lock_text(self, path):
        if self.tamper_next:
            self.tamper_next = False
            return "star-lease: 1\nholder: gefaelscht\n"
        return StarLease._read_lock_text(path)


def test_01_acquire_exklusiv_release(tmp_path):
    lease_a = StarLease(resource_dir=tmp_path)
    assert lease_a.acquire(holder="alpha") is True
    assert lease_a.is_held is True
    assert lease_a.holder == "alpha"

    lease_b = StarLease(resource_dir=tmp_path)
    with pytest.raises(LeaseDeniedError) as excinfo:
        lease_b.acquire(holder="beta")
    assert "[CONFLICT]" in str(excinfo.value)
    assert "alpha" in str(excinfo.value)

    with pytest.raises(LeaseViolation) as excinfo:
        lease_a.acquire()
    assert "bereits gehalten" in str(excinfo.value)

    assert lease_a.release() is True
    assert not (tmp_path / "LOCK.txt").exists()
    assert lease_a.release() is False
    assert lease_a.is_held is False


def test_02_status_vor_und_nach_acquire(tmp_path):
    lease = StarLease(resource_dir=tmp_path)
    davor = lease.status()
    assert davor["exists"] is False
    assert davor["held"] is False
    assert davor["holder"] is None
    assert davor["corrupt"] is False

    assert lease.acquire(holder="alpha") is True
    danach = lease.status()
    assert danach["held"] is True
    assert danach["exists"] is True
    assert danach["holder"] == "alpha"
    assert danach["pid"] == os.getpid()
    assert danach["expired"] is False
    assert danach["fence"] == lease.fence
    assert danach["path"].endswith("LOCK.txt")


def test_03_readback_tamper_konfliktkopie(tmp_path):
    lease = _TamperReadback(resource_dir=tmp_path)
    lease.tamper_next = True
    with pytest.raises(LeaseUnavailableError):
        lease.acquire(holder="alpha")
    lock_text = (tmp_path / "LOCK.txt").read_text(encoding="utf-8")
    assert "holder: alpha" in lock_text
    assert lease.is_held is False
    konflikte = list(tmp_path.glob("LOCK*-Konflikt*"))
    assert len(konflikte) == 1
    inhalt = konflikte[0].read_text(encoding="utf-8")
    assert "gefaelscht" in inhalt
    assert "Readback weicht vom eigenen Payload ab" in inhalt


def test_04_steal_abgelaufenes_lock(tmp_path):
    lease_alt = StarLease(resource_dir=tmp_path)
    assert lease_alt.acquire(holder="alt", ttl=0.05) is True
    time.sleep(0.12)

    warnungen = []
    lease_neu = StarLease(resource_dir=tmp_path, warn=warnungen.append)
    assert lease_neu.acquire(holder="neu") is True
    assert lease_neu.fence != lease_alt.fence

    assert any("Steal abgelaufenes Lock" in w for w in warnungen)
    konflikte = list(tmp_path.glob("LOCK*-Konflikt*"))
    assert len(konflikte) == 1
    inhalt = konflikte[0].read_text(encoding="utf-8")
    assert "holder: alt" in inhalt

    # Das stale Lease darf nicht mehr freigegeben werden, ohne dass es knallt:
    with pytest.raises(LeaseViolation):
        lease_alt.release()


def test_05_korrupt_frisch_gnadenfrist(tmp_path):
    lock = tmp_path / "LOCK.txt"
    inhalt = "muell ohne doppel\nzweite zeile\n"
    lock.write_text(inhalt, encoding="utf-8")
    lease = StarLease(resource_dir=tmp_path)
    with pytest.raises(LeaseUnavailableError) as excinfo:
        lease.acquire(holder="alpha")
    assert "Gnadenfrist" in str(excinfo.value)
    assert lock.read_text(encoding="utf-8") == inhalt
    assert lease.is_held is False


def test_06_korrupt_alt_wird_gestohlen(tmp_path):
    lock = tmp_path / "LOCK.txt"
    lock.write_text("kaputtes lock\n", encoding="utf-8")
    jetzt = time.time()
    os.utime(str(lock), (jetzt - 120, jetzt - 120))

    warnungen = []
    lease = StarLease(resource_dir=tmp_path, warn=warnungen.append)
    assert lease.acquire(holder="alpha") is True
    assert warnungen
    assert any("Steal" in w for w in warnungen)
    konflikte = list(tmp_path.glob("LOCK*-Konflikt*"))
    assert len(konflikte) == 1
    assert "kaputtes lock" in konflikte[0].read_text(encoding="utf-8")


def test_07_release_bei_fremdinhalt(tmp_path):
    lease = StarLease(resource_dir=tmp_path)
    assert lease.acquire(holder="alpha") is True
    lock = tmp_path / "LOCK.txt"
    fake = (
        "star-lease: 1\n"
        "host: fremd\n"
        "pid: 1\n"
        "holder: beta\n"
        "expiry: 2100-01-01T00:00:00Z\n"
        "expiry_epoch: 4102444800.0\n"
        "fence: fremde-fence\n"
    )
    lock.write_text(fake, encoding="utf-8")
    with pytest.raises(LeaseViolation):
        lease.release()
    assert "holder: beta" in lock.read_text(encoding="utf-8")
    assert lease.is_held is True
    konflikte = list(tmp_path.glob("LOCK*-Konflikt*"))
    assert len(konflikte) == 1
    assert "holder: beta" in konflikte[0].read_text(encoding="utf-8")


def test_08_check_fence_blocker(tmp_path):
    lease = StarLease(resource_dir=tmp_path)
    with pytest.raises(LeaseViolation) as excinfo:
        lease.check_fence()
    assert "kein Lease gehalten" in str(excinfo.value)

    assert lease.acquire(holder="alpha") is True
    lock = tmp_path / "LOCK.txt"

    lock.write_text("star-lease: 1\nholder: jemand-anderes\n", encoding="utf-8")
    with pytest.raises(LeaseViolation) as excinfo:
        lease.check_fence()
    assert "verändert" in str(excinfo.value)

    lock.unlink()
    with pytest.raises(LeaseViolation) as excinfo:
        lease.check_fence()
    assert "fehlt" in str(excinfo.value)

    kurzer = StarLease(resource_dir=tmp_path)
    assert kurzer.acquire(holder="kurz", ttl=0.05) is True
    time.sleep(0.12)
    with pytest.raises(LeaseViolation) as excinfo:
        kurzer.check_fence()
    assert "abgelaufen" in str(excinfo.value)


def test_09_check_fence_ok(tmp_path):
    lease = StarLease(resource_dir=tmp_path)
    assert lease.acquire(holder="alpha") is True
    assert lease.check_fence() is True
    assert lease.release() is True


def test_10_renew_verlaengert_fence_stabil(tmp_path):
    lease = StarLease(resource_dir=tmp_path)
    assert lease.acquire(holder="alpha", ttl=0.2) is True
    fence_davor = lease.fence
    alt_raw = (tmp_path / "LOCK.txt").read_text(encoding="utf-8")

    assert lease.renew(30) is True
    neu_raw = (tmp_path / "LOCK.txt").read_text(encoding="utf-8")
    assert neu_raw != alt_raw
    geparst = StarLease._parse(neu_raw)
    assert geparst["fence"] == fence_davor
    assert geparst["holder"] == "alpha"

    time.sleep(0.25)
    assert lease.check_fence() is True

    anderer = StarLease(resource_dir=tmp_path)
    with pytest.raises(LeaseViolation):
        anderer.renew(30)


def test_11_contextmanager_gibt_lock_frei(tmp_path):
    with StarLease(resource_dir=tmp_path) as lease:
        assert lease.acquire(holder="alpha") is True
        assert lease.check_fence() is True
    assert lease.is_held is False
    assert not (tmp_path / "LOCK.txt").exists()


_CHILD_SCRIPT = r'''
import os
import sys
import time

sys.path.insert(0, os.environ["STAR_LEASE_HOME"])
import star_lease

chain_dir = os.environ["CHAIN_DIR"]
tag = os.environ["PROC_TAG"]
lease = star_lease.StarLease(chain_dir, warn=lambda msg: None)
try:
    lease.acquire(holder=tag, ttl=30)
except star_lease.LeaseError:
    print("DENIED", flush=True)
    sys.exit(2)
try:
    with open(os.path.join(chain_dir, tag + ".acquired"), "w") as fh:
        fh.write(tag + "\n")
    deadline = time.time() + 30
    go_path = os.path.join(chain_dir, tag + ".go")
    while not os.path.exists(go_path):
        if time.time() >= deadline:
            sys.exit(3)
        time.sleep(0.02)
    lease.check_fence()
    with open(os.path.join(chain_dir, "decisions.log"), "a") as fh:
        fh.write(tag + "\n")
    print("WON", flush=True)
finally:
    lease.release()
sys.exit(0)
'''


def test_12_zwei_prozesse_decide_nur_mit_lease(tmp_path):
    chain_dir = tmp_path / "chain"
    chain_dir.mkdir()
    base_env = dict(os.environ)
    base_env["CHAIN_DIR"] = str(chain_dir)
    base_env["STAR_LEASE_HOME"] = str(HUB_ROOT)

    env_a = dict(base_env)
    env_a["PROC_TAG"] = "proc-A"
    proc_a = subprocess.Popen(
        [sys.executable, "-c", _CHILD_SCRIPT],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env_a,
        text=True,
    )
    deadline = time.time() + 20
    while not (chain_dir / "proc-A.acquired").exists():
        if proc_a.poll() is not None:
            out_a, err_a = proc_a.communicate()
            raise AssertionError(
                "proc-A endete vor dem Lock: rc=%s out=%r err=%r"
                % (proc_a.returncode, out_a, err_a)
            )
        if time.time() >= deadline:
            out_a, err_a = proc_a.communicate(timeout=45)
            raise AssertionError(
                "proc-A erlangte kein Lock: out=%r err=%r" % (out_a, err_a)
            )
        time.sleep(0.02)

    env_b = dict(base_env)
    env_b["PROC_TAG"] = "proc-B"
    proc_b = subprocess.Popen(
        [sys.executable, "-c", _CHILD_SCRIPT],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env_b,
        text=True,
    )
    out_b, err_b = proc_b.communicate(timeout=45)
    assert proc_b.returncode == 2, "out=%r err=%r" % (out_b, err_b)
    assert "DENIED" in out_b

    (chain_dir / "proc-A.go").write_text("go\n", encoding="utf-8")
    out_a, err_a = proc_a.communicate(timeout=45)
    assert proc_a.returncode == 0, "out=%r err=%r" % (out_a, err_a)
    assert "WON" in out_a

    log_text = (chain_dir / "decisions.log").read_text(encoding="utf-8")
    assert log_text.splitlines() == ["proc-A"]