# SPDX-License-Identifier: MIT
"""Versioned Taskmaster operating policy in BACH's existing config store.

The policy describes cadence, ownership, deduplication and retry backoff. It
does not contain tasks and cannot start a worker. The cloud-start mode is
intentionally fixed to ``user_only``.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping


SCHEMA = "bach.taskmaster.policy.v1"
KEY = "taskmaster_policy.v1"
FIELDS = frozenset({
    "enabled", "owner_role_id", "interval_seconds", "dedup_window_seconds",
    "backoff_base_seconds", "backoff_max_seconds", "max_tasks_per_cycle",
    "cloud_start_mode",
})
DEFAULTS = {
    "enabled": False,
    "owner_role_id": "taskmaster.operator",
    "interval_seconds": 300,
    "dedup_window_seconds": 900,
    "backoff_base_seconds": 30,
    "backoff_max_seconds": 3600,
    "max_tasks_per_cycle": 1,
    "cloud_start_mode": "user_only",
}


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _digest(value: Mapping[str, Any]) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def validate_policy(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError("Unvollständige oder unbekannte Taskmaster-Policyfelder")
    if type(value["enabled"]) is not bool:
        raise ValueError("Taskmaster enabled muss boolesch sein")
    if value["owner_role_id"] != "taskmaster.operator":
        raise ValueError("Taskmaster braucht den nativen Operator als Betriebsowner")
    for key, lower, upper in (
        ("interval_seconds", 30, 86_400),
        ("dedup_window_seconds", 1, 7_776_000),
        ("backoff_base_seconds", 1, 86_400),
        ("backoff_max_seconds", 1, 31_536_000),
        ("max_tasks_per_cycle", 1, 100),
    ):
        number = value[key]
        if type(number) is not int or not lower <= number <= upper:
            raise ValueError(f"Ungültiger Taskmaster-Wert: {key}")
    if value["backoff_max_seconds"] < value["backoff_base_seconds"]:
        raise ValueError("Backoff-Obergrenze muss mindestens die Basis sein")
    if value["cloud_start_mode"] != "user_only":
        raise ValueError("Cloud-Worker dürfen nur durch den Nutzer gestartet werden")
    return dict(value)


def _db_path(db_path: str | Path | None = None) -> Path:
    if db_path is not None:
        return Path(db_path).expanduser()
    from hub.bach_paths import BACH_DB
    return Path(BACH_DB)


def read_policy(db_path: str | Path | None = None) -> dict[str, Any]:
    """Read policy state without creating or mutating any schema."""
    path = _db_path(db_path).resolve()
    conn = None
    try:
        uri = path.as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=2)
        row = conn.execute("SELECT value FROM system_config WHERE key = ?", (KEY,)).fetchone()
    except (OSError, sqlite3.Error) as exc:
        raise RuntimeError("Taskmaster-Policy nicht verfügbar") from exc
    finally:
        if conn is not None:
            conn.close()
    source = "system_default"
    values: dict[str, Any] = dict(DEFAULTS)
    if row is not None:
        try:
            stored = json.loads(row[0])
            if not isinstance(stored, dict) or set(stored) != {"revision", "values"}:
                raise ValueError
            values = validate_policy(stored["values"])
            source = "user_override"
        except (TypeError, ValueError, json.JSONDecodeError):
            raise RuntimeError("Gespeicherte Taskmaster-Policy ist ungültig") from None
    else:
        values = validate_policy(values)
    return {
        "schema": SCHEMA,
        "availability": "available",
        "configuration_version": _digest(values),
        "policy_source": source,
        "values": values,
        "task_source": "canonical_bach_taskdb",
        "lease_authority": "canonical_task_api",
        "scheduler_state": "disabled_by_default" if not values["enabled"] else "user_enabled",
    }
