"""Exact physical worker lease snapshots must never hide an unknown holder."""
import json
import sqlite3
from datetime import datetime, timezone, timedelta

import pytest

from hub._services import task_lease as leases
from hub._services import task_lease_client as clients
from system.tests.test_task_lease_client import _init_db

T0 = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


@pytest.fixture
def db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    monkeypatch.setattr(leases, "_utcnow", lambda: T0)
    monkeypatch.setattr(clients, "get_lead_config", lambda: {"mode": "isolated"})
    yield conn
    conn.close()


def add(conn, ident, worker, **changes):
    conn.execute("INSERT INTO tasks(id,title,status) VALUES(?,?,'pending')", (ident, "Fixture"))
    conn.commit()
    result = leases.acquire_lease(conn, ident, worker_id=worker, host=worker.split("@")[1],
                                  request_id=f"worker-snapshot-{ident:08d}", now=T0,
                                  config=leases.LeaseConfig(creator_window_seconds=0))
    assert result.payload["granted"] is True
    for name, value in changes.items():
        assert name in {"status", "claim_expires_at", "claimed_at", "claim_id"}
        conn.execute(f"UPDATE tasks SET {name}=? WHERE id=?", (value, ident))
    conn.commit()
    return result.payload


def test_exact_worker_snapshot_is_complete_and_capability_free(db):
    own = add(db, 1, "worker-own@HOST")
    add(db, 2, "worker-other@HOST")
    add(db, 3, "worker-own@HOST", claim_expires_at=(T0-timedelta(seconds=1)).isoformat())
    add(db, 4, "worker-own@HOST", status="blocked")
    result = clients.TaskLeaseClient(conn=db).worker_leases("worker-own@HOST")
    assert result["complete"] is True and result["worker_id"] == "worker-own@HOST"
    assert [row["task_id"] for row in result["leases"]] == [1]
    assert result["leases"][0]["fence"] == 1
    assert own["lease_id"] not in json.dumps(result)
    assert "claim_id" not in json.dumps(result) and "intent" not in json.dumps(result)


def test_unknown_modern_expiry_is_not_an_empty_snapshot(db):
    add(db, 1, "worker-own@HOST", claim_expires_at="invalid")
    with pytest.raises(leases.LeaseValidationError):
        clients.TaskLeaseClient(conn=db).worker_leases("worker-own@HOST")


def test_unknown_legacy_expiry_remains_a_live_holder(db):
    add(db, 1, "worker-own@HOST", claim_id=None, claimed_at="invalid")
    rows = clients.TaskLeaseClient(conn=db).worker_leases("worker-own@HOST")["leases"]
    assert len(rows) == 1 and rows[0]["legacy"] is True and rows[0]["expires_at"] is None


@pytest.mark.parametrize("worker", [None, "", "worker", "worker@host' OR 1=1", "worker@host/evil"])
def test_invalid_worker_identity_rejected_before_read(db, worker):
    with pytest.raises(clients.LeaseProtocolError):
        clients.TaskLeaseClient(conn=db).worker_leases(worker)


@pytest.mark.parametrize("broken", ["complete", "identity", "schema", "time", "duplicate", "lease_fields"])
def test_remote_incomplete_readback_is_rejected(monkeypatch, broken):
    client = clients.TaskLeaseClient(lead_url="http://127.0.0.1:9999")
    data = {"schema": "bach.worker-leases.v1", "worker_id": "worker-own@HOST", "server_now": T0.isoformat(),
            "complete": True, "leases": []}
    if broken == "complete":data["complete"] = False
    elif broken == "identity":data["worker_id"] = "worker-other@HOST"
    elif broken == "schema":data["schema"] = "wrong"
    elif broken == "time":data["server_now"] = "invalid"
    else:
        row = {"task_id": 1, "fence": 1, "expires_at": T0.isoformat(), "legacy": False}
        data["leases"] = [row, dict(row)] if broken == "duplicate" else [{**row,"lease_id":"PRIVATE"}]
    monkeypatch.setattr(client, "_http_request", lambda *a, **k: (200, data))
    with pytest.raises(clients.LeaseProtocolError):
        client.worker_leases("worker-own@HOST")


def test_remote_uses_encoded_identity(monkeypatch):
    client = clients.TaskLeaseClient(lead_url="http://127.0.0.1:9999")
    calls=[]
    data = {"schema": "bach.worker-leases.v1", "worker_id": "worker-own@HOST", "server_now": T0.isoformat(),
            "complete": True, "leases": []}
    def request(method,path):
        calls.append((method,path));return 200,data
    monkeypatch.setattr(client, "_http_request", request)
    assert client.worker_leases("worker-own@HOST")["leases"] == []
    assert calls == [("GET", "/api/tasks/leases/by-worker?worker_id=worker-own%40HOST")]


def test_native_http_route_requires_device_and_returns_exact_snapshot(db, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from gui import server
    add(db, 1, "worker-own@HOST")
    add(db, 2, "worker-other@HOST")
    path = tmp_path / "native.db"
    with sqlite3.connect(path) as target:
        db.backup(target)
    opened = []
    def connect():
        opened.append(True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    monkeypatch.setattr(server, "get_bach_db", connect)
    monkeypatch.setattr(server, "validate_token", lambda token: {"name": "fixture"} if token == "fixture" else None)
    client = TestClient(server.app)
    endpoint = "/api/tasks/leases/by-worker?worker_id=worker-own%40HOST"
    assert client.get(endpoint).status_code == 401
    assert opened == []
    response = client.get(endpoint, headers={"Authorization": "Bearer fixture"})
    assert response.status_code == 200
    assert response.json()["worker_id"] == "worker-own@HOST"
    assert response.json()["complete"] is True
    assert [row["task_id"] for row in response.json()["leases"]] == [1]
    assert set(response.json()["leases"][0]) == {"task_id", "fence", "expires_at", "legacy"}
