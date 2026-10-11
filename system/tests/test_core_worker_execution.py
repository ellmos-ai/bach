"""Core Always-On uses the owned native controller, without live inference."""
import importlib
import json

import pytest

from hub._services.chat import slots_config
from hub._services.chat.chat_runtime import ChatSession, ChatRuntime, FailedAnswer
from hub._services.task_lease_client import TaskLeaseClient
from hub._services import task_lease_client as lease_module
from system.tests.test_task_lease_client import mem_db


CORE = "buddha_always_on"


@pytest.fixture
def core_file(tmp_path, monkeypatch):
    path = str(tmp_path / "slots.json")
    slots_config.initialize_slots_config(path)
    monkeypatch.setattr(slots_config, "DEFAULT_SLOTS_FILE", path)
    control = importlib.import_module("hub._services.chat.telegram_chat")
    monkeypatch.setattr(control, "_WORKER_EXECUTIONS", {})
    slots_config.update_slot(CORE, {"model": "selected-model", "backend": "openrouter",
        "mode": "safe", "think": False, "max_tool_rounds": 7,
        "pause_basis": "tasks", "task_id": 42}, path)
    return path


def test_core_execution_reader_keeps_exact_identity_and_configuration(core_file):
    slot = slots_config.get_always_on_execution_slot(core_file)
    assert slot["id"] == CORE and slot["chat_id"] == "idle-worker"
    assert slot["type"] == "continuous" and slot["sub_mode"] == "task_worker"
    assert slot["model"] == "selected-model" and slot["backend"] == "openrouter"
    assert slot["mode"] == "safe" and slot["think"] is False and slot["max_tool_rounds"] == 7
    assert slot["pause_basis"] == "tasks" and slot["pickup_filter"]["categories"] == ["INBOX"]
    assert slots_config.get_worker_slot(CORE, core_file) == {}
    assert "type" not in slots_config.get_slot(CORE, core_file)  # Reader does not rewrite storage.


@pytest.mark.parametrize("bad", ["missing-core", "wrong-id", "duplicate", "untyped-enabled", "malformed-workers"])
def test_core_execution_reader_fails_closed(core_file, bad):
    with open(core_file, encoding="utf-8") as stream:
        config = json.load(stream)
    if bad == "missing-core":
        del config["slots"][CORE]
    elif bad == "wrong-id":
        config["slots"][CORE]["id"] = "idle-worker"
    elif bad == "duplicate":
        config["dynamic_workers"].append({"id": CORE})
    elif bad == "untyped-enabled":
        config["slots"][CORE]["enabled"] = "true"
    else:
        config["dynamic_workers"] = {}
    with open(core_file, "w", encoding="utf-8") as stream:
        json.dump(config, stream)
    with pytest.raises(ValueError):
        slots_config.get_always_on_execution_slot(core_file)


