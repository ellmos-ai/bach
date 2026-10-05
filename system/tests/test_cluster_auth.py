# -*- coding: utf-8 -*-
"""Tests fuer Cluster-Node-Authentifizierung & Token-Validation (Task #1659)."""
import os
import sys
import sqlite3
import tempfile
from pathlib import Path

import pytest
import uuid


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
    from system.gui.task_db import create_cluster_node_token, validate_cluster_node_token
    from fastapi.testclient import TestClient

    yield TestClient(app, headers={"Authorization": "Bearer test-control-token"}), create_cluster_node_token, validate_cluster_node_token

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


@pytest.fixture
def node(client):
    """Legt einen Cluster-Knoten an und liefert dessen Daten."""
    test_client, _, _ = client
    payload = {
        "name": f"auth-test-node-{uuid.uuid4().hex[:8]}",
        "url": "http://auth.local",
        "token": "legacy-secret",
        "role": "worker",
        "status": "offline",
        "capabilities": "cpu",
    }
    res = test_client.post("/api/cluster/nodes", json=payload)
    if res.status_code == 409:
        # aufräumen falls ein zufälliger Name doch kollidiert
        existing = test_client.get("/api/cluster/nodes").json()
        for n in existing:
            if n["name"].startswith("auth-test-node-"):
                test_client.delete(f"/api/cluster/nodes/{n['id']}")
        res = test_client.post("/api/cluster/nodes", json=payload)
    assert res.status_code == 200
    return res.json()


@pytest.fixture
def node_token(client, node):
    """Erzeugt ein Cluster-Node-Token und liefert (rohes Token, Token-Metadaten)."""
    _, create_cluster_node_token, _ = client
    raw_token = f"cluster-token-{uuid.uuid4().hex}-very-secret"
    conn = sqlite3.connect(os.environ["BACH_DB"])
    conn.row_factory = sqlite3.Row
    result = create_cluster_node_token(conn, node["id"], raw_token, label="test-token")
    conn.close()
    assert result.get("success"), result
    return raw_token, result["token"]


def test_create_and_validate_token(client, node):
    _, create_cluster_node_token, validate_cluster_node_token = client
    raw_token = "a-brand-new-token"
    conn = sqlite3.connect(os.environ["BACH_DB"])
    conn.row_factory = sqlite3.Row
    create_result = create_cluster_node_token(conn, node["id"], raw_token, label="validate-me")
    assert create_result["success"]
    assert create_result["token"]["node_id"] == node["id"]
    assert create_result["token"]["label"] == "validate-me"

    validate_result = validate_cluster_node_token(conn, node["id"], raw_token)
    assert validate_result["success"]
    assert "last_seen" in validate_result
    conn.close()


def test_register_node_success(client, node, node_token):
    test_client, _, _ = client
    raw_token, token_meta = node_token
    res = test_client.post(
        f"/api/cluster/nodes/{node['id']}/register",
        json={"token": raw_token},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["node_id"] == node["id"]
    assert "last_seen" in data


def test_register_node_fail_wrong_token(client, node):
    test_client, _, _ = client
    res = test_client.post(
        f"/api/cluster/nodes/{node['id']}/register",
        json={"token": "definitely-wrong-token"},
    )
    assert res.status_code == 401
    assert "Ungueltiges Token" in res.json()["detail"]


def test_heartbeat_protected(client, node, node_token):
    test_client, _, _ = client
    raw_token, _ = node_token
    node_id = node["id"]

    # Ohne Token verweigert
    res = test_client.post(f"/api/cluster/nodes/{node_id}/heartbeat")
    assert res.status_code == 403

    # Mit Header erfolgreich
    res = test_client.post(
        f"/api/cluster/nodes/{node_id}/heartbeat",
        headers={"X-Cluster-Node-Token": raw_token},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["node_id"] == node_id
    assert "last_seen" in data

    # GET-Variante ebenfalls geschützt
    res = test_client.get(
        f"/api/cluster/nodes/{node_id}/heartbeat",
        headers={"X-Cluster-Node-Token": raw_token},
    )
    assert res.status_code == 200


def test_active_protected(client, node, node_token):
    test_client, _, _ = client
    raw_token, _ = node_token
    node_id = node["id"]

    # Ohne Token verweigert
    res = test_client.get(f"/api/cluster/nodes/{node_id}/active")
    assert res.status_code == 403

    # Mit Header erfolgreich
    res = test_client.get(
        f"/api/cluster/nodes/{node_id}/active",
        headers={"X-Cluster-Node-Token": raw_token},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["active"] is True
    assert data["node_id"] == node_id

    # POST-Variante ebenfalls geschützt
    res = test_client.post(
        f"/api/cluster/nodes/{node_id}/active",
        headers={"X-Cluster-Node-Token": raw_token},
    )
    assert res.status_code == 200


def test_active_wrong_node_token(client, node, node_token):
    test_client, _, _ = client
    raw_token, _ = node_token

    # Anderer Knoten existiert nicht: 404, da Path-Parameter zuerst geprüft wird
    res = test_client.get(
        "/api/cluster/nodes/99999/active",
        headers={"X-Cluster-Node-Token": raw_token},
    )
    assert res.status_code in (401, 403, 404)
