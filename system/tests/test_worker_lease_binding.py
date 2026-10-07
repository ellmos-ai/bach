"""Private native worker binding: isolated authority, generation and receipts."""
import threading

import pytest

from system.tests.test_task_lease_client import mem_db, _insert_task
from system.tests.test_task_lease_client_review import T0
from hub._services.task_lease_client import TaskLeaseClient, LeaseError, LeaseConnectionError


@pytest.fixture
def binding(mem_db):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    mem_db.execute("ALTER TABLE tasks ADD COLUMN created_at TEXT")
    mem_db.commit()
    tid = _insert_task(mem_db)
    client = TaskLeaseClient(conn=mem_db)
    return WorkerLeaseBinding.acquire(client, tid, worker_id="physical-worker@HOST", host="HOST",
                                     generation="generation-1", is_current=lambda: True,
                                     stop_event=threading.Event(), clock=lambda: T0)


def test_binding_uses_canonical_content_and_keeps_capability_private(binding):
    assert binding.task_id == binding.task_snapshot()["id"]
    assert "task_version" in binding.task_snapshot()
    assert binding._ack.lease_id not in str(binding.task_snapshot())
    assert binding._ack.lease_id not in repr(binding)


def test_done_receipt_requires_authoritative_release(binding):
    result = binding.execute_task_manage({"action": "done", "task_id": binding.task_id})
    assert result == f"Task #{binding.task_id} erledigt."
    assert binding.closed
    assert binding.completed_task_ids == (binding.task_id,)
    with pytest.raises(LeaseError):
        binding.execute_task_manage({"action": "done", "task_id": binding.task_id})


def test_content_update_rebinds_before_next_mutation(binding):
    previous = binding.task_snapshot()["task_version"]
    binding.execute_task_manage({"action": "update", "task_id": binding.task_id,
                                 "description": "Änderung"})
    assert binding.task_snapshot()["task_version"] != previous
    assert binding.task_snapshot()["description"] == "Änderung"
    assert binding.execute_task_manage({"action": "done", "task_id": binding.task_id}).endswith("erledigt.")


@pytest.mark.parametrize("changes", [{"status": "done", "description": "Must not apply"},
                                     {"status": "in_progress"}, {"unknown": "x"}])
def test_unsafe_update_does_not_partially_write(binding, changes):
    before = binding._client.task_snapshot(binding.task_id)
    with pytest.raises(LeaseError):
        binding.execute_task_manage({"action": "update", "task_id": binding.task_id, **changes})
    assert binding._client.task_snapshot(binding.task_id) == before


@pytest.mark.parametrize("cause", ["foreign-task", "stopped", "generation", "expired"])
def test_guard_prevents_mutation(binding, cause):
    args = {"action": "done", "task_id": binding.task_id}
    before = binding._client.task_snapshot(binding.task_id)
    if cause == "foreign-task": args["task_id"] += 1
    if cause == "stopped": binding._stop_event.set()
    if cause == "generation": binding._is_current = lambda: False
    if cause == "expired": binding._clock = lambda: binding._ack.local_deadline
    with pytest.raises(LeaseError):
        binding.execute_task_manage(args)
    assert binding._client.task_snapshot(binding.task_id) == before
    assert not binding.completed_task_ids


def test_lost_update_ack_revokes_binding_and_never_retries(binding, monkeypatch):
    original = binding._client.update
    calls = []
    def lose(*args, **kwargs):
        calls.append(args)
        original(*args, **kwargs)
        raise LeaseConnectionError("Bestätigung fehlt")
    monkeypatch.setattr(binding._client, "update", lose)
    with pytest.raises(LeaseError):
        binding.execute_task_manage({"action": "update", "task_id": binding.task_id,
                                     "description": "Committed once"})
    with pytest.raises(LeaseError): binding.assert_active()
    assert binding.return_lease() is False
    assert len(calls) == 1
    assert binding._client.task_snapshot(binding.task_id)["description"] == "Committed once"
    assert not binding.completed_task_ids


