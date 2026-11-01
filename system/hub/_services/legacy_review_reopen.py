# SPDX-License-Identifier: MIT
"""Targeted, authenticated reopen of an old review task without a result."""

from __future__ import annotations

import json
import re
import sqlite3

from hub._services.task_lease import _CLEARED_ON_RELEASE, task_content_version
from hub._services.task_result_service import (
    ResultConflict,
    ResultPermissionDenied,
    _correction_operator_device_id,
    _dict_row,
    _legacy_result,
    _status_revision,
    _table_exists,
)
from hub.task_audit import apply_task_field_changes


_VERSION = re.compile(r"[a-f0-9]{64}\Z")
_SCHEMA = "bach.legacy-review-reopen.v1"
_REVIEW_SOURCE = "worker-result-review:v1:"


def _has_row(conn: sqlite3.Connection, table: str, where: str, params: tuple) -> bool:
    """Only call with the static table/where literals below."""
    return (_table_exists(conn, table)
            and conn.execute(f"SELECT 1 FROM {table} WHERE {where} LIMIT 1", params).fetchone()
            is not None)


def _result_or_intent_blocker(conn: sqlite3.Connection, task_id: int, task: dict) -> str | None:
    # Never reinterpret a lost result row, an inline legacy result, or an old
    # correction as a fresh task. All reads occur in the same writer snapshot.
    if task.get("result_correction_request_id") is not None:
        return "correction_request_reference"
    if "result" in task and task["result"] is not None:
        return "inline_result"
    if str(task.get("source") or "").startswith(_REVIEW_SOURCE):
        return "review_task_source"
    if _has_row(conn, "worker_task_results", "task_id=?", (task_id,)):
        return "worker_result"
    if _has_row(conn, "task_result_corrections", "task_id=?", (task_id,)):
        return "result_correction"
    if _has_row(conn, "worker_result_review_intents",
                "review_task_id=? OR target_task_id=?", (task_id, task_id)):
        return "review_intent"
    if _has_row(conn, "worker_result_model_reviews",
                "review_task_id=? OR target_task_id=?", (task_id, task_id)):
        return "model_review"
    if _legacy_result(conn, task_id) is not None:
        return "legacy_result"
    # A deleted result row, an external result reference, an old release note,
    # or a rejected late submission must not downgrade to "no result".
    # Malformed audit data also denies.
    for (raw,) in conn.execute(
            "SELECT new_value FROM task_history WHERE task_id=? AND action='lease_release'",
            (task_id,)):
        try:
            detail = json.loads(raw)
        except (TypeError, ValueError):
            return "malformed_release_audit"
        if not isinstance(detail, dict):
            return "malformed_release_audit"
        if detail.get("result_ref") or detail.get("note"):
            return "release_result_or_note"
    if _has_row(
        conn, "task_history",
        "task_id=? AND (action LIKE 'result_%' OR action LIKE 'worker_result_%' "
        "OR action='worker_completion_decision' OR action='late_result')",
        (task_id,),
    ):
        return "result_history"
    return None


def _no_result_or_intent(conn: sqlite3.Connection, task_id: int, task: dict) -> bool:
    return _result_or_intent_blocker(conn, task_id, task) is None


def legacy_review_reopen_eligibility(conn: sqlite3.Connection, task_id: int, *,
                                     operator_token: str) -> dict:
    """Read the existing reopen predicates in one consistent, non-writing snapshot.

    This is an observation, never an authorization for a later write. The
    existing reopen owner still rechecks permissions, task CAS and every guard.
    Blocker codes disclose classes only, never result or intent contents.
    """
    if type(task_id) is not int or task_id <= 0:
        raise ValueError("Ungültige Task-ID")
    if conn.in_transaction:
        raise ResultConflict("Eignungsprüfung benötigt eine eigene Lesetransaktion")
    device_id = _correction_operator_device_id(conn, operator_token)
    if device_id is None:
        raise ResultPermissionDenied("Persönliche Korrekturberechtigung fehlt oder wurde widerrufen")
    conn.execute("BEGIN")
    try:
        if _correction_operator_device_id(conn, operator_token) != device_id:
            raise ResultPermissionDenied("Persönliche Korrekturberechtigung wurde widerrufen")
        if not (_table_exists(conn, "tasks") and _table_exists(conn, "task_history")):
            raise ResultConflict("Kanonischer Task- oder Auditstore fehlt")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
        if not {"id", "status", *_CLEARED_ON_RELEASE} <= columns:
            raise ResultConflict("Task-Lease-Schema ist unvollständig")
        task = _dict_row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
        if task is None:
            raise ResultConflict("Aufgabe nicht vorhanden; neu laden")
        blocker = _result_or_intent_blocker(conn, task_id, task)
        checks = {
            "status_review": task["status"] == "review",
            "lease_claim_free": all(task.get(name) in (None, "") for name in _CLEARED_ON_RELEASE),
            "result_intent_history_clear": blocker is None,
        }
        history_revision = conn.execute(
            "SELECT COALESCE(MAX(id),0) FROM task_history WHERE task_id=?", (task_id,),
        ).fetchone()[0]
        lease_fence = task.get("claim_fence")
        if type(lease_fence) is not int or lease_fence < 0 or type(history_revision) is not int:
            raise ResultConflict("Lease- oder Auditrevision ist nicht bestätigt")
        return {
            "schema": "bach.legacy-review-reopen-eligibility.v1",
            "availability": "available", "task_id": task_id,
            "task_version": task_content_version(task),
            "status_revision": _status_revision(conn, task_id),
            "history_revision": history_revision, "lease_fence": lease_fence,
            "status": task["status"], "eligible": all(checks.values()),
            "checks": checks, "result_intent_history_blocker": blocker,
            "write_rechecks_required": True,
        }
    finally:
        if conn.in_transaction:
            conn.rollback()


