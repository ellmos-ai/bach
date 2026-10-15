# SPDX-License-Identifier: MIT
"""Private native model-call receipts; no reviewer authority or public attestation.

Only the controller's actual dispatch boundary calls this module. The opaque
handle stays in its WorkerLeaseBinding; providers see neither it nor the lease.
Readback is additive and read-only, including on old databases.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid

from .task_lease import LeaseConfig, _fmt, _history, _load_for_holder, _local_naive
from .model_provenance import reported_model

_SEAL = object()
_ACTOR = "native-model-controller"
_LEGACY_SCHEMA = "bach.worker-model-execution.v1"
_SCHEMA = "bach.worker-model-execution.v2"
_READ_SCHEMA = "bach.worker-execution-evidence.v2"
_HEX = re.compile(r"[a-f0-9]{64}\Z")


class ExecutionHandle:
    """Process-private correlation, never a serializable provider capability."""
    __slots__ = ("_binding", "_execution_id", "_seal")

    def __init__(self, binding, execution_id, *, _seal=None):
        if _seal is not _SEAL:
            raise ValueError("Private controller handle required")
        self._binding = binding
        self._execution_id = execution_id
        self._seal = _seal

    def __repr__(self):
        return "<ExecutionHandle private>"


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _row(cursor):
    row = cursor.fetchone()
    return dict(zip((col[0] for col in cursor.description), row)) if row is not None else None


def _ensure_schema(conn):
    # Called only inside an explicit writer transaction, never by any GET.
    conn.execute("""CREATE TABLE IF NOT EXISTS worker_model_executions (
        id TEXT PRIMARY KEY, task_id INTEGER NOT NULL, fence INTEGER NOT NULL,
        generation TEXT NOT NULL, phase TEXT NOT NULL CHECK(phase IN ('attempted','returned','failed')),
        receipt TEXT NOT NULL, receipt_sha256 TEXT NOT NULL, started_event_id INTEGER NOT NULL,
        terminal_event_id INTEGER, result_id INTEGER UNIQUE, submission_revision TEXT,
        link_event_id INTEGER, linked_at TEXT)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_worker_model_execution_task ON "
                 "worker_model_executions(task_id,fence,generation)")


def _current(binding):
    from .chat.worker_lease_binding import WorkerLeaseBinding
    return (isinstance(binding, WorkerLeaseBinding) and binding._is_current()
            and not binding._stop_event.is_set()
            and binding._ack.result_generation == binding.generation)


def _holder(conn, binding, now):
    if not _current(binding) or not binding._active or binding._closed:
        return False
    ack = binding._ack
    task, problem = _load_for_holder(conn, binding.task_id, ack.lease_id, ack.fence, now,
                                    LeaseConfig.from_env(), binding._snapshot.get("task_version"))
    return (not problem and task.get("status") == "in_progress"
            and task.get("claim_result_generation") == binding.generation)


def _submitted(conn, binding):
    """A real Submit-ACK and current canonical receipt replace the released lease."""
    if not _current(binding):
        return None
    completion = binding._completion_result
    expected = binding._submission_expected
    ack = binding._review_ack
    if not isinstance(expected, dict) or (completion is not None and not isinstance(completion, dict)):
        return None
    from .task_result_service import read_result
    observed = read_result(conn, binding.task_id)
    record = observed.get("result")
    if (not isinstance(record, dict) or record.get("reason") not in {"awaiting_review", "accepted"}
            or record.get("submission", {}).get("availability") != "available"
            or not isinstance(record.get("submission_revision"), str)
            or (ack is not None and (ack.released is not True or ack.task_id != binding.task_id
                or ack.fence != binding._ack.fence or ack.outcome != "review" or ack.status != "review"))
            or (completion is not None and record.get("result_id") != completion.get("result_id"))
            or record.get("generation") != binding.generation
            or record.get("fence") != binding._ack.fence
            or record.get("task_version") != binding._snapshot.get("task_version")):
        return None
    for key in ("task_id", "fence", "generation", "task_version", "result_sha256", "result"):
        if (record.get(key) != expected.get(key)
                or (completion is not None and record.get(key) != completion.get(key))):
            return None
    return record


