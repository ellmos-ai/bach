"""Owner of automatic resolver tasks as a versioned system setting (#2661).

Default ``BACH``: resolver tasks are open to every agent (user rule "Aufgaben
standardmäßig für alle"). Stored in BACH's ``system_config`` with the same
revision/CAS handling as the creator priority setting.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3

from hub._services import worker_policy_settings as _store

log = logging.getLogger(__name__)

KEY = "task_resolver_assignee.v1"
SCHEMA = "bach.task-resolver-assignee.v1"
DEFAULT_ASSIGNEE = "BACH"
_FIELDS = {"assignee"}
_ASSIGNEE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,31}\Z")


def _validate(values):
    if not isinstance(values, dict) or set(values) != _FIELDS:
        raise ValueError("Erwartet wird genau assignee")
    if not isinstance(values["assignee"], str) or not _ASSIGNEE.fullmatch(values["assignee"]):
        raise ValueError("assignee muss ein Agentenname wie BACH, CLAUDE oder OLLAMA sein")


def stored_assignee(conn) -> str:
    """Owner for a new resolver task; missing or unreadable values mean the default."""
    try:
        row = conn.execute("SELECT value FROM system_config WHERE key=?", (KEY,)).fetchone()
    except sqlite3.Error:
        return DEFAULT_ASSIGNEE
    if row is None:
        return DEFAULT_ASSIGNEE
    try:
        values = json.loads(row[0])["values"]
        _validate(values)
    except (ValueError, TypeError, KeyError):
        log.warning("task_resolver_assignee_unreadable key=%s; default %s", KEY, DEFAULT_ASSIGNEE)
        return DEFAULT_ASSIGNEE
    return values["assignee"]


def _snapshot(conn):
    stored = _store._stored(conn, KEY)
    values = stored["values"]
    if values is None:
        values = {"assignee": DEFAULT_ASSIGNEE}
    try:
        _validate(values)
    except ValueError as exc:
        raise _store.PolicyUnavailable("Gespeicherte Auflöser-Zuweisung ist ungültig") from exc
    return {"schema": SCHEMA, "configuration_version": _store._digest(stored),
            "source": "system_default" if stored["values"] is None else "user_override", **values}


def read_setting(db_path=None):
    with _store._connection(db_path) as conn:
        return _snapshot(conn)


def write_setting(payload, *, actor, db_path=None):
    if not isinstance(payload, dict) or set(payload) != _FIELDS | {"configuration_version"}:
        raise ValueError("Erwartet werden configuration_version und assignee")
    values = {key: payload[key] for key in _FIELDS}
    _validate(values)
    with _store._connection(db_path, write=True) as conn:
        if payload["configuration_version"] != _snapshot(conn)["configuration_version"]:
            raise _store.PolicyConflict("Einstellung wurde parallel geändert")
        _store._persist(conn, KEY, values, actor=actor)
        return {**_snapshot(conn), "updated": True}
