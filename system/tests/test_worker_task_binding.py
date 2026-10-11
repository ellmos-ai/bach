# SPDX-License-Identifier: MIT
"""Task transitions of a continuous worker, without live TaskDB or inference."""
import importlib
import pytest
from system.tests.test_task_lease_client import mem_db
from hub._services.task_lease_client import TaskLeaseClient
from hub._services import task_lease_client as lease_module

from hub._services.chat.chat_runtime import ChatSession
from hub._services.chat.slots_config import (
    add_worker, get_worker_slot, initialize_slots_config, update_slot,
)


@pytest.mark.parametrize(("worker_type", "receipt_kind"), [
    (kind, receipt) for kind in ("continuous", "persistent")
    for receipt in ("matched", "foreign", "next-assignment-denied", "review", "review-text", "blocked", "returned")
] + [("once", "review")])
@pytest.mark.parametrize("entrypoint", ["http", "native"])
def test_continuous_worker_advances_task_binding_and_assignment(tmp_path, monkeypatch, mem_db, worker_type, receipt_kind, entrypoint):
    control = importlib.import_module("hub._services.chat.telegram_chat")
    path = str(tmp_path / "slots.json")
    initialize_slots_config(path)
    worker = add_worker({"name": "Transition", "type": worker_type, "task_id": 42,
                         "sub_mode": "task_worker", "pause_basis": "tasks"}, path=path)
    wid = worker["id"]
    session = ChatSession()
    session.chat_id = wid
    session.messages = [{"role": "user", "content": "Vorheriger Taskkontext"}]
    context_resets = []
    calls, starts, ends, pauses = [], [], [], []
    mem_db.executemany("INSERT INTO tasks (id, title, status, priority) VALUES (?, ?, 'pending', ?)",
                      [(42, "First canonical task", "P1"), (43, "Second canonical task", "P2")])
    mem_db.execute("UPDATE tasks SET assigned_to='BACH'")
    mem_db.commit()
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    monkeypatch.setattr(lease_module, "get_lead_config", lambda: {"mode": "isolated"})
    monkeypatch.setattr(control, "_native_task_client", lambda: TaskLeaseClient(conn=mem_db), raising=False)
    monkeypatch.setattr(control, "get_worker_slot", lambda ident: get_worker_slot(ident, path=path))
    monkeypatch.setattr(control, "update_slot", lambda ident, change: update_slot(ident, change, path=path))
    monkeypatch.setattr(control, "record_activity", lambda *a, **kw: None)
    monkeypatch.setattr(control, "_snapshot_chat_backend", lambda *a, **kw: (object(), "test-model"))
    monkeypatch.setattr(control.runtime, "get_session", lambda ident: session)
    monkeypatch.setattr(control.runtime, "session_store", object())

    def clear_worker_context(chat_id, *, archive_reason):
        assert chat_id == wid
        assert archive_reason == "Worker Taskwechsel"
        context_resets.append(chat_id)
        session.messages.clear()

    monkeypatch.setattr(control.runtime, "clear_session", clear_worker_context)

    def begin(**kwargs):
        starts.append(kwargs)
        if receipt_kind == "next-assignment-denied" and len(starts) == 2:
            raise ValueError("synthetic assignment denied")
        return kwargs
    monkeypatch.setattr(control, "begin_assignment", begin)
    monkeypatch.setattr(control, "finish_assignment", lambda assignment, **kw: ends.append((assignment, kw)))

    async def process(prompt, *a, **kw):
        calls.append(prompt)
        assert len(calls) <= 2
        assert all(message.get("content") != "Vorheriger Taskkontext" for message in session.messages)
        binding = session.worker_task_binding
        assert binding is not None
        assert binding.task_id == (42 if len(calls) == 1 or receipt_kind in {"foreign", "review-text"} else 43)
        assert binding.task_snapshot()["title"] in prompt
        assert binding._ack.lease_id not in prompt
        binding.assert_active()
        if receipt_kind in {"blocked", "returned"} and len(calls) == 1:
            binding.execute_task_manage({"action": "update", "task_id": binding.task_id,
                                         "status": "blocked" if receipt_kind == "blocked" else "pending"})
        elif receipt_kind == "review" and len(calls) == 1:
            binding.record_worktree_result(binding.task_id, "PR ready", review=True,
                result_ref="https://github.com/ellmos-ai/bach/pull/123")
            assert binding.completed_task_ids == ()
        elif receipt_kind not in {"foreign", "review-text"}:
            binding.execute_task_manage({"action": "done", "task_id": binding.task_id, "result": "Konkretes Ergebnis der Worker-Aufgabe"})
        return "PR bestätigt; review" if receipt_kind == "review-text" else "verified task completion"
    monkeypatch.setattr(control.runtime, "process", process)
    monkeypatch.setattr(control.runtime, "consume_task_completion_receipts",
                        lambda ident: ((99,) if receipt_kind == "foreign" else (42,))
                        if len(calls) == 1 else (43,))

    def pause(ctrl, *, event_type):
        pauses.append(event_type)
        if receipt_kind in {"foreign", "review-text"}:
            assert ctrl.lease_supervisor is not None and ctrl.lease_supervisor.is_alive
        if receipt_kind == "blocked":
            return len(calls) < 2
        return len(pauses) < 2  # Stop this isolated probe after two task receipts.
    monkeypatch.setattr(control, "_wait_worker_cooldown", pause)

    class SynchronousThread:
        def __init__(self, target, **kwargs):
            self.target = target
        def start(self):
            self.active = True
            try:
                control._WORKER_CONTROLS[wid].stop_event.wait = lambda timeout=None: False
                self.target()
            finally:
                self.active = False

        def is_alive(self):
            return getattr(self, "active", False)
    monkeypatch.setattr(control.threading, "Thread", SynchronousThread)
    handler = control.ControlHandler.__new__(control.ControlHandler)
    handler.path = "/api/workers/run"
    monkeypatch.setattr(handler, "_allow_json_post", lambda: True)
    monkeypatch.setattr(handler, "_read_body", lambda: {"id": wid})
    responses = []
    monkeypatch.setattr(handler, "_json", lambda body, code=200: responses.append((body, code)))
    if entrypoint == "http":
        handler.do_POST()
    else:
        responses.append(control.start_worker_execution(wid))

    assert responses[-1][1] == 200
    assert len(context_resets) == len(calls) - (1 if receipt_kind in {"foreign", "review-text"} else 0)
    if receipt_kind in {"blocked", "returned"}:
        assert get_worker_slot(wid, path=path)["task_id"] is None
        assert len(calls) == len(ends) == 2
        assert [assignment["task_id"] for assignment in starts] == [42, 43]
        assert ends[0][1]["result"] == "task_returned"
        assert ends[1][1]["result"] == "task_review"
        assert pauses == ["runs", "tasks"]
        assert mem_db.execute("SELECT status FROM tasks WHERE id=42").fetchone()[0] == (
            "blocked" if receipt_kind == "blocked" else "pending")
        return
    if worker_type == "once" and receipt_kind == "review":
        assert len(calls) == len(starts) == len(ends) == 1
        assert pauses == []
        assert get_worker_slot(wid, path=path)["status"] == "idle"
        assert get_worker_slot(wid, path=path)["task_id"] is None
        assert ends[0][1]["status"] == "released" and ends[0][1]["result"] == "task_review"
        return
    if receipt_kind in {"foreign", "review-text"}:
        assert len(calls) == 2
        assert pauses == ["runs", "runs"]
        assert get_worker_slot(wid, path=path)["task_id"] == 42
        assert len(starts) == len(ends) == 1
        assert ends[0][1]["status"] == "released"
        return
    assert [assignment["task_id"] for assignment in starts] == [42, 43]
    assert starts[0]["agent_instance_id"] == starts[1]["agent_instance_id"]
    if receipt_kind == "next-assignment-denied":
        assert len(calls) == len(ends) == 1
        assert pauses == ["tasks"]
        assert get_worker_slot(wid, path=path)["status"] == "error"
        assert mem_db.execute("SELECT status FROM tasks WHERE id=43").fetchone()[0] == "pending"
        return
    assert get_worker_slot(wid, path=path)["task_id"] is None
    assert len(calls) == 2
    assert pauses == (["runs", "tasks"] if receipt_kind == "review" else ["tasks", "tasks"])
    assert len(ends) == 2
    if receipt_kind == "review":
        assert ends[0][1]["status"] == "released" and ends[0][1]["result"] == "task_review"
        assert ends[1][1]["status"] == "released"
        assert mem_db.execute("SELECT status FROM tasks WHERE id=42").fetchone()[0] == "review"
    else:
        assert all(details["status"] == "released" for assignment, details in ends)