def _owned(conn, binding, handle):
    if (not isinstance(handle, ExecutionHandle) or handle._seal is not _SEAL
            or handle._binding is not binding):
        return None
    row = _row(conn.execute("SELECT * FROM worker_model_executions WHERE id=?", (handle._execution_id,)))
    if (row is None or row["task_id"] != binding.task_id or row["fence"] != binding._ack.fence
            or row["generation"] != binding.generation):
        return None
    return row


def _metadata(value, *, required=True):
    if value is None and not required:
        return None
    if (not isinstance(value, str) or not value.strip() or len(value) > 256
            or any(ord(c) < 32 for c in value) or "://" in value):
        raise ValueError("Model route metadata invalid")
    return value


def start_execution(conn, binding, *, backend_id, requested_model, slot_id, request_sha256):
    """Write one actual attempt under the current task holder, no raw payloads."""
    if conn.in_transaction:
        return None
    backend_id = _metadata(backend_id)
    requested_model = _metadata(requested_model)
    slot_id = _metadata(slot_id, required=False)
    if not isinstance(request_sha256, str) or not _HEX.fullmatch(request_sha256):
        return None
    conn.execute("BEGIN IMMEDIATE")
    try:
        now = binding._clock()
        if not _holder(conn, binding, now):
            conn.rollback()
            return None
        _ensure_schema(conn)
        execution_id = str(uuid.uuid4())
        receipt = {"schema": _SCHEMA, "execution_id": execution_id,
            "task_id": binding.task_id, "fence": binding._ack.fence,
            "generation": binding.generation, "input_task_version": binding._snapshot["task_version"],
            "backend_id": backend_id, "requested_model": requested_model,
            "observed_model": None, "model_provenance": "unknown",
            "slot_id": slot_id, "request_sha256": request_sha256,
            "response_sha256": None, "phase": "attempted", "started_at": _fmt(now), "returned_at": None}
        event = _history(conn, binding.task_id, "worker_model_execution_start", _ACTOR, now, receipt)
        conn.execute("INSERT INTO worker_model_executions "
            "(id,task_id,fence,generation,phase,receipt,receipt_sha256,started_event_id) VALUES (?,?,?,?,?,?,?,?)",
            (execution_id, binding.task_id, binding._ack.fence, binding.generation,
             "attempted", _json(receipt), _digest(receipt), event))
        conn.commit()
        return ExecutionHandle(binding, execution_id, _seal=_SEAL)
    except BaseException:
        conn.rollback()
        raise


def _answer(result):
    if not isinstance(result, dict) or result.get("error"):
        return None
    content, tools = result.get("content"), result.get("tool_calls")
    if content is not None and not isinstance(content, str):
        return None
    if tools is not None:
        if not isinstance(tools, list):
            return None
        for call in tools:
            function = call.get("function") if isinstance(call, dict) else None
            if (not isinstance(function, dict) or not isinstance(function.get("name"), str)
                    or not function["name"].strip()):
                return None
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    return None
            if not isinstance(arguments, dict):
                return None
    if not ((isinstance(content, str) and content.strip()) or (isinstance(tools, list) and tools)):
        return None
    # `model` is a compatibility/display field and may be a request fallback.
    # Only the adapter's explicit current response field is an observation.
    observed = reported_model(result.get("provider_reported_model"))
    return _digest(result), observed


