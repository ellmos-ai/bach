"""Tests zum Stern-Lease-Modul (Task #3746, Rekonstruktion fuer Rest #3743).

Abgedeckte Themen in Reihenfolge acquire / renew / release / status / register,
dazu Fehlerklassen ([CONFLICT]/[UNAVAILABLE]/[VIOLATION]), Fence-Pruefung,
MUTATION_LOCK-Ebene 1 vor Stern-Lease (Ebene 2) und Parameter (DEFAULT_TTL,
MAX_ACQUIRE_ATTEMPTS, Exponential Backoff). Alle Ablaeufe laufen ueber einen
injizierten Fake-Runner (lease.py-CLI-Semantik), ohne echte Polarstern-Verbindung.
"""

import os
import sys
import threading

import pytest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYSTEM_DIR = os.path.dirname(_TESTS_DIR)
if _SYSTEM_DIR not in sys.path:
    sys.path.insert(0, _SYSTEM_DIR)

from hub.star_lease import (  # noqa: E402
    DEFAULT_TTL,
    MAX_ACQUIRE_ATTEMPTS,
    MUTATION_LOCK,
    LeaseDeniedError,
    LeaseHandle,
    LeaseUnavailableError,
    LeaseViolation,
    acquire,
    check_fence,
    mutation_lock_held,
    mutate,
    register,
    release,
    renew,
    status,
)

ACQUIRE_OK = ("[OK] Polaris star polaris-star an agent-1 (LEAD, Fence 2, Profil short, "
              "Frist bis 2026-01-01T00:00:30Z, Renew alle 10s)\n"
              "Lease-Capability: lease-uuid-1")
RENEW_OK = ("[OK] Polaris star polaris-star verlaengert "
            "(Fence 8, bis 2026-01-01T00:01:00Z)")
RELEASE_OK = "[OK] Polaris star polaris-star zurueckgegeben (Fence 2)"
STATUS_OWN = ("polaris-star: Leased=True, Fence=7, Version=3, Server aktiv=True\n"
              "Halter: agent-1 (LEAD), Ablauf 2026-01-01T00:00:30Z\n"
              "[OWN POLARIS STAR CONFIRMED]")


class Recorder:
    """Fake-Runner: zeichnet (resource, action, opts) auf und spielt Antworten."""

    def __init__(self, responses):
        self.calls = []
        self.responses = list(responses)

    def __call__(self, resource, action, opts):
        self.calls.append((resource, action, dict(opts)))
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        raise AssertionError(f"unerwartete Aktion ohne Antwort: {action}")

    @property
    def actions(self):
        return [action for _, action, _ in self.calls]


class Pause:
    """Erfasst Backoff-Verzoegerungen statt real zu warten."""

    def __init__(self):
        self.delays = []

    def __call__(self, seconds):
        self.delays.append(seconds)


# --- Parameter und Schichttyp -------------------------------------------

def test_parameter_default_ttl_und_max_versuche_und_rlock():
    assert DEFAULT_TTL == 30.0
    assert MAX_ACQUIRE_ATTEMPTS == 3
    assert isinstance(MUTATION_LOCK, type(threading.RLock()))


# --- acquire -------------------------------------------------------------

def test_acquire_liefert_handle_und_default_ttl():
    runner = Recorder([(True, ACQUIRE_OK)])
    handle = acquire("polaris-star", "agent-1", intent="test", runner=runner)
    assert runner.calls == [("polaris-star", "acquire",
                             {"by": "agent-1", "intent": "test", "ttl": "30.0",
                              "show-capability": True})]
    assert isinstance(handle, LeaseHandle)
    assert handle.lease_id == "lease-uuid-1"
    assert handle.fence == 2
    assert handle.ttl_profile == "short"
    assert handle.renew_after_seconds == 10
    assert handle.expires_at == "2026-01-01T00:00:30Z"


def test_acquire_retry_unavailable_mit_exponential_backoff():
    runner = Recorder([(False, "[UNAVAILABLE] acquire: busy"),
                       (False, "[UNAVAILABLE] acquire: busy"),
                       (True, ACQUIRE_OK)])
    pause = Pause()
    handle = acquire("polaris-star", "agent-1", runner=runner, pause=pause)
    assert runner.actions == ["acquire", "acquire", "acquire"]
    assert pause.delays == [0.5, 1.0]
    assert handle.fence == 2


def test_acquire_erschoepft_max_versuche_mit_unavailable():
    pause = Pause()
    runner = Recorder([(False, "[UNAVAILABLE] acquire: busy")] * MAX_ACQUIRE_ATTEMPTS)
    with pytest.raises(LeaseUnavailableError) as excinfo:
        acquire("polaris-star", "agent-1", runner=runner, pause=pause)
    assert len(runner.calls) == MAX_ACQUIRE_ATTEMPTS == 3
    assert pause.delays == [0.5, 1.0]
    assert "[UNAVAILABLE]" in str(excinfo.value)


