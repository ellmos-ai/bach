# SPDX-License-Identifier: MIT
"""Private, result-bound Git scope observation; no completion authority.

The SQLite reader verifies only the recorded history. A caller must invoke
project_scope_evidence after closing its SQLite read snapshot to check the
current worktree. Neither observation grants review, User approval or Done.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3

from .chat.worker_write_guard import snapshot_task_scope
from .task_lease import _fmt, _history, _local_naive, parse_ts
from .worker_execution_evidence import _submitted, read_execution_evidence

_ACTOR = "native-scope-controller"
_RECEIPT_SCHEMA = "bach.worker-scope-receipt.v1"
_READ_SCHEMA = "bach.worker-scope-evidence.v1"
_REVISION_SCHEMA = "bach.worker-result-revision.v1"
_EVENT_ACTION = "worker_result_scope_capture"
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SNAPSHOT_KEYS = frozenset({
    "schema", "availability", "task_id", "repository", "origin", "branch",
    "head_oid", "tree_oid", "repo_path_sha256", "worktree_path_sha256",
    "common_dir_sha256", "source_pin", "clean_scope", "status_sha256",
    "index_sha256", "project_state_ref", "workspace_fingerprint",
})


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _row(cursor):
    row = cursor.fetchone()
    return dict(zip((column[0] for column in cursor.description), row)) if row is not None else None


def _unavailable(reason):
    return {"schema": _READ_SCHEMA, "availability": "unavailable",
            "reason": reason, "result_revision": None}


def _ensure_schema(conn):
    """Create the additive ledger only inside the explicit capture write path."""
    conn.execute("""CREATE TABLE IF NOT EXISTS worker_scope_evidence (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL, result_id INTEGER NOT NULL UNIQUE,
        fence INTEGER NOT NULL, generation TEXT NOT NULL,
        task_version TEXT NOT NULL, submission_revision TEXT NOT NULL,
        receipt TEXT NOT NULL, receipt_sha256 TEXT NOT NULL,
        event_id INTEGER NOT NULL, captured_at TEXT NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_worker_scope_evidence_task "
                 "ON worker_scope_evidence(task_id,result_id)")


def _snapshot_valid(snapshot, task_id):
    if (not isinstance(snapshot, dict) or set(snapshot) != _SNAPSHOT_KEYS
            or snapshot.get("schema") != "bach.task-scope-snapshot.v1"
            or snapshot.get("availability") != "available"
            or type(snapshot.get("task_id")) is not int or snapshot["task_id"] != task_id
            or snapshot.get("repository") != "ellmos-ai/bach"
            or snapshot.get("origin") != "https://github.com/ellmos-ai/bach"
            or snapshot.get("branch") != f"refs/heads/bach-task/{task_id}"
            or snapshot.get("clean_scope") != "porcelain-v1-z-all-untracked-no-ignored"
            or not _OID.fullmatch(snapshot.get("head_oid", ""))
            or not _OID.fullmatch(snapshot.get("tree_oid", ""))
            or len(snapshot["head_oid"]) != len(snapshot["tree_oid"])):
        return False
    for key in ("repo_path_sha256", "worktree_path_sha256", "common_dir_sha256",
                "status_sha256", "index_sha256", "project_state_ref", "workspace_fingerprint"):
        if not isinstance(snapshot.get(key), str) or not _HEX.fullmatch(snapshot[key]):
            return False
    if snapshot["status_sha256"] != hashlib.sha256(b"").hexdigest():
        return False
    pin = snapshot["source_pin"]
    if pin is not None and (not isinstance(pin, dict)
            or set(pin) != {"schema", "source_ref", "source_sha", "verified_at"}
            or pin["schema"] != "bach.task-public-source.v1"
            or pin["source_ref"] != "refs/heads/main"
            or not isinstance(pin["source_sha"], str)
            or not re.fullmatch(r"[0-9a-f]{40}", pin["source_sha"])
            or not isinstance(pin["verified_at"], str) or not pin["verified_at"]):
        return False
    project = _digest({"repository": snapshot["repository"], "origin": snapshot["origin"],
                       "source_pin": pin, "head_oid": snapshot["head_oid"]})
    workspace = _digest({
        "worktree_path_sha256": snapshot["worktree_path_sha256"],
        "common_dir_sha256": snapshot["common_dir_sha256"],
        "branch": snapshot["branch"], "tree_oid": snapshot["tree_oid"],
        "clean_scope": snapshot["clean_scope"],
        "status_sha256": snapshot["status_sha256"],
        "index_sha256": snapshot["index_sha256"]})
    return (snapshot["project_state_ref"] == project
            and snapshot["workspace_fingerprint"] == workspace)