def finish_execution(conn, binding, handle, *, result=None, failed=False):
    """Positive terminal evidence requires a returned answer and live correlation."""
    if conn.in_transaction:
        return False
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = _owned(conn, binding, handle)
        if row is None:
            conn.rollback()
            return False
        receipt = json.loads(row["receipt"])
        if _digest(receipt) != row["receipt_sha256"]:
            conn.rollback()
            return False
        now = binding._clock()
        answer = None if failed else _answer(result)
        valid = (answer is not None and _current(binding)
                 and (_holder(conn, binding, now) or _submitted(conn, binding) is not None))
        phase = "returned" if valid else "failed"
        if row["phase"] != "attempted":
            same = (row["phase"] == "returned" and valid
                    and receipt.get("response_sha256") == answer[0])
            conn.rollback()
            return same
        receipt.update(phase=phase, returned_at=_fmt(now),
                       response_sha256=answer[0] if valid else None,
                       observed_model=answer[1] if valid else None)
        if receipt.get("schema") == _SCHEMA:
            receipt["model_provenance"] = "provider_reported" if valid and answer[1] is not None else "unknown"
        digest = _digest(receipt)
        event = _history(conn, binding.task_id, "worker_model_execution_terminal", _ACTOR, now,
                         {"execution_id": row["id"], "phase": phase, "receipt_sha256": digest})
        conn.execute("UPDATE worker_model_executions SET phase=?,receipt=?,receipt_sha256=?,terminal_event_id=? WHERE id=?",
                     (phase, _json(receipt), digest, event, row["id"]))
        conn.commit()
        return bool(valid)
    except BaseException:
        conn.rollback()
        raise


def _revision(row, record):
    return _digest({"execution_id": row["id"], "receipt_sha256": row["receipt_sha256"],
        "started_event_id": row["started_event_id"], "terminal_event_id": row["terminal_event_id"],
        "result_id": record["result_id"], "submission_revision": record["submission_revision"]})


def link_execution(conn, binding, handle):
    """Attach only this binding's confirmed latest answer to its real submission."""
    if conn.in_transaction or binding._model_execution_candidate is not handle:
        return False
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = _owned(conn, binding, handle)
        record = _submitted(conn, binding)
        if row is None or record is None or row["phase"] != "returned":
            conn.rollback()
            return False
        if row["result_id"] is not None:
            valid = (row["result_id"] == record["result_id"]
                     and read_execution_evidence(conn, record)["availability"] == "available")
            conn.rollback()
            return valid
        now = binding._clock()
        revision = _revision(row, record)
        detail = {"execution_id": row["id"], "execution_revision": revision,
            "result_id": record["result_id"], "submission_revision": record["submission_revision"],
            "submission_task_version": record["task_version"], "linked_at": _fmt(now)}
        event = _history(conn, binding.task_id, "worker_result_execution_link", _ACTOR, now, detail)
        conn.execute("UPDATE worker_model_executions SET result_id=?,submission_revision=?,link_event_id=?,linked_at=? WHERE id=?",
            (record["result_id"], record["submission_revision"], event, _fmt(now), row["id"]))
        # The same reader is the acceptance gate for the persisted correlation.
        if read_execution_evidence(conn, record)["availability"] != "available":
            conn.rollback()
            return False
        conn.commit()
        return True
    except BaseException:
        conn.rollback()
        raise


def _event(conn, event_id, task_id, action, expected, timestamp):
    if type(event_id) is not int or event_id <= 0:
        return False
    row = _row(conn.execute("SELECT * FROM task_history WHERE id=?", (event_id,)))
    from .task_lease import parse_ts
    return (row is not None and row["task_id"] == task_id and row["action"] == action
        and row["field_changed"] == "lease" and row["changed_by"] == _ACTOR
        and row["old_value"] is None and json.loads(row["new_value"]) == expected
        and row["changed_at"] == _local_naive(parse_ts(timestamp)))


def _unavailable(reason):
    return {"schema": _READ_SCHEMA, "availability": "unavailable", "reason": reason}


