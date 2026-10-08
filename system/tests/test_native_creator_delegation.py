"""Private sequence Creator delegation with real SQLite leases and the normal 10-minute gate."""
import inspect
import json
import sqlite3
import sys
import threading
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from hub._services import task_lease, task_lease_client
from hub._services.chat.sequence_store import SequenceConflict, SequenceStore
from hub._services.chat.native_sequences import _SequenceCreatorAuthority
from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
from hub._services.task_lease_client import TaskLeaseClient, LeaseConnectionError, LeaseDeniedError, LeaseProtocolError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from system.tests.test_task_lease_client import _init_db


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.delenv("BACH_TASK_LEASE_CREATOR_WINDOW", raising=False)
    monkeypatch.setattr(task_lease_client, "get_lead_config", lambda: {"mode": "isolated"})
    assert task_lease.LeaseConfig.from_env().creator_window_seconds == 600
    path = tmp_path / "authority.db"
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    _init_db(db)
    db.execute("ALTER TABLE tasks ADD COLUMN created_at TEXT")
    db.commit()
    store = SequenceStore(path)
    chain = store.save_chain({"name": "private-grant", "mode": "agents", "steps": [
        {"label": "Analyse", "agent_slot": "buddha_research", "instructions": "Isolierter Auftrag"}]})
    run_id, service, request = "a"*32, "b"*32, "c"*32
    store.create_run(run_id, chain["id"], chain["version"], "e"*64, service, "test", {"steps": [{}]})
    slot_id = f"system-sequence-{run_id}-0"
    step = store.prepare_step(run_id, 0, request, slot_id, "Analyse", "Isolierter Auftrag", "model", service=service)
    yield SimpleNamespace(store=store, db=db, client=TaskLeaseClient(conn=db), step=step, run_id=run_id,
        service=service, request=request, slot_id=slot_id, generation="d"*32,
        worker="worker-"+uuid.uuid4().hex+"@test", host="test")
    db.close()


def bind(p):
    return p.store.bind_creator_delegation(p.run_id, 0, p.service,
        task_id=p.step["task_id"], slot_id=p.slot_id, start_request_id=p.request,
        generation=p.generation, worker_id=p.worker, host=p.host)


def redeem(p, delegation, *, client=None, now=None):
    return (client or p.client)._acquire_native_creator(delegation.task_id, delegation=delegation,
        worker_id=delegation.worker_id, host=delegation.host, task_version=delegation.task_version, now=now)


def grant(p):
    return dict(p.db.execute("SELECT * FROM native_sequence_creator_delegations").fetchone())


def test_normal_creator_gate_and_public_signature_remain_unchanged(prepared):
    p = prepared
    with pytest.raises(LeaseDeniedError) as denied:
        p.client.acquire(p.step["task_id"], worker_id=p.worker, host=p.host,
            intent=f"marblerun:{p.run_id}:0")
    assert denied.value.reason == "creator_priority"
    assert "creator_delegation" not in inspect.signature(task_lease.acquire_lease).parameters
    assert grant(p)["consumed_at"] is None


def test_bound_generation_gets_one_grant_without_spoofing_task_creator(prepared):
    p = prepared
    delegation = bind(p)
    ack = redeem(p, delegation)
    saved = grant(p)
    task = dict(p.db.execute("SELECT * FROM tasks").fetchone())
    assert task["created_by"] == task["creation_origin"] == "user"
    assert task["claimed_by"] == p.worker and task["claim_fence"] == 1
    assert saved["task_version"] == delegation.task_version and saved["generation"] == p.generation
    assert saved["consumed_at"] and saved["consumed_fence"] == 1
    audit = json.loads(p.db.execute("SELECT new_value FROM task_history WHERE action='lease_acquire'").fetchone()[0])
    assert audit["creator_delegation"]["run_id"] == p.run_id
    assert audit["creator_delegation"]["generation"] == p.generation
    assert ack.lease_id not in json.dumps(saved) + json.dumps(audit)
    snapshot = p.client.task_snapshot(ack.task_id)
    assert "creator_delegation" not in snapshot and "claim_id" not in snapshot


@pytest.mark.parametrize("field,value", [
    ("run_id", "f"*32), ("cursor", 1), ("task_id", 999),
    ("task_version", "f"*64), ("slot_id", "another-slot"), ("start_request_id", "f"*32),
    ("service_instance", "f"*32), ("generation", "f"*32),
    ("worker_id", "other@test"), ("host", "other"), ("acquire_request_id", "f"*64)])
def test_private_redemption_requires_every_exact_persisted_identity(prepared, field, value):
    p = prepared
    delegation = replace(bind(p), **{field: value})
    with pytest.raises((LeaseDeniedError, LeaseProtocolError)):
        redeem(p, delegation)
    assert grant(p)["consumed_at"] is None
    assert p.db.execute("SELECT claim_fence FROM tasks").fetchone()[0] == 0