@pytest.mark.parametrize("close", [False, True])
def test_decomposition_rebinds_or_closes_parent(binding, close):
    previous = binding.task_snapshot()["task_version"]
    result = binding.execute_task_manage({"action": "decompose", "task_id": binding.task_id,
                                         "subtasks": [{"title": "Kind"}], "close_parent": close})
    assert "in 1 Teilaufgaben zerlegt: IDs" in result
    assert binding.closed is close
    assert binding.completed_task_ids == ((binding.task_id,) if close else ())
    if not close:
        assert binding.task_snapshot()["task_version"] != previous
        binding.execute_task_manage({"action": "done", "task_id": binding.task_id})


def test_add_uses_parent_fenced_decomposition_without_completion_receipt(binding):
    previous = binding.task_snapshot()["task_version"]
    result = binding.execute_task_manage({"action": "add", "title": "Fortsetzung", "category": "TO-DECIDE"})
    assert "erstellt" in result
    assert not binding.closed and not binding.completed_task_ids
    assert binding.task_snapshot()["task_version"] != previous


def test_stopped_worker_can_return_lease_without_completion_receipt(binding):
    binding._stop_event.set()
    assert binding.return_lease()
    assert binding._client.task_snapshot(binding.task_id)["status"] == "pending"
    assert not binding.completed_task_ids


def test_typo_in_decomposition_does_not_close_parent(binding):
    with pytest.raises(LeaseError):
        binding.execute_task_manage({"action": "decompose", "task_id": binding.task_id,
                                     "subtasks": [{"title": "Kind"}], "close_parnt": False})
    assert not binding.closed and not binding.completed_task_ids
    assert binding._client.task_snapshot(binding.task_id)["status"] == "in_progress"


def test_renew_replaces_private_deadline_without_exposing_capability(binding):
    from datetime import timedelta
    previous = binding._ack.local_deadline
    binding._clock = lambda: T0 + timedelta(minutes=20)
    binding.renew()
    assert binding._ack.local_deadline > previous
    binding.assert_active()


def test_missing_renew_ack_revokes_binding(binding, monkeypatch):
    def lost(*args, **kwargs):
        raise LeaseConnectionError("Bestätigung fehlt")
    monkeypatch.setattr(binding._client, "renew", lost)
    with pytest.raises(LeaseError): binding.renew()
    with pytest.raises(LeaseError): binding.assert_active()
    assert binding.return_lease() is False


def test_task_tool_dispatch_uses_private_binding_before_local_db(binding, monkeypatch):
    from hub._services.chat import bach_tools
    monkeypatch.setattr(bach_tools, "_current_runtime_db", lambda: pytest.fail("projection path accessed"))
    result = bach_tools.exec_tool("task_manage", {"action": "done", "task_id": binding.task_id},
                                  mode="safe", worker_task_binding=binding)
    assert result == f"Task #{binding.task_id} erledigt."
    assert binding.completed_task_ids == (binding.task_id,)


def test_required_binding_cannot_fall_back_to_projection(monkeypatch):
    from hub._services.chat import bach_tools
    monkeypatch.setattr(bach_tools, "_current_runtime_db", lambda: pytest.fail("projection path accessed"))
    result = bach_tools.exec_tool("task_manage", {"action": "done", "task_id": 1},
                                  mode="safe", require_task_binding=True)
    assert "Taskbindung fehlt" in result


def test_real_native_process_releases_bound_task_without_post_completion_inference(binding, monkeypatch):
    import asyncio
    from hub._services.chat import bach_tools
    from hub._services.chat.chat_runtime import ChatRuntime
    calls = []
    class Backend:
        def get_default_model(self): return "isolated-model"
        async def chat(self, messages, **kwargs):
            calls.append(messages)
            assert binding._ack.lease_id not in str(messages)
            assert len(calls) == 1
            tools = [{"function": {"name": "task_manage", "arguments": {
                "action": "done", "task_id": binding.task_id}}}]
            return {"content": "", "tool_calls": tools,
                    "raw_message": {"role": "assistant", "content": "", "tool_calls": tools}}
        def tool_response_message(self, content, tool_call_id=""):
            return {"role": "tool", "content": content}
    runtime = ChatRuntime(Backend())
    runtime.max_tool_rounds = 3
    runtime.hook_every = 999
    session = runtime.get_session("worker-bound")
    session.worker_task_binding = binding
    session.require_task_binding = True
    monkeypatch.setattr(bach_tools, "_current_runtime_db", lambda: pytest.fail("projection path accessed"))
    answer = asyncio.run(runtime.process("Gebundenen Auftrag abschließen", "worker-bound",
                                         work_priority="background"))
    assert str(answer) == f"Task #{binding.task_id} erledigt."
    assert answer.completed_task_ids == (binding.task_id,)
    assert len(calls) == 1
    assert binding._ack.lease_id not in str(runtime.history("worker-bound"))


