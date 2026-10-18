"""Creator priority for task leases as a versioned system setting (BACH #2231).

Off by default: a new task is leasable by any matching worker at once. When the
operator enables it, a task is reserved for its creator for ``window_seconds``
(2 minutes by default). Stored in BACH's existing ``system_config`` with the
same revision/CAS handling as the worker policy. The environment variable
``BACH_TASK_LEASE_CREATOR_WINDOW`` stays an explicit operator override inside
``task_lease.LeaseConfig``.
"""
from __future__ import annotations

import json
import logging
import sqlite3

from hub._services import worker_policy_settings as _store

log = logging.getLogger(__name__)

KEY = "task_lease_creator_priority.v1"
SCHEMA = "bach.task-lease-creator-priority.v1"
DEFAULT_WINDOW_SECONDS = 2 * 60
MAX_WINDOW_SECONDS = 24 * 3600
_FIELDS = {"enabled", "window_seconds"}


def _validate(values):
    if not isinstance(values, dict) or set(values) != _FIELDS:
        raise ValueError("Erwartet werden genau enabled und window_seconds")
    if type(values["enabled"]) is not bool:
        raise ValueError("enabled muss true oder false sein")
    window = values["window_seconds"]
    if type(window) is not int or not 1 <= window <= MAX_WINDOW_SECONDS:
        raise ValueError(f"window_seconds muss eine ganze Zahl von 1 bis {MAX_WINDOW_SECONDS} sein")


def stored_window(conn) -> int:
    """Effective window in seconds for lease acquisition; 0 means off.

    Missing table, missing key or an unreadable value all mean off, the
    documented default. This read never initializes a schema.
    """
    try:
        row = conn.execute("SELECT value FROM system_config WHERE key=?", (KEY,)).fetchone()
    except sqlite3.Error:
        return 0
    if row is None:
        return 0
    try:
        values = json.loads(row[0])["values"]
        _validate(values)
    except (ValueError, TypeError, KeyError):
        log.warning("task_lease_creator_priority_unreadable key=%s; creator priority off", KEY)
        return 0
    return values["window_seconds"] if values["enabled"] else 0


def _snapshot(conn):
    stored = _store._stored(conn, KEY)
    values = stored["values"]
    if values is None:
        values = {"enabled": False, "window_seconds": DEFAULT_WINDOW_SECONDS}
    try:
        _validate(values)
    except ValueError as exc:
        raise _store.PolicyUnavailable("Gespeicherter Ersteller-Vorrang ist ungültig") from exc
    return {"schema": SCHEMA, "configuration_version": _store._digest(stored),
            "source": "system_default" if stored["values"] is None else "user_override", **values}


def read_setting(db_path=None):
    with _store._connection(db_path) as conn:
        return _snapshot(conn)


def write_setting(payload, *, actor, db_path=None):
    if not isinstance(payload, dict) or set(payload) != _FIELDS | {"configuration_version"}:
        raise ValueError("Erwartet werden configuration_version, enabled und window_seconds")
    values = {key: payload[key] for key in _FIELDS}
    _validate(values)
    with _store._connection(db_path, write=True) as conn:
        if payload["configuration_version"] != _snapshot(conn)["configuration_version"]:
            raise _store.PolicyConflict("Einstellung wurde parallel geändert")
        _store._persist(conn, KEY, values, actor=actor)
        return {**_snapshot(conn), "updated": True}
