# BACH Adapter: ellmos-core native maintenance producer provenance
"""maintenance_task_provenance.py — Native documentation producer receipts.

The private receipt is committed with the task by TaskHandler. It is not a
queue or an alternate task authority. Public task fields and documentation.json
cannot issue this capability. Source provisioning remains an operator action.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from hub._services.task_lease import _history, task_content_version
from hub._services.chat import worker_repo_registry as registry

_REPOSITORY = "ellmos-ai/bach"
_SCHEMA = "bach.maintenance-task-intent.v1"
_ACTOR = "native-docs-maintenance"
_SEAL = object()
_TERMINAL = {"done", "completed", "cancelled", "archived"}
_NAMES = {
    "delta": {"workers", "scheduler", "memory", "governance", "gui", "root"},
    "routine": {"help_forensic", "roadmap_review", "doc_freshness", "docs_changelog_review"},
}
_DDL = """CREATE TABLE IF NOT EXISTS maintenance_task_intents (
    task_id INTEGER PRIMARY KEY, operation_id TEXT NOT NULL UNIQUE,
    root_id TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
    intent TEXT NOT NULL, intent_sha256 TEXT NOT NULL, event_id INTEGER NOT NULL)"""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _error(reason):
    return registry.RepositoryBindingError(reason, reason_code=reason)


def _row(cursor):
    row = cursor.fetchone()
    return dict(zip((c[0] for c in cursor.description), row)) if row is not None else None


def _has_table(conn):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='maintenance_task_intents'").fetchone() is not None


def _canonical():
    from hub._services.task_lease_client import TaskLeaseClient
    client = TaskLeaseClient()
    path, identity = registry._canonical_review_client(client)
    return client, path, identity


@contextmanager
def _connection(*, write=False):
    client, path, identity = _canonical()
    # A disappearing authority must never become an empty replacement DB.
    try:
        conn = sqlite3.connect(path.as_uri() + ("?mode=rw" if write else "?mode=ro"),
                               uri=True, timeout=5.0)
    except sqlite3.Error:
        raise _error("canonical_lead_required") from None
    conn.row_factory = sqlite3.Row
    try:
        registry._assert_database_identity(path, identity)
        yield conn, path, identity
    finally:
        conn.close()


def _read_intent(conn, task_id):
    """Read only; neither schema creation nor task/version repair."""
    if not _has_table(conn):
        return None
    row = _row(conn.execute("SELECT * FROM maintenance_task_intents WHERE task_id=?", (task_id,)))
    if row is None:
        return None
    try:
        raw = row["intent"]
        if not isinstance(raw, str) or len(raw.encode()) > 16384:
            raise ValueError
        value = json.loads(raw)
        if (set(value) != {"schema", "operation_id", "root_id", "root", "kind", "name",
                          "occurrence", "revision", "repository", "repository_record",
                          "source_proof", "task_id", "task_version", "request_sha256", "created_at"}
                or value["schema"] != _SCHEMA or value["repository"] != _REPOSITORY
                or value["task_id"] != task_id
                or value["kind"] not in _NAMES or value["name"] not in _NAMES[value["kind"]]
                or value["root_id"] != hashlib.sha256(value["root"].encode()).hexdigest()
                or value["operation_id"] != _digest({
                    k: value[k] for k in ("root_id", "kind", "name", "occurrence")})
                or _digest(value) != row["intent_sha256"]
                or any(row[k] != value[k] for k in ("operation_id", "root_id", "kind", "name"))
                or any(re.fullmatch(r"[0-9a-f]{64}", value[k]) is None
                       for k in ("task_version", "request_sha256"))
                or re.fullmatch(r"[0-9a-f]{40}", value["revision"]) is None):
            raise ValueError
        _check_source_proof(value["source_proof"], value["repository_record"], value["revision"])
        event = _row(conn.execute("SELECT * FROM task_history WHERE id=?", (row["event_id"],)))
        detail = {"intent_sha256": row["intent_sha256"], "operation_id": value["operation_id"]}
        if (event is None or event["task_id"] != task_id
                or event["action"] != "maintenance_producer_create"
                or event["changed_by"] != _ACTOR or json.loads(event["new_value"]) != detail):
            raise ValueError
        task = _row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
        if task is None:
            raise ValueError
        return {"row": row, "intent": value, "task": task}
    except (TypeError, ValueError, KeyError, AttributeError):
        raise _error("maintenance_provenance_unavailable") from None


def _operation(conn, operation_id):
    if not _has_table(conn):
        return None
    found = conn.execute("SELECT task_id FROM maintenance_task_intents WHERE operation_id=?",
                         (operation_id,)).fetchone()
    return _read_intent(conn, found[0]) if found else None


def _record_intent(conn, request, task_id):
    """Called only inside TaskHandler's native create transaction."""
    if type(request) is not _CreateRequest or request._seal is not _SEAL or not conn.in_transaction:
        raise _error("maintenance_provenance_unavailable")
    task = _row(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
    intent = {**request.intent, "task_id": task_id, "task_version": task_content_version(task),
              "created_at": datetime.now(timezone.utc).isoformat()}
    digest = _digest(intent)
    event_id = _history(conn, task_id, "maintenance_producer_create", _ACTOR,
        datetime.now(timezone.utc), {"intent_sha256": digest, "operation_id": intent["operation_id"]})
    conn.execute("INSERT INTO maintenance_task_intents "
        "(task_id,operation_id,root_id,kind,name,intent,intent_sha256,event_id) VALUES (?,?,?,?,?,?,?,?)",
        (task_id, intent["operation_id"], intent["root_id"], intent["kind"], intent["name"],
         _json(intent), digest, event_id))
    request.writer.assert_current()
    registry._assert_database_identity(request.database, request.identity)


class _CreateRequest:
    def __init__(self, *, seal, intent, fields, writer, database, identity):
        if seal is not _SEAL:
            raise _error("maintenance_provenance_unavailable")
        self._seal, self.intent, self.fields, self.writer = seal, intent, fields, writer
        self.database, self.identity = database, identity

    def __reduce__(self):
        raise TypeError("Private maintenance request cannot be serialized")


def check_create_request(request, args):
    from hub.rheingold import get_lead_config
    if (type(request) is not _CreateRequest or request._seal is not _SEAL
            or any(flag in args for flag in ("--remote", "--offline", "--local"))
            or get_lead_config().get("mode") not in {"lead", "isolated"}):
        raise _error("maintenance_provenance_unavailable")


@contextmanager
def create_connection(request, handler, fields):
    """Internal TaskHandler seam; never a public CLI/API argument."""
    from hub.rheingold import get_lead_config
    if (type(request) is not _CreateRequest or request._seal is not _SEAL
            or Path(handler.db_path) != request.database
            or fields != request.fields or get_lead_config().get("mode") not in {"lead", "isolated"}):
        raise _error("maintenance_provenance_unavailable")
    registry._assert_database_identity(request.database, request.identity)
    request.writer.assert_current()
    with _connection(write=True) as (conn, path, identity):
        if (path != request.database
                or (identity.st_dev, identity.st_ino) != (request.identity.st_dev, request.identity.st_ino)):
            raise _error("canonical_lead_required")
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(_DDL)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_maintenance_task_owner "
                         "ON maintenance_task_intents(root_id,kind,name,task_id)")
            yield conn
        finally:
            conn.rollback()