@pytest.mark.parametrize("outcome", ["done", "review"])
@pytest.mark.parametrize("idle_polls", [0, 3])
def test_core_worker_acquires_exact_bound_tasks_and_advances(core_file, monkeypatch, mem_db, outcome, idle_polls):
    control = importlib.import_module("hub._services.chat.telegram_chat")
    session = ChatSession()
    session.chat_id = CORE
    calls, assignments, endings, pauses = [], [], [], []
    activities = []
    mem_db.executemany("INSERT INTO tasks (id,title,status,priority,category,assigned_to,assigned_slot) "
        "VALUES (?,?,'pending',?,'INBOX','BACH',?)",
        [(42, "First core task", "P1", CORE), (43, "Second core task", "P2", CORE)])
    mem_db.commit()
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    monkeypatch.setattr(lease_module, "get_lead_config", lambda: {"mode": "isolated"})
    monkeypatch.setattr(control, "_native_task_client", lambda: TaskLeaseClient(conn=mem_db))
    monkeypatch.setattr(control, "record_activity", lambda *args, **kw: activities.append(args))
    monkeypatch.setattr(control.runtime, "get_session", lambda ident: session)
    monkeypatch.setattr(control, "begin_assignment", lambda **kw: assignments.append(kw) or kw)
    monkeypatch.setattr(control, "finish_assignment", lambda assignment, **kw: endings.append(kw))
    original_acquire = control._acquire_worker_task
    acquire_calls = []
    def acquire_after_idle(*args, **kwargs):
        acquire_calls.append(True)
        if len(acquire_calls) <= idle_polls:
            assert calls == []
            return None
        return original_acquire(*args, **kwargs)
    monkeypatch.setattr(control, "_acquire_worker_task", acquire_after_idle)

    def snapshot(ident, *, worker_slot=None):
        assert ident == CORE and worker_slot["id"] == CORE
        assert worker_slot["model"] == "selected-model" and worker_slot["backend"] == "openrouter"
        return object(), "selected-model"
    monkeypatch.setattr(control, "_snapshot_chat_backend", snapshot)

    async def process(prompt, ident, **kw):
        calls.append(prompt)
        assert len(calls) <= 2 and ident == CORE and kw["model"] == "selected-model"
        binding = session.worker_task_binding
        assert binding.task_id == (42 if len(calls) == 1 else 43)
        assert binding.task_snapshot()["assigned_slot"] == CORE
        binding.assert_active()
        if outcome == "review" and len(calls) == 1:
            binding.record_worktree_result(42, "PR ready", review=True,
                result_ref="https://github.com/ellmos-ai/bach/pull/123")
        else:
            binding.execute_task_manage({"action": "done", "task_id": binding.task_id, "result": "Konkretes Ergebnis der gebundenen Core-Aufgabe"})
        return "block finished"
    monkeypatch.setattr(control.runtime, "process", process)

    def pause(ctrl, *, event_type):
        pauses.append(event_type)
        return len(pauses) < 2
    monkeypatch.setattr(control, "_wait_worker_cooldown", pause)

    class SynchronousThread:
        def __init__(self, target, **kw): self.target = target
        def start(self):
            self.active = True
            try:
                control._WORKER_CONTROLS[CORE].stop_event.wait = lambda timeout=None: False
                self.target()
            finally:
                self.active = False

        def is_alive(self):
            return getattr(self, "active", False)
    monkeypatch.setattr(control.threading, "Thread", SynchronousThread)
    response, status = control.start_worker_execution(CORE)
    assert status == 200 and response["ok"] is True
    assert len(calls) == 2
    assert len(acquire_calls) == idle_polls + 2
    assert any("Block 1: block finished" in str(a) for a in activities)
    assert any("Block 2: block finished" in str(a) for a in activities)
    assert not any("Block 3:" in str(a) for a in activities)
    assert [a["task_id"] for a in assignments] == [42, 43]
    assert all(a["slot_id"] == CORE and a["session_id"] == CORE for a in assignments)
    assert all(a["backend_id"] == "openrouter" and a["model_id"] == "selected-model" for a in assignments)
    assert assignments[0]["agent_instance_id"] == assignments[1]["agent_instance_id"]
    assert pauses == (["runs", "tasks"] if outcome == "review" else ["tasks", "tasks"])
    assert endings[0]["result"] == "task_review"
    assert slots_config.get_slot(CORE, core_file)["task_id"] is None


def test_failed_prompt_snapshot_does_not_count_or_call_a_model():
    import ast
    import inspect

    control = importlib.import_module("hub._services.chat.telegram_chat")
    tree = ast.parse(inspect.getsource(control._start_reserved_worker_execution))
    # Execute the actual submission statements with a failed canonical read.
    # The complete controller flow is covered by the bound-task tests above.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for index, statement in enumerate(node.body):
            if (isinstance(statement, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "bound_prompt"
                            for target in statement.targets)):
                statements = node.body[index:index + 3]
                break
        else:
            continue
        break
    else:
        pytest.fail("Worker submission boundary was not found")
    calls = []
    def failed_snapshot(*_):
        raise RuntimeError("canonical snapshot unavailable")
    scope = {"_bound_worker_prompt": failed_snapshot, "control": type("Control", (), {"task_binding": object()})(),
             "prompt_to_run": "task", "run_count": 0,
             "runtime": type("Runtime", (), {"process": lambda *args, **kwargs: calls.append(args)})()}
    with pytest.raises(RuntimeError, match="canonical snapshot unavailable"):
        exec(compile(ast.Module(body=statements, type_ignores=[]), "worker-submission", "exec"), scope)
    assert scope["run_count"] == 0 and calls == []


