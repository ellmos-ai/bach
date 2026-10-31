# SPDX-License-Identifier: MIT
"""Private, result-bound model review using the existing native task queue.

The intent is task metadata, not a second scheduler. A model response supplies
only a verdict; task, revision, reviewer identity and independence are derived
from controller-bound receipts. Public/read paths never create tables.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone

from . import worker_policy_settings as settings
from .limits import limit
from . import worker_review_identity as identity
from .task_lease import _history, _local_naive, _utcnow, task_content_version
from .task_result_service import read_result
from .worker_execution_evidence import (_digest as execution_digest, _event as execution_event,
                                        _owned as owned_execution, _submitted)
from .worker_scope_evidence import project_scope_evidence
from .worker_result_provenance import author_principal, author_slot, source_kind, source_pin

_SEAL = object()
_ACTOR = "native-result-review-controller"
_INTENT_SCHEMA = "bach.worker-result-review-intent.v1"
_REVIEW_SCHEMA = "bach.worker-result-model-review.v1"
_EXTERNAL_INTENT_SCHEMA = "bach.worker-result-review-intent.external-attested.v1"
_EXTERNAL_REVIEW_SCHEMA = "bach.worker-result-model-review.external-attested.v1"
_INVALID_SCHEMA = "bach.worker-review-invalid-result.v1"
_OBSOLETE_SCHEMA = "bach.worker-review-obsolete-child.v1"
_READ_SCHEMA = "bach.worker-result-review-evidence.v1"
_HEX = re.compile(r"[a-f0-9]{64}\Z")
_SUBMISSION_REVISION = re.compile(r"sha256:[a-f0-9]{64}\Z")
_SOURCE = "worker-result-review:v1:"


class ReviewGrant:
    """One process-private permission to run a particular review task."""

    __slots__ = ("_seal", "task_id", "task_version", "target_task_id", "target_result_id",
                 "target_revision", "worker_id", "host", "generation", "slot_id", "route",
                 "requested_model", "principal_id", "policy_version", "identity_version",
                 "_is_current", "_stop_event", "_last_answer", "_last_answer_sha256")

    def __init__(self, *, _seal=None, **values):
        if _seal is not _SEAL:
            raise ValueError("Private review grant required")
        self._seal = _seal
        for name, value in values.items():
            setattr(self, name, value)
        self._last_answer = None
        self._last_answer_sha256 = None

    def __repr__(self):
        return "<ReviewGrant private>"

    def __reduce__(self):
        raise TypeError("ReviewGrant cannot be serialized")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _row(cursor):
    row = cursor.fetchone()
    return dict(zip((column[0] for column in cursor.description), row)) if row is not None else None


def _table(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (name,)).fetchone() is not None


def _ensure_schema(conn):
    if not conn.in_transaction:
        raise RuntimeError("Review-Schema benötigt einen Writer")
    conn.execute("""CREATE TABLE IF NOT EXISTS worker_result_review_intents (
        review_task_id INTEGER PRIMARY KEY, target_task_id INTEGER NOT NULL,
        target_result_id INTEGER NOT NULL, target_revision TEXT NOT NULL,
        intent TEXT NOT NULL, intent_sha256 TEXT NOT NULL, event_id INTEGER NOT NULL,
        UNIQUE(target_result_id,target_revision))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_worker_review_target "
                 "ON worker_result_review_intents(target_task_id,target_result_id)")
    conn.execute("""CREATE TABLE IF NOT EXISTS worker_result_model_reviews (
        review_task_id INTEGER PRIMARY KEY, target_task_id INTEGER NOT NULL,
        target_result_id INTEGER NOT NULL, target_revision TEXT NOT NULL,
        child_result_id INTEGER NOT NULL UNIQUE, receipt TEXT NOT NULL,
        receipt_sha256 TEXT NOT NULL, event_id INTEGER NOT NULL,
        UNIQUE(target_result_id,target_revision))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS worker_result_review_pages (
        receipt_sha256 TEXT NOT NULL, target_result_id INTEGER NOT NULL,
        target_revision TEXT NOT NULL, diff_sha256 TEXT NOT NULL,
        page_no INTEGER NOT NULL, page_sha256 TEXT NOT NULL,
        created_at TEXT NOT NULL, UNIQUE(target_result_id,target_revision,page_no))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_worker_review_pages_receipt "
                 "ON worker_result_review_pages(receipt_sha256)")


def _policy_snapshot(conn, task_id):
    original_factory = conn.row_factory
    try:
        conn.row_factory = sqlite3.Row
        return settings._task_snapshot(conn, task_id)
    finally:
        conn.row_factory = original_factory


def _identity_snapshot(conn):
    return identity.identity_snapshot(conn)


def _route(value):
    if (type(value) is not dict or set(value) != {"backend_id", "route_sha256"}
            or type(value["backend_id"]) is not str
            or value["backend_id"] not in identity.BACKENDS
            or type(value["route_sha256"]) is not str
            or not _HEX.fullmatch(value["route_sha256"])):
        return None
    return dict(value)


def _policy_eligible(policy, author_id, *, exclude_author=True):
    """Select a configured reviewer; never infer a completion verdict here."""
    if (not isinstance(policy, dict) or policy.get("availability") != "available"
            or not isinstance(author_id, str)):
        return ()
    try:
        typed = settings.validate_policy(policy["policy"])
        override = settings.validate_override(policy["override"])
    except (ValueError, TypeError, KeyError, settings.PolicyUnavailable):
        return ()
    if (override.allow_review_task_pickup is False
            or (override.allow_review_task_pickup is None
                and not typed.allow_review_task_pickup)):
        return ()
    kernel = settings._kernel()
    mode = override.mode or typed.default_mode
    return tuple(reviewer.reviewer_id for reviewer in typed.reviewers
                 if (not exclude_author or reviewer.reviewer_id != author_id)
                 and (mode is not kernel.CompletionMode.HIGH_SECURITY
                      or reviewer.tier is kernel.ReviewerTier.TOP))


def _author_model_blocked(authority, principal):
    # The fresh run is the fixed independence unit; the author's model is only
    # excluded when the operator explicitly configured that rule.
    return authority["exclude_author_model"] and principal == authority["author_id"]


def _target_record(conn, task_id, *, repo_root=None, worktrees_dir=None):
    """Fresh Git projection strictly outside a SQLite transaction."""
    if conn.in_transaction:
        return None
    try:
        task = _row(conn.execute("SELECT claim_id FROM tasks WHERE id=?", (task_id,)))
        if task is None or task.get("claim_id"):
            return None
        projected = project_scope_evidence(
            read_result(conn, task_id), repo_root=repo_root, worktrees_dir=worktrees_dir)
        record = projected.get("result")
        if (projected.get("status") != "review" or not isinstance(record, dict)
                or record.get("reason") != "awaiting_review"
                or record.get("submission", {}).get("availability") != "available"
                or source_pin(record) is None
                or (source_kind(record) == "native" and
                    (type(author_slot(record)) is not str or not author_slot(record)))
                or record.get("scope", {}).get("availability") != "available"
                or type(record.get("submission_revision")) is not str
                or not _SUBMISSION_REVISION.fullmatch(record["submission_revision"])
                or not isinstance(record.get("result_revision"), str)
                or not _HEX.fullmatch(record["result_revision"])):
            return None
        return record
    except (sqlite3.Error, ValueError, TypeError, KeyError, settings.PolicyUnavailable):
        return None


def _target_authority(conn, record):
    """Read current config and resolve a real linked author, no Git or DDL."""
    try:
        policy = record["submission"]["policy"]
        current = _policy_snapshot(conn, record["task_id"])
        model_ids = _identity_snapshot(conn)
        author = author_principal(model_ids, record)
        exclude_author = settings.exclude_author_model(conn)
        eligible = (_policy_eligible(policy, author, exclude_author=exclude_author)
                    if author is not None else ())
        if (policy.get("availability") != "available" or author is None
                or policy.get("configuration_version") != current["configuration_version"]
                or policy.get("policy") != settings._global(conn)["policy"]
                or policy.get("override") != current["override"]
                or not eligible):
            return None
        return {"author_id": author, "policy_version": current["configuration_version"],
                "identity_version": model_ids["configuration_version"],
                "identity": model_ids, "eligible": eligible,
                "exclude_author_model": exclude_author}
    except (sqlite3.Error, ValueError, TypeError, KeyError, settings.PolicyUnavailable):
        return None


def _same_target_db(conn, record, authority):
    """Recheck the canonical rows and settings under the caller's writer."""
    try:
        current = read_result(conn, record["task_id"])
        observed = current["result"]
        task = _row(conn.execute("SELECT claim_id FROM tasks WHERE id=?", (record["task_id"],)))
        if (task is None or task.get("claim_id")
                or current["status"] != "review" or not isinstance(observed, dict)
                or observed.get("reason") != "awaiting_review"
                or observed.get("submission", {}).get("availability") != "available"):
            return False
        fields = ("result_id", "task_id", "fence", "generation", "task_version",
                  "result_sha256", "submission_revision", "submission_event_id",
                  "status_revision", "submitted_status_event_id")
        if any(observed.get(key) != record.get(key) for key in fields):
            return False
        if source_pin(observed) is None or source_pin(observed) != source_pin(record):
            return False
        resolved = _target_authority(conn, observed)
        return bool(resolved and all(resolved[key] == authority[key]
                                     for key in ("author_id", "policy_version",
                                                 "identity_version", "eligible")))
    except (sqlite3.Error, ValueError, TypeError, KeyError):
        return False


def _intent_author_fields(target):
    if source_kind(target) == "external_attested":
        return {"author_source": source_pin(target)}
    return {"execution_revision": target["execution"]["execution_revision"],
            "scope_receipt_sha256": target["scope"]["scope_receipt_sha256"],
            "author_execution_id": target["execution"]["execution_id"],
            "author_slot_id": author_slot(target)}


def _external_pin_valid(pin):
    return (isinstance(pin, dict) and set(pin) == {"source_kind", "attestation_sha256",
        "attestation_event_id", "scope_receipt_sha256", "scope_event_id", "model_principal_id"}
        and pin["source_kind"] == "external_attested"
        and all(type(pin[key]) is str and _HEX.fullmatch(pin[key]) for key in (
            "attestation_sha256", "scope_receipt_sha256"))
        and type(pin["attestation_event_id"]) is int and type(pin["scope_event_id"]) is int
        and 0 < pin["attestation_event_id"] < pin["scope_event_id"]
        and type(pin["model_principal_id"]) is str and bool(pin["model_principal_id"]))


def _intent_source_valid(receipt):
    if receipt.get("schema") == _EXTERNAL_INTENT_SCHEMA:
        return (_external_pin_valid(receipt.get("author_source"))
                and receipt["author_source"]["model_principal_id"] == receipt.get("author_id"))
    return (receipt.get("schema") == _INTENT_SCHEMA
        and all(type(receipt.get(key)) is str and _HEX.fullmatch(receipt[key]) for key in (
            "execution_revision", "scope_receipt_sha256"))
        and all(type(receipt.get(key)) is str and receipt[key] for key in (
            "author_execution_id", "author_slot_id")))


def _intent_source_matches(receipt, target):
    expected_schema = _EXTERNAL_INTENT_SCHEMA if source_kind(target) == "external_attested" else _INTENT_SCHEMA
    fields = _intent_author_fields(target) if source_pin(target) is not None else None
    return (fields is not None and receipt.get("schema") == expected_schema
            and _intent_source_valid(receipt)
            and all(receipt.get(key) == value for key, value in fields.items()))


def _intent_same_author(receipt, target):
    """Stable author match for proven scope drift, never review acceptance.

    A valid new native scope receipt can obsolete the old review intent.
    Requiring that old scope hash here would hide the very revision drift
    this recovery path must detect. Normal dispatch/submit still requires
    the complete source match.
    """
    if source_kind(target) != "native":
        return _intent_source_matches(receipt, target)
    return (source_pin(target) is not None and receipt.get("schema") == _INTENT_SCHEMA
            and _intent_source_valid(receipt)
            and all(receipt.get(key) == value for key, value in _intent_author_fields(target).items()
                    if key != "scope_receipt_sha256"))


def _review_author_fields(target):
    if source_kind(target) == "external_attested":
        return {"author_source": source_pin(target)}
    return {"author_execution_id": target["execution"]["execution_id"],
            "author_slot_id": author_slot(target)}


def _review_source_matches(receipt, target):
    expected_schema = _EXTERNAL_REVIEW_SCHEMA if source_kind(target) == "external_attested" else _REVIEW_SCHEMA
    if receipt.get("schema") != expected_schema or source_pin(target) is None:
        return False
    if source_kind(target) == "external_attested" and not _external_pin_valid(receipt.get("author_source")):
        return False
    return all(receipt.get(key) == value for key, value in _review_author_fields(target).items())


def _intent_scope_sha(receipt):
    return (receipt.get("author_source", {}).get("scope_receipt_sha256")
            if receipt.get("schema") == _EXTERNAL_INTENT_SCHEMA else receipt.get("scope_receipt_sha256"))


def _intent(conn, review_task_id):
    if (type(review_task_id) is not int or review_task_id <= 0
            or not _table(conn, "worker_result_review_intents")):
        return None
    row = _row(conn.execute("SELECT * FROM worker_result_review_intents WHERE review_task_id=?",
                            (review_task_id,)))
    if row is None:
        return None
    try:
        receipt = json.loads(row["intent"])
        event = _row(conn.execute("SELECT task_id,action,field_changed,new_value,changed_by "
                                  "FROM task_history WHERE id=?", (row["event_id"],)))
        task = _row(conn.execute("SELECT * FROM tasks WHERE id=?", (review_task_id,)))
        if (type(row["event_id"]) is not int or row["event_id"] <= 0
                or type(row["target_task_id"]) is not int or row["target_task_id"] <= 0
                or type(row["target_result_id"]) is not int or row["target_result_id"] <= 0
                or not isinstance(receipt, dict) or not _intent_source_valid(receipt)
                or set(receipt) not in ({"schema", "review_task_id", "target_task_id",
                                         "target_result_id", "target_revision",
                                         "submission_revision", "author_generation", "author_id",
                                         "policy_version", "identity_version"}
                                        | ({"author_source"} if receipt.get("schema") == _EXTERNAL_INTENT_SCHEMA
                                           else {"execution_revision", "scope_receipt_sha256",
                                                 "author_execution_id", "author_slot_id"}),
                                        {"schema", "review_task_id", "target_task_id",
                                         "target_result_id", "target_revision",
                                         "submission_revision", "author_generation", "author_id",
                                         "policy_version", "identity_version",
                                         "diff_chars", "diff_truncated", "diff_sha256"}
                                        | ({"author_source"} if receipt.get("schema") == _EXTERNAL_INTENT_SCHEMA
                                           else {"execution_revision", "scope_receipt_sha256",
                                                 "author_execution_id", "author_slot_id"}))
                or _digest(receipt) != row["intent_sha256"]
                or receipt.get("review_task_id") != review_task_id
                or receipt.get("target_task_id") != row["target_task_id"]
                or receipt.get("target_result_id") != row["target_result_id"]
                or receipt.get("target_revision") != row["target_revision"]
                or not _HEX.fullmatch(row["target_revision"])
                or type(receipt["submission_revision"]) is not str
                or not _SUBMISSION_REVISION.fullmatch(receipt["submission_revision"])
                or any(type(receipt[key]) is not str or not _HEX.fullmatch(receipt[key])
                       for key in ("policy_version", "identity_version"))
                or any(type(receipt[key]) is not str or not receipt[key]
                       for key in ("author_generation", "author_id"))
                or task is None or task.get("source") != _SOURCE + str(review_task_id)
                or task.get("depends_on") not in (None, "")
                or event is None or event["task_id"] != row["target_task_id"]
                or event["action"] != "worker_result_review_task"
                or event["field_changed"] != "lease"
                or event["changed_by"] != _ACTOR
                or json.loads(event["new_value"]) != {
                    "intent_sha256": row["intent_sha256"], "review_task_id": review_task_id,
                    "target_result_id": row["target_result_id"],
                    "target_revision": row["target_revision"]}):
            return None
        return {"row": row, "receipt": receipt, "task": task}
    except (ValueError, TypeError, KeyError, sqlite3.Error):
        return None


def review_task_metadata(conn, task_id):
    """Read-only validated task/intent projection; missing old schema is empty."""
    found = _intent(conn, task_id)
    if found is None:
        return None
    receipt = found["receipt"]
    return {"schema": receipt["schema"], "review_task_id": task_id,
            "task_version": task_content_version(found["task"]),
            "status": found["task"]["status"],
            "target_task_id": receipt["target_task_id"],
            "target_result_id": receipt["target_result_id"],
            "target_revision": receipt["target_revision"],
            "author_id": receipt["author_id"]}


def review_task_marker(conn, task_id):
    """Deny ordinary pickup for even a damaged reserved review task."""
    if type(task_id) is not int or task_id <= 0:
        return False
    try:
        if (_table(conn, "worker_result_review_intents")
                and conn.execute("SELECT 1 FROM worker_result_review_intents WHERE review_task_id=?",
                                 (task_id,)).fetchone() is not None):
            return True
        row = _row(conn.execute("SELECT source FROM tasks WHERE id=?", (task_id,)))
        if row is None:
            return False
        return isinstance(row.get("source"), str) and row["source"].startswith(_SOURCE)
    except sqlite3.Error:
        return False


def list_review_candidates(conn, limit=100, offset=0):
    """A filtered view of normal pending tasks, never a second queue."""
    if (type(limit) is not int or not 1 <= limit <= 100
            or type(offset) is not int or offset < 0):
        raise ValueError("Ungültige Review-Taskseite")
    if not _table(conn, "worker_result_review_intents"):
        return []
    cursor = conn.execute("SELECT t.* FROM tasks t JOIN worker_result_review_intents i "
                          "ON i.review_task_id=t.id WHERE t.status IN ('pending','open') "
                          "ORDER BY t.created_at DESC,t.id DESC LIMIT ? OFFSET ?", (limit, offset))
    names = [column[0] for column in cursor.description]
    result = []
    for values in cursor.fetchall():
        task = dict(zip(names, values))
        meta = review_task_metadata(conn, task["id"])
        if meta is not None:
            result.append({**task, "task_version": meta["task_version"],
                           "review_intent": meta})
    return result


def prepare_review_task(conn, binding, *, repo_root=None, worktrees_dir=None,
                         diff_chars=0, diff_truncated=False, diff_sha256=""):
    """Create one ordinary pending review task after a real author submission."""
    if conn.in_transaction or getattr(getattr(binding, "_client", None), "mode", None) != "local":
        return None
    try:
        author_record = _submitted(conn, binding)
        if author_record is None or review_task_marker(conn, binding.task_id):
            return None
        target = _target_record(conn, binding.task_id, repo_root=repo_root,
                                worktrees_dir=worktrees_dir)
        if (target is None or author_record["result_id"] != target["result_id"]
                or source_kind(target) != "native"):
            return None
        authority = _target_authority(conn, target)
        if authority is None:
            return None
        return _prepare_target_review(conn, target, authority,
                                       diff_chars=diff_chars, diff_truncated=diff_truncated,
                                       diff_sha256=diff_sha256)
    except (sqlite3.Error, ValueError, TypeError, KeyError, RuntimeError,
            settings.PolicyUnavailable):
        return None


def validate_external_review_target(payload):
    """Pin the exact public revision the operator selected, never latest-wins."""
    fields = {"task_id", "result_id", "result_sha256", "result_revision", "task_version", "status_revision"}
    settings._object(payload, fields)
    for key in ("task_id", "result_id", "status_revision"):
        if type(payload[key]) is not int or payload[key] <= 0:
            raise ValueError("Positive Reviewziel-Kennung erforderlich")
    for key in ("result_sha256", "result_revision", "task_version"):
        if type(payload[key]) is not str or not _HEX.fullmatch(payload[key]):
            raise ValueError("Vollständige Reviewziel-Revision erforderlich")
    return dict(payload)


def prepare_external_review_task(conn, task_id, *, operator_token, expected=None,
                                 repo_root=None, worktrees_dir=None,
                                 diff_chars=0, diff_truncated=False, diff_sha256=""):
    """Explicit enrolled-operator entry after a verified external attestation."""
    if conn.in_transaction:
        raise ValueError("Externe Reviewanlage benötigt eine freie DB-Verbindung")
    if expected is not None:
        expected = validate_external_review_target(expected)
    conn.execute("BEGIN")
    try:
        identity.require_operator(conn, operator_token)
        if review_task_marker(conn, task_id):
            return None
    finally:
        conn.rollback()
    target = _target_record(conn, task_id, repo_root=repo_root, worktrees_dir=worktrees_dir)
    if target is None or source_kind(target) != "external_attested":
        return None
    if expected is not None and any(target.get(key) != value for key, value in expected.items()):
        raise settings.PolicyConflict("Das ausgewählte externe Reviewziel wurde geändert")
    authority = _target_authority(conn, target)
    if authority is None:
        return None
    return _prepare_target_review(conn, target, authority, operator_token=operator_token,
                                  diff_chars=diff_chars, diff_truncated=diff_truncated,
                                  diff_sha256=diff_sha256)


def _prepare_target_review(conn, target, authority, *, operator_token=None,
                            diff_chars=0, diff_truncated=False, diff_sha256=""):
    """One ordinary review task for either proven source; DB CAS only here."""
    if conn.in_transaction:
        raise ValueError("Reviewanlage benötigt eine freie DB-Verbindung")
    if (type(diff_chars) is not int or diff_chars < 0
            or type(diff_truncated) is not bool
            or (diff_sha256 != "" and not _HEX.fullmatch(diff_sha256))
            or (diff_truncated and (diff_chars <= 0 or diff_sha256 == ""))):
        raise ValueError("Unvollständige Review-Diff-Metadaten")
    conn.execute("BEGIN IMMEDIATE")
    try:
        if source_kind(target) == "external_attested":
            identity.require_operator(conn, operator_token)
        try:
            if not _same_target_db(conn, target, authority):
                conn.rollback()
                return None
            _ensure_schema(conn)
            old = _row(conn.execute("SELECT review_task_id FROM worker_result_review_intents "
                                    "WHERE target_result_id=? AND target_revision=?",
                                    (target["result_id"], target["result_revision"])))
            if old is not None:
                result = review_task_metadata(conn, old["review_task_id"])
                conn.commit()
                return result
            now = _utcnow()
            stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            chunk = max(1, limit("BACH_MAX_CONTEXT_CHARS"))
            max_diff_chars = limit("BACH_CONTEXT_LIMIT") * 3
            paging_required = bool(diff_truncated
                                   or diff_chars > max(0, max_diff_chars - chunk))
            page_count = max(1, (int(diff_chars) + chunk - 1) // chunk)
            if paging_required:
                description = ("Controllergebundenes Ergebnisreview; Ziel nur aus privatem Intent lesen. "
                               f"Diff zu lang für ein Slot-Fenster: hole Diff-Seiten via Reviewer-Tool "
                               f"(page_count={page_count}, diff_sha256={diff_sha256}) und fordere im "
                               "Verdict diff_pages: je Seite {\"page\": i, \"sha256\": HEX64}, "
                               "Seitennummern strikt aufsteigend, jedes sha256 HEX64, einmalig.")
            else:
                description = ("Controllergebundenes Ergebnisreview; Ziel nur aus privatem Intent lesen. "
                               f"Voller Diff ({int(diff_chars)} Zeichen) liegt im Slot-Fenster; "
                               "kein Seitenabruf nötig.")
            title = f"Ergebnisreview Task #{target['task_id']} / Result #{target['result_id']}"
            source = _SOURCE + "pending:" + uuid.uuid4().hex
            cursor = conn.execute("""INSERT INTO tasks
                (title,description,priority,category,status,created_by,assigned_to,
                 depends_on,source,required_model,assigned_slot,created_at,updated_at)
                VALUES (?,?,'P2','worker-review','pending',?,'bach','',?,NULL,NULL,?,?)""",
                (title, description, _ACTOR, source, stamp, stamp))
            review_task_id = cursor.lastrowid
            conn.execute("UPDATE tasks SET source=? WHERE id=?", (_SOURCE + str(review_task_id),
                                                                    review_task_id))
            receipt = {"schema": (_EXTERNAL_INTENT_SCHEMA if source_kind(target) == "external_attested" else _INTENT_SCHEMA),
                       "review_task_id": review_task_id,
                       "target_task_id": target["task_id"], "target_result_id": target["result_id"],
                       "target_revision": target["result_revision"],
                       "submission_revision": target["submission_revision"],
                       **_intent_author_fields(target),
                       "author_generation": target["generation"],
                       "author_id": authority["author_id"],
                       "policy_version": authority["policy_version"],
                       "identity_version": authority["identity_version"], "diff_chars": diff_chars,
                       "diff_truncated": diff_truncated, "diff_sha256": diff_sha256}
            digest = _digest(receipt)
            event_id = _history(conn, target["task_id"], "worker_result_review_task", _ACTOR,
                                now, {"intent_sha256": digest, "review_task_id": review_task_id,
                                      "target_result_id": target["result_id"],
                                      "target_revision": target["result_revision"]})
            conn.execute("INSERT INTO worker_result_review_intents "
                         "(review_task_id,target_task_id,target_result_id,target_revision,"
                         "intent,intent_sha256,event_id) VALUES (?,?,?,?,?,?,?)",
                         (review_task_id, target["task_id"], target["result_id"],
                          target["result_revision"], _json(receipt), digest, event_id))
            result = review_task_metadata(conn, review_task_id)
            if result is None:
                raise RuntimeError("Review-Intent nach Anlage nicht bestätigt")
            conn.commit()
            return result
        except BaseException:
            conn.rollback()
            raise
    finally:
        if conn.in_transaction:
            conn.rollback()


def _intent_target(conn, found, *, repo_root=None, worktrees_dir=None):
    receipt = found["receipt"]
    target = _target_record(conn, receipt["target_task_id"], repo_root=repo_root,
                            worktrees_dir=worktrees_dir)
    if target is None:
        return None
    authority = _target_authority(conn, target)
    if (authority is None or target["result_id"] != receipt["target_result_id"]
            or target["result_revision"] != receipt["target_revision"]
            or target["submission_revision"] != receipt["submission_revision"]
            or not _intent_source_matches(receipt, target)
            or target["generation"] != receipt["author_generation"]
            or authority["author_id"] != receipt["author_id"]
            or authority["policy_version"] != receipt["policy_version"]
            or authority["identity_version"] != receipt["identity_version"]):
        return None
    return target, authority


def _paging_plan(receipt):
    """Diff-Paging-Plan: Paging notwendig, Seitenzahl und Diff-Digest."""
    max_diff_chars = limit("BACH_CONTEXT_LIMIT") * 3
    chunk = max(1, limit("BACH_MAX_CONTEXT_CHARS"))
    diff_chars = receipt.get("diff_chars", 0)
    diff_truncated = receipt.get("diff_truncated", False)
    diff_sha256 = receipt.get("diff_sha256", "")
    # Restfenster: selbst ohne truncation ist der Diff nur dann vollstaendig
    # pruefbar, wenn er in das verfuegbare Slot-Kontextfenster passt.
    paging_required = diff_truncated or diff_chars > max(0, max_diff_chars - chunk)
    page_count = max(1, (diff_chars + chunk - 1) // chunk)
    return paging_required, page_count, diff_sha256


def _grant_valid(grant):
    try:
        return (isinstance(grant, ReviewGrant) and grant._seal is _SEAL
                and grant._is_current() is True and not grant._stop_event.is_set())
    except (AttributeError, TypeError, RuntimeError):
        return False


def issue_review_grant(conn, task_id, *, worker_id, host, generation, slot_id, route,
                       requested_model, is_current, stop_event, clock,
                       repo_root=None, worktrees_dir=None):
    """Authorize one local controller generation for an existing pending task."""
    if (conn.in_transaction or type(task_id) is not int or task_id <= 0
            or not all(type(value) is str and value and value == value.strip()
                       for value in (worker_id, host, generation, slot_id, requested_model))
            or not callable(is_current) or not callable(clock)
            or not callable(getattr(stop_event, "is_set", None))
            or is_current() is not True or stop_event.is_set()):
        return None
    route = _route(route)
    if route is None:
        return None
    try:
        found = _intent(conn, task_id)
        if found is None or found["task"]["status"] not in {"pending", "open"}:
            return None
        target_pair = _intent_target(conn, found, repo_root=repo_root,
                                     worktrees_dir=worktrees_dir)
        if target_pair is None:
            return None
        target, authority = target_pair
        paging_required, _page_count, diff_sha256 = _paging_plan(found["receipt"])
        if paging_required and not diff_sha256:
            return None
        principal = identity.principal_for_route(authority["identity"],
            backend_id=route["backend_id"], route_sha256=route["route_sha256"],
            requested_model=requested_model)
        if (principal is None or principal not in authority["eligible"]
                or _author_model_blocked(authority, principal)
                or generation == target["generation"]):
            return None
        # An explicit slot/model task route is an additional constraint, not
        # the source of reviewer identity.
        task = found["task"]
        if (task.get("assigned_slot") not in (None, "", slot_id)
                or task.get("required_model") not in (None, "", requested_model)):
            return None
        return ReviewGrant(_seal=_SEAL, task_id=task_id,
            task_version=task_content_version(task),
            target_task_id=target["task_id"], target_result_id=target["result_id"],
            target_revision=target["result_revision"], worker_id=worker_id, host=host,
            generation=generation, slot_id=slot_id, route=route,
            requested_model=requested_model, principal_id=principal,
            policy_version=authority["policy_version"],
            identity_version=authority["identity_version"],
            _is_current=is_current, _stop_event=stop_event)
    except (sqlite3.Error, ValueError, TypeError, KeyError, settings.PolicyUnavailable):
        return None


def validate_review_acquire(conn, task, *, worker_id, host, grant, now):
    """Pure DB check inside the canonical Acquire writer; never run Git here."""
    if (not conn.in_transaction or not _grant_valid(grant)
            or not isinstance(task, dict) or type(task.get("id")) is not int
            or task["id"] != grant.task_id or task.get("status") not in {"pending", "open"}
            or task_content_version(task) != grant.task_version
            or worker_id != grant.worker_id or host != grant.host
            or not isinstance(now, datetime)):
        return False
    try:
        found = _intent(conn, task["id"])
        if found is None:
            return False
        receipt = found["receipt"]
        if (receipt["target_task_id"] != grant.target_task_id
                or receipt["target_result_id"] != grant.target_result_id
                or receipt["target_revision"] != grant.target_revision
                or receipt["policy_version"] != grant.policy_version
                or receipt["identity_version"] != grant.identity_version):
            return False
        target = read_result(conn, grant.target_task_id)["result"]
        authority = _target_authority(conn, target)
        if (not isinstance(target, dict) or target.get("reason") != "awaiting_review"
                or target.get("result_id") != grant.target_result_id
                or target.get("submission_revision") != receipt["submission_revision"]
                or not _intent_source_matches(receipt, target)
                or target.get("generation") != receipt["author_generation"]
                or grant.generation == target.get("generation")
                or authority is None
                or authority["author_id"] != receipt["author_id"]
                or authority["policy_version"] != grant.policy_version
                or authority["identity_version"] != grant.identity_version
                or grant.principal_id not in authority["eligible"]
                or _author_model_blocked(authority, grant.principal_id)
                or identity.principal_for_route(authority["identity"],
                    backend_id=grant.route["backend_id"],
                    route_sha256=grant.route["route_sha256"],
                    requested_model=grant.requested_model) != grant.principal_id):
            return False
        return True
    except (sqlite3.Error, ValueError, TypeError, KeyError, AttributeError,
            settings.PolicyUnavailable):
        return False


def guard_review_dispatch(conn, binding, *, route, requested_model,
                          repo_root=None, worktrees_dir=None):
    """Revalidate a claimed review and its current target before inference."""
    if conn.in_transaction:
        return False
    grant = getattr(binding, "_review_grant", None)
    route = _route(route)
    if (not _grant_valid(grant) or route != grant.route
            or requested_model != grant.requested_model
            or binding.task_id != grant.task_id or binding.generation != grant.generation
            or binding._ack.result_generation != grant.generation
            or binding._ack.worker_id != grant.worker_id
            or binding._ack.host != grant.host
            or not binding._active or binding._closed):
        return False
    try:
        found = _intent(conn, grant.task_id)
        if found is None:
            return False
        target_pair = _intent_target(conn, found, repo_root=repo_root,
                                     worktrees_dir=worktrees_dir)
        if target_pair is None:
            return False
        target, authority = target_pair
        task = _row(conn.execute("SELECT * FROM tasks WHERE id=?", (grant.task_id,)))
        if (task is None or task["status"] != "in_progress"
                or task.get("claim_fence") != binding._ack.fence
                or task.get("claim_id") != binding._ack.lease_id
                or task.get("claim_result_generation") != grant.generation
                or task.get("claimed_by") != grant.worker_id
                or task_content_version(task) != grant.task_version
                or target["result_revision"] != grant.target_revision
                or authority["policy_version"] != grant.policy_version
                or authority["identity_version"] != grant.identity_version
                or grant.principal_id not in authority["eligible"]
                or _author_model_blocked(authority, grant.principal_id)
                or grant.generation == target["generation"]
                or identity.principal_for_route(authority["identity"],
                    backend_id=route["backend_id"], route_sha256=route["route_sha256"],
                    requested_model=requested_model) != grant.principal_id):
            return False
        return True
    except (sqlite3.Error, ValueError, TypeError, KeyError, AttributeError,
            settings.PolicyUnavailable):
        return False


def validate_review_release(conn, task, worker_result, binding):
    """Private review-child CAS in the canonical lease-release transaction.

    Git is checked before the binding lock; this writer checks the exact DB
    target, intent, current identity and actual returned provider receipt.
    Nothing supplied by a tool request can stand in for the execution handle.
    """
    if not conn.in_transaction or binding is None or not isinstance(task, dict):
        return False
    grant = getattr(binding, "_review_grant", None)
    try:
        if (not _grant_valid(grant) or binding.task_id != grant.task_id
                or binding.generation != grant.generation
                or binding._ack.result_generation != grant.generation
                or binding._ack.worker_id != grant.worker_id
                or binding._ack.host != grant.host
                or binding._ack.fence != task.get("claim_fence")
                or binding._ack.lease_id != task.get("claim_id")
                or task.get("claimed_by") != grant.worker_id
                or task.get("claim_host") != grant.host
                or task.get("claim_result_generation") != grant.generation
                or task_content_version(task) != grant.task_version
                or worker_result.get("generation") != grant.generation
                or type(worker_result.get("result")) is not str
                or not binding._active or binding._closed
                or binding._model_execution_pending is not None):
            return False
        found = _intent(conn, grant.task_id)
        if found is None or found["task"] != task:
            return False
        intent = found["receipt"]
        if (intent["target_task_id"] != grant.target_task_id
                or intent["target_result_id"] != grant.target_result_id
                or intent["target_revision"] != grant.target_revision
                or intent["policy_version"] != grant.policy_version
                or intent["identity_version"] != grant.identity_version):
            return False
        parent = read_result(conn, grant.target_task_id)
        target = parent.get("result")
        if (parent.get("status") != "review" or not isinstance(target, dict)
                or target.get("result_id") != grant.target_result_id
                or target.get("submission_revision") != intent["submission_revision"]
                or not _intent_source_matches(intent, target)
                or target.get("generation") != intent["author_generation"]
                ):
            return False
        authority = _target_authority(conn, target)
        if (authority is None or not _same_target_db(conn, target, authority)
                or authority["author_id"] != intent["author_id"]
                or authority["policy_version"] != grant.policy_version
                or authority["identity_version"] != grant.identity_version
                or grant.principal_id not in authority["eligible"]
                or _author_model_blocked(authority, grant.principal_id)
                or grant.generation == target["generation"]):
            return False
        answer = grant._last_answer
        handle = binding._model_execution_candidate
        if (not isinstance(answer, dict) or handle is None
                or grant._last_answer_sha256 != execution_digest(answer)
                or _verdict_from_answer(answer, grant.task_id, worker_result["result"]) is None):
            return False
        execution = owned_execution(conn, binding, handle)
        if (execution is None or execution["phase"] != "returned"
                or execution["result_id"] is not None
                or execution["submission_revision"] is not None
                or execution["link_event_id"] is not None
                or type(execution["started_event_id"]) is not int
                or type(execution["terminal_event_id"]) is not int
                or execution["started_event_id"] >= execution["terminal_event_id"]):
            return False
        receipt = json.loads(execution["receipt"])
        if (execution_digest(receipt) != execution["receipt_sha256"]
                or receipt.get("schema") != "bach.worker-model-execution.v2"
                or receipt.get("execution_id") != execution["id"]
                or receipt.get("task_id") != grant.task_id
                or receipt.get("fence") != task["claim_fence"]
                or receipt.get("generation") != grant.generation
                or receipt.get("input_task_version") != grant.task_version
                or receipt.get("phase") != "returned"
                or receipt.get("slot_id") != grant.slot_id
                or receipt.get("backend_id") != grant.route["backend_id"]
                or receipt.get("route_sha256") != grant.route["route_sha256"]
                or receipt.get("route_confirmed") is not True
                or receipt.get("requested_model") != grant.requested_model
                or receipt.get("model_provenance") != "provider_reported"
                or receipt.get("response_sha256") != grant._last_answer_sha256
                or receipt.get("identity_configuration_version") != grant.identity_version
                or receipt.get("model_principal_id") != grant.principal_id
                or identity.principal_for_execution(authority["identity"],
                    {**receipt, "availability": "available"}) != grant.principal_id):
            return False
        terminal = {"execution_id": execution["id"], "phase": "returned",
                    "receipt_sha256": execution["receipt_sha256"]}
        if not execution_event(conn, execution["terminal_event_id"], grant.task_id,
                               "worker_model_execution_terminal", terminal,
                               receipt.get("returned_at")):
            return False
        initial = dict(receipt, phase="attempted", returned_at=None,
                       response_sha256=None, observed_model=None,
                       model_provenance="unknown", route_confirmed=False,
                       model_principal_id=None, identity_binding_sha256=None)
        return execution_event(conn, execution["started_event_id"], grant.task_id,
                               "worker_model_execution_start", initial,
                               receipt.get("started_at"))
    except (AttributeError, KeyError, TypeError, ValueError, sqlite3.Error,
            settings.PolicyUnavailable):
        return False


def _parse_verdict(result_text):
    try:
        verdict = json.loads(result_text)
    except (ValueError, TypeError):
        return None
    if (type(verdict) is not dict
            or set(verdict) not in ({"status", "summary", "task_contract_met"},
                                    {"status", "summary", "task_contract_met", "diff_pages"})
            or verdict["status"] not in {"approved", "findings", "rejected"}
            or type(verdict["summary"]) is not str
            or not verdict["summary"] or verdict["summary"] != verdict["summary"].strip()
            or len(verdict["summary"]) > 1200
            or any(ord(char) < 32 or ord(char) == 127 for char in verdict["summary"])
            or type(verdict["task_contract_met"]) is not bool
            or (verdict["status"] == "approved" and not verdict["task_contract_met"])):
        return None
    if "diff_pages" in verdict:
        pages = verdict["diff_pages"]
        if type(pages) is not list:
            return None
        seen = set()
        last = 0
        for page in pages:
            if (type(page) is not dict or set(page) != {"page", "sha256"}
                    or type(page["page"]) is not int or page["page"] < 1
                    or page["page"] <= last or page["page"] in seen
                    or type(page["sha256"]) is not str or not _HEX.fullmatch(page["sha256"])):
                return None
            seen.add(page["page"])
            last = page["page"]
    return verdict


def _verdict_from_answer(answer, child_task_id, result_text):
    if not isinstance(answer, dict) or answer.get("error"):
        return None
    calls = answer.get("tool_calls")
    if type(calls) is not list or len(calls) != 1 or type(calls[0]) is not dict:
        return None
    function = calls[0].get("function")
    if type(function) is not dict or function.get("name") != "task_manage":
        return None
    arguments = function.get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return None
    if (type(arguments) is not dict or set(arguments) != {"action", "task_id", "result"}
            or arguments["action"] != "submit_result"
            or type(arguments["task_id"]) is not int
            or arguments["task_id"] != child_task_id
            or type(arguments["result"]) is not str
            or arguments["result"] != result_text):
        return None
    return _parse_verdict(result_text)


def _invalid_child(conn, found, target, authority, child_id, status_revision):
    """Recognize only an actual, independently executed malformed review result."""
    observed = read_result(conn, child_id)
    child = observed.get("result")
    task = found["task"]
    if (observed.get("status") != "review" or observed.get("status_revision") != status_revision
            or not isinstance(child, dict) or child.get("reason") != "awaiting_review"
            or child.get("completion_policy_version") != 1
            or child.get("submission", {}).get("availability") != "available"
            or child.get("execution", {}).get("availability") != "available"
            or child.get("task_id") != child_id
            or child.get("task_version") != task_content_version(task)
            or child.get("submitted_status_event_id") != status_revision
            or task.get("claim_id") or task.get("status") != "review"
            or _parse_verdict(child.get("result")) is not None
            or child.get("accepted") is True
            or child.get("completion_decision_event_id") is not None
            or child.get("completion_decision_sha256") is not None
            or (_table(conn, "worker_result_model_reviews") and conn.execute(
                "SELECT 1 FROM worker_result_model_reviews WHERE review_task_id=? "
                "OR (target_result_id=? AND target_revision=?) LIMIT 1",
                (child_id, target["result_id"], target["result_revision"])).fetchone() is not None)):
        return None
    execution = child["execution"]
    reviewer = identity.principal_for_execution(authority["identity"], execution)
    if (reviewer is None or _author_model_blocked(authority, reviewer)
            or reviewer not in authority["eligible"]
            or child.get("generation") == target.get("generation")
            or execution.get("generation") != child.get("generation")
            or task.get("assigned_slot") not in (None, "", execution.get("slot_id"))
            or task.get("required_model") not in (None, "", execution.get("requested_model"))):
        return None
    return observed, child, reviewer


def recover_invalid_review_child(conn, task_id, *, result_id, status_revision,
                                 repo_root=None, worktrees_dir=None):
    """Requeue an immutable malformed review submission through the correction ledger.

    This controller-only operation cannot approve a verdict. It requires the
    original intent, live target revision, exact child CAS and independent
    provider execution; no device capability is inferred or changed.
    """
    if (conn.in_transaction or type(task_id) is not int or task_id <= 0
            or type(result_id) is not int or result_id <= 0
            or type(status_revision) is not int or status_revision <= 0):
        return None
    try:
        found = _intent(conn, task_id)
        if found is None:
            return None
        target_pair = _intent_target(conn, found, repo_root=repo_root,
                                     worktrees_dir=worktrees_dir)
        if target_pair is None:
            return None
        target, authority = target_pair
        initial = _invalid_child(conn, found, target, authority, task_id, status_revision)
        if initial is None or initial[1].get("result_id") != result_id:
            return None
        from .task_result_service import ensure_result_correction_schema
        from .task_lease import _history, _local_naive, _utcnow
        from hub.task_audit import apply_task_field_changes
        conn.execute("BEGIN IMMEDIATE")
        try:
            current_found = _intent(conn, task_id)
            if (not _same_target_db(conn, target, authority)
                    or current_found is None
                    or current_found["row"]["intent_sha256"] != found["row"]["intent_sha256"]):
                conn.rollback()
                return None
            # The final local Git check occurs in the small writer window.
            projected = project_scope_evidence(read_result(conn, target["task_id"]),
                repo_root=repo_root, worktrees_dir=worktrees_dir).get("result")
            if (not isinstance(projected, dict)
                    or projected.get("result_revision") != target["result_revision"]
                    or projected.get("scope", {}).get("availability") != "available"):
                conn.rollback()
                return None
            current_identity = _identity_snapshot(conn)
            if current_identity["configuration_version"] != authority["identity_version"]:
                conn.rollback()
                return None
            current = _invalid_child(conn, current_found, target, authority,
                                     task_id, status_revision)
            if (current is None or current[1].get("result_id") != result_id
                    or any(current[1].get(key) != initial[1].get(key) for key in (
                        "result_sha256", "submission_revision", "submission_event_id",
                        "task_version", "generation", "fence"))
                    or current[1]["execution"].get("execution_revision") !=
                       initial[1]["execution"].get("execution_revision")):
                conn.rollback()
                return None
            observed, child, reviewer = current
            now = _utcnow()
            receipt = {"schema": _INVALID_SCHEMA, "reason": "invalid_verdict_shape",
                "intent_sha256": found["row"]["intent_sha256"],
                "target_task_id": target["task_id"], "target_result_id": target["result_id"],
                "target_revision": target["result_revision"],
                "review_task_id": task_id, "child_result_id": result_id,
                "child_result_sha256": child["result_sha256"],
                "child_submission_revision": child["submission_revision"],
                "child_execution_revision": child["execution"]["execution_revision"],
                "child_execution_id": child["execution"]["execution_id"],
                "reviewer_id": reviewer, "generation": child["generation"],
                "fence": child["fence"], "task_version": child["task_version"],
                "status_revision": status_revision, "recorded_at": _local_naive(now)}
            digest = _digest(receipt)
            decision_event = _history(conn, task_id, "worker_result_review_invalid",
                _ACTOR, now, {**receipt, "receipt_sha256": digest})
            ensure_result_correction_schema(conn)
            note = (f"Ungültige strukturierte Review-Abgabe (Result #{result_id}); "
                    "erneute unabhängige Prüfung erforderlich.")
            correction_round = int(conn.execute(
                "SELECT COALESCE(MAX(correction_round),0)+1 FROM task_result_corrections "
                "WHERE task_id=?", (task_id,)).fetchone()[0])
            request_id = str(uuid.uuid4())
            cursor = conn.execute("""INSERT INTO task_result_corrections
                (task_id,request_id,correction_round,source_result_id,source_result_sha256,
                 source_generation,source_fence,source_task_version,source_status_revision,
                 correction_note,requested_by_device_id,requested_at,policy_decision_sha256)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (task_id, request_id, correction_round, result_id, child["result_sha256"],
                 child["generation"], child["fence"], child["task_version"],
                 status_revision, note, 0, _local_naive(now), digest))
            correction_id = cursor.lastrowid
            apply_task_field_changes(conn, task_id, current_found["task"], {"status": "pending"},
                changed_by=_ACTOR, now=_local_naive(now), allow_reopen=True)
            pointer = conn.execute("UPDATE tasks SET result_correction_request_id=? "
                "WHERE id=? AND status='pending' AND (claim_id IS NULL OR claim_id='') "
                "AND result_correction_request_id IS ?",
                (correction_id, task_id, current_found["task"].get("result_correction_request_id")))
            if pointer.rowcount != 1:
                raise ValueError("Reviewkorrektur wurde parallel geändert")
            updated = _row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
            from .task_lease import task_content_version as content_version
            next_version = content_version(updated)
            correction_event = _history(conn, task_id, "result_correction_request", _ACTOR, now,
                {"correction_id": correction_id, "request_id": request_id,
                 "correction_round": correction_round, "result_id": result_id,
                 "result_sha256": child["result_sha256"], "generation": child["generation"],
                 "fence": child["fence"], "task_version": child["task_version"],
                 "status_revision": status_revision, "correction_note": note,
                 "next_task_version": next_version, "policy_decision_sha256": digest})
            conn.execute("UPDATE task_result_corrections SET event_id=?,next_task_version=? WHERE id=?",
                (correction_event, next_version, correction_id))
            conn.execute("UPDATE worker_task_results SET completion_decision_event_id=?,"
                         "completion_decision_sha256=? WHERE id=? AND task_id=?",
                         (decision_event, digest, result_id, task_id))
            from .task_result_service import active_correction_request
            verified = active_correction_request(conn, task_id)
            if (not isinstance(verified, dict)
                    or verified.get("correction_id") != correction_id
                    or verified.get("source_result_id") != result_id):
                raise ValueError("Reviewkorrektur wurde nicht kanonisch bestätigt")
            conn.commit()
            return {"schema": _INVALID_SCHEMA, "availability": "recorded",
                    "review_task_id": task_id, "source_result_id": result_id,
                    "correction_id": correction_id, "status": "pending"}
        except BaseException:
            conn.rollback()
            raise
    except (sqlite3.Error, ValueError, TypeError, KeyError, AttributeError,
            settings.PolicyUnavailable):
        return None


def review_invalid_correction_matches(conn, row):
    """Pure historical validation of the private negative review correction."""
    try:
        child_id = row["task_id"]
        source = _row(conn.execute(
            "SELECT * FROM worker_task_results WHERE id=? AND task_id=?",
            (row["source_result_id"], child_id)))
        if (source is None or type(source.get("completion_decision_event_id")) is not int
                or not 0 < source["completion_decision_event_id"] < row["event_id"]
                or source.get("completion_decision_sha256") != row["policy_decision_sha256"]
                or source.get("submitted_status_event_id") != row["source_status_revision"]):
            return False
        event = _row(conn.execute("SELECT * FROM task_history WHERE id=? AND task_id=?",
            (source["completion_decision_event_id"], child_id)))
        if (event is None or event["action"] != "worker_result_review_invalid"
                or event["field_changed"] != "lease" or event["old_value"] is not None
                or event["changed_by"] != _ACTOR):
            return False
        stored = json.loads(event["new_value"])
        receipt = {key: value for key, value in stored.items() if key != "receipt_sha256"}
        found = _intent(conn, child_id)
        if (found is None or stored.get("receipt_sha256") != row["policy_decision_sha256"]
                or _digest(receipt) != row["policy_decision_sha256"]
                or receipt.get("schema") != _INVALID_SCHEMA
                or receipt.get("reason") != "invalid_verdict_shape"
                or receipt.get("recorded_at") != event["changed_at"]
                or receipt.get("intent_sha256") != found["row"]["intent_sha256"]
                or receipt.get("target_task_id") != found["receipt"]["target_task_id"]
                or receipt.get("target_result_id") != found["receipt"]["target_result_id"]
                or receipt.get("target_revision") != found["receipt"]["target_revision"]
                or receipt.get("review_task_id") != child_id
                or receipt.get("child_result_id") != source["id"]
                or receipt.get("child_result_sha256") != source["result_sha256"]
                or receipt.get("generation") != source["generation"]
                or receipt.get("fence") != source["fence"]
                or receipt.get("task_version") != source["task_version"]
                or receipt.get("status_revision") != row["source_status_revision"]
                or _parse_verdict(source["result"]) is not None):
            return False
        from .task_result_service import _submission_readback, _submission_revision
        submission = _submission_readback(conn, source)
        if submission.get("availability") != "available":
            return False
        revision = _submission_revision(source, submission["receipt_sha256"])
        if receipt.get("child_submission_revision") != revision:
            return False
        from .worker_execution_evidence import read_execution_evidence
        execution = read_execution_evidence(conn, dict(source, result_id=source["id"],
            reason="awaiting_review", submission=submission,
            submission_revision=revision))
        return (execution.get("availability") == "available"
            and execution.get("execution_revision") == receipt.get("child_execution_revision")
            and execution.get("execution_id") == receipt.get("child_execution_id")
            and execution.get("model_principal_id") == receipt.get("reviewer_id")
            and (not settings.exclude_author_model(conn)
                 or receipt.get("reviewer_id") != found["receipt"]["author_id"]))
    except (sqlite3.Error, ValueError, TypeError, KeyError, AttributeError):
        return False


def _obsolete_target_reason(conn, found, grant, *, repo_root=None, worktrees_dir=None):
    """Only proven target drift qualifies; missing observations do not."""
    intent = found["receipt"]
    observed = read_result(conn, grant.target_task_id)
    target = observed.get("result")
    if observed.get("status") not in {"review", None}:
        return "target_db_changed"
    if not isinstance(target, dict):
        return None
    if (type(target.get("result_id")) is int
            and target["result_id"] != intent["target_result_id"]):
        return "target_db_changed"
    if (type(observed.get("task_version")) is str
            and type(target.get("task_version")) is str
            and observed["task_version"] != target["task_version"]):
        return "target_db_changed"
    if (observed.get("status") != "review" or target.get("reason") != "awaiting_review"
            or target.get("result_id") != intent["target_result_id"]
            or target.get("submission_revision") != intent["submission_revision"]
            or not _intent_same_author(intent, target)):
        return None
    authority = _target_authority(conn, target)
    if (authority is None or authority["author_id"] != intent["author_id"]
            or authority["policy_version"] != grant.policy_version
            or authority["identity_version"] != grant.identity_version
            or not _same_target_db(conn, target, authority)):
        return None
    scope = target.get("scope", {})
    if (scope.get("availability") == "recorded"
            and type(scope.get("scope_receipt_sha256")) is str
            and _HEX.fullmatch(scope["scope_receipt_sha256"])
            and scope["scope_receipt_sha256"] != _intent_scope_sha(intent)):
        return "target_revision_changed"
    projected = project_scope_evidence(observed, repo_root=repo_root,
                                       worktrees_dir=worktrees_dir).get("result")
    if (isinstance(projected, dict) and projected.get("scope", {}).get("availability") == "available"
            and type(projected.get("result_revision")) is str
            and _HEX.fullmatch(projected["result_revision"])
            and projected["result_revision"] != grant.target_revision):
        return "target_revision_changed"
    if (isinstance(projected, dict)
            and target.get("scope", {}).get("scope_receipt_sha256") == _intent_scope_sha(intent)
            and projected.get("scope", {}).get("reason") == "current_git_changed"):
        return "current_git_changed"
    return None


def cancel_obsolete_review_child(conn, binding, *, repo_root=None, worktrees_dir=None):
    """Terminally park a released review child after proven target drift only."""
    if conn.in_transaction or getattr(getattr(binding, "_client", None), "mode", None) != "local":
        return None
    grant = getattr(binding, "_review_grant", None)
    try:
        if (not _grant_valid(grant) or binding.task_id != grant.task_id
                or binding.generation != grant.generation):
            return None
        found = _intent(conn, grant.task_id)
        child = _submitted(conn, binding)
        answer = grant._last_answer
        if (found is None or not isinstance(child, dict)
                or child.get("reason") != "awaiting_review"
                or child.get("completion_policy_version") != 1
                or child.get("submission", {}).get("availability") != "available"
                or child.get("execution", {}).get("availability") != "available"
                or child.get("accepted") is True
                or child.get("completion_decision_event_id") is not None
                or child.get("completion_decision_sha256") is not None
                or child.get("task_id") != grant.task_id
                or child.get("generation") != grant.generation
                or not isinstance(answer, dict)
                or execution_digest(answer) != grant._last_answer_sha256
                or _verdict_from_answer(answer, grant.task_id, child.get("result")) is None):
            return None
        intent = found["receipt"]
        execution = child["execution"]
        ids = _identity_snapshot(conn)
        if (intent["target_task_id"] != grant.target_task_id
                or intent["target_result_id"] != grant.target_result_id
                or intent["target_revision"] != grant.target_revision
                or intent["policy_version"] != grant.policy_version
                or intent["identity_version"] != grant.identity_version
                or ids["configuration_version"] != grant.identity_version
                or identity.principal_for_execution(ids, execution) != grant.principal_id
                or execution.get("response_sha256") != grant._last_answer_sha256
                or execution.get("slot_id") != grant.slot_id
                or execution.get("generation") != grant.generation
                or execution.get("backend_id") != grant.route["backend_id"]
                or execution.get("route_sha256") != grant.route["route_sha256"]
                or execution.get("requested_model") != grant.requested_model
                or (_table(conn, "worker_result_model_reviews") and conn.execute(
                    "SELECT 1 FROM worker_result_model_reviews WHERE review_task_id=? LIMIT 1",
                    (grant.task_id,)).fetchone() is not None)):
            return None
        reason = _obsolete_target_reason(conn, found, grant, repo_root=repo_root,
                                         worktrees_dir=worktrees_dir)
        if reason is None:
            return None
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = _intent(conn, grant.task_id)
            fresh = _submitted(conn, binding)
            if (current is None or current["row"]["intent_sha256"] != found["row"]["intent_sha256"]
                    or current["task"]["status"] != "review"
                    or current["task"].get("claim_id")
                    or not isinstance(fresh, dict) or fresh.get("reason") != "awaiting_review"
                    or fresh.get("status_revision") != child.get("status_revision")
                    or any(fresh.get(key) != child.get(key) for key in (
                        "result_id", "task_id", "fence", "generation", "task_version",
                        "result_sha256", "submission_revision", "submission_event_id"))
                    or fresh.get("execution", {}).get("execution_revision") !=
                       execution.get("execution_revision")
                    or fresh.get("execution", {}).get("response_sha256") !=
                       execution.get("response_sha256")
                    or _obsolete_target_reason(conn, current, grant,
                        repo_root=repo_root, worktrees_dir=worktrees_dir) != reason):
                conn.rollback()
                return None
            from hub.task_audit import apply_task_field_changes
            from .task_result_service import _status_revision
            now = _utcnow()
            apply_task_field_changes(conn, grant.task_id, current["task"],
                {"status": "cancelled"}, changed_by=_ACTOR, now=_local_naive(now))
            status_event = _status_revision(conn, grant.task_id)
            receipt = {"schema": _OBSOLETE_SCHEMA, "reason": reason,
                "intent_sha256": current["row"]["intent_sha256"],
                "target_task_id": grant.target_task_id,
                "target_result_id": grant.target_result_id,
                "target_revision": grant.target_revision,
                "review_task_id": grant.task_id,
                "child_result_id": fresh["result_id"],
                "child_submission_revision": fresh["submission_revision"],
                "child_execution_revision": fresh["execution"]["execution_revision"],
                "child_response_sha256": fresh["execution"]["response_sha256"],
                "reviewer_id": grant.principal_id,
                "generation": fresh["generation"], "fence": fresh["fence"],
                "status_revision": child["status_revision"],
                "cancelled_status_event_id": status_event,
                "recorded_at": _local_naive(now)}
            digest = _digest(receipt)
            event_id = _history(conn, grant.task_id, "worker_result_review_obsolete",
                _ACTOR, now, {**receipt, "receipt_sha256": digest})
            status_row = _row(conn.execute("SELECT * FROM task_history WHERE id=?",
                                           (status_event,)))
            if (status_row is None or status_row["task_id"] != grant.task_id
                    or status_row["action"] != "status_change"
                    or status_row["field_changed"] != "status"
                    or status_row["old_value"] != "review"
                    or status_row["new_value"] != "cancelled"
                    or status_row["changed_by"] != _ACTOR
                    or not status_event < event_id
                    or read_result(conn, grant.task_id)["status"] != "cancelled"):
                raise ValueError("Stale Reviewkind ist nicht terminal bestätigt")
            conn.commit()
            return {"schema": _OBSOLETE_SCHEMA, "availability": "cancelled",
                    "reason": reason, "review_task_id": grant.task_id,
                    "child_result_id": fresh["result_id"], "event_id": event_id}
        except BaseException:
            conn.rollback()
            raise
    except (sqlite3.Error, ValueError, TypeError, KeyError, AttributeError,
            settings.PolicyUnavailable):
        return None


def record_review(conn, binding, *, repo_root=None, worktrees_dir=None):
    """Commit one real, eligible independent model verdict for the target.

    The child has already submitted its own canonical result and linked its
    final actual backend return. An ineligible or same-principal report must
    not consume the unique independent review slot for this result revision.
    No active parent lease or model-supplied identity is accepted.
    """
    if conn.in_transaction or getattr(getattr(binding, "_client", None), "mode", None) != "local":
        return None
    grant = getattr(binding, "_review_grant", None)
    if (not _grant_valid(grant) or binding.task_id != grant.task_id
            or binding.generation != grant.generation
            or binding._ack.result_generation != grant.generation
            or binding._ack.worker_id != grant.worker_id
            or binding._ack.host != grant.host):
        return None
    try:
        found = _intent(conn, grant.task_id)
        if found is None:
            return None
        target_pair = _intent_target(conn, found, repo_root=repo_root,
                                     worktrees_dir=worktrees_dir)
        if target_pair is None:
            return None
        target, authority = target_pair
        child = _submitted(conn, binding)
        if isinstance(child, dict) and child.get("reason") == "accepted":
            # Submit can already have recorded and completed this child.
            # Replays read only the existing verified receipt; a personally
            # accepted child without that receipt gains no review authority.
            previous = read_review_evidence(conn, target)
            if (previous.get("availability") == "recorded"
                    and previous.get("review_task_id") == grant.task_id
                    and previous.get("child_result_id") == child.get("result_id")
                    and previous.get("result_revision") == grant.target_revision
                    and previous.get("reviewer_id") == grant.principal_id):
                return previous
            return None
        if (child is None or child.get("reason") != "awaiting_review"
                or child.get("execution", {}).get("availability") != "available"
                or child.get("task_id") != grant.task_id
                or child.get("generation") != grant.generation):
            return None
        execution = child["execution"]
        answer = copy.deepcopy(grant._last_answer)
        if (not isinstance(answer, dict) or execution_digest(answer) != execution.get("response_sha256")
                or execution.get("slot_id") != grant.slot_id
                or execution.get("generation") != grant.generation
                or execution.get("backend_id") != grant.route["backend_id"]
                or execution.get("route_sha256") != grant.route["route_sha256"]
                or execution.get("requested_model") != grant.requested_model
                or (source_kind(target) == "native" and
                    execution.get("execution_id") == target["execution"].get("execution_id"))
                or grant.generation == target["generation"]):
            return None
        verdict = _verdict_from_answer(answer, grant.task_id, child["result"])
        actual_principal = identity.principal_for_execution(authority["identity"], execution)
        if (verdict is None or actual_principal is None
                or actual_principal != grant.principal_id
                or _author_model_blocked(authority, actual_principal)
                or actual_principal not in authority["eligible"]
                or authority["policy_version"] != grant.policy_version
                or authority["identity_version"] != grant.identity_version
                or target["result_revision"] != grant.target_revision):
            return None
        paging_required, page_count, diff_sha256 = _paging_plan(found["receipt"])
        if paging_required:
            if verdict["status"] == "approved":
                pages = verdict.get("diff_pages", [])
                if (diff_sha256 == "" or len(pages) != page_count
                        or any(type(page) is not dict or page.get("page") != index + 1
                               for index, page in enumerate(pages))):
                    return None
        conn.execute("BEGIN IMMEDIATE")
        try:
            if not _same_target_db(conn, target, authority):
                conn.rollback()
                return None
            current_intent = _intent(conn, grant.task_id)
            if (current_intent is None
                    or current_intent["row"]["intent_sha256"] != found["row"]["intent_sha256"]):
                conn.rollback()
                return None
            current_child = read_result(conn, grant.task_id)["result"]
            if (not isinstance(current_child, dict) or current_child.get("reason") != "awaiting_review"
                    or any(current_child.get(key) != child.get(key) for key in (
                        "result_id", "task_id", "fence", "generation", "task_version",
                        "result_sha256", "submission_revision", "submission_event_id"))
                    or current_child.get("execution", {}).get("availability") != "available"
                    or current_child["execution"].get("execution_revision") != execution["execution_revision"]
                    or current_child["execution"].get("response_sha256") != execution["response_sha256"]):
                conn.rollback()
                return None
            current_identity = _identity_snapshot(conn)
            if (current_identity["configuration_version"] != grant.identity_version
                    or identity.principal_for_execution(current_identity,
                        current_child["execution"]) != actual_principal):
                conn.rollback()
                return None
            _ensure_schema(conn)
            prior = _row(conn.execute("SELECT * FROM worker_result_model_reviews "
                                   "WHERE target_result_id=? AND target_revision=?",
                                   (target["result_id"], target["result_revision"])))
            if prior is not None:
                conn.commit()
                return (read_review_evidence(conn, target)
                        if prior["review_task_id"] == grant.task_id else None)
            now = _utcnow()
            receipt = {"schema": (_EXTERNAL_REVIEW_SCHEMA if source_kind(target) == "external_attested" else _REVIEW_SCHEMA),
                       "target_task_id": target["task_id"],
                       "target_result_id": target["result_id"],
                       "target_revision": target["result_revision"],
                       "target_submission_revision": target["submission_revision"],
                       **_review_author_fields(target),
                       "author_id": authority["author_id"],
                       "author_generation": target["generation"],
                       "review_task_id": grant.task_id, "child_result_id": child["result_id"],
                       "child_submission_revision": child["submission_revision"],
                       "child_execution_id": execution["execution_id"],
                       "child_execution_revision": execution["execution_revision"],
                       "child_response_sha256": execution["response_sha256"],
                       "review_generation": grant.generation, "review_fence": child["fence"],
                       "review_slot_id": grant.slot_id, "reviewer_id": actual_principal,
                       "status": verdict["status"], "summary": verdict["summary"],
                       "reviewer_asserted_task_contract_met": verdict["task_contract_met"],
                       "policy_version": grant.policy_version,
                       "identity_version": grant.identity_version,
                       "recorded_at": _local_naive(now)}
            digest = _digest(receipt)
            event_id = _history(conn, target["task_id"], "worker_result_model_review",
                                _ACTOR, now,
                                {"receipt_sha256": digest, "review_task_id": grant.task_id,
                                 "child_result_id": child["result_id"],
                                 "target_revision": target["result_revision"]})
            conn.execute("INSERT INTO worker_result_model_reviews "
                         "(review_task_id,target_task_id,target_result_id,target_revision,"
                         "child_result_id,receipt,receipt_sha256,event_id) "
                         "VALUES (?,?,?,?,?,?,?,?)",
                         (grant.task_id, target["task_id"], target["result_id"],
                          target["result_revision"], child["result_id"], _json(receipt),
                          digest, event_id))
            if "diff_pages" in verdict:
                for page in verdict["diff_pages"]:
                    conn.execute("INSERT INTO worker_result_review_pages "
                                 "(receipt_sha256,target_result_id,target_revision,diff_sha256,"
                                 "page_no,page_sha256,created_at) VALUES (?,?,?,?,?,?,?)",
                                 (digest, target["result_id"], target["result_revision"],
                                  diff_sha256, page["page"], page["sha256"], _local_naive(now)))
            # The performed review is finished administrative work. This
            # accepts only its own verdict record, never the target's result.
            from .task_result_service import _Acceptance, _status_revision
            from hub.task_audit import apply_task_field_changes
            child_task = _row(conn.execute("SELECT * FROM tasks WHERE id=?",
                                           (grant.task_id,)))
            if child_task is None or child_task.get("claim_id") or child_task["status"] != "review":
                raise ValueError("Review-Aufgabe ist nicht abschließbar")
            apply_task_field_changes(conn, grant.task_id, child_task, {"status": "done"},
                changed_by=_ACTOR, now=_local_naive(now),
                result_acceptance=_Acceptance(conn, current_child))
            revision = _status_revision(conn, grant.task_id)
            acceptance_event = _history(conn, grant.task_id, "result_acceptance", _ACTOR, now,
                {"result_id": child["result_id"], "result_sha256": child["result_sha256"],
                 "task_version": child["task_version"], "status_revision": revision})
            conn.execute("UPDATE worker_task_results SET accepted_by=?,accepted_at=?,"
                         "accepted_status_event_id=?,acceptance_event_id=? WHERE id=?",
                         (_ACTOR, _local_naive(now), revision, acceptance_event, child["result_id"]))
            if read_result(conn, grant.task_id)["result"].get("accepted") is not True:
                raise ValueError("Review-Abschluss wurde nicht bestätigt")
            conn.commit()
            return read_review_evidence(conn, target)
        except BaseException:
            conn.rollback()
            raise
    except (sqlite3.Error, ValueError, TypeError, KeyError, AttributeError,
            settings.PolicyUnavailable):
        return None


def _unavailable(reason):
    return {"schema": _READ_SCHEMA, "availability": "unavailable", "reason": reason}


def read_review_evidence(conn, record):
    """Pure DB/history readback; outer projection checks current full revision."""
    if (not isinstance(record, dict) or type(record.get("task_id")) is not int
            or type(record.get("result_id")) is not int or record["result_id"] <= 0
            or record.get("submission", {}).get("availability") != "available"
            or source_pin(record) is None
            or review_task_marker(conn, record["task_id"])
            or not _table(conn, "worker_result_model_reviews")):
        return _unavailable("review_not_recorded")
    try:
        row = _row(conn.execute("SELECT * FROM worker_result_model_reviews "
                                "WHERE target_result_id=?", (record["result_id"],)))
        if row is None:
            return _unavailable("review_not_recorded")
        receipt = json.loads(row["receipt"])
        found = _intent(conn, row["review_task_id"])
        if (found is None or not isinstance(receipt, dict)
                or not _review_source_matches(receipt, record)
                or _digest(receipt) != row["receipt_sha256"]
                or type(row["event_id"]) is not int or row["event_id"] <= 0
                or type(row["review_task_id"]) is not int or row["review_task_id"] <= 0
                or row["target_task_id"] != record["task_id"]
                or row["target_result_id"] != record["result_id"]
                or row["target_revision"] != receipt.get("target_revision")
                or not _HEX.fullmatch(row["target_revision"])
                or receipt.get("target_task_id") != record["task_id"]
                or receipt.get("target_result_id") != record["result_id"]
                or receipt.get("target_submission_revision") != record["submission_revision"]
                or found["receipt"]["submission_revision"] != record["submission_revision"]
                or not _intent_source_matches(found["receipt"], record)
                or receipt.get("author_generation") != record["generation"]
                or receipt.get("review_task_id") != row["review_task_id"]
                or receipt.get("child_result_id") != row["child_result_id"]
                or receipt.get("policy_version") != found["receipt"]["policy_version"]
                or receipt.get("identity_version") != found["receipt"]["identity_version"]
                or receipt.get("author_id") != found["receipt"]["author_id"]
                or receipt.get("target_revision") != found["receipt"]["target_revision"]
                or receipt.get("status") not in {"approved", "findings", "rejected"}
                or type(receipt.get("reviewer_asserted_task_contract_met")) is not bool
                or type(receipt.get("summary")) is not str
                or not receipt["summary"] or len(receipt["summary"]) > 1200):
            return _unavailable("review_evidence_invalid")
        child = read_result(conn, row["review_task_id"])["result"]
        if (not isinstance(child, dict) or child.get("result_id") != row["child_result_id"]
                or type(child.get("submission_event_id")) is not int
                or not found["row"]["event_id"] < child["submission_event_id"] < row["event_id"]
                or child.get("reason") not in {"awaiting_review", "accepted"}
                or child.get("submission", {}).get("availability") != "available"
                or child.get("submission_revision") != receipt["child_submission_revision"]
                or child.get("generation") != receipt["review_generation"]
                or child.get("fence") != receipt["review_fence"]
                or child.get("execution", {}).get("availability") != "available"
                or child["execution"].get("execution_id") != receipt["child_execution_id"]
                or child["execution"].get("execution_revision") != receipt["child_execution_revision"]
                or child["execution"].get("response_sha256") != receipt["child_response_sha256"]
                or child["execution"].get("slot_id") != receipt["review_slot_id"]
                or receipt["author_generation"] == receipt["review_generation"]):
            return _unavailable("review_evidence_invalid")
        # The writer compared the private actual response/toolcall to the
        # execution digest. The reader checks that the immutable child result
        # still says exactly what the review receipt recorded.
        verdict = _parse_verdict(child["result"])
        if (verdict is None or any(verdict[key] != receipt[value] for key, value in (
                ("status", "status"), ("summary", "summary"),
                ("task_contract_met", "reviewer_asserted_task_contract_met")))):
            return _unavailable("review_evidence_invalid")
        authority = _target_authority(conn, record)
        if (authority is None or authority["author_id"] != receipt["author_id"]
                or authority["policy_version"] != receipt["policy_version"]
                or authority["identity_version"] != receipt["identity_version"]
                or identity.principal_for_execution(authority["identity"],
                    child["execution"]) != receipt["reviewer_id"]):
            return _unavailable("review_identity_not_current")
        event = _row(conn.execute("SELECT task_id,action,field_changed,new_value,changed_by,"
                                  "changed_at FROM task_history WHERE id=?",
                                  (row["event_id"],)))
        if (event is None or event["task_id"] != record["task_id"]
                or event["action"] != "worker_result_model_review"
                or event["field_changed"] != "lease"
                or event["changed_by"] != _ACTOR
                or event["changed_at"] != receipt["recorded_at"]
                or json.loads(event["new_value"]) != {
                    "receipt_sha256": row["receipt_sha256"],
                    "review_task_id": row["review_task_id"],
                    "child_result_id": row["child_result_id"],
                    "target_revision": row["target_revision"]}):
            return _unavailable("review_history_invalid")
        return {"schema": _READ_SCHEMA, "availability": "recorded",
                "task_id": record["task_id"], "result_id": record["result_id"],
                "result_revision": row["target_revision"],
                "review_task_id": row["review_task_id"],
                "child_result_id": row["child_result_id"],
                "reviewer_id": receipt["reviewer_id"],
                "status": receipt["status"], "summary": receipt["summary"],
                "reviewer_asserted_task_contract_met": receipt["reviewer_asserted_task_contract_met"],
                "independent": (receipt["review_generation"] != receipt["author_generation"]
                    and not _author_model_blocked(authority, receipt["reviewer_id"])),
                "policy_eligible": receipt["reviewer_id"] in authority["eligible"],
                "event_id": row["event_id"]}
    except (sqlite3.Error, ValueError, TypeError, KeyError, AttributeError,
            settings.PolicyUnavailable):
        return _unavailable("review_evidence_invalid")