def _receipt(record, snapshot, captured_at):
    return {"schema": _RECEIPT_SCHEMA, "task_id": record["task_id"],
            "result_id": record["result_id"], "fence": record["fence"],
            "generation": record["generation"],
            "task_scope_version": record["task_version"],
            "result_sha256": record["result_sha256"],
            "submission_revision": record["submission_revision"],
            "submission_event_id": record["submission_event_id"],
            "submitted_status_event_id": record["submitted_status_event_id"],
            "snapshot": snapshot, "captured_at": captured_at}


def _event_detail(receipt, receipt_sha256):
    return {"task_id": receipt["task_id"], "result_id": receipt["result_id"],
            "fence": receipt["fence"], "generation": receipt["generation"],
            "submission_revision": receipt["submission_revision"],
            "task_scope_version": receipt["task_scope_version"],
            "scope_receipt_sha256": receipt_sha256,
            "captured_at": receipt["captured_at"]}


def capture_scope_evidence(conn, binding) -> bool:
    """Capture one real current submission and Git snapshot, without a second queue.

    Git and lock reads happen before BEGIN IMMEDIATE. The native result,
    generation, fence and task content are rechecked under that transaction.
    Existing result receipts are never overwritten.
    """
    if conn.in_transaction:
        return False
    try:
        record = _submitted(conn, binding)
        if record is None:
            return False
        snapshot = snapshot_task_scope(binding.task_id)
        if not _snapshot_valid(snapshot, binding.task_id):
            return False
        # The read above has no SQLite write transaction; the following one
        # serializes the immutable link and its history row.
        conn.execute("BEGIN IMMEDIATE")
        _ensure_schema(conn)
        current = _submitted(conn, binding)
        if (current is None or any(current.get(key) != record.get(key) for key in
                ("task_id", "result_id", "fence", "generation", "task_version",
                 "result_sha256", "submission_revision", "submission_event_id",
                 "submitted_status_event_id"))):
            conn.rollback()
            return False
        existing = _row(conn.execute(
            "SELECT * FROM worker_scope_evidence WHERE result_id=?", (record["result_id"],)))
        if existing is not None:
            observed = read_scope_evidence(conn, current)
            valid = (observed["availability"] == "recorded"
                     and observed["snapshot"] == snapshot)
            conn.rollback()
            return valid
        now = binding._clock()
        receipt = _receipt(current, snapshot, _fmt(now))
        digest = _digest(receipt)
        event_id = _history(conn, current["task_id"], _EVENT_ACTION, _ACTOR,
                            now, _event_detail(receipt, digest))
        if (type(event_id) is not int or event_id <= current["submission_event_id"]):
            conn.rollback()
            return False
        conn.execute("""INSERT INTO worker_scope_evidence
            (task_id,result_id,fence,generation,task_version,submission_revision,
             receipt,receipt_sha256,event_id,captured_at)
             VALUES (?,?,?,?,?,?,?,?,?,?)""",
             (current["task_id"], current["result_id"], current["fence"],
              current["generation"], current["task_version"],
              current["submission_revision"], _json(receipt), digest,
              event_id, receipt["captured_at"]))
        if read_scope_evidence(conn, current)["availability"] != "recorded":
            conn.rollback()
            return False
        conn.commit()
        return True
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        return False
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise


