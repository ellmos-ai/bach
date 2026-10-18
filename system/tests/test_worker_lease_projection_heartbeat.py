"""Real isolated acquisition must produce a post-acquire controller observation."""
import socket
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from hub._services import task_lease_client as lease_module
from hub._services.task_lease_client import LeaseDeniedError, TaskLeaseClient

pytest_plugins = ("system.tests.test_task_lease_client",)


@pytest.fixture
def acquisition(monkeypatch, mem_db):
    from hub._services.chat import telegram_chat as controller

    monkeypatch.setattr(lease_module, "get_lead_config", lambda: {"mode": "isolated"})
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    client = TaskLeaseClient(conn=mem_db)
    ctrl = controller._WorkerControl("lease-projection-slot")
    ctrl.physical_worker_id = "lease-projection-process"
    ctrl.lease_worker_id = f"{ctrl.physical_worker_id}@{socket.gethostname()}"
    ctrl.thread = SimpleNamespace(is_alive=lambda: True)
    ctrl.worker_thread_started = True
    ctrl.last_heartbeat_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    monkeypatch.setattr(controller, "_native_task_client", lambda: client)
    monkeypatch.setattr(controller, "_WORKER_CONTROLS", {ctrl.worker_id: ctrl})
    monkeypatch.setattr(controller, "_WORKER_EXECUTIONS", {ctrl.worker_id: ctrl})
    yield controller, ctrl, client, mem_db
    if ctrl.task_binding is not None:
        ctrl.task_binding.return_lease()


def insert_task(connection):
    connection.execute(
        "INSERT INTO tasks (id,title,status,assigned_to) VALUES (42,?, 'pending','BACH')",
        ("Controller heartbeat regression",),
    )
    connection.commit()


def test_confirmed_acquire_projects_lease_before_first_model_call(acquisition, monkeypatch):
    from hub._services import worker_policy_settings
    from hub._services.task_lease import parse_ts

    controller, ctrl, _client, connection = acquisition
    insert_task(connection)
    before = parse_ts(ctrl.last_heartbeat_at)
    ctrl.task_binding = controller._acquire_worker_task(
        ctrl, {"id": ctrl.worker_id, "task_id": 42}, ctrl.physical_worker_id
    )
    row = connection.execute("SELECT * FROM tasks WHERE id=42").fetchone()
    issued = parse_ts(row["claim_issued_at"])
    assert before < issued <= parse_ts(ctrl.last_heartbeat_at)

    @contextmanager
    def isolated_connection(_path):
        yield connection

    monkeypatch.setattr(worker_policy_settings, "_connection", isolated_connection)
    receipt = controller.worker_execution_receipt(ctrl.worker_id, verify_results=False)
    item = {
        "id": ctrl.worker_id, "running": True, "runtime_verified": True,
        "execution": receipt,
    }
    projected, = worker_policy_settings.attach_active_task_leases([item])
    assert projected["active_task_lease"]["task_id"] == 42
    assert projected["active_task_lease"]["fence"] == row["claim_fence"]
    assert projected["active_task_lease"]["lease_id_kind"] == "observation_sha256"
    assert ctrl.task_binding._ack.lease_id not in str(projected)

    # The guard itself remains strict; an observation from before Acquire is invalid.
    stale = {**item, "execution": {**receipt, "heartbeat_at": before.isoformat()}}
    rejected, = worker_policy_settings.attach_active_task_leases([stale])
    assert "active_task_lease" not in rejected


@pytest.mark.parametrize("state", ["empty", "held"])
def test_no_acquisition_does_not_fabricate_post_acquire_observation(acquisition, state):
    controller, ctrl, client, connection = acquisition
    before = ctrl.last_heartbeat_at
    slot = {"id": ctrl.worker_id}
    if state == "held":
        insert_task(connection)
        foreign = client.acquire(
            42, worker_id="foreign@HOST", host="HOST",
            task_version=client.task_snapshot(42)["task_version"],
        )
        slot["task_id"] = 42
        with pytest.raises(LeaseDeniedError):
            controller._acquire_worker_task(ctrl, slot, ctrl.physical_worker_id)
        assert client.read(42, lease_id=foreign.lease_id).own
    else:
        assert controller._acquire_worker_task(ctrl, slot, ctrl.physical_worker_id) is None
    assert ctrl.last_heartbeat_at == before
