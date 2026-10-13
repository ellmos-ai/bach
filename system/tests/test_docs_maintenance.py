"""Documentation dispatch is evidence, never automatic semantic acceptance."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from hub._services.docs.maintenance_dispatch import (
    DocumentationDispatcher,
    packages_for,
    read_state,
)
from hub._services.docs.maintenance_runtime import (
    CONFIG_SCHEMA,
    STATUS_SCHEMA,
    CanonicalLockGuard,
    MaintenanceRuntime,
    SchedulerFacadeUnavailable,
    process_owner,
    readonly_status,
    validate_config,
)

NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)
REV = "a" * 40


class FakeTasks:
    def __init__(self):
        self.rows = []
        self.adds = 0
        self.fail_ack = False

    def list(self, **options):
        assert options["status"] is None
        return [
            dict(row) for row in self.rows if options["filter_text"] in row["title"]
        ]

    def raw(self, operation, *args):
        assert operation == "add"
        assert args[args.index("--category") + 1] == "WORKER"
        assert args[args.index("--assigned") + 1] == "bach"
        self.adds += 1
        fields = {
            args[i].removeprefix("--").replace("-", "_"): args[i + 1]
            for i in range(1, len(args), 2)
        }
        self.rows.append(
            {
                "id": self.adds,
                "title": args[0],
                "status": "pending",
                **fields,
                "assigned_to": fields["assigned"],
            }
        )
        if self.fail_ack:
            raise RuntimeError("Unknown acknowledgement")
        return True, "created"


def result(task_id, *, accepted=False, status="pending"):
    return {
        "verified": True,
        "task_id": task_id,
        "status": status,
        "result": {"accepted": True, "result_id": 12, "accepted_at": NOW.isoformat()}
        if accepted
        else None,
    }


@pytest.fixture
def fixture(tmp_path):
    tasks = FakeTasks()
    source = lambda root, previous: (
        REV,
        [] if previous == REV else ["system/hub/_services/chat/worker.py"],
    )
    dispatcher = DocumentationDispatcher(
        tmp_path,
        tmp_path / "docs.json",
        tasks,
        result,
        lambda _: None,
        snapshot=source,
        clock=lambda: NOW,
    )
    return dispatcher, tasks


@pytest.fixture
def native_task_environment(tmp_path, monkeypatch):
    import sqlite3

    from core.hooks import hooks
    from hub.task import TaskHandler

    import bach_api

    db = tmp_path / "isolated-task.db"
    schema = Path(__file__).parents[1] / "data/schema/schema.sql"
    with sqlite3.connect(db) as conn:
        conn.executescript(schema.read_text(encoding="utf-8"))
    monkeypatch.setenv("BACH_RHEINGOLD_DISABLED", "1")
    monkeypatch.setattr(bach_api, "_resolve_db_path", lambda: db)
    monkeypatch.setattr(hooks, "emit", lambda *_args, **_kwargs: None)
    handler = TaskHandler(tmp_path)
    handler.db_path = db
    proxy = bach_api._TaskProxy("task")
    monkeypatch.setattr(proxy, "raw", lambda operation, *args: handler.handle(operation, list(args)))
    return SimpleNamespace(proxy=proxy, handler=handler, db=db)


@pytest.fixture
def native_task_proxy(native_task_environment):
    return native_task_environment.proxy


def test_dispatch_uses_native_atomic_task_owner(native_task_proxy, tmp_path):
    dispatcher = DocumentationDispatcher(
        tmp_path,
        tmp_path / "maintenance.json",
        native_task_proxy,
        result,
        lambda _: None,
        snapshot=lambda *_: (REV, ["docs/README.md"]),
        clock=lambda: NOW,
        binding={"assigned_slot": "cloud_worker", "required_model": "glm-5.3:cloud"},
    )
    receipt = dispatcher.dispatch()
    row = native_task_proxy.show(receipt["task_id"])
    assert row["assigned_to"] == "BACH"
    assert row["assigned_slot"] == "cloud_worker"
    assert row["required_model"] == "glm-5.3:cloud"
    assert dispatcher.dispatch()["state"] == "idle"
    assert len(native_task_proxy.list(status=None, filter_text=row["title"])) == 1


def test_structured_task_add_accepts_atomic_owner(native_task_proxy):
    row = native_task_proxy.add("Automatisierte Dokuprüfung", assigned_to="bach")
    assert row["assigned_to"] == "BACH"


def test_owner_is_committed_before_create_hook(native_task_proxy, monkeypatch):
    from core.hooks import hooks

    observed = []
    monkeypatch.setattr(hooks, "emit", lambda event, data: observed.append(native_task_proxy.show(data["task_id"])))
    native_task_proxy.add("Atomarer Create-Hook", assigned_to="BACH")
    assert len(observed) == 1
    assert observed[0]["assigned_to"] == "BACH"


def test_add_without_owner_preserves_schema_default(native_task_proxy):
    with native_task_proxy._connect() as conn:
        default = next(row[4] for row in conn.execute("PRAGMA table_info(tasks)") if row[1] == "assigned_to")
    row = native_task_proxy.add("Unveränderter Standard")
    assert row["assigned_to"] == default.strip("'\"")


@pytest.mark.parametrize("arguments", [("--assigned",), ("--assigned", " "), ("--assigned=",), ("--assigned=-p",), ("--assigned", " -p"), ("--assigned= -p",), ("--assigned", "--priority", "P1"), ("-a", "-p", "P1")])
def test_invalid_owner_does_not_create_task(native_task_proxy, arguments):
    ok, _ = native_task_proxy.raw("add", "Ungültiger Besitzer", *arguments)
    assert not ok
    assert not native_task_proxy.list(status=None)


def test_native_unknown_ack_recovers_without_second_add(native_task_proxy, tmp_path, monkeypatch):
    dispatcher = DocumentationDispatcher(tmp_path, tmp_path / "ack.json", native_task_proxy, result, lambda _: None,
        snapshot=lambda *_: (REV, ["docs/README.md"]), clock=lambda: NOW)
    raw = native_task_proxy.raw
    calls = []

    def lost_ack(operation, *args):
        calls.append(operation)
        raw(operation, *args)
        raise RuntimeError("Unknown acknowledgement")

    monkeypatch.setattr(native_task_proxy, "raw", lost_ack)
    with pytest.raises(RuntimeError, match="Unknown acknowledgement"):
        dispatcher.dispatch()
    assert not dispatcher.state_path.exists()
    monkeypatch.setattr(native_task_proxy, "raw", raw)
    assert dispatcher.dispatch()["dispatch_action"] == "recovered"
    assert calls == ["add"]
    assert len(native_task_proxy.list(status=None)) == 1


def test_native_wrong_binding_is_retained(native_task_proxy, tmp_path):
    dispatcher = DocumentationDispatcher(tmp_path, tmp_path / "binding.json", native_task_proxy, result, lambda _: None,
        snapshot=lambda *_: (REV, ["docs/README.md"]), clock=lambda: NOW)
    root_id = hashlib.sha256(str(tmp_path.resolve()).encode()).hexdigest()[:8]
    title = f"Doku-Delta root {root_id} {REV[:12]}"
    native_task_proxy.add(title, assigned_to="user", category="WORKER",
        description=dispatcher._description("root", REV, ["docs/README.md"]))
    with pytest.raises(RuntimeError, match="binding_conflict"):
        dispatcher.dispatch()
    assert native_task_proxy.list(status=None)[0]["assigned_to"] == "USER"
    assert len(native_task_proxy.list(status=None)) == 1


@pytest.mark.parametrize("remote", [False, True])
def test_offline_owner_survives_draft_promotion(native_task_environment, monkeypatch, remote):
    from hub.rheingold import sync_drafts_to_rheingold

    proxy, handler = native_task_environment.proxy, native_task_environment.handler
    monkeypatch.setattr("hub.task.get_lead_config", lambda: {"mode": "worker"})
    monkeypatch.setattr("hub.task.get_rheingold_url", lambda **_: None)
    if remote:
        monkeypatch.delenv("BACH_RHEINGOLD_DISABLED")
        handler._canonical_db = native_task_environment.db
    ok, message = proxy.raw("add", "Offline-Aufgabe", "--assigned", "bach", *([] if remote else ["--offline"]))
    assert ok, message
    row = proxy.list(status=None)[0]
    assert row["id"] < 0 and row["assigned_to"] == "BACH"
    payloads = []

    def post(_url, payload):
        payloads.append(payload)
        return True, {"id": 987}

    monkeypatch.setattr("hub.rheingold.post_task_to_rheingold", post)
    with proxy._connect() as conn:
        sync_drafts_to_rheingold(conn, "https://isolated.invalid")
    assert payloads[0]["assigned_to"] == "BACH"
    assert proxy.show(987)["assigned_to"] == "BACH"


@pytest.mark.parametrize("owner", [None, "bach"])
def test_remote_add_preserves_explicit_assignment(native_task_environment, monkeypatch, owner):
    proxy, handler = native_task_environment.proxy, native_task_environment.handler
    monkeypatch.delenv("BACH_RHEINGOLD_DISABLED")
    handler._canonical_db = native_task_environment.db
    monkeypatch.setattr("hub.task.get_lead_config", lambda: {"mode": "worker"})
    monkeypatch.setattr("hub.task.get_rheingold_url", lambda **_: "https://isolated.invalid")
    payloads = []

    def post(_url, payload):
        payloads.append(payload)
        return True, {"id": 987}

    monkeypatch.setattr("hub.task.post_task_to_rheingold", post)
    arguments = ["--assigned", owner] if owner is not None else []
    assert proxy.raw("add", "Remote-Aufgabe", *arguments)[0]
    assert ("assigned_to" in payloads[0]) is (owner is not None)
    if owner is not None:
        assert payloads[0]["assigned_to"] == owner.upper()
        assert proxy.show(987)["assigned_to"] == owner.upper()


def test_remote_ack_cannot_overwrite_local_task(native_task_environment, monkeypatch):
    proxy, handler = native_task_environment.proxy, native_task_environment.handler
    original = proxy.add("Gleicher Titel", assigned_to="user", description="Lokale Nutzeraufgabe")
    original.pop("_message")
    monkeypatch.delenv("BACH_RHEINGOLD_DISABLED")
    handler._canonical_db = native_task_environment.db
    monkeypatch.setattr("hub.task.get_lead_config", lambda: {"mode": "worker"})
    monkeypatch.setattr("hub.task.get_rheingold_url", lambda **_: "https://isolated.invalid")
    monkeypatch.setattr("hub.task.post_task_to_rheingold", lambda *_: (True, {"id": original["id"]}))
    ok, message = proxy.raw("add", "Gleicher Titel", "--assigned", "bach")
    assert not ok and "COLLISION" in message
    assert proxy.show(original["id"]) == original


def test_identical_remote_ack_never_updates_existing_row(native_task_environment, monkeypatch):
    import sqlite3
    from contextlib import contextmanager

    proxy, handler = native_task_environment.proxy, native_task_environment.handler
    monkeypatch.delenv("BACH_RHEINGOLD_DISABLED")
    handler._canonical_db = native_task_environment.db
    monkeypatch.setattr("hub.task.get_lead_config", lambda: {"mode": "worker"})
    monkeypatch.setattr("hub.task.get_rheingold_url", lambda **_: "https://isolated.invalid")
    monkeypatch.setattr("hub.task.post_task_to_rheingold", lambda *_: (True, {"id": 987}))
    assert proxy.raw("add", "Idempotentes ACK", "--assigned", "bach")[0]
    original = proxy.show(987)

    @contextmanager
    def readonly_existing():
        with proxy._connect() as conn:
            conn.set_authorizer(lambda action, *_: sqlite3.SQLITE_DENY if action in
                (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE) else sqlite3.SQLITE_OK)
            yield conn

    monkeypatch.setattr(handler, "_get_db", readonly_existing)
    assert proxy.raw("add", "Idempotentes ACK", "--assigned", "bach")[0]
    assert proxy.show(987) == original


@pytest.mark.parametrize("owner", ["bach", "BACH", "Ollama", "OLLAMA", "Büro", "BÜRO", "müller", "Müller"])
def test_atomic_owner_is_visible_through_both_list_filters(native_task_proxy, owner):
    row = native_task_proxy.add("Zugewiesene Aufgabe", assigned_to=owner)
    assert [r["id"] for r in native_task_proxy.list(status=None, assigned_to=owner)] == [row["id"]]
    ok, message = native_task_proxy.raw("list", "all", "--assigned", owner)
    assert ok and "Zugewiesene Aufgabe" in message



def test_one_task_then_idle_without_false_review(fixture):
    dispatcher, tasks = fixture
    assert dispatcher.dispatch()["state"] == "dispatched"
    assert dispatcher.dispatch()["state"] == "idle"
    assert tasks.adds == 1
    item = read_state(dispatcher.state_path)["packages"]["workers"]
    assert item["task_status"] == "pending"
    assert item["last_review_success"] is None
    assert item["last_repair_success"] is None


def test_unknown_create_ack_recovers_same_native_task(fixture):
    dispatcher, tasks = fixture
    tasks.fail_ack = True
    with pytest.raises(RuntimeError):
        dispatcher.dispatch()
    assert not dispatcher.state_path.exists()
    tasks.fail_ack = False
    recovered = dispatcher.dispatch()
    assert recovered["dispatch_action"] == "recovered"
    assert tasks.adds == 1


def test_review_blocks_repeated_package_dispatch(fixture):
    dispatcher, tasks = fixture
    dispatcher.dispatch()
    dispatcher.snapshot = lambda *_: ("b" * 40, ["system/hub/_services/chat/worker.py"])
    dispatcher.result_reader = lambda task_id: result(task_id, status="review")
    assert dispatcher.dispatch()["state"] == "idle"
    assert tasks.adds == 1
    assert read_state(dispatcher.state_path)["source_revision"] == REV


def test_accepted_analysis_is_not_document_repair(fixture):
    dispatcher, tasks = fixture
    dispatcher.dispatch()
    dispatcher.result_reader = lambda task_id: result(
        task_id, accepted=True, status="done"
    )
    dispatcher.dispatch()
    item = read_state(dispatcher.state_path)["packages"]["workers"]
    assert item["last_review_success"] == NOW.isoformat()
    assert item["last_repair_success"] is None
    assert tasks.adds == 1


def test_lock_prevents_task_or_state_write(fixture):
    dispatcher, tasks = fixture

    def denied(_):
        raise PermissionError("locked")

    dispatcher.guard = denied
    with pytest.raises(PermissionError):
        dispatcher.dispatch()
    assert tasks.adds == 0
    assert not dispatcher.state_path.exists()


def test_readback_failure_does_not_advance_cursor(fixture):
    dispatcher, tasks = fixture
    dispatcher.result_reader = lambda _: {"verified": False}
    with pytest.raises(RuntimeError):
        dispatcher.dispatch()
    assert tasks.adds == 1
    assert not dispatcher.state_path.exists()


def test_one_package_per_tick(fixture):
    dispatcher, tasks = fixture
    dispatcher.snapshot = lambda *_: (
        REV,
        ["system/hub/scheduler.py", "system/gui/server.py"],
    )
    dispatcher.dispatch()
    assert tasks.adds == 1
    assert "source_revision" not in read_state(dispatcher.state_path)
    dispatcher.dispatch()
    assert tasks.adds == 2
    assert read_state(dispatcher.state_path)["source_revision"] == REV


@pytest.mark.parametrize(
    "filename", ["../README.md", "/etc/passwd", "foo\ninstruction", "foo\x00bar"]
)
def test_source_filename_cannot_be_instruction_or_escape(filename):
    with pytest.raises(ValueError):
        packages_for([filename])


def config(tmp_path):
    return {
        "schema": CONFIG_SCHEMA,
        "enabled": True,
        "interval_seconds": 300,
        "poll_seconds": 60,
        "min_available_mib": 512,
        "max_state_db_bytes": 67108864,
        "lock_tools_root": str(tmp_path),
        "protected_roots": [str(tmp_path)],
        "worker_binding": {},
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("enabled", 1),
        ("interval_seconds", 0),
        ("poll_seconds", True),
        ("min_available_mib", 1),
        ("max_state_db_bytes", 0),
    ],
)
def test_config_budget_validation(tmp_path, field, value):
    data = config(tmp_path)
    data[field] = value
    with pytest.raises(ValueError):
        validate_config(data)


def test_unknown_lock_configuration_is_denied(tmp_path):
    guard = CanonicalLockGuard(config(tmp_path))
    with pytest.raises(PermissionError):
        guard(tmp_path)
    assert not list(tmp_path.iterdir())


def test_owner_excludes_second_process_handle(tmp_path):
    with (
        process_owner(tmp_path / "owner.lock", lambda _: None),
        pytest.raises(OSError),
        process_owner(tmp_path / "owner.lock", lambda _: None),
    ):
        pytest.fail("Second maintenance owner acquired the same lock")


def test_two_checkouts_share_canonical_runtime_owner(tmp_path):
    cp = tmp_path / "config.json"
    cp.write_text(json.dumps(config(tmp_path)), encoding="utf-8")
    tasks = FakeTasks()
    options = {"task_api": tasks, "result_reader": result, "guard": lambda _: None}
    first = MaintenanceRuntime(
        tmp_path, tmp_path / "checkout1/state.db", tmp_path / "runtime", cp, **options
    )
    second = MaintenanceRuntime(
        tmp_path, tmp_path / "checkout2/state.db", tmp_path / "runtime", cp, **options
    )
    assert first.owner_path == second.owner_path
    with (
        process_owner(first.owner_path, first.guard),
        pytest.raises(OSError),
        process_owner(second.owner_path, second.guard),
    ):
        pytest.fail("Second checkout acquired canonical maintenance owner")


def test_arbitrary_scanner_cannot_grant_lock_authority(tmp_path, monkeypatch):
    (tmp_path / "lock_scan.py").write_text("print('fake clear')", encoding="utf-8")
    (tmp_path / "lock_utils.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *_args, **_options: pytest.fail("Untrusted scanner executed"),
    )
    with pytest.raises(PermissionError, match="source_unverified"):
        CanonicalLockGuard(config(tmp_path))(tmp_path)


def _exact_delta_review_row(dispatcher, *, task_id=77):
    files = ["system/hub/_services/chat/worker.py"]
    root_id = hashlib.sha256(str(dispatcher.root.resolve()).encode()).hexdigest()[:8]
    title = f"Doku-Delta workers {root_id} {REV[:12]}"
    return {
        "id": task_id,
        "title": title,
        "status": "review",
        "description": dispatcher._description("workers", REV, files),
        "category": "WORKER",
        "assigned_to": "user",
        "assigned_slot": dispatcher.binding.get("assigned_slot", ""),
        "required_model": dispatcher.binding.get("required_model", ""),
    }


def test_exact_human_review_handoff_recovers_without_acceptance(fixture):
    dispatcher, tasks = fixture
    dispatcher.binding = {
        "assigned_slot": "worker-5c70b1e2",
        "required_model": "glm-5.3:cloud",
    }
    row = _exact_delta_review_row(dispatcher, task_id=2051)
    tasks.rows.append(dict(row))
    dispatcher.result_reader = lambda task_id: result(task_id, status="review")

    outcome = dispatcher.dispatch()

    item = read_state(dispatcher.state_path)["packages"]["workers"]
    assert outcome["dispatch_action"] == "recovered"
    assert outcome["task_id"] == row["id"]
    assert outcome["semantic_review_completed"] is False
    assert item["task_status"] == "review"
    assert item["result_accepted"] is False
    assert item["last_review_success"] is None
    assert item["last_repair_success"] is None
    assert tasks.rows == [row]
    assert tasks.adds == 0


def test_actual_2051_root_review_row_recovers_with_observed_payload(fixture):
    dispatcher, tasks = fixture
    dispatcher.binding = {
        "assigned_slot": "worker-5c70b1e2",
        "required_model": "glm-5.3:cloud",
    }
    revision = "1bfc1fe3634f01ad099f8eb15cbc43904da15610"
    files = ["docs/GUX-Abnahmeblatt.md"]
    title = "Doku-Delta root 969c569e 1bfc1fe3634f"
    description = dispatcher._description("root", revision, files)
    assert (
        hashlib.sha256(description.encode("utf-8")).hexdigest()
        == "25c522dfbbfee2e35d683df422ba2f9cf9df73a8dd5aebcc2ed6c114d08bf701"
    )
    row = {
        "id": 2051,
        "title": title,
        "status": "review",
        "description": description,
        "category": "WORKER",
        "assigned_to": "user",
        "assigned_slot": "worker-5c70b1e2",
        "required_model": "glm-5.3:cloud",
    }
    tasks.rows.append(dict(row))

    task_id, action = dispatcher._ensure_task(title, description)

    assert (task_id, action) == (2051, "recovered")
    assert tasks.rows == [row]
    assert tasks.rows[0]["status"] == "review"
    assert tasks.adds == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("description", "foreign task"),
        ("category", "GENERAL"),
        ("assigned_slot", "slot-other"),
        ("required_model", "model-other"),
        ("status", "pending"),
        ("assigned_to", ""),
    ],
)
def test_human_review_handoff_requires_exact_identity_and_binding(
    fixture, field, value
):
    dispatcher, tasks = fixture
    dispatcher.binding = {"assigned_slot": "slot-a", "required_model": "model-a"}
    row = _exact_delta_review_row(dispatcher)
    row[field] = value
    tasks.rows.append(dict(row))

    with pytest.raises(RuntimeError, match="binding_conflict"):
        dispatcher.dispatch()

    assert tasks.rows == [row]
    assert tasks.adds == 0


def test_same_title_with_changed_authority_is_not_adopted(fixture):
    dispatcher, tasks = fixture
    tasks.fail_ack = True
    with pytest.raises(RuntimeError):
        dispatcher.dispatch()
    tasks.fail_ack = False
    tasks.rows[0]["description"] = "foreign task"
    with pytest.raises(RuntimeError, match="binding_conflict"):
        dispatcher.dispatch()
    assert tasks.adds == 1


def test_recurring_preserves_legacy_open_task(fixture):
    from hub._services.docs.maintenance_recurring import dispatch_routine

    dispatcher, tasks = fixture
    tasks.rows.append({"id": 40, "title": "Existing review", "status": "review"})
    definition = {
        "name": "help_forensic",
        "legacy_title": "Existing review",
        "priority": "P2",
        "dispatch_marker": NOW.isoformat(),
    }
    assert (
        dispatch_routine(dispatcher, definition, scheduled_for=NOW.isoformat())["state"]
        == "existing_legacy_work"
    )
    assert tasks.adds == 0


def test_recurring_waits_for_native_task_result(fixture):
    from hub._services.docs.maintenance_recurring import dispatch_routine

    dispatcher, tasks = fixture
    definition = {
        "name": "help_forensic",
        "legacy_title": "Existing review",
        "priority": "P2",
        "dispatch_marker": NOW.isoformat(),
    }
    assert (
        dispatch_routine(dispatcher, definition, scheduled_for=NOW.isoformat())["state"]
        == "dispatched"
    )
    assert (
        dispatch_routine(dispatcher, definition, scheduled_for=NOW.isoformat())["state"]
        == "waiting_review_or_work"
    )
    assert tasks.adds == 1


def test_routine_new_native_occurrence_creates_new_task(fixture):
    from datetime import timedelta

    from hub._services.docs.maintenance_recurring import dispatch_routine

    dispatcher, tasks = fixture
    definition = {
        "name": "help_forensic",
        "legacy_title": "Existing review",
        "priority": "P2",
        "dispatch_marker": NOW.isoformat(),
    }
    dispatch_routine(dispatcher, definition, scheduled_for=NOW.isoformat())
    dispatcher.result_reader = lambda task_id: result(
        task_id, status="done" if task_id == 1 else "pending"
    )
    second = (NOW + timedelta(days=14)).isoformat()
    dispatch_routine(dispatcher, definition, scheduled_for=second)
    assert tasks.adds == 2
    assert tasks.rows[0]["title"] != tasks.rows[1]["title"]


def test_writing_cli_cannot_select_alternate_owner(tmp_path):
    from hub._services.docs.maintenance_cli import handle

    handler = SimpleNamespace(
        base_path=tmp_path / "system", user_db=tmp_path / "bach.db"
    )
    for action in ("configure", "tick", "serve", "launch-plan"):
        ok, message = handle(
            handler, [action, "--runtime-dir", str(tmp_path / "another")]
        )
        assert ok is False and "kanonische" in message
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_id", "private text"),
        ("revision", "private text"),
        ("task_status", "private text"),
        ("result_id", {"secret": 1}),
    ],
)
def test_status_rejects_private_content_in_allowed_fields(tmp_path, field, value):
    data, proc = status_receipt(tmp_path)
    data["documentation"] = {"packages": {"root": {field: value}}}
    (tmp_path / "status.json").write_text(json.dumps(data), encoding="utf-8")
    observed = readonly_status(
        tmp_path, root=tmp_path, now=NOW, process_factory=lambda _: proc
    )
    assert observed["running"] is False
    assert "private text" not in json.dumps(observed)


def test_api_authorizes_before_reading_status(monkeypatch):
    from fastapi import HTTPException
    from gui.api import docs_maintenance, unified_api

    def deny(_):
        raise HTTPException(403, "device required")

    monkeypatch.setattr(unified_api, "_require_memory_device", deny)
    monkeypatch.setattr(
        docs_maintenance,
        "readonly_status",
        lambda *_args, **_options: pytest.fail("Unauthorized read"),
    )
    with pytest.raises(HTTPException) as error:
        docs_maintenance.status(None)
    assert error.value.status_code == 403


def test_invalid_owner_config_blocks_only_doc_legacy(tmp_path):
    from hub._services.docs.maintenance_recurring import delegated_to_maintenance

    directory = tmp_path / "maintenance"
    directory.mkdir()
    directory.joinpath("config.json").write_text("broken", encoding="utf-8")
    assert delegated_to_maintenance(tmp_path / "bach.db", "help_forensic") is True
    assert delegated_to_maintenance(tmp_path / "bach.db", "backup_check") is False


def test_launch_plan_is_portable_and_has_no_side_effect(tmp_path):
    import plistlib
    import sys

    from hub._services.docs.maintenance_launch import launch_plan

    root = tmp_path / "repo"
    local = tmp_path / "local"
    runtime = local / "maintenance"
    script = root / "system/tools/maintenance/scheduler_maintenance.py"
    script.parent.mkdir(parents=True)
    script.touch()
    local.mkdir()
    data = launch_plan(
        root,
        Path(sys.executable).resolve(),
        local / "bach.db",
        runtime,
        runtime / "config.json",
    )
    plist = plistlib.loads(data["launch_agent"].encode("utf-8"))
    assert data["installed"] is False and data["started"] is False
    assert plist["StandardOutPath"] == str(runtime / "scheduler.stdout.log")
    assert plist["StandardErrorPath"] == str(runtime / "scheduler.stderr.log")
    assert plist["Umask"] == "077"
    assert all(
        Path(plist[key]).parent == runtime
        and "onedrive" not in plist[key].casefold()
        for key in ("StandardOutPath", "StandardErrorPath")
    )
    assert not runtime.exists()


def test_cli_launch_plan_preserves_virtual_environment_interpreter(tmp_path, monkeypatch):
    from hub._services.docs import maintenance_cli

    # Model venv symlink resolution without requiring Windows symlink privilege.
    interpreter = tmp_path / "venv" / "bin" / "python"
    resolved = tmp_path / "global" / "python"
    for path in (interpreter, resolved):
        path.parent.mkdir(parents=True)
        path.touch()
    script = tmp_path / "system/tools/maintenance/scheduler_maintenance.py"
    script.parent.mkdir(parents=True)
    script.touch()
    original_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        return resolved if path == interpreter else original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr(maintenance_cli.sys, "executable", str(interpreter))
    handler = SimpleNamespace(base_path=tmp_path / "system", user_db=tmp_path / "bach.db")
    ok, payload = maintenance_cli.handle(handler, ["launch-plan", "--json"])
    assert ok
    plan = json.loads(payload)
    assert plan["program_arguments"][0] == str(interpreter.absolute())
    assert not (tmp_path / "maintenance").exists()
    assert plan["installed"] is False and plan["started"] is False


def test_entrypoint_imports_handler_and_coordinator_from_stage():
    import importlib.util
    import inspect

    from hub import scheduler as scheduler_module
    from hub._services.docs import maintenance_cli

    script = (
        Path(__file__).resolve().parents[1]
        / "tools/maintenance/scheduler_maintenance.py"
    )
    spec = importlib.util.spec_from_file_location(
        "bach_maintenance_entrypoint_test", script
    )
    assert spec is not None and spec.loader is not None
    entrypoint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entrypoint)

    handler_type = entrypoint.load_handler()
    expected_root = entrypoint.SYSTEM_ROOT.resolve()
    assert handler_type is scheduler_module.SchedulerHandler
    assert Path(inspect.getsourcefile(handler_type)).resolve().is_relative_to(
        expected_root
    )
    assert Path(maintenance_cli.__file__).resolve().is_relative_to(expected_root)


def test_cli_failure_writes_redacted_runtime_receipt(tmp_path, monkeypatch, capsys):
    from hub._services.docs import maintenance_cli

    local = tmp_path / "local"
    runtime = local / "maintenance"
    runtime.mkdir(parents=True)
    config_path = runtime / "config.json"
    config_path.write_text(json.dumps(config(tmp_path)), encoding="utf-8")
    root = tmp_path / "repo"
    system = root / "system"
    system.mkdir(parents=True)
    handler = SimpleNamespace(
        base_path=system,
        user_db=local / "bach.db",
        _external_state_db=lambda: local / "scheduler.db",
    )

    class FailingRuntime:
        def __init__(self, *_args, **_options):
            self.stop_event = SimpleNamespace(set=lambda: None)

        def tick(self):
            raise RuntimeError("private_token=do-not-copy")

    monkeypatch.setattr(
        maintenance_cli, "CanonicalLockGuard", lambda _config: lambda _path: None
    )
    monkeypatch.setattr(maintenance_cli, "MaintenanceRuntime", FailingRuntime)

    ok, message = maintenance_cli.handle(handler, ["tick"])
    stderr = capsys.readouterr().err
    receipt = json.loads((runtime / "failure.json").read_text(encoding="utf-8"))

    assert ok is False
    assert "private_token" not in message
    assert "phase=tick exception=RuntimeError" in stderr
    assert "private_token" not in stderr
    assert receipt["schema"] == "bach.maintenance-failure.v1"
    assert receipt["phase"] == "tick"
    assert receipt["exception_class"] == "RuntimeError"
    assert "frames" not in receipt
    assert receipt["owner_generation"] is None
    assert receipt["revision"] is None
    assert "private_token" not in json.dumps(receipt)


def test_cli_serve_failure_writes_redacted_receipt_and_status_stays_fail_closed(
    tmp_path, monkeypatch, capsys
):
    from hub._services.docs import maintenance_cli

    local = tmp_path / "local"
    runtime = local / "maintenance"
    runtime.mkdir(parents=True)
    config_path = runtime / "config.json"
    config_path.write_text(json.dumps(config(tmp_path)), encoding="utf-8")
    root = tmp_path / "repo"
    system = root / "system"
    system.mkdir(parents=True)
    handler = SimpleNamespace(
        base_path=system,
        user_db=local / "bach.db",
        _external_state_db=lambda: local / "scheduler.db",
    )

    class FailingRuntime:
        def __init__(self, *_args, **_options):
            self.stop_event = SimpleNamespace(set=lambda: None)

        def serve(self):
            raise RuntimeError("private_token=do-not-copy")

    monkeypatch.setattr(
        maintenance_cli, "CanonicalLockGuard", lambda _config: lambda _path: None
    )
    monkeypatch.setattr(maintenance_cli, "MaintenanceRuntime", FailingRuntime)
    monkeypatch.setattr(maintenance_cli.signal, "signal", lambda *_args: None)

    ok, message = maintenance_cli.handle(handler, ["serve"])
    stderr = capsys.readouterr().err
    receipt = json.loads((runtime / "failure.json").read_text(encoding="utf-8"))
    status = readonly_status(runtime, root=root, config_path=config_path)

    assert ok is False
    assert "private_token" not in message
    assert "phase=serve exception=RuntimeError" in stderr
    assert "private_token" not in stderr
    assert receipt["schema"] == "bach.maintenance-failure.v1"
    assert receipt["phase"] == "serve"
    assert receipt["exception_class"] == "RuntimeError"
    assert "frames" not in receipt
    assert receipt["owner_generation"] is None
    assert receipt["revision"] is None
    assert "private_token" not in json.dumps(receipt)
    assert status["running"] is False
    assert status.get("identity") in {None, "unknown"}


def test_cli_config_load_failure_reports_receipt_unavailable_without_guard(
    tmp_path, monkeypatch, capsys
):
    from hub._services.docs import maintenance_cli

    local = tmp_path / "local"
    runtime = local / "maintenance"
    runtime.mkdir(parents=True)
    config_path = runtime / "config.json"
    config_path.write_text("{malformed", encoding="utf-8")
    root = tmp_path / "repo"
    system = root / "system"
    system.mkdir(parents=True)
    handler = SimpleNamespace(
        base_path=system,
        user_db=local / "bach.db",
        _external_state_db=lambda: local / "scheduler.db",
    )
    monkeypatch.setattr(
        maintenance_cli,
        "CanonicalLockGuard",
        lambda _config: pytest.fail("guard must not be fabricated before config"),
    )

    ok, _message = maintenance_cli.handle(handler, ["serve"])
    stderr = capsys.readouterr().err
    status = readonly_status(runtime, root=root, config_path=config_path)

    assert ok is False
    assert "phase=config_load exception=JSONDecodeError receipt=unavailable" in stderr
    assert not (runtime / "failure.json").exists()
    assert status["running"] is False
    assert status["reason"] == "no_maintenance_receipt"
    assert "last_failure" not in status


def test_startup_import_failure_reports_receipt_unavailable_without_guard(
    tmp_path, monkeypatch, capsys
):
    import importlib.util

    script = (
        Path(__file__).resolve().parents[1]
        / "tools/maintenance/scheduler_maintenance.py"
    )
    spec = importlib.util.spec_from_file_location(
        "bach_maintenance_startup_failure_test", script
    )
    assert spec is not None and spec.loader is not None
    entrypoint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entrypoint)

    local = tmp_path / "local"
    runtime = local / "maintenance"
    runtime.mkdir(parents=True)
    task_db = local / "bach.db"
    task_db.write_bytes(b"")
    monkeypatch.setenv("BACH_DB", str(task_db))
    monkeypatch.setattr(
        entrypoint.sys,
        "argv",
        [
            str(script),
            "serve",
            "--config",
            str(runtime / "config.json"),
            "--runtime-dir",
            str(runtime),
        ],
    )

    def fail_import():
        raise ImportError("private_token=never-copy-this")

    monkeypatch.setattr(entrypoint, "load_handler", fail_import)
    assert entrypoint.main() == 1
    stderr = capsys.readouterr().err
    assert "phase=handler_import exception=ImportError receipt=unavailable" in stderr
    assert "private_token" not in stderr
    assert not (runtime / "failure.json").exists()


def test_startup_import_failure_uses_validated_native_lock_guard(
    tmp_path, monkeypatch, capsys
):
    import importlib.util

    from hub._services.docs import maintenance_runtime

    script = (
        Path(__file__).resolve().parents[1]
        / "tools/maintenance/scheduler_maintenance.py"
    )
    spec = importlib.util.spec_from_file_location(
        "bach_maintenance_guarded_startup_test", script
    )
    assert spec is not None and spec.loader is not None
    entrypoint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entrypoint)

    local = tmp_path / "local"
    runtime = local / "maintenance"
    runtime.mkdir(parents=True)
    task_db = local / "bach.db"
    config_path = runtime / "config.json"
    expected_config = config(tmp_path)
    config_path.write_text(json.dumps(expected_config), encoding="utf-8")
    monkeypatch.setenv("BACH_DB", str(task_db))
    monkeypatch.setattr(
        entrypoint.sys,
        "argv",
        [
            str(script),
            "serve",
            "--config",
            str(config_path),
            "--runtime-dir",
            str(runtime),
        ],
    )
    guard_calls = []
    guard_configurations = []

    def make_guard(value):
        guard_configurations.append(value)
        return lambda path: guard_calls.append(Path(path))

    monkeypatch.setattr(maintenance_runtime, "CanonicalLockGuard", make_guard)

    def fail_import():
        raise ImportError("private_token=never-copy-this")

    monkeypatch.setattr(entrypoint, "load_handler", fail_import)
    assert entrypoint.main() == 1
    stderr = capsys.readouterr().err
    assert "phase=handler_import exception=ImportError receipt=written" in stderr
    assert "private_token" not in stderr and "Traceback" not in stderr
    assert guard_configurations == [expected_config]
    assert len(guard_calls) == 3
    assert guard_calls[0] == runtime / "failure.json"
    assert guard_calls[1].parent == runtime
    assert guard_calls[1].name.startswith(".failure-")
    assert guard_calls[2] == runtime / "failure.json"
    receipt = json.loads((runtime / "failure.json").read_text(encoding="utf-8"))
    assert receipt["schema"] == "bach.maintenance-failure.v1"
    assert receipt["phase"] == "handler_import"
    assert receipt["exception_class"] == "ImportError"
    assert set(receipt) == {
        "schema",
        "observed_at",
        "phase",
        "exception_class",
        "host",
        "revision",
        "owner_generation",
    }
    assert "private_token" not in json.dumps(receipt)
    assert (runtime / "failure.json").stat().st_mode & 0o777 == 0o600


def test_startup_import_failure_with_denied_lock_guard_is_unavailable(
    tmp_path, monkeypatch, capsys
):
    import importlib.util

    from hub._services.docs import maintenance_runtime

    script = (
        Path(__file__).resolve().parents[1]
        / "tools/maintenance/scheduler_maintenance.py"
    )
    spec = importlib.util.spec_from_file_location(
        "bach_maintenance_denied_startup_test", script
    )
    assert spec is not None and spec.loader is not None
    entrypoint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entrypoint)

    local = tmp_path / "local"
    runtime = local / "maintenance"
    runtime.mkdir(parents=True)
    task_db = local / "bach.db"
    config_path = runtime / "config.json"
    config_path.write_text(json.dumps(config(tmp_path)), encoding="utf-8")
    monkeypatch.setenv("BACH_DB", str(task_db))
    monkeypatch.setattr(
        entrypoint.sys,
        "argv",
        [
            str(script),
            "serve",
            "--config",
            str(config_path),
            "--runtime-dir",
            str(runtime),
        ],
    )
    secret = "private-lock-path-secret"

    def deny_guard(_path):
        raise PermissionError(secret)

    monkeypatch.setattr(
        maintenance_runtime, "CanonicalLockGuard", lambda _config: deny_guard
    )
    monkeypatch.setattr(
        entrypoint,
        "load_handler",
        lambda: (_ for _ in ()).throw(ImportError("private startup secret")),
    )
    assert entrypoint.main() == 1
    stderr = capsys.readouterr().err
    assert "phase=handler_import exception=ImportError receipt=unavailable" in stderr
    assert secret not in stderr and "private startup secret" not in stderr
    assert "Traceback" not in stderr
    assert not (runtime / "failure.json").exists()


@pytest.mark.parametrize("scanner_state", ["missing", "untrusted"])
def test_startup_failure_with_real_lock_guard_fails_closed(
    scanner_state, tmp_path, monkeypatch, capsys
):
    import importlib.util

    from hub._services.docs import maintenance_runtime

    script = (
        Path(__file__).resolve().parents[1]
        / "tools/maintenance/scheduler_maintenance.py"
    )
    spec = importlib.util.spec_from_file_location(
        f"bach_maintenance_real_guard_{scanner_state}_test", script
    )
    assert spec is not None and spec.loader is not None
    entrypoint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entrypoint)

    local = tmp_path / "local"
    runtime = local / "maintenance"
    runtime.mkdir(parents=True)
    task_db = local / "bach.db"
    config_path = runtime / "config.json"
    lock_tools = tmp_path / "lock-tools"
    lock_tools.mkdir()
    expected_config = dict(config(tmp_path))
    expected_config["lock_tools_root"] = str(lock_tools)
    config_path.write_text(json.dumps(expected_config), encoding="utf-8")
    assert maintenance_runtime.load_config(config_path) == expected_config

    if scanner_state == "untrusted":
        (lock_tools / "lock_scan.py").write_text(
            "print('not the pinned scanner')", encoding="utf-8"
        )
        (lock_tools / "lock_utils.py").write_text(
            "def not_the_pinned_lock_utility(): pass", encoding="utf-8"
        )

    monkeypatch.setenv("BACH_DB", str(task_db))
    monkeypatch.setattr(
        entrypoint.sys,
        "argv",
        [
            str(script),
            "serve",
            "--config",
            str(config_path),
            "--runtime-dir",
            str(runtime),
        ],
    )
    secret = "private_startup_failure_must_not_escape"

    def fail_import():
        raise ImportError(secret)

    monkeypatch.setattr(entrypoint, "load_handler", fail_import)
    assert entrypoint.main() == 1
    stderr = capsys.readouterr().err
    assert "phase=handler_import exception=ImportError receipt=unavailable" in stderr
    assert secret not in stderr
    assert str(lock_tools) not in stderr
    assert "Traceback" not in stderr
    assert not (runtime / "failure.json").exists()


def test_startup_failure_rejects_wrong_maintenance_runtime_origin(
    tmp_path, monkeypatch, capsys
):
    import importlib.util

    from hub._services.docs import maintenance_runtime

    script = (
        Path(__file__).resolve().parents[1]
        / "tools/maintenance/scheduler_maintenance.py"
    )
    spec = importlib.util.spec_from_file_location(
        "bach_maintenance_wrong_runtime_origin_test", script
    )
    assert spec is not None and spec.loader is not None
    entrypoint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entrypoint)

    local = tmp_path / "local"
    runtime = local / "maintenance"
    runtime.mkdir(parents=True)
    task_db = local / "bach.db"
    config_path = runtime / "config.json"
    config_path.write_text(json.dumps(config(tmp_path)), encoding="utf-8")
    monkeypatch.setenv("BACH_DB", str(task_db))
    monkeypatch.setattr(
        entrypoint.sys,
        "argv",
        [
            str(script),
            "serve",
            "--config",
            str(config_path),
            "--runtime-dir",
            str(runtime),
        ],
    )
    wrong_origin = tmp_path / "private-origin" / "maintenance_runtime.py"
    monkeypatch.setattr(maintenance_runtime, "__file__", str(wrong_origin))

    def fail_import():
        raise ImportError("private startup path")

    monkeypatch.setattr(entrypoint, "load_handler", fail_import)
    assert entrypoint.main() == 1
    stderr = capsys.readouterr().err
    assert "phase=handler_import exception=ImportError receipt=unavailable" in stderr
    assert "private startup path" not in stderr
    assert str(wrong_origin) not in stderr
    assert "Traceback" not in stderr
    assert not (runtime / "failure.json").exists()


def test_launcher_bad_configured_path_does_not_mask_primary_failure(
    tmp_path, monkeypatch, capsys
):
    import importlib.util

    script = (
        Path(__file__).resolve().parents[1]
        / "tools/maintenance/scheduler_maintenance.py"
    )
    spec = importlib.util.spec_from_file_location(
        "bach_maintenance_bad_configured_path_test", script
    )
    assert spec is not None and spec.loader is not None
    entrypoint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entrypoint)
    private_component = "private-token-no-output"
    malformed_root = tmp_path / private_component
    malformed_root.symlink_to(malformed_root)
    malformed_db = malformed_root / "bach.db"
    monkeypatch.setenv("BACH_DB", str(malformed_db))
    monkeypatch.setattr(entrypoint.sys, "argv", [str(script), "serve"])

    def fail_import():
        raise ImportError("primary startup failure")

    monkeypatch.setattr(entrypoint, "load_handler", fail_import)
    assert entrypoint.main() == 1
    stderr = capsys.readouterr().err
    assert "phase=handler_import exception=ImportError receipt=unavailable" in stderr
    assert "primary startup failure" not in stderr
    assert private_component not in stderr
    assert "Traceback" not in stderr
    assert list(tmp_path.iterdir()) == [malformed_root]


def test_launcher_handler_dispatch_failure_is_redacted(tmp_path, monkeypatch, capsys):
    import importlib.util

    script = (
        Path(__file__).resolve().parents[1]
        / "tools/maintenance/scheduler_maintenance.py"
    )
    spec = importlib.util.spec_from_file_location(
        "bach_maintenance_dispatch_failure_test", script
    )
    assert spec is not None and spec.loader is not None
    entrypoint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entrypoint)
    local = tmp_path / "local"
    runtime = local / "maintenance"
    runtime.mkdir(parents=True)
    task_db = local / "bach.db"
    task_db.write_bytes(b"")
    monkeypatch.setenv("BACH_DB", str(task_db))
    monkeypatch.setattr(
        entrypoint.sys,
        "argv",
        [
            str(script),
            "serve",
            "--config",
            str(runtime / "config.json"),
            "--runtime-dir",
            str(runtime),
        ],
    )

    class FailingHandler:
        def __init__(self, _root):
            pass

        def handle(self, *_args):
            raise RuntimeError("private_token=dispatch-secret")

    monkeypatch.setattr(entrypoint, "load_handler", lambda: FailingHandler)
    assert entrypoint.main() == 1
    stderr = capsys.readouterr().err
    assert "phase=handler_dispatch exception=RuntimeError receipt=unavailable" in stderr
    assert "private_token" not in stderr
    assert not (runtime / "failure.json").exists()


def test_failure_receipt_writer_failure_does_not_mask_primary_cli_error(
    tmp_path, monkeypatch, capsys
):
    from hub._services.docs import maintenance_cli

    local = tmp_path / "local"
    runtime = local / "maintenance"
    runtime.mkdir(parents=True)
    config_path = runtime / "config.json"
    config_path.write_text(json.dumps(config(tmp_path)), encoding="utf-8")
    root = tmp_path / "repo"
    system = root / "system"
    system.mkdir(parents=True)
    handler = SimpleNamespace(
        base_path=system,
        user_db=local / "bach.db",
        _external_state_db=lambda: local / "scheduler.db",
    )

    class FailingRuntime:
        def __init__(self, *_args, **_options):
            self.failure_phase = "scheduler_tick"
            self._failure_owner_generation = None

        def tick(self):
            raise RuntimeError("private_token=primary")

    monkeypatch.setattr(
        maintenance_cli, "CanonicalLockGuard", lambda _config: lambda _path: None
    )
    monkeypatch.setattr(maintenance_cli, "MaintenanceRuntime", FailingRuntime)

    def fail_receipt(*_args, **_kwargs):
        raise OSError("private_token=secondary")

    monkeypatch.setattr(maintenance_cli, "write_failure_receipt", fail_receipt)
    ok, message = maintenance_cli.handle(handler, ["tick"])
    stderr = capsys.readouterr().err
    assert ok is False
    assert "private_token" not in message
    assert "exception=RuntimeError receipt=unavailable" in stderr
    assert "private_token" not in stderr


def test_failure_receipt_readback_rejects_stale_and_malformed(tmp_path):
    from hub._services.docs.maintenance_failure import write_failure_receipt

    local = tmp_path / "local"
    runtime = local / "maintenance"
    runtime.mkdir(parents=True)
    task_db = local / "bach.db"
    assert write_failure_receipt(
        runtime,
        tmp_path,
        "serve",
        RuntimeError("private_token=never-copy"),
        guard=lambda _path: None,
        task_db=task_db,
        now=NOW,
    )
    stale = readonly_status(runtime, root=tmp_path, now=NOW.replace(day=12))
    assert stale["running"] is False
    assert stale["reason"] == "maintenance_failure_stale"
    data = json.loads((runtime / "failure.json").read_text(encoding="utf-8"))
    data["private_payload"] = "secret"
    (runtime / "failure.json").write_text(json.dumps(data), encoding="utf-8")
    invalid = readonly_status(runtime, root=tmp_path, now=NOW)
    assert invalid["running"] is False
    assert invalid["reason"] == "maintenance_failure_unverified"
    assert "last_failure" not in invalid


def test_serve_cleanup_write_does_not_mask_primary_status_error(
    tmp_path, monkeypatch
):
    from contextlib import contextmanager

    import hub._services.docs.maintenance_runtime as module

    config_path = tmp_path / "maintenance/config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(config(tmp_path)), encoding="utf-8")
    service = object.__new__(MaintenanceRuntime)
    service.config = config(tmp_path)
    service.config_path = config_path
    service.owner_path = config_path.parent / "owner.lock"
    service.guard = lambda _path: None
    service.root = tmp_path
    service.runtime = config_path.parent
    service.generation = "a" * 32
    service._owner_thread = None
    service._failure_owner_generation = None
    service.failure_phase = "owner_acquire"
    service.stop_event = SimpleNamespace(is_set=lambda: False, wait=lambda _s: None)
    service.clock = lambda: NOW
    service.tick = lambda: {"state": "running", "runs": []}
    service.run_receipts = list
    service.job_receipts = list

    @contextmanager
    def owner(_path, _guard):
        yield

    writes = []

    def fail_writes(*_args, **_kwargs):
        writes.append(True)
        if len(writes) == 1:
            raise RuntimeError("primary status failure")
        raise OSError("secondary cleanup failure")

    monkeypatch.setattr(module, "process_owner", owner)
    monkeypatch.setattr(module, "_write_status", fail_writes)
    with pytest.raises(RuntimeError, match="primary status failure"):
        service.serve(max_ticks=1)
    assert len(writes) == 2
    assert service.failure_phase == "status_write"
    assert service._failure_owner_generation == service.generation


def test_failure_writer_requires_an_available_lock_guard(tmp_path):
    from hub._services.docs.maintenance_failure import write_failure_receipt

    local = tmp_path / "local"
    runtime = local / "maintenance"
    runtime.mkdir(parents=True)
    task_db = local / "bach.db"
    error = RuntimeError("private_token=never-copy")

    assert not write_failure_receipt(
        runtime, tmp_path, "serve", error, task_db=task_db
    )

    def unavailable_guard(_path):
        raise OSError("private lock details")

    assert not write_failure_receipt(
        runtime,
        tmp_path,
        "serve",
        error,
        guard=unavailable_guard,
        task_db=task_db,
    )
    assert not (runtime / "failure.json").exists()


def test_failure_writer_is_unavailable_without_fchmod(tmp_path, monkeypatch):
    import hub._services.docs.maintenance_failure as module

    local = tmp_path / "local"
    runtime = local / "maintenance"
    runtime.mkdir(parents=True)
    task_db = local / "bach.db"
    monkeypatch.delattr(module.os, "fchmod", raising=False)

    assert not module.write_failure_receipt(
        runtime,
        tmp_path,
        "serve",
        RuntimeError("private_token=never-copy"),
        guard=lambda _path: None,
        task_db=task_db,
    )
    assert not (runtime / "failure.json").exists()


def test_failure_writer_rejects_noncanonical_output_location(tmp_path):
    from hub._services.docs.maintenance_failure import write_failure_receipt

    local = tmp_path / "local"
    runtime = local / "maintenance"
    runtime.mkdir(parents=True)
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    assert not write_failure_receipt(
        elsewhere,
        tmp_path,
        "serve",
        RuntimeError("no"),
        guard=lambda _path: None,
        task_db=local / "bach.db",
    )
    assert not (elsewhere / "failure.json").exists()


def test_status_does_not_project_nested_private_values(tmp_path):
    data, proc = status_receipt(tmp_path)
    data["documentation"] = {
        "packages": {"root": {"task_id": 7, "secret": "not visible"}}
    }
    data["runs"] = [
        {"job_id": "bach.docs.delta", "status": "succeeded", "output": "not visible"}
    ]
    (tmp_path / "status.json").write_text(json.dumps(data), encoding="utf-8")
    observed = readonly_status(
        tmp_path, root=tmp_path, now=NOW, process_factory=lambda _: proc
    )
    assert "secret" not in observed["documentation"]["packages"]["root"]
    assert "output" not in observed["runs"][0]


def test_readonly_status_absent_has_no_effect(tmp_path):
    assert readonly_status(tmp_path, root=tmp_path)["running"] is False
    assert not list(tmp_path.iterdir())


def status_receipt(tmp_path):
    cp = tmp_path / "config.json"
    cp.write_text(json.dumps(config(tmp_path)), encoding="utf-8")
    data = {
        "schema": STATUS_SCHEMA,
        "service": "bach-docs-maintenance",
        "pid": 123,
        "root_id": hashlib.sha256(str(tmp_path.resolve()).encode()).hexdigest(),
        "config_hash": hashlib.sha256(cp.read_bytes()).hexdigest(),
        "poll_seconds": 60,
        "observed_at": NOW.isoformat(),
        "create_time": 10.0,
        "state": "running",
        "generation": "a" * 32,
        "provider": "ellmos-scheduler",
        "semantic_review_completed": False,
    }
    (tmp_path / "status.json").write_text(json.dumps(data), encoding="utf-8")
    proc = SimpleNamespace(
        is_running=lambda: True,
        create_time=lambda: 10.0,
        cmdline=lambda: [
            "python",
            str(tmp_path / "system/tools/maintenance/scheduler_maintenance.py"),
            "serve",
        ],
    )
    return data, proc


def test_status_needs_process_command_birth_and_current_config(tmp_path):
    _data, proc = status_receipt(tmp_path)
    read = lambda: readonly_status(
        tmp_path, root=tmp_path, now=NOW, process_factory=lambda _: proc
    )
    assert read()["running"] is True
    proc.cmdline = lambda: ["unrelated-process"]
    assert read()["running"] is False
    assert "documentation" not in read()


def test_status_rejects_stale_heartbeat_and_foreign_fields(tmp_path):
    data, proc = status_receipt(tmp_path)
    data["observed_at"] = datetime(2026, 10, 9, tzinfo=timezone.utc).isoformat()
    data["private_token"] = "never_project"
    (tmp_path / "status.json").write_text(json.dumps(data), encoding="utf-8")
    observed = readonly_status(
        tmp_path, root=tmp_path, now=NOW, process_factory=lambda _: proc
    )
    assert observed["running"] is False
    assert "private_token" not in observed


def test_status_script_argument_is_not_an_entrypoint(tmp_path):
    _data, proc = status_receipt(tmp_path)
    proc.cmdline = lambda: [
        "python",
        "-c",
        "other code",
        str(tmp_path / "system/tools/maintenance/scheduler_maintenance.py"),
        "serve",
    ]
    assert (
        readonly_status(
            tmp_path, root=tmp_path, now=NOW, process_factory=lambda _: proc
        )["running"]
        is False
    )


def test_busy_skips_native_engine_and_task_api(tmp_path, monkeypatch):
    cp = tmp_path / "config.json"
    cp.write_text(json.dumps(config(tmp_path)), encoding="utf-8")
    tasks = FakeTasks()
    service = MaintenanceRuntime(
        tmp_path,
        tmp_path / "scheduler.db",
        tmp_path,
        cp,
        task_api=tasks,
        result_reader=result,
        guard=lambda _: None,
    )
    monkeypatch.setattr("psutil.virtual_memory", lambda: SimpleNamespace(available=1))
    assert service.tick() == {"state": "busy", "runs": []}
    assert tasks.adds == 0
    assert not (tmp_path / "scheduler.db").exists()


def test_job_receipts_use_scheduler_facade_last_success_without_store_access():
    success_at = "2026-10-12T10:15:00+00:00"
    rows = [
        {
            "id": "bach.docs.delta",
            "is_active": True,
            "next_run": "2026-10-13T10:00:00+00:00",
            "last_result": "failed",
            "last_success": success_at,
        },
        {
            "id": "bach.docs.routine.help_forensic",
            "is_active": False,
            "next_run": "2026-10-20T10:00:00+00:00",
            "last_success": None,
        },
        {"id": "other.job"},
    ]

    class AdapterFacade:
        def __init__(self):
            self.calls = 0

        def jobs(self):
            self.calls += 1
            return rows

        @property
        def store(self):
            raise AssertionError("job receipts must use the scheduler facade")

    adapter = AdapterFacade()
    service = SimpleNamespace(adapter=adapter)
    assert MaintenanceRuntime.job_receipts(service) == [
        {
            "id": "bach.docs.delta",
            "enabled": True,
            "next_due_at": "2026-10-13T10:00:00+00:00",
            "last_success": success_at,
        },
        {
            "id": "bach.docs.routine.help_forensic",
            "enabled": False,
            "next_due_at": "2026-10-20T10:00:00+00:00",
            "last_success": None,
        },
    ]
    assert adapter.calls == 1


@pytest.mark.parametrize(
    "adapter",
    [
        SimpleNamespace(store=object()),
        SimpleNamespace(
            jobs=lambda: [
                {
                    "id": "bach.docs.delta",
                    "is_active": True,
                    "next_run": "2026-10-13T10:00:00+00:00",
                }
            ]
        ),
        SimpleNamespace(
            jobs=lambda: [
                {
                    "id": "bach.docs.delta",
                    "is_active": True,
                    "next_run": "2026-10-13T10:00:00+00:00",
                    "last_success": 1,
                }
            ]
        ),
    ],
)
def test_job_receipts_fail_closed_without_valid_last_success_facade(adapter):
    with pytest.raises(SchedulerFacadeUnavailable):
        MaintenanceRuntime.job_receipts(SimpleNamespace(adapter=adapter))


def test_prepare_rejects_scheduler_without_projection_before_store_access(
    tmp_path, monkeypatch
):
    from hub._services.docs import maintenance_runtime as module

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config(tmp_path)), encoding="utf-8")
    (tmp_path / "system/data").mkdir(parents=True)
    service = MaintenanceRuntime(
        tmp_path,
        tmp_path / "scheduler.db",
        tmp_path / "runtime",
        config_path,
        task_api=FakeTasks(),
        result_reader=result,
        guard=lambda _: None,
        clock=lambda: NOW,
    )
    store_calls = []

    class Store:
        def list_jobs(self):
            store_calls.append("list")
            return []

        def add_job(self, *_args, **_kwargs):
            store_calls.append("add")

    adapter = SimpleNamespace(store=Store())
    monkeypatch.setattr(module, "routine_definitions", lambda *_args: [])
    monkeypatch.setattr(module, "create_documentation_scheduler", lambda *_args, **_kwargs: adapter)
    with pytest.raises(SchedulerFacadeUnavailable):
        service._prepare()
    assert store_calls == []
    assert not (tmp_path / "scheduler.db").exists()


def test_native_module_runs_only_docs_job(tmp_path):
    pytest.importorskip("ellmos_scheduler")
    cp = tmp_path / "config.json"
    cp.write_text(json.dumps(config(tmp_path)), encoding="utf-8")
    tasks = FakeTasks()
    when = [NOW]
    from hub._services.docs.maintenance_recurring import ROUTINES

    directory = tmp_path / "system/hub/_services/recurring"
    directory.mkdir(parents=True)
    directory.joinpath("config.json").write_text(
        json.dumps(
            {
                "recurring_tasks": {
                    name: {
                        "enabled": True,
                        "interval_days": 14,
                        "target": "tasks",
                        "last_run": NOW.isoformat(),
                        "task_text": "Existing " + name,
                    }
                    for name in ROUTINES
                }
            }
        ),
        encoding="utf-8",
    )
    service = MaintenanceRuntime(
        tmp_path,
        tmp_path / "scheduler.db",
        tmp_path / "runtime",
        cp,
        task_api=tasks,
        result_reader=result,
        guard=lambda _: None,
        clock=lambda: when[0],
    )
    service.dispatcher.snapshot = lambda *_: (REV, ["README.md"])
    first = service.tick()
    assert len(first["runs"]) == 1
    assert first["runs"][0]["status"] == "succeeded"
    assert tasks.adds == 1
    assert service.tick()["runs"] == []
    jobs = service.adapter.store.list_jobs()
    assert len(jobs) == 5
    first_success_at = next(
        row["finished_at"]
        for row in service.run_receipts()
        if row["job_id"] == first["runs"][0]["job_id"]
    )
    receipts = {row["id"]: row for row in service.job_receipts()}
    assert len(receipts) == 5
    assert receipts["bach.docs.delta"]["last_success"] == first_success_at
    assert len(service.run_receipts()) == 1
    assert len(service.run_receipts()[0]["run_id"]) == 64
    assert service.adapter.service.registry.names() == ("bach-docs",)
    assert (
        read_state(service.dispatcher.state_path)["packages"]["root"][
            "last_repair_success"
        ]
        is None
    )
    from datetime import timedelta

    # Native occurrence supplies the dedup key, including a second full cycle.
    routine_id = "bach.docs.routine.help_forensic"
    when[0] = NOW + timedelta(days=14)
    first_routine = service.adapter.service.tick(
        now=when[0], limit=1, job_ids=[routine_id]
    )
    assert first_routine[0]["status"] == "succeeded"
    assert tasks.adds == 2
    service.dispatcher.result_reader = lambda task_id: result(
        task_id, status="done" if task_id == 2 else "pending"
    )
    when[0] = NOW + timedelta(days=28)
    second_routine = service.adapter.service.tick(
        now=when[0], limit=1, job_ids=[routine_id]
    )
    assert second_routine[0]["status"] == "succeeded"
    assert tasks.adds == 3
    assert tasks.rows[-2]["title"] != tasks.rows[-1]["title"]

    # Recover native failure backoff in a fresh owner instance.
    def failed_snapshot(*_):
        raise RuntimeError("bounded source failure")

    service.dispatcher.snapshot = failed_snapshot
    failure = service.tick()
    assert failure["runs"][0]["status"] == "failed"
    assert failure["runs"][0]["job_id"] == "bach.docs.delta"
    latest_success = {row["id"]: row for row in service.job_receipts()}
    assert latest_success["bach.docs.delta"]["last_success"] == first_success_at
    restarted = MaintenanceRuntime(
        tmp_path,
        tmp_path / "scheduler.db",
        tmp_path / "runtime",
        cp,
        task_api=tasks,
        result_reader=result,
        guard=lambda _: None,
        clock=lambda: when[0],
    )
    assert restarted.tick()["state"] == "backoff"
    assert tasks.adds == 3


def test_provider_neutral_cli_uses_owner_request_ack_and_physical_cas(
    tmp_path, monkeypatch
):
    import threading
    import time

    from hub._services.docs import maintenance_cli, maintenance_runtime

    local = tmp_path / "local"
    runtime_dir = local / "maintenance"
    runtime_dir.mkdir(parents=True)
    config_path = runtime_dir / "config.json"
    before = config(tmp_path)
    before["worker_binding"] = {
        "assigned_slot": "worker-5c70b1e2",
        "required_model": "glm-5.3:cloud",
    }
    config_bytes = json.dumps(before, ensure_ascii=False, indent=2).encode("utf-8")
    config_path.write_bytes(config_bytes)
    generation = "a" * 32
    (runtime_dir / "status.json").write_text(
        json.dumps(
            {
                "generation": generation,
                "config_hash": hashlib.sha256(config_bytes).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    guard_calls = []

    def guard(path):
        guard_calls.append(Path(path))

    monkeypatch.setattr(
        maintenance_runtime, "CanonicalLockGuard", lambda _config: guard
    )
    monkeypatch.setattr(
        maintenance_runtime,
        "readonly_status",
        lambda *_args, **_kwargs: {
            "running": True,
            "identity": "verified",
            "generation": generation,
        },
    )
    service = MaintenanceRuntime(
        tmp_path,
        local / "scheduler.db",
        runtime_dir,
        config_path,
        task_api=FakeTasks(),
        result_reader=result,
        guard=guard,
        task_db=local / "bach.db",
        clock=lambda: NOW,
    )
    service.generation = generation
    request_path = runtime_dir / "worker-binding.request.json"
    consumed = []

    def owner_loop():
        deadline = time.monotonic() + 5
        while not request_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        with process_owner(service.owner_path, guard):
            service._failure_owner_generation = generation
            service._owner_thread = threading.get_ident()
            try:
                consumed.append(service._consume_provider_neutral_request())
            finally:
                service._owner_thread = None

    owner = threading.Thread(target=owner_loop)
    owner.start()
    handler = SimpleNamespace(
        base_path=tmp_path / "system",
        user_db=local / "bach.db",
    )
    ok, payload = maintenance_cli.handle(
        handler, ["provider-neutral", "--wait-seconds", "5"]
    )
    owner.join(5)

    assert not owner.is_alive() and consumed == [True]
    assert ok is True, payload
    outcome = json.loads(payload)
    assert outcome["status"] == "applied" and outcome["readback"] is True
    actual = json.loads(config_path.read_text(encoding="utf-8"))
    assert {key: value for key, value in actual.items() if key != "worker_binding"} == {
        key: value for key, value in before.items() if key != "worker_binding"
    }
    assert actual["worker_binding"] == {}
    assert service.config == actual and service.dispatcher.binding == {}
    request_bytes = request_path.read_bytes()
    ack_path = runtime_dir / "worker-binding.ack.json"
    ack = json.loads(ack_path.read_text(encoding="utf-8"))
    assert ack["request_sha256"] == hashlib.sha256(request_bytes).hexdigest()
    assert ack["request_generation"] == ack["owner_generation"] == generation
    assert ack["new_config_sha256"] == hashlib.sha256(config_path.read_bytes()).hexdigest()
    assert request_path.stat().st_mode & 0o777 == 0o600
    assert ack_path.stat().st_mode & 0o777 == 0o600
    assert config_path in guard_calls and request_path in guard_calls and ack_path in guard_calls


def test_provider_neutral_cli_timeout_reuses_the_same_private_request(
    tmp_path, monkeypatch
):
    from hub._services.docs import maintenance_runtime

    local = tmp_path / "local"
    runtime_dir = local / "maintenance"
    runtime_dir.mkdir(parents=True)
    config_path = runtime_dir / "config.json"
    before = config(tmp_path)
    before["worker_binding"] = {"required_model": "glm-5.3:cloud"}
    config_path.write_text(json.dumps(before, indent=2), encoding="utf-8")
    config_bytes = config_path.read_bytes()
    generation = "b" * 32
    (runtime_dir / "status.json").write_text(
        json.dumps(
            {
                "generation": generation,
                "config_hash": hashlib.sha256(config_bytes).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(maintenance_runtime, "CanonicalLockGuard", lambda _cfg: lambda _path: None)
    monkeypatch.setattr(
        maintenance_runtime,
        "readonly_status",
        lambda *_args, **_kwargs: {
            "running": True,
            "identity": "verified",
            "generation": generation,
        },
    )

    first = maintenance_runtime.request_provider_neutral_binding(
        tmp_path, runtime_dir, config_path, timeout_seconds=0
    )
    request_path = runtime_dir / "worker-binding.request.json"
    first_request = request_path.read_bytes()
    second = maintenance_runtime.request_provider_neutral_binding(
        tmp_path, runtime_dir, config_path, timeout_seconds=0
    )

    assert first["status"] == second["status"] == "unknown"
    assert first["error_code"] == second["error_code"] == "maintenance_binding_ack_timeout"
    assert first["request_retained"] is second["request_retained"] is True
    assert request_path.read_bytes() == first_request
    assert json.loads(first_request)["nonce"] == json.loads(request_path.read_bytes())["nonce"]
    assert request_path.stat().st_mode & 0o777 == 0o600
    assert not (runtime_dir / "worker-binding.ack.json").exists()


def test_provider_neutral_dispatch_creates_future_tasks_without_slot_or_model(
    native_task_proxy, tmp_path
):
    dispatcher = DocumentationDispatcher(
        tmp_path,
        tmp_path / "provider-neutral.json",
        native_task_proxy,
        result,
        lambda _path: None,
        snapshot=lambda *_args: (REV, ["docs/README.md"]),
        clock=lambda: NOW,
        binding={},
    )

    receipt = dispatcher.dispatch()
    row = native_task_proxy.show(receipt["task_id"])

    assert row["assigned_to"] == "BACH"
    assert row.get("assigned_slot") in (None, "")
    assert row.get("required_model") in (None, "")


def _provider_neutral_fixture(tmp_path, monkeypatch, generation):
    from hub._services.docs import maintenance_runtime

    local = tmp_path / "local"
    runtime_dir = local / "maintenance"
    runtime_dir.mkdir(parents=True)
    config_path = runtime_dir / "config.json"
    initial = config(tmp_path)
    initial["worker_binding"] = {
        "assigned_slot": "worker-5c70b1e2",
        "required_model": "glm-5.3:cloud",
    }
    config_bytes = json.dumps(initial, ensure_ascii=False, indent=2).encode("utf-8")
    config_path.write_bytes(config_bytes)
    (runtime_dir / "status.json").write_text(
        json.dumps(
            {
                "generation": generation,
                "config_hash": hashlib.sha256(config_bytes).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    guard = lambda _path: None
    monkeypatch.setattr(
        maintenance_runtime, "CanonicalLockGuard", lambda _config: guard
    )
    monkeypatch.setattr(
        maintenance_runtime,
        "readonly_status",
        lambda *_args, **_kwargs: {
            "running": True,
            "identity": "verified",
            "generation": generation,
        },
    )
    service = MaintenanceRuntime(
        tmp_path,
        local / "scheduler.db",
        runtime_dir,
        config_path,
        task_api=FakeTasks(),
        result_reader=result,
        guard=guard,
        task_db=local / "bach.db",
        clock=lambda: NOW,
    )
    service.generation = generation
    return maintenance_runtime, service, runtime_dir, config_path, config_bytes, guard


def test_provider_neutral_request_is_owner_and_generation_bound(
    tmp_path, monkeypatch
):
    import threading

    runtime_module, service, runtime_dir, config_path, before_bytes, guard = (
        _provider_neutral_fixture(tmp_path, monkeypatch, "c" * 32)
    )
    queued = runtime_module.request_provider_neutral_binding(
        tmp_path, runtime_dir, config_path, timeout_seconds=0
    )
    assert queued["status"] == "unknown"
    request_path = runtime_dir / "worker-binding.request.json"
    assert service._consume_provider_neutral_request() is False
    assert config_path.read_bytes() == before_bytes

    service.generation = "d" * 32
    with process_owner(service.owner_path, guard):
        service._failure_owner_generation = service.generation
        service._owner_thread = threading.get_ident()
        try:
            assert service._consume_provider_neutral_request() is True
        finally:
            service._owner_thread = None

    ack = json.loads((runtime_dir / "worker-binding.ack.json").read_text("utf-8"))
    assert ack["status"] == "rejected"
    assert ack["error_code"] == "maintenance_generation_conflict"
    assert ack["request_generation"] == "c" * 32
    assert ack["owner_generation"] == "d" * 32
    assert config_path.read_bytes() == before_bytes
    assert service.dispatcher.binding == json.loads(before_bytes)["worker_binding"]
    assert request_path.stat().st_mode & 0o777 == 0o600


def test_provider_neutral_request_cannot_change_other_config_fields(
    tmp_path, monkeypatch
):
    import threading

    runtime_module, service, runtime_dir, config_path, before_bytes, guard = (
        _provider_neutral_fixture(tmp_path, monkeypatch, "e" * 32)
    )
    queued = runtime_module.request_provider_neutral_binding(
        tmp_path, runtime_dir, config_path, timeout_seconds=0
    )
    assert queued["status"] == "unknown"
    request_path = runtime_dir / "worker-binding.request.json"
    request = json.loads(request_path.read_text("utf-8"))
    desired = dict(request["desired_config"])
    desired["poll_seconds"] = 61
    request["desired_config"] = desired
    request["desired_config_sha256"] = runtime_module._binding_digest(
        runtime_module._configuration_bytes(desired)
    )
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    request_path.chmod(0o600)

    with process_owner(service.owner_path, guard):
        service._failure_owner_generation = service.generation
        service._owner_thread = threading.get_ident()
        try:
            assert service._consume_provider_neutral_request() is True
        finally:
            service._owner_thread = None

    ack = json.loads((runtime_dir / "worker-binding.ack.json").read_text("utf-8"))
    assert ack["status"] == "rejected"
    assert ack["error_code"] == "maintenance_binding_conflict"
    assert config_path.read_bytes() == before_bytes
    assert service.config["poll_seconds"] == 60
    assert service.dispatcher.binding == json.loads(before_bytes)["worker_binding"]