def read_scope_evidence(conn, record) -> dict:
    """Verify one persisted scope receipt and exact history; no DDL or Git."""
    if (not isinstance(record, dict) or record.get("reason") not in {"awaiting_review", "accepted"}
            or record.get("submission", {}).get("availability") != "available"
            or not isinstance(record.get("submission_revision"), str)
            or not _HEX.fullmatch(record["submission_revision"])):
        return _unavailable("submission_not_current")
    try:
        table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                             "AND name='worker_scope_evidence'").fetchone()
        if table is None:
            return _unavailable("scope_not_recorded")
        result_id = record.get("result_id")
        if type(result_id) is not int or result_id <= 0:
            return _unavailable("scope_evidence_invalid")
        row = _row(conn.execute("SELECT * FROM worker_scope_evidence WHERE result_id=?",
                                (result_id,)))
        if row is None:
            return _unavailable("scope_not_recorded")
        result = _row(conn.execute("SELECT * FROM worker_task_results WHERE id=?", (result_id,)))
        if result is None:
            return _unavailable("scope_evidence_invalid")
        for key, left, right in (
                ("task_id", row["task_id"], record.get("task_id")),
                ("fence", row["fence"], record.get("fence")),
                ("generation", row["generation"], record.get("generation")),
                ("task_version", row["task_version"], record.get("task_version"))):
            if (left != right or result[key] != right
                    or (key in {"task_id", "fence"} and (type(right) is not int or right <= 0))):
                return _unavailable("scope_evidence_invalid")
        if (type(row["id"]) is not int or row["id"] <= 0
                or type(row["result_id"]) is not int or row["result_id"] != result_id
                or type(row["event_id"]) is not int or row["event_id"] <= 0
                or not isinstance(row["submission_revision"], str)
                or row["submission_revision"] != record["submission_revision"]
                or result["result_sha256"] != record.get("result_sha256")):
            return _unavailable("scope_evidence_invalid")
        receipt = json.loads(row["receipt"])
        if (not isinstance(receipt, dict) or receipt.get("schema") != _RECEIPT_SCHEMA
                or _digest(receipt) != row["receipt_sha256"]
                or receipt.get("task_id") != row["task_id"]
                or receipt.get("result_id") != result_id
                or receipt.get("fence") != row["fence"]
                or receipt.get("generation") != row["generation"]
                or receipt.get("task_scope_version") != row["task_version"]
                or receipt.get("task_scope_version") != record["task_version"]
                or receipt.get("result_sha256") != record["result_sha256"]
                or receipt.get("submission_revision") != row["submission_revision"]
                or receipt.get("submission_event_id") != record["submission_event_id"]
                or receipt.get("submitted_status_event_id") != record["submitted_status_event_id"]
                or receipt.get("captured_at") != row["captured_at"]
                or not _snapshot_valid(receipt.get("snapshot"), row["task_id"])):
            return _unavailable("scope_evidence_invalid")
        if (type(receipt["task_id"]) is not int or type(receipt["result_id"]) is not int
                or type(receipt["fence"]) is not int
                or type(receipt["submission_event_id"]) is not int
                or type(receipt["submitted_status_event_id"]) is not int
                or not 0 < receipt["submitted_status_event_id"] < receipt["submission_event_id"] < row["event_id"]
                or not isinstance(receipt["task_scope_version"], str)
                or not _HEX.fullmatch(receipt["task_scope_version"])):
            return _unavailable("scope_evidence_invalid")
        event = _row(conn.execute("SELECT * FROM task_history WHERE id=?", (row["event_id"],)))
        captured = parse_ts(receipt["captured_at"])
        if (event is None or captured is None or event["task_id"] != row["task_id"]
                or event["action"] != _EVENT_ACTION or event["field_changed"] != "lease"
                or event["changed_by"] != _ACTOR or event["old_value"] is not None
                or event["changed_at"] != _local_naive(captured)
                or json.loads(event["new_value"]) != _event_detail(receipt, row["receipt_sha256"])):
            return _unavailable("scope_evidence_invalid")
        # Re-evaluate the canonical execution receipt, not caller-supplied flags.
        execution = read_execution_evidence(conn, record)
        execution_revision = (execution.get("execution_revision")
                              if execution.get("availability") == "available" else None)
        if execution_revision is not None and not _HEX.fullmatch(execution_revision):
            execution_revision = None
        return {"schema": _READ_SCHEMA, "availability": "recorded",
                "task_id": row["task_id"], "result_id": result_id,
                "submission_revision": row["submission_revision"],
                "task_scope_version": row["task_version"],
                "scope_receipt_sha256": row["receipt_sha256"],
                "scope_event_id": row["event_id"],
                "snapshot": receipt["snapshot"],
                "execution_revision": execution_revision,
                "result_revision": None}
    except sqlite3.DatabaseError:
        return _unavailable("scope_schema_unavailable")
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return _unavailable("scope_evidence_invalid")