@pytest.mark.parametrize("field,value", [("generation", "f"*32), ("worker_id", "other@test")])
def test_grant_cannot_rebind_to_a_second_physical_run(prepared, field, value):
    p = prepared
    original = bind(p)
    args = dict(task_id=p.step["task_id"], slot_id=p.slot_id, start_request_id=p.request,
        generation=p.generation, worker_id=p.worker, host=p.host)
    args[field] = value
    with pytest.raises(SequenceConflict):
        p.store.bind_creator_delegation(p.run_id, 0, p.service, **args)
    assert bind(p) == original


def test_live_ack_replay_uses_same_request_lease_fence_and_audit(prepared, monkeypatch):
    p = prepared
    delegation = bind(p)
    original = p.client._grant
    def lost(*args, **kwargs):
        raise LeaseConnectionError("Lost ACK after commit")
    monkeypatch.setattr(p.client, "_grant", lost)
    with pytest.raises(LeaseConnectionError):
        redeem(p, delegation)
    monkeypatch.setattr(p.client, "_grant", original)
    ack = redeem(p, bind(p))
    assert ack.replayed and ack.fence == 1
    again = redeem(p, delegation)
    assert again.lease_id == ack.lease_id and again.fence == 1
    assert p.db.execute("SELECT COUNT(*) FROM task_history WHERE action='lease_acquire'").fetchone()[0] == 1
    assert grant(p)["consumed_fence"] == 1


def test_consumed_grant_never_creates_another_lease_even_after_creator_window(prepared):
    p = prepared
    delegation = bind(p)
    ack = redeem(p, delegation)
    p.client.release(ack.task_id, lease_id=ack.lease_id, fence=ack.fence,
        task_version=ack.task_version, outcome="return")
    with pytest.raises(LeaseDeniedError) as denied:
        redeem(p, delegation, now=datetime.now(timezone.utc)+timedelta(minutes=11))
    assert denied.value.reason == "creator_delegation_consumed"
    assert p.db.execute("SELECT claim_fence FROM tasks").fetchone()[0] == 1


@pytest.mark.parametrize("gate", ["status", "holder", "legacy", "dependency", "content"])
def test_delegation_preserves_existing_claimability_gates(prepared, gate):
    p = prepared
    delegation = bind(p)
    if gate == "status":
        p.db.execute("UPDATE tasks SET status='blocked'")
        reason = "not_claimable"
    elif gate == "holder":
        p.client.acquire(p.step["task_id"], worker_id="user@test", host="test")
        reason = "held"
    elif gate == "legacy":
        p.db.execute("UPDATE tasks SET status='in_progress',claimed_by='legacy',claimed_at=?",
            (datetime.now(timezone.utc).isoformat(),))
        reason = "held"
    elif gate == "dependency":
        # Fixture represents a grant created for a task that already has a missing dependency.
        p.db.execute("UPDATE tasks SET depends_on='999'")
        row = dict(p.db.execute("SELECT * FROM tasks").fetchone())
        version = task_lease.task_content_version(row)
        p.db.execute("UPDATE native_sequence_creator_delegations SET task_version=?", (version,))
        delegation = replace(delegation, task_version=version)
        reason = "not_claimable"
    else:
        p.db.execute("UPDATE tasks SET description='Changed content'")
        reason = "stale_task_version"
    p.db.commit()
    with pytest.raises(LeaseDeniedError) as denied:
        redeem(p, delegation)
    assert denied.value.reason == reason and grant(p)["consumed_at"] is None


@pytest.mark.parametrize("when", ["before_binding", "after_binding"])
def test_stop_revokes_unused_authority_before_any_later_acquire(prepared, when):
    p = prepared
    delegation = bind(p) if when == "after_binding" else None
    p.store.stop(p.run_id, p.service)
    assert p.store.run(p.run_id)["stop_requested"] == 1 and grant(p)["revoked_at"]
    if delegation is None:
        with pytest.raises(SequenceConflict):
            bind(p)
    else:
        with pytest.raises(LeaseDeniedError) as denied:
            redeem(p, delegation)
        assert denied.value.reason == "creator_delegation_revoked"
    assert p.db.execute("SELECT claim_fence FROM tasks").fetchone()[0] == 0


def test_stop_and_grant_revocation_roll_back_together(prepared):
    p = prepared
    bind(p)
    p.db.execute("""CREATE TRIGGER reject_revocation BEFORE UPDATE ON native_sequence_creator_delegations
        WHEN NEW.revoked_at IS NOT NULL BEGIN SELECT RAISE(ABORT,'fixture'); END""")
    p.db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        p.store.stop(p.run_id, p.service)
    assert p.store.run(p.run_id)["stop_requested"] == 0 and grant(p)["revoked_at"] is None