def existing_creation(conn, request):
    found = _operation(conn, request.intent["operation_id"])
    if found is not None:
        if found["intent"]["request_sha256"] != request.intent["request_sha256"]:
            raise _error("maintenance_operation_conflict")
        return found["intent"]["task_id"]
    rows = conn.execute("SELECT p.task_id FROM maintenance_task_intents p JOIN tasks t ON t.id=p.task_id "
        "WHERE p.root_id=? AND p.kind=? AND p.name=? AND t.status NOT IN ('done','completed','cancelled','archived')",
        (request.intent["root_id"], request.intent["kind"], request.intent["name"])).fetchall()
    if rows:
        raise _error("maintenance_pending_operation")
    if conn.execute("SELECT 1 FROM tasks WHERE title=? LIMIT 1", (request.fields["title"],)).fetchone():
        raise _error("maintenance_provenance_unavailable")
    return None


def _check_source_proof(proof, record, revision):
    expected = {"schema": "bach.task-public-source.v2", "repository": _REPOSITORY,
        "origin": "https://github.com/" + _REPOSITORY, "source_sha": revision,
        "source_ref": "refs/heads/" + record["default_branch"], "visibility": "public",
        "private": False, "metadata_verified": True, "ref_verified": True}
    if (record != {"origin": expected["origin"], "default_branch": record["default_branch"],
                   "visibility": "public"} or not isinstance(proof, dict)
            or any(proof.get(key) != value for key, value in expected.items())
            or proof.get("private") is not False or proof.get("metadata_verified") is not True
            or proof.get("ref_verified") is not True):
        raise _error("maintenance_source_unverified")
    registry.canonical_default_branch(record["default_branch"])


