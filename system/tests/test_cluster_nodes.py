# -*- coding: utf-8 -*-
"""Tests für Cluster-Node-Endpunkte in gui/server.py (Task #1657)."""
import os
import sys
import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def client():
    """Baut eine temporäre BACH-DB auf, importiert den GUI-Server und liefert TestClient."""
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
    from fastapi.testclient import TestClient

    yield TestClient(app, headers={"Authorization": "Bearer test-control-token"})

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


def _node_payload(name="alpha", url="http://alpha.local"):
    return {
        "name": name,
        "url": url,
        "token": "secret",
        "role": "worker",
        "status": "offline",
        "capabilities": "cpu,gpu",
    }


def test_create_cluster_node(client):
    res = client.post("/api/cluster/nodes", json=_node_payload("node-create", "http://create.local"))
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "node-create"
    assert data["url"] == "http://create.local"
    assert data["role"] == "worker"
    assert data["status"] == "offline"
    assert "id" in data


def test_list_cluster_nodes(client):
    # Zwei weitere Knoten anlegen
    client.post("/api/cluster/nodes", json=_node_payload("node-list-1", "http://list1.local"))
    client.post("/api/cluster/nodes", json=_node_payload("node-list-2", "http://list2.local"))
    res = client.get("/api/cluster/nodes")
    assert res.status_code == 200
    data = res.json()
    assert "nodes" in data
    names = {n["name"] for n in data["nodes"]}
    assert names >= {"node-list-1", "node-list-2"}


def test_get_cluster_node(client):
    created = client.post("/api/cluster/nodes", json=_node_payload("node-get", "http://get.local")).json()
    node_id = created["id"]
    res = client.get(f"/api/cluster/nodes/{node_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == node_id
    assert data["name"] == "node-get"


def test_update_cluster_node(client):
    created = client.post("/api/cluster/nodes", json=_node_payload("node-update", "http://update.local")).json()
    node_id = created["id"]
    res = client.put(
        f"/api/cluster/nodes/{node_id}",
        json={"name": "node-updated", "status": "online"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "node-updated"
    assert data["status"] == "online"
    assert data["url"] == "http://update.local"


def test_delete_cluster_node(client):
    created = client.post("/api/cluster/nodes", json=_node_payload("node-delete", "http://delete.local")).json()
    node_id = created["id"]
    res = client.delete(f"/api/cluster/nodes/{node_id}")
    assert res.status_code == 200
    assert res.json()["status"] == "deleted"
    assert res.json()["id"] == node_id

    res = client.get(f"/api/cluster/nodes/{node_id}")
    assert res.status_code == 404


def test_create_duplicate_returns_409(client):
    payload = _node_payload("node-duplicate", "http://dup.local")
    res1 = client.post("/api/cluster/nodes", json=payload)
    assert res1.status_code == 200
    res2 = client.post("/api/cluster/nodes", json=payload)
    assert res2.status_code == 409
    assert "existiert bereits" in res2.json()["detail"]


def test_get_nonexistent_returns_404(client):
    res = client.get("/api/cluster/nodes/999999")
    assert res.status_code == 404


def test_delete_nonexistent_returns_404(client):
    res = client.delete("/api/cluster/nodes/999999")
    assert res.status_code == 404
