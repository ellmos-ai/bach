"""Canonical worker submissions and explicit acceptance of their exact content.

Worker output is evidence awaiting review. Only a separate operator transaction
can accept its digest, task version and current status revision. No provider
argument or cached Done receipt grants that authority.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3


class ResultConflict(ValueError):
    """The result, task content or status changed since the operator read it."""


class ResultPermissionDenied(PermissionError):
    """The dedicated operator credential is missing or revoked."""


def ensure_result_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS worker_task_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        fence INTEGER NOT NULL,
        generation TEXT NOT NULL,
        task_version TEXT NOT NULL,
        result TEXT NOT NULL,
        result_sha256 TEXT NOT NULL,
        submitted_by TEXT NOT NULL,
        submitted_at TEXT NOT NULL,
        submission_event_id INTEGER,
        accepted_by TEXT,
        accepted_at TEXT,
        accepted_status_event_id INTEGER,
        acceptance_event_id INTEGER,
        UNIQUE(task_id, fence)
    )""")


def _has_results(conn):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='worker_task_results'").fetchone() is not None


def _dict_row(cursor):
    row = cursor.fetchone()
    return None if row is None else dict(zip((c[0] for c in cursor.description), row))


def _status_revision(conn, task_id):
    row = conn.execute("SELECT MAX(id) FROM task_history WHERE task_id=? "
                       "AND field_changed='status' AND action='status_change'", (task_id,)).fetchone()
    return int(row[0] or 0)