def _project_scope_record(data, *, repo_root=None, worktrees_dir=None) -> dict:
    if not isinstance(data, dict) or data.get("availability") != "recorded":
        if isinstance(data, dict) and data.get("schema") == _READ_SCHEMA:
            return {**data, "result_revision": None}
        return _unavailable("scope_not_recorded")
    if (type(data.get("task_id")) is not int or data["task_id"] <= 0
            or type(data.get("scope_event_id")) is not int or data["scope_event_id"] <= 0
            or not isinstance(data.get("submission_revision"), str)
            or not _HEX.fullmatch(data["submission_revision"])
            or not isinstance(data.get("scope_receipt_sha256"), str)
            or not _HEX.fullmatch(data["scope_receipt_sha256"])
            or not _snapshot_valid(data.get("snapshot"), data["task_id"])):
        return _unavailable("scope_evidence_invalid")
    try:
        current = snapshot_task_scope(data["task_id"], repo_root=repo_root,
                                      worktrees_dir=worktrees_dir)
    except Exception:
        return _unavailable("current_git_unavailable")
    if not isinstance(current, dict):
        return _unavailable("current_git_unavailable")
    if current.get("availability") != "available":
        return _unavailable("current_git_unavailable")
    if current != data["snapshot"]:
        return _unavailable("current_git_changed")
    execution_revision = data.get("execution_revision")
    result_revision = (_digest({"schema": _REVISION_SCHEMA,
                                "submission_revision": data["submission_revision"],
                                "execution_revision": execution_revision,
                                "scope_receipt_sha256": data["scope_receipt_sha256"],
                                "scope_event_id": data["scope_event_id"]})
                       if isinstance(execution_revision, str)
                       and _HEX.fullmatch(execution_revision) else None)
    return {**data, "availability": "available", "result_revision": result_revision}


def project_scope_evidence(data, *, repo_root=None, worktrees_dir=None) -> dict:
    """Project a full read_result DTO after its SQLite read transaction ends.

    A direct scope-record call is accepted for local, read-only consumers, but
    SDK and API callers pass the complete readback and receive its copied shape.
    """
    if not isinstance(data, dict):
        return data
    if data.get("schema") == _READ_SCHEMA:
        try:
            return _project_scope_record(data, repo_root=repo_root,
                                         worktrees_dir=worktrees_dir)
        except (KeyError, TypeError, ValueError, AttributeError):
            return _unavailable("scope_evidence_invalid")
    if data.get("schema") != "bach.task-result-readback.v1":
        return data.copy()
    result = data.get("result")
    if not isinstance(result, dict):
        return data.copy()
    try:
        scope = _project_scope_record(result.get("scope"), repo_root=repo_root,
                                      worktrees_dir=worktrees_dir)
    except (KeyError, TypeError, ValueError, AttributeError):
        scope = _unavailable("scope_evidence_invalid")
    projected_result = {**result, "scope": scope,
                        "result_revision": scope.get("result_revision")}
    return {**data, "result": projected_result}