@pytest.mark.parametrize("state", ["no-task", "foreign-holder", "missing-store", "broken-store"])
def test_controller_does_not_infer_without_confirmed_task_lease(tmp_path, monkeypatch, mem_db, state):
    control = importlib.import_module("hub._services.chat.telegram_chat")
    path = str(tmp_path / "slots.json")
    initialize_slots_config(path)
    worker = add_worker({"name": "Denied", "type": "once", "task_id": 42 if state != "no-task" else None}, path=path)
    wid = worker["id"]
    monkeypatch.setattr(lease_module, "get_lead_config", lambda: {"mode": "isolated"})
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    client = TaskLeaseClient(conn=mem_db)
    if state in {"foreign-holder", "missing-store", "broken-store"}:
        mem_db.execute("INSERT INTO tasks (id, title, status) VALUES (42, 'Foreign', 'pending')")
        if state in {"missing-store", "broken-store"}:
            mem_db.execute("UPDATE tasks SET assigned_to='BACH' WHERE id=42")
        mem_db.commit()
    if state == "foreign-holder":
        client.acquire(42, worker_id="foreign@HOST", host="HOST")
    monkeypatch.setattr(control, "_native_task_client", lambda: client, raising=False)
    monkeypatch.setattr(control, "get_worker_slot", lambda ident: get_worker_slot(ident, path=path))
    monkeypatch.setattr(control, "update_slot", lambda ident, change: update_slot(ident, change, path=path))
    monkeypatch.setattr(control, "record_activity", lambda *a, **kw: None)
    monkeypatch.setattr(control, "begin_assignment", lambda **kw: kw)
    monkeypatch.setattr(control, "finish_assignment", lambda *a, **kw: None)
    monkeypatch.setattr(control, "_snapshot_chat_backend", lambda *a, **kw: (object(), "test-model"))
    if state == "missing-store":
        monkeypatch.setattr(control.runtime, "session_store", None)
    elif state == "broken-store":
        import sqlite3
        from hub._services.chat.session_store import SQLiteChatSessionStore
        broken_db = tmp_path / "chat-without-snapshot-table.db"
        sqlite3.connect(broken_db).close()
        monkeypatch.setattr(control.runtime, "session_store", SQLiteChatSessionStore(broken_db))
    async def forbidden(*a, **kw): pytest.fail("Inference without lease")
    monkeypatch.setattr(control.runtime, "process", forbidden)
    class SynchronousThread:
        def __init__(self, target, **kw): self.target = target
        def start(self):
            self.active = True
            try:
                self.target()
            finally:
                self.active = False

        def is_alive(self):
            return getattr(self, "active", False)
    monkeypatch.setattr(control.threading, "Thread", SynchronousThread)
    handler = control.ControlHandler.__new__(control.ControlHandler)
    handler.path = "/api/workers/run"
    monkeypatch.setattr(handler, "_allow_json_post", lambda: True)
    monkeypatch.setattr(handler, "_read_body", lambda: {"id": wid})
    monkeypatch.setattr(handler, "_json", lambda *a, **kw: None)
    handler.do_POST()
    assert get_worker_slot(wid, path=path)["status"] == ("idle" if state == "no-task" else "error")
    if state in {"missing-store", "broken-store"}:
        assert client.read(42).leased is False


