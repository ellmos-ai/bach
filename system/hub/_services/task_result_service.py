"""Canonical worker submissions and explicit acceptance of their exact content.

Worker output is evidence awaiting review. Only a separate operator transaction
can accept its digest, task version and current status revision. No provider
argument or cached Done receipt grants that authority.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.metadata
import importlib.util
import inspect
import json
import re
import sqlite3
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

SUBMISSION_RECEIPT_SCHEMA = "bach.worker-submission-receipt.v1"
SUBMISSION_READBACK_SCHEMA = "bach.worker-submission-readback.v1"


class WorkerSelfCheckRequired(ValueError):
    """A confirmed simple-task submission lacks its required full self-check."""


class ResultConflict(ValueError):
    """The result, task content or status changed since the operator read it."""


class ResultPermissionDenied(PermissionError):
    """The dedicated operator credential is missing or revoked."""


class ResultCorrectionError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class ResultCorrectionValidation(ResultCorrectionError):
    pass


class ResultHistoryUnavailable(RuntimeError):
    """History cannot be served with a bounded indexed query on this database."""


class ResultCorrectionConflict(ResultCorrectionError):
    pass


class CorrectionContextDenied(Exception):
    """A task-bound worker cannot prove the current correction context."""
    pass


class ResultServiceUnavailable(RuntimeError):
    """The separately installed result-review policy or schema is unavailable."""


class ResultServicePermissionDenied(PermissionError):
    """The scoped result-service credential or policy denies this action."""
    def __init__(self, message, *, code="service_scope_denied"):
        super().__init__(message)
        self.code = code


class ResultServiceConflict(ResultCorrectionError):
    """The service scope revision or reviewed result changed before the write."""


_RESULT_SERVICE_ACTIONS = frozenset({"read", "history", "accept", "correction"})
_RESULT_SERVICE_POLICY_INPUT_SCHEMA = "task-result-review-input.v1"
_RESULT_SERVICE_POLICY_DECISION_SCHEMA = "task-result-service-review-decision.v1"
_RESULT_SERVICE_POLICY_REASON_CODES = frozenset({
    "allow", "scope_denied", "self_review", "producer_binding_missing",
    "service_revoked", "invalid_request",
})
_RESULT_SERVICE_POLICY_RELATIVE_PATH = "tools/task_result_review_policy.py"
_RESULT_SERVICE_POLICY_MODULES = {}
_RESULT_SERVICE_POLICY_LOCK = threading.RLock()


def _load_result_service_review_policy():
    """Load only the RECORD-verified file from the installed Open Ocean package."""
    with _RESULT_SERVICE_POLICY_LOCK:
        try:
            distribution = importlib.metadata.distribution("open-ocean")
            name = str(distribution.metadata.get("Name") or "").casefold().replace("_", "-")
            version = str(distribution.version or "").strip()
            if name != "open-ocean" or not version:
                raise ResultServiceUnavailable("Ergebnisreview-Richtlinie nicht verfügbar")
            relative = _RESULT_SERVICE_POLICY_RELATIVE_PATH
            files = distribution.files
            if files is None:
                raise ResultServiceUnavailable("Ergebnisreview-Richtlinie nicht verfügbar")
            matches = [entry for entry in files
                       if str(entry).replace(chr(92), "/") == relative]
            if len(matches) != 1:
                raise ResultServiceUnavailable("Ergebnisreview-Richtlinie nicht verfügbar")
            file_hash = matches[0].hash
            if file_hash is None or file_hash.mode != "sha256" or not file_hash.value:
                raise ResultServiceUnavailable("Ergebnisreview-Richtlinie nicht verfügbar")

            target = Path(distribution.locate_file(relative))
            if target.is_symlink() or not target.is_file():
                raise ResultServiceUnavailable("Ergebnisreview-Richtlinie nicht verfügbar")
            resolved = target.resolve(strict=True)
            distribution_root = Path(distribution.locate_file("")).resolve(strict=True)
            if distribution_root not in resolved.parents:
                raise ResultServiceUnavailable("Ergebnisreview-Richtlinie nicht verfügbar")

            # Read through one no-follow descriptor, bound the file, and execute
            # these exact verified bytes so importlib cannot reopen a changed path.
            import os
            import stat
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(resolved, flags)
            try:
                before = os.fstat(descriptor)
                if not stat.S_ISREG(before.st_mode) or before.st_size > 131072:
                    raise ResultServiceUnavailable("Ergebnisreview-Richtlinie nicht verfügbar")
                chunks = []
                remaining = 131073
                while remaining:
                    chunk = os.read(descriptor, min(remaining, 32768))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                source = b"".join(chunks)
                after = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            path_stat = resolved.lstat()
            identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            identity_path = (path_stat.st_dev, path_stat.st_ino, path_stat.st_size, path_stat.st_mtime_ns)
            if (identity_before != identity_after or identity_before != identity_path
                    or len(source) != before.st_size or len(source) > 131072):
                raise ResultServiceUnavailable("Ergebnisreview-Richtlinie nicht verfügbar")

            digest = hashlib.sha256(source).hexdigest()
            observed = base64.urlsafe_b64encode(hashlib.sha256(source).digest()).decode("ascii").rstrip("=")
            if not hmac.compare_digest(observed, file_hash.value):
                raise ResultServiceUnavailable("Ergebnisreview-Richtlinie nicht verfügbar")
            cache_key = (str(resolved), version, digest)
            module = _RESULT_SERVICE_POLICY_MODULES.get(cache_key)
            if module is None:
                import types
                module_name = "_bach_open_ocean_result_policy_" + digest[:20]
                module = types.ModuleType(module_name)
                module.__file__ = str(resolved)
                module.__package__ = ""
                sys.modules[module_name] = module
                try:
                    exec(compile(source, str(resolved), "exec"), module.__dict__)  # noqa: S102 - exact bounded bytes passed RECORD and SHA-256 checks
                except Exception:
                    sys.modules.pop(module_name, None)
                    raise
                function = getattr(module, "evaluate_service_review", None)
                if (getattr(module, "INPUT_SCHEMA", None) != _RESULT_SERVICE_POLICY_INPUT_SCHEMA
                        or getattr(module, "DECISION_SCHEMA", None) != _RESULT_SERVICE_POLICY_DECISION_SCHEMA
                        or not callable(function)
                        or tuple(inspect.signature(function).parameters)
                        != ("scope", "task", "producer_binding", "reviewer_subject", "action")
                        or set(getattr(module, "REASON_CODES", ())) != _RESULT_SERVICE_POLICY_REASON_CODES):
                    sys.modules.pop(module_name, None)
                    raise ResultServiceUnavailable("Ergebnisreview-Richtlinie nicht verfügbar")
                _RESULT_SERVICE_POLICY_MODULES[cache_key] = module
                if len(_RESULT_SERVICE_POLICY_MODULES) > 8:
                    oldest = next(iter(_RESULT_SERVICE_POLICY_MODULES))
                    _RESULT_SERVICE_POLICY_MODULES.pop(oldest, None)
            provenance = {"distribution": name, "version": version, "source_sha256": digest}
            return module, provenance
        except ResultServiceUnavailable:
            raise
        except Exception:  # noqa: BLE001 - metadata, I/O and import errors are deliberately redacted fail-closed
            raise ResultServiceUnavailable("Ergebnisreview-Richtlinie nicht verfügbar") from None


def _evaluate_result_service_policy(scope, task, producer_binding, reviewer_subject, action):
    policy, provenance = _load_result_service_review_policy()
    try:
        decision = policy.evaluate_service_review(scope, task, producer_binding, reviewer_subject, action)
    except Exception:  # noqa: BLE001 - policy failures are deliberately redacted fail-closed
        raise ResultServiceUnavailable("Ergebnisreview-Richtlinie nicht verfügbar") from None
    if (not isinstance(decision, dict)
            or set(decision) != {"schema", "allowed", "reason_code"}
            or decision.get("schema") != _RESULT_SERVICE_POLICY_DECISION_SCHEMA
            or type(decision.get("allowed")) is not bool
            or type(decision.get("reason_code")) is not str
            or decision["reason_code"] not in _RESULT_SERVICE_POLICY_REASON_CODES
            or decision["allowed"] != (decision["reason_code"] == "allow")):
        raise ResultServiceUnavailable("Ergebnisreview-Richtlinie nicht verfügbar")
    return decision, provenance


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
        submission_receipt_version INTEGER NOT NULL DEFAULT 0,
        completion_policy_version INTEGER NOT NULL DEFAULT 0,
        submitted_status_event_id INTEGER,
        submission_receipt_sha256 TEXT,
        accepted_by TEXT,
        accepted_at TEXT,
        accepted_status_event_id INTEGER,
        acceptance_event_id INTEGER,
        user_review_revision TEXT,
        user_review_event_id INTEGER,
        contract_attestation_revision TEXT,
        contract_attestation_event_id INTEGER,
        completion_decision_event_id INTEGER,
        completion_decision_sha256 TEXT,
        UNIQUE(task_id, fence)
    )""")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(worker_task_results)")}
    for name, declaration in (("submission_receipt_version", "INTEGER NOT NULL DEFAULT 0"),
                              ("completion_policy_version", "INTEGER NOT NULL DEFAULT 0"),
                              ("submitted_status_event_id", "INTEGER"),
                              ("submission_receipt_sha256", "TEXT"),
                              ("user_review_revision", "TEXT"),
                              ("user_review_event_id", "INTEGER"),
                              ("contract_attestation_revision", "TEXT"),
                              ("contract_attestation_event_id", "INTEGER"),
                              ("completion_decision_event_id", "INTEGER"),
                              ("completion_decision_sha256", "TEXT")):
        if name not in columns:
            conn.execute(f"ALTER TABLE worker_task_results ADD COLUMN {name} {declaration}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_worker_task_results_task_submission_event "
                 "ON worker_task_results(task_id, submission_event_id DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_worker_task_results_task_acceptance_event "
                 "ON worker_task_results(task_id, acceptance_event_id DESC)")
    if _table_exists(conn, "task_history"):
        conn.execute("CREATE INDEX IF NOT EXISTS idx_task_history_task_action_id "
                     "ON task_history(task_id, action, id DESC)")