def test_acquire_conflict_abbrechen_ohne_retry():
    runner = Recorder([(False, "[CONFLICT] acquire: denied")])
    pause = Pause()
    with pytest.raises(LeaseDeniedError) as excinfo:
        acquire("polaris-star", "agent-1", runner=runner, pause=pause)
    assert len(runner.calls) == 1
    assert pause.delays == []
    assert "[CONFLICT]" in str(excinfo.value)


# --- renew ---------------------------------------------------------------

def test_renew_aktualisiert_fence_im_handle():
    lease = LeaseHandle("polaris-star", "lease-uuid-1", 2)
    runner = Recorder([(True, RENEW_OK)])
    assert renew(lease, runner=runner) is lease
    assert lease.fence == 8
    assert runner.calls[0][1] == "renew"
    assert runner.calls[0][2] == {"lease-id": "lease-uuid-1", "fence": "2"}


# --- release -------------------------------------------------------------

def test_release_gibt_lease_id_und_fence_weiter():
    lease = LeaseHandle("polaris-star", "lease-uuid-1", 2)
    runner = Recorder([(True, RELEASE_OK)])
    assert release(lease, runner=runner).startswith("[OK]")
    assert runner.calls[0][1] == "release"
    assert runner.calls[0][2] == {"lease-id": "lease-uuid-1", "fence": "2"}


# --- status --------------------------------------------------------------

def test_status_parst_haltestatus_mit_own_beleg():
    runner = Recorder([(True, STATUS_OWN)])
    info = status("polaris-star", runner=runner)
    assert runner.calls[0][1] == "status"
    assert info["leased"] is True
    assert info["fence"] == 7
    assert info["version"] == "3"
    assert info["server_active"] is True
    assert info["holder"] == "agent-1"
    assert info["role"] == "LEAD"
    assert info["expires_at"] == "2026-01-01T00:00:30Z"
    assert info["own"] is True


# --- register ------------------------------------------------------------

def test_register_baut_cli_optionen_korrekt():
    runner = Recorder([(True, "[OK] Ressource polaris-star registriert: ok")])
    message = register("polaris-star", allowed_workers=["a-1", "a-2"],
                       device_bindings={"gyro": ["p*"]}, server_role="lead",
                       standby_roles=["standby-a"], runner=runner)
    assert message.startswith("[OK]")
    assert runner.calls[0] == ("polaris-star", "register",
                               {"bind": "gyro=p*", "allowed": "a-1,a-2",
                                "server-role": "lead", "standby": "standby-a"})


# --- Fence-Pruefung ------------------------------------------------------

def test_check_fence_violation_bei_fencedivergenz_und_fremdlease():
    lease = LeaseHandle("polaris-star", "lease-uuid-1", 7)
    drifted = Recorder([(True, STATUS_OWN.replace("Fence=7", "Fence=9"))])
    with pytest.raises(LeaseViolation) as excinfo:
        check_fence(lease, runner=drifted)
    assert "[VIOLATION]" in str(excinfo.value)
    foreign = Recorder([(True, "polaris-star: Leased=True, Fence=7, Version=3, "
                              "Server aktiv=True")])
    with pytest.raises(LeaseViolation):
        check_fence(lease, runner=foreign)


# --- Schichtenreihenfolge und try/finally -------------------------------

def test_mutate_ebene1_lock_vor_ebene2_stern_lease_in_fester_reihenfolge():
    runner = Recorder([(True, ACQUIRE_OK), (True, STATUS_OWN.replace("Fence=7", "Fence=2")), (True, RELEASE_OK)])
    events = []

    def probe(resource, action, opts):
        events.append(action)
        if action == "acquire":
            events.append(f"lock-held={mutation_lock_held()}")
        return runner(resource, action, opts)

    def callback(lease):
        events.append("mutate")
        assert mutation_lock_held()
        return "fertig"

    assert not mutation_lock_held()
    assert mutate("polaris-star", "agent-1", callback, runner=probe) == "fertig"
    assert not mutation_lock_held()
    # Ebene 1 gehalten, waehrend Ebene 2 acquiriert wird; Reihenfolge fix.
    assert events == ["acquire", "lock-held=True", "status", "mutate", "release"]
    assert runner.actions == ["acquire", "status", "release"]


def test_mutate_gibt_lease_im_finally_frei_bei_mutationfehler():
    runner = Recorder([(True, ACQUIRE_OK), (True, STATUS_OWN.replace("Fence=7", "Fence=2")), (True, RELEASE_OK)])

    def callback(lease):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        mutate("polaris-star", "agent-1", callback, runner=runner)
    assert runner.actions == ["acquire", "status", "release"]
