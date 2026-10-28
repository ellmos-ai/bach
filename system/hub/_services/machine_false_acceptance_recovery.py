"""Private, evidence-bound repair of a historical machine false acceptance.

This controller changes only the current task state and correction pointer. The
original result, acceptance, and completion decision remain immutable history.
It grants neither a result-operator capability nor a personal user approval.
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid

from .task_result_service import (
    ResultConflict, _dict_row, _receipt_digest, _submission_readback,
    _submission_revision, _table_exists,
    read_result,
)
from .task_lease import _CLEARED_ON_RELEASE, _history, _local_naive, _utcnow, task_content_version
from .worker_completion_policy import (
    _current_revision_from_db, _db_fingerprint, _settings_snapshot,
    evaluate_current_result,
)
from .worker_review_identity import identity_snapshot, principal_for_execution
from hub.task_audit import apply_task_field_changes


SCHEMA = "bach.machine-false-acceptance-repair.v1"
ACTOR = "native-machine-false-acceptance-controller"
_HEX = re.compile(r"[a-f0-9]{64}\Z")
_EXPECTED = frozenset({
    "result_id", "result_sha256", "result_revision", "task_version",
    "status_revision", "acceptance_event_id", "completion_decision_event_id",
    "completion_decision_sha256", "review_event_id", "review_task_id",
    "child_result_id",
})


def _valid_request(task_id, expected, request_id):
    if type(task_id) is not int or task_id <= 0 or type(expected) is not dict or set(expected) != _EXPECTED:
        raise ResultConflict("Ungültige Maschinenkorrektur-Anfrage")
    for field in ("result_id", "status_revision", "acceptance_event_id",
                  "completion_decision_event_id", "review_event_id", "review_task_id",
                  "child_result_id"):
        if type(expected[field]) is not int or expected[field] <= 0:
            raise ResultConflict("Ungültige Maschinenkorrektur-Revision")
    for field in ("result_sha256", "result_revision", "task_version",
                  "completion_decision_sha256"):
        if type(expected[field]) is not str or not _HEX.fullmatch(expected[field]):
            raise ResultConflict("Ungültiger Maschinenkorrektur-Digest")
    try:
        parsed = uuid.UUID(request_id)
    except (ValueError, TypeError, AttributeError):
        raise ResultConflict("Ungültige Maschinenkorrektur-Anfrage") from None
    if parsed.version != 4 or str(parsed) != request_id:
        raise ResultConflict("request_id muss eine kanonische UUIDv4 sein")


def _receipt_from_audit(conn, row):
    event_id = row.get("event_id")
    if type(event_id) is not int or event_id <= 0:
        return None
    event = _dict_row(conn.execute(
        "SELECT * FROM task_history WHERE id=? AND task_id=? AND action='result_correction_request'",
        (event_id, row["task_id"])))
    if event is None or event["changed_by"] != ACTOR:
        return None
    try:
        detail = json.loads(event["new_value"])
        repair_event_id = detail.get("repair_event_id")
        if type(repair_event_id) is not int or repair_event_id <= 0 or repair_event_id >= event_id:
            return None
        repair_event = _dict_row(conn.execute(
            "SELECT * FROM task_history WHERE id=? AND task_id=?",
            (repair_event_id, row["task_id"])))
        if (repair_event is None or repair_event["action"] != "machine_false_acceptance_repair"
                or repair_event["field_changed"] != "lease" or repair_event["old_value"] is not None
                or repair_event["changed_by"] != ACTOR):
            return None
        stored = json.loads(repair_event["new_value"])
        receipt = {key: value for key, value in stored.items() if key != "receipt_sha256"}
        if (stored.get("receipt_sha256") != row["policy_decision_sha256"]
                or _receipt_digest(receipt) != row["policy_decision_sha256"]
                or receipt.get("schema") != SCHEMA
                or receipt.get("recorded_at") != repair_event["changed_at"]
                or receipt.get("request_id") != row["request_id"]
                or receipt.get("task_id") != row["task_id"]
                or receipt.get("result_id") != row["source_result_id"]
                or receipt.get("result_sha256") != row["source_result_sha256"]
                or receipt.get("task_version") != row["source_task_version"]
                or receipt.get("status_revision") != row["source_status_revision"]
                or detail.get("repair_event_id") != repair_event_id):
            return None
        return receipt
    except (TypeError, ValueError, KeyError, AttributeError, sqlite3.Error):
        return None


def repair_correction_matches(conn, row, detail):
    """Validate a historical correction without rewriting its old decision."""
    try:
        if (row.get("event_changed_by") != ACTOR or row.get("requested_by_device_id") != 0
                or detail.get("policy_decision_sha256") != row.get("policy_decision_sha256")):
            return False
        receipt = _receipt_from_audit(conn, row)
        if receipt is None or receipt.get("decision") != {
            "state": "correction_required", "completion_allowed": False,
            "task_contract_met": False,
        }:
            return False
        source = _dict_row(conn.execute(
            "SELECT * FROM worker_task_results WHERE id=? AND task_id=?",
            (row["source_result_id"], row["task_id"])))
        if (source is None or source["accepted_by"] != "native-worker-completion-policy"
                or source["acceptance_event_id"] != receipt["acceptance_event_id"]
                or source["completion_decision_event_id"] != receipt["completion_decision_event_id"]
                or source["completion_decision_sha256"] != receipt["completion_decision_sha256"]
                or source["accepted_status_event_id"] != row["source_status_revision"]
                or source["result_sha256"] != receipt["result_sha256"]
                or source["task_version"] != receipt["task_version"]
                or source["user_review_event_id"] is not None
                or source["user_review_revision"] is not None):
            return False
        accepted = _dict_row(conn.execute(
            "SELECT * FROM task_history WHERE id=? AND task_id=?",
            (receipt["acceptance_event_id"], row["task_id"])))
        decision = _dict_row(conn.execute(
            "SELECT * FROM task_history WHERE id=? AND task_id=?",
            (receipt["completion_decision_event_id"], row["task_id"])))
        status = _dict_row(conn.execute(
            "SELECT * FROM task_history WHERE id=? AND task_id=?",
            (row["source_status_revision"], row["task_id"])))
        if (accepted is None or accepted["action"] != "result_acceptance"
                or accepted["changed_by"] != "native-worker-completion-policy"
                or json.loads(accepted["new_value"]) != {
                    "result_id": source["id"], "result_sha256": source["result_sha256"],
                    "task_version": source["task_version"],
                    "status_revision": row["source_status_revision"]}
                or decision is None or decision["action"] != "worker_completion_decision"
                or decision["changed_by"] != "native-worker-completion-policy"
                or decision["old_value"] is not None
                or status is None or status["action"] != "status_change"
                or status["old_value"] != "review" or status["new_value"] != "done"
                or status["changed_by"] != "native-worker-completion-policy"
                or not (receipt["review_event_id"] < decision["id"] < status["id"]
                        < accepted["id"] < row["event_id"])):
            return False
        old = json.loads(decision["new_value"])
        old_body = {key: value for key, value in old.items() if key != "receipt_sha256"}
        if (old.get("receipt_sha256") != receipt["completion_decision_sha256"]
                or _receipt_digest(old_body) != receipt["completion_decision_sha256"]
                or old.get("result_revision") != receipt["result_revision"]
                or old.get("result_id") != source["id"]
                or old.get("result_sha256") != source["result_sha256"]
                or old.get("task_version") != source["task_version"]
                or old.get("decision", {}).get("completion_allowed") is not True
                or old["decision"].get("reason") != "non_blocking_review_findings"):
            return False
        from .worker_result_review import read_review_evidence
        from .worker_execution_evidence import read_execution_evidence
        from .worker_scope_evidence import read_scope_evidence
        # Reconstruct only the immutable source projection. The task may be
        # pending or have a newer result by the time history is read.
        historical = dict(source, result_id=source["id"], reason="accepted")
        historical["submission"] = _submission_readback(conn, source)
        if historical["submission"].get("availability") != "available":
            return False
        historical["submission_revision"] = _submission_revision(
            source, historical["submission"]["receipt_sha256"])
        historical["execution"] = read_execution_evidence(conn, historical)
        historical["scope"] = read_scope_evidence(conn, historical)
        review = read_review_evidence(conn, historical)
        return (review.get("availability") == "recorded"
            and review.get("independent") is True
            and review.get("status") in {"findings", "rejected"}
            and review.get("reviewer_asserted_task_contract_met") is False
            and review.get("event_id") == receipt["review_event_id"]
            and review.get("review_task_id") == receipt["review_task_id"]
            and review.get("child_result_id") == receipt["child_result_id"]
            and review.get("result_revision") == receipt["result_revision"])
    except (sqlite3.Error, ValueError, TypeError, KeyError, AttributeError):
        return False


def _ack(row, *, replayed):
    return {"schema": SCHEMA, "task_id": row["task_id"],
            "correction_id": row["id"], "request_id": row["request_id"],
            "status": "pending", "next_task_version": row["next_task_version"],
            "replayed": replayed}


def _replay(conn, task_id, expected, request_id):
    if not _table_exists(conn, "task_result_corrections"):
        return None
    row = _dict_row(conn.execute(
        "SELECT * FROM task_result_corrections WHERE task_id=? AND request_id=?",
        (task_id, request_id)))
    if row is None:
        return None
    audit_row = dict(row, source_result_id=row["source_result_id"],
        source_result_sha256=row["source_result_sha256"],
        source_task_version=row["source_task_version"],
        source_status_revision=row["source_status_revision"],
        requested_by_device_id=row["requested_by_device_id"],
        policy_decision_sha256=row["policy_decision_sha256"],
        event_changed_by=ACTOR)
    event = _dict_row(conn.execute("SELECT new_value,changed_by FROM task_history WHERE id=?",
                                   (row["event_id"],)))
    if event is None or event["changed_by"] != ACTOR:
        raise ResultConflict("request_id hat einen anderen Ursprung")
    try:
        detail = json.loads(event["new_value"])
    except (TypeError, ValueError):
        raise ResultConflict("Korrekturaudit beschädigt") from None
    receipt = _receipt_from_audit(conn, audit_row)
    if (receipt is None or not repair_correction_matches(conn, audit_row, detail)
            or any(receipt.get(key) != value for key, value in expected.items())):
        raise ResultConflict("request_id wurde bereits anders verwendet oder Audit ist ungültig")
    return _ack(row, replayed=True)


def repair_machine_false_acceptance(conn, task_id, *, expected, request_id,
                                    repo_root=None, worktrees_dir=None):
    """Requeue one proven false machine acceptance through the canonical ledger."""
    _valid_request(task_id, expected, request_id)
    if conn.in_transaction:
        raise ResultConflict("Maschinenkorrektur braucht eine eigene Transaktion")
    replay = _replay(conn, task_id, expected, request_id)
    if replay is not None:
        return replay
    evaluation = evaluate_current_result(conn, task_id, repo_root=repo_root,
                                         worktrees_dir=worktrees_dir)
    observed = read_result(conn, task_id)
    record = observed.get("result")
    review = record.get("model_review", {}) if isinstance(record, dict) else {}
    if (evaluation.get("availability") != "available"
            or evaluation.get("status") != "done"
            or evaluation.get("decision", {}).get("state") != "correction_required"
            or evaluation["decision"].get("completion_allowed") is not False
            or evaluation.get("contract_finding", {}).get("reviewer_asserted_task_contract_met") is not False
            or evaluation.get("user_approved") is not False
            or observed.get("status") != "done"
            or not isinstance(record, dict) or record.get("accepted") is not True
            or record.get("accepted_by") != "native-worker-completion-policy"
            or record.get("user_review_event_id") is not None
            or record.get("user_review_revision") is not None
            or record.get("completion_decision", {}).get("availability") != "available"
            or not isinstance(review, dict) or review.get("availability") != "recorded"
            or review.get("independent") is not True
            or review.get("status") not in {"findings", "rejected"}
            or review.get("reviewer_asserted_task_contract_met") is not False
            or any(record.get(key) != expected[key] for key in (
                "result_id", "result_sha256", "acceptance_event_id",
                "completion_decision_event_id", "completion_decision_sha256"))
            or any(observed.get(key) != expected[key] for key in (
                "task_version", "status_revision"))
            or evaluation.get("result_revision") != expected["result_revision"]
            or evaluation.get("result_sha256") != expected["result_sha256"]
            or review.get("result_revision") != expected["result_revision"]
            or review.get("event_id") != expected["review_event_id"]
            or review.get("review_task_id") != expected["review_task_id"]
            or review.get("child_result_id") != expected["child_result_id"]):
        raise ResultConflict("Keine aktuelle, unabhängig bewiesene maschinelle Falschannahme")
    decision_event = _dict_row(conn.execute(
        "SELECT new_value FROM task_history WHERE id=? AND task_id=?",
        (expected["completion_decision_event_id"], task_id)))
    if decision_event is None:
        raise ResultConflict("Alte Maschinenentscheidung fehlt")
    try:
        old_decision = json.loads(decision_event["new_value"])["decision"]
    except (TypeError, ValueError, KeyError):
        raise ResultConflict("Alte Maschinenentscheidung ungültig") from None
    if (old_decision.get("reason") != "non_blocking_review_findings"
            or old_decision.get("completion_allowed") is not True):
        raise ResultConflict("Kein betroffener historischer Maschinenentscheid")
    checked = evaluate_current_result(conn, task_id, repo_root=repo_root,
                                      worktrees_dir=worktrees_dir)
    if (checked.get("availability") != "available"
            or any(checked.get(key) != evaluation.get(key) for key in (
                "result_id", "result_sha256", "result_revision", "task_version",
                "status_revision", "db_evidence_sha256", "decision", "contract_finding"))):
        raise ResultConflict("Maschinenkorrektur-Beleg seit dem Lesen geändert")
    conn.execute("BEGIN IMMEDIATE")
    try:
        replay = _replay(conn, task_id, expected, request_id)
        if replay is not None:
            conn.commit()
            return replay
        task = _dict_row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
        current = read_result(conn, task_id)
        source = current.get("result")
        if (task is None or task.get("status") != "done"
                or any(task.get(name) not in (None, "") for name in _CLEARED_ON_RELEASE)
                or current.get("status_revision") != expected["status_revision"]
                or current.get("task_version") != expected["task_version"]
                or not isinstance(source, dict) or source.get("accepted") is not True
                or source.get("result_id") != expected["result_id"]
                or source.get("result_sha256") != expected["result_sha256"]
                or source.get("accepted_by") != "native-worker-completion-policy"
                or source.get("acceptance_event_id") != expected["acceptance_event_id"]
                or source.get("completion_decision_event_id") != expected["completion_decision_event_id"]
                or source.get("completion_decision_sha256") != expected["completion_decision_sha256"]
                or source.get("user_review_event_id") is not None
                or source.get("user_review_revision") is not None
                or _current_revision_from_db(conn, source) != expected["result_revision"]
                or _db_fingerprint(source) != evaluation["db_evidence_sha256"]
                or source.get("model_review", {}).get("event_id") != expected["review_event_id"]
                or source.get("model_review", {}).get("review_task_id") != expected["review_task_id"]
                or source.get("model_review", {}).get("child_result_id") != expected["child_result_id"]
                or source.get("model_review", {}).get("reviewer_asserted_task_contract_met") is not False):
            raise ResultConflict("Task, Lease, Ergebnis oder Review seit dem Lesen geändert")
        policy, global_view = _settings_snapshot(conn, task_id)
        frozen = source.get("submission", {}).get("policy", {})
        current_identity = identity_snapshot(conn)
        if (frozen.get("availability") != "available"
                or policy["configuration_version"] != frozen.get("configuration_version")
                or global_view["policy"] != frozen.get("policy")
                or policy["override"] != frozen.get("override")
                or current_identity["configuration_version"] != evaluation["identity_configuration_version"]
                or principal_for_execution(current_identity, source["execution"]) != evaluation["author_id"]):
            raise ResultConflict("Policy oder Modellidentität seit dem Lesen geändert")
        from .chat.worker_write_guard import snapshot_task_scope
        if (snapshot_task_scope(task_id, repo_root=repo_root,
                                worktrees_dir=worktrees_dir)
                != source.get("scope", {}).get("snapshot")):
            raise ResultConflict("Git- oder Sperrstand seit dem Lesen geändert")
        if not _table_exists(conn, "task_result_corrections"):
            raise ResultConflict("Kanonischer Korrekturledger fehlt")
        now = _utcnow()
        stamp = _local_naive(now)
        receipt = {"schema": SCHEMA, "request_id": request_id, "task_id": task_id,
            "result_id": source["result_id"], "result_sha256": source["result_sha256"],
            "result_revision": expected["result_revision"],
            "task_version": expected["task_version"],
            "status_revision": expected["status_revision"],
            "acceptance_event_id": expected["acceptance_event_id"],
            "completion_decision_event_id": expected["completion_decision_event_id"],
            "completion_decision_sha256": expected["completion_decision_sha256"],
            "review_event_id": expected["review_event_id"],
            "review_task_id": expected["review_task_id"],
            "child_result_id": expected["child_result_id"],
            "decision": {"state": "correction_required", "completion_allowed": False,
                         "task_contract_met": False}, "recorded_at": stamp}
        digest = _receipt_digest(receipt)
        repair_event_id = _history(conn, task_id, "machine_false_acceptance_repair",
                                   ACTOR, now, {**receipt, "receipt_sha256": digest})
        correction_round = int(conn.execute(
            "SELECT COALESCE(MAX(correction_round),0)+1 FROM task_result_corrections WHERE task_id=?",
            (task_id,)).fetchone()[0])
        note = ("Technische Maschinenkorrektur: unabhängiger Review belegt "
                "nicht erfüllten Taskvertrag; frühere Annahme bleibt im Audit.")
        cursor = conn.execute("""INSERT INTO task_result_corrections
            (task_id,request_id,correction_round,source_result_id,source_result_sha256,
             source_generation,source_fence,source_task_version,source_status_revision,
             correction_note,requested_by_device_id,requested_at,policy_decision_sha256)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (task_id, request_id, correction_round, source["result_id"],
             source["result_sha256"], source["generation"], source["fence"],
             source["task_version"], expected["status_revision"], note, 0, stamp, digest))
        correction_id = cursor.lastrowid
        apply_task_field_changes(conn, task_id, task, {"status": "pending"},
                                 changed_by=ACTOR, now=stamp, allow_reopen=True)
        pointer = conn.execute("UPDATE tasks SET result_correction_request_id=? WHERE id=? "
            "AND status='pending' AND result_correction_request_id IS ?",
            (correction_id, task_id, task.get("result_correction_request_id")))
        if pointer.rowcount != 1:
            raise ResultConflict("Korrekturzeiger wurde parallel geändert")
        after = _dict_row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
        next_version = task_content_version(after)
        correction_event_id = _history(conn, task_id, "result_correction_request",
            ACTOR, now, {"correction_id": correction_id, "request_id": request_id,
                "correction_round": correction_round, "result_id": source["result_id"],
                "result_sha256": source["result_sha256"], "generation": source["generation"],
                "fence": source["fence"], "task_version": source["task_version"],
                "status_revision": expected["status_revision"], "correction_note": note,
                "next_task_version": next_version, "policy_decision_sha256": digest,
                "repair_event_id": repair_event_id})
        conn.execute("UPDATE task_result_corrections SET event_id=?,next_task_version=? WHERE id=?",
                     (correction_event_id, next_version, correction_id))
        row = _dict_row(conn.execute(
            "SELECT * FROM task_result_corrections WHERE id=?", (correction_id,)))
        audit_row = dict(row, event_changed_by=ACTOR)
        event_detail = json.loads(conn.execute(
            "SELECT new_value FROM task_history WHERE id=?", (correction_event_id,)).fetchone()[0])
        if not repair_correction_matches(conn, audit_row, event_detail):
            raise ResultConflict("Maschinenkorrektur-Audit nicht bestätigt")
        conn.commit()
        return _ack(row, replayed=False)
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