def read_execution_evidence(conn, record):
    """Project only verified, currently linked receipts. No DDL or side effects."""
    if (record.get("reason") not in {"awaiting_review", "accepted"}
            or record.get("submission", {}).get("availability") != "available"
            or not isinstance(record.get("submission_revision"), str)):
        return _unavailable("submission_not_current")
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='worker_model_executions'").fetchone() is None:
        return _unavailable("execution_not_recorded")
    try:
        row = _row(conn.execute("SELECT * FROM worker_model_executions WHERE result_id=?", (record["result_id"],)))
        if row is None:
            return _unavailable("execution_not_recorded")
        receipt = json.loads(row["receipt"])
        if (not isinstance(receipt, dict) or _digest(receipt) != row["receipt_sha256"]
                or type(receipt.get("task_id")) is not int or type(receipt.get("fence")) is not int
                or receipt.get("schema") not in {_LEGACY_SCHEMA, _SCHEMA} or receipt.get("execution_id") != row["id"]
                or row["task_id"] != record["task_id"] or receipt.get("task_id") != record["task_id"]
                or row["fence"] != record["fence"] or receipt.get("fence") != record["fence"]
                or row["generation"] != record["generation"] or receipt.get("generation") != record["generation"]
                or row["phase"] != "returned" or receipt.get("phase") != "returned"
                or row["submission_revision"] != record["submission_revision"]
                or not _HEX.fullmatch(receipt.get("request_sha256", ""))
                or not _HEX.fullmatch(receipt.get("response_sha256", ""))
                or not _HEX.fullmatch(receipt.get("input_task_version", ""))
                or not row["started_event_id"] < row["terminal_event_id"] < row["link_event_id"]):
            return _unavailable("execution_evidence_invalid")
        for key in ("backend_id", "requested_model"):
            _metadata(receipt.get(key))
        for key in ("observed_model", "slot_id"):
            _metadata(receipt.get(key), required=False)
        started = dict(receipt, phase="attempted", returned_at=None, response_sha256=None, observed_model=None)
        legacy = receipt["schema"] == _LEGACY_SCHEMA
        if not legacy:
            observed = receipt.get("observed_model")
            provenance = receipt.get("model_provenance")
            if ((observed is None and provenance != "unknown")
                    or (observed is not None and (provenance != "provider_reported"
                        or reported_model(observed) != observed))):
                return _unavailable("execution_evidence_invalid")
            started["model_provenance"] = "unknown"
        terminal = {"execution_id": row["id"], "phase": "returned", "receipt_sha256": row["receipt_sha256"]}
        revision = _revision(row, record)
        linked = {"execution_id": row["id"], "execution_revision": revision,
            "result_id": record["result_id"], "submission_revision": record["submission_revision"],
            "submission_task_version": record["task_version"], "linked_at": row["linked_at"]}
        if not (_event(conn, row["started_event_id"], row["task_id"], "worker_model_execution_start", started, receipt["started_at"])
                and _event(conn, row["terminal_event_id"], row["task_id"], "worker_model_execution_terminal", terminal, receipt["returned_at"])
                and _event(conn, row["link_event_id"], row["task_id"], "worker_result_execution_link", linked, row["linked_at"])):
            return _unavailable("execution_evidence_invalid")
        fields = ("execution_id", "backend_id", "requested_model", "observed_model", "slot_id",
                  "generation", "fence", "input_task_version", "request_sha256", "response_sha256", "started_at", "returned_at")
        return {"schema": _READ_SCHEMA, "availability": "available", **{k: receipt[k] for k in fields},
            # v1 saved display fallbacks. Preserve its immutable execution proof,
            # but never promote that legacy model value to a provider report.
            "observed_model": None if legacy else receipt["observed_model"],
            "model_provenance": "legacy_unknown" if legacy else receipt["model_provenance"],
            "execution_revision": revision, "submission_task_version": record["task_version"], "linked_at": row["linked_at"]}
    except sqlite3.DatabaseError:
        return _unavailable("execution_schema_unavailable")
    except (ValueError, TypeError, KeyError, AttributeError):
        return _unavailable("execution_evidence_invalid")