def validate_submission(payload):
    if not isinstance(payload, dict) or set(payload) != {"generation", "result"}:
        raise ValueError("Ergebnisabgabe erlaubt nur generation und result")
    generation, text = payload["generation"], payload["result"]
    if not isinstance(generation, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", generation):
        raise ValueError("Workergeneration fehlt oder ist ungültig")
    if not isinstance(text, str) or not text.strip() or len(text) > 3000 or "\x00" in text:
        raise ValueError("Konkretes Ergebnis mit höchstens 3000 Zeichen erforderlich")
    acknowledgement = re.sub(r"[\s.!:;✅]+", " ", text.casefold()).strip()
    if re.fullmatch(r"(?:(?:task|aufgabe)\s*#?\d+\s*)?(?:done|completed|erledigt|abgeschlossen)", acknowledgement):
        raise ValueError("Eine Erledigungsbestätigung ist kein fachliches Ergebnis")
    return generation, text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def insert_submission(conn, row, payload, *, worker, now):
    from .task_lease import task_content_version
    generation, text, digest = validate_submission(payload)
    ensure_result_schema(conn)
    cursor = conn.execute("""INSERT INTO worker_task_results
        (task_id,fence,generation,task_version,result,result_sha256,submitted_by,submitted_at)
        VALUES (?,?,?,?,?,?,?,?)""", (row["id"], row["claim_fence"], generation,
        task_content_version(row), text, digest, worker, now))
    return {"schema": "bach.worker-result.v1", "result_id": cursor.lastrowid,
            "task_id": row["id"], "fence": row["claim_fence"], "generation": generation,
            "task_version": task_content_version(row), "result_sha256": digest,
            "result": text, "accepted": False}


def result_reference(record):
    return f"bach-task-result:{record['result_id']}:{record['result_sha256']}"


def finish_submission(conn, record, event_id):
    conn.execute("UPDATE worker_task_results SET submission_event_id=? WHERE id=?",
                 (event_id, record["result_id"]))
    record["submission_event_id"] = event_id
    record["status_revision"] = _status_revision(conn, record["task_id"])
    return record


def _legacy_result(conn, task_id):
    # Preserve older output for inspection; its existence cannot prove acceptance.
    for row in conn.execute("SELECT new_value FROM task_history WHERE task_id=? "
                            "AND action='lease_release' ORDER BY id DESC LIMIT 20", (task_id,)):
        try:
            outer = json.loads(row[0]); record = json.loads(outer.get("note") or "null")
        except (TypeError, ValueError, AttributeError):
            continue
        if (isinstance(record, dict) and record.get("schema") == "bach.task-result.v1"
                and type(record.get("task_id")) is int and record["task_id"] == task_id
                and isinstance(record.get("result"), str) and record["result"].strip()):
            return {"schema": "bach.worker-result.v1", "task_id": task_id,
                    "result_id": None, "result": record["result"],
                    "generation": record.get("generation"), "fence": outer.get("fence"),
                    "result_sha256": hashlib.sha256(record["result"].encode("utf-8")).hexdigest(),
                    "accepted": False, "reason": "legacy_result_without_acceptance"}
    return None


def read_result(conn, task_id):
    """Read task, result and status event from one SQLite snapshot; never migrate."""
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("BEGIN")
    try:
        from .task_lease import task_content_version
        task = _dict_row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
        if task is None:
            raise ResultConflict("Task nicht vorhanden")
        revision = _status_revision(conn, task_id)
        record = (_dict_row(conn.execute("SELECT * FROM worker_task_results WHERE task_id=? "
                                        "ORDER BY id DESC LIMIT 1", (task_id,)))
                  if _has_results(conn) else None)
        if record is None:
            result = _legacy_result(conn, task_id)
            return {"schema": "bach.task-result-readback.v1", "task_id": task_id,
                    "task_version": task_content_version(task), "status": task["status"],
                    "status_revision": revision, "result": result, "verified": True}
        same_content = task_content_version(task) == record["task_version"]
        same_fence = int(task.get("claim_fence") or 0) == record["fence"]
        same_digest = hashlib.sha256(record["result"].encode("utf-8")).hexdigest() == record["result_sha256"]
        decision = None
        if record["acceptance_event_id"] is not None:
            decision = conn.execute("SELECT changed_by,new_value FROM task_history WHERE id=? "
                                    "AND task_id=? AND action='result_acceptance'",
                                    (record["acceptance_event_id"], task_id)).fetchone()
        try:
            decision_matches = (decision is not None and decision[0] == record["accepted_by"]
                and json.loads(decision[1]) == {"result_id": record["id"],
                    "result_sha256": record["result_sha256"], "task_version": record["task_version"],
                    "status_revision": record["accepted_status_event_id"]})
        except (TypeError, ValueError):
            decision_matches = False
        accepted = (task["status"] in {"done", "completed"} and same_content and same_fence
                    and same_digest and decision_matches and bool(record["accepted_by"])
                    and record["accepted_status_event_id"] == revision)
        record.update(schema="bach.worker-result.v1", result_id=record.pop("id"),
                      accepted=accepted, status_revision=revision,
                      reason=("accepted" if accepted else "task_content_changed" if not same_content
                              else "fence_changed" if not same_fence else "result_content_changed" if not same_digest
                              else "awaiting_review" if task["status"] == "review" else "acceptance_not_current"))
        return {"schema": "bach.task-result-readback.v1", "task_id": task_id,
                "task_version": task_content_version(task), "status": task["status"],
                "status_revision": revision, "result": record, "verified": True}
    finally:
        if owns_transaction:
            conn.rollback()


class _Acceptance:
    def __init__(self, conn, record):
        self.conn, self.task_id, self.result_id, self.digest = (
            conn, record["task_id"], record["result_id"], record["result_sha256"])


def assert_completion_allowed(conn, task_id, acceptance=None, *, changes=None):
    """Shared write choke point; a model's status alias grants no acceptance."""
    current = _dict_row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
    if current and current.get("claim_id") and current.get("claim_result_generation"):
        raise ResultConflict("Native Workergeneration benötigt Ergebnisabgabe und getrennte Abnahme")
    if not _has_results(conn):
        return
    observed = read_result(conn, task_id)
    record = observed["result"]
    if not record or record.get("result_id") is None:
        return
    from .task_lease import task_content_version
    if task_content_version({**current, **(changes or {})}) != record.get("task_version"):
        raise ResultConflict("Geänderter Auftrag benötigt eine neue Ergebnisabgabe und Abnahme")
    if record.get("accepted") is True:
        return
    if (isinstance(acceptance, _Acceptance) and acceptance.conn is conn
            and conn.in_transaction and acceptance.task_id == task_id
            and acceptance.result_id == record["result_id"] and acceptance.digest == record["result_sha256"]):
        return
    raise ResultConflict("Worker-Ergebnis braucht eine getrennte Abnahme des aktuellen Inhalts")


def accept_result(conn, task_id, result_id, *, digest, task_version, status_revision, operator_token):
    """Authenticated operator decision, correlated and committed atomically."""
    if (type(result_id) is not int or result_id <= 0 or type(status_revision) is not int
            or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
            or not isinstance(task_version, str) or not re.fullmatch(r"[a-f0-9]{64}", task_version)):
        raise ResultConflict("Ungültige Ergebnisabnahme")
    if conn.in_transaction:
        raise ResultConflict("Abnahme benötigt eine eigene kanonische Transaktion")
    conn.execute("BEGIN IMMEDIATE")
    try:
        # Resolve the separate principal under the SAME write lock as acceptance.
        # General device enrollment, first device, and loopback confer no right.
        if (not isinstance(operator_token, str) or not operator_token.strip()
                or len(operator_token) > 256
                or not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                                    "AND name='task_result_operators'").fetchone()):
            raise ResultPermissionDenied("Persönliche Ergebnisfreigabe erforderlich")
        from gui.device_auth import _hash_token
        principal = conn.execute("SELECT d.id FROM devices d JOIN task_result_operators o "
                                 "ON o.device_id=d.id WHERE d.token_hash=? AND d.status='active'",
                                 (_hash_token(operator_token),)).fetchone()
        if principal is None:
            raise ResultPermissionDenied("Ergebnisfreigabe fehlt oder wurde widerrufen")
        actor = f"operator-device:{principal[0]}"
        from .task_lease import _history, _utcnow, _local_naive
        from hub.task_audit import apply_task_field_changes
        observed = read_result(conn, task_id); record = observed["result"]
        if (not record or record.get("result_id") != result_id or record.get("result_sha256") != digest
                or observed["task_version"] != task_version or observed["status_revision"] != status_revision
                or record.get("task_version") != task_version or record.get("reason") != "awaiting_review"):
            raise ResultConflict("Ergebnis oder Auftrag seit dem Lesen verändert; neu laden")
        row = _dict_row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
        if row.get("claim_id") or row["status"] != "review":
            raise ResultConflict("Nur ein freigegebenes Review-Ergebnis kann abgenommen werden")
        now = _utcnow()
        apply_task_field_changes(conn, task_id, row, {"status": "done"}, changed_by=actor,
                                 now=_local_naive(now), result_acceptance=_Acceptance(conn, record))
        revision = _status_revision(conn, task_id)
        acceptance_event = _history(conn, task_id, "result_acceptance", actor, now,
                 {"result_id": result_id, "result_sha256": digest, "task_version": task_version,
                  "status_revision": revision})
        conn.execute("UPDATE worker_task_results SET accepted_by=?,accepted_at=?,"
                     "accepted_status_event_id=?,acceptance_event_id=? WHERE id=?",
                     (actor, _local_naive(now), revision, acceptance_event, result_id))
        result = read_result(conn, task_id)
        if result["result"].get("accepted") is not True:
            raise ResultConflict("Kanonische Ergebnisabnahme nicht bestätigt")
        conn.commit()
        return result
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
