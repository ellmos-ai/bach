# -*- coding: utf-8 -*-
"""Tests fuer Cluster-Delegated-Task-Endpunkte in gui/server.py (Task #1660)."""
import os
import sys
import sqlite3
import tempfile
from pathlib import Path

import pytest
import uuid


@pytest.fixture(scope="module")
def client():
    """Baut eine temporaere BACH-DB auf, importiert den GUI-Server und liefert TestClient."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    original_db = os.environ.get("BACH_DB")
    os.environ["BACH_DB"] = db_path
    original_control_token = os.environ.get("BACH_CONTROL_API_TOKEN")
    os.environ["BACH_CONTROL_API_TOKEN"] = "test-control-token"

    for name in list(sys.modules.keys()):
        if "gui.server" in name or "hub.bach_paths" in name:
            sys.modules.pop(name, None)

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    for name in list(sys.modules.keys()):
        if name == "gui" or name.startswith("gui."):
            sys.modules.pop(name, None)

    from system.gui.server import app
    from system.gui.task_db import create_cluster_node_token
    from fastapi.testclient import TestClient

    yield TestClient(app, headers={"Authorization": "Bearer test-control-token"}), create_cluster_node_token

    if original_db is None:
        os.environ.pop("BACH_DB", None)
    else:
        os.environ["BACH_DB"] = original_db
    if original_control_token is None:
        os.environ.pop("BACH_CONTROL_API_TOKEN", None)
    else:
        os.environ["BACH_CONTROL_API_TOKEN"] = original_control_token
    sys.modules.pop("hub.bach_paths", None)
    try:
        os.unlink(db_path)
    except FileNotFoundError:
        pass


def _node_payload(name, url="http://example.local"):
    return {
        "name": name,
        "url": url,
        "token": "legacy-secret",
        "role": "worker",
        "status": "offline",
        "capabilities": "cpu",
    }


@pytest.fixture
def nodes(client):
    """Legt zwei Cluster-Knoten an und liefert deren Daten."""
    test_client, _ = client
    from_node = test_client.post("/api/cluster/nodes", json=_node_payload(f"from-{uuid.uuid4().hex[:8]}")).json()
    to_node = test_client.post("/api/cluster/nodes", json=_node_payload(f"to-{uuid.uuid4().hex[:8]}")).json()
    return from_node, to_node


@pytest.fixture
def node_token(client, nodes):
    """Erzeugt ein Cluster-Node-Token fuer den Ziel-Knoten."""
    _, create_cluster_node_token = client
    _, to_node = nodes
    raw_token = f"cluster-token-{uuid.uuid4().hex}-very-secret"
    conn = sqlite3.connect(os.environ["BACH_DB"])
    conn.row_factory = sqlite3.Row
    result = create_cluster_node_token(conn, to_node["id"], raw_token, label="delegation-test-token")
    conn.close()
    assert result.get("success"), result
    return raw_token, to_node["id"]


@pytest.fixture
def delegation(client, nodes, node_token):
    """Erstellt eine delegierte Task und liefert deren Daten."""
    test_client, _ = client
    from_node, to_node = nodes
    raw_token, _ = node_token
    payload = {
        "task_id": f"task-{uuid.uuid4().hex}",
        "from_node_id": from_node["id"],
        "to_node_id": to_node["id"],
        "payload": '{"foo": "bar"}',
    }
    res = test_client.post(
        "/api/cluster/delegated-tasks",
        json=payload,
        headers={"X-Cluster-Node-Token": raw_token},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["task_id"] == payload["task_id"]
    assert data["from_node_id"] == from_node["id"]
    assert data["to_node_id"] == to_node["id"]
    assert data["status"] == "pending"
    return data


def test_create_delegation_missing_token(client, nodes):
    test_client, _ = client
    from_node, to_node = nodes
    res = test_client.post(
        "/api/cluster/delegated-tasks",
        json={
            "task_id": f"task-{uuid.uuid4().hex}",
            "from_node_id": from_node["id"],
            "to_node_id": to_node["id"],
        },
    )
    assert res.status_code == 403


def test_create_delegation_wrong_token(client, nodes):
    test_client, _ = client
    from_node, to_node = nodes
    res = test_client.post(
        "/api/cluster/delegated-tasks",
        json={
            "task_id": f"task-{uuid.uuid4().hex}",
            "from_node_id": from_node["id"],
            "to_node_id": to_node["id"],
        },
        headers={"X-Cluster-Node-Token": "wrong-token"},
    )
    assert res.status_code in (401, 403)


def test_list_delegations(client, nodes, node_token, delegation):
    test_client, _ = client
    raw_token, to_node_id = node_token
    res = test_client.get(
        "/api/cluster/delegated-tasks",
        params={"node_id": to_node_id, "direction": "received"},
        headers={"X-Cluster-Node-Token": raw_token},
    )
    assert res.status_code == 200
    data = res.json()
    assert "delegations" in data
    assert any(d["id"] == delegation["id"] for d in data["delegations"])


def test_list_delegations_missing_token(client, nodes, delegation):
    test_client, _ = client
    _, to_node = nodes
    res = test_client.get(
        "/api/cluster/delegated-tasks",
        params={"node_id": to_node["id"], "direction": "received"},
    )
    assert res.status_code == 403


def test_get_delegation(client, nodes, node_token, delegation):
    test_client, _ = client
    raw_token, to_node_id = node_token
    res = test_client.get(
        f"/api/cluster/delegated-tasks/{delegation['id']}",
        params={"node_id": to_node_id},
        headers={"X-Cluster-Node-Token": raw_token},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == delegation["id"]
    assert data["task_id"] == delegation["task_id"]


def test_get_delegation_not_found(client, nodes, node_token):
    test_client, _ = client
    raw_token, to_node_id = node_token
    res = test_client.get(
        "/api/cluster/delegated-tasks/999999",
        params={"node_id": to_node_id},
        headers={"X-Cluster-Node-Token": raw_token},
    )
    assert res.status_code == 404


def test_update_delegation(client, nodes, node_token, delegation):
    test_client, _ = client
    raw_token, to_node_id = node_token
    res = test_client.put(
        f"/api/cluster/delegated-tasks/{delegation['id']}",
        json={"status": "accepted"},
        params={"node_id": to_node_id},
        headers={"X-Cluster-Node-Token": raw_token},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "accepted"
    assert data["accepted_at"] is not None

    res = test_client.put(
        f"/api/cluster/delegated-tasks/{delegation['id']}",
        json={"status": "completed", "result": "done"},
        params={"node_id": to_node_id},
        headers={"X-Cluster-Node-Token": raw_token},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "completed"
    assert data["result"] == "done"
    assert data["completed_at"] is not None


def test_update_delegation_empty_body(client, nodes, node_token, delegation):
    test_client, _ = client
    raw_token, to_node_id = node_token
    res = test_client.put(
        f"/api/cluster/delegated-tasks/{delegation['id']}",
        json={},
        params={"node_id": to_node_id},
        headers={"X-Cluster-Node-Token": raw_token},
    )
    assert res.status_code == 400


def test_update_delegation_not_found(client, nodes, node_token):
    test_client, _ = client
    raw_token, to_node_id = node_token
    res = test_client.put(
        "/api/cluster/delegated-tasks/999999",
        json={"status": "failed"},
        params={"node_id": to_node_id},
        headers={"X-Cluster-Node-Token": raw_token},
    )
    assert res.status_code == 404