@pytest.mark.parametrize("reason", ["stopped", "missing-binding", "managed-tools", "wrong-model"])
def test_native_backend_boundary_refuses_unverifiable_run(binding, reason):
    import asyncio
    from unittest.mock import AsyncMock
    from hub._services.chat.chat_runtime import ChatRuntime, FailedAnswer
    backend = type("Backend", (), {"get_default_model": lambda self: "isolated-model",
                                   "chat": AsyncMock(return_value={"content": "unreachable"})})()
    runtime = ChatRuntime(backend)
    session = runtime.get_session("worker-bound")
    session.require_task_binding = True
    if reason != "missing-binding": session.worker_task_binding = binding
    if reason == "stopped": binding._stop_event.set()
    if reason == "managed-tools": backend.manages_own_tools = True
    if reason == "wrong-model":
        binding.execute_task_manage({"action": "update", "task_id": binding.task_id,
                                     "required_model": "other-model"})
    answer = asyncio.run(runtime.process("Gebundener Auftrag", "worker-bound", work_priority="background"))
    assert isinstance(answer, FailedAnswer)
    backend.chat.assert_not_awaited()


def test_next_actual_task_is_acquired_after_skipping_live_foreign_holder(mem_db):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    foreign = _insert_task(mem_db, "Foreign")
    next_task = _insert_task(mem_db, "Next actual task")
    mem_db.execute("UPDATE tasks SET assigned_to='BACH'")
    mem_db.execute("UPDATE tasks SET priority='P1' WHERE id=?", (foreign,))
    mem_db.execute("UPDATE tasks SET priority='P2' WHERE id=?", (next_task,))
    mem_db.commit()
    client = TaskLeaseClient(conn=mem_db)
    client.acquire(foreign, worker_id="other@HOST", host="HOST", now=T0)
    binding = WorkerLeaseBinding.acquire_next(client, {"id": "slot", "model": "test-model"},
        worker_id="physical-worker@HOST", host="HOST", generation="current",
        is_current=lambda: True, stop_event=threading.Event(), clock=lambda: T0)
    assert binding.task_id == next_task
    assert binding.task_snapshot()["title"] == "Next actual task"
    assert client.read(next_task, lease_id=binding._ack.lease_id, now=T0).own
    assert client.read(foreign, now=T0).holder["worker_id"] == "other@HOST"


def test_explicit_model_mismatch_is_rejected_before_acquire(mem_db, monkeypatch):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    tid = _insert_task(mem_db)
    mem_db.execute("UPDATE tasks SET required_model='other-model' WHERE id=?", (tid,))
    mem_db.commit()
    client = TaskLeaseClient(conn=mem_db)
    monkeypatch.setattr(client, "acquire", lambda *a, **kw: pytest.fail("ineligible task acquired"))
    with pytest.raises(LeaseError):
        WorkerLeaseBinding.acquire_next(client, {"task_id": tid, "id": "slot", "model": "test-model"},
            worker_id="physical-worker@HOST", host="HOST", generation="current",
            is_current=lambda: True, stop_event=threading.Event(), clock=lambda: T0)


def test_completed_binding_selects_and_acquires_real_successor(mem_db):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    first = _insert_task(mem_db, "First")
    second = _insert_task(mem_db, "Second")
    mem_db.execute("UPDATE tasks SET assigned_to='BACH'")
    mem_db.execute("UPDATE tasks SET priority='P1' WHERE id=?", (first,))
    mem_db.commit()
    client = TaskLeaseClient(conn=mem_db)
    args = dict(worker_id="physical-worker@HOST", host="HOST", generation="current",
                is_current=lambda: True, stop_event=threading.Event(), clock=lambda: T0)
    binding = WorkerLeaseBinding.acquire_next(client, {"id": "slot"}, **args)
    assert binding.task_id == first
    binding.execute_task_manage({"action": "done", "task_id": first})
    successor = WorkerLeaseBinding.acquire_next(client, {"id": "slot"}, **args)
    assert successor.task_id == second
    assert successor._ack.worker_id == binding._ack.worker_id
    assert successor._ack.lease_id != binding._ack.lease_id


