"""One Postfach message per repeated abort (PB-4, #3988; user decision E1, 2026-11-06).

Only "repeated abort" reaches the user's inbox: a task blocked by the return rule
or a worker that needed a resolver task. Everything else stays in the history,
and Telegram is never used. The switch is a versioned system setting, default on,
stored like the resolver assignee (same revision/CAS handling).
"""
from __future__ import annotations

import json
import logging
import sqlite3

from hub._services import worker_policy_settings as _store

log = logging.getLogger(__name__)

KEY = "abort_notices.v1"
SCHEMA = "bach.abort-notice-settings.v1"
_FIELDS = {"repeated_abort"}
SENDER = "bach-abort-watch"


def _validate(values):
    if not isinstance(values, dict) or set(values) != _FIELDS or type(values["repeated_abort"]) is not bool:
        raise ValueError("Erwartet wird genau repeated_abort als Ja/Nein-Wert")


def stored_enabled(conn) -> bool:
    """Missing setting means on; an unreadable one also (a lost alarm costs more than a message)."""
    try:
        row = conn.execute("SELECT value FROM system_config WHERE key=?", (KEY,)).fetchone()
        if row is None:
            return True
        values = json.loads(row[0])["values"]
        _validate(values)
    except (sqlite3.Error, ValueError, TypeError, KeyError):
        return True
    return values["repeated_abort"]


def post(conn, key, subject, body):
    """Insert the inbox message unless one with ``key`` exists; id or None. Never raises."""
    try:
        if not stored_enabled(conn):
            return None
        metadata = json.dumps({"notice_key": key}, sort_keys=True)
        if conn.execute("SELECT 1 FROM messages WHERE metadata = ? AND recipient = 'user' LIMIT 1",
                        (metadata,)).fetchone():
            return None
        cursor = conn.execute(
            "INSERT INTO messages (direction, sender, recipient, subject, body, priority, status, tags, metadata) "
            "VALUES ('inbox', ?, 'user', ?, ?, 1, 'unread', ?, ?)",
            (SENDER, subject[:200], body, json.dumps(["abbruch"]), metadata))
        return cursor.lastrowid
    except sqlite3.Error as exc:  # no messages table (test or old DB): the block itself must still happen
        log.warning("abort_notice_unconfirmed key=%s reason=%s", key, type(exc).__name__)
        return None


def _snapshot(conn):
    stored = _store._stored(conn, KEY)
    values = stored["values"] if stored["values"] is not None else {"repeated_abort": True}
    try:
        _validate(values)
    except ValueError as exc:
        raise _store.PolicyUnavailable("Gespeicherte Benachrichtigungseinstellung ist ungültig") from exc
    return {"schema": SCHEMA, "configuration_version": _store._digest(stored),
            "source": "system_default" if stored["values"] is None else "user_override", **values}


def read_setting(db_path=None):
    with _store._connection(db_path) as conn:
        return _snapshot(conn)


def write_setting(payload, *, actor, db_path=None):
    if not isinstance(payload, dict) or set(payload) != _FIELDS | {"configuration_version"}:
        raise ValueError("Erwartet werden configuration_version und repeated_abort")
    values = {key: payload[key] for key in _FIELDS}
    _validate(values)
    with _store._connection(db_path, write=True) as conn:
        if payload["configuration_version"] != _snapshot(conn)["configuration_version"]:
            raise _store.PolicyConflict("Einstellung wurde parallel geändert")
        _store._persist(conn, KEY, values, actor=actor)
        return {**_snapshot(conn), "updated": True}
