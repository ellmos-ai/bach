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
SENDER = "bach-abort-watch"
DEFAULT_MAX_PER_HOUR = 3
_REQUIRED = {"repeated_abort"}
_OPTIONAL = {"max_per_hour"}
SUMMARY_LIST_LIMIT = 40


def _validate(values):
    if (not isinstance(values, dict) or not _REQUIRED <= set(values) <= _REQUIRED | _OPTIONAL
            or type(values["repeated_abort"]) is not bool):
        raise ValueError("Erwartet werden repeated_abort (Ja/Nein) und optional max_per_hour")
    cap = values.get("max_per_hour", DEFAULT_MAX_PER_HOUR)
    if type(cap) is not int or not 0 <= cap <= 20:
        raise ValueError("max_per_hour muss eine ganze Zahl von 0 bis 20 sein")


def _stored_values(conn):
    """Stored setting with defaults filled in; unreadable means defaults (a lost alarm costs more than a message)."""
    try:
        row = conn.execute("SELECT value FROM system_config WHERE key=?", (KEY,)).fetchone()
        if row is None:
            return {"repeated_abort": True, "max_per_hour": DEFAULT_MAX_PER_HOUR}
        values = json.loads(row[0])["values"]
        _validate(values)
    except (sqlite3.Error, ValueError, TypeError, KeyError):
        return {"repeated_abort": True, "max_per_hour": DEFAULT_MAX_PER_HOUR}
    return {"max_per_hour": DEFAULT_MAX_PER_HOUR, **values}


def stored_enabled(conn) -> bool:
    return _stored_values(conn)["repeated_abort"]


def stored_max_per_hour(conn) -> int:
    return _stored_values(conn)["max_per_hour"]


def _insert(conn, subject, body, metadata, tags):
    return conn.execute(
        "INSERT INTO messages (direction, sender, recipient, subject, body, priority, status, tags, metadata) "
        "VALUES ('inbox', ?, 'user', ?, ?, 1, 'unread', ?, ?)",
        (SENDER, subject[:200], body, json.dumps(tags), json.dumps(metadata, sort_keys=True))).lastrowid


def _summary(conn, key, subject):
    """One summary per rolling hour: further events are listed in it instead of becoming messages."""
    row = conn.execute(
        "SELECT id, metadata FROM messages WHERE sender = ? AND recipient = 'user' "
        "AND json_extract(metadata, '$.kind') = 'summary' AND created_at >= datetime('now', '-1 hour') "
        "ORDER BY id DESC LIMIT 1", (SENDER,)).fetchone()
    items = json.loads(row[1])["items"] if row else []
    items.append([key, subject])
    shown = "\n".join("- " + text for _, text in items[:SUMMARY_LIST_LIMIT])
    more = len(items) - SUMMARY_LIST_LIMIT
    body = (f"{len(items)} weitere wiederholte Abbrüche in dieser Stunde, einzeln nicht gemeldet.\n{shown}"
            + (f"\n... und {more} weitere" if more > 0 else "")
            + "\nÜberblick: /tasks (Rückgaben und Abbrüche), /agenten/running")
    sub = f"{len(items)} weitere wiederholte Abbrüche in dieser Stunde"
    metadata = json.dumps({"kind": "summary", "notice_key": f"summary:{items[0][0]}", "items": items}, sort_keys=True)
    if row:
        conn.execute("UPDATE messages SET subject=?, body=?, metadata=?, status='unread', read_at=NULL WHERE id=?",
                     (sub, body, metadata, row[0]))
        return row[0]
    return _insert(conn, sub, body, json.loads(metadata), ["abbruch"])


def post(conn, key, subject, body):
    """Inbox message for one event, at most ``max_per_hour`` singles per hour, then one summary. Never raises."""
    try:
        values = _stored_values(conn)
        if not values["repeated_abort"]:
            return None
        if conn.execute("SELECT 1 FROM messages WHERE sender = ? AND instr(metadata, ?) > 0 LIMIT 1",
                        (SENDER, json.dumps(key))).fetchone():
            return None  # this event was already announced, alone or inside the summary
        singles = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE sender = ? AND recipient = 'user' AND created_at >= datetime('now', '-1 hour') "
            "AND COALESCE(json_extract(metadata, '$.kind'), 'single') = 'single'", (SENDER,)).fetchone()[0]
        if singles >= values["max_per_hour"]:
            return _summary(conn, key, subject)
        return _insert(conn, subject, body, {"notice_key": key, "kind": "single"}, ["abbruch"])
    except sqlite3.Error as exc:  # no messages table (test or old DB): the block itself must still happen
        log.warning("abort_notice_unconfirmed key=%s reason=%s", key, type(exc).__name__)
        return None


def _snapshot(conn):
    stored = _store._stored(conn, KEY)
    values = stored["values"] if stored["values"] is not None else {"repeated_abort": True}
    values = {"max_per_hour": DEFAULT_MAX_PER_HOUR, **values}
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
    if (not isinstance(payload, dict) or "configuration_version" not in payload
            or not _REQUIRED <= set(payload) - {"configuration_version"} <= _REQUIRED | _OPTIONAL):
        raise ValueError("Erwartet werden configuration_version, repeated_abort und optional max_per_hour")
    values = {key: payload[key] for key in payload if key != "configuration_version"}
    _validate(values)
    with _store._connection(db_path, write=True) as conn:
        if payload["configuration_version"] != _snapshot(conn)["configuration_version"]:
            raise _store.PolicyConflict("Einstellung wurde parallel geändert")
        _store._persist(conn, KEY, values, actor=actor)
        return {**_snapshot(conn), "updated": True}
