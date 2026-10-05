"""Regressionstests für den engen agents-heart-Besetzungs-Seam."""

import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.agents_heart import (
     _REQUIRED_RIGHTS,
    ROLE_CONTRACTS,
    AssignmentDenied,
    AssignmentEventSink,
    authorize_role,
    begin_assignment,
    finish_assignment,
)
from hub._services.chat.slots_config import (
    get_activity_history,
    initialize_slots_config,
)


def test_assignment_start_and_end_are_correlated_and_flattened(tmp_path):
    cfg_file = tmp_path / "slots.json"
    initialize_slots_config(str(cfg_file))

    assignment = begin_assignment(
        role_id="hintergrund_worker",
        mode="full",
        agent_instance_id="worker-test-instance",
        backend_id="ollama",
        model_id="qwen3.8:27b-mlx",
        slot_id="buddha_always_on",
        task_id=42,
        session_id="worker-all-42",
        initiated_by="worker:all",
        path=str(cfg_file),
     )
    finish_assignment(
        assignment,
        status="completed",
        result="task_done",
        path=str(cfg_file),
     )

    history = get_activity_history(limit=10, path=str(cfg_file))
    assert len(history) == 2
    start, end = history[1], history[0]

    assert start["event"] == "assignment_started"
    assert end["event"] == "assignment_ended"
    assert start["assignment_id"] == end["assignment_id"] == assignment.assignment_id
    for entry in (start, end):
        assert entry["role_id"] == "hintergrund_worker"
        assert entry["agent_instance_id"] == "worker-test-instance"
        assert entry["backend_id"] == "ollama"
        assert entry["model_id"] == "qwen3.8:27b-mlx"
        assert entry["slot_id"] == "buddha_always_on"
        assert entry["task_id"] == 42
        assert entry["initiated_by"] == "worker:all"
        assert entry["started_at"] == assignment.started_at
    assert end["ended_at"]
    assert end["result"] == "task_done"


@pytest.mark.parametrize("role_id", ["task_worker", "boss_routing", "expert_role"])
def test_board_sub_modes_are_registered_with_hintergrund_worker_rights(role_id):
     """T-20260926-658915805: Board (telegram_chat.py) startet Worker über die
    sub_mode-Werte task_worker/boss_routing/expert_role, nicht über
    hintergrund_worker. Ohne einen registrierten Vertrag würde authorize_role()
    JEDE Board-Ausführung ablehnen -- diese drei müssen also existieren.
    Least Privilege heißt hier dieselben Rechte wie hintergrund_worker, weil
     _run_worker_job() für alle sub_mode-Werte denselben Ausführungscode nutzt
     (kein zusätzliches Recht wird irgendwo geprüft)."""
    contract = ROLE_CONTRACTS[role_id]
    assert contract.rights == ROLE_CONTRACTS["hintergrund_worker"].rights
    assert contract.rights == _REQUIRED_RIGHTS


def test_unregistered_board_role_is_denied_fail_closed():
    with pytest.raises(AssignmentDenied):
        authorize_role("task_worker_typo", "full")


def test_unknown_role_is_denied_before_assignment_is_created(tmp_path):
    with pytest.raises(AssignmentDenied):
        begin_assignment(
            role_id="not-registered",
            mode="full",
            agent_instance_id="worker-test-instance",
            backend_id="ollama",
            model_id="qwen3.8:27b-mlx",
            slot_id="buddha_always_on",
            task_id=43,
            session_id="worker-all-43",
            initiated_by="worker:all",
            path=str(tmp_path / "slots.json"),
         )


# ── Neutrales-Sink-Test (T-20261003-793817309) ──────────────────────────
class _CollectingSink:
     """Inlinem Noop-Sink, der alle record()-Aufrufe in einer Liste sammelt.

    Beweist, dass begin_assignment / finish_assignment den Sink-Parameter
    respektieren und BACH-spezifische record_activity() NICHT aufrufen.
    """

    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(
        self,
        slot_id: str,
        activity: str,
        status: str,
        details: dict,
        path: str | None = None,
    ) -> None:
        self.entries.append(
            {
                "slot_id": slot_id,
                "activity": activity,
                "status": status,
                "details": details,
                "path": path,
            }
        )


def test_custom_sink_receives_correlated_events(tmp_path):
     """Eigener Sink fängt start + end auf, ohne BACH-record_activity.

    Prüft:
      * genau 2 Einträge (Start + Ende)
      * gleicher assignment_id (Korrelation)
      * Event-Typen 'assignment_started' / 'assignment_ended'
      * Start-Zeitstempel <= Ende-Zeitstempel
      * Keine Datei-Aktion (kein slots.json geschrieben)
     """
    sink = _CollectingSink()
    cfg_file = tmp_path / "slots.json"
    initialize_slots_config(str(cfg_file))

    assignment = begin_assignment(
        role_id="hintergrund_worker",
        mode="full",
        agent_instance_id="worker-test-instance",
        backend_id="ollama",
        model_id="qwen3.8:27b-mlx",
        slot_id="buddha_always_on",
        task_id=99,
        session_id="worker-all-99",
        initiated_by="worker:all",
        path=str(cfg_file),
        sink=sink,
     )
    finish_assignment(
        assignment,
        status="completed",
        result="task_done",
        path=str(cfg_file),
        sink=sink,
     )

    # --- genau 2 Ereignisse ---
    assert len(sink.entries) == 2, f"erwartet 2 Einträge, erhielt {len(sink.entries)}"
    start, end = sink.entries[0], sink.entries[1]

    # --- Korrelation über assignment_id ---
    assert start["details"]["event"] == "assignment_started"
    assert end["details"]["event"] == "assignment_ended"
    assert start["details"]["assignment_id"] == end["details"]["assignment_id"]
    assert start["details"]["assignment_id"] == assignment.assignment_id

    # --- Zeitliche Reihenfolge: Start <= Ende ---
    assert start["details"]["started_at"] <= end["details"]["ended_at"]

    # --- Durchgängige Felder ---
    for entry in (start, end):
        assert entry["details"]["role_id"] == "hintergrund_worker"
        assert entry["details"]["agent_instance_id"] == "worker-test-instance"
        assert entry["details"]["backend_id"] == "ollama"
        assert entry["details"]["model_id"] == "qwen3.8:27b-mlx"
        assert entry["details"]["slot_id"] == "buddha_always_on"
        assert entry["details"]["task_id"] == 99
        assert entry["details"]["initiated_by"] == "worker:all"

    assert end["details"]["result"] == "task_done"
    assert end["details"]["status"] == "completed"

    # --- slots.json unverändert: record_activity NICHT aufgerufen ---
    history = get_activity_history(limit=10, path=str(cfg_file))
    assert len(history) == 0, (
        "BACH-Sink wurde aufgerufen, obwohl Custom-Sink injiziert war"
    )
