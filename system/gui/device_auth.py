#!/usr/bin/env python3
"""Device-Authentication Backend for BACH.

Provides persistent, non-expiring authentication tokens scoped to specific devices
(Laptop, Workstation, Mobile, Browser).
Tokens are stored securely:
- On the server (bach.db): Only SHA-256 hashes in table `devices`.
- On client devices: In the OS Keyring (macOS Keychain, Windows Credential Manager)
  using hub.secrets_handler.
- In browsers: In localStorage.

Tokens do not expire automatically; they can be revoked individually.
"""
from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path
from typing import Any

# Ensure system root is on sys.path
_SYSTEM_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "hub" / "bach_paths.py").exists()
)
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))

from hub.bach_paths import BACH_DB
from hub.secrets_handler import (
    KEYRING_SERVICE,
    SecretsBackendError,
    _backend_or_raise,
)

try:
    from core.database import get_connection as _get_connection

    GET_CONNECTION = _get_connection
except ImportError:
    def GET_CONNECTION():
        conn = sqlite3.connect(str(BACH_DB))
        conn.row_factory = sqlite3.Row
        return conn


DEVICES_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    token_hash TEXT NOT NULL UNIQUE,
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    revoked_at TEXT,
    last_seen_at TEXT
);
"""


def _hash_token(token: str) -> str:
    """Compute SHA-256 hexadecimal hash of a token string."""
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def init_devices_db(connection: sqlite3.Connection | None = None) -> None:
    """Ensure the devices table exists (lazy migration)."""
    close_after = False
    if connection is None:
        connection = GET_CONNECTION()
        close_after = True

    try:
        connection.execute(DEVICES_TABLE_SCHEMA)
        connection.commit()
    finally:
        if close_after:
            connection.close()


def create_device(name: str, connection: sqlite3.Connection | None = None) -> str:
    """Register a new device and return its plaintext token once.

    Raises:
        ValueError: If name is empty, invalid, or already registered.
    """
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Gerätename darf nicht leer sein.")

    import secrets

    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)

    close_after = False
    if connection is None:
        connection = GET_CONNECTION()
        close_after = True

    try:
        init_devices_db(connection)
        connection.execute(
            """
            INSERT INTO devices (name, token_hash, status, created_at)
            VALUES (?, ?, 'active', CURRENT_TIMESTAMP)
            """,
            (clean_name, token_hash),
        )
        connection.commit()
        return token
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"Gerät '{clean_name}' existiert bereits.") from exc
    finally:
        if close_after:
            connection.close()


def revoke_device(name: str, connection: sqlite3.Connection | None = None) -> bool:
    """Revoke a device token by name.

    Returns:
        True if the device was found and revoked, False otherwise.
    """
    clean_name = (name or "").strip()
    if not clean_name:
        return False

    close_after = False
    if connection is None:
        connection = GET_CONNECTION()
        close_after = True

    try:
        init_devices_db(connection)
        cursor = connection.execute(
            """
            UPDATE devices
            SET status = 'revoked', revoked_at = CURRENT_TIMESTAMP
            WHERE name = ? AND status != 'revoked'
            """,
            (clean_name,),
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        if close_after:
            connection.close()


def list_devices(connection: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    """List all registered devices without exposing secret hashes."""
    close_after = False
    if connection is None:
        connection = GET_CONNECTION()
        close_after = True

    try:
        init_devices_db(connection)
        cursor = connection.execute(
            """
            SELECT id, name, status, created_at, revoked_at, last_seen_at
            FROM devices
            ORDER BY id ASC
            """
        )
        rows = cursor.fetchall()
        result: list[dict[str, Any]] = []
        for r in rows:
            if isinstance(r, sqlite3.Row) or hasattr(r, "keys"):
                result.append(dict(r))
            else:
                result.append({
                    "id": r[0],
                    "name": r[1],
                    "status": r[2],
                    "created_at": r[3],
                    "revoked_at": r[4],
                    "last_seen_at": r[5],
                })
        return result
    finally:
        if close_after:
            connection.close()


def get_device(name: str, connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    """Retrieve metadata for a specific device by name."""
    clean_name = (name or "").strip()
    if not clean_name:
        return None

    close_after = False
    if connection is None:
        connection = GET_CONNECTION()
        close_after = True

    try:
        init_devices_db(connection)
        cursor = connection.execute(
            """
            SELECT id, name, status, created_at, revoked_at, last_seen_at
            FROM devices
            WHERE name = ?
            """,
            (clean_name,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        if isinstance(row, sqlite3.Row) or hasattr(row, "keys"):
            return dict(row)
        return {
            "id": row[0],
            "name": row[1],
            "status": row[2],
            "created_at": row[3],
            "revoked_at": row[4],
            "last_seen_at": row[5],
        }
    finally:
        if close_after:
            connection.close()


def validate_token(token: str, connection: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    """Validate a plaintext token.

    If valid and active, updates `last_seen_at` and returns device metadata.
    If invalid or revoked, returns None.
    """
    if not token or not isinstance(token, str):
        return None

    token_hash = _hash_token(token)

    close_after = False
    if connection is None:
        connection = GET_CONNECTION()
        close_after = True

    try:
        init_devices_db(connection)
        cursor = connection.execute(
            """
            SELECT id, name, status, created_at, revoked_at, last_seen_at
            FROM devices
            WHERE token_hash = ? AND status = 'active'
            """,
            (token_hash,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        device_id = row["id"] if hasattr(row, "keys") else row[0]
        from datetime import datetime, timezone

        now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        connection.execute(
            "UPDATE devices SET last_seen_at = ? WHERE id = ?",
            (now_ts, device_id),
        )
        connection.commit()

        if isinstance(row, sqlite3.Row) or hasattr(row, "keys"):
            res = dict(row)
        else:
            res = {
                "id": row[0],
                "name": row[1],
                "status": row[2],
                "created_at": row[3],
                "revoked_at": row[4],
                "last_seen_at": row[5],
            }
        res["last_seen_at"] = now_ts
        return res
    finally:
        if close_after:
            connection.close()


def has_active_devices(connection: sqlite3.Connection | None = None) -> bool:
    """Check if any active device exists in the database."""
    close_after = False
    if connection is None:
        connection = GET_CONNECTION()
        close_after = True

    try:
        init_devices_db(connection)
        cursor = connection.execute(
            "SELECT 1 FROM devices WHERE status = 'active' LIMIT 1"
        )
        return cursor.fetchone() is not None
    finally:
        if close_after:
            connection.close()


# ── KEYRING INTEGRATION (hub.secrets_handler) ──────────────────────────


def _keyring_key_for_device(device_name: str) -> str:
    """Construct the canonical secret key for a device token in OS keyring."""
    clean_name = (device_name or "").strip().lower().replace(" ", "_")
    return f"bach_device_token_{clean_name}"


def store_device_token(device_name: str, token: str, keyring_backend: Any = None) -> None:
    """Store device token in OS keyring (macOS Keychain / Windows Credential Manager)."""
    backend = _backend_or_raise(keyring_backend)
    key = _keyring_key_for_device(device_name)
    try:
        backend.set_password(KEYRING_SERVICE, key, token)
    except Exception as exc:
        raise SecretsBackendError(
            f"Device-Token für '{device_name}' konnte nicht im OS-Schlüsselbund gespeichert werden."
        ) from exc


def get_device_token(device_name: str, keyring_backend: Any = None) -> str | None:
    """Retrieve device token from OS keyring."""
    backend = _backend_or_raise(keyring_backend)
    key = _keyring_key_for_device(device_name)
    try:
        return backend.get_password(KEYRING_SERVICE, key)
    except Exception as exc:
        raise SecretsBackendError(
            f"Device-Token für '{device_name}' konnte nicht aus dem OS-Schlüsselbund gelesen werden."
        ) from exc


def delete_device_token(device_name: str, keyring_backend: Any = None) -> None:
    """Remove device token from OS keyring."""
    backend = _backend_or_raise(keyring_backend)
    key = _keyring_key_for_device(device_name)
    try:
        if backend.get_password(KEYRING_SERVICE, key) is not None:
            backend.delete_password(KEYRING_SERVICE, key)
    except Exception as exc:
        raise SecretsBackendError(
            f"Device-Token für '{device_name}' konnte nicht aus dem OS-Schlüsselbund gelöscht werden."
        ) from exc
