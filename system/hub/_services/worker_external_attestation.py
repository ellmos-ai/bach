# SPDX-License-Identifier: MIT
"""Explicit external provenance, separate from native model-call evidence.

An enrolled operator checks private source artifacts and the exact result
bytes. BACH observes the current registered task tree itself. This ledger
creates neither a historical native execution nor a completion decision.
Git/lock observations always happen outside SQLite transactions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import sqlite3

from . import worker_external_evidence as evidence
from .chat.worker_write_guard import snapshot_task_scope
from .task_lease import _history
from .task_result_service import read_result
from .worker_scope_evidence import _snapshot_valid
from .worker_review_identity import require_operator

_TABLE = "worker_external_attestations"
_READ_SCHEMA = "bach.worker-external-attestation.v1"
_RECEIPT_SCHEMA = "bach.worker-external-attestation-receipt.v1"
_SCOPE_SCHEMA = "bach.worker-external-scope-receipt.v1"
_REVISION_SCHEMA = "bach.worker-result-revision.external-attested.v1"
_ATTEST_ACTION = "worker_external_result_attested"
_SCOPE_ACTION = "worker_external_result_scope_capture"
_SCOPE_ACTOR = "external-scope-controller"
_HEX = re.compile(r"[a-f0-9]{64}\Z")
_SUBMISSION = re.compile(r"sha256:[a-f0-9]{64}\Z")
_BINDING_FIELDS = frozenset({
    "task_id", "result_id", "result_sha256", "fence", "generation", "task_version",
    "status_revision", "submission_revision", "submission_event_id", "submitted_status_event_id",
})
_REQUEST_FIELDS = _BINDING_FIELDS | {
    "source_id", "model_key", "model_label", "binding_sha256", "run_id", "turn_id",
    "source_artifact_ids", "result_artifact_id", "source_reported_at", "verification_method", "checked",
}
_CHECKS = frozenset({"source_identity", "model_identity", "run_turn", "result_content"})


def _row(cursor):
    value = cursor.fetchone()
    return dict(zip((column[0] for column in cursor.description), value)) if value is not None else None


def _exists(conn, table):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _unavailable(reason):
    return {"schema": _READ_SCHEMA, "source_kind": "external_attested",
            "availability": "unavailable", "reason": reason, "result_revision": None}


def _utc(value):
    if type(value) is not str or len(value) > 64:
        raise ValueError("Explizite UTC-Quellzeit erforderlich")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("Explizite UTC-Quellzeit erforderlich")
    return parsed.isoformat()


def _validate_binding(value):
    evidence.settings._object(value, _BINDING_FIELDS)
    for key in ("task_id", "result_id", "fence", "status_revision", "submission_event_id", "submitted_status_event_id"):
        if type(value[key]) is not int or value[key] <= 0:
            raise ValueError("Positive Task-/Result-/Ereigniskennung erforderlich")
    for key in ("result_sha256", "task_version"):
        if type(value[key]) is not str or not _HEX.fullmatch(value[key]):
            raise ValueError("Vollständige Ergebnis- und Taskrevision erforderlich")
    if type(value["submission_revision"]) is not str or not _SUBMISSION.fullmatch(value["submission_revision"]):
        raise ValueError("Vollständige Submissionrevision erforderlich")
    if (type(value["generation"]) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value["generation"]) is None):
        raise ValueError("Gültige Ausführungsgeneration erforderlich")
    if not 0 < value["submitted_status_event_id"] < value["submission_event_id"]:
        raise ValueError("Ungültige Submission-Ereignisfolge")
    if value["status_revision"] != value["submitted_status_event_id"]:
        raise ValueError("Ergebnis gehört nicht zur abgegebenen Reviewrevision")
    return dict(value)


def validate_request(payload):
    evidence.settings._object(payload, _REQUEST_FIELDS)
    value = _validate_binding({key: payload[key] for key in _BINDING_FIELDS})
    for key in ("source_id", "model_key", "run_id", "turn_id"):
        value[key] = evidence._identifier(payload[key])
    value["model_label"] = evidence._label(payload["model_label"])
    digest = payload["binding_sha256"]
    if type(digest) is not str or not _HEX.fullmatch(digest):
        raise ValueError("Explizite externe Identitätsrevision erforderlich")
    value["binding_sha256"] = digest
    ids = payload["source_artifact_ids"]
    if (type(ids) is not list or not 1 <= len(ids) <= 8
            or any(type(item) is not str or evidence._ARTIFACT_ID.fullmatch(item) is None for item in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("Ein bis acht private Herkunftsartefakte erforderlich")
    result_id = payload["result_artifact_id"]
    if (type(result_id) is not str or evidence._ARTIFACT_ID.fullmatch(result_id) is None
            or result_id in ids):
        raise ValueError("Eigenes privates Artefakt mit dem vollständigen Ergebnis erforderlich")
    value["source_artifact_ids"] = sorted(ids)
    value["result_artifact_id"] = result_id
    value["source_reported_at"] = None if payload["source_reported_at"] is None else _utc(payload["source_reported_at"])
    if payload["verification_method"] != evidence.VERIFICATION_METHOD:
        raise ValueError("Explizite Operatorprüfung der Herkunftsartefakte erforderlich")
    value["verification_method"] = evidence.VERIFICATION_METHOD
    evidence.settings._object(payload["checked"], _CHECKS)
    if any(payload["checked"][key] is not True for key in _CHECKS):
        raise ValueError("Operator muss Herkunft, Modell, Run/Turn und Ergebnis geprüft haben")
    value["checked"] = dict(payload["checked"])
    return value


def _binding(record):
    # Acceptance changes the live status revision; provenance remains bound to
    # the submitted review status. The writer separately CASes the live DTO.
    value = {key: record.get(key) for key in _BINDING_FIELDS}
    value["status_revision"] = record.get("submitted_status_event_id")
    return _validate_binding(value)


def _native_linked(conn, result_id):
    return (_exists(conn, "worker_model_executions") and conn.execute(
        "SELECT 1 FROM worker_model_executions WHERE result_id=?", (result_id,)).fetchone() is not None)


def _principal(conn, request):
    value = evidence.resolve_external_principal(evidence.registry_snapshot(conn),
        source_id=request["source_id"], model_key=request["model_key"],
        model_label=request["model_label"], binding_sha256=request["binding_sha256"])
    if value is None:
        raise evidence.ExternalEvidenceConflict("Externe Modell-/Quellbindung ist nicht aktuell")
    return {key: value[key] for key in evidence._ENTRY_FIELDS | {"binding_sha256"}}


def _artifacts(conn, request, record):
    source = evidence.artifact_manifest(conn, request["source_artifact_ids"])
    result = evidence._artifact_record(conn, request["result_artifact_id"])
    if result is None or result["content"] != record["result"].encode("utf-8"):
        raise evidence.ExternalEvidenceConflict("Privates Ergebnisartefakt stimmt nicht mit dem vollständigen Result überein")
    return {"source_artifacts": source,
            "result_artifact": {key: result[key] for key in ("artifact_id", "sha256", "size_bytes", "media_type")}}


def _receipt(record, request, principal, artifacts, actor, attested_at):
    return {"schema": _RECEIPT_SCHEMA, "binding": _binding(record),
            "source": principal, "model_label": request["model_label"],
            "run_id": request["run_id"], "turn_id": request["turn_id"],
            "verification_method": request["verification_method"], "checked": request["checked"],
            "source_reported_at": request["source_reported_at"],
            "attested_by": actor, "attested_at": attested_at,
            "request_sha256": evidence._digest(request), **artifacts}


def _scope_receipt(record, snapshot, receipt_sha, event_id, attested_at):
    return {"schema": _SCOPE_SCHEMA, "binding": _binding(record), "snapshot": snapshot,
            "attestation_sha256": receipt_sha, "attestation_event_id": event_id,
            "captured_at": attested_at}


def _event_detail(receipt, digest):
    return {"schema": receipt["schema"], "binding": receipt["binding"], "receipt_sha256": digest}


def _event_matches(conn, event_id, *, task_id, action, actor, receipt, digest):
    if type(event_id) is not int:
        return False
    event = _row(conn.execute("SELECT task_id,action,field_changed,old_value,new_value,changed_by "
                              "FROM task_history WHERE id=?", (event_id,)))
    return (event is not None and event["task_id"] == task_id and event["action"] == action
            and event["field_changed"] == "lease" and event["old_value"] is None
            and event["changed_by"] == actor
            and evidence._json(json.loads(event["new_value"])) == evidence._json(_event_detail(receipt, digest)))


def _operator_active(conn, actor):
    if type(actor) is not str or re.fullmatch(r"operator-device:[1-9][0-9]*", actor) is None:
        return False
    return conn.execute("SELECT 1 FROM devices d JOIN task_result_operators o ON o.device_id=d.id "
                        "WHERE d.id=? AND d.status='active'", (int(actor.split(":")[1]),)).fetchone() is not None


def _ensure_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS worker_external_attestations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL,
        result_id INTEGER NOT NULL UNIQUE, platform_id TEXT NOT NULL,
        tenant_id TEXT NOT NULL, account_id TEXT NOT NULL, run_id TEXT NOT NULL, turn_id TEXT NOT NULL,
        request TEXT NOT NULL, request_sha256 TEXT NOT NULL,
        attestation TEXT NOT NULL, attestation_sha256 TEXT NOT NULL, attestation_event_id INTEGER NOT NULL,
        scope_receipt TEXT NOT NULL, scope_receipt_sha256 TEXT NOT NULL, scope_event_id INTEGER NOT NULL,
        UNIQUE(platform_id,tenant_id,account_id,run_id,turn_id))""")


