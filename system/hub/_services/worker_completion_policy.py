"""Result-bound BACH adapter for the shared taskplan completion contract.

Only canonical result, execution, scope, identity, operator and GitHub sources
may supply policy facts. This module never treats a worker verdict as a task
contract check or as personal approval.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
import uuid

from . import worker_policy_settings as settings
from .task_result_service import read_result
from .worker_scope_evidence import project_scope_evidence
from .worker_completion_contract import evaluate_contract
from .worker_github_review import observe_github_review
from .worker_review_identity import identity_snapshot, principal_for_execution

SCHEMA = "bach.worker-completion-evaluation.v1"
_HEX = re.compile(r"[a-f0-9]{64}\Z")


def _row(cursor):
    value = cursor.fetchone()
    return dict(zip((field[0] for field in cursor.description), value)) if value is not None else None


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _db_fingerprint(record):
    execution, scope, review = (record.get("execution") or {},
                                record.get("scope") or {}, record.get("model_review") or {})
    return _digest({"schema": "bach.worker-completion-db-inputs.v1",
        **{key: record.get(key) for key in ("task_id", "result_id", "fence", "generation",
            "task_version", "result_sha256", "submission_revision", "submission_event_id",
            "completion_policy_version", "user_review_revision", "user_review_event_id",
            "contract_attestation_revision", "contract_attestation_event_id")},
        "submission_policy": (record.get("submission") or {}).get("policy"),
        "execution": {key: execution.get(key) for key in ("execution_id", "execution_revision",
            "response_sha256", "model_principal_id", "identity_binding_sha256")},
        "scope": {key: scope.get(key) for key in ("scope_event_id", "scope_receipt_sha256")},
        "review": {key: review.get(key) for key in ("event_id", "status", "reviewer_id",
            "result_revision", "independent")}})


def _unavailable(task_id, reason, *, record=None):
    return {"schema": SCHEMA, "availability": "unavailable", "task_id": task_id,
            "result_id": record.get("result_id") if isinstance(record, dict) else None,
            "result_revision": None, "decision": None, "reason": reason,
            "contract": {"availability": "unavailable", "met": False},
            "github": {"availability": "unavailable", "status": "pending"}}


def _settings_snapshot(conn, task_id):
    old_factory = conn.row_factory
    try:
        conn.row_factory = sqlite3.Row
        return settings._task_snapshot(conn, task_id), settings._global(conn)
    finally:
        conn.row_factory = old_factory


def _history_matches(conn, record, *, revision_field, event_field, action, status):
    revision, event_id = record.get(revision_field), record.get(event_field)
    if (type(revision) is not str or not _HEX.fullmatch(revision)
            or type(event_id) is not int or event_id <= record.get("submission_event_id", 0)):
        return False
    event = _row(conn.execute("SELECT task_id,action,field_changed,old_value,new_value,changed_by "
                              "FROM task_history WHERE id=?", (event_id,)))
    if (not event or event["task_id"] != record["task_id"] or event["action"] != action
            or event["field_changed"] != "lease" or event["old_value"] is not None
            or not isinstance(event["changed_by"], str)
            or not event["changed_by"].startswith("operator-device:")):
        return False
    try:
        detail = json.loads(event["new_value"])
    except (TypeError, ValueError):
        return False
    return detail == {"schema": "bach.worker-operator-review.v1", "status": status,
                      "task_id": record["task_id"], "result_id": record["result_id"],
                      "result_sha256": record["result_sha256"], "result_revision": revision,
                      "device_id": int(event["changed_by"].split(":", 1)[1])}


def _age_seconds(value):
    try:
        from .task_lease import parse_ts
        submitted = parse_ts(value)
        if submitted is None:
            return None
        return max(0, int((datetime.now(timezone.utc) - submitted).total_seconds()))
    except (TypeError, ValueError, OverflowError):
        return None


def evaluate_current_result(conn, task_id: int, *, repo_root=None, worktrees_dir=None,
                            github_observer=None) -> dict:
    """Read-only evaluation. Git and GitHub are never called under a DB writer."""
    if type(task_id) is not int or task_id <= 0:
        return _unavailable(task_id, "task_id_invalid")
    if conn.in_transaction:
        return _unavailable(task_id, "active_database_transaction")
    try:
        observed = read_result(conn, task_id)
        record = observed.get("result")
        if not isinstance(record, dict) or type(record.get("result_id")) is not int:
            return _unavailable(task_id, "worker_result_missing")
        if record.get("completion_policy_version") != 1:
            return _unavailable(task_id, "legacy_result", record=record)
        from .worker_result_review import review_task_marker
        if review_task_marker(conn, task_id):
            return _unavailable(task_id, "administrative_review_child", record=record)
        if observed.get("status") not in {"review", "done", "completed"}:
            return _unavailable(task_id, "task_not_in_review", record=record)
        if (record.get("reason") not in {"awaiting_review", "accepted"}
                or (observed["status"] == "review" and record["reason"] != "awaiting_review")
                or (observed["status"] in {"done", "completed"} and record["reason"] != "accepted")):
            return _unavailable(task_id, "result_not_current", record=record)
        if record.get("submission", {}).get("availability") != "available":
            return _unavailable(task_id, "submission_unavailable", record=record)
        projected = project_scope_evidence(observed, repo_root=repo_root,
                                           worktrees_dir=worktrees_dir)
        record = projected["result"]
        revision = record.get("result_revision")
        if (type(revision) is not str or not _HEX.fullmatch(revision)
                or record.get("scope", {}).get("availability") != "available"
                or record.get("execution", {}).get("availability") != "available"):
            return _unavailable(task_id, "full_result_revision_unavailable", record=record)
        task = _row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
        if task is None or task.get("claim_id"):
            return _unavailable(task_id, "task_claim_or_row_changed", record=record)
        policy_view, global_view = _settings_snapshot(conn, task_id)
        frozen = record["submission"].get("policy", {})
        if (frozen.get("availability") != "available"
                or frozen.get("configuration_version") != policy_view["configuration_version"]
                or frozen.get("policy") != global_view["policy"]
                or frozen.get("override") != policy_view["override"]
                or frozen.get("user_review_required") != policy_view["effective"]["user_review_required"]):
            return _unavailable(task_id, "policy_configuration_changed", record=record)
        kernel = settings._kernel()
        policy = settings.validate_policy(frozen["policy"])
        override = settings.validate_override(frozen["override"])
        identity = identity_snapshot(conn)
        author_id = principal_for_execution(identity, record["execution"])
        if author_id is None:
            return _unavailable(task_id, "author_identity_unavailable", record=record)
        if type(task.get("require_user_review")) not in {type(None), int} or task.get("require_user_review") not in {None, 0, 1}:
            return _unavailable(task_id, "user_gate_invalid", record=record)
        if type(task.get("github_pr_review_required")) not in {type(None), int} or task.get("github_pr_review_required") not in {None, 0, 1}:
            return _unavailable(task_id, "github_gate_invalid", record=record)
        # This column is fixed before submission by task_content_version.
        contract = evaluate_contract(task.get("completion_contract_json"), result=record["result"],
                                     snapshot=record["scope"]["snapshot"],
                                     repo_root=repo_root, worktrees_dir=worktrees_dir)
        from .chat.worker_write_guard import snapshot_task_scope
        if snapshot_task_scope(task_id, repo_root=repo_root,
                               worktrees_dir=worktrees_dir) != record["scope"]["snapshot"]:
            return _unavailable(task_id, "current_git_changed", record=record)
        contract_attested = (_history_matches(conn, record,
            revision_field="contract_attestation_revision", event_field="contract_attestation_event_id",
            action="worker_contract_attestation", status="approved")
            and record.get("contract_attestation_revision") == revision)
        user_approved = (_history_matches(conn, record,
            revision_field="user_review_revision", event_field="user_review_event_id",
            action="worker_user_review", status="approved")
            and record.get("user_review_revision") == revision)
        user_required = policy_view["effective"]["user_review_required"] or task.get("require_user_review") == 1
        github_required = task.get("github_pr_review_required") == 1
        github = {"availability": "not_required", "status": "not_applicable"}
        if github_required:
            try:
                github_contract = json.loads(task.get("github_review_contract_json") or "")
            except (TypeError, ValueError):
                github_contract = None
            github = observe_github_review(github_contract,
                head_oid=record["scope"]["snapshot"].get("head_oid"), task_id=str(task_id),
                result_revision=revision, observer=github_observer)
        review = record.get("model_review", {})
        review_status = (review.get("status") if review.get("availability") == "available" else None)
        status_map = {"approved": kernel.ReviewStatus.APPROVED,
                      "findings": kernel.ReviewStatus.FINDINGS,
                      "rejected": kernel.ReviewStatus.REJECTED}
        review_record = kernel.ReviewRecord(
            status=status_map.get(review_status, kernel.ReviewStatus.PENDING),
            reviewer_id=review.get("reviewer_id") if review_status else None,
            task_id=str(task_id) if review_status else None,
            result_revision=revision if review_status else None,
            independent=review_status is not None and review.get("independent") is True)
        user_record = kernel.UserReviewRecord(
            status=kernel.UserReviewStatus.APPROVED if user_approved else kernel.UserReviewStatus.PENDING,
            task_id=str(task_id) if user_approved else None,
            result_revision=revision if user_approved else None)
        external_record = kernel.ExternalReviewRecord(
            status=kernel.ExternalReviewStatus.VERIFIED if github.get("status") == "verified"
                   else kernel.ExternalReviewStatus.REJECTED if github.get("status") == "rejected"
                   else kernel.ExternalReviewStatus.PENDING if github_required
                   else kernel.ExternalReviewStatus.NOT_APPLICABLE,
            task_id=str(task_id) if github.get("status") in {"verified", "rejected"} else None,
            result_revision=revision if github.get("status") in {"verified", "rejected"} else None)
        context = kernel.WorkerReviewContext(task_id=str(task_id), author_id=author_id,
            result_revision=revision, lease_valid=True, fence_valid=True,
            locks_clear=True, task_contract_met=contract["met"] is True or (
                contract.get("reason") == "contract_not_predeclared" and contract_attested),
            result_evidence_valid=True, user_review_required=bool(user_required),
            github_pr_review_required=github_required, result_age_seconds=_age_seconds(record.get("submitted_at")),
            review=review_record, user_review=user_record, external_review=external_record)
        decision = kernel.evaluate_worker_policy(policy, context, override).as_dict()
        return {"schema": SCHEMA, "availability": "available", "task_id": task_id,
            "result_id": record["result_id"], "result_revision": revision,
            "status": observed["status"],
            "author_id": author_id, "identity_configuration_version": identity["configuration_version"],
            "db_evidence_sha256": _db_fingerprint(record),
            "result_sha256": record["result_sha256"], "task_version": observed["task_version"],
            "status_revision": observed["status_revision"], "reason": decision["reason"],
            "decision": decision, "contract": contract, "contract_attested": contract_attested,
            "user_review_required": bool(user_required), "user_approved": user_approved,
            "github_pr_review_required": github_required, "github": github}
    except (sqlite3.Error, KeyError, TypeError, ValueError, AttributeError,
            settings.PolicyUnavailable) as exc:
        return _unavailable(task_id, "completion_source_unavailable")


def _current_revision_from_db(record):
    """Rebuild only the immutable revision inputs inside an SQLite writer."""
    from .worker_scope_evidence import _REVISION_SCHEMA
    scope, execution = record.get("scope", {}), record.get("execution", {})
    if (scope.get("availability") != "recorded"
            or execution.get("availability") != "available"):
        return None
    revision = execution.get("execution_revision")
    receipt = scope.get("scope_receipt_sha256")
    event_id = scope.get("scope_event_id")
    if (type(revision) is not str or not _HEX.fullmatch(revision)
            or type(receipt) is not str or not _HEX.fullmatch(receipt)
            or type(event_id) is not int or event_id <= 0):
        return None
    return _digest({"schema": _REVISION_SCHEMA,
        "submission_revision": record.get("submission_revision"),
        "execution_revision": revision,
        "scope_receipt_sha256": receipt, "scope_event_id": event_id})


def _same_db_result(conn, evaluation):
    observed = read_result(conn, evaluation["task_id"])
    record = observed.get("result")
    if (not isinstance(record, dict) or observed.get("status") != "review"
            or record.get("result_id") != evaluation["result_id"]
            or record.get("result_sha256") != evaluation["result_sha256"]
            or observed.get("task_version") != evaluation["task_version"]
            or observed.get("status_revision") != evaluation["status_revision"]
            or record.get("reason") != "awaiting_review"
            or record.get("completion_policy_version") != 1
            or _current_revision_from_db(record) != evaluation["result_revision"]
            or _db_fingerprint(record) != evaluation["db_evidence_sha256"]):
        return None, None, None
    task = _row(conn.execute("SELECT * FROM tasks WHERE id=?", (evaluation["task_id"],)))
    if task is None or task.get("claim_id") or task.get("status") != "review":
        return None, None, None
    view, global_view = _settings_snapshot(conn, evaluation["task_id"])
    frozen = record.get("submission", {}).get("policy", {})
    if (frozen.get("availability") != "available"
            or view["configuration_version"] != frozen.get("configuration_version")
            or global_view["policy"] != frozen.get("policy")
            or view["override"] != frozen.get("override")
            or (current_identity := identity_snapshot(conn))["configuration_version"]
                != evaluation["identity_configuration_version"]
            or principal_for_execution(current_identity, record["execution"]) != evaluation["author_id"]):
        return None, None, None
    return task, record, observed


def _operator_device(conn, token):
    if (not isinstance(token, str) or not token.strip() or len(token) > 256
            or conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_result_operators'").fetchone() is None):
        return None
    from gui.device_auth import _hash_token
    row = conn.execute("SELECT d.id FROM devices d JOIN task_result_operators o ON o.device_id=d.id "
                       "WHERE d.token_hash=? AND d.status='active'", (_hash_token(token),)).fetchone()
    return row[0] if row is not None and type(row[0]) is int and row[0] > 0 else None


def reconcile_operator_result(conn, task_id, *, result_id, result_sha256,
                              result_revision, task_version, status_revision,
                              operator_token, repo_root=None, worktrees_dir=None,
                              github_observer=None):
    """Explicit operator-triggered recheck for a late external approval."""
    from .task_result_service import ResultConflict, ResultPermissionDenied
    if _operator_device(conn, operator_token) is None:
        raise ResultPermissionDenied("Persönliche Ergebnisberechtigung fehlt oder wurde widerrufen")
    observed = evaluate_current_result(conn, task_id, repo_root=repo_root,
        worktrees_dir=worktrees_dir, github_observer=github_observer)
    if (observed["availability"] != "available"
            or type(result_id) is not int or observed["result_id"] != result_id
            or type(result_sha256) is not str or observed["result_sha256"] != result_sha256
            or type(result_revision) is not str or observed["result_revision"] != result_revision
            or type(task_version) is not str or observed["task_version"] != task_version
            or type(status_revision) is not int or observed["status_revision"] != status_revision):
        raise ResultConflict("Ergebnis oder Git-Stand seit dem Lesen verändert; neu laden")
    return reconcile_current_result(conn, task_id, repo_root=repo_root,
        worktrees_dir=worktrees_dir, github_observer=github_observer,
        operator_token=operator_token, expected={
            key: observed[key] for key in ("result_id", "result_sha256", "result_revision",
                                      "task_version", "status_revision")})


def record_operator_review(conn, task_id, result_id, *, digest, task_version,
                           status_revision, result_revision, task_contract_met,
                           operator_token, repo_root=None, worktrees_dir=None,
                           github_observer=None):
    """Store personal approval and optional fachliche Feststellung, not Done."""
    from .task_result_service import ResultConflict, ResultPermissionDenied
    from .task_lease import _history, _utcnow
    if (type(result_id) is not int or result_id <= 0
            or type(status_revision) is not int or status_revision < 0
            or type(digest) is not str or not _HEX.fullmatch(digest)
            or type(task_version) is not str or not _HEX.fullmatch(task_version)
            or type(result_revision) is not str or not _HEX.fullmatch(result_revision)
            or task_contract_met not in (None, True) or type(task_contract_met) is int):
        raise ResultConflict("Ungültige revisionsgebundene Ergebnisfeststellung")
    if conn.in_transaction:
        raise ResultConflict("Ergebnisfeststellung braucht eine eigene Transaktion")
    # Reject a missing or revoked personal capability before expensive Git or
    # GitHub observations. The writer checks the same authority again.
    if _operator_device(conn, operator_token) is None:
        raise ResultPermissionDenied("Persönliche Ergebnisfreigabe fehlt oder wurde widerrufen")
    evaluation = evaluate_current_result(conn, task_id, repo_root=repo_root,
        worktrees_dir=worktrees_dir, github_observer=github_observer)
    if (evaluation["availability"] != "available"
            or evaluation["result_id"] != result_id
            or evaluation["result_revision"] != result_revision
            or evaluation["result_sha256"] != digest
            or evaluation["task_version"] != task_version
            or evaluation["status_revision"] != status_revision):
        raise ResultConflict("Ergebnis oder Git-Stand seit dem Lesen verändert; neu laden")
    if (task_contract_met is True and evaluation["contract"].get("reason")
            not in {"contract_not_predeclared", "predeclared_criteria_met"}):
        raise ResultConflict("Vorgegebenes maschinelles Kriterium ist nicht bestätigt")
    conn.execute("BEGIN IMMEDIATE")
    try:
        device_id = _operator_device(conn, operator_token)
        if device_id is None:
            raise ResultPermissionDenied("Persönliche Ergebnisfreigabe fehlt oder wurde widerrufen")
        task, record, _ = _same_db_result(conn, evaluation)
        if task is None:
            raise ResultConflict("Ergebnis oder Konfiguration seit dem Lesen verändert; neu laden")
        actor = f"operator-device:{device_id}"
        now = _utcnow()
        for action, revision_col, event_col, needed in (
                ("worker_user_review", "user_review_revision", "user_review_event_id", True),
                ("worker_contract_attestation", "contract_attestation_revision",
                 "contract_attestation_event_id", task_contract_met is True)):
            if not needed:
                continue
            if record.get(revision_col) is not None or record.get(event_col) is not None:
                if (record.get(revision_col) != result_revision
                        or not _history_matches(conn, record, revision_field=revision_col,
                            event_field=event_col, action=action, status="approved")):
                    raise ResultConflict("Vorhandene Feststellung ist nicht kanonisch")
                continue
            detail = {"schema": "bach.worker-operator-review.v1", "status": "approved",
                "task_id": task_id, "result_id": result_id,
                "result_sha256": digest, "result_revision": result_revision,
                "device_id": device_id}
            event_id = _history(conn, task_id, action, actor, now, detail)
            cursor = conn.execute(f"UPDATE worker_task_results SET {revision_col}=?,{event_col}=? "
                f"WHERE id=? AND {revision_col} IS NULL AND {event_col} IS NULL",
                (result_revision, event_id, result_id))
            if cursor.rowcount != 1:
                raise ResultConflict("Feststellung wurde parallel geändert")
            record[revision_col], record[event_col] = result_revision, event_id
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    return reconcile_current_result(conn, task_id, repo_root=repo_root,
        worktrees_dir=worktrees_dir, github_observer=github_observer)


def _policy_correction(conn, task, record, observed, now, decision_event,
                       decision_sha, result_revision, reason):
    """Use the existing correction ledger/pointer for an adverse policy verdict."""
    from .task_result_service import ensure_result_correction_schema, ResultConflict
    from .task_lease import _history, _local_naive, task_content_version
    from hub.task_audit import apply_task_field_changes
    ensure_result_correction_schema(conn)
    task_id = record["task_id"]
    actor = "native-worker-completion-policy"
    summary = record.get("model_review", {}).get("summary")
    summary = summary.strip()[:800] if isinstance(summary, str) else ""
    note = (f"Policy-Korrektur ({reason}) für Ergebnisrevision {result_revision}. "
            + summary).strip()[:1200]
    correction_round = int(conn.execute(
        "SELECT COALESCE(MAX(correction_round),0)+1 FROM task_result_corrections WHERE task_id=?",
        (task_id,)).fetchone()[0])
    request_id = str(uuid.uuid4())
    cursor = conn.execute("""INSERT INTO task_result_corrections
        (task_id,request_id,correction_round,source_result_id,source_result_sha256,
         source_generation,source_fence,source_task_version,source_status_revision,
         correction_note,requested_by_device_id,requested_at,policy_decision_sha256)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (task_id, request_id, correction_round, record["result_id"],
         record["result_sha256"], record["generation"], record["fence"],
         record["task_version"], observed["status_revision"], note, 0,
         _local_naive(now), decision_sha))
    correction_id = cursor.lastrowid
    apply_task_field_changes(conn, task_id, task, {"status": "pending"},
                             changed_by=actor, now=_local_naive(now), allow_reopen=True)
    pointer = conn.execute("UPDATE tasks SET result_correction_request_id=? WHERE id=? "
        "AND status='pending' AND (claim_id IS NULL OR claim_id='') "
        "AND result_correction_request_id IS ?",
        (correction_id, task_id, task.get("result_correction_request_id")))
    if pointer.rowcount != 1:
        raise ResultConflict("Taskkorrektur wurde parallel geändert")
    updated = _row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
    next_version = task_content_version(updated)
    event = _history(conn, task_id, "result_correction_request", actor, now,
        {"correction_id": correction_id, "request_id": request_id,
         "correction_round": correction_round, "result_id": record["result_id"],
         "result_sha256": record["result_sha256"], "generation": record["generation"],
         "fence": record["fence"], "task_version": record["task_version"],
         "status_revision": observed["status_revision"], "correction_note": note,
         "next_task_version": next_version, "policy_decision_sha256": decision_sha})
    conn.execute("UPDATE task_result_corrections SET event_id=?,next_task_version=? WHERE id=?",
                 (event, next_version, correction_id))
    conn.execute("UPDATE worker_task_results SET completion_decision_event_id=?,"
                 "completion_decision_sha256=? WHERE id=?",
                 (decision_event, decision_sha, record["result_id"]))