def test_continuous_worker_archives_context_between_confirmed_task_leases(tmp_path, monkeypatch, mem_db):
    import json
    import sqlite3
    control = importlib.import_module("hub._services.chat.telegram_chat")
    from hub._services.chat.chat_runtime import ChatRuntime
    from hub._services.chat.session_store import CHAT_SNAPSHOT_TYPE, SQLiteChatSessionStore

    slot_path = str(tmp_path / "slots.json")
    initialize_slots_config(slot_path)
    worker = add_worker({"name": "Context boundary", "type": "continuous", "task_id": 42,
                         "sub_mode": "task_worker", "pause_basis": "tasks"}, path=slot_path)
    wid = worker["id"]
    mem_db.executemany("INSERT INTO tasks (id, title, status, priority) VALUES (?, ?, 'pending', ?)",
                      [(42, "First task", "P1"), (43, "Second task", "P2")])
    mem_db.execute("UPDATE tasks SET assigned_to='BACH'")
    mem_db.commit()
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    monkeypatch.setattr(lease_module, "get_lead_config", lambda: {"mode": "isolated"})
    client = TaskLeaseClient(conn=mem_db)
    monkeypatch.setattr(control, "_native_task_client", lambda: client, raising=False)
    monkeypatch.setattr(control, "get_worker_slot", lambda ident: get_worker_slot(ident, path=slot_path))
    monkeypatch.setattr(control, "update_slot", lambda ident, change: update_slot(ident, change, path=slot_path))
    monkeypatch.setattr(control, "record_activity", lambda *a, **kw: None)
    monkeypatch.setattr(control, "_snapshot_chat_backend", lambda *a, **kw: (object(), "test-model"))

    chat_db = tmp_path / "chat.db"
    with sqlite3.connect(chat_db) as conn:
        conn.execute("""
            CREATE TABLE session_snapshots (
                id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL,
                snapshot_type TEXT NOT NULL,
                snapshot_data TEXT,
                name TEXT,
                created_at TEXT
            )
        """)

    class Backend:
        @staticmethod
        def get_default_model():
            return "test-model"

    store = SQLiteChatSessionStore(chat_db)
    runtime = ChatRuntime(Backend(), session_store=store)
    monkeypatch.setattr(control, "runtime", runtime)
    previous = runtime.get_session(wid)
    previous.messages.append({"role": "user", "content": "Vorheriger privater Gesprächsverlauf"})
    runtime._persist_session(wid, previous)

    starts, ends, prompts, observed_sessions = [], [], [], []
    monkeypatch.setattr(control, "begin_assignment", lambda **kwargs: starts.append(kwargs) or kwargs)
    monkeypatch.setattr(control, "finish_assignment", lambda assignment, **kwargs: ends.append(kwargs))

    async def process(prompt, chat_id, **kwargs):
        prompts.append(prompt)
        session = runtime.get_session(chat_id)
        observed_sessions.append((session, [dict(message) for message in session.messages]))
        assert all(message.get("content") != "Vorheriger privater Gesprächsverlauf"
                   for message in session.messages)
        assert all(message.get("content") != "Task-42-only transcript"
                   for message in session.messages)
        binding = session.worker_task_binding
        if len(prompts) == 1:
            session.messages.append({"role": "user", "content": "Task-42-only transcript"})
            runtime._persist_session(chat_id, session)
        return binding.execute_task_manage({
            "action": "done", "task_id": binding.task_id,
            "result": "Konkretes Ergebnis der isolierten Workeraufgabe",
        })

    monkeypatch.setattr(runtime, "process", process)
    monkeypatch.setattr(runtime, "consume_task_completion_receipts",
                        lambda ident: (42,) if len(prompts) == 1 else (43,))
    monkeypatch.setattr(control, "_wait_worker_cooldown", lambda *a, **kw: len(prompts) < 2)

    class SynchronousThread:
        def __init__(self, target, **kwargs): self.target = target
        def start(self):
            self.active = True
            try:
                control._WORKER_CONTROLS[wid].stop_event.wait = lambda timeout=None: False
                self.target()
            finally:
                self.active = False
        def is_alive(self):
            return getattr(self, "active", False)

    monkeypatch.setattr(control.threading, "Thread", SynchronousThread)
    handler = control.ControlHandler.__new__(control.ControlHandler)
    handler.path = "/api/workers/run"
    monkeypatch.setattr(handler, "_allow_json_post", lambda: True)
    monkeypatch.setattr(handler, "_read_body", lambda: {"id": wid})
    responses = []
    monkeypatch.setattr(handler, "_json", lambda body, code=200: responses.append((body, code)))
    handler.do_POST()

    assert responses[-1][1] == 200
    assert len(prompts) == 2
    assert observed_sessions[0][1] == observed_sessions[1][1] == []
    assert observed_sessions[0][0] is not observed_sessions[1][0]
    assert "First task" in prompts[0]
    assert "Second task" in prompts[1]
    assert [assignment["task_id"] for assignment in starts] == [42, 43]
    assert len(ends) == 2
    assert client.read(42).leased is False
    assert client.read(43).leased is False
    assert store.load(wid) == []

    with sqlite3.connect(chat_db) as conn:
        rows = conn.execute(
            "SELECT snapshot_data FROM session_snapshots WHERE session_id LIKE ? AND snapshot_type = ?",
            (f"{store.session_id(wid)}:archived:%", CHAT_SNAPSHOT_TYPE),
        ).fetchall()
    archived_messages = [
        message["content"]
        for (payload,) in rows
        for message in json.loads(payload)["messages"]
    ]
    assert "Vorheriger privater Gesprächsverlauf" in archived_messages
    assert "Task-42-only transcript" in archived_messages