def test_disabled_core_cannot_start_or_dispatch_tools(core_file, monkeypatch):
    control = importlib.import_module("hub._services.chat.telegram_chat")
    slots_config.update_slot(CORE, {"enabled": False}, core_file)
    monkeypatch.setattr(control, "begin_assignment", lambda **kw: pytest.fail("disabled core assignment"))
    response, status = control.start_worker_execution(CORE)
    assert status == 403 and "error" in response
    session = ChatSession()
    session.chat_id = CORE
    session.worker_slot_reader = lambda: slots_config.get_always_on_execution_slot(core_file)
    result = ChatRuntime._refresh_worker_tools(session)
    assert isinstance(result, FailedAnswer) and session.allow_tools is False


def test_core_snapshot_binds_live_reader_and_selected_backend(core_file, monkeypatch):
    control = importlib.import_module("hub._services.chat.telegram_chat")
    session = ChatSession()
    session.chat_id = CORE
    backend = object()
    selections = []
    monkeypatch.setattr(control.runtime, "get_session", lambda ident: session)
    monkeypatch.setattr(control, "_get_or_create_backend", lambda kind, model: selections.append((kind, model)) or backend)
    selected, model = control._snapshot_chat_backend(CORE,
        worker_slot=slots_config.get_always_on_execution_slot(core_file))
    assert selected is backend and model == "selected-model"
    assert selections == [("openrouter", "selected-model")]
    assert session.mode == "safe" and session.think is False and session.max_tool_rounds == 7
    assert session.worker_slot_reader()["id"] == CORE
    slots_config.update_slot(CORE, {"enabled": False}, core_file)
    assert isinstance(ChatRuntime._refresh_worker_tools(session), FailedAnswer)


def test_core_running_receipts_use_actual_binding_and_disable_actions(core_file, monkeypatch, mem_db):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    control = importlib.import_module("hub._services.chat.telegram_chat")
    ctrl = control._WorkerControl(CORE)
    # This fixture models an API worker after its backend capability was admitted.
    ctrl.supports_step_actions = True
    ctrl.thread = type("Alive", (), {"is_alive": lambda self: True})()
    mem_db.execute("INSERT INTO tasks (id,title,status) VALUES (42,'Core running','pending')")
    mem_db.commit()
    monkeypatch.setattr(lease_module, "get_lead_config", lambda: {"mode": "isolated"})
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    monkeypatch.setitem(control._WORKER_CONTROLS, CORE, ctrl)
    monkeypatch.setitem(control._ACTIVE_WORKER_THREADS, CORE, ctrl.thread)
    ctrl.task_binding = WorkerLeaseBinding.acquire(TaskLeaseClient(conn=mem_db), 42,
        worker_id="core-test@HOST", host="HOST", generation=ctrl.generation,
        is_current=lambda: control._WORKER_CONTROLS.get(CORE) is ctrl, stop_event=ctrl.stop_event)
    slots_config.update_slot(CORE, {"status": "running"}, core_file)
    try:
        public = control._worker_handoff_snapshot(slots_config.get_always_on_execution_slot(core_file))
        assert public["generation"] == ctrl.generation
        assert public["task_action_binding"]["task_id"] == 42
        handler = control.ControlHandler.__new__(control.ControlHandler)
        handler.path = "/api/workers"
        responses = []
        monkeypatch.setattr(handler, "_json", lambda body, code=200: responses.append((body, code)))
        handler.do_GET()
        assert responses[-1][1] == 200
        visible = next(worker for worker in responses[-1][0]["workers"] if worker["id"] == CORE)
        assert visible["system"] is True and visible["deletable"] is False
        assert visible["generation"] == ctrl.generation and visible["task_action_binding"]["task_id"] == 42
        version = public["task_action_binding"]["task_version"]
        receipt = control._request_worker_decomposition(CORE, ctrl.generation, 42, version)
        assert receipt["state"] == "pending" and receipt["confirmed_at"] is None
        assert ctrl.task_binding._ack.lease_id not in str(public)
        slots_config.update_slot(CORE, {"enabled": False}, core_file)
        public = control._worker_handoff_snapshot(slots_config.get_always_on_execution_slot(core_file))
        assert "task_action_binding" not in public
        with pytest.raises(ValueError):
            control._request_worker_decomposition(CORE, ctrl.generation, 42, version)
    finally:
        ctrl.task_binding.return_lease()


