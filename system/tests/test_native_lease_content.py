"""Task1729: isolated canonical content and atomic leased-update evidence."""
import sqlite3
from datetime import timedelta

import pytest

from system.tests.test_task_lease_client import mem_db, _insert_task
from system.tests.test_task_lease_client_review import T0
from hub._services import task_lease_client as client_module
from hub._services.task_lease_client import TaskLeaseClient, LeaseError


def acquire(client, task_id):
    snapshot = client.task_snapshot(task_id)
    return client.acquire(task_id, worker_id="worker@HOST", host="HOST",
                          task_version=snapshot["task_version"], now=T0)


def test_snapshot_never_exposes_lease_capability(mem_db):
    tid = _insert_task(mem_db)
    client = TaskLeaseClient(conn=mem_db)
    ack = acquire(client, tid)
    snapshot = client.task_snapshot(tid)
    assert snapshot["task_version"] == ack.task_version
    assert not {"claim_id", "claim_request_id", "claim_task_version"} & snapshot.keys()
    assert ack.lease_id not in str(snapshot)


def test_snapshot_accepts_tuple_connection(tmp_path, monkeypatch):
    monkeypatch.setattr(client_module, "get_lead_config", lambda: {"mode": "isolated"})
    conn = sqlite3.connect(tmp_path / "isolated.db")
    conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT, status TEXT)")
    conn.execute("INSERT INTO tasks VALUES (1, 'Canonical', 'pending')")
    conn.commit()
    try:
        assert TaskLeaseClient(conn=conn).task_snapshot(1)["title"] == "Canonical"
    finally:
        conn.close()


def test_atomic_update_rebinds_version_and_allows_release(mem_db):
    tid = _insert_task(mem_db)
    client = TaskLeaseClient(conn=mem_db)
    ack = acquire(client, tid)
    changed = client.update(tid, lease_id=ack.lease_id, fence=ack.fence,
                            task_version=ack.task_version,
                            changes={"description": "Überarbeiteter Auftrag"}, now=T0)
    assert changed.task_version != ack.task_version
    assert changed.fence == ack.fence
    assert client.task_snapshot(tid)["description"] == "Überarbeiteter Auftrag"
    assert client._held[tid].task_version == changed.task_version
    with pytest.raises(LeaseError):
        client.update(tid, lease_id=ack.lease_id, fence=ack.fence,
                      task_version=ack.task_version, changes={"title": "Stale"}, now=T0)
    client.release(tid, lease_id=ack.lease_id, fence=ack.fence,
                   task_version=changed.task_version, outcome="return", now=T0)


@pytest.mark.parametrize("changes", [{"status": "done"}, {"claim_id": "x"},
                                     {"title": ""}, {"description": 4}, {},
                                     {"title": "Valid", "unknown": "x"}])
def test_invalid_update_is_atomic(mem_db, changes):
    tid = _insert_task(mem_db)
    client = TaskLeaseClient(conn=mem_db)
    ack = acquire(client, tid)
    before = client.task_snapshot(tid)
    with pytest.raises(LeaseError):
        client.update(tid, lease_id=ack.lease_id, fence=ack.fence,
                      task_version=ack.task_version, changes=changes, now=T0)
    assert client.task_snapshot(tid) == before


def test_expired_update_does_not_write(mem_db):
    tid = _insert_task(mem_db)
    client = TaskLeaseClient(conn=mem_db)
    ack = acquire(client, tid)
    before = client.task_snapshot(tid)
    with pytest.raises(LeaseError):
        client.update(tid, lease_id=ack.lease_id, fence=ack.fence,
                      task_version=ack.task_version, changes={"title": "Too late"},
                      now=T0 + timedelta(days=1))
    assert client.task_snapshot(tid) == before


def test_remote_snapshot_never_opens_projection(mem_db, monkeypatch):
    monkeypatch.setattr(client_module, "get_lead_config",
                        lambda: {"mode": "worker", "lead_url": "http://lead.invalid"})
    client = TaskLeaseClient(conn=mem_db, device_token="test-device")
    monkeypatch.setattr(client, "_get_local_connection", lambda: pytest.fail("projection opened"))
    calls = []
    def transport(method, path, *args, **kwargs):
        calls.append((method, path))
        return 200, {"id": 7, "title": "Lead", "task_version": "a" * 64,
                     "claim_id": "must-not-leak", "claim_request_id": "secret"}
    monkeypatch.setattr(client, "_http_request", transport)
    assert client.task_snapshot(7) == {"id": 7, "title": "Lead", "task_version": "a" * 64}
    assert calls == [("GET", "/api/tasks/7")]


@pytest.mark.parametrize("payload", [{"id": 8, "task_version": "a" * 64},
                                    {"id": 7}, {"id": 7, "task_version": "bad"}])
def test_remote_snapshot_rejects_bad_identity_or_version(monkeypatch, payload):
    client = TaskLeaseClient(lead_url="http://lead.invalid", device_token="test-device")
    monkeypatch.setattr(client, "_http_request", lambda *a, **kw: (200, payload))
    with pytest.raises(LeaseError):
        client.task_snapshot(7)


def test_canonical_candidate_pages_include_expired_work_not_terminal_tasks(mem_db):
    pending = _insert_task(mem_db, title="pending", status="pending")
    active = _insert_task(mem_db, title="active", status="in_progress")
    _insert_task(mem_db, title="done", status="done")
    client = TaskLeaseClient(conn=mem_db)
    first = client.task_candidates(limit=1)
    assert first["has_more"] is True
    second = client.task_candidates(limit=1, offset=1)
    assert second["has_more"] is False
    assert {first["tasks"][0]["id"], second["tasks"][0]["id"]} == {pending, active}
    assert all(len(page["tasks"][0]["task_version"]) == 64 for page in (first, second))


def test_remote_candidate_pages_use_lead_only(mem_db, monkeypatch):
    monkeypatch.setattr(client_module, "get_lead_config",
                        lambda: {"mode": "worker", "lead_url": "http://lead.invalid"})
    client = TaskLeaseClient(conn=mem_db, device_token="test-device")
    monkeypatch.setattr(client, "_get_local_connection", lambda: pytest.fail("projection opened"))
    calls = []
    def transport(method, path):
        calls.append((method, path))
        return 200, {"success": True, "tasks": [{"id": 7, "task_version": "a" * 64}],
                     "has_more": False, "count": 1, "total": 1, "offset": 0}
    monkeypatch.setattr(client, "_http_request", transport)
    assert client.task_candidates(limit=25)["tasks"][0]["id"] == 7
    assert calls[0][0] == "GET" and calls[0][1].startswith("/api/tasks?")
    assert "limit=25" in calls[0][1]


@pytest.mark.parametrize("limit,offset", [(0, 0), (101, 0), (True, 0), (20, -1)])
def test_candidate_page_bounds_are_strict(mem_db, limit, offset):
    with pytest.raises(LeaseError):
        TaskLeaseClient(conn=mem_db).task_candidates(limit=limit, offset=offset)