def test_native_factory_rejects_undeclared_authority_before_projection_path(monkeypatch):
    from hub import rheingold
    from hub._services.chat import bach_tools
    from hub._services.task_lease_client import LeaseError
    control = importlib.import_module("hub._services.chat.telegram_chat")
    monkeypatch.delenv("BACH_MODE", raising=False)
    monkeypatch.setattr(rheingold, "get_lead_config", lambda: {"mode": "isolated", "lead_url": None})
    monkeypatch.setattr(bach_tools, "_current_runtime_db", lambda: pytest.fail("projection path requested"))
    with pytest.raises(LeaseError): control._native_task_client()


def test_native_factory_rejects_authority_change_without_opening_projection(monkeypatch):
    from hub import rheingold
    from hub._services.chat import bach_tools
    from hub._services.task_lease_client import LeaseError
    control = importlib.import_module("hub._services.chat.telegram_chat")
    monkeypatch.setattr(rheingold, "get_lead_config", lambda: {"mode": "worker", "lead_url": "http://lead.invalid"})
    monkeypatch.setattr(lease_module, "get_lead_config", lambda: {"mode": "isolated"})
    monkeypatch.setattr(bach_tools, "_current_runtime_db", lambda: "unused-projection.db")
    monkeypatch.setattr(TaskLeaseClient, "_get_local_connection", lambda self: pytest.fail("projection opened"))
    with pytest.raises(LeaseError): control._native_task_client()


