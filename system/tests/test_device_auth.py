# -*- coding: utf-8 -*-
"""Tests fuer gui.device_auth — Geraetetoken ohne OS-Keyring (CI-tauglich)."""
import hashlib, sqlite3, sys
from pathlib import Path
from unittest.mock import patch
import pytest

SYSTEM = Path(__file__).resolve().parent.parent
BACH_ROOT = SYSTEM.parent
for _p in (str(BACH_ROOT), str(SYSTEM)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from hub.secrets_handler import KEYRING_SERVICE  # "ellmos-bach"
import gui.device_auth as da


class MemoryKeyring:
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
def device_env(tmp_path, monkeypatch):
    db_path = tmp_path / "test_device_auth.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS secrets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            value TEXT NOT NULL DEFAULT '',
            description TEXT DEFAULT '',
            category TEXT DEFAULT 'general',
            source TEXT DEFAULT 'manual',
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("BACH_SECRETS_FILE", str(tmp_path / "bach_secrets.json"))
    return tmp_path, db_path


@pytest.fixture
def auth(device_env):
    _, db_path = device_env

    def mock_conn():
        return sqlite3.connect(str(db_path))

    with patch("gui.device_auth.GET_CONNECTION", mock_conn), patch(
        "hub.secrets_handler.GET_CONNECTION", mock_conn
    ):
        yield da


class TestCreateDevice:
    def test_create_returns_device_and_token(self, auth):
        device, token = auth.create_device("macbook")
        assert device["name"] == "macbook"
        assert device["status"] == "active"
        assert isinstance(token, str)
        assert len(token) >= 32
        assert "token_hash" not in device

    def test_created_token_validates(self, auth):
        device, token = auth.create_device("macbook")
        result = auth.validate_token(token)
        assert result is not None
        assert result["name"] == "macbook"
        assert "last_seen_at" in result
        assert "token_hash" not in result

    def test_validate_rejects_bad_tokens(self, auth):
        device, token = auth.create_device("macbook")
        assert auth.validate_token("falsch") is None
        assert auth.validate_token("") is None
        assert auth.validate_token(None) is None

    def test_create_empty_name_raises(self, auth):
        with pytest.raises(ValueError):
            auth.create_device("")

    def test_create_duplicate_raises(self, auth):
        auth.create_device("macbook")
        with pytest.raises(ValueError):
            auth.create_device("macbook")


class TestRevokeDevice:
    def test_revoke_returns_revoked_device(self, auth):
        auth.create_device("macbook")
        result = auth.revoke_device("macbook")
        assert result is not None
        assert result["status"] == "revoked"
        assert "token_hash" not in result

    def test_revoked_token_no_longer_validates(self, auth):
        device, token = auth.create_device("macbook")
        assert auth.validate_token(token) is not None
        auth.revoke_device("macbook")
        assert auth.validate_token(token) is None

    def test_revoke_twice_returns_none(self, auth):
        auth.create_device("macbook")
        assert auth.revoke_device("macbook") is not None
        assert auth.revoke_device("macbook") is None

    def test_revoke_unknown_returns_none(self, auth):
        assert auth.revoke_device("unbekannt") is None


class TestListDevices:
    def test_list_returns_all_active_devices(self, auth):
        auth.create_device("macbook")
        auth.create_device("ipad")
        devices = auth.list_devices()
        assert isinstance(devices, list)
        assert sorted(d["name"] for d in devices) == ["ipad", "macbook"]
        for d in devices:
            assert "token_hash" not in d
            assert d["status"] == "active"


class TestHashInDb:
    def test_db_stores_sha256_hash_not_token(self, auth, device_env):
        _, db_path = device_env
        device, token = auth.create_device("macbook")
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                "SELECT token_hash FROM devices WHERE name = ?", ("macbook",)
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row[0] == hashlib.sha256(token.encode("utf-8")).hexdigest()
        assert row[0] != token


class TestKeyringStorage:
    def test_store_read_delete_device_token(self, auth):
        backend = MemoryKeyring()
        token = "t" * 43
        assert auth.store_device_token("tray", token, backend) is True
        assert backend.values[(KEYRING_SERVICE, da._device_key("tray"))] == token
        assert auth.read_device_token("tray", keyring_backend=backend) == token
        assert auth.delete_device_token("tray", keyring_backend=backend) is True
        assert auth.read_device_token("tray", keyring_backend=backend) is None

    def test_missing_entries(self, auth):
        backend = MemoryKeyring()
        assert auth.read_device_token("fehlt", keyring_backend=backend) is None
        assert auth.delete_device_token("fehlt", keyring_backend=backend) is False