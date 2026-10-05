# -*- coding: utf-8 -*-
"""Tests fuer Cluster-Inbound-Delegated-Task-Endpoint in gui/server.py (Task #1661)."""
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
    """Erzeugt ein Cluster-Node-Token fuer den Ziel-Knoten (unbegrenzte Nutzungen)."""
    _, create_cluster_node_token = client
    _, to_node = nodes
    raw_token = f"cluster-token-{uuid.uuid4().hex}-very-secret"
    conn = sqlite3.connect(os.environ["BACH_DB"])
    conn.row_factory = sqlite3.Row
    result = create_cluster_node_token(conn, to_node["id"], raw_token, label="inbound-test-token", uses_left=None)
    conn.close()
    assert result.get("success"), result
    return raw_token, to_node["id"]


_INBOUND_URL = "/api/cluster/inbound/delegated-tasks"


def _inbound_payload(task_id, from_node_id, to_node_id):
    return {
        "original_task_id": task_id,
        "title": "Inbound test task",
        "description": "Created by test_cluster_inbound_tasks.py",
        "from_node_id": from_node_id,
        "to_node_id": to_node_id,
        "priority": "normal",
    }


def test_inbound_delegated_task_success(client, nodes, node_token):
    """Erfolgreicher Inbound mit gueltigem X-Cluster-Node-Token -> 201 + direction='received'."""
    test_client, _ = client
    from_node, to_node = nodes
    raw_token, to_node_id = node_token
    payload = _inbound_payload(f"task-{uuid.uuid4().hex}", from_node["id"], to_node["id"])
    res = test_client.post(_INBOUND_URL, json=payload, headers={"X-Cluster-Node-Token": raw_token})
    assert res.status_code == 201
    data = res.json()
    assert data["task_id"] == payload["original_task_id"]
    assert data["from_node_id"] == from_node["id"]
    assert data["to_node_id"] == to_node_id
    assert data["direction"] == "received"
    assert data["status"] == "pending"


def test_inbound_delegated_task_missing_token(client, nodes):
    """Fehlender Token -> 403."""
    test_client, _ = client
    from_node, to_node = nodes
    payload = _inbound_payload(f"task-{uuid.uuid4().hex}", from_node["id"], to_node["id"])
    res = test_client.post(_INBOUND_URL, json=payload)
    assert res.status_code == 403


def test_inbound_delegated_task_wrong_token(client, nodes):
    """Falscher Token -> 401/403."""
    test_client, _ = client
    from_node, to_node = nodes
    payload = _inbound_payload(f"task-{uuid.uuid4().hex}", from_node["id"], to_node["id"])
    res = test_client.post(_INBOUND_URL, json=payload, headers={"X-Cluster-Node-Token": "wrong-token"})
    assert res.status_code in (401, 403)


def test_inbound_delegated_task_invalid_payload(client, nodes, node_token):
    """Ungueltige Payload (fehlendes Pflichtfeld) -> 422."""
    test_client, _ = client
    from_node, to_node = nodes
    raw_token, _ = node_token
    # `title` ist Pflichtfeld im ClusterInboundDelegatedTask-Modell
    payload = {
        "original_task_id": f"task-{uuid.uuid4().hex}",
        "from_node_id": from_node["id"],
        "to_node_id": to_node["id"],
    }
    res = test_client.post(_INBOUND_URL, json=payload, headers={"X-Cluster-Node-Token": raw_token})
    assert res.status_code == 422


def test_inbound_delegated_task_unknown_to_node(client, nodes, node_token):
    """Unbekannte to_node_id -> 404."""
    test_client, _ = client
    from_node, _ = nodes
    raw_token, _ = node_token
    payload = _inbound_payload(f"task-{uuid.uuid4().hex}", from_node["id"], 99999)
    res = test_client.post(_INBOUND_URL, json=payload, headers={"X-Cluster-Node-Token": raw_token})
    assert res.status_code == 404


def test_inbound_delegated_task_persistence(client, nodes, node_token):
    """Persistenzpruefung via GET /api/cluster/delegated-tasks -> 200 + Eintrag."""
    test_client, _ = client
    from_node, to_node = nodes
    raw_token, to_node_id = node_token
    task_id = f"task-{uuid.uuid4().hex}"
    payload = _inbound_payload(task_id, from_node["id"], to_node_id)
    create_res = test_client.post(_INBOUND_URL, json=payload, headers={"X-Cluster-Node-Token": raw_token})
    assert create_res.status_code == 201
    created = create_res.json()

    list_res = test_client.get(
        "/api/cluster/delegated-tasks",
        params={"node_id": to_node_id, "direction": "received"},
        headers={"X-Cluster-Node-Token": raw_token},
    )
    assert list_res.status_code == 200
    data = list_res.json()
    assert "delegations" in data
    assert any(d["id"] == created["id"] and d["direction"] == "received" for d in data["delegations"])