def _verify_source(intent, *, require_current):
    from hub import worker_git
    from hub._services.chat.worker_write_guard import _scan_locks
    record, revision = intent["repository_record"], intent["revision"]
    binding = registry.RepositoryBinding(1, _REPOSITORY, record["origin"],
                                         record["default_branch"], revision)
    try:
        source = worker_git._safe_source_clone_path(binding)
        if source != registry.source_clone_path(_REPOSITORY, revision):
            raise ValueError
        if _scan_locks(source).get("hook_guards") != []:
            raise ValueError
        proof = worker_git._validate_pinned_source_clone(source, binding, require_current=require_current)
        _check_source_proof(proof, record, revision)
        return proof
    except (RuntimeError, OSError, ValueError, TypeError, KeyError):
        raise _error("maintenance_source_unverified") from None


class NativeMaintenanceProducer:
    """The installed maintenance consumer's narrow native create capability."""

    def __init__(self, root, guard):
        self.root = Path(root)
        self.guard = guard
        self.root_id = hashlib.sha256(str(self.root.resolve()).encode()).hexdigest()

    def _check_root(self):
        from hub import worker_git
        if (self.root.is_symlink() or self.root.resolve(strict=True) != self.root
                or self.root != worker_git.get_live_repo_root()):
            raise _error("maintenance_root_unverified")
        self.guard(self.root)

    def _enroll(self, task_id):
        from hub._services.task_lease_client import TaskLeaseClient
        return registry.enroll_maintenance_task_repository(
            TaskLeaseClient(), task_id, expected_registry_sha256=hashlib.sha256(
                registry._read_registry_bytes(registry.registry_path())).hexdigest())

    def ensure(self, *, kind, name, occurrence, revision, title, description, priority, binding):
        from hub import worker_git
        import bach_api
        self._check_root()
        if (kind not in _NAMES or name not in _NAMES[kind]
                or re.fullmatch(r"[0-9a-f]{40}", revision) is None
                or not isinstance(occurrence, str) or not occurrence or len(occurrence) > 64):
            raise _error("maintenance_operation_invalid")
        if kind == "delta" and occurrence != revision:
            raise _error("maintenance_operation_invalid")
        if kind == "routine":
            when = datetime.fromisoformat(occurrence)
            if when.tzinfo is None:
                raise _error("maintenance_operation_invalid")
            occurrence = when.astimezone(timezone.utc).isoformat()
        operation = {"root_id": self.root_id, "kind": kind, "name": name, "occurrence": occurrence}
        operation_id = _digest(operation)
        with _connection() as (conn, _, _):
            found = _operation(conn, operation_id)
        if found is not None:
            self._enroll(found["intent"]["task_id"])
            return found["intent"]["task_id"], "recovered"
        fields = {"title": title, "priority": priority, "category": "WORKER",
                  "description": description, "due_date": None,
                  "required_model": binding.get("required_model") or None,
                  "assigned_slot": binding.get("assigned_slot") or None,
                  "result_max_chars": None, "assigned_to": "BACH", "creation_origin": _ACTOR}
        _, database, identity = _canonical()
        expected = hashlib.sha256(registry._read_registry_bytes(registry.registry_path())).hexdigest()
        with registry._RegistryWriter(expected) as writer:
            data = registry.load_registry()
            record = data["repositories"].get(_REPOSITORY)
            if record is None:
                raise _error("maintenance_source_unverified")
            intent = {"schema": _SCHEMA, **operation, "root": str(self.root),
                      "operation_id": operation_id, "revision": revision,
                      "repository": _REPOSITORY, "repository_record": record,
                      "request_sha256": _digest(fields)}
            # The trusted root and exact current public clone must agree. Never clone here.
            try:
                origin = worker_git._canonical_public_origin(worker_git._git_text(self.root, "origin"),
                                                             _REPOSITORY)
                if origin != record["origin"] or worker_git._git_text(self.root, "head") != revision:
                    raise ValueError
                worker_git._assert_source_clone_clean(self.root)
            except (RuntimeError, OSError, ValueError):
                raise _error("maintenance_source_unverified") from None
            intent["source_proof"] = _verify_source(intent, require_current=True)
            self._check_root()
            writer.check_fences()
            writer.assert_current()
            handler = bach_api.get_app().get_handler("task")
            from hub.task import TaskHandler
            if type(handler) is not TaskHandler:
                raise _error("canonical_lead_required")
            request = _CreateRequest(seal=_SEAL, intent=intent, fields=fields, writer=writer,
                                     database=database, identity=identity)
            args = [title, "--priority", priority, "--category", "WORKER", "--assigned", "bach",
                    "--description", description, "--creation-origin", _ACTOR]
            for key, flag in (("required_model", "--required-model"), ("assigned_slot", "--assigned-slot")):
                if fields[key]:
                    args.extend([flag, fields[key]])
            ok, _ = handler._add(args, _maintenance_request=request)
            if not ok:
                raise _error("documentation_task_creation_failed")
        with _connection() as (conn, _, _):
            found = _operation(conn, operation_id)
        if found is None:
            raise _error("maintenance_provenance_unavailable")
        self._enroll(found["intent"]["task_id"])
        return found["intent"]["task_id"], "created"

    def references(self, kind):
        """Bounded latest native receipts restore the cache after an ACK/process loss."""
        self._check_root()
        with _connection() as (conn, _, _):
            if not _has_table(conn):
                return []
            rows = conn.execute("SELECT p.task_id FROM maintenance_task_intents p "
                "WHERE p.root_id=? AND p.kind=? AND NOT EXISTS (SELECT 1 FROM maintenance_task_intents q "
                "WHERE q.root_id=p.root_id AND q.kind=p.kind AND q.name=p.name AND q.task_id>p.task_id) "
                "ORDER BY p.task_id LIMIT 11", (self.root_id, kind)).fetchall()
            if len(rows) > len(_NAMES[kind]):
                raise _error("maintenance_provenance_unavailable")
            found = [_read_intent(conn, row[0]) for row in rows]
        result = []
        for item in found:
            value, task = item["intent"], item["task"]
            if task["status"] not in _TERMINAL:
                self._enroll(value["task_id"])
            reference = {"revision": value["revision"], "task_id": value["task_id"],
                         "dispatched_at": value["created_at"]}
            if value["kind"] == "routine":
                reference["scheduled_for"] = value["occurrence"]
            result.append((value["name"], reference))
        return result

    def confirm_reference(self, item):
        """Legacy caches are references only; an operator must have bound old open work."""
        if item["task_status"] in _TERMINAL:
            return
        try:
            binding = registry.resolve_task_repository(item["task_id"])
            if binding.repository != _REPOSITORY:
                raise ValueError
        except (registry.RepositoryBindingError, ValueError):
            raise _error("maintenance_legacy_enrollment_required") from None


def native_producer_for(task_api, root, guard):
    """Only the installed native singleton receives automatic producer authority.

    Injected task APIs retain their existing test/legacy contract. They cannot
    create a private receipt or write the production registry through this seam.
    """
    import bach_api
    return NativeMaintenanceProducer(root, guard) if task_api is bach_api.task else None
