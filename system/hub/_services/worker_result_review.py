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
from . import worker_review_identity as identity
from .task_lease import _history, _local_naive, _utcnow, task_content_version
from .task_result_service import read_result
from .worker_execution_evidence import _digest as execution_digest, _submitted
from .worker_scope_evidence import project_scope_evidence

_SEAL = object()
_ACTOR = "native-result-review-controller"
_INTENT_SCHEMA = "bach.worker-result-review-intent.v1"
_REVIEW_SCHEMA = "bach.worker-result-model-review.v1"
_READ_SCHEMA = "bach.worker-result-review-evidence.v1"
_HEX = re.compile(r"[a-f0-9]{64}\Z")
_SUBMISSION_REVISION = re.compile(r"sha256:[a-f0-9]{64}\Z")
_SOURCE = "worker-result-review:v1:"


class ReviewGrant:
    """One process-private permission to run a particular review task."""

    __slots__ = ("_seal", "task_id", "task_version", "target_task_id", "target_result_id",
                 "target_revision", "worker_id", "host", "generation", "slot_id", "route",
                 "requested_model", "principal_id", "policy_version", "identity_version",
                 "_is_current", "_stop_event", "_last_answer")

    def __init__(self, *, _seal=None, **values):
        if _seal is not _SEAL:
            raise ValueError("Private review grant required")
        self._seal = _seal
        for name, value in values.items():
            setattr(self, name, value)
        self._last_answer = None

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


def _policy_eligible(policy, author_id):
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
                 if reviewer.reviewer_id != author_id
                 and (mode is not kernel.CompletionMode.HIGH_SECURITY
                      or reviewer.tier is kernel.ReviewerTier.TOP))


