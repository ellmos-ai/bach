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
        assert args[args.index("--assign") + 1] == "bach"
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
                "assigned_to": fields["assign"],
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
    import sys

    from hub._services.docs.maintenance_launch import launch_plan

    script = tmp_path / "system/tools/maintenance/scheduler_maintenance.py"
    script.parent.mkdir(parents=True)
    script.touch()
    data = launch_plan(
        tmp_path,
        Path(sys.executable).resolve(),
        tmp_path / "bach.db",
        tmp_path / "runtime",
        tmp_path / "runtime/config.json",
    )
    assert data["installed"] is False and data["started"] is False
    assert not (tmp_path / "runtime").exists()


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
    assert len(service.job_receipts()) == 5
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