def test_persisted_core_metadata_is_not_running_authority(core_file, monkeypatch):
    control = importlib.import_module("hub._services.chat.telegram_chat")
    monkeypatch.setattr(control, "_WORKER_CONTROLS", {})
    fake = {**slots_config.get_always_on_execution_slot(core_file), "generation": "old",
        "task_action_binding": {"task_id": 42, "task_version": "old"}, "status": "running"}
    public = control._worker_handoff_snapshot(fake)
    assert "generation" not in public and "task_action_binding" not in public


@pytest.mark.parametrize("change", [{"mode": "full"}, {"model": "other-model"},
    {"backend": "ollama"}, {"max_tool_rounds": 0}, {"category": "other"}])
def test_core_configuration_change_revokes_current_block_policy(core_file, monkeypatch, change):
    control = importlib.import_module("hub._services.chat.telegram_chat")
    session = ChatSession()
    session.chat_id = CORE
    monkeypatch.setattr(control.runtime, "get_session", lambda ident: session)
    monkeypatch.setattr(control, "_get_or_create_backend", lambda *args: object())
    control._snapshot_chat_backend(CORE, worker_slot=slots_config.get_always_on_execution_slot(core_file))
    reader = session.worker_slot_reader
    # The controller's task metadata update does not alter its admitted policy.
    slots_config.update_slot(CORE, {"task_id": 43}, core_file)
    assert reader()["task_id"] == 43
    slots_config.update_slot(CORE, change, core_file)
    assert isinstance(ChatRuntime._refresh_worker_tools(session), FailedAnswer)
    assert session.allow_tools is False
    # process() gets the session again: it must not replace the private reader.
    session.require_task_binding = True
    monkeypatch.setitem(control._WORKER_CONTROLS, CORE, control._WorkerControl(CORE))
    monkeypatch.setattr(control, "_orig_get_session", lambda ident: session)
    assert control._patched_get_session(CORE) is session
    assert session.worker_slot_reader is reader


def test_core_policy_change_blocks_bound_operations_but_keeps_confirmed_cleanup(core_file, monkeypatch, mem_db):
    from hub._services.task_lease_client import LeaseProtocolError
    control = importlib.import_module("hub._services.chat.telegram_chat")
    mem_db.execute("INSERT INTO tasks (id,title,status,priority,category,assigned_to,assigned_slot) "
        "VALUES (42,'Bound core policy','pending','P1','INBOX','BACH',?)", (CORE,))
    mem_db.commit()
    monkeypatch.setattr(lease_module, "get_lead_config", lambda: {"mode": "isolated"})
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    monkeypatch.setattr(control, "_native_task_client", lambda: TaskLeaseClient(conn=mem_db))
    ctrl = control._WorkerControl(CORE)
    monkeypatch.setitem(control._WORKER_CONTROLS, CORE, ctrl)
    binding = control._acquire_worker_task(ctrl, slots_config.get_always_on_execution_slot(core_file), "core-test")
    try:
        binding.assert_active()
        slots_config.update_slot(CORE, {"mode": "full"}, core_file)
        with pytest.raises(LeaseProtocolError):
            binding.assert_active()
        with pytest.raises(LeaseProtocolError):
            binding.execute_task_manage({"action": "done", "task_id": 42, "result": "Konkretes Ergebnis"})
        assert binding.completed_task_ids == ()
        # Maintain ownership while an already admitted physical call terminates.
        assert binding.heartbeat(renew_due=True)
        assert binding.return_lease() is True
        assert mem_db.execute("SELECT status FROM tasks WHERE id=42").fetchone()[0] == "pending"
    finally:
        binding.return_lease()