def read_external_attestation(conn, record):
    """Pure DB/history read. It exposes no artifacts, account/run IDs or paths.

    Recorded scope becomes current only through project_external_attestation.
    Current registry membership and active attester authority are rechecked;
    their revocation preserves history but disables its use for acceptance.
    """
    try:
        if (not isinstance(record, dict) or record.get("reason") not in {"awaiting_review", "accepted"}
                or record.get("submission", {}).get("availability") != "available"):
            return _unavailable("submission_not_current")
        bound = _binding(record)
        if _native_linked(conn, bound["result_id"]):
            return _unavailable("native_execution_present")
        if not _exists(conn, _TABLE):
            return _unavailable("external_attestation_not_recorded")
        row = _row(conn.execute("SELECT * FROM worker_external_attestations WHERE result_id=?", (bound["result_id"],)))
        if row is None:
            return _unavailable("external_attestation_not_recorded")
        request = validate_request(json.loads(row["request"]))
        if ({key: request[key] for key in _BINDING_FIELDS} != bound
                or row["task_id"] != bound["task_id"] or row["result_id"] != bound["result_id"]
                or row["request_sha256"] != evidence._digest(request)):
            return _unavailable("external_attestation_invalid")
        principal = _principal(conn, request)
        if any(row[key] != principal[key] for key in ("platform_id", "tenant_id", "account_id")):
            return _unavailable("external_attestation_invalid")
        if any(row[key] != request[key] for key in ("run_id", "turn_id")):
            return _unavailable("external_attestation_invalid")
        receipt = json.loads(row["attestation"])
        actor, at = receipt.get("attested_by"), receipt.get("attested_at")
        if not _operator_active(conn, actor):
            return _unavailable("attesting_operator_revoked")
        if _utc(at) != at or receipt != _receipt(record, request, principal, _artifacts(conn, request, record), actor, at):
            return _unavailable("external_attestation_invalid")
        digest = evidence._digest(receipt)
        event_id, scope_event = row["attestation_event_id"], row["scope_event_id"]
        if (digest != row["attestation_sha256"] or type(event_id) is not int or type(scope_event) is not int
                or not bound["submission_event_id"] < event_id < scope_event
                or not _event_matches(conn, event_id, task_id=bound["task_id"], action=_ATTEST_ACTION,
                    actor=actor, receipt=receipt, digest=digest)):
            return _unavailable("external_attestation_invalid")
        scope = json.loads(row["scope_receipt"])
        snapshot = scope.get("snapshot")
        if (not _snapshot_valid(snapshot, bound["task_id"])
                or scope != _scope_receipt(record, snapshot, digest, event_id, at)
                or evidence._digest(scope) != row["scope_receipt_sha256"]
                or not _event_matches(conn, scope_event, task_id=bound["task_id"], action=_SCOPE_ACTION,
                    actor=_SCOPE_ACTOR, receipt=scope, digest=row["scope_receipt_sha256"])):
            return _unavailable("external_scope_invalid")
        return {"schema": _READ_SCHEMA, "source_kind": "external_attested", "availability": "recorded",
                "task_id": bound["task_id"], "result_id": bound["result_id"],
                "submission_revision": bound["submission_revision"],
                "attestation_sha256": digest, "attestation_event_id": event_id,
                "scope_receipt_sha256": row["scope_receipt_sha256"], "scope_event_id": scope_event,
                "snapshot": snapshot, "model_principal_id": principal["model_principal_id"],
                "platform_id": principal["platform_id"], "model_label": request["model_label"],
                "verification_method": evidence.VERIFICATION_METHOD,
                "attested_at": at, "source_reported_at": request["source_reported_at"], "result_revision": None}
    except evidence.ExternalEvidenceConflict:
        return _unavailable("external_identity_changed")
    except (sqlite3.DatabaseError, evidence.settings.PolicyUnavailable, KeyError,
            ValueError, TypeError, AttributeError, OverflowError):
        return _unavailable("external_attestation_invalid")


