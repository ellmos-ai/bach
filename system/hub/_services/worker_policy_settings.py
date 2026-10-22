"""Versioned worker settings in BACH's existing configuration store.

The shared taskplan contract owns policy types. This adapter owns persistence
and CAS, never task completion, worker starts, or an alternative task queue.
Reads are read-only and never initialize a schema.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
import uuid

CONTRACT = "worker-review-policy.v1alpha1"
GLOBAL_SCHEMA = "bach.worker-review-policy-settings.v1"
TASK_SCHEMA = "bach.task-worker-policy-override.v1"
GLOBAL_KEY = "worker_review_policy.v1"
TASK_KEY = "worker_review_task.v1:"
POLICY_KEYS = {"policy_version", "default_mode", "reviewers", "allow_review_task_pickup",
               "review_expiry_seconds", "github_external_review"}
OVERRIDE_KEYS = {"mode", "require_user_review", "github_external_review", "allow_review_task_pickup"}
SELECTION_KEYS = {"resume_bound_task_first", "decompose_when_idle", "normal_task_order"}
WORKER_SELECTION_KEYS = {"require_assigned_slot", "enforce_model_binding"}
WORKER_OVERRIDE_KEYS = {"require_assigned_slot", "enforce_model_binding"}


class PolicyUnavailable(RuntimeError):
    pass


class PolicyConflict(ValueError):
    pass


def _kernel():
    try:
        module = importlib.import_module("taskplan.worker_policy")
    except ImportError as exc:
        raise PolicyUnavailable("Gemeinsamer Task-Master-Policyvertrag fehlt") from exc
    if getattr(module, "CONTRACT_VERSION", None) != CONTRACT:
        raise PolicyUnavailable("Gemeinsamer Policyvertrag hat eine unbekannte Version")
    return module


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _object(value, keys):
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("Unvollständige oder unbekannte Policyfelder")


def _boolean(value):
    if type(value) is not bool:
        raise ValueError("Boolescher Policywert erforderlich")
    return value


def validate_policy(value):
    _object(value, POLICY_KEYS)
    kernel = _kernel()
    reviewers = value["reviewers"]
    if not isinstance(reviewers, list) or len(reviewers) > 64:
        raise ValueError("Ungültige Reviewerliste")
    seen = set()
    typed = []
    for entry in reviewers:
        _object(entry, {"reviewer_id", "tier"})
        ident = entry["reviewer_id"]
        if (not isinstance(ident, str) or not ident or ident != ident.strip()
                or len(ident) > 180 or any(ord(char) < 32 for char in ident)
                or ident.casefold() in seen):
            raise ValueError("Reviewer-IDs müssen gültig und eindeutig sein")
        seen.add(ident.casefold())
        typed.append(kernel.Reviewer(ident, kernel.ReviewerTier(entry["tier"])))
    expiry = value["review_expiry_seconds"]
    if expiry is not None and (type(expiry) is not int or not 1 <= expiry <= 31536000):
        raise ValueError("Review-Frist muss zwischen einer Sekunde und einem Jahr liegen")
    mode = kernel.CompletionMode(value["default_mode"])
    if mode is kernel.CompletionMode.HIGH_SECURITY and not any(
            reviewer.tier is kernel.ReviewerTier.TOP for reviewer in typed):
        raise ValueError("Hochsicherheit benötigt einen zugelassenen Top-Reviewer")
    if not isinstance(value["policy_version"], str) or len(value["policy_version"]) > 180:
        raise ValueError("Ungültige Policyversion")
    return kernel.WorkerReviewPolicy(
        policy_version=value["policy_version"], default_mode=mode, reviewers=tuple(typed),
        allow_review_task_pickup=_boolean(value["allow_review_task_pickup"]),
        review_expiry_seconds=expiry, github_external_review=_boolean(value["github_external_review"]),
    )


def validate_override(value):
    _object(value, OVERRIDE_KEYS | WORKER_OVERRIDE_KEYS)
    kernel = _kernel()
    mode = value["mode"]
    _boolean(value["require_user_review"])
    for name in ("github_external_review", "allow_review_task_pickup"):
        if value[name] is not None:
            _boolean(value[name])
    for name in WORKER_OVERRIDE_KEYS:
        if value.get(name) is not None:
            _boolean(value[name])
    return kernel.TaskPolicyOverride(
        mode=None if mode is None else kernel.CompletionMode(mode),
        require_user_review=value["require_user_review"],
        github_external_review=value["github_external_review"],
        allow_review_task_pickup=value["allow_review_task_pickup"],
    )


def _selection(value):
    _object(value, SELECTION_KEYS)
    _boolean(value["resume_bound_task_first"])
    _boolean(value["decompose_when_idle"])
    if value["normal_task_order"] not in {"priority_then_created", "oldest_first"}:
        raise ValueError("Unbekannte Auswahlreihenfolge")
    return value


def _worker_selection(value):
    _object(value, WORKER_SELECTION_KEYS)
    _boolean(value["require_assigned_slot"])
    _boolean(value["enforce_model_binding"])
    return value


def _defaults():
    # Preserve the current review-first deployment until result integration is
    # explicitly enabled. No reviewer identity is inferred from a model name.
    return {"policy": {"policy_version": "worker-policy-settings-1", "default_mode": "balanced",
        "reviewers": [], "allow_review_task_pickup": False,
        "review_expiry_seconds": None, "github_external_review": True},
        "selection": {"resume_bound_task_first": True, "decompose_when_idle": True,
                      "normal_task_order": "priority_then_created"},
        "worker_selection": {"require_assigned_slot": False, "enforce_model_binding": False}}


def _default_override():
    return {"mode": None, "require_user_review": False,
            "github_external_review": None, "allow_review_task_pickup": None,
            "require_assigned_slot": None, "enforce_model_binding": None}


@contextmanager
def _connection(db_path=None, *, write=False):
    if db_path is None:
        from hub.bach_paths import BACH_DB
        db_path = BACH_DB
    conn = None
    try:
        uri = Path(db_path).resolve().as_uri() + ("?mode=rw" if write else "?mode=ro")
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        if write:
            conn.execute("BEGIN IMMEDIATE")
        else:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
        yield conn
        if write:
            conn.commit()
    except sqlite3.Error as exc:
        if conn is not None and conn.in_transaction:
            conn.rollback()
        raise PolicyUnavailable("Kanonischer Konfigurationsspeicher nicht verfügbar") from exc
    except BaseException:
        if conn is not None and conn.in_transaction:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()


def _stored(conn, key):
    row = conn.execute("SELECT value FROM system_config WHERE key=?", (key,)).fetchone()
    if row is None:
        return {"revision": 0, "values": None}
    try:
        value = json.loads(row[0])
        _object(value, {"revision", "values"})
        if type(value["revision"]) is not int or value["revision"] < 1:
            raise ValueError("Ungültige Revision")
        return value
    except (ValueError, TypeError) as exc:
        raise PolicyUnavailable("Gespeicherte Worker-Regeln sind ungültig") from exc


def _global(conn):
    stored = _stored(conn, GLOBAL_KEY)
    values = stored["values"] if stored["values"] is not None else _defaults()
    try:
        unknown = set(values) - {"policy", "selection", "worker_selection"}
        if unknown:
            raise ValueError("Unvollständige oder unbekannte Policyfelder")
        # Older revisions lack worker_selection; fill from defaults on read.
        merged = {**_defaults(), **values}
        _object(merged, {"policy", "selection", "worker_selection"})
        validate_policy(merged["policy"])
        _selection(merged["selection"])
        _worker_selection(merged["worker_selection"])
    except (ValueError, TypeError) as exc:
        raise PolicyUnavailable("Gespeicherte globale Worker-Regeln sind ungültig") from exc
    return {"schema": GLOBAL_SCHEMA, "availability": "available", "contract_version": CONTRACT,
        "configuration_version": _digest(stored),
        "policy_source": "system_default" if stored["values"] is None else "user_override",
        **merged}


def read_global_policy(db_path=None):
    with _connection(db_path) as conn:
        return _global(conn)


def _persist(conn, key, values, *, actor):
    if not isinstance(actor, str) or not actor.strip() or len(actor) > 180:
        raise ValueError("Nachvollziehbarer Konfigurationsakteur erforderlich")
    old = _stored(conn, key)
    stored = {"revision": old["revision"] + 1, "values": values}
    # The existing configuration store holds the config and an append-only
    # settings event. Neither row is a task or a second task-result ledger.
    conn.execute("INSERT INTO system_config(key,value) VALUES (?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, _canonical(stored)))
    event = {"actor": actor, "key": key, "revision": stored["revision"],
        "previous_version": _digest(old), "configuration_version": _digest(stored),
        "observed_at": datetime.now(timezone.utc).isoformat()}
    conn.execute("INSERT INTO system_config(key,value) VALUES (?,?)",
                 ("worker_review_audit.v1:" + uuid.uuid4().hex, _canonical(event)))


def write_global_policy(payload, *, actor, operator_token=None, db_path=None):
    if not isinstance(payload, dict):
        raise ValueError("Policyobjekt erforderlich")
    reset = payload.get("reset_to_default") is True
    if reset:
        _object(payload, {"configuration_version", "reset_to_default"})
        _boolean(payload["reset_to_default"])
    else:
        # worker_selection is optional so older clients keep working.
        required = {"configuration_version", "policy", "selection"}
        allowed = required | {"worker_selection"}
        _object(payload, allowed if "worker_selection" in payload else required)
        if not required <= set(payload) or set(payload) - required - {"worker_selection"}:
            raise ValueError("Unvollständige oder unbekannte Policyfelder")
        validate_policy(payload["policy"])
        _selection(payload["selection"])
        if "worker_selection" in payload:
            _worker_selection(payload["worker_selection"])
    with _connection(db_path, write=True) as conn:
        before = _global(conn)
        if payload["configuration_version"] != before["configuration_version"]:
            raise PolicyConflict("Konfiguration wurde parallel geändert")
        reviewers = _defaults()["policy"]["reviewers"] if reset else payload["policy"]["reviewers"]
        if reviewers != before["policy"]["reviewers"]:
            # Device enrollment permits ordinary settings, not granting model
            # principals or Top-review rights. Reuse the explicit operator.
            from .worker_review_identity import require_operator
            actor = require_operator(conn, operator_token)
        values = None if reset else {
            "policy": payload["policy"],
            "selection": payload["selection"],
            "worker_selection": payload.get("worker_selection", before["worker_selection"]),
        }
        _persist(conn, GLOBAL_KEY, values, actor=actor)
        return {"schema": GLOBAL_SCHEMA, "updated": True, "worker_started": False,
                "configuration_version": _global(conn)["configuration_version"]}


def _task(conn, task_id):
    if type(task_id) is not int or task_id <= 0:
        raise ValueError("Gültige Task-ID erforderlich")
    cursor = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
    row = cursor.fetchone()
    if row is None:
        raise KeyError(task_id)
    if hasattr(row, "keys"):
        return dict(row)
    return dict(zip((column[0] for column in cursor.description), row))


def _task_snapshot(conn, task_id):
    from hub._services.task_lease import task_content_version
    row = _task(conn, task_id)
    global_snapshot = _global(conn)
    stored = _stored(conn, TASK_KEY + str(task_id))
    override = dict(stored["values"]) if stored["values"] is not None else _default_override()
    for _key in WORKER_OVERRIDE_KEYS:
        override.setdefault(_key, None)
    try:
        typed = validate_override(override)
    except (ValueError, TypeError) as exc:
        raise PolicyUnavailable("Gespeicherte Task-Regeln sind ungültig") from exc
    policy = validate_policy(global_snapshot["policy"])
    inherited_review = row.get("require_user_review")
    if inherited_review is None:
        inherited_review = False
    if type(inherited_review) not in (bool, int) or inherited_review not in (True, False, 0, 1):
        raise PolicyUnavailable("Geerbte Nutzerabnahme ist nicht bestätigt")
    def flag(name):
        return getattr(policy, name) if override[name] is None else override[name]
    worker_defaults = global_snapshot.get("worker_selection", _defaults()["worker_selection"])
    def wflag(name):
        return worker_defaults[name] if override[name] is None else override[name]
    # This is a configuration projection, not a fabricated completion verdict.
    # Only the result service may supply verified integrity and review evidence.
    effective = {"contract_version": CONTRACT, "policy_version": policy.policy_version,
        "policy_source": "task_override" if stored["values"] is not None else "system_default",
        "effective_mode": (typed.mode or policy.default_mode).value,
        "state": "not_evaluated", "reason": "completion_integrity_not_evaluated",
        "user_review_required": bool(inherited_review) or typed.require_user_review,
        "github_external_review": flag("github_external_review"),
        "allow_review_task_pickup": flag("allow_review_task_pickup"),
        "require_assigned_slot": wflag("require_assigned_slot"),
        "enforce_model_binding": wflag("enforce_model_binding")}
    return {"schema": TASK_SCHEMA, "availability": "available", "task_id": task_id,
        "task_version": task_content_version(row),
        "configuration_version": _digest({"global": global_snapshot["configuration_version"], "task": stored}),
        "global_policy_source": global_snapshot["policy_source"],
        "override": override, "effective": effective}


def read_task_policy(task_id, db_path=None, *, connection=None):
    if connection is not None:
        if db_path is not None or not isinstance(connection, sqlite3.Connection):
            raise PolicyUnavailable("Native Policy-Connection ist ungültig oder mehrdeutig")
        return _task_snapshot(connection, task_id)
    with _connection(db_path) as conn:
        return _task_snapshot(conn, task_id)


def write_task_policy(task_id, payload, *, actor, db_path=None):
    if not isinstance(payload, dict):
        raise ValueError("Task-Policyobjekt erforderlich")
    reset = payload.get("reset_to_default") is True
    _object(payload, {"task_id", "task_version", "configuration_version", "reset_to_default"}
            if reset else {"task_id", "task_version", "configuration_version", "override"})
    if reset:
        _boolean(payload["reset_to_default"])
    if type(payload["task_id"]) is not int or payload["task_id"] != task_id:
        raise ValueError("Taskbindung stimmt nicht")
    if not reset:
        validate_override(payload["override"])
    with _connection(db_path, write=True) as conn:
        before = _task_snapshot(conn, task_id)
        if (payload["task_version"] != before["task_version"]
                or payload["configuration_version"] != before["configuration_version"]):
            raise PolicyConflict("Task oder Policy wurde parallel geändert")
        if (before["override"]["require_user_review"]
                and (reset or not payload["override"]["require_user_review"])):
            raise ValueError("Eine gesetzte Nutzerabnahme darf nicht entfernt werden")
        _persist(conn, TASK_KEY + str(task_id), None if reset else payload["override"], actor=actor)
        return {"schema": TASK_SCHEMA, "updated": True, "worker_started": False,
                "task_id": task_id, "configuration_version": _task_snapshot(conn, task_id)["configuration_version"]}


def attach_active_task_leases(items, *, db_path=None, now=None):
    """Join a trusted controller generation to the current canonical lease.

    No row's assigned task ID, saved profile or caller-supplied lease is enough.
    The native result generation, content version, expiry and heartbeat must
    agree; private lease clients and renew/claim operations are never invoked.
    """
    from hub._services.task_lease import LeaseConfig, _lease_state, parse_ts, task_content_version
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("UTC-Zeitpunkt mit Zeitzone erforderlich")
    now = now.astimezone(timezone.utc)
    output = [{key: value for key, value in item.items() if key != "active_task_lease"} for item in items]
    try:
        with _connection(db_path) as conn:
            for item in output:
                if item.get("runtime_verified") is not True or item.get("running") is not True:
                    continue
                execution = item.get("execution")
                if not isinstance(execution, dict):
                    continue
                task_id = execution.get("active_task_id")
                generation = execution.get("generation")
                lease_worker_id = execution.get("lease_worker_id")
                controller_heartbeat = parse_ts(execution.get("heartbeat_at"))
                if (execution.get("schema") != "bach.worker-execution.v1"
                        or execution.get("state") != "running" or execution.get("terminal") is not False
                        or execution.get("worker_id") != item.get("id")
                        or ("active_task_id" in item and item["active_task_id"] != task_id)
                        or ("generation" in item and item["generation"] != generation)
                        or type(task_id) is not int or task_id <= 0
                        or not isinstance(generation, str) or not generation
                        or not isinstance(lease_worker_id, str) or not lease_worker_id
                        or controller_heartbeat is None or controller_heartbeat > now):
                    continue
                try:
                    row = _task(conn, task_id)
                except KeyError:
                    continue
                state = _lease_state(row, now, LeaseConfig.from_env())
                heartbeat = parse_ts(row.get("claim_heartbeat_at"))
                issued = parse_ts(row.get("claim_issued_at"))
                fence = row.get("claim_fence")
                if (not state["live"] or state["kind"] != "lease"
                        or row.get("claim_result_generation") != generation
                        or row.get("claimed_by") != lease_worker_id
                        or row.get("claim_task_version") != task_content_version(row)
                        or type(fence) is not int or fence <= 0
                        or not isinstance(row.get("claim_id"), str) or not row["claim_id"].strip()
                        or issued is None or heartbeat is None or not issued <= heartbeat <= now
                        or controller_heartbeat < issued):
                    continue
                item["active_task_lease"] = {"schema": "bach.task-lease.v1", "state": "active",
                    "task_id": task_id,
                    "lease_id": "sha256:" + hashlib.sha256(row["claim_id"].encode("utf-8")).hexdigest(),
                    "lease_id_kind": "observation_sha256", "source": "native_task_db", "fence": fence,
                    "observed_at": now.isoformat(), "expires_at": state["expires_at"].isoformat(),
                    "heartbeat_at": heartbeat.isoformat(), "holder": row.get("claimed_by")}
    except (PolicyUnavailable, ValueError, TypeError):
        # A partial read cannot bless a subset of a failed observation.
        for item in output:
            item.pop("active_task_lease", None)
    return output