def _target_record(conn, task_id, *, repo_root=None, worktrees_dir=None):
    """Fresh Git projection strictly outside a SQLite transaction."""
    if conn.in_transaction:
        return None
    try:
        projected = project_scope_evidence(
            read_result(conn, task_id), repo_root=repo_root, worktrees_dir=worktrees_dir)
        record = projected.get("result")
        if (projected.get("status") != "review" or not isinstance(record, dict)
                or record.get("reason") != "awaiting_review"
                or record.get("submission", {}).get("availability") != "available"
                or record.get("execution", {}).get("availability") != "available"
                or type(record["execution"].get("slot_id")) is not str
                or not record["execution"]["slot_id"]
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
        author = identity.principal_for_execution(model_ids, record["execution"])
        if (policy.get("availability") != "available" or author is None
                or policy.get("configuration_version") != current["configuration_version"]
                or policy.get("policy") != settings._global(conn)["policy"]
                or policy.get("override") != current["override"]
                or not _policy_eligible(policy, author)):
            return None
        return {"author_id": author, "policy_version": current["configuration_version"],
                "identity_version": model_ids["configuration_version"],
                "identity": model_ids, "eligible": _policy_eligible(policy, author)}
    except (sqlite3.Error, ValueError, TypeError, KeyError, settings.PolicyUnavailable):
        return None


def _same_target_db(conn, record, authority):
    """Recheck the canonical rows and settings under the caller's writer."""
    try:
        current = read_result(conn, record["task_id"])
        observed = current["result"]
        if (current["status"] != "review" or not isinstance(observed, dict)
                or observed.get("reason") != "awaiting_review"
                or observed.get("submission", {}).get("availability") != "available"):
            return False
        fields = ("result_id", "task_id", "fence", "generation", "task_version",
                  "result_sha256", "submission_revision", "submission_event_id")
        if any(observed.get(key) != record.get(key) for key in fields):
            return False
        for name, fields in (("execution", ("execution_revision", "execution_id",
                                            "response_sha256", "route_sha256")),
                             ("scope", ("scope_receipt_sha256", "scope_event_id"))):
            left, right = observed.get(name), record.get(name)
            if (not isinstance(left, dict) or not isinstance(right, dict)
                    or left.get("availability") not in {"available", "recorded"}
                    or any(left.get(key) != right.get(key) for key in fields)):
                return False
        resolved = _target_authority(conn, observed)
        return bool(resolved and all(resolved[key] == authority[key]
                                     for key in ("author_id", "policy_version",
                                                 "identity_version", "eligible")))
    except (sqlite3.Error, ValueError, TypeError, KeyError):
        return False


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
                or not isinstance(receipt, dict) or receipt.get("schema") != _INTENT_SCHEMA
                or set(receipt) != {"schema", "review_task_id", "target_task_id",
                                    "target_result_id", "target_revision",
                                    "submission_revision", "execution_revision",
                                    "scope_receipt_sha256", "author_execution_id",
                                    "author_slot_id", "author_generation", "author_id",
                                    "policy_version", "identity_version"}
                or _digest(receipt) != row["intent_sha256"]
                or receipt.get("review_task_id") != review_task_id
                or receipt.get("target_task_id") != row["target_task_id"]
                or receipt.get("target_result_id") != row["target_result_id"]
                or receipt.get("target_revision") != row["target_revision"]
                or not _HEX.fullmatch(row["target_revision"])
                or type(receipt["submission_revision"]) is not str
                or not _SUBMISSION_REVISION.fullmatch(receipt["submission_revision"])
                or any(type(receipt[key]) is not str or not _HEX.fullmatch(receipt[key])
                       for key in ("execution_revision", "scope_receipt_sha256",
                                   "policy_version", "identity_version"))
                or any(type(receipt[key]) is not str or not receipt[key]
                       for key in ("author_execution_id", "author_slot_id",
                                   "author_generation", "author_id"))
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
    return {"schema": _INTENT_SCHEMA, "review_task_id": task_id,
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


def prepare_review_task(conn, binding, *, repo_root=None, worktrees_dir=None):
    """Create one ordinary pending review task after a real author submission."""
    if conn.in_transaction or getattr(getattr(binding, "_client", None), "mode", None) != "local":
        return None
    try:
        author_record = _submitted(conn, binding)
        if author_record is None or review_task_marker(conn, binding.task_id):
            return None
        target = _target_record(conn, binding.task_id, repo_root=repo_root,
                                worktrees_dir=worktrees_dir)
        if target is None or author_record["result_id"] != target["result_id"]:
            return None
        authority = _target_authority(conn, target)
        if authority is None:
            return None
        conn.execute("BEGIN IMMEDIATE")
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
            title = f"Ergebnisreview Task #{binding.task_id} / Result #{target['result_id']}"
            source = _SOURCE + "pending:" + uuid.uuid4().hex
            cursor = conn.execute("""INSERT INTO tasks
                (title,description,priority,category,status,created_by,assigned_to,
                 depends_on,source,required_model,assigned_slot,created_at,updated_at)
                VALUES (?,?,'P2','worker-review','pending',?,'bach','',?,NULL,NULL,?,?)""",
                (title, "Controllergebundenes Ergebnisreview; Ziel nur aus privatem Intent lesen.",
                 _ACTOR, source, stamp, stamp))
            review_task_id = cursor.lastrowid
            conn.execute("UPDATE tasks SET source=? WHERE id=?", (_SOURCE + str(review_task_id),
                                                                    review_task_id))
            receipt = {"schema": _INTENT_SCHEMA, "review_task_id": review_task_id,
                       "target_task_id": binding.task_id, "target_result_id": target["result_id"],
                       "target_revision": target["result_revision"],
                       "submission_revision": target["submission_revision"],
                       "execution_revision": target["execution"]["execution_revision"],
                       "scope_receipt_sha256": target["scope"]["scope_receipt_sha256"],
                       "author_execution_id": target["execution"]["execution_id"],
                       "author_slot_id": target["execution"].get("slot_id"),
                       "author_generation": target["generation"],
                       "author_id": authority["author_id"],
                       "policy_version": authority["policy_version"],
                       "identity_version": authority["identity_version"]}
            digest = _digest(receipt)
            event_id = _history(conn, binding.task_id, "worker_result_review_task", _ACTOR,
                                now, {"intent_sha256": digest, "review_task_id": review_task_id,
                                      "target_result_id": target["result_id"],
                                      "target_revision": target["result_revision"]})
            conn.execute("INSERT INTO worker_result_review_intents "
                         "(review_task_id,target_task_id,target_result_id,target_revision,"
                         "intent,intent_sha256,event_id) VALUES (?,?,?,?,?,?,?)",
                         (review_task_id, binding.task_id, target["result_id"],
                          target["result_revision"], _json(receipt), digest, event_id))
            result = review_task_metadata(conn, review_task_id)
            if result is None:
                raise RuntimeError("Review-Intent nach Anlage nicht bestätigt")
            conn.commit()
            return result
        except BaseException:
            conn.rollback()
            raise
    except (sqlite3.Error, ValueError, TypeError, KeyError, RuntimeError,
            settings.PolicyUnavailable):
        return None


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
            or target["execution"]["execution_revision"] != receipt["execution_revision"]
            or target["execution"]["execution_id"] != receipt["author_execution_id"]
            or target["scope"]["scope_receipt_sha256"] != receipt["scope_receipt_sha256"]
            or target["execution"].get("slot_id") != receipt["author_slot_id"]
            or target["generation"] != receipt["author_generation"]
            or authority["author_id"] != receipt["author_id"]
            or authority["policy_version"] != receipt["policy_version"]
            or authority["identity_version"] != receipt["identity_version"]):
        return None
    return target, authority


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
        principal = identity.principal_for_route(authority["identity"],
            backend_id=route["backend_id"], route_sha256=route["route_sha256"],
            requested_model=requested_model)
        if (principal is None or principal not in authority["eligible"]
                or principal == authority["author_id"]
                or slot_id == target["execution"].get("slot_id")
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
                or target.get("execution", {}).get("execution_revision") != receipt["execution_revision"]
                or target.get("execution", {}).get("execution_id") != receipt["author_execution_id"]
                or target.get("execution", {}).get("slot_id") != receipt["author_slot_id"]
                or target.get("generation") != receipt["author_generation"]
                or target.get("scope", {}).get("scope_receipt_sha256") != receipt["scope_receipt_sha256"]
                or authority is None
                or authority["author_id"] != receipt["author_id"]
                or authority["policy_version"] != grant.policy_version
                or authority["identity_version"] != grant.identity_version
                or grant.principal_id not in authority["eligible"]
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
                or grant.principal_id == authority["author_id"]
                or grant.slot_id == target["execution"].get("slot_id")
                or grant.generation == target["generation"]
                or identity.principal_for_route(authority["identity"],
                    backend_id=route["backend_id"], route_sha256=route["route_sha256"],
                    requested_model=requested_model) != grant.principal_id):
            return False
        return True
    except (sqlite3.Error, ValueError, TypeError, KeyError, AttributeError,
            settings.PolicyUnavailable):
        return False


def _parse_verdict(result_text):
    try:
        verdict = json.loads(result_text)
    except (ValueError, TypeError):
        return None
    if (type(verdict) is not dict
            or set(verdict) != {"status", "summary", "task_contract_met"}
            or verdict["status"] not in {"approved", "findings", "rejected"}
            or type(verdict["summary"]) is not str
            or not verdict["summary"] or verdict["summary"] != verdict["summary"].strip()
            or len(verdict["summary"]) > 1200
            or any(ord(char) < 32 or ord(char) == 127 for char in verdict["summary"])
            or type(verdict["task_contract_met"]) is not bool
            or (verdict["status"] == "approved" and not verdict["task_contract_met"])):
        return None
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


def record_review(conn, binding, *, repo_root=None, worktrees_dir=None):
    """Commit one real, independent model verdict for the target result.

    The child has already submitted its own canonical result and linked its
    final actual backend return. No active parent lease or model-supplied
    identity field is accepted.
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
                or execution.get("execution_id") == target["execution"].get("execution_id")
                or grant.slot_id == target["execution"].get("slot_id")
                or grant.generation == target["generation"]):
            return None
        verdict = _verdict_from_answer(answer, grant.task_id, child["result"])
        actual_principal = identity.principal_for_execution(authority["identity"], execution)
        if (verdict is None or actual_principal is None
                or actual_principal != grant.principal_id
                or actual_principal == authority["author_id"]
                or actual_principal not in authority["eligible"]
                or authority["policy_version"] != grant.policy_version
                or authority["identity_version"] != grant.identity_version
                or target["result_revision"] != grant.target_revision):
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
            receipt = {"schema": _REVIEW_SCHEMA,
                       "target_task_id": target["task_id"],
                       "target_result_id": target["result_id"],
                       "target_revision": target["result_revision"],
                       "target_submission_revision": target["submission_revision"],
                       "author_execution_id": target["execution"]["execution_id"],
                       "author_id": authority["author_id"],
                       "author_slot_id": target["execution"].get("slot_id"),
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
            or record.get("execution", {}).get("availability") != "available"
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
                or receipt.get("schema") != _REVIEW_SCHEMA
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
                or receipt.get("author_execution_id") != record["execution"]["execution_id"]
                or found["receipt"]["submission_revision"] != record["submission_revision"]
                or found["receipt"]["execution_revision"] != record["execution"]["execution_revision"]
                or found["receipt"]["author_execution_id"] != record["execution"]["execution_id"]
                or found["receipt"]["scope_receipt_sha256"] != record["scope"]["scope_receipt_sha256"]
                or receipt.get("author_generation") != record["generation"]
                or receipt.get("author_slot_id") != record["execution"].get("slot_id")
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
                or receipt["author_id"] == receipt.get("reviewer_id")
                or receipt["author_slot_id"] == receipt["review_slot_id"]
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
                or receipt["reviewer_id"] not in authority["eligible"]
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
                "independent": True, "event_id": row["event_id"]}
    except (sqlite3.Error, ValueError, TypeError, KeyError, AttributeError,
            settings.PolicyUnavailable):
        return _unavailable("review_evidence_invalid")
