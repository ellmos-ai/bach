"""Tests fuer den Ersteller-Vorrang (Creator-Priority) bei Task-Leases.

Drei Faelle:
(a) Standard aus: jede Worker-ID kann die Lease sofort erwerben.
(b) Einstellung aktiv mit 120 s: nur der Ersteller erhaelt die Lease,
    ein Fremder wird mit ``reason == "creator_priority"`` verweigert.
(c) Sequenz-Delegation: 600 s Fenster, unabhaengig von der Einstellung.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from system.tests.test_task_lease_client import _init_db  # noqa: E402
from hub._services import task_lease, task_lease_client  # noqa: E402
from hub._services import task_lease_settings  # noqa: E402
from hub._services.task_lease_client import LeaseDeniedError, TaskLeaseClient  # noqa: E402


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def prepared(tmp_path, monkeypatch):
    """Liefert (pfad, verbindung, dienst) mit leerer Authority-DB."""
    from hub._services import SequenceStore

    monkeypatch.delenv("BACH_TASK_LEASE_CREATOR_WINDOW", raising=False)
    monkeypatch.setattr(task_lease_client, "get_lead_config", lambda: {"mode": "isolated"})

    path = tmp_path / "authority.db"
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    _init_db(db)
    db.execute("ALTER TABLE tasks ADD COLUMN created_at TEXT")
    db.commit()

    service = task_lease.TaskLeaseService(db)
    store = SequenceStore(path)
    try:
        yield path, db, service, store
    finally:
        db.close()


def _insert_task(db, *, task_id: int, created_by: str, created_at: str) -> None:
    db.execute(
        "INSERT INTO tasks (id, title, status, created_by, created_at) VALUES (?, ?, 'pending', ?, ?)",
        (task_id, f"Aufgabe {task_id}", created_by, created_at),
    )
    db.commit()


def test_ohne_einstellung_sofort_leasbar(prepared):
    """(a) Standard aus: Fremder erhaelt die Lease sofort."""
    _path, db, _service, _store = prepared
    _insert_task(db, task_id=101, created_by="buddha@host-a", created_at=_iso_now())

    client = TaskLeaseClient(conn=db)
    lease = client.acquire(
        task_id=101,
        worker_id="fremd@host-b",
        host="host-b",
        intent="task:101",
    )

    assert lease is not None
    assert lease.worker_id == "fremd@host-b"


def test_einstellung_aktiv_verweigert_fremden(prepared):
    """(b) 120-s-Fenster: Ersteller ja, Fremder nein."""
    path, db, _service, _store = prepared
    _insert_task(db, task_id=202, created_by="buddha@host-a", created_at=_iso_now())

    current = task_lease_settings.read_setting(path)
    task_lease_settings.write_setting(
        {
            "enabled": True,
            "window_seconds": 120,
            "configuration_version": current["configuration_version"],
        },
        actor="tester",
        db_path=path,
    )

    client = TaskLeaseClient(conn=db)

    lease = client.acquire(
        task_id=202,
        worker_id="buddha@host-a",
        host="host-a",
        intent="task:202",
    )
    assert lease.worker_id == "buddha@host-a"

    with pytest.raises(LeaseDeniedError) as excinfo:
        client.acquire(
            task_id=202,
            worker_id="fremd@host-b",
            host="host-b",
            intent="task:202",
        )
    assert excinfo.value.reason == "creator_priority"


def test_sequenz_delegation_haelt_600_sekunden(prepared):
    """(c) Sequenzschritt: 600-s-Gate auch ohne Einstellung."""
    path, db, service, store = prepared

    chain = store.save_chain(
        {
            "name": "Creator-Priority-Kette",
            "mode": "agents",
            "steps": [
                {
                    "label": "Analyse",
                    "agent_slot": "buddha_research",
                    "instructions": "Analysiere den Bestand.",
                }
            ],
        }
    )
    run_id = "run-creator-600"
    store.create_run(run_id, chain["id"], chain["version"], "e" * 64, service, "test", {"steps": [{}]})
    step = store.prepare_step(
        run_id,
        0,
        {"input": "x"},
        f"system-sequence-{run_id}-0",
        "Analyse",
        "Analysiere den Bestand.",
        "model",
        service=service,
    )
    task_id = step["task_id"]

    db.execute(
        "UPDATE tasks SET created_at = ? WHERE id = ?",
        (_iso_now(), task_id),
    )
    db.commit()

    current = task_lease_settings.read_setting(path)
    task_lease_settings.write_setting(
        {
            "enabled": True,
            "window_seconds": 120,
            "configuration_version": current["configuration_version"],
        },
        actor="tester",
        db_path=path,
    )

    client = TaskLeaseClient(conn=db)
    with pytest.raises(LeaseDeniedError) as excinfo:
        client.acquire(
            task_id=task_id,
            worker_id="fremd@host-b",
            host="host-b",
            intent=f"marblerun:{run_id}:0",
        )
    assert excinfo.value.reason == "creator_priority"

    # Sequenz-Tasks (created_by == "user") haben keinen gueltigen Ersteller-Worker;
    # der Schutz greift hier ueber den Sequenzschritt-Fallback von 600 s.
    assert (
        task_lease._creator_window_seconds(db, task_id, task_lease.LeaseConfig.from_env())
        == 600
    )