def _current(conn, task_id, request):
    view = read_result(conn, task_id)
    record = view.get("result")
    task = _row(conn.execute("SELECT claim_id FROM tasks WHERE id=?", (task_id,)))
    if (view.get("status") != "review" or not isinstance(record, dict)
            or record.get("reason") != "awaiting_review" or task is None or task["claim_id"]
            or record.get("submission", {}).get("availability") != "available"
            or record.get("completion_policy_version") != 1
            or view.get("status_revision") != request["status_revision"]
            or view.get("task_version") != request["task_version"]
            or {key: record.get(key) for key in _BINDING_FIELDS} != {key: request[key] for key in _BINDING_FIELDS}):
        raise evidence.ExternalEvidenceConflict("Task-/Resultrevision oder freie Lease hat sich geändert")
    if _native_linked(conn, request["result_id"]):
        raise evidence.ExternalEvidenceConflict("Native Modellausführung darf nicht extern überschrieben werden")
    return record


def attest_external_result(conn, task_id, payload, *, operator_token, repo_root=None, worktrees_dir=None):
    """CAS an explicit operator attestation of checked, real private artifacts.

    The caller supplies no Git path/snapshot/time for the BACH observation.
    A current clean registered task tree is mandatory, including on replay.
    Authentication and every DB dependency are checked again under the writer.
    """
    request = validate_request(payload)
    if type(task_id) is not int or task_id <= 0 or task_id != request["task_id"]:
        raise ValueError("Task-ID stimmt nicht mit dem Ergebnisbeleg überein")
    if conn.in_transaction:
        raise ValueError("Externe Attestierung benötigt eine Verbindung ohne offene Transaktion")
    try:
        conn.execute("BEGIN")
        require_operator(conn, operator_token)
        before = _current(conn, task_id, request)
        principal = _principal(conn, request)
        artifacts = _artifacts(conn, request, before)
    finally:
        conn.rollback()
    try:
        snapshot = snapshot_task_scope(task_id, repo_root=repo_root, worktrees_dir=worktrees_dir)
    except Exception as exc:
        raise evidence.ExternalEvidenceUnavailable("Aktueller registrierter Task-Scope ist nicht prüfbar") from exc
    if not _snapshot_valid(snapshot, task_id):
        raise evidence.ExternalEvidenceUnavailable("Aktueller registrierter Task-Scope ist nicht prüfbar")
    try:
        conn.execute("BEGIN IMMEDIATE")
        actor = require_operator(conn, operator_token)
        current = _current(conn, task_id, request)
        if principal != _principal(conn, request) or artifacts != _artifacts(conn, request, current):
            raise evidence.ExternalEvidenceConflict("Externe Identität oder Artefakte wurden parallel geändert")
        _ensure_schema(conn)
        existing = _row(conn.execute("SELECT request_sha256 FROM worker_external_attestations WHERE result_id=?", (request["result_id"],)))
        if existing is not None:
            result = read_external_attestation(conn, current)
            if (existing["request_sha256"] != evidence._digest(request)
                    or result.get("availability") != "recorded" or result["snapshot"] != snapshot):
                raise evidence.ExternalEvidenceConflict("Unveränderlicher externer Ergebnisbeleg weicht ab")
            conn.rollback()
            return {**result, "created": False}
        now = datetime.now(timezone.utc)
        receipt = _receipt(current, request, principal, artifacts, actor, now.isoformat())
        digest = evidence._digest(receipt)
        event = _history(conn, task_id, _ATTEST_ACTION, actor, now, _event_detail(receipt, digest))
        scope = _scope_receipt(current, snapshot, digest, event, now.isoformat())
        scope_sha = evidence._digest(scope)
        scope_event = _history(conn, task_id, _SCOPE_ACTION, _SCOPE_ACTOR, now, _event_detail(scope, scope_sha))
        conn.execute("""INSERT INTO worker_external_attestations
            (task_id,result_id,platform_id,tenant_id,account_id,run_id,turn_id,
             request,request_sha256,attestation,attestation_sha256,attestation_event_id,
             scope_receipt,scope_receipt_sha256,scope_event_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (task_id, request["result_id"], principal["platform_id"], principal["tenant_id"], principal["account_id"],
             request["run_id"], request["turn_id"], evidence._json(request), evidence._digest(request),
             evidence._json(receipt), digest, event, evidence._json(scope), scope_sha, scope_event))
        result = read_external_attestation(conn, current)
        if result.get("availability") != "recorded":
            raise evidence.ExternalEvidenceUnavailable("Neuer externer Beleg konnte nicht unabhängig gelesen werden")
        conn.commit()
        return {**result, "created": True}
    except sqlite3.IntegrityError as exc:
        raise evidence.ExternalEvidenceConflict("Externer Run/Turn oder Ergebnisbeleg wurde bereits verwendet") from exc
    finally:
        if conn.in_transaction:
            conn.rollback()


def external_result_revision(data):
    """Compute the external revision without borrowing a native execution ID."""
    if (not isinstance(data, dict) or data.get("schema") != _READ_SCHEMA
            or data.get("source_kind") != "external_attested"
            or data.get("availability") not in {"recorded", "available"}
            or type(data.get("submission_revision")) is not str
            or not _SUBMISSION.fullmatch(data["submission_revision"])):
        return None
    for key in ("attestation_sha256", "scope_receipt_sha256"):
        if type(data.get(key)) is not str or not _HEX.fullmatch(data[key]):
            return None
    if (type(data.get("attestation_event_id")) is not int
            or type(data.get("scope_event_id")) is not int
            or not 0 < data["attestation_event_id"] < data["scope_event_id"]):
        return None
    return evidence._digest({"schema": _REVISION_SCHEMA, **{key: data[key] for key in (
        "submission_revision", "attestation_sha256", "attestation_event_id", "scope_receipt_sha256", "scope_event_id")}})


def project_external_attestation(data, *, repo_root=None, worktrees_dir=None):
    """Re-observe Git after the DB snapshot ends; never approve a result."""
    revision = external_result_revision(data)
    if revision is None:
        return _unavailable("external_attestation_not_recorded")
    try:
        task_id = data.get("task_id")
        if type(task_id) is not int or task_id <= 0 or not _snapshot_valid(data.get("snapshot"), task_id):
            return _unavailable("external_scope_invalid")
        current = snapshot_task_scope(task_id, repo_root=repo_root, worktrees_dir=worktrees_dir)
        if not _snapshot_valid(current, task_id):
            return _unavailable("current_git_unavailable")
        if current != data["snapshot"]:
            return _unavailable("current_git_changed")
        return {**data, "availability": "available", "result_revision": revision}
    except Exception:
        return _unavailable("current_git_unavailable")