@pytest.mark.parametrize("case", ["actual-ack", "no-task"])
def test_assignment_completion_uses_authority_ack_not_stale_slot_projection(tmp_path, monkeypatch, mem_db, case):
    control = importlib.import_module("hub._services.chat.telegram_chat")
    wid = "alpha"
    worker = {"id": wid, "name": "Stale view", "type": "once", "sub_mode": "task_worker",
              "status": "running" if case == "actual-ack" else "completed",
              "task_id": 42 if case == "actual-ack" else None}
    if case == "actual-ack":
        worker.update({
            "backend": "ollama-cloud", "model": "kimi-k3:cloud",
            "allow_tools": False, "allowed_tools": ["task_manage"],
            "max_tool_rounds": 7, "mode": "safe", "think": False,
            "system_prompt": "Aufgabenprofil mit begrenzten Werkzeugen",
        })
        mem_db.execute("INSERT INTO tasks (id, title, status) VALUES (42, 'Actual', 'pending')")
        mem_db.commit()
    ends = []
    store = None
    if case == "actual-ack":
        import sqlite3
        from hub._services.chat.chat_runtime import ChatRuntime
        from hub._services.chat.session_store import CHAT_SNAPSHOT_TYPE, SQLiteChatSessionStore

        chat_db = tmp_path / "worker-task-context.db"
        with sqlite3.connect(chat_db) as conn:
            conn.execute("""
                CREATE TABLE session_snapshots (
                    id INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    snapshot_type TEXT NOT NULL,
                    snapshot_data TEXT,
                    name TEXT,
                    created_at TEXT
                )
            """)

        class Backend:
            @staticmethod
            def get_default_model():
                return "test-model"

        store = SQLiteChatSessionStore(chat_db)
        test_runtime = ChatRuntime(Backend(), session_store=store)
        monkeypatch.setattr(control, "runtime", test_runtime)
        target_backend = object()
        monkeypatch.setattr(control, "_get_or_create_backend", lambda *_args, **_kwargs: target_backend)
        previous = test_runtime.get_session(wid)
        previous.messages.append({"role": "user", "content": "Vorheriger Taskverlauf"})
        test_runtime._persist_session(wid, previous)
    else:
        session = ChatSession()
        session.chat_id = wid
        monkeypatch.setattr(control.runtime, "get_session", lambda ident: session)
    monkeypatch.setattr(lease_module, "get_lead_config", lambda: {"mode": "isolated"})
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    monkeypatch.setattr(control, "_native_task_client", lambda: TaskLeaseClient(conn=mem_db))
    monkeypatch.setattr(control, "get_worker_slot", lambda ident: worker)
    monkeypatch.setattr(control, "update_slot", lambda *a: worker)  # Deliberately stale projection.
    monkeypatch.setattr(control, "record_activity", lambda *a, **kw: None)
    monkeypatch.setattr(control, "begin_assignment", lambda **kw: kw)
    monkeypatch.setattr(control, "finish_assignment", lambda assignment, **kw: ends.append(kw))
    if case != "actual-ack":
        monkeypatch.setattr(control, "_snapshot_chat_backend", lambda *a, **kw: (object(), "test-model"))
    async def process(*a, **kw):
        assert case == "actual-ack"
        session = control.runtime.get_session(wid)
        assert all(message.get("content") != "Vorheriger Taskverlauf" for message in session.messages)
        assert session is not previous
        assert kw["backend"] is session.backend
        assert kw["model"] == session.model
        assert session.backend is target_backend
        assert session.model == "kimi-k3:cloud"
        assert session.mode == "safe"
        assert session.think is False
        assert session.allow_tools is False
        assert session.allowed_tools == ["task_manage"]
        assert session.max_tool_rounds == 7
        assert session.custom_system_prompt == "Aufgabenprofil mit begrenzten Werkzeugen"
        assert session.worker_slot_reader is not None
        return session.worker_task_binding.execute_task_manage({"action": "done", "task_id": 42, "result": "Konkretes Ergebnis des realen ACK-Falls"})
    monkeypatch.setattr(control.runtime, "process", process)
    class SynchronousThread:
        def __init__(self, target, **kw): self.target = target
        def start(self):
            self.active = True
            try:
                self.target()
            finally:
                self.active = False

        def is_alive(self):
            return getattr(self, "active", False)
    monkeypatch.setattr(control.threading, "Thread", SynchronousThread)
    handler = control.ControlHandler.__new__(control.ControlHandler)
    handler.path = "/api/workers/run"
    monkeypatch.setattr(handler, "_allow_json_post", lambda: True)
    monkeypatch.setattr(handler, "_read_body", lambda: {"id": wid})
    monkeypatch.setattr(handler, "_json", lambda *a, **kw: None)
    handler.do_POST()
    assert len(ends) == 1
    assert ends[0]["status"] == "released"
    assert ends[0]["result"] == ("task_review" if case == "actual-ack" else "not_finished")
    if case == "actual-ack":
        assert store.load(wid) == []
        with sqlite3.connect(chat_db) as conn:
            rows = conn.execute(
                "SELECT snapshot_data FROM session_snapshots WHERE session_id LIKE ? AND snapshot_type = ?",
                (f"{store.session_id(wid)}:archived:%", CHAT_SNAPSHOT_TYPE),
            ).fetchall()
        assert any("Vorheriger Taskverlauf" in row[0] for row in rows)
