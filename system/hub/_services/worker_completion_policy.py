"""Result-bound BACH adapter for the shared taskplan completion contract.

Only canonical result, execution, scope, identity, operator and GitHub sources
may supply policy facts. A structured worker self-check can assert completion
for simple tasks; it is neither a machine criterion proof nor personal approval.
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
from .worker_result_provenance import (author_principal, current_result_revision,
                                       source_kind, source_pin)
from .worker_completion_contract import (evaluate_contract, evaluate_worker_self_check,
    evaluate_worker_completion_assertion)
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
    source = ({"source_kind": "external_attested", "external_source": source_pin(record)}
              if source_kind(record) == "external_attested" else {})
    return _digest({"schema": "bach.worker-completion-db-inputs.v1", **source,
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


def _completion_assertion_recorded(conn, record):
    """Only submissions with their own contemporaneous audit marker qualify."""
    before = record.get("submission_event_id")
    if type(before) is not int or before <= 0:
        return False
    event = _row(conn.execute(
        "SELECT id,task_id,action,field_changed,old_value,new_value,changed_by "
        "FROM task_history WHERE task_id=? AND action='worker_completion_asserted' "
        "AND id<? ORDER BY id DESC LIMIT 1", (record["task_id"], before)))
    if (event is None or event["task_id"] != record["task_id"]
            or event["field_changed"] != "lease" or event["old_value"] is not None
            or event["changed_by"] != record.get("submitted_by")):
        return False
    try:
        detail = json.loads(event["new_value"])
    except (TypeError, ValueError):
        return False
    return detail == {"schema": "bach.worker-completion-assertion.v1",
                      "task_id": record["task_id"], "result_id": record["result_id"],
                      "result_sha256": record["result_sha256"],
                      "generation": record["generation"], "fence": record["fence"],
                      "task_version": record["task_version"]}


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
                or source_pin(record) is None):
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
        author_id = author_principal(identity, record)
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
        review = record.get("model_review")
        if not isinstance(review, dict):
            review = {}
        review_is_current = (
            review.get("schema") == "bach.worker-result-review-evidence.v1"
            and review.get("availability") == "available"
            and type(review.get("status")) is str
            and review.get("status") in {"approved", "findings", "rejected"}
            and review.get("independent") is True
            and review.get("policy_eligible") is True
            and type(review.get("task_id")) is int
            and review.get("task_id") == task_id
            and type(review.get("result_id")) is int
            and review.get("result_id") == record["result_id"]
            and type(review.get("result_revision")) is str
            and review.get("result_revision") == revision
            and type(review.get("review_task_id")) is int
            and review.get("review_task_id") > 0
            and type(review.get("reviewer_id")) is str
            and bool(review.get("reviewer_id")))
        review_status = review.get("status") if review_is_current else None
        # A configured independent reviewer can make the semantic finding for
        # an unstructured task. This is a reviewer judgment, never a machine
        # criterion proof or a personal user approval. The canonical reader
        # already binds it to the actual child verdict, identity and revision.
        semantic_review_met = (
            contract.get("reason") == "contract_not_predeclared"
            and review_is_current
            and review_status == "approved"
            and review.get("reviewer_asserted_task_contract_met") is True)
        worker_self_check = evaluate_worker_self_check(record["result"])
        worker_completion_assertion = evaluate_worker_completion_assertion(record["result"])
        simple_self_check_met = (
            policy_view["effective"]["effective_mode"] == "simple_task"
            and contract.get("reason") == "contract_not_predeclared"
            and worker_self_check["met"] is True)
        simple_completion_asserted = (
            policy_view["effective"]["effective_mode"] == "simple_task"
            and contract.get("reason") == "contract_not_predeclared"
            and worker_completion_assertion["met"] is True
            and _completion_assertion_recorded(conn, record))
        adverse_review_contract_finding = (
            review_is_current
            and review_status in {"findings", "rejected"}
            and review.get("reviewer_asserted_task_contract_met") is False)
        task_contract_met = (False if adverse_review_contract_finding else
            contract["met"] is True or (
                contract.get("reason") == "contract_not_predeclared"
                and (contract_attested or semantic_review_met or simple_self_check_met
                     or simple_completion_asserted)))
        contract_finding = {
            "met": task_contract_met,
            "source": "independent_model_review" if adverse_review_contract_finding else
                      "predeclared_criteria" if contract["met"] is True else
                      "operator_attestation" if task_contract_met and contract_attested else
                      "independent_model_review" if semantic_review_met else
                      "worker_self_check" if simple_self_check_met and task_contract_met else
                      "worker_completion_asserted" if simple_completion_asserted and task_contract_met else
                      "unconfirmed",
            "review_task_id": (review.get("review_task_id")
                               if adverse_review_contract_finding or semantic_review_met else None),
        }
        if adverse_review_contract_finding:
            contract_finding.update({
                "review_status": review_status,
                "reviewer_asserted_task_contract_met": False,
            })
        status_map = {"approved": kernel.ReviewStatus.APPROVED,
                      "findings": kernel.ReviewStatus.FINDINGS,
                      "rejected": kernel.ReviewStatus.REJECTED}
        review_record = kernel.ReviewRecord(
            status=status_map.get(review_status, kernel.ReviewStatus.PENDING),
            reviewer_id=review.get("reviewer_id") if review_status else None,
            task_id=str(task_id) if review_status else None,
            result_revision=revision if review_status else None,
            independent=review_is_current)
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
            locks_clear=True, task_contract_met=task_contract_met,
            result_evidence_valid=True, user_review_required=bool(user_required),
            github_pr_review_required=github_required, result_age_seconds=_age_seconds(record.get("submitted_at")),
            review=review_record, user_review=user_record, external_review=external_record)
        decision = kernel.evaluate_worker_policy(policy, context, override).as_dict()
        # Internal review can affect whether this result is accepted, but it
        # never holds the worker's next queue claim. External-effect gates
        # remain represented by completion_allowed and the result status.
        decision["worker_may_claim_next"] = True
        return {"schema": SCHEMA, "availability": "available", "task_id": task_id,
            "result_id": record["result_id"], "result_revision": revision,
            "status": observed["status"],
            "author_id": author_id, "identity_configuration_version": identity["configuration_version"],
            "db_evidence_sha256": _db_fingerprint(record),
            "result_sha256": record["result_sha256"], "task_version": observed["task_version"],
            "status_revision": observed["status_revision"], "reason": decision["reason"],
            "decision": decision, "contract": contract, "contract_attested": contract_attested,
            "worker_self_check": worker_self_check,
            "worker_completion_assertion": worker_completion_assertion,
            "contract_finding": contract_finding,
            "user_review_required": bool(user_required), "user_approved": user_approved,
            "github_pr_review_required": github_required, "github": github}
    except (sqlite3.Error, KeyError, TypeError, ValueError, AttributeError,
            settings.PolicyUnavailable) as exc:
        return _unavailable(task_id, "completion_source_unavailable")


def _current_revision_from_db(record):
    """Rebuild only the immutable revision inputs inside an SQLite writer."""
    return current_result_revision(record)


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
            or author_principal(current_identity, record) != evaluation["author_id"]):
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
    revision_label = (f"Ergebnisrevision {result_revision}" if result_revision is not None
                      else f"Abgaberevision {record['submission_revision']}")
    note = (f"Policy-Korrektur ({reason}) für {revision_label}. "
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


def _definitely_missing_task_tree(task_id, *, repo_root=None, worktrees_dir=None):
    """Prove absence of both the canonical path and its Git registration."""
    from .chat.worker_write_guard import _fresh_locks, _paths, _run_readonly
    from pathlib import Path
    try:
        repo, root = _paths(repo_root, worktrees_dir)
        if not root.is_dir() or root.resolve(strict=True) != root:
            return False
        target = root / f"task-{task_id}"
        try:
            target.lstat()  # Includes dangling links, which must never count as absent.
        except FileNotFoundError:
            pass
        else:
            return False
        # The normal scope writer also requires a clean canonical lock scan.
        # Unknown or occupied scopes must not be converted into corrections.
        _fresh_locks(repo, root, target)
        raw = _run_readonly(["git", "worktree", "list", "--porcelain"], repo)
        registrations = [block for block in raw.split("\n\n") if block.startswith("worktree ")]
        if not registrations:
            return False
        for block in registrations:
            lines = block.splitlines()
            path = Path(lines[0][9:])
            if (path.resolve(strict=False) == target
                    or f"branch refs/heads/bach-task/{task_id}" in lines):
                return False
        return True
    except Exception:
        return False


def _missing_scope_candidate(conn, task_id, *, repo_root=None, worktrees_dir=None):
    """Read only: an actual V1 release whose task tree cannot still be captured."""
    from .worker_completion_contract import parse_contract
    from .worker_result_review import review_task_marker
    from .task_lease import task_content_version
    try:
        observed = read_result(conn, task_id)
        record = observed.get("result")
        if (not isinstance(record, dict) or record.get("completion_policy_version") != 1
                or review_task_marker(conn, task_id)
                or observed.get("status") != "review"
                or record.get("reason") != "awaiting_review"
                or record.get("submission", {}).get("availability") != "available"
                or record.get("scope", {}).get("availability") != "unavailable"
                or record.get("scope", {}).get("reason") != "scope_not_recorded"):
            return None
        submission_revision = record.get("submission_revision")
        execution = record.get("execution") or {}
        if (type(submission_revision) is not str
                or re.fullmatch(r"sha256:[a-f0-9]{64}", submission_revision) is None
                or execution.get("availability") != "available"
                or type(execution.get("execution_revision")) is not str
                or not _HEX.fullmatch(execution["execution_revision"])):
            return None
        task = _row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
        if (task is None or task.get("status") != "review" or task.get("claim_id")
                or task_content_version(task) != observed.get("task_version")):
            return None
        # A lost scope row with a persisted capture event is corrupted evidence,
        # not proof that the task worktree was never captured.
        if conn.execute("SELECT 1 FROM task_history WHERE task_id=? "
                "AND action='worker_result_scope_capture' AND id>? LIMIT 1",
                (task_id, record["submission_event_id"])).fetchone() is not None:
            return None
        contract = parse_contract(task.get("completion_contract_json"))
        if not contract or not any(item["kind"] == "git_blob_sha256" for item in contract["criteria"]):
            return None
        policy_view, global_view = _settings_snapshot(conn, task_id)
        frozen = record["submission"].get("policy", {})
        if (frozen.get("availability") != "available"
                or frozen.get("configuration_version") != policy_view["configuration_version"]
                or frozen.get("policy") != global_view["policy"]
                or frozen.get("override") != policy_view["override"]
                or frozen.get("user_review_required") != policy_view["effective"]["user_review_required"]):
            return None
        identity = identity_snapshot(conn)
        author_id = principal_for_execution(identity, execution)
        if author_id is None:
            return None
        if not _definitely_missing_task_tree(task_id, repo_root=repo_root,
                                              worktrees_dir=worktrees_dir):
            return None
        return {"task": task, "record": record, "observed": observed,
                "author_id": author_id,
                "identity_configuration_version": identity["configuration_version"],
                "db_evidence_sha256": _db_fingerprint(record)}
    except (sqlite3.Error, KeyError, TypeError, ValueError, AttributeError,
            settings.PolicyUnavailable):
        return None


def _reconcile_missing_scope(conn, task_id, *, repo_root=None, worktrees_dir=None):
    """Reopen only a submitted task with proven, permanent missing scope."""
    from .task_result_service import ResultConflict
    from .task_lease import _history, _utcnow
    before = _missing_scope_candidate(conn, task_id, repo_root=repo_root,
                                      worktrees_dir=worktrees_dir)
    if before is None:
        return None
    conn.execute("BEGIN IMMEDIATE")
    try:
        current = _missing_scope_candidate(conn, task_id, repo_root=repo_root,
                                           worktrees_dir=worktrees_dir)
        if (current is None or current["db_evidence_sha256"] != before["db_evidence_sha256"]
                or current["observed"]["task_version"] != before["observed"]["task_version"]
                or current["observed"]["status_revision"] != before["observed"]["status_revision"]
                or current["author_id"] != before["author_id"]
                or current["identity_configuration_version"] != before["identity_configuration_version"]):
            raise ResultConflict("Fehlender Task-Arbeitsbaum nicht mehr stabil bestätigt")
        record, observed, task = current["record"], current["observed"], current["task"]
        detail = {"schema": SCHEMA, "task_id": task_id,
            "result_id": record["result_id"], "result_sha256": record["result_sha256"],
            "result_revision": None, "task_version": observed["task_version"],
            "status_revision": observed["status_revision"],
            "generation": record["generation"], "fence": record["fence"],
            "submission_revision": record["submission_revision"],
            "evidence_guard": {"schema": "bach.worker-missing-scope-guard.v1",
                "reason": "scope_not_recorded", "task_tree": "definitively_absent",
                "execution_revision": record["execution"]["execution_revision"],
                "author_id": current["author_id"]},
            "decision": {"state": "correction_required", "reason": "scope_evidence_missing",
                         "completion_allowed": False, "worker_may_claim_next": True}}
        decision_sha = _digest(detail)
        now = _utcnow()
        event = _history(conn, task_id, "worker_completion_decision",
            "native-worker-completion-policy", now,
            {"receipt_sha256": decision_sha, **detail})
        _policy_correction(conn, task, record, observed, now, event, decision_sha,
                           None, "scope_evidence_missing")
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    return {"schema": SCHEMA, "availability": "available", "task_id": task_id,
            "result_id": record["result_id"], "result_revision": None,
            "decision": detail["decision"], "reason": "scope_evidence_missing",
            "status": "pending"}


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
        if expected is None and evaluation.get("reason") == "full_result_revision_unavailable":
            correction = _reconcile_missing_scope(conn, task_id, repo_root=repo_root,
                                                   worktrees_dir=worktrees_dir)
            if correction is not None:
                return correction
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
        if (evaluation["contract_finding"]["source"] == "worker_completion_asserted"
                and not _completion_assertion_recorded(conn, record)):
            raise ResultConflict("Fertigmeldung seit der Prüfung verändert")
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