def reconcile_current_result(conn, task_id, *, repo_root=None, worktrees_dir=None,
                             github_observer=None, operator_token=None,
                             expected=None) -> dict:
    """Re-evaluate a current result, then CAS one policy status transition."""
    from .task_result_service import ResultConflict, _PolicyAcceptance, _status_revision
    from .task_lease import _history, _utcnow, _local_naive, task_content_version
    from hub.task_audit import apply_task_field_changes
    if conn.in_transaction:
        return _unavailable(task_id, "active_database_transaction")
    evaluation = evaluate_current_result(conn, task_id, repo_root=repo_root,
        worktrees_dir=worktrees_dir, github_observer=github_observer)
    if expected is not None and (evaluation.get("availability") != "available"
            or any(evaluation.get(key) != expected.get(key) for key in (
                "result_id", "result_sha256", "result_revision", "task_version",
                "status_revision"))):
        raise ResultConflict("Ergebnis seit der Operatoransicht verändert; neu laden")
    if evaluation["availability"] != "available":
        return evaluation
    decision = evaluation["decision"]
    if decision["state"] not in {"completed", "completed_unreviewed", "correction_required"}:
        return evaluation
    if evaluation.get("status") in {"done", "completed"}:
        return evaluation
    # A second Git observation brackets slow contract/GitHub reads.
    checked = evaluate_current_result(conn, task_id, repo_root=repo_root,
        worktrees_dir=worktrees_dir, github_observer=github_observer)
    if (checked["availability"] != "available" or checked["result_revision"] != evaluation["result_revision"]
            or checked["decision"] != decision or checked["task_version"] != evaluation["task_version"]
            or checked["status_revision"] != evaluation["status_revision"]):
        return _unavailable(task_id, "completion_observation_changed")
    conn.execute("BEGIN IMMEDIATE")
    try:
        if operator_token is not None and _operator_device(conn, operator_token) is None:
            from .task_result_service import ResultPermissionDenied
            raise ResultPermissionDenied("Persönliche Ergebnisberechtigung wurde widerrufen")
        task, record, observed = _same_db_result(conn, evaluation)
        if task is None:
            raise ResultConflict("Ergebnis, Task oder Konfiguration für Abschluss verändert")
        if expected is not None and (record["result_id"] != expected["result_id"]
                or record["result_sha256"] != expected["result_sha256"]
                or observed["task_version"] != expected["task_version"]
                or observed["status_revision"] != expected["status_revision"]
                or _current_revision_from_db(record) != expected["result_revision"]):
            raise ResultConflict("Ergebnis seit der Operatoransicht verändert; neu laden")
        now = _utcnow()
        actor = "native-worker-completion-policy"
        detail = {"schema": SCHEMA, "task_id": task_id,
            "result_id": record["result_id"], "result_sha256": record["result_sha256"],
            "result_revision": evaluation["result_revision"],
            "task_version": evaluation["task_version"],
            "status_revision": evaluation["status_revision"], "decision": decision}
        decision_sha = _digest(detail)
        decision_event = _history(conn, task_id, "worker_completion_decision", actor, now,
            {"receipt_sha256": decision_sha, **detail})
        if decision["completion_allowed"] is True:
            capability = _PolicyAcceptance(conn, record,
                result_revision=evaluation["result_revision"], decision_sha256=decision_sha,
                decision_event_id=decision_event)
            apply_task_field_changes(conn, task_id, task, {"status": "done"},
                changed_by=actor, now=_local_naive(now), result_acceptance=capability)
            revision = _status_revision(conn, task_id)
            acceptance_event = _history(conn, task_id, "result_acceptance", actor, now,
                {"result_id": record["result_id"], "result_sha256": record["result_sha256"],
                 "task_version": record["task_version"], "status_revision": revision})
            conn.execute("UPDATE worker_task_results SET accepted_by=?,accepted_at=?,"
                "accepted_status_event_id=?,acceptance_event_id=?,completion_decision_event_id=?,"
                "completion_decision_sha256=? WHERE id=?",
                (actor, _local_naive(now), revision, acceptance_event,
                 decision_event, decision_sha, record["result_id"]))
        else:
            _policy_correction(conn, task, record, observed, now, decision_event, decision_sha,
                               evaluation["result_revision"], decision["reason"])
        # The final bounded, local Git/lock read deliberately runs inside the
        # short SQLite writer window. It closes the ordinary gap between the
        # outside evaluation and committing Done/correction; it is not an
        # atomic transaction with arbitrary external Git writers.
        from .chat.worker_write_guard import snapshot_task_scope
        current_scope = snapshot_task_scope(task_id, repo_root=repo_root,
                                            worktrees_dir=worktrees_dir)
        if (current_scope.get("availability") != "available"
                or current_scope != record.get("scope", {}).get("snapshot")):
            raise ResultConflict("Git-/Sperrstand vor Abschlusscommit verändert")
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    return evaluate_current_result(conn, task_id, repo_root=repo_root,
        worktrees_dir=worktrees_dir, github_observer=github_observer)
