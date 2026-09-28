"""Tests for system/gui/device_auth.py and device token authentication."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SYSTEM = Path(__file__).resolve().parent.parent
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

from gui.device_auth import (
    DEVICES_TABLE_SCHEMA,
    create_device,
    delete_device_token,
    get_device,
    get_device_token,
    has_active_devices,
    init_devices_db,
    list_devices,
    revoke_device,
    store_device_token,
    validate_token,
)
from gui.server import app


class MemoryKeyring:
    """Minimal in-memory keyring mock."""

    priority = 1

    def __init__(self):
        self.values = {}

    def get_keyring(self):
        return self

    def get_password(self, service, key):
        return self.values.get((service, key))

    def set_password(self, service, key, value):
        self.values[(service, key)] = value

    def delete_password(self, service, key):
        self.values.pop((service, key), None)


@pytest.fixture
def db_conn(tmp_path):
    """Isolated SQLite connection with devices table."""
    db_file = tmp_path / "test_devices.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute(DEVICES_TABLE_SCHEMA)
    conn.commit()
    yield conn
    conn.close()


def test_create_device_and_validate(db_conn):
    """Creating a device yields a plaintext token that validates successfully."""
    token = create_device("MacBook-Pro", connection=db_conn)
    assert token
    assert isinstance(token, str)
    assert len(token) >= 32

    # Database contains hash, not the plaintext token
    row = db_conn.execute("SELECT * FROM devices WHERE name = 'MacBook-Pro'").fetchone()
    assert row is not None
    assert row["name"] == "MacBook-Pro"
    assert row["status"] == "active"
    assert row["token_hash"] != token
    assert len(row["token_hash"]) == 64  # SHA-256 hex

    # Validate token
    validated = validate_token(token, connection=db_conn)
    assert validated is not None
    assert validated["name"] == "MacBook-Pro"
    assert validated["status"] == "active"
    assert validated["last_seen_at"] is not None


def test_validate_token_invalid_or_empty(db_conn):
    """Validating wrong, empty, or revoked token returns None."""
    create_device("TestDevice", connection=db_conn)
    assert validate_token("wrong-token", connection=db_conn) is None
    assert validate_token("", connection=db_conn) is None
    assert validate_token(None, connection=db_conn) is None


def test_duplicate_device_name_rejected(db_conn):
    """Registering the same device name twice raises ValueError."""
    create_device("Workstation", connection=db_conn)
    with pytest.raises(ValueError, match="existiert bereits"):
        create_device("Workstation", connection=db_conn)


def test_revoke_device(db_conn):
    """Revoking a device deactivates its token immediately."""
    token = create_device("Tablet", connection=db_conn)
    assert validate_token(token, connection=db_conn) is not None

    revoked = revoke_device("Tablet", connection=db_conn)
    assert revoked is True

    # Validating now returns None
    assert validate_token(token, connection=db_conn) is None

    # Status in DB is revoked
    dev = get_device("Tablet", connection=db_conn)
    assert dev is not None
    assert dev["status"] == "revoked"
    assert dev["revoked_at"] is not None

    # Revoking again returns False
    assert revoke_device("Tablet", connection=db_conn) is False
    assert revoke_device("NonExistent", connection=db_conn) is False


def test_list_devices_hides_token_hash(db_conn):
    """list_devices returns device list without exposing token_hash."""
    create_device("Dev1", connection=db_conn)
    create_device("Dev2", connection=db_conn)

    devices = list_devices(connection=db_conn)
    assert len(devices) == 2
    names = [d["name"] for d in devices]
    assert "Dev1" in names
    assert "Dev2" in names

    for d in devices:
        assert "token_hash" not in d
        assert "status" in d
        assert "created_at" in d


def test_has_active_devices(db_conn):
    """has_active_devices correctly reflects presence of active devices."""
    assert has_active_devices(connection=db_conn) is False

    create_device("ActiveDev", connection=db_conn)
    assert has_active_devices(connection=db_conn) is True

    revoke_device("ActiveDev", connection=db_conn)
    assert has_active_devices(connection=db_conn) is False


def test_keyring_storage():
    """store_device_token and get_device_token use keyring mock properly."""
    keyring = MemoryKeyring()
    device_name = "Workstation-LG"
    token = "secret-token-12345"

    store_device_token(device_name, token, keyring_backend=keyring)
    retrieved = get_device_token(device_name, keyring_backend=keyring)
    assert retrieved == token

    delete_device_token(device_name, keyring_backend=keyring)
    assert get_device_token(device_name, keyring_backend=keyring) is None


def test_fastapi_endpoints_and_middleware(monkeypatch, tmp_path):
    """Test device API endpoints and middleware behavior."""
    test_db = tmp_path / "bach.db"
    conn = sqlite3.connect(str(test_db))
    conn.row_factory = sqlite3.Row
    init_devices_db(conn)

    # Monkeypatch GET_CONNECTION to use isolated DB
    import gui.device_auth as da
    monkeypatch.setattr(da, "GET_CONNECTION", lambda: sqlite3.connect(str(test_db)))

    client = TestClient(app)

    # 1. When no active devices exist: fail-open for unconfigured systems
    res = client.get("/api/devices")
    assert res.status_code == 200
    assert res.json() == {"devices": []}

    # 2. Register a new device via POST /api/devices
    res = client.post("/api/devices", json={"name": "Laptop-Work"})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["name"] == "Laptop-Work"
    token = data["token"]
    assert token

    # 3. Now active devices exist -> request without token on protected route gives 401
    res = client.get("/api/devices")
    assert res.status_code == 401

    # 4. Request with invalid token -> 401
    res = client.get("/api/devices", headers={"Authorization": "Bearer bad-token"})
    assert res.status_code == 401

    # 5. Request with valid token -> 200
    res = client.get("/api/devices", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    devs = res.json()["devices"]
    assert len(devs) == 1
    assert devs[0]["name"] == "Laptop-Work"

    # 6. Exempt endpoint /api/status works without token
    res = client.get("/api/status")
    assert res.status_code == 200

    # 7. Verify endpoint POST /api/devices/verify
    res = client.post("/api/devices/verify", json={"token": token})
    assert res.status_code == 200
    assert res.json()["valid"] is True

    # 8. Revoke device
    res = client.post(
        "/api/devices/Laptop-Work/revoke",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "revoked"

    # 9. Once revoked, token is no longer authorized
    res = client.get("/api/devices", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401

    conn.close()