def test_failed_audit_rolls_back_lease_fence_and_grant_consumption(prepared):
    p = prepared
    delegation = bind(p)
    p.db.execute("""CREATE TRIGGER reject_audit BEFORE INSERT ON task_history
        BEGIN SELECT RAISE(ABORT,'fixture'); END""")
    p.db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        redeem(p, delegation)
    assert grant(p)["consumed_at"] is None and grant(p)["consumed_fence"] is None
    task = p.db.execute("SELECT status,claim_fence,claim_id FROM tasks").fetchone()
    assert tuple(task) == ("pending", 0, None)


def test_remote_role_never_opens_or_transmits_a_creator_grant(prepared, monkeypatch):
    p = prepared
    delegation = bind(p)
    client = TaskLeaseClient(lead_url="http://lead.test")
    def forbidden(*args, **kwargs):
        pytest.fail("private creator authority reached network or projection")
    monkeypatch.setattr(client, "_http_request", forbidden)
    monkeypatch.setattr(client, "_get_local_connection", forbidden)
    with pytest.raises(LeaseProtocolError):
        redeem(p, delegation, client=client)
    assert grant(p)["consumed_at"] is None


def test_actual_controller_binds_current_generation_and_physical_id_before_first_acquire(prepared, monkeypatch):
    from hub._services.chat import telegram_chat as controller
    p = prepared
    authority = _SequenceCreatorAuthority(p.store, p.run_id, 0, p.service)
    control = controller._WorkerControl(p.slot_id, generation=p.generation,
        start_request_id=p.request, sequence_creator_authority=authority)
    slot = {"id": p.slot_id, "task_id": p.step["task_id"], "system": True, "backend": "ollama",
        "model": "model", "enabled": True, "require_assigned_slot": True}
    monkeypatch.setattr(controller, "_WORKER_CONTROLS", {p.slot_id: control})
    monkeypatch.setattr(controller, "_native_task_client", lambda: p.client)
    monkeypatch.setattr(controller, "_execution_slot_reader", lambda _: lambda: slot)
    monkeypatch.setattr(controller.socket, "gethostname", lambda: p.host)
    binding = controller._acquire_worker_task(control, slot, p.worker.rsplit("@", 1)[0])
    assert binding.task_id == p.step["task_id"] and binding.generation == control.generation
    assert grant(p)["worker_id"] == p.worker and grant(p)["consumed_fence"] == 1
    assert "_creator_authority" not in inspect.signature(controller.start_worker_execution).parameters


def test_stale_or_stopped_controller_cannot_bind_a_grant(prepared, monkeypatch):
    from hub._services.chat import telegram_chat as controller
    p = prepared
    control = controller._WorkerControl(p.slot_id, start_request_id=p.request,
        sequence_creator_authority=_SequenceCreatorAuthority(p.store, p.run_id, 0, p.service))
    monkeypatch.setattr(controller, "_native_task_client", lambda: p.client)
    monkeypatch.setattr(controller, "_WORKER_CONTROLS", {})
    with pytest.raises(RuntimeError):
        controller._acquire_worker_task(control, {"task_id": p.step["task_id"]}, "worker-"+uuid.uuid4().hex)
    assert grant(p)["generation"] is None


def test_racing_stop_serializes_after_acquire_consumption(prepared):
    p = prepared
    delegation = bind(p)
    held, release, stop_started, stopped = (threading.Event() for _ in range(4))
    outcomes, errors = [], []
    class HeldConnection(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql.lstrip().startswith("UPDATE tasks") and "claim_id = ?" in sql:
                held.set()
                assert release.wait(5)
            return super().execute(sql, *args)
    def acquire():
        conn = sqlite3.connect(p.store.path, factory=HeldConnection)
        conn.row_factory = sqlite3.Row
        try:
            outcomes.append(redeem(p, delegation, client=TaskLeaseClient(conn=conn)))
        except BaseException as exc:
            errors.append(exc)
        finally:
            conn.close()
    stopping = SequenceStore(p.store.path, write_guard=stop_started.set)
    def stop():
        try:
            stopping.stop(p.run_id, p.service)
            stopped.set()
        except BaseException as exc:
            errors.append(exc)
    acquirer = threading.Thread(target=acquire)
    stopper = threading.Thread(target=stop)
    acquirer.start()
    try:
        assert held.wait(5)
        stopper.start()
        assert stop_started.wait(5) and not stopped.is_set()
    finally:
        release.set()
        acquirer.join(5)
        if stopper.ident is not None:
            stopper.join(5)
    assert not errors and len(outcomes) == 1 and outcomes[0].fence == 1 and stopped.is_set()
    assert p.store.run(p.run_id)["stop_requested"] == 1 and grant(p)["consumed_fence"] == 1
    with pytest.raises(LeaseDeniedError) as denied:
        redeem(p, delegation)
    assert denied.value.reason == "creator_delegation_revoked"
