# SPDX-License-Identifier: MIT
"""Personal, atomic requeue of one stale or note-only review task.

The old result and every release note remain evidence. This operation neither
accepts a result nor supplies missing scope, author or submission attestation.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import Counter

from hub._services.task_lease import _CLEARED_ON_RELEASE, RELEASE_OUTCOMES, task_content_version, _utcnow, _local_naive
from hub._services.task_result_service import (
    ResultConflict, ResultPermissionDenied, _correction_operator_device_id,
    _dict_row, _legacy_result,
    _status_revision, _table_exists, _submission_readback,
    active_correction_request,
)
from hub.task_audit import apply_task_field_changes

SCHEMA = "bach.review-task-requeue.v1"
ELIGIBILITY_SCHEMA = "bach.review-task-requeue-eligibility.v1"
CASES = {"stale_result", "release_note_without_result"}
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_HISTORY_LIMIT = 10000
_PRECONDITIONS = {
    "task_version", "status_revision", "history_revision", "history_sha256",
    "lease_fence", "lease_sha256", "results_sha256", "intent_sha256",
    "release_audit_sha256", "result_id", "result_preimage_sha256",
}


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _decode(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate key")
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("constant")))


def _all_rows(conn, sql, params):
    cursor = conn.execute(sql, params)
    names = [column[0] for column in cursor.description]
    rows = [dict(zip(names, tuple(row))) for row in cursor.fetchmany(_HISTORY_LIMIT + 1)]
    if len(rows) > _HISTORY_LIMIT:
        raise ResultConflict("Vollständige Review-Provenienz ist nicht bestätigt")
    return rows


def _correction_pointer_state(conn, task):
    """Bind a present correction pointer to its immutable ledger and result history."""
    pointer = task.get("result_correction_request_id")
    if pointer is None:
        return {"pointer": None, "state": "absent"}
    if type(pointer) is not int or pointer <= 0:
        return {"pointer": pointer, "state": "unconfirmed", "reason": "invalid_pointer"}

    task_id = task.get("id")
    if type(task_id) is not int or task_id <= 0:
        return {"pointer": pointer, "state": "unconfirmed", "reason": "invalid_task"}
    try:
        # This canonical reader validates the pointer's task-bound request,
        # immutable audit event, source-result digest and latest-result order.
        active = active_correction_request(conn, task_id)
        request = _dict_row(conn.execute(
            "SELECT * FROM task_result_corrections WHERE id=? AND task_id=?", (pointer, task_id)
        ))
        if (request is None or request.get("id") != pointer or request.get("task_id") != task_id
                or type(request.get("source_result_id")) is not int or request["source_result_id"] <= 0
                or type(request.get("event_id")) is not int or request["event_id"] <= 0):
            return {"pointer": pointer, "state": "unconfirmed", "reason": "request_unconfirmed"}
        audit = _dict_row(conn.execute(
            "SELECT * FROM task_history WHERE id=? AND task_id=? AND action='result_correction_request'",
            (request["event_id"], task_id),
        ))
        source = _dict_row(conn.execute(
            "SELECT * FROM worker_task_results WHERE id=? AND task_id=?",
            (request["source_result_id"], task_id),
        ))
        latest = _dict_row(conn.execute(
            "SELECT * FROM worker_task_results WHERE task_id=? ORDER BY id DESC LIMIT 1", (task_id,)
        ))
        if (audit is None or source is None or latest is None
                or type(latest.get("id")) is not int or latest["id"] <= 0
                or source.get("id") != request["source_result_id"]
                or type(source.get("result")) is not str
                or source.get("result_sha256") != request.get("source_result_sha256")
                or hashlib.sha256(source["result"].encode("utf-8")).hexdigest() != source.get("result_sha256")
                or source.get("generation") != request.get("source_generation")
                or source.get("fence") != request.get("source_fence")
                or source.get("task_version") != request.get("source_task_version")):
            return {"pointer": pointer, "state": "unconfirmed", "reason": "result_or_audit_unconfirmed"}

        source_id = request["source_result_id"]
        if active is None:
            # None is accepted only with a non-null, strictly correlated
            # pointer and an independently read later result in this snapshot.
            if latest["id"] <= source_id:
                return {"pointer": pointer, "state": "unconfirmed", "reason": "inactive_order_unconfirmed"}
            state = "historical_inactive"
        else:
            if (active.get("correction_id") != pointer or latest["id"] != source_id
                    or active.get("source_result_id") != source_id
                    or active.get("source_result_sha256") != source.get("result_sha256")):
                return {"pointer": pointer, "state": "unconfirmed", "reason": "active_order_unconfirmed"}
            state = "active"
        return {
            "pointer": pointer,
            "state": state,
            "request_sha256": _digest(request),
            "audit_sha256": _digest(audit),
            "source_result_id": source_id,
            "source_result_sha256": source.get("result_sha256"),
            "latest_result_id": latest["id"],
            "latest_result_sha256": latest.get("result_sha256"),
        }
    except Exception:
        # Any reader/schema failure means the immutable inactivity proof is
        # unknown. It must never turn a pointer into requeue permission.
        return {"pointer": pointer, "state": "unconfirmed", "reason": "correction_ledger_unconfirmed"}


def _intent_state(conn, task_id, task=None):
    # Historical entries are preserved and bound too. A present review intent
    # is conservatively denied; this owner never closes another review owner.
    if task is None:
        task = _dict_row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
    if task is None:
        raise ResultConflict("Korrekturzeiger-Provenienz ist nicht bestätigt")
    state = {"correction_pointer": _correction_pointer_state(conn, task)}
    for table, where, params in (
        ("task_result_corrections", "task_id=?", (task_id,)),
        ("worker_result_review_intents", "review_task_id=? OR target_task_id=?", (task_id, task_id)),
        ("worker_result_model_reviews", "review_task_id=? OR target_task_id=?", (task_id, task_id)),
    ):
        if not _table_exists(conn, table):
            raise ResultConflict("Review-Intent-Schema ist nicht bestätigt")
        state[table] = sorted(_all_rows(conn, f"SELECT * FROM {table} WHERE {where}", params), key=_json)
    children = {}
    for item in state["worker_result_review_intents"]:
        child_id = item.get("review_task_id")
        if type(child_id) is not int or child_id <= 0:
            raise ResultConflict("Review-Intent-Provenienz ist nicht bestätigt")
        child = _dict_row(conn.execute("SELECT * FROM tasks WHERE id=?", (child_id,)))
        children[str(child_id)] = None if child is None else {
            "status": child["status"], "task_version": task_content_version(child),
            "lease_fence": child.get("claim_fence"),
            "lease_sha256": _digest({name: child.get(name) for name in _CLEARED_ON_RELEASE}),
        }
    state["review_children"] = children
    return state


def _intent_projection(state):
    counts = Counter()
    for item in state["worker_result_review_intents"]:
        child = state["review_children"].get(str(item["review_task_id"]))
        receipt = any(row.get("review_task_id") == item["review_task_id"]
                      and row.get("target_result_id") == item.get("target_result_id")
                      and row.get("target_revision") == item.get("target_revision")
                      for row in state["worker_result_model_reviews"])
        if child is None:
            counts["orphaned"] += 1
        elif child["status"] in {"pending", "open", "in_progress", "review"}:
            counts["open"] += 1
        elif child["status"] in {"done", "completed"} and receipt:
            counts["terminal_receipt_requires_canonical_validation"] += 1
        else:
            counts["unconfirmed"] += 1
    return {"review_intents": dict(counts),
            "model_review_rows": len(state["worker_result_model_reviews"]),
            "historical_corrections": len(state["task_result_corrections"])}


def _release_state(history):
    released, kinds = [], Counter()
    for event in history:
        if event["action"] != "lease_release":
            continue
        try:
            detail = _decode(event["new_value"])
        except (TypeError, ValueError):
            raise ResultConflict("Release-Provenienz ist nicht bestätigt") from None
        if (type(detail) is not dict or type(detail.get("fence")) is not int
                or detail["fence"] < 0 or type(detail.get("outcome")) is not str
                or detail["outcome"] not in RELEASE_OUTCOMES
                or type(detail.get("note")) not in {str, type(None)}
                or type(detail.get("result_ref")) not in {str, type(None)}):
            raise ResultConflict("Release-Provenienz ist nicht bestätigt")
        note = detail.get("note")
        kind = "absent" if not note else "text"
        if note:
            try:
                parsed = _decode(note)
                kind = "json_note" if isinstance(parsed, (dict, list)) else "scalar_note"
            except (TypeError, ValueError):
                pass
        kinds[kind] += 1
        released.append({"event_id": event["id"], "detail": detail, "actor": event["changed_by"],
                         "audit_sha256": _digest(event), "note_kind": kind})
    projection = {
        "count": len(released), "note_kinds": dict(kinds),
        "with_result_reference": sum(bool(item["detail"].get("result_ref")) for item in released),
        "with_submission_receipt": sum(item["detail"].get("submission_receipt") is not None for item in released),
        "latest_event_id": released[-1]["event_id"] if released else None,
        "latest_outcome": released[-1]["detail"]["outcome"] if released else None,
        "latest_fence": released[-1]["detail"]["fence"] if released else None,
    }
    return released, projection


def _observe(conn, task_id):
    """Shared, SQL-read-only guard; caller owns its consistent transaction."""
    if not conn.in_transaction:
        raise ResultConflict("Review-Beobachtung benötigt eine eigene Transaktion")
    if type(task_id) is not int or task_id <= 0:
        raise ValueError("Ungültige Task-ID")
    required = {"tasks", "task_history", "worker_task_results"}
    if not all(_table_exists(conn, name) for name in required):
        raise ResultConflict("Task-/Result-/Auditstore ist nicht bestätigt")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
    if not {"id", "status", "claim_fence", "result_correction_request_id", *_CLEARED_ON_RELEASE} <= columns:
        raise ResultConflict("Task-Lease-Schema ist nicht bestätigt")
    task = _dict_row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
    if task is None:
        raise ResultConflict("Aufgabe nicht vorhanden")
    history = _all_rows(conn, "SELECT * FROM task_history WHERE task_id=? ORDER BY id", (task_id,))
    results = _all_rows(conn, "SELECT * FROM worker_task_results WHERE task_id=? ORDER BY id", (task_id,))
    intents = _intent_state(conn, task_id, task)
    releases, release_projection = _release_state(history)
    blockers = []
    if task["status"] != "review":
        blockers.append("task_not_in_review")
    if any(task.get(name) not in (None, "") for name in _CLEARED_ON_RELEASE):
        blockers.append("lease_or_claim_present")
    pointer_state = intents["correction_pointer"]["state"]
    if task.get("result_correction_request_id") is not None and pointer_state != "historical_inactive":
        blockers.append("correction_pointer_present")
    if pointer_state == "unconfirmed":
        blockers.append("correction_pointer_unconfirmed")
    if task.get("result") is not None or str(task.get("source") or "").startswith("worker-result-review:v1:"):
        blockers.append("other_result_or_review_contract")
    if intents["worker_result_review_intents"] or intents["worker_result_model_reviews"]:
        blockers.append("review_intent_or_model_review_present")
    fence = task.get("claim_fence")
    if type(fence) is not int or fence < 0:
        raise ResultConflict("Lease-Fence ist nicht bestätigt")
    record = results[-1] if results else None
    case, result_projection = None, None
    if record is not None:
        if (type(record.get("id")) is not int or record["id"] <= 0 or type(record.get("result")) is not str
                or type(record.get("result_sha256")) is not str
                or not _SHA.fullmatch(record["result_sha256"])
                or hashlib.sha256(record["result"].encode("utf-8")).hexdigest() != record["result_sha256"]
                or type(record.get("task_version")) is not str or not _SHA.fullmatch(record["task_version"])
                or type(record.get("fence")) is not int or record["fence"] < 0
                or type(record.get("generation")) is not str or not record["generation"]):
            blockers.append("result_provenance_unconfirmed")
        else:
            acceptance = any(record.get(key) is not None for key in
                             ("accepted_by", "accepted_at", "accepted_status_event_id", "acceptance_event_id"))
            if acceptance:
                blockers.append("accepted_result")
            if record["task_version"] == task_content_version(task):
                blockers.append("current_result_requires_existing_review")
            else:
                case = "stale_result"
            submission = _submission_readback(conn, record)
            if submission.get("availability") not in {"available", "legacy_release_only"}:
                blockers.append("submission_provenance_unconfirmed")
            result_projection = {key: record.get(key) for key in
                ("id", "result_sha256", "task_version", "generation", "fence",
                 "submission_event_id", "submission_receipt_sha256")}
            result_projection["acceptance_markers_present"] = acceptance
    else:
        case = "release_note_without_result"
        if (_legacy_result(conn, task_id) is not None or intents["task_result_corrections"]
                or any(str(event["action"]).startswith(("result_", "worker_result_"))
                       or event["action"] in {"worker_completion_decision", "late_result"} for event in history)):
            blockers.append("other_result_history_present")
        if (not releases or release_projection["latest_outcome"] != "review"
                or release_projection["latest_fence"] != fence
                or not any(item["detail"].get("note") for item in releases)
                or release_projection["with_result_reference"]
                or release_projection["with_submission_receipt"]):
            blockers.append("note_only_release_provenance_unconfirmed")
        status_event = next((event for event in history if event["id"] == _status_revision(conn, task_id)), None)
        if (not releases or status_event is None or status_event.get("action") != "status_change"
                or status_event.get("new_value") != "review"
                or status_event["id"] >= releases[-1]["event_id"]
                or status_event["changed_by"] != releases[-1]["actor"]):
            blockers.append("review_release_status_provenance_unconfirmed")
    preconditions = {
        "task_version": task_content_version(task), "status_revision": _status_revision(conn, task_id),
        "history_revision": history[-1]["id"] if history else 0, "history_sha256": _digest(history),
        "lease_fence": fence, "lease_sha256": _digest({name: task.get(name) for name in _CLEARED_ON_RELEASE}),
        "results_sha256": _digest(results), "intent_sha256": _digest(intents),
        "release_audit_sha256": _digest(releases), "result_id": record["id"] if record else None,
        "result_preimage_sha256": _digest(record),
    }
    return ({"schema": ELIGIBILITY_SCHEMA, "availability": "available", "task_id": task_id,
             "status": task["status"], "case": case, "eligible": not blockers and case in CASES,
             "blockers": blockers, "preconditions": preconditions,
             "release_provenance": release_projection, "result_provenance": result_projection,
             "intent_provenance": _intent_projection(intents),
             "write_rechecks_required": True}, task)


def _operator(conn, token):
    device = _correction_operator_device_id(conn, token)
    if device is None:
        raise ResultPermissionDenied("Persönliche Korrekturberechtigung fehlt oder wurde widerrufen")
    return device


def review_requeue_eligibility(conn, task_id, *, operator_token):
    if conn.in_transaction:
        raise ResultConflict("Review-Eignung benötigt eine eigene Transaktion")
    device = _operator(conn, operator_token)
    conn.execute("BEGIN")
    try:
        if _operator(conn, operator_token) != device:
            raise ResultPermissionDenied("Korrekturberechtigung wurde geändert")
        return _observe(conn, task_id)[0]
    finally:
        if conn.in_transaction:
            conn.rollback()


def _request(payload):
    if type(payload) is not dict or set(payload) != {"request_id", "case", "preconditions"}:
        raise ValueError("Ungültiger Requeue-Auftrag")
    if type(payload["request_id"]) is not str:
        raise ValueError("Ungültige Request-ID")
    try:
        request_id = uuid.UUID(payload["request_id"])
    except (ValueError, AttributeError):
        raise ValueError("Ungültige Request-ID") from None
    if (request_id.version != 4 or str(request_id) != payload["request_id"]
            or type(payload["case"]) is not str or payload["case"] not in CASES):
        raise ValueError("Ungültiger Requeue-Auftrag")
    pre = payload["preconditions"]
    if type(pre) is not dict or set(pre) != _PRECONDITIONS:
        raise ValueError("Vollständige Requeue-Preimages fehlen")
    for key in _PRECONDITIONS:
        value = pre[key]
        if key.endswith("sha256") or key == "task_version":
            if type(value) is not str or not _SHA.fullmatch(value):
                raise ValueError("Ungültiges Requeue-Preimage")
        elif key == "result_id" and value is None:
            pass
        elif type(value) is not int or value < 0 or (key == "result_id" and value == 0):
            raise ValueError("Ungültige Requeue-Revision")
    return payload


def requeue_review_task(conn, task_id, payload, *, operator_token):
    """One official writer, with durable history-based request recovery."""
    request = _request(payload)
    if type(task_id) is not int or task_id <= 0 or conn.in_transaction:
        raise ValueError("Ungültige Task-ID oder offene Transaktion")
    device = _operator(conn, operator_token)
    actor = f"operator-device:{device}"
    request_sha = _digest({"task_id": task_id, "request": request})
    conn.execute("BEGIN IMMEDIATE")
    try:
        if _operator(conn, operator_token) != device:
            raise ResultPermissionDenied("Korrekturberechtigung wurde geändert")
        old_events = _all_rows(conn, "SELECT id,new_value,changed_by FROM task_history "
                               "WHERE task_id=? AND action='review_task_requeue' ORDER BY id", (task_id,))
        for event in old_events:
            try:
                detail = _decode(event["new_value"])
            except (TypeError, ValueError):
                raise ResultConflict("Requeue-Audit ist nicht bestätigt") from None
            if type(detail) is not dict:
                raise ResultConflict("Requeue-Audit ist nicht bestätigt")
            if detail.get("request_id") != request["request_id"]:
                continue
            if (detail.get("schema") != SCHEMA or detail.get("request_sha256") != request_sha
                    or detail.get("device_id") != device or event["changed_by"] != actor
                    or type(detail.get("ack")) is not dict or detail["ack"].get("task_id") != task_id):
                raise ResultConflict("Request-ID wurde bereits anders verwendet")
            ack = {**detail["ack"], "event_id": event["id"], "replayed": True}
            conn.rollback()
            return ack
        before, task = _observe(conn, task_id)
        if (not before["eligible"] or before["case"] != request["case"]
                or _json(before["preconditions"]) != _json(request["preconditions"])):
            raise ResultConflict("Review-/Result-/Intent-/Lease-Preimages geändert; neu laden")
        if _operator(conn, operator_token) != device:
            raise ResultPermissionDenied("Korrekturberechtigung wurde geändert")
        changed = apply_task_field_changes(conn, task_id, task, {"status": "pending"},
                                          changed_by=actor, allow_reopen=True)
        after = _dict_row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
        revision = _status_revision(conn, task_id)
        status_event = _dict_row(conn.execute("SELECT * FROM task_history WHERE id=? AND task_id=?", (revision, task_id)))
        if (changed is not True or after is None or after["status"] != "pending"
                or any(after.get(name) not in (None, "") for name in _CLEARED_ON_RELEASE)
                or after.get("claim_fence") != before["preconditions"]["lease_fence"]
                or task_content_version(after) != before["preconditions"]["task_version"]
                or status_event is None or status_event["action"] != "status_change"
                or status_event["old_value"] != "review" or status_event["new_value"] != "pending"
                or status_event["changed_by"] != actor or revision <= before["preconditions"]["status_revision"]):
            raise ResultConflict("Auditierter Requeue-Statuswechsel nicht bestätigt")
        # Verify preservation before committing. No result, note or intent row
        # is updated/deleted by this owner, even when the old output is stale.
        result_rows = _all_rows(conn, "SELECT * FROM worker_task_results WHERE task_id=? ORDER BY id", (task_id,))
        if (_digest(result_rows) != before["preconditions"]["results_sha256"]
                or _digest(_intent_state(conn, task_id)) != before["preconditions"]["intent_sha256"]
                or _digest(_all_rows(conn, "SELECT * FROM task_history WHERE task_id=? AND id<=? ORDER BY id",
                                    (task_id, before["preconditions"]["history_revision"])))
                != before["preconditions"]["history_sha256"]):
            raise ResultConflict("Result-/Intent-Erhalt nicht bestätigt")
        ack = {"schema": SCHEMA, "task_id": task_id, "request_id": request["request_id"],
               "applied": True, "status_at_event": "pending", "case": request["case"],
               "previous_task_version": before["preconditions"]["task_version"],
               "task_version": task_content_version(after),
               "previous_status_revision": before["preconditions"]["status_revision"],
               "status_revision": revision, "status_event_id": revision,
               "preserved_result_id": before["preconditions"]["result_id"],
               "preserved_results_sha256": before["preconditions"]["results_sha256"],
               "preserved_release_audit_sha256": before["preconditions"]["release_audit_sha256"],
               "replayed": False, "current_readback_required": True}
        detail = {"schema": SCHEMA, "request_id": request["request_id"], "request_sha256": request_sha,
                  "device_id": device, "case": request["case"], "before": before["preconditions"], "ack": ack}
        cursor = conn.execute("INSERT INTO task_history "
            "(task_id,action,field_changed,old_value,new_value,changed_by,changed_at) VALUES (?,?,?,?,?,?,?)",
            (task_id, "review_task_requeue", "review_requeue", "review", _json(detail), actor, _local_naive(_utcnow())))
        ack["event_id"] = cursor.lastrowid
        conn.commit()
        return ack
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