def ensure_result_correction_schema(conn):
    """Add the append-only correction ledger and explicit operator scope."""
    ensure_result_schema(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
    if "result_correction_request_id" not in columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN result_correction_request_id INTEGER")
    operators = conn.execute("SELECT type FROM sqlite_master WHERE name='task_result_operators'").fetchone()
    if operators and operators[0] == "table":
        operator_columns = {row[1] for row in conn.execute("PRAGMA table_info(task_result_operators)")}
        if "can_request_correction" not in operator_columns:
            conn.execute("ALTER TABLE task_result_operators ADD COLUMN can_request_correction INTEGER NOT NULL DEFAULT 0")
    conn.execute("""CREATE TABLE IF NOT EXISTS task_result_corrections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        request_id TEXT NOT NULL,
        correction_round INTEGER NOT NULL,
        source_result_id INTEGER NOT NULL,
        source_result_sha256 TEXT NOT NULL,
        source_generation TEXT NOT NULL,
        source_fence INTEGER NOT NULL,
        source_task_version TEXT NOT NULL,
        source_status_revision INTEGER NOT NULL,
        correction_note TEXT NOT NULL,
        requested_by_device_id INTEGER NOT NULL,
        requested_at TEXT NOT NULL,
        policy_decision_sha256 TEXT,
        event_id INTEGER,
        next_task_version TEXT,
        UNIQUE(task_id, request_id),
        UNIQUE(task_id, correction_round)
    )""")
    correction_columns = {row[1] for row in conn.execute("PRAGMA table_info(task_result_corrections)")}
    if "policy_decision_sha256" not in correction_columns:
        conn.execute("ALTER TABLE task_result_corrections ADD COLUMN policy_decision_sha256 TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_result_corrections_event "
                 "ON task_result_corrections(task_id, event_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_result_corrections_task_event_desc "
                 "ON task_result_corrections(task_id, event_id DESC)")


def _table_exists(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


_RESULT_SERVICE_REQUIRED_COLUMNS = {
    "task_result_services": {"service_id", "credential_scheme", "credential_salt",
                             "credential_verifier", "issuer_id", "principal_id",
                             "generation", "revision", "status", "created_at", "revoked_at"},
    "task_result_service_scopes": {"scope_id", "service_id", "revision", "action", "task_id", "category"},
    "task_result_service_producer_bindings": {"result_id", "task_id", "result_sha256", "generation", "fence", "task_version", "producer_principal", "issuer_id", "submission_event_id"},
    "task_result_service_audit": {"service_id", "service_revision", "action", "task_id", "result_id", "result_sha256", "task_version", "status_revision", "decision_schema", "decision_reason", "policy_distribution", "policy_version", "policy_sha256", "event_id", "occurred_at"},
    "task_result_corrections": {"id", "task_id", "request_id", "correction_round", "source_result_id", "source_result_sha256", "source_generation", "source_fence", "source_task_version", "source_status_revision", "correction_note", "requested_by_device_id", "requested_by_service_id", "requested_at", "event_id", "next_task_version"},
}
_RESULT_SERVICE_SCOPE_SCHEMA = "task-result-service-scope.v1"
_RESULT_SERVICE_TARGET_SCHEMA = "bach.task-result-review-target.v1"
_RESULT_SERVICE_PRODUCER_SCHEMA = "bach.task-result-producer-binding.v1"
_RESULT_SERVICE_REVIEWER_SCHEMA = "bach.task-result-service-principal.v1"
_RESULT_SERVICE_ISSUER = "bach.result-service.v1"
_RESULT_PRODUCER_ISSUER = "bach.native-task-lease.v1"
_RESULT_SERVICE_CREDENTIAL_SCHEME = "argon2id-v1"
_RESULT_SERVICE_ARGON2_SALT_BYTES = 16
_RESULT_SERVICE_ARGON2_VERIFIER_BYTES = 32
_RESULT_SERVICE_ARGON2_MEMORY_COST_KIB = 19 * 1024
_RESULT_SERVICE_ARGON2_ITERATIONS = 2
_RESULT_SERVICE_ARGON2_LANES = 1


def _result_service_schema_present(conn):
    "Read-only schema gate. Request paths never create or migrate these tables."
    try:
        for table, expected in _RESULT_SERVICE_REQUIRED_COLUMNS.items():
            if not _table_exists(conn, table):
                return False
            table_info = list(conn.execute(f"PRAGMA table_info({table})"))
            columns = {row[1] for row in table_info}
            if not expected <= columns:
                return False
            if table == "task_result_services":
                primary_key = [row[1] for row in table_info if row[5]]
                if primary_key != ["service_id"]:
                    return False
        task_columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
        result_columns = {row[1] for row in conn.execute("PRAGMA table_info(worker_task_results)")}
        return ({"id", "status", "category", "claim_id", "claim_fence", "claim_task_version",
                 "claim_result_generation", "result_correction_request_id"} <= task_columns
                and {"id", "task_id", "fence", "generation", "task_version", "result_sha256",
                     "submission_event_id"} <= result_columns)
    except sqlite3.Error:
        return False


def _result_service_token_bytes(token):
    if not isinstance(token, str) or re.fullmatch(r"[A-Za-z0-9_-]{43,256}", token) is None:
        raise ResultServicePermissionDenied("Service-Credential fehlt oder ist ungültig",
                                            code="service_credential_invalid")
    return token.encode("ascii")


def _verify_result_service_credential(token, scheme, salt, verifier):
    if scheme != _RESULT_SERVICE_CREDENTIAL_SCHEME:
        raise ResultServiceUnavailable("Service-Credentialformat ist nicht verfügbar")
    if (not isinstance(salt, bytes) or len(salt) != _RESULT_SERVICE_ARGON2_SALT_BYTES
            or not isinstance(verifier, bytes)
            or len(verifier) != _RESULT_SERVICE_ARGON2_VERIFIER_BYTES):
        raise ResultServiceUnavailable("Service-Credentialformat ist nicht verfügbar")
    try:
        from cryptography.exceptions import InvalidKey, UnsupportedAlgorithm
        from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
    except ImportError:
        raise ResultServiceUnavailable("Service-Credentialprüfung ist nicht verfügbar") from None
    try:
        Argon2id(salt=salt, length=_RESULT_SERVICE_ARGON2_VERIFIER_BYTES,
                 iterations=_RESULT_SERVICE_ARGON2_ITERATIONS,
                 lanes=_RESULT_SERVICE_ARGON2_LANES,
                 memory_cost=_RESULT_SERVICE_ARGON2_MEMORY_COST_KIB).verify(
                     _result_service_token_bytes(token), verifier)
    except ResultServicePermissionDenied:
        raise
    except InvalidKey:
        raise ResultServicePermissionDenied("Service-Credential fehlt oder ist ungültig",
                                            code="service_credential_invalid") from None
    except (UnsupportedAlgorithm, MemoryError, ValueError, TypeError):
        raise ResultServiceUnavailable("Service-Credentialprüfung ist nicht verfügbar") from None


def _result_service_context(conn, service_id, token, *, expected_revision=None):
    if not _result_service_schema_present(conn):
        raise ResultServiceUnavailable("Ergebnisreview-Schema ist nicht verfügbar")
    if (not isinstance(service_id, str) or not service_id.strip()
            or service_id != service_id.strip() or len(service_id) > 128 or "\x00" in service_id):
        raise ResultServicePermissionDenied("Service-Identität fehlt oder ist ungültig",
                                            code="service_credential_invalid")
    row = _dict_row(conn.execute(
        "SELECT service_id,credential_scheme,credential_salt,credential_verifier,"
        "issuer_id,principal_id,generation,revision,status "
        "FROM task_result_services WHERE service_id=?", (service_id,)))
    if row is None:
        raise ResultServicePermissionDenied("Service-Credential fehlt oder ist ungültig",
                                            code="service_credential_invalid")
    _verify_result_service_credential(token, row["credential_scheme"],
                                      row["credential_salt"], row["credential_verifier"])
    if row.get("status") != "active":
        raise ResultServicePermissionDenied("Service wurde widerrufen", code="service_revoked")
    if (row.get("issuer_id") != _RESULT_SERVICE_ISSUER
            or not isinstance(row.get("service_id"), str) or not row["service_id"]
            or not isinstance(row.get("principal_id"), str) or not row["principal_id"]
            or not isinstance(row.get("generation"), str) or not row["generation"]
            or type(row.get("revision")) is not int or row["revision"] <= 0):
        raise ResultServiceUnavailable("Service-Identität ist nicht kanonisch")
    if expected_revision is not None and (
            type(expected_revision) is not int or expected_revision != row["revision"]):
        raise ResultServiceConflict("service_revision_conflict", "Service-Scope hat sich geändert; bitte neu laden")
    scope_rows = conn.execute(
        "SELECT action,task_id,category FROM task_result_service_scopes "
        "WHERE service_id=? AND revision=? ORDER BY scope_id", (row["service_id"], row["revision"])
    ).fetchall()
    entries = []
    for action, task_id, category in scope_rows:
        if not isinstance(action, str) or action not in _RESULT_SERVICE_ACTIONS:
            raise ResultServiceUnavailable("Service-Scope ist nicht kanonisch")
        entry = {"action": action}
        if type(task_id) is int and task_id > 0 and category is None:
            entry["task_id"] = task_id
        elif (task_id is None and isinstance(category, str) and category.strip()
              and "\x00" not in category and len(category) <= 128
              and category.strip() not in {"*", "all"}):
            entry["category"] = category
        else:
            raise ResultServiceUnavailable("Service-Scope ist nicht kanonisch")
        entries.append(entry)
    return {
        "service_id": row["service_id"], "revision": row["revision"],
        "scope": {"schema": _RESULT_SERVICE_SCOPE_SCHEMA, "service_id": row["service_id"],
                  "revision": row["revision"], "entries": entries},
        "reviewer": {"schema": _RESULT_SERVICE_REVIEWER_SCHEMA, "service_id": row["service_id"],
                     "issuer_id": row["issuer_id"], "principal_id": row["principal_id"],
                     "generation": row["generation"], "revision": row["revision"], "status": row["status"]},
    }


def _result_service_producer_binding(conn, record):
    if not isinstance(record, dict):
        return None
    result_id = record.get("result_id", record.get("id"))
    if type(result_id) is not int:
        return None
    row = _dict_row(conn.execute(
        "SELECT result_id,task_id,result_sha256,generation,fence,task_version,"
        "producer_principal,issuer_id FROM task_result_service_producer_bindings WHERE result_id=?",
        (result_id,)))
    if row is None:
        return None
    return {
        "schema": _RESULT_SERVICE_PRODUCER_SCHEMA, "issuer_id": row["issuer_id"],
        "task_id": row["task_id"], "result_id": row["result_id"],
        "result_sha256": row["result_sha256"], "generation": row["generation"],
        "fence": row["fence"], "task_version": row["task_version"],
        "producer_principal": row["producer_principal"],
    }


def _result_service_target(task, record):
    from .task_lease import task_content_version
    if record is None:
        return {"schema": _RESULT_SERVICE_TARGET_SCHEMA, "task_id": task["id"],
                "category": task.get("category"), "result_id": None, "result_sha256": None,
                "generation": None, "fence": None, "task_version": None}
    result_id = record.get("result_id", record.get("id"))
    return {"schema": _RESULT_SERVICE_TARGET_SCHEMA, "task_id": task["id"],
            "category": task.get("category"), "result_id": result_id,
            "result_sha256": record.get("result_sha256"), "generation": record.get("generation"),
            "fence": record.get("fence"), "task_version": record.get("task_version") or task_content_version(task)}


def _authorize_result_service(conn, context, task, record, action):
    if (record is not None
            and record.get("result_id", record.get("id")) is None):
        raise ResultServicePermissionDenied("Ergebnisherkunft ist nicht bestätigt", code="producer_binding_missing")
    target = _result_service_target(task, record)
    binding = _result_service_producer_binding(conn, record) if record is not None else None
    decision, provenance = _evaluate_result_service_policy(
        context["scope"], target, binding, context["reviewer"], action)
    if not decision["allowed"]:
        reason = decision["reason_code"]
        message = ("Ergebnisherkunft ist nicht bestätigt" if reason == "producer_binding_missing"
                   else "Service-Scope oder Prüferbindung lehnt diese Aktion ab")
        raise ResultServicePermissionDenied(message, code=reason)
    if action == "accept" and record is not None and record.get("completion_policy_version") == 1:
        # Policy-bound completion needs the authenticated operator review, so a scoped
        # service never holds the accept capability for it (capabilities report False).
        raise ResultServicePermissionDenied("Policyverwalteter Abschluss benötigt die Operator-Prüfung",
                                            code="completion_policy_operator_review_required")
    return target, binding, provenance


def _result_service_audit(conn, *, context, action, target, status_revision, provenance, now, event_id=None):
    conn.execute("""INSERT INTO task_result_service_audit
        (service_id,service_revision,action,task_id,result_id,result_sha256,task_version,
         status_revision,decision_schema,decision_reason,policy_distribution,policy_version,
         policy_sha256,event_id,occurred_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (context["service_id"], context["revision"], action, target["task_id"],
         target["result_id"], target["result_sha256"], target["task_version"],
         status_revision, _RESULT_SERVICE_POLICY_DECISION_SCHEMA, "allow",
         provenance["distribution"], provenance["version"], provenance["source_sha256"],
         event_id, now))


def _has_results(conn):
    return _table_exists(conn, "worker_task_results")


def _dict_row(cursor):
    row = cursor.fetchone()
    return None if row is None else dict(zip((c[0] for c in cursor.description), row))


def _status_revision(conn, task_id):
    row = conn.execute("SELECT MAX(id) FROM task_history WHERE task_id=? "
                       "AND field_changed='status' AND action='status_change'", (task_id,)).fetchone()
    return int(row[0] or 0)


def validate_submission(payload, *, max_chars=None):
    if max_chars is not None and (type(max_chars) is not int or not 1 <= max_chars <= 3000):
        raise ValueError("Task-Ausgabelimit muss eine Ganzzahl von 1 bis 3000 sein")
    limit = min(max_chars, 3000) if max_chars is not None else 3000
    if not isinstance(payload, dict) or set(payload) != {"generation", "result"}:
        raise ValueError("Ergebnisabgabe erlaubt nur generation und result")
    generation, text = payload["generation"], payload["result"]
    if not isinstance(generation, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", generation):
        raise ValueError("Workergeneration fehlt oder ist ungültig")
    if not isinstance(text, str) or not text.strip() or len(text) > limit or "\x00" in text:
        raise ValueError(f"Konkretes Ergebnis mit höchstens {limit} Zeichen erforderlich")
    acknowledgement = re.sub(r"[\s.!:;✅]+", " ", text.casefold()).strip()
    if re.fullmatch(r"(?:(?:task|aufgabe)\s*#?\d+\s*)?(?:done|completed|erledigt|abgeschlossen)", acknowledgement):
        raise ValueError("Eine Erledigungsbestätigung ist kein fachliches Ergebnis")
    return generation, text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def insert_submission(conn, row, payload, *, worker, now, max_chars=None):
    from .task_lease import task_content_version
    generation, text, digest = validate_submission(payload, max_chars=max_chars)
    completion_asserted = False
    if row.get("completion_contract_json") is None:
        from .worker_result_review import review_task_marker
        if not review_task_marker(conn, row["id"]):
            frozen = _submission_policy(conn, row["id"])
            if (frozen["availability"] == "available" and
                    (frozen["override"].get("mode") or frozen["policy"]["default_mode"]) == "simple_task"):
                from .worker_completion_contract import (evaluate_worker_self_check,
                    evaluate_worker_completion_assertion)
                self_check_met = evaluate_worker_self_check(text)["met"] is True
                if not self_check_met:
                    completion_asserted = evaluate_worker_completion_assertion(text)["met"] is True
                if not self_check_met and not completion_asserted:
                    raise WorkerSelfCheckRequired("Vollständiger Selbstcheck erforderlich")
    ensure_result_schema(conn)
    version = task_content_version(row)
    cursor = conn.execute("""INSERT INTO worker_task_results
        (task_id,fence,generation,task_version,result,result_sha256,submitted_by,submitted_at,
         submission_receipt_version,completion_policy_version)
        VALUES (?,?,?,?,?,?,?,?,1,1)""", (row["id"], row["claim_fence"], generation,
        version, text, digest, worker, now))
    result_id = cursor.lastrowid
    binding_columns = {item[1] for item in conn.execute(
        "PRAGMA table_info(task_result_service_producer_bindings)")}
    claimed_by = row.get("claimed_by")
    claim_generation = row.get("claim_result_generation")
    claim_id = row.get("claim_id")
    if ({"result_id", "task_id", "result_sha256", "generation", "fence", "task_version",
         "producer_principal", "issuer_id", "submission_event_id", "bound_at"} <= binding_columns
            and isinstance(claimed_by, str) and claimed_by and worker == claimed_by
            and isinstance(claim_id, str) and claim_id
            and isinstance(claim_generation, str) and claim_generation == generation
            and type(row.get("claim_fence")) is int and row["claim_fence"] > 0
            and row.get("claim_task_version") == version):
        conn.execute("""INSERT INTO task_result_service_producer_bindings
            (result_id,task_id,result_sha256,generation,fence,task_version,producer_principal,
             issuer_id,submission_event_id,bound_at) VALUES (?,?,?,?,?,?,?,?,NULL,?)""",
            (result_id, row["id"], digest, generation, row["claim_fence"], version,
             claimed_by, _RESULT_PRODUCER_ISSUER, now))
    if completion_asserted:
        from .task_lease import _history, parse_ts
        marker_now = now if isinstance(now, datetime) else parse_ts(now)
        if marker_now is None:
            raise ValueError("Zeitstempel der Fertigmeldung nicht lesbar")
        _history(conn, row["id"], "worker_completion_asserted", worker, marker_now,
            {"schema": "bach.worker-completion-assertion.v1", "task_id": row["id"],
             "result_id": result_id, "result_sha256": digest,
             "generation": generation, "fence": row["claim_fence"],
             "task_version": version})
    return {"schema": "bach.worker-result.v1", "result_id": result_id,
            "task_id": row["id"], "fence": row["claim_fence"], "generation": generation,
            "task_version": task_content_version(row), "result_sha256": digest,
            "submitted_by": worker, "submitted_at": now,
            "submission_receipt_version": 1, "completion_policy_version": 1,
            "result": text, "accepted": False}


def result_reference(record):
    return f"bach-task-result:{record['result_id']}:{record['result_sha256']}"


def _receipt_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _completion_decision_readback(conn, record):
    """Validate the policy event recorded before an accepted status change."""
    event_id = record.get("completion_decision_event_id")
    digest = record.get("completion_decision_sha256")
    if (type(event_id) is not int or event_id <= 0
            or type(digest) is not str or re.fullmatch(r"[a-f0-9]{64}", digest) is None):
        return {"availability": "unavailable", "reason": "completion_decision_missing"}
    event = _dict_row(conn.execute("SELECT * FROM task_history WHERE id=? AND task_id=?",
                                  (event_id, record["task_id"])))
    if (event is None or event.get("action") != "worker_completion_decision"
            or event.get("field_changed") != "lease"
            or event.get("changed_by") != "native-worker-completion-policy"
            or event.get("old_value") is not None
            or type(record.get("accepted_status_event_id")) is not int
            or event_id >= record["accepted_status_event_id"]):
        return {"availability": "unavailable", "reason": "completion_decision_invalid"}
    try:
        detail = json.loads(event["new_value"])
        receipt = {key: value for key, value in detail.items() if key != "receipt_sha256"}
        if (detail.get("receipt_sha256") != digest or _receipt_digest(receipt) != digest
                or detail.get("schema") != "bach.worker-completion-evaluation.v1"
                or type(detail.get("task_id")) is not int or detail["task_id"] != record["task_id"]
                or type(detail.get("result_id")) is not int or detail["result_id"] != record["result_id"]
                or detail.get("result_sha256") != record["result_sha256"]
                or detail.get("task_version") != record["task_version"]
                or type(detail.get("status_revision")) is not int
                or not 0 <= detail["status_revision"] < event_id
                or type(detail.get("result_revision")) is not str
                or re.fullmatch(r"[a-f0-9]{64}", detail["result_revision"]) is None
                or detail.get("decision", {}).get("completion_allowed") is not True):
            raise ValueError("receipt mismatch")
        from .worker_result_provenance import current_result_revision
        revision = current_result_revision(record)
        if revision is None or revision != detail["result_revision"]:
            raise ValueError("revision changed")
        return {"availability": "available", "event_id": event_id,
                "result_revision": revision, "decision_sha256": digest}
    except (TypeError, ValueError, KeyError, AttributeError):
        return {"availability": "unavailable", "reason": "completion_decision_invalid"}


def _submission_policy(conn, task_id):
    """Freeze configuration from the submit transaction, not a later settings read."""
    try:
        from . import worker_policy_settings as settings
    except ImportError:
        return {"availability": "unavailable", "reason": "policy_contract_unavailable"}
    original_row_factory = conn.row_factory
    try:
        # The lease service also accepts plain sqlite connections. Settings
        # expect named rows; restore the caller's factory before returning.
        conn.row_factory = sqlite3.Row
        global_view = settings._global(conn)
        task_view = settings._task_snapshot(conn, task_id)
        return {"availability": "available", "contract_version": settings.CONTRACT,
            "policy": global_view["policy"],
            "global_configuration_version": global_view["configuration_version"],
            "global_policy_source": global_view["policy_source"],
            "override": task_view["override"],
            "configuration_version": task_view["configuration_version"],
            "policy_source": task_view["effective"]["policy_source"],
            "override_present": task_view["effective"]["policy_source"] == "task_override",
            "user_review_required": task_view["effective"]["user_review_required"]}
    except sqlite3.Error:
        return {"availability": "unavailable", "reason": "policy_store_unavailable"}
    except (ValueError, TypeError, KeyError, AttributeError, settings.PolicyUnavailable):
        return {"availability": "unavailable", "reason": "policy_contract_unavailable"}
    finally:
        conn.row_factory = original_row_factory


def prepare_submission_receipt(conn, record):
    """Bind the exact in-progress -> review event before release history is added."""
    status_id = _status_revision(conn, record["task_id"])
    status = conn.execute("SELECT old_value,new_value,changed_by,changed_at FROM task_history "
        "WHERE id=? AND task_id=? AND action='status_change' AND field_changed='status'",
        (status_id, record["task_id"])).fetchone()
    if (type(status_id) is not int or status_id <= 0 or status is None
            or tuple(status[:3]) != ("in_progress", "review", record["submitted_by"])
            or not isinstance(status[3], str) or not status[3]):
        raise ResultConflict("Submission-Statuswechsel ist nicht bestätigt")
    return {"schema": SUBMISSION_RECEIPT_SCHEMA, "result_id": record["result_id"],
        "task_id": record["task_id"], "fence": record["fence"],
        "generation": record["generation"], "task_version": record["task_version"],
        "result_sha256": record["result_sha256"], "submitted_by": record["submitted_by"],
        "submitted_at": record["submitted_at"], "submitted_status_event_id": status_id,
        "submitted_status_changed_at": status[3],
        "completion_policy_version": record["completion_policy_version"],
        "policy": _submission_policy(conn, record["task_id"])}


def _submission_revision(record, digest):
    result_id = record.get("result_id", record.get("id"))
    return "sha256:" + _receipt_digest({"schema": "bach.worker-submission-revision.v1",
        "task_id": record["task_id"], "result_id": result_id,
        "submission_event_id": record["submission_event_id"], "submission_receipt_sha256": digest})


def finish_submission(conn, record, event_id, receipt):
    digest = _receipt_digest(receipt)
    cursor = conn.execute("UPDATE worker_task_results SET submission_event_id=?,"
        "submitted_status_event_id=?,submission_receipt_sha256=? WHERE id=? AND task_id=? "
        "AND submission_event_id IS NULL", (event_id, receipt["submitted_status_event_id"],
        digest, record["result_id"], record["task_id"]))
    if cursor.rowcount != 1:
        raise ResultConflict("Submission-Beleg konnte nicht gespeichert werden")
    if _table_exists(conn, "task_result_service_producer_bindings"):
        conn.execute("UPDATE task_result_service_producer_bindings SET submission_event_id=? "
                     "WHERE result_id=?", (event_id, record["result_id"]))
    record["submission_event_id"] = event_id
    record["submitted_status_event_id"] = receipt["submitted_status_event_id"]
    record["submission_receipt_sha256"] = digest
    record["status_revision"] = receipt["submitted_status_event_id"]
    record["submission_revision"] = _submission_revision(record, digest)
    record["submission"] = {"schema": SUBMISSION_READBACK_SCHEMA,
        "availability": "available", "receipt_sha256": digest,
        "submitted_status_event_id": receipt["submitted_status_event_id"],
        "policy": receipt["policy"]}
    return record


def _submission_readback(conn, record):
    """Verify one historical submit without requiring its released claim to be live."""
    invalid = {"schema": SUBMISSION_READBACK_SCHEMA, "availability": "unavailable",
               "reason": "submission_receipt_invalid"}
    event_id = record.get("submission_event_id")
    if type(event_id) is not int or event_id <= 0:
        return invalid
    event = _dict_row(conn.execute("SELECT task_id,action,field_changed,old_value,"
        "new_value,changed_by,changed_at FROM task_history WHERE id=?", (event_id,)))
    if (event is None or type(record.get("id")) is not int or record["id"] <= 0
            or type(record.get("task_id")) is not int or record["task_id"] <= 0
            or type(record.get("fence")) is not int or record["fence"] <= 0
            or event["task_id"] != record["task_id"] or event["action"] != "lease_release"
            or event["field_changed"] != "lease" or event["old_value"] != "in_progress"
            or event["changed_by"] != record["submitted_by"]
            or event["changed_at"] != record["submitted_at"]):
        return invalid
    try:
        detail = json.loads(event["new_value"])
    except (TypeError, ValueError):
        return invalid
    if (not isinstance(detail, dict) or type(detail.get("fence")) is not int
            or detail["fence"] != record["fence"] or detail.get("outcome") != "review"
            or detail.get("result_ref") != result_reference({"result_id": record["id"],
                "result_sha256": record["result_sha256"]}) or detail.get("note") != ""):
        return invalid
    receipt = detail.get("submission_receipt")
    digest = record.get("submission_receipt_sha256")
    status_id = record.get("submitted_status_event_id")
    version = record.get("submission_receipt_version", 0)
    completion_version = record.get("completion_policy_version", 0)
    if type(version) is not int or version not in (0, 1):
        return invalid
    if type(completion_version) is not int or completion_version not in (0, 1):
        return invalid
    if completion_version == 1 and version != 1:
        return invalid
    if version == 0 and receipt is None and digest is None and status_id is None:
        status = _dict_row(conn.execute("SELECT id,old_value,new_value,changed_by FROM task_history "
            "WHERE task_id=? AND action='status_change' AND field_changed='status' AND id<? "
            "ORDER BY id DESC LIMIT 1", (record["task_id"], event_id)))
        if (status is None or status["old_value"] != "in_progress"
                or status["new_value"] != "review"
                or status["changed_by"] != record["submitted_by"]):
            return invalid
        return {"schema": SUBMISSION_READBACK_SCHEMA, "availability": "legacy_release_only",
                "reason": "legacy_release_only"}
    if version != 1:
        return invalid
    if (not isinstance(receipt, dict) or type(status_id) is not int or status_id <= 0
            or status_id >= event_id or not isinstance(digest, str)
            or not re.fullmatch(r"[a-f0-9]{64}", digest)):
        return invalid
    if (type(receipt.get("result_id")) is not int or receipt["result_id"] <= 0
            or type(receipt.get("task_id")) is not int or receipt["task_id"] <= 0
            or type(receipt.get("fence")) is not int or receipt["fence"] <= 0
            or type(receipt.get("submitted_status_event_id")) is not int
            or receipt["submitted_status_event_id"] <= 0
            or not isinstance(receipt.get("submitted_status_changed_at"), str)
            or not receipt["submitted_status_changed_at"]):
        return invalid
    expected = {"schema": SUBMISSION_RECEIPT_SCHEMA, "result_id": record["id"],
        "task_id": record["task_id"], "fence": record["fence"],
        "generation": record["generation"], "task_version": record["task_version"],
        "result_sha256": record["result_sha256"], "submitted_by": record["submitted_by"],
        "submitted_at": record["submitted_at"], "submitted_status_event_id": status_id,
        "submitted_status_changed_at": receipt["submitted_status_changed_at"],
        "policy": receipt.get("policy")}
    if completion_version == 1:
        expected["completion_policy_version"] = 1
    policy = receipt.get("policy")
    try:
        digest_matches = _receipt_digest(receipt) == digest
    except (TypeError, ValueError, OverflowError):
        digest_matches = False
    if (receipt != expected or not isinstance(policy, dict)
            or policy.get("availability") not in ("available", "unavailable")
            or (policy["availability"] == "unavailable" and policy.get("reason") not in (
                "policy_store_unavailable", "policy_contract_unavailable"))
            or not digest_matches):
        return invalid
    status = _dict_row(conn.execute("SELECT id,task_id,action,field_changed,old_value,"
        "new_value,changed_by,changed_at FROM task_history WHERE id=?", (status_id,)))
    latest_before = conn.execute("SELECT MAX(id) FROM task_history WHERE task_id=? "
        "AND action='status_change' AND field_changed='status' AND id<?",
        (record["task_id"], event_id)).fetchone()
    if (status is None or status["task_id"] != record["task_id"]
            or status["action"] != "status_change" or status["field_changed"] != "status"
            or status["old_value"] != "in_progress" or status["new_value"] != "review"
            or status["changed_by"] != record["submitted_by"]
            or status["changed_at"] != receipt["submitted_status_changed_at"]
            or latest_before is None or latest_before[0] != status_id):
        return invalid
    return {"schema": SUBMISSION_READBACK_SCHEMA, "availability": "available",
        "receipt_sha256": digest, "submitted_status_event_id": status_id,
        "policy": policy}


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


def _operator_capabilities(conn, operator_token):
    empty = {"accept_result": False, "request_correction": False}
    if not isinstance(operator_token, str) or not operator_token.strip() or len(operator_token) > 256:
        return empty
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"devices", "task_result_operators"} <= tables:
        return empty
    columns = {row[1] for row in conn.execute("PRAGMA table_info(task_result_operators)")}
    correction_expr = "o.can_request_correction" if "can_request_correction" in columns else "0"
    from gui.device_auth import _hash_token
    row = conn.execute(
        f"SELECT o.device_id, {correction_expr} FROM devices d "
        "JOIN task_result_operators o ON o.device_id=d.id "
        "WHERE d.token_hash=? AND d.status='active'",
        (_hash_token(operator_token),),
    ).fetchone()
    if row is None:
        return empty
    return {"accept_result": True, "request_correction": bool(row[1])}


_TASK_LEASE_CONTEXT_COLUMNS = frozenset({
    "id", "status", "claimed_by", "claimed_at", "claim_id", "claim_fence",
    "claim_expires_at", "claim_task_version", "claim_result_generation",
})


def _task_lease_context_schema_present(conn):
    """Check existing lease columns without running a schema migration."""
    try:
        if not _table_exists(conn, "tasks"):
            return False
        columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
    except sqlite3.Error:
        return False
    return _TASK_LEASE_CONTEXT_COLUMNS <= columns


def _correction_operator_device_id(conn, operator_token):
    """Read an explicitly correction-enabled operator; missing schema denies."""
    if not isinstance(operator_token, str) or not operator_token.strip() or len(operator_token) > 256:
        return None
    try:
        if not _table_exists(conn, "devices") or not _table_exists(conn, "task_result_operators"):
            return None
        device_columns = {row[1] for row in conn.execute("PRAGMA table_info(devices)")}
        operator_columns = {row[1] for row in conn.execute("PRAGMA table_info(task_result_operators)")}
        if not {"id", "token_hash", "status"} <= device_columns:
            return None
        if not {"device_id", "can_request_correction"} <= operator_columns:
            return None
        from gui.device_auth import _hash_token
        row = conn.execute(
            "SELECT d.id, o.can_request_correction FROM devices d "
            "JOIN task_result_operators o ON o.device_id=d.id "
            "WHERE d.token_hash=? AND d.status='active'",
            (_hash_token(operator_token),),
        ).fetchone()
    except sqlite3.OperationalError:
        # A missing/revoked operator schema is a regular denial, never a 500 or migration.
        return None
    if row is None or type(row[0]) is not int or type(row[1]) is not int or row[1] != 1:
        return None
    return row[0]


def _result_service_capabilities(conn, context, task, record):
    actions = {}
    reasons = {}
    for action in sorted(_RESULT_SERVICE_ACTIONS):
        try:
            _authorize_result_service(conn, context, task, record, action)
            actions[action] = True
        except ResultServicePermissionDenied as exc:
            actions[action] = False
            reasons[action] = exc.code
    return {"schema": "bach.task-result-service-capabilities.v1",
            "revision": context["revision"], "actions": actions, "reasons": reasons}


def read_result(conn, task_id, *, operator_token=None, service_id=None, service_token=None):
    """Read task and result from one snapshot; service access is separately scoped."""
    if (service_id is not None or service_token is not None) and operator_token is not None:
        raise ResultServicePermissionDenied("Mehrdeutige Ergebnisanmeldung", code="ambiguous_credentials")
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("BEGIN")
    try:
        from .task_lease import task_content_version
        task = _dict_row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
        if task is None:
            raise ResultConflict("Task nicht vorhanden")
        revision = _status_revision(conn, task_id)
        service_context = _result_service_context(conn, service_id, service_token) if service_id is not None or service_token is not None else None
        operator_capabilities = _operator_capabilities(conn, operator_token) if service_context is None else None
        record = (_dict_row(conn.execute("SELECT * FROM worker_task_results WHERE task_id=? "
                                        "ORDER BY id DESC LIMIT 1", (task_id,)))
                  if _has_results(conn) else None)
        if record is None:
            result = _legacy_result(conn, task_id)
            if service_context is not None and result is not None:
                raise ResultServicePermissionDenied("Legacy-Ergebnis ohne vertrauenswürdige Produzentenbindung",
                                                    code="producer_binding_missing")
            service_capabilities = None
            if service_context is not None:
                _authorize_result_service(conn, service_context, task, None, "read")
                service_capabilities = _result_service_capabilities(conn, service_context, task, None)
            response = {"schema": "bach.task-result-readback.v1", "task_id": task_id,
                        "task_version": task_content_version(task), "status": task["status"],
                        "status_revision": revision, "result": result, "verified": True}
            if service_context is None:
                response["operator_capabilities"] = operator_capabilities
            else:
                response["service_capabilities"] = service_capabilities
            return response

        service_capabilities = None
        if service_context is not None:
            _authorize_result_service(conn, service_context, task, record, "read")
            service_capabilities = _result_service_capabilities(conn, service_context, task, record)
        same_content = task_content_version(task) == record["task_version"]
        same_fence = int(task.get("claim_fence") or 0) == record["fence"]
        same_digest = hashlib.sha256(record["result"].encode("utf-8")).hexdigest() == record["result_sha256"]
        submission = _submission_readback(conn, record)
        release_valid = submission["availability"] in {"available", "legacy_release_only"}
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
        accepted = (task["status"] in {"done", "completed"} and release_valid
                    and same_content and same_fence
                    and same_digest and decision_matches and bool(record["accepted_by"])
                    and record["accepted_status_event_id"] == revision)
        submission_revision = (_submission_revision(record, submission["receipt_sha256"])
                               if submission["availability"] == "available" else None)
        record.update(schema="bach.worker-result.v1", result_id=record.pop("id"),
                      accepted=accepted, status_revision=revision, submission=submission,
                      submission_revision=submission_revision,
                      reason=("accepted" if accepted else "task_content_changed" if not same_content
                              else "fence_changed" if not same_fence else "result_content_changed" if not same_digest
                               else "submission_receipt_invalid" if not release_valid
                              else "awaiting_review" if task["status"] == "review" else "acceptance_not_current"))
        from .worker_execution_evidence import read_execution_evidence
        record["execution"] = read_execution_evidence(conn, record)
        from .worker_scope_evidence import read_scope_evidence
        # Git is deliberately outside this SQLite snapshot. A recorded receipt
        # is historical evidence until the local SDK/API revalidates its tree.
        record["scope"] = read_scope_evidence(conn, record)
        record["result_revision"] = None
        from .worker_result_provenance import read_result_source
        record = read_result_source(conn, record)
        from .worker_result_review import read_review_evidence, review_task_metadata
        # This read is history/DB only. The SDK/API scope projection below
        # must still compare the exact currently observed Git revision.
        record["model_review"] = read_review_evidence(conn, record)
        if record.get("completion_policy_version") == 1 and accepted:
            review_child = review_task_metadata(conn, task_id)
            child_row = (_dict_row(conn.execute("SELECT target_task_id FROM worker_result_model_reviews "
                "WHERE review_task_id=? AND child_result_id=?",
                (task_id, record["result_id"]))) if review_child is not None else None)
            if (review_child is not None and child_row is not None
                    and child_row["target_task_id"] == review_child["target_task_id"]
                    and record.get("accepted_by") == "native-result-review-controller"):
                record["completion_decision"] = {"availability": "administrative_review_child",
                    "result_id": record["result_id"], "target_task_id": child_row["target_task_id"]}
            else:
                record["completion_decision"] = _completion_decision_readback(conn, record)
            if record["completion_decision"]["availability"] != "available":
                if record["completion_decision"]["availability"] != "administrative_review_child":
                    record["accepted"] = False
                    record["reason"] = "completion_decision_invalid"
        elif record.get("completion_policy_version") == 1:
            record["completion_decision"] = {"availability": "unavailable",
                "reason": "completion_not_recorded"}
        response = {"schema": "bach.task-result-readback.v1", "task_id": task_id,
                    "task_version": task_content_version(task), "status": task["status"],
                    "status_revision": revision, "result": record, "verified": True}
        if service_context is None:
            response["operator_capabilities"] = operator_capabilities
        else:
            response["service_capabilities"] = service_capabilities
        return response
    finally:
        if owns_transaction:
            conn.rollback()


def _validate_correction_payload(payload):
    fields = {"result_id", "result_sha256", "generation", "fence", "task_version",
              "status_revision", "request_id", "correction_note"}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ResultCorrectionValidation("correction_request_invalid", "Korrekturanfrage hat unbekannte oder fehlende Felder")
    if type(payload["result_id"]) is not int or payload["result_id"] <= 0:
        raise ResultCorrectionValidation("correction_request_invalid", "result_id ist ungültig")
    if type(payload["fence"]) is not int or payload["fence"] <= 0:
        raise ResultCorrectionValidation("correction_request_invalid", "fence ist ungültig")
    if type(payload["status_revision"]) is not int or payload["status_revision"] < 0:
        raise ResultCorrectionValidation("correction_request_invalid", "status_revision ist ungültig")
    for name in ("result_sha256", "task_version"):
        if not isinstance(payload[name], str) or re.fullmatch(r"[a-f0-9]{64}", payload[name]) is None:
            raise ResultCorrectionValidation("correction_request_invalid", f"{name} ist ungültig")
    if not isinstance(payload["generation"], str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", payload["generation"]) is None:
        raise ResultCorrectionValidation("correction_request_invalid", "generation ist ungültig")
    try:
        request_id = uuid.UUID(payload["request_id"])
    except (ValueError, TypeError, AttributeError):
        raise ResultCorrectionValidation("correction_request_invalid", "request_id ist ungültig") from None
    if request_id.version != 4 or str(request_id) != payload["request_id"]:
        raise ResultCorrectionValidation("correction_request_invalid", "request_id muss eine kanonische UUIDv4 sein")
    note = payload["correction_note"]
    if not isinstance(note, str) or not note.strip() or len(note) > 1200 or "\x00" in note:
        raise ResultCorrectionValidation("correction_request_invalid", "correction_note muss 1 bis 1200 Zeichen enthalten")
    return dict(payload)


def _correction_ack(row, *, replayed=False):
    return {
        "schema": "bach.task-result-correction-request.v1",
        "request_id": row["request_id"], "task_id": row["task_id"],
        "correction_id": row["id"], "correction_round": row["correction_round"],
        "source_result_id": row["source_result_id"],
        "source_result_sha256": row["source_result_sha256"],
        "status": "pending", "next_task_version": row["next_task_version"],
        "replayed": replayed,
    }


def request_result_correction(conn, task_id, payload, *, operator_token=None,
                              service_id=None, service_token=None, service_revision=None):
    """Return the exact current review result under an operator or scoped-service CAS."""
    if type(task_id) is not int or task_id <= 0:
        raise ResultCorrectionValidation("correction_request_invalid", "task_id ist ungültig")
    request = _validate_correction_payload(payload)
    service_mode = service_id is not None or service_token is not None
    if service_mode == (operator_token is not None):
        raise ResultServicePermissionDenied("Genau eine Ergebnisanmeldung erforderlich", code="ambiguous_credentials")
    if conn.in_transaction:
        raise ResultCorrectionConflict("task_not_revisable", "Korrektur braucht eine eigene kanonische Transaktion")
    from .task_lease import task_content_version, _history, _utcnow, _local_naive
    from hub.task_audit import apply_task_field_changes

    prechecked_device_id = None
    prechecked_service = None
    prechecked_provenance = None
    if service_mode:
        if type(service_revision) is not int or service_revision <= 0:
            raise ResultServiceConflict("service_revision_required", "Service-Scope-Version muss bestätigt werden")
        prechecked_service = _result_service_context(conn, service_id, service_token, expected_revision=service_revision)
        if not _task_lease_context_schema_present(conn) or not _result_service_schema_present(conn):
            raise ResultServiceUnavailable("Korrektur-Schema ist nicht verfügbar")
        pre_observed = read_result(conn, task_id)
        pre_record = pre_observed.get("result")
        pre_task = _dict_row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
        if pre_task is None:
            raise ResultCorrectionConflict("task_not_revisable", "Task ist nicht vorhanden")
        _, _, prechecked_provenance = _authorize_result_service(
            conn, prechecked_service, pre_task, pre_record, "correction")
    else:
        prechecked_device_id = _correction_operator_device_id(conn, operator_token)
        if prechecked_device_id is None:
            raise ResultPermissionDenied("Korrekturfreigabe fehlt oder wurde widerrufen")
        if not _task_lease_context_schema_present(conn):
            raise ResultCorrectionConflict("task_not_revisable", "Task-Lease-Schema ist nicht verfügbar")

    conn.execute("BEGIN IMMEDIATE")
    try:
        if service_mode:
            service_context = _result_service_context(conn, service_id, service_token, expected_revision=service_revision)
            if (service_context["service_id"] != prechecked_service["service_id"]
                    or service_context["revision"] != prechecked_service["revision"]):
                raise ResultServiceConflict("service_revision_conflict", "Service-Scope hat sich geändert; bitte neu laden")
            if not _task_lease_context_schema_present(conn) or not _result_service_schema_present(conn):
                raise ResultServiceUnavailable("Korrektur-Schema ist nicht verfügbar")
            service_id = service_context["service_id"]
            device_id = None
            actor = f"operator-service:{service_id}"
            required_correction_columns = _RESULT_SERVICE_REQUIRED_COLUMNS["task_result_corrections"]
            correction_columns = {item[1] for item in conn.execute("PRAGMA table_info(task_result_corrections)")}
            if not required_correction_columns <= correction_columns:
                raise ResultServiceUnavailable("Korrektur-Schema ist nicht verfügbar")
        else:
            device_id = _correction_operator_device_id(conn, operator_token)
            if device_id is None or device_id != prechecked_device_id:
                raise ResultPermissionDenied("Korrekturfreigabe fehlt oder wurde widerrufen")
            if not _task_lease_context_schema_present(conn):
                raise ResultCorrectionConflict("task_not_revisable", "Task-Lease-Schema ist nicht verfügbar")
            ensure_result_correction_schema(conn)
            service_id = None
            service_context = None
            actor = f"operator-device:{device_id}"
            correction_columns = {item[1] for item in conn.execute("PRAGMA table_info(task_result_corrections)")}

        existing = _dict_row(conn.execute(
            "SELECT * FROM task_result_corrections WHERE task_id=? AND request_id=?",
            (task_id, request["request_id"]),
        ))
        if existing is not None:
            same = (
                existing["source_result_id"] == request["result_id"]
                and existing["source_result_sha256"] == request["result_sha256"]
                and existing["source_generation"] == request["generation"]
                and existing["source_fence"] == request["fence"]
                and existing["source_task_version"] == request["task_version"]
                and existing["source_status_revision"] == request["status_revision"]
                and existing["correction_note"] == request["correction_note"]
                and existing.get("requested_by_device_id") == device_id
                and (existing.get("requested_by_service_id") if "requested_by_service_id" in existing else None) == service_id
            )
            if not same:
                raise ResultCorrectionConflict("request_id_conflict", "request_id wurde bereits anders verwendet")
            conn.commit()
            ack = _correction_ack(existing, replayed=True)
            if service_mode:
                ack["service_revision"] = service_context["revision"]
            return ack

        observed = read_result(conn, task_id)
        record = observed.get("result")
        task = _dict_row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
        if task is None:
            raise ResultCorrectionConflict("task_not_revisable", "Task ist nicht vorhanden")
        service_provenance = prechecked_provenance
        if service_mode:
            _, _, service_provenance = _authorize_result_service(
                conn, service_context, task, record, "correction")
        if (observed.get("status") != "review" or observed.get("status_revision") != request["status_revision"]
                or observed.get("task_version") != request["task_version"]
                or not isinstance(record, dict) or record.get("result_id") is None
                or record.get("reason") != "awaiting_review"
                or record.get("result_id") != request["result_id"]
                or record.get("result_sha256") != request["result_sha256"]
                or record.get("generation") != request["generation"]
                or record.get("fence") != request["fence"]
                or record.get("task_version") != request["task_version"]
                or type(record.get("submission_event_id")) is not int):
            raise ResultCorrectionConflict("result_changed_reload", "Ergebnis oder Task hat sich geändert; bitte neu laden")
        if task.get("status") != "review" or task.get("claim_id"):
            raise ResultCorrectionConflict("task_not_revisable", "Nur ein freigegebenes Review-Ergebnis kann korrigiert werden")

        now = _utcnow()
        stamp = _local_naive(now)
        correction_round = int(conn.execute(
            "SELECT COALESCE(MAX(correction_round),0)+1 FROM task_result_corrections WHERE task_id=?",
            (task_id,),
        ).fetchone()[0])
        if "requested_by_service_id" in correction_columns:
            cursor = conn.execute(
                """INSERT INTO task_result_corrections
                   (task_id,request_id,correction_round,source_result_id,source_result_sha256,
                    source_generation,source_fence,source_task_version,source_status_revision,
                    correction_note,requested_by_device_id,requested_by_service_id,requested_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (task_id, request["request_id"], correction_round, request["result_id"],
                 request["result_sha256"], request["generation"], request["fence"],
                 request["task_version"], request["status_revision"], request["correction_note"],
                 device_id, service_id, stamp),
            )
        else:
            if service_mode:
                raise ResultServiceUnavailable("Korrektur-Schema ist nicht verfügbar")
            cursor = conn.execute(
                """INSERT INTO task_result_corrections
                   (task_id,request_id,correction_round,source_result_id,source_result_sha256,
                    source_generation,source_fence,source_task_version,source_status_revision,
                    correction_note,requested_by_device_id,requested_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (task_id, request["request_id"], correction_round, request["result_id"],
                 request["result_sha256"], request["generation"], request["fence"],
                 request["task_version"], request["status_revision"], request["correction_note"],
                 device_id, stamp),
            )
        correction_id = cursor.lastrowid
        apply_task_field_changes(conn, task_id, task, {"status": "pending"}, changed_by=actor,
                                 now=stamp, allow_reopen=True)
        pointer = conn.execute(
            "UPDATE tasks SET result_correction_request_id=? WHERE id=? AND status='pending' "
            "AND (claim_id IS NULL OR claim_id='') AND result_correction_request_id IS ?",
            (correction_id, task_id, task.get("result_correction_request_id")),
        )
        if pointer.rowcount != 1:
            raise ResultCorrectionConflict("result_changed_reload", "Task hat sich während der Korrektur geändert")
        next_task = _dict_row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
        next_version = task_content_version(next_task)
        event_id = _history(conn, task_id, "result_correction_request", actor, now,
            {"correction_id": correction_id, "request_id": request["request_id"],
             "correction_round": correction_round, "result_id": request["result_id"],
             "result_sha256": request["result_sha256"], "generation": request["generation"],
             "fence": request["fence"], "task_version": request["task_version"],
             "status_revision": request["status_revision"], "correction_note": request["correction_note"],
             "next_task_version": next_version})
        conn.execute("UPDATE task_result_corrections SET event_id=?,next_task_version=? WHERE id=?",
                     (event_id, next_version, correction_id))
        if service_mode:
            _result_service_audit(conn, context=service_context, action="correction",
                target=_result_service_target(task, record), status_revision=request["status_revision"],
                provenance=service_provenance, now=stamp, event_id=event_id)
        if next_task.get("status") != "pending" or next_task.get("result_correction_request_id") != correction_id:
            raise ResultCorrectionConflict("task_not_revisable", "Korrekturanfrage konnte nicht bestätigt werden")
        conn.commit()
        row = _dict_row(conn.execute("SELECT * FROM task_result_corrections WHERE id=?", (correction_id,)))
        ack = _correction_ack(row)
        if service_mode:
            ack["service_revision"] = service_context["revision"]
        return ack
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise


def _policy_correction_decision_matches(conn, row):
    """Verify the immutable policy event behind a controller correction."""
    digest = row.get("policy_decision_sha256")
    correction_event = row.get("event_id")
    if (type(digest) is not str or re.fullmatch(r"[a-f0-9]{64}", digest) is None
            or type(correction_event) is not int or correction_event <= 0):
        return False
    source = _dict_row(conn.execute("SELECT * FROM worker_task_results WHERE id=? AND task_id=?",
        (row.get("source_result_id"), row.get("task_id"))))
    if source is None:
        return False
    policy_event_id = source.get("completion_decision_event_id")
    if (type(policy_event_id) is not int or not 0 < policy_event_id < correction_event
            or source.get("completion_decision_sha256") != digest):
        return False
    event = _dict_row(conn.execute("SELECT * FROM task_history WHERE id=? AND task_id=?",
        (policy_event_id, source["task_id"])))
    if (event is None or event.get("action") != "worker_completion_decision"
            or event.get("field_changed") != "lease" or event.get("old_value") is not None
            or event.get("changed_by") != "native-worker-completion-policy"):
        return False
    try:
        stored = json.loads(event["new_value"])
        detail = {key: value for key, value in stored.items() if key != "receipt_sha256"}
        if (stored.get("receipt_sha256") != digest or _receipt_digest(detail) != digest
                or detail.get("schema") != "bach.worker-completion-evaluation.v1"
                or type(detail.get("task_id")) is not int or detail["task_id"] != source["task_id"]
                or type(detail.get("result_id")) is not int or detail["result_id"] != source["id"]
                or detail.get("result_sha256") != source["result_sha256"]
                or detail.get("task_version") != source["task_version"]
                or detail.get("status_revision") != row.get("source_status_revision")
                or detail.get("decision", {}).get("state") != "correction_required"
                or detail["decision"].get("completion_allowed") is not False
                or detail.get("status_revision") != source.get("submitted_status_event_id")
                or not 0 < detail["status_revision"] < policy_event_id):
            return False
        guard = detail.get("evidence_guard")
        if guard is None:
            return (type(detail.get("result_revision")) is str
                and re.fullmatch(r"[a-f0-9]{64}", detail["result_revision"]) is not None)
        if (set(guard) != {"schema", "reason", "task_tree", "execution_revision", "author_id"}
                or guard.get("schema") != "bach.worker-missing-scope-guard.v1"
                or guard.get("reason") != "scope_not_recorded"
                or guard.get("task_tree") != "definitively_absent"
                or detail.get("result_revision") is not None
                or detail.get("generation") != source["generation"]
                or detail.get("fence") != source["fence"]
                or detail["decision"] != {"state": "correction_required",
                    "reason": "scope_evidence_missing", "completion_allowed": False,
                    "worker_may_claim_next": True}):
            return False
        submission = _submission_readback(conn, source)
        if submission.get("availability") != "available":
            return False
        revision = _submission_revision(source, submission["receipt_sha256"])
        if revision != detail.get("submission_revision"):
            return False
        from .worker_execution_evidence import read_execution_evidence
        historical = dict(source, result_id=source["id"], reason="awaiting_review",
                          submission=submission, submission_revision=revision)
        execution = read_execution_evidence(conn, historical)
        if (execution.get("availability") != "available"
                or execution.get("execution_revision") != guard["execution_revision"]
                or execution.get("model_principal_id") != guard["author_id"]):
            return False
        if _table_exists(conn, "worker_scope_evidence") and conn.execute(
                "SELECT 1 FROM worker_scope_evidence WHERE result_id=?",
                (source["id"],)).fetchone() is not None:
            return False
        return True
    except (TypeError, ValueError, KeyError, AttributeError, sqlite3.Error):
        return False


def _correction_audit_matches(conn, row, detail):
    """Bind every correction-ledger field to its event before exposing it."""
    expected = {
        "correction_id": row.get("correction_id"),
        "request_id": row.get("request_id"),
        "correction_round": row.get("correction_round"),
        "result_id": row.get("source_result_id"),
        "result_sha256": row.get("source_result_sha256"),
        "generation": row.get("source_generation"),
        "fence": row.get("source_fence"),
        "task_version": row.get("source_task_version"),
        "status_revision": row.get("source_status_revision"),
        "correction_note": row.get("correction_note"),
        "next_task_version": row.get("correction_next_task_version"),
    }
    if not isinstance(detail, dict) or any(name not in detail for name in expected):
        return False
    if any(type(detail[name]) is not type(value) or detail[name] != value
           for name, value in expected.items()):
        return False
    correction_id = expected["correction_id"]
    correction_round = expected["correction_round"]
    source_result_id = expected["result_id"]
    source_digest = expected["result_sha256"]
    generation = expected["generation"]
    fence = expected["fence"]
    source_version = expected["task_version"]
    status_revision = expected["status_revision"]
    note = expected["correction_note"]
    next_version = expected["next_task_version"]
    device_id = row.get("requested_by_device_id")
    policy_sha = row.get("policy_decision_sha256")
    if policy_sha is not None:
        from .worker_result_review import review_invalid_correction_matches
        from .machine_false_acceptance_recovery import repair_correction_matches
        review_correction = (device_id == 0
            and row.get("event_changed_by") == "native-result-review-controller"
            and review_invalid_correction_matches(conn, row))
        machine_repair = (device_id == 0
            and row.get("event_changed_by") == "native-machine-false-acceptance-controller"
            and repair_correction_matches(conn, row, detail))
        if (type(policy_sha) is not str or re.fullmatch(r"[a-f0-9]{64}", policy_sha) is None
                or detail.get("policy_decision_sha256") != policy_sha or device_id != 0
                or not (review_correction or machine_repair or (
                    row.get("event_changed_by") == "native-worker-completion-policy"
                    and _policy_correction_decision_matches(conn, row)))):
            return False
    service_id = row.get("requested_by_service_id")
    if service_id is not None:
        actor_valid = (isinstance(service_id, str) and bool(service_id)
                       and device_id is None and policy_sha is None
                       and row.get("event_changed_by") == f"operator-service:{service_id}")
    elif policy_sha is not None:
        # Device 0 and the native controller evidence were verified above.
        actor_valid = type(device_id) is int and device_id == 0
    else:
        actor_valid = (type(device_id) is int and device_id > 0
                       and row.get("event_changed_by") == f"operator-device:{device_id}")
    if (type(correction_id) is not int or correction_id <= 0
            or type(correction_round) is not int or correction_round <= 0
            or type(source_result_id) is not int or source_result_id <= 0
            or not isinstance(expected["request_id"], str) or not expected["request_id"]
            or not isinstance(source_digest, str) or re.fullmatch(r"[a-f0-9]{64}", source_digest) is None
            or not isinstance(generation, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", generation) is None
            or type(fence) is not int or fence <= 0
            or not isinstance(source_version, str) or re.fullmatch(r"[a-f0-9]{64}", source_version) is None
            or type(status_revision) is not int or status_revision < 0
            or not isinstance(note, str) or not note.strip() or len(note) > 1200 or "\x00" in note
            or not isinstance(next_version, str) or re.fullmatch(r"[a-f0-9]{64}", next_version) is None
            or not actor_valid):
        return False
    audit_time = _canonical_history_timestamp(row.get("event_changed_at"), None)
    ledger_time = _canonical_history_timestamp(row.get("source_timestamp"), None)
    return audit_time is not None and audit_time == ledger_time


def _history_index_gaps(conn):
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    required = set()
    if "worker_task_results" in tables:
        required.update({
            "idx_worker_task_results_task_submission_event",
            "idx_worker_task_results_task_acceptance_event",
        })
    if "task_result_corrections" in tables:
        required.add("idx_task_result_corrections_task_event_desc")
    if required:
        required.add("idx_task_history_task_action_id")
    return required - indexes


def _history_scan_limit(limit):
    return min(max(limit * 10, 100), 500)


def _history_candidate_query(conn, task_id, before_event_id, scan_limit):
    """Build one bounded, indexed candidate query; each event source has a cap."""
    branches = []
    params = []
    cursor_clause = " AND h.id < ?" if before_event_id is not None else ""

    if _table_exists(conn, "worker_task_results"):
        result_sources = (
            ("result_submitted", "submission_event_id", "submitted_at",
             "idx_worker_task_results_task_submission_event", "lease_release"),
            ("result_accepted", "acceptance_event_id", "COALESCE(r.accepted_at, h.changed_at)",
             "idx_worker_task_results_task_acceptance_event", "result_acceptance"),
        )
        for event_type, event_column, timestamp, result_index, action in result_sources:
            branch = f"""
                SELECT h.id AS event_id, h.task_id AS task_id, '{event_type}' AS event_type,
                       h.new_value AS event_new_value, h.changed_at AS event_changed_at,
                       h.changed_by AS event_changed_by, {timestamp} AS source_timestamp,
                       r.id AS result_id, r.result AS result_text,
                       r.result_sha256 AS result_sha256, r.generation AS generation,
                       r.fence AS fence, r.task_version AS task_version,
                       NULL AS correction_id, NULL AS correction_round,
                       NULL AS source_result_id, NULL AS source_result_sha256,
                       NULL AS source_generation, NULL AS source_fence,
                       NULL AS source_task_version, NULL AS source_status_revision,
                       NULL AS correction_note, NULL AS request_id,
                       NULL AS policy_decision_sha256,
                       NULL AS requested_by_device_id, NULL AS requested_by_service_id, NULL AS correction_next_task_version
                FROM task_history AS h INDEXED BY idx_task_history_task_action_id
                JOIN worker_task_results AS r INDEXED BY {result_index}
                  ON r.task_id = h.task_id AND r.{event_column} = h.id
                WHERE h.task_id = ? AND h.action = ?{cursor_clause}
                ORDER BY h.id DESC LIMIT ?
            """
            branches.append(f"SELECT * FROM ({branch}) AS source_{len(branches)}")
            params.extend([task_id, action])
            if before_event_id is not None:
                params.append(before_event_id)
            params.append(scan_limit + 1)

    if _table_exists(conn, "task_result_corrections"):
        correction_columns = {item[1] for item in conn.execute(
            "PRAGMA table_info(task_result_corrections)")}
        policy_column = ("c.policy_decision_sha256" if "policy_decision_sha256" in correction_columns
                         else "NULL")
        service_actor = "c.requested_by_service_id" if "requested_by_service_id" in correction_columns else "NULL"
        branch = f"""
            SELECT h.id AS event_id, h.task_id AS task_id, 'correction_requested' AS event_type,
                   h.new_value AS event_new_value, h.changed_at AS event_changed_at,
                   h.changed_by AS event_changed_by, c.requested_at AS source_timestamp,
                   NULL AS result_id, NULL AS result_text, NULL AS result_sha256,
                   NULL AS generation, NULL AS fence, NULL AS task_version,
                   c.id AS correction_id, c.correction_round AS correction_round,
                   c.source_result_id AS source_result_id,
                   c.source_result_sha256 AS source_result_sha256,
                   c.source_generation AS source_generation, c.source_fence AS source_fence,
                   c.source_task_version AS source_task_version,
                   c.source_status_revision AS source_status_revision,
                   c.correction_note AS correction_note, c.request_id AS request_id,
                   {policy_column} AS policy_decision_sha256,
                   c.requested_by_device_id AS requested_by_device_id,
                   {service_actor} AS requested_by_service_id,
                   c.next_task_version AS correction_next_task_version
            FROM task_history AS h INDEXED BY idx_task_history_task_action_id
            LEFT JOIN task_result_corrections AS c INDEXED BY idx_task_result_corrections_task_event_desc
              ON c.task_id = h.task_id AND c.event_id = h.id
            WHERE h.task_id = ? AND h.action = ?{cursor_clause}
            ORDER BY h.id DESC LIMIT ?
        """
        branches.append(f"SELECT * FROM ({branch}) AS source_{len(branches)}")
        params.extend([task_id, "result_correction_request"])
        if before_event_id is not None:
            params.append(before_event_id)
        params.append(scan_limit + 1)

    if not branches:
        return "", [], []
    sql = "SELECT * FROM (" + " UNION ALL ".join(branches) + ") ORDER BY event_id DESC"
    return sql, params, ["result_submitted", "result_accepted", "correction_requested"]


def _canonical_history_timestamp(value, fallback):
    from .task_lease import _fmt, parse_ts

    for candidate in (value, fallback):
        parsed = parse_ts(candidate)
        if parsed is not None:
            return _fmt(parsed)
    return None


def read_result_history(conn, task_id, *, before_event_id=None, limit=20, service_id=None, service_token=None):
    if type(task_id) is not int or task_id <= 0:
        raise ResultCorrectionValidation("history_request_invalid", "task_id ist ungültig")
    if before_event_id is not None and (type(before_event_id) is not int or before_event_id <= 0):
        raise ResultCorrectionValidation("history_request_invalid", "before_event_id ist ungültig")
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ResultCorrectionValidation("history_request_invalid", "limit muss zwischen 1 und 50 liegen")
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("BEGIN")
    try:
        task = _dict_row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
        if task is None:
            raise ResultConflict("Task nicht vorhanden")
        service_context = _result_service_context(conn, service_id, service_token) if service_id is not None or service_token is not None else None
        if service_context is not None:
            latest = _dict_row(conn.execute("SELECT * FROM worker_task_results WHERE task_id=? ORDER BY id DESC LIMIT 1",
                                            (task_id,))) if _has_results(conn) else None
            if latest is None:
                legacy = _legacy_result(conn, task_id)
                if legacy is not None:
                    raise ResultServicePermissionDenied("Legacy-Ergebnis ohne vertrauenswürdige Produzentenbindung",
                                                        code="producer_binding_missing")
            _authorize_result_service(conn, service_context, task, latest, "history")
        if _history_index_gaps(conn):
            raise ResultHistoryUnavailable("Ergebnisverlauf ist mit dem aktuellen Datenbankschema nicht verfügbar")
        scan_limit = _history_scan_limit(limit)
        sql, params, source_types = _history_candidate_query(conn, task_id, before_event_id, scan_limit)
        raw_rows = []
        if sql:
            cursor = conn.execute(sql, params)
            columns = [column[0] for column in cursor.description]
            raw_rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

        grouped = {event_type: [] for event_type in source_types}
        for row in raw_rows:
            grouped.setdefault(row["event_type"], []).append(row)
        boundaries = []
        candidates = []
        for event_type in source_types:
            ordered = sorted(grouped.get(event_type, []), key=lambda row: row["event_id"], reverse=True)
            if len(ordered) > scan_limit:
                boundaries.append(ordered[scan_limit - 1]["event_id"])
                ordered = ordered[:scan_limit]
            candidates.extend(ordered)
        complete_before = max(boundaries) if boundaries else None
        if complete_before is not None:
            candidates = [row for row in candidates if row["event_id"] >= complete_before]
        candidates.sort(key=lambda row: row["event_id"], reverse=True)

        events = []
        for row in candidates:
            event_id = row.get("event_id")
            if type(event_id) is not int:
                raise ResultHistoryUnavailable("Ergebnisverlauf enthält ein unbestätigtes Ereignis")
            try:
                detail = json.loads(row.get("event_new_value") or "null")
            except (TypeError, ValueError):
                raise ResultHistoryUnavailable("Ergebnisverlauf enthält ein unbestätigtes Ereignis") from None
            if not isinstance(detail, dict):
                raise ResultHistoryUnavailable("Ergebnisverlauf enthält ein unbestätigtes Ereignis")
            occurred_at = _canonical_history_timestamp(
                row.get("source_timestamp"), row.get("event_changed_at")
            )
            if occurred_at is None:
                raise ResultHistoryUnavailable("Ergebnisverlauf enthält einen ungültigen Zeitstempel")

            if row["event_type"] in {"result_submitted", "result_accepted"}:
                result_id = row.get("result_id")
                text = row.get("result_text")
                stored_digest = row.get("result_sha256")
                if type(result_id) is not int or not isinstance(text, str):
                    raise ResultHistoryUnavailable("Ergebnisverlauf enthält ein unbestätigtes Ergebnis")
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if digest != stored_digest:
                    raise ResultHistoryUnavailable("Ergebnisverlauf enthält ein unbestätigtes Ergebnis")
                if row["event_type"] == "result_submitted":
                    if detail.get("result_ref") != f"bach-task-result:{result_id}:{digest}":
                        raise ResultHistoryUnavailable("Ergebnisverlauf enthält ein unbestätigtes Abgabeereignis")
                    events.append({"event_id": event_id, "type": "result_submitted",
                        "occurred_at": occurred_at, "result": {
                            "result_id": result_id, "result_sha256": digest, "text": text,
                            "generation": row.get("generation"), "fence": row.get("fence"),
                            "task_version": row.get("task_version")}})
                elif (detail.get("result_id") == result_id
                      and detail.get("result_sha256") == digest):
                    events.append({"event_id": event_id, "type": "result_accepted",
                        "occurred_at": occurred_at, "result": {
                            "result_id": result_id, "result_sha256": digest}})
                else:
                    raise ResultHistoryUnavailable("Ergebnisverlauf enthält ein unbestätigtes Abnahmeereignis")
            elif row["event_type"] == "correction_requested":
                if not _correction_audit_matches(conn, row, detail):
                    raise ResultHistoryUnavailable("Ergebnisverlauf enthält eine unbestätigte Korrektur")
                audit_time = _canonical_history_timestamp(row.get("event_changed_at"), None)
                events.append({"event_id": event_id, "type": "correction_requested",
                    "occurred_at": audit_time, "correction": {
                        "correction_id": row.get("correction_id"),
                        "correction_round": row.get("correction_round"),
                        "source_result_id": row.get("source_result_id"),
                        "source_result_sha256": row.get("source_result_sha256"),
                        "note": row.get("correction_note"), "request_id": row.get("request_id")}})
            else:
                raise ResultHistoryUnavailable("Ergebnisverlauf enthält einen unbekannten Ereignistyp")

        events.sort(key=lambda event: event["event_id"], reverse=True)
        if service_context is not None:
            for event in events:
                if event["type"] == "result_submitted" or event["type"] == "result_accepted":
                    result_id = event["result"]["result_id"]
                else:
                    result_id = event["correction"]["source_result_id"]
                source = _dict_row(conn.execute(
                    "SELECT * FROM worker_task_results WHERE id=? AND task_id=?", (result_id, task_id)))
                if source is None:
                    raise ResultServicePermissionDenied("Historisches Ergebnis ohne verifizierbare Produzentenbindung",
                                                        code="producer_binding_missing")
                _authorize_result_service(conn, service_context, task, source, "history")
        if complete_before is not None and len(events) <= limit:
            raise ResultHistoryUnavailable(
                "Ergebnisverlauf ist innerhalb des begrenzten Suchfensters unvollständig"
            )
        has_more = len(events) > limit
        page = events[:limit]
        next_before = page[-1]["event_id"] if has_more and page else None
        response = {"schema": "bach.task-result-history.v1", "task_id": task_id,
                    "events": page, "next_before_event_id": next_before, "has_more": has_more}
        if service_context is not None:
            response["service_revision"] = service_context["revision"]
        return response
    finally:
        if owns_transaction:
            conn.rollback()


def read_correction_context(conn, task_id, *, lease_id, fence, task_version, generation):
    """Read a correction only for the exact live task lease and result generation."""
    from .task_lease import LeaseConfig, _lease_state, _row, _utcnow, task_content_version
    if (type(task_id) is not int or task_id <= 0 or not isinstance(lease_id, str) or not lease_id
            or type(fence) is not int or fence <= 0 or not isinstance(task_version, str)
            or re.fullmatch(r"[a-f0-9]{64}", task_version) is None
            or not isinstance(generation, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", generation) is None):
        raise CorrectionContextDenied("Task-Korrekturkontext nicht bestätigt")
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("BEGIN")
    try:
        if not _task_lease_context_schema_present(conn):
            raise CorrectionContextDenied("Task-Korrekturkontext nicht bestätigt")
        task = _row(conn, task_id)
        now = _utcnow()
        state = _lease_state(task, now, LeaseConfig.from_env()) if task is not None else None
        if (task is None or state is None or state.get("live") is not True or state.get("kind") != "lease"
                or task.get("claim_id") != lease_id or task.get("claim_fence") != fence
                or task.get("status") != "in_progress" or task_content_version(task) != task_version
                or task.get("claim_task_version") != task_version
                or task.get("claim_result_generation") != generation):
            raise CorrectionContextDenied("Task-Korrekturkontext nicht bestätigt")
        correction = active_correction_request(conn, task_id)
        response = {"schema": "bach.task-result-correction-context.v1", "task_id": task_id,
                    "fence": fence, "generation": generation, "task_version": task_version,
                    "correction": None}
        if correction is None:
            return response
        source = _dict_row(conn.execute(
            "SELECT * FROM worker_task_results WHERE id=? AND task_id=?",
            (correction["source_result_id"], task_id),
        ))
        if (source is None or source.get("result_sha256") != correction["source_result_sha256"]
                or hashlib.sha256(source["result"].encode("utf-8")).hexdigest() != source["result_sha256"]):
            raise CorrectionContextDenied("Task-Korrekturkontext nicht bestätigt")
        response["correction"] = {
            "correction_id": correction["correction_id"],
            "correction_round": correction["correction_round"],
            "correction_note": correction["correction_note"],
            "source_result": {
                "result_id": source["id"], "result_sha256": source["result_sha256"],
                "text": source["result"], "generation": source["generation"],
                "fence": source["fence"], "task_version": source["task_version"],
                "submission_event_id": source["submission_event_id"],
            },
        }
        return response
    finally:
        if owns_transaction and conn.in_transaction:
            conn.rollback()


def active_correction_request(conn, task_id):
    """Return an audit-bound correction, or None only for legacy/inactive state."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
    if "result_correction_request_id" not in columns:
        return None
    task = _dict_row(conn.execute(
        "SELECT result_correction_request_id FROM tasks WHERE id=?", (task_id,)
    ))
    if task is None:
        raise CorrectionContextDenied("Task-Korrekturkontext nicht bestätigt")
    pointer = task.get("result_correction_request_id")
    if pointer is None:
        return None
    if type(pointer) is not int or pointer <= 0:
        raise CorrectionContextDenied("Task-Korrekturkontext nicht bestätigt")
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_result_corrections'"
    ).fetchone():
        raise CorrectionContextDenied("Task-Korrekturkontext nicht bestätigt")
    request = _dict_row(conn.execute(
        "SELECT * FROM task_result_corrections WHERE id=? AND task_id=?", (pointer, task_id)
    ))
    if request is None or request.get("id") != pointer or request.get("task_id") != task_id:
        raise CorrectionContextDenied("Task-Korrekturkontext nicht bestätigt")
    event_id = request.get("event_id")
    if type(event_id) is not int or event_id <= 0:
        raise CorrectionContextDenied("Task-Korrekturkontext nicht bestätigt")
    audit = _dict_row(conn.execute(
        "SELECT id,new_value,changed_by,changed_at FROM task_history "
        "WHERE id=? AND task_id=? AND action='result_correction_request'",
        (event_id, task_id),
    ))
    if audit is None:
        raise CorrectionContextDenied("Task-Korrekturkontext nicht bestätigt")
    try:
        detail = json.loads(audit.get("new_value") or "null")
    except (TypeError, ValueError):
        raise CorrectionContextDenied("Task-Korrekturkontext nicht bestätigt") from None
    audit_row = {
        "correction_id": request.get("id"),
        "event_id": event_id,
        "task_id": task_id,
        "correction_round": request.get("correction_round"),
        "source_result_id": request.get("source_result_id"),
        "source_result_sha256": request.get("source_result_sha256"),
        "source_generation": request.get("source_generation"),
        "source_fence": request.get("source_fence"),
        "source_task_version": request.get("source_task_version"),
        "source_status_revision": request.get("source_status_revision"),
        "correction_note": request.get("correction_note"),
        "request_id": request.get("request_id"),
        "requested_by_device_id": request.get("requested_by_device_id"),
        "policy_decision_sha256": request.get("policy_decision_sha256"),
        "requested_by_service_id": request.get("requested_by_service_id"),
        "source_timestamp": request.get("requested_at"),
        "event_changed_at": audit.get("changed_at"),
        "event_changed_by": audit.get("changed_by"),
        "correction_next_task_version": request.get("next_task_version"),
    }
    if not _correction_audit_matches(conn, audit_row, detail):
        raise CorrectionContextDenied("Task-Korrekturkontext nicht bestätigt")
    if not _has_results(conn):
        raise CorrectionContextDenied("Task-Korrekturkontext nicht bestätigt")
    source = _dict_row(conn.execute(
        "SELECT * FROM worker_task_results WHERE id=? AND task_id=?",
        (request["source_result_id"], task_id),
    ))
    if (source is None or not isinstance(source.get("result"), str)
            or source.get("result_sha256") != request.get("source_result_sha256")
            or hashlib.sha256(source["result"].encode("utf-8")).hexdigest() != source.get("result_sha256")
            or source.get("generation") != request.get("source_generation")
            or source.get("fence") != request.get("source_fence")
            or source.get("task_version") != request.get("source_task_version")):
        raise CorrectionContextDenied("Task-Korrekturkontext nicht bestätigt")
    latest = _dict_row(conn.execute(
        "SELECT id FROM worker_task_results WHERE task_id=? ORDER BY id DESC LIMIT 1", (task_id,)
    ))
    if latest is None or type(latest.get("id")) is not int or latest["id"] < request["source_result_id"]:
        raise CorrectionContextDenied("Task-Korrekturkontext nicht bestätigt")
    if latest["id"] > request["source_result_id"]:
        return None
    return {
        "correction_id": request["id"],
        "correction_round": request["correction_round"],
        "source_result_id": request["source_result_id"],
        "source_result_sha256": request["source_result_sha256"],
        "correction_note": request["correction_note"],
        "request_id": request["request_id"],
    }


class _Acceptance:
    def __init__(self, conn, record):
        self.conn, self.task_id, self.result_id, self.digest = (
            conn, record["task_id"], record["result_id"], record["result_sha256"])


class _PolicyAcceptance(_Acceptance):
    def __init__(self, conn, record, *, result_revision, decision_sha256, decision_event_id):
        super().__init__(conn, record)
        self.result_revision = result_revision
        self.decision_sha256 = decision_sha256
        self.decision_event_id = decision_event_id


def _has_worker_result_release(conn, task_id):
    """Keep a lost result row from downgrading a native submission to manual Done."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_history'").fetchone() is None:
        return False
    return conn.execute("SELECT 1 FROM task_history WHERE task_id=? "
        "AND action='lease_release' AND instr(new_value,'bach-task-result:')>0 LIMIT 1",
        (task_id,)).fetchone() is not None


def assert_completion_allowed(conn, task_id, acceptance=None, *, changes=None):
    """Shared write choke point; a model's status alias grants no acceptance."""
    current = _dict_row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
    if current and current.get("claim_id") and current.get("claim_result_generation"):
        raise ResultConflict("Native Workergeneration benötigt Ergebnisabgabe und getrennte Abnahme")
    # A predeclared task gate is meaningful even before the first worker result.
    # Missing result storage must not turn such a task into an ordinary manual Done.
    gated = bool(current and (
        current.get("require_user_review") not in (None, 0)
        or current.get("github_pr_review_required") not in (None, 0)
        or current.get("completion_contract_json") is not None
        or current.get("github_review_contract_json") is not None))
    if not _has_results(conn):
        if gated or _has_worker_result_release(conn, task_id):
            raise ResultConflict("Vorab festgelegter Abschlussvertrag benötigt ein gültiges Worker-Ergebnis")
        return
    observed = read_result(conn, task_id)
    record = observed["result"]
    if not record or record.get("result_id") is None:
        if gated or _has_worker_result_release(conn, task_id):
            raise ResultConflict("Vorab festgelegter Abschlussvertrag benötigt ein gültiges Worker-Ergebnis")
        return
    marker = record.get("completion_policy_version", 0)
    if type(marker) is not int or marker not in (0, 1):
        raise ResultConflict("Unbekannte Abschlussvertragsversion")
    if record.get("submission", {}).get("availability") not in {"available", "legacy_release_only"}:
        raise ResultConflict("Submission-Beleg ist nicht gültig")
    from .task_lease import task_content_version
    if task_content_version({**current, **(changes or {})}) != record.get("task_version"):
        raise ResultConflict("Geänderter Auftrag benötigt eine neue Ergebnisabgabe und Abnahme")
    if marker == 1:
        if (type(acceptance) is _PolicyAcceptance and acceptance.conn is conn
                and conn.in_transaction and acceptance.task_id == task_id
                and acceptance.result_id == record["result_id"]
                and acceptance.digest == record["result_sha256"]
                and re.fullmatch(r"[a-f0-9]{64}", acceptance.result_revision or "")
                and re.fullmatch(r"[a-f0-9]{64}", acceptance.decision_sha256 or "")
                and type(acceptance.decision_event_id) is int):
            event = _dict_row(conn.execute("SELECT * FROM task_history WHERE id=? AND task_id=?",
                                           (acceptance.decision_event_id, task_id)))
            if event and event["action"] == "worker_completion_decision" and event["field_changed"] == "lease":
                try:
                    detail = json.loads(event["new_value"])
                    from .worker_completion_policy import _digest
                    if (detail.get("receipt_sha256") == acceptance.decision_sha256
                            and _digest({key: value for key, value in detail.items()
                                         if key != "receipt_sha256"}) == acceptance.decision_sha256
                            and detail.get("result_revision") == acceptance.result_revision
                            and detail.get("result_id") == record["result_id"]
                            and detail.get("decision", {}).get("completion_allowed") is True):
                        return
                except (TypeError, ValueError, AttributeError):
                    pass
        # Performed review work has its own validated reserved child intent.
        # This permission never applies to its parent or an ordinary worker.
        from .worker_result_review import review_task_metadata
        if (type(acceptance) is _Acceptance and acceptance.conn is conn
                and conn.in_transaction and acceptance.task_id == task_id
                and acceptance.result_id == record["result_id"]
                and acceptance.digest == record["result_sha256"]
                and review_task_metadata(conn, task_id) is not None):
            return
        raise ResultConflict("Policyverwalteter Abschluss benötigt aktuelle geprüfte Entscheidung")
    if record.get("accepted") is True:
        return
    if (isinstance(acceptance, _Acceptance) and acceptance.conn is conn
            and conn.in_transaction and acceptance.task_id == task_id
            and acceptance.result_id == record["result_id"] and acceptance.digest == record["result_sha256"]):
        return
    raise ResultConflict("Worker-Ergebnis braucht eine getrennte Abnahme des aktuellen Inhalts")


def accept_result(conn, task_id, result_id, *, digest, task_version, status_revision,
                  operator_token=None, result_revision=None, task_contract_met=None,
                  repo_root=None, worktrees_dir=None, github_observer=None,
                  service_id=None, service_token=None, service_revision=None):
    """Accept the exact current result as an operator or scoped service transaction.

    Policy-bound results (completion_policy_version 1) are accepted only through
    the authenticated operator review; the scoped service contract has no such path.
    """
    if (type(result_id) is not int or result_id <= 0 or type(status_revision) is not int
            or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
            or not isinstance(task_version, str) or not re.fullmatch(r"[a-f0-9]{64}", task_version)):
        raise ResultConflict("Ungültige Ergebnisabnahme")
    service_mode = service_id is not None or service_token is not None
    # Both credential kinds are ambiguous (as in read_result); no credential at all
    # stays a personal-operator denial (ResultPermissionDenied) on the operator path.
    if service_mode and operator_token is not None:
        raise ResultServicePermissionDenied("Genau eine Ergebnisanmeldung erforderlich", code="ambiguous_credentials")
    if conn.in_transaction:
        raise ResultConflict("Abnahme benötigt eine eigene kanonische Transaktion")
    service_precheck = None
    service_provenance = None
    if service_mode:
        if type(service_revision) is not int or service_revision <= 0:
            raise ResultServiceConflict("service_revision_required", "Service-Scope-Version muss bestätigt werden")
        service_precheck = _result_service_context(conn, service_id, service_token, expected_revision=service_revision)
        if not _result_service_schema_present(conn):
            raise ResultServiceUnavailable("Ergebnisreview-Schema ist nicht verfügbar")
        pre_task = _dict_row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
        if pre_task is None:
            raise ResultConflict("Task nicht vorhanden")
        pre_result = _dict_row(conn.execute("SELECT * FROM worker_task_results WHERE id=? AND task_id=?",
                                            (result_id, task_id)))
        if pre_result is None:
            raise ResultConflict("Ergebnis hat sich seit dem Lesen verändert")
        _, _, service_provenance = _authorize_result_service(
            conn, service_precheck, pre_task, pre_result, "accept")
    existing = read_result(conn, task_id).get("result")
    if isinstance(existing, dict) and existing.get("completion_policy_version") == 1:
        if service_mode:
            # The completion policy records an authenticated operator review
            # before Done; the scoped service contract has no such decision path.
            raise ResultServicePermissionDenied(
                "Policyverwalteter Abschluss benötigt die Operator-Prüfung",
                code="completion_policy_operator_review_required")
        from .worker_completion_policy import record_operator_review, evaluate_current_result
        from .worker_scope_evidence import project_scope_evidence
        record_operator_review(conn, task_id, result_id, digest=digest,
            task_version=task_version, status_revision=status_revision,
            result_revision=result_revision, task_contract_met=task_contract_met,
            operator_token=operator_token, repo_root=repo_root,
            worktrees_dir=worktrees_dir, github_observer=github_observer)
        data = project_scope_evidence(read_result(conn, task_id, operator_token=operator_token),
            repo_root=repo_root, worktrees_dir=worktrees_dir)
        data["completion_evaluation"] = evaluate_current_result(conn, task_id,
            repo_root=repo_root, worktrees_dir=worktrees_dir,
            github_observer=github_observer)
        return data
    if isinstance(existing, dict) and existing.get("completion_policy_version") not in (None, 0):
        raise ResultConflict("Unbekannte Abschlussvertragsversion")
    conn.execute("BEGIN IMMEDIATE")
    try:
        service_context = None
        if service_mode:
            service_context = _result_service_context(conn, service_id, service_token, expected_revision=service_revision)
            if (service_context["service_id"] != service_precheck["service_id"]
                    or service_context["revision"] != service_precheck["revision"]
                    or not _result_service_schema_present(conn)):
                raise ResultServiceUnavailable("Service-Scope oder Ergebnisreview-Schema hat sich geändert")
            principal_id = service_context["service_id"]
            actor = f"operator-service:{principal_id}"
        else:
            # Existing personal-operator semantics stay separate from the service contract.
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
            principal_id = principal[0]
            actor = f"operator-device:{principal_id}"

        from .task_lease import _history, _utcnow, _local_naive
        from hub.task_audit import apply_task_field_changes
        observed = read_result(conn, task_id)
        record = observed["result"]
        row = _dict_row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
        if service_mode:
            if row is None:
                raise ResultConflict("Task nicht vorhanden")
            _, _, service_provenance = _authorize_result_service(
                conn, service_context, row, _dict_row(conn.execute(
                    "SELECT * FROM worker_task_results WHERE id=? AND task_id=?", (result_id, task_id))), "accept")
        if (not record or record.get("result_id") != result_id or record.get("result_sha256") != digest
                or observed["task_version"] != task_version or observed["status_revision"] != status_revision
                or record.get("task_version") != task_version or record.get("reason") != "awaiting_review"):
            raise ResultConflict("Ergebnis oder Auftrag seit dem Lesen verändert; neu laden")
        if row is None:
            raise ResultConflict("Task nicht vorhanden")
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
        if service_mode:
            target = _result_service_target(row, {"result_id": result_id, "result_sha256": digest,
                "generation": record.get("generation"), "fence": record.get("fence"),
                "task_version": record.get("task_version")})
            _result_service_audit(conn, context=service_context, action="accept", target=target,
                status_revision=status_revision, provenance=service_provenance,
                now=_local_naive(now), event_id=acceptance_event)
        if service_mode:
            result = {
                "schema": "bach.task-result-service-acceptance.v1",
                "task_id": task_id,
                "result_id": result_id,
                "result_sha256": digest,
                "task_version": task_version,
                "source_status_revision": status_revision,
                "accepted_status_revision": revision,
                "acceptance_event_id": acceptance_event,
                "accepted": True,
                "service_revision": service_context["revision"],
            }
        else:
            result = read_result(conn, task_id)
            if result["result"].get("accepted") is not True:
                raise ResultConflict("Kanonische Ergebnisabnahme nicht bestätigt")
        conn.commit()
        return result
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