def reopen_legacy_review(conn: sqlite3.Connection, task_id: int, *,
                         task_version: str, status_revision: int,
                         operator_token: str) -> dict:
    """CAS one review task without any result back to pending.

    The existing correction-enabled result-operator device is the only
    authority. This function provisions no device, changes no capability and
    creates no second queue. It requires an own SQLite writer transaction.
    """
    if (type(task_id) is not int or task_id <= 0
            or type(task_version) is not str or not _VERSION.fullmatch(task_version)
            or type(status_revision) is not int or status_revision < 0):
        raise ValueError("Ungültige Task-ID oder erwartete Revision")
    if conn.in_transaction:
        raise ResultConflict("Wiederaufnahme benötigt eine eigene Transaktion")
    device_id = _correction_operator_device_id(conn, operator_token)
    if device_id is None:
        raise ResultPermissionDenied("Persönliche Korrekturberechtigung fehlt oder wurde widerrufen")

    conn.execute("BEGIN IMMEDIATE")
    try:
        if _correction_operator_device_id(conn, operator_token) != device_id:
            raise ResultPermissionDenied("Persönliche Korrekturberechtigung wurde widerrufen")
        if not (_table_exists(conn, "tasks") and _table_exists(conn, "task_history")):
            raise ResultConflict("Kanonischer Task- oder Auditstore fehlt")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
        if not {"id", "status", *_CLEARED_ON_RELEASE} <= columns:
            raise ResultConflict("Task-Lease-Schema ist unvollständig")
        task = _dict_row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
        if task is None or task["status"] != "review":
            raise ResultConflict("Review-Aufgabe seit dem Lesen verändert; neu laden")
        if (task_content_version(task) != task_version
                or _status_revision(conn, task_id) != status_revision):
            raise ResultConflict("Task- oder Statusrevision seit dem Lesen verändert")
        if any(task.get(name) not in (None, "") for name in _CLEARED_ON_RELEASE):
            raise ResultConflict("Task hat noch einen Claim oder eine Lease")
        if not _no_result_or_intent(conn, task_id, task):
            raise ResultConflict("Task hat ein Ergebnis oder einen Korrektur-/Review-Intent")

        actor = f"operator-device:{device_id}"
        changed = apply_task_field_changes(
            conn, task_id, task, {"status": "pending"},
            changed_by=actor, allow_reopen=True,
        )
        new_revision = _status_revision(conn, task_id)
        event = _dict_row(conn.execute(
            "SELECT id,old_value,new_value,changed_by,action,field_changed "
            "FROM task_history WHERE id=? AND task_id=?",
            (new_revision, task_id),
        ))
        after = _dict_row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
        if (changed is not True or after is None or after["status"] != "pending"
                or new_revision <= status_revision or event is None
                or event["action"] != "status_change" or event["field_changed"] != "status"
                or event["old_value"] != "review" or event["new_value"] != "pending"
                or event["changed_by"] != actor):
            raise ResultConflict("Auditierter Statuswechsel konnte nicht bestätigt werden")
        result = {
            "schema": _SCHEMA, "task_id": task_id, "status": "pending",
            "previous_task_version": task_version,
            "task_version": task_content_version(after),
            "previous_status_revision": status_revision,
            "status_revision": new_revision, "status_event_id": new_revision,
        }
        conn.commit()
        return result
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