def test_candidate_reassigned_after_page_is_skipped_using_fresh_detail(mem_db, monkeypatch):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    moved = _insert_task(mem_db, "Moved")
    suitable = _insert_task(mem_db, "Still suitable")
    mem_db.execute("UPDATE tasks SET assigned_to='BACH'")
    mem_db.execute("UPDATE tasks SET priority='P1' WHERE id=?", (moved,))
    mem_db.commit()
    client = TaskLeaseClient(conn=mem_db)
    original = client.task_candidates
    def page_then_reassign(**kwargs):
        page = original(**kwargs)
        mem_db.execute("UPDATE tasks SET assigned_slot='other-slot' WHERE id=?", (moved,))
        mem_db.commit()
        return page
    monkeypatch.setattr(client, "task_candidates", page_then_reassign)
    binding = WorkerLeaseBinding.acquire_next(client, {"id": "our-slot"},
        worker_id="physical-worker@HOST", host="HOST", generation="current",
        is_current=lambda: True, stop_event=threading.Event(), clock=lambda: T0)
    assert binding.task_id == suitable
    assert client.read(moved, now=T0).leased is False


def test_stop_during_inference_prevents_all_following_tool_dispatch(binding, monkeypatch):
    import asyncio
    from hub._services.chat import chat_runtime
    calls = []
    class Backend:
        def get_default_model(self): return "isolated-model"
        async def chat(self, messages, **kwargs):
            binding._stop_event.set()
            tools = [{"function": {"name": "get_datetime", "arguments": {}}}]
            return {"content": "", "tool_calls": tools,
                    "raw_message": {"role": "assistant", "content": "", "tool_calls": tools}}
        def tool_response_message(self, content, tool_call_id=""):
            return {"role": "tool", "content": content}
    runtime = chat_runtime.ChatRuntime(Backend())
    runtime.max_tool_rounds = 2
    session = runtime.get_session("worker-bound")
    session.worker_task_binding = binding
    session.require_task_binding = True
    monkeypatch.setattr(chat_runtime, "exec_tool", lambda *a, **kw: calls.append(a) or "tool")
    answer = asyncio.run(runtime.process("Auftrag", "worker-bound", work_priority="background"))
    assert isinstance(answer, chat_runtime.FailedAnswer)
    assert not calls


@pytest.mark.parametrize("assignee", ["user", "claude", "gemini", "codex", "other-agent"])
def test_automatic_worker_does_not_pick_human_or_other_agent_tasks(mem_db, assignee):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    protected = _insert_task(mem_db, "Protected")
    work = _insert_task(mem_db, "BACH work")
    mem_db.execute("UPDATE tasks SET assigned_to=?, priority='P1' WHERE id=?", (assignee, protected))
    mem_db.execute("UPDATE tasks SET assigned_to='BACH', priority='P2' WHERE id=?", (work,))
    mem_db.commit()
    client = TaskLeaseClient(conn=mem_db)
    chosen = WorkerLeaseBinding.acquire_next(client, {"id": "our-slot", "sub_mode": "task_worker"},
        worker_id="physical-worker@HOST", host="HOST", generation="current",
        is_current=lambda: True, stop_event=threading.Event(), clock=lambda: T0)
    assert chosen.task_id == work
    assert client.read(protected, now=T0).leased is False


def test_automatic_selection_reaches_eligible_work_beyond_first_thousand_candidates(mem_db):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    mem_db.executemany("INSERT INTO tasks (title, status, priority, assigned_to) VALUES (?, 'pending', 'P1', 'user')",
                      [(f"Human task {i}",) for i in range(1001)])
    mem_db.execute("INSERT INTO tasks (title, status, priority, assigned_to) VALUES ('Actual work', 'pending', 'P2', 'BACH')")
    mem_db.commit()
    client = TaskLeaseClient(conn=mem_db)
    chosen = WorkerLeaseBinding.acquire_next(client, {"id": "our-slot", "sub_mode": "task_worker"},
        worker_id="physical-worker@HOST", host="HOST", generation="current",
        is_current=lambda: True, stop_event=threading.Event(), clock=lambda: T0)
    assert chosen.task_snapshot()["title"] == "Actual work"
