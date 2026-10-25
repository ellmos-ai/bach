"""Private native worker binding: isolated authority, generation and receipts."""
import json
import threading

import pytest

from system.tests.test_task_lease_client import mem_db, _insert_task
from system.tests.test_task_lease_client_review import T0
from hub._services.task_lease_client import TaskLeaseClient, LeaseError, LeaseConnectionError
from system.tests.test_worker_tool_trace import binding as trace_binding
from system.tests.worker_completion_fixtures import CompletionHarness
from hub._services import worker_policy_settings as settings


def _self_check(work):
    return json.dumps({"schema": "bach.worker-self-check.v1", "complete": True,
        "completed_work": work, "checks": ["Fachliches Ergebnis gegen den Auftrag geprüft."],
        "remaining_required_work": []}, ensure_ascii=False)


def _require_personal_review(binding):
    """Keep tests about separate personal acceptance on an explicit user gate."""
    conn = binding._client._conn
    settings._persist(conn, settings.TASK_KEY + str(binding.task_id),
        {"mode": None, "require_user_review": True,
         "github_external_review": None, "allow_review_task_pickup": None},
        actor="fixture-explicit-user-review")
    conn.commit()


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


@pytest.fixture
def completion_binding(binding, tmp_path, monkeypatch):
    harness = CompletionHarness(tmp_path, monkeypatch)
    harness.prepare(binding, binding._client._conn)
    binding._test_completion_harness = harness
    return binding


def approve_result(binding, conn=None):
    """Separate operator on the isolated authority; never a provider credential."""
    from gui.device_auth import create_task_result_operator
    conn = conn if conn is not None else binding._client._conn
    harness = getattr(binding, "_test_completion_harness", None)
    assert isinstance(harness, CompletionHarness)
    observed = binding._client.task_result_snapshot(binding.task_id)
    record = observed["result"]
    token = create_task_result_operator(f"fixture-operator-{record['result_id']}", connection=conn)
    accepted = harness.accept(binding, conn, token)
    assert accepted["result"]["accepted"] is True
    assert accepted["status"] == "done"
    return accepted


def test_binding_uses_canonical_content_and_keeps_capability_private(binding):
    assert binding.task_id == binding.task_snapshot()["id"]
    assert "task_version" in binding.task_snapshot()
    assert binding._ack.lease_id not in str(binding.task_snapshot())
    assert binding._ack.lease_id not in repr(binding)


@pytest.mark.parametrize("ack_fault", [None, "before_commit", "after_commit", "malformed"])
def test_quarantine_blocks_requeue_and_never_falls_back_to_return(binding, monkeypatch, ack_fault):
    from dataclasses import replace
    from hub._services.task_lease_client import LeaseProtocolError
    binding.mark_tool_dispatch()
    native_release = binding._client.release
    def release(*args, **kwargs):
        assert kwargs["outcome"] == "blocked"
        if ack_fault == "before_commit":
            raise LeaseProtocolError("Isolated missing ACK before commit")
        ack = native_release(*args, **kwargs)
        if ack_fault == "after_commit":
            raise LeaseProtocolError("Isolated missing ACK after commit")
        return replace(ack, status="pending") if ack_fault == "malformed" else ack
    monkeypatch.setattr(binding._client, "release", release)
    assert binding.quarantine_lease() is (ack_fault is None)
    assert binding.return_lease() is False
    snapshot = binding._client.task_snapshot(binding.task_id)
    assert snapshot["status"] == ("in_progress" if ack_fault == "before_commit" else "blocked")
    assert binding.tool_dispatch_count == 1
    if ack_fault is not None:
        with pytest.raises(LeaseError):
            binding.assert_active()


def test_done_receipt_requires_submission_and_separate_authoritative_acceptance(completion_binding):
    binding = completion_binding
    _require_personal_review(binding)
    with pytest.raises(LeaseError):
        binding.execute_task_manage({"action": "done", "task_id": binding.task_id})
    binding.assert_active()
    result = binding.execute_task_manage({"action": "done", "task_id": binding.task_id,
                                         "result": _self_check("Konkretes fachliches Ergebnis erstellt.")})
    assert result == f"Task #{binding.task_id}: Ergebnis gespeichert; Abschlussstatus wird nach Policy ermittelt."
    assert binding.closed
    assert binding.completed_task_ids == () and binding.reviewed_task_ids == (binding.task_id,)
    approve_result(binding)
    assert binding.completed_task_ids == (binding.task_id,)
    with pytest.raises(LeaseError):
        binding.execute_task_manage({"action": "done", "task_id": binding.task_id})


def test_content_update_rebinds_before_next_mutation(binding):
    previous = binding.task_snapshot()["task_version"]
    binding.execute_task_manage({"action": "update", "task_id": binding.task_id,
                                 "description": "Änderung"})
    assert binding.task_snapshot()["task_version"] != previous
    assert binding.task_snapshot()["description"] == "Änderung"
    assert "Abschlussstatus wird nach Policy ermittelt" in binding.execute_task_manage({"action": "done", "task_id": binding.task_id,
                                                              "result": "Ergebnis für den geänderten Inhalt"})
    assert binding.submitted_result["task_version"] == binding.task_snapshot()["task_version"]


@pytest.mark.parametrize("changes", [{"status": "done", "description": "Must not apply"},
                                     {"status": "in_progress"}, {"unknown": "x"}])
def test_unsafe_update_does_not_partially_write(binding, changes):
    before = binding._client.task_snapshot(binding.task_id)
    with pytest.raises(LeaseError):
        binding.execute_task_manage({"action": "update", "task_id": binding.task_id, **changes})
    assert binding._client.task_snapshot(binding.task_id) == before


@pytest.mark.parametrize("cause", ["foreign-task", "stopped", "generation", "expired"])
def test_guard_prevents_mutation(binding, cause):
    args = {"action": "done", "task_id": binding.task_id, "result": "Konkretes Ergebnis"}
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
def test_decomposition_rebinds_without_parent_completion(binding, close):
    previous = binding.task_snapshot()["task_version"]
    if close:
        before = binding._client.task_snapshot(binding.task_id)
        with pytest.raises(LeaseError):
            binding.execute_task_manage({"action": "decompose", "task_id": binding.task_id,
                                         "subtasks": [{"title": "Kind"}], "close_parent": True})
        assert binding._client.task_snapshot(binding.task_id) == before
        assert not binding.closed and not binding.completed_task_ids
        binding.assert_active()
        return
    result = binding.execute_task_manage({"action": "decompose", "task_id": binding.task_id,
                                         "subtasks": [{"title": "Kind"}], "close_parent": close})
    assert "in 1 Teilaufgaben zerlegt: IDs" in result
    assert not binding.closed and not binding.completed_task_ids
    if not close:
        assert binding.task_snapshot()["task_version"] != previous
        binding.execute_task_manage({"action": "done", "task_id": binding.task_id,
                                    "result": "Zerlegungsplan mit bestätigten Kind-IDs: " + result})
        assert binding.reviewed_task_ids == (binding.task_id,)


def test_add_uses_parent_fenced_decomposition_without_completion_receipt(binding):
    previous = binding.task_snapshot()["task_version"]
    result = binding.execute_task_manage({"action": "add", "title": "Fortsetzung", "category": "TO-DECIDE"})
    assert "erstellt" in result
    assert not binding.closed and not binding.completed_task_ids
    assert binding.task_snapshot()["task_version"] != previous


def test_bound_decomposition_inherits_top_level_routing_and_preserves_child_overrides(binding, mem_db):
    result = binding.execute_task_manage({"action": "decompose", "task_id": binding.task_id,
        "assigned_slot": "buddha_research", "required_model": "chosen-model", "close_parent": False,
        "subtasks": [{"title": "Recherche"}, {"title": "Umsetzung", "assigned_slot": "buddha_developer"}]})
    assert "in 2 Teilaufgaben" in result
    rows = mem_db.execute("SELECT assigned_slot, required_model FROM tasks WHERE id<>? ORDER BY id", (binding.task_id,)).fetchall()
    assert [tuple(row) for row in rows] == [("buddha_research", "chosen-model"), ("buddha_developer", "chosen-model")]
    assert not binding.closed


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


def test_task_tool_dispatch_uses_private_binding_before_local_db(completion_binding, monkeypatch):
    binding = completion_binding
    _require_personal_review(binding)
    from hub._services.chat import bach_tools
    monkeypatch.setattr(bach_tools, "_current_runtime_db", lambda: pytest.fail("projection path accessed"))
    result = bach_tools.exec_tool(
        "task_manage",
        {"action": "update", "task_id": binding.task_id,
         "description": "Gebundene Teständerung ohne lokale Projektion"},
        mode="safe", worker_task_binding=binding)
    assert f"Task #{binding.task_id} aktualisiert: description" == result
    binding.assert_active()
    result = bach_tools.exec_tool("task_manage", {"action": "submit_result", "task_id": binding.task_id, "complete": True,
                                                   "result": _self_check("Konkretes Ergebnis ohne Projektion erstellt.")},
                                  mode="safe", worker_task_binding=binding)
    assert "Abschlussstatus wird nach Policy ermittelt" in result
    assert not binding.completed_task_ids and binding.reviewed_task_ids == (binding.task_id,)
    approve_result(binding)
    assert binding.completed_task_ids == (binding.task_id,)


def test_required_binding_cannot_fall_back_to_projection(monkeypatch):
    from hub._services.chat import bach_tools
    monkeypatch.setattr(bach_tools, "_current_runtime_db", lambda: pytest.fail("projection path accessed"))
    result = bach_tools.exec_tool("task_manage", {"action": "done", "task_id": 1},
                                  mode="safe", require_task_binding=True)
    assert "Taskbindung fehlt" in result


def test_real_native_process_releases_bound_task_without_post_completion_inference(trace_binding, monkeypatch):
    binding = trace_binding
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
                "action": "submit_result", "task_id": binding.task_id, "complete": True,
                "result": _self_check("Konkretes Ergebnis aus dem isolierten Lauf erstellt.")}}}]
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
    assert "Abschlussstatus wird nach Policy ermittelt" in str(answer)
    assert getattr(answer, "completed_task_ids", ()) == ()
    assert binding.reviewed_task_ids == (binding.task_id,) and not binding.completed_task_ids
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
    binding.execute_task_manage({"action": "done", "task_id": first, "result": "Ergebnis der ersten Aufgabe"})
    assert binding.reviewed_task_ids == (first,) and not binding.completed_task_ids
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


def test_returned_version_is_deferred_but_changed_content_can_be_picked(mem_db):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    first = _insert_task(mem_db, "Returned")
    second = _insert_task(mem_db, "Next")
    mem_db.execute("UPDATE tasks SET assigned_to='BACH'")
    mem_db.execute("UPDATE tasks SET priority='P1' WHERE id=?", (first,))
    mem_db.commit()
    client = TaskLeaseClient(conn=mem_db)
    args = dict(worker_id="physical-worker@HOST", host="HOST", generation="current",
                is_current=lambda: True, stop_event=threading.Event(), clock=lambda: T0)
    bound = WorkerLeaseBinding.acquire_next(client, {"id": "slot"}, **args)
    bound.execute_task_manage({"action": "update", "task_id": first, "status": "pending"})
    deferred = {first: bound.task_snapshot()["task_version"]}
    next_task = WorkerLeaseBinding.acquire_next(client, {"id": "slot"}, deferred_versions=deferred, **args)
    assert next_task.task_id == second
    next_task.execute_task_manage({"action": "done", "task_id": second, "result": "Ergebnis der zweiten Aufgabe"})
    assert WorkerLeaseBinding.acquire_next(client, {"id": "slot"}, deferred_versions=deferred, **args) is None
    mem_db.execute("UPDATE tasks SET description='Neue Voraussetzung' WHERE id=?", (first,))
    mem_db.commit()
    changed = WorkerLeaseBinding.acquire_next(client, {"id": "slot"}, deferred_versions=deferred, **args)
    assert changed.task_id == first
    assert changed.task_snapshot()["task_version"] != deferred[first]


@pytest.mark.parametrize("assigned_slot, expected", [("our-slot", True), (None, False), ("  ", False)])
def test_explicit_slot_assignment_precedes_generic_pickup_filter(request, assigned_slot, expected):
    task_db = request.getfixturevalue("mem_db")
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    tid = _insert_task(task_db, "Explicit GUI assignment")
    task_db.execute("UPDATE tasks SET assigned_to='user', assigned_slot=?, required_model='openrouter/free', "
                   "category='GUI', priority='P3' WHERE id=?", (assigned_slot, tid))
    task_db.commit()
    slot = {"id": "our-slot", "model": "openrouter/free", "pickup_filter": {
        "enabled": True, "categories": ["WORKER"], "priorities": ["P1", "P2"]}}
    client = TaskLeaseClient(conn=task_db)
    chosen = WorkerLeaseBinding.acquire_next(client, slot, worker_id="physical-worker@HOST", host="HOST",
        generation="current", is_current=lambda: True, stop_event=threading.Event(), clock=lambda: T0)
    assert (chosen is not None) is expected
    if expected:
        assert chosen.task_id == tid and chosen.task_snapshot()["category"] == "GUI"
        assert chosen.task_snapshot()["priority"] == "P3"
        assert client.read(tid, lease_id=chosen._ack.lease_id, now=T0).own
    else:
        assert client.read(tid, now=T0).leased is False


def test_explicit_task_id_remains_an_authorized_personal_task_route(mem_db):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    tid = _insert_task(mem_db, "Explicit personal route")
    mem_db.execute("UPDATE tasks SET assigned_to='user', category='WORKER', priority='P1' WHERE id=?", (tid,))
    mem_db.commit()
    client = TaskLeaseClient(conn=mem_db)
    bound = WorkerLeaseBinding.acquire_next(client,
        {"id": "our-slot", "task_id": tid, "model": "openrouter/free", "pickup_filter": {
            "enabled": True, "categories": ["WORKER"], "priorities": ["P1"]}},
        worker_id="physical-worker@HOST", host="HOST", generation="current",
        is_current=lambda: True, stop_event=threading.Event(), clock=lambda: T0)
    assert bound.task_id == tid
    assert client.read(tid, lease_id=bound._ack.lease_id, now=T0).own


@pytest.mark.parametrize("assigned_slot, required_model", [
    ("other-slot", "openrouter/free"), ("our-slot", "paid-model")])
def test_explicit_assignment_never_overrides_slot_or_model(request, monkeypatch, assigned_slot, required_model):
    task_db = request.getfixturevalue("mem_db")
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    tid = _insert_task(task_db)
    task_db.execute("UPDATE tasks SET assigned_slot=?, required_model=? WHERE id=?",
                   (assigned_slot, required_model, tid))
    task_db.commit()
    client = TaskLeaseClient(conn=task_db)
    monkeypatch.setattr(client, "acquire", lambda *a, **kw: pytest.fail("ineligible task acquired"))
    chosen = WorkerLeaseBinding.acquire_next(client,
        {"id": "our-slot", "model": "openrouter/free", "pickup_filter": {"enabled": True, "categories": ["WORKER"]}},
        worker_id="physical-worker@HOST", host="HOST", generation="current",
        is_current=lambda: True, stop_event=threading.Event(), clock=lambda: T0)
    assert chosen is None


@pytest.mark.parametrize("denial", ["foreign-holder", "dependency", "creator-priority"])
def test_explicit_assignment_keeps_canonical_acquire_guards(request, denial):
    task_db = request.getfixturevalue("mem_db")
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    tid = _insert_task(task_db)
    task_db.execute("ALTER TABLE tasks ADD COLUMN created_at TEXT")
    task_db.execute("UPDATE tasks SET assigned_slot='our-slot', required_model='openrouter/free', "
                   "category='GUI', priority='P3' WHERE id=?", (tid,))
    client = TaskLeaseClient(conn=task_db)
    if denial == "dependency":
        dependency = _insert_task(task_db, "Unfinished prerequisite")
        task_db.execute("UPDATE tasks SET depends_on=? WHERE id=?", (str(dependency), tid))
    if denial == "creator-priority":
        # Creator priority is off by default since BACH #2231; enable it explicitly.
        request.getfixturevalue("monkeypatch").setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "600")
        task_db.execute("UPDATE tasks SET created_by='user', created_at=? WHERE id=?", (T0.isoformat(), tid))
    task_db.commit()
    if denial == "foreign-holder":
        client.acquire(tid, worker_id="other@HOST", host="HOST", now=T0)
    slot = {"id": "our-slot", "model": "openrouter/free", "pickup_filter": {"enabled": True, "categories": ["WORKER"]}}
    chosen = WorkerLeaseBinding.acquire_next(client, slot, worker_id="physical-worker@HOST", host="HOST",
        generation="current", is_current=lambda: True, stop_event=threading.Event(), clock=lambda: T0)
    assert chosen is None
    if denial == "foreign-holder":
        assert client.read(tid, now=T0).holder["worker_id"] == "other@HOST"
    else:
        assert client.read(tid, now=T0).leased is False


@pytest.mark.parametrize("tags, expected", [("ready", True), ("waiting", False), ("delegated", False), ("", False)])
def test_explicit_assignment_preserves_required_and_excluded_tags(tags, expected):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    task = {"assigned_slot": "our-slot", "required_model": "openrouter/free",
            "category": "GUI", "priority": "P3", "tags": tags}
    slot = {"id": "our-slot", "model": "openrouter/free", "pickup_filter": {
        "enabled": True, "categories": ["WORKER"], "priorities": ["P1", "P2"],
        "tags": ["ready"], "exclude_tags": ["waiting", "delegated"]}}
    assert WorkerLeaseBinding._automatic_matches_slot(task, slot) is expected


def _binding_with_output_limit(mem_db, result_max_chars):
    columns = {row[1] for row in mem_db.execute("PRAGMA table_info(tasks)")}
    if "result_max_chars" not in columns:
        mem_db.execute("ALTER TABLE tasks ADD COLUMN result_max_chars INTEGER")
        mem_db.commit()
    task_id = _insert_task(mem_db, "Bounded worker task")
    mem_db.execute("UPDATE tasks SET result_max_chars=? WHERE id=?", (result_max_chars, task_id))
    mem_db.commit()
    client = TaskLeaseClient(conn=mem_db)
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    return WorkerLeaseBinding.acquire(
        client, task_id, worker_id="limited-worker@HOST", host="HOST",
        generation="limited-generation", is_current=lambda: True,
        stop_event=threading.Event(), clock=lambda: T0,
    )


@pytest.mark.parametrize("attempted_limit", [None, 2000])
def test_worker_update_cannot_loosen_output_limit(mem_db, attempted_limit):
    binding = _binding_with_output_limit(mem_db, 1000)
    before = binding._client.task_snapshot(binding.task_id)
    with pytest.raises(LeaseError, match="Ausgabelimit"):
        binding.execute_task_manage({
            "action": "update", "task_id": binding.task_id,
            "result_max_chars": attempted_limit,
        })
    assert binding._client.task_snapshot(binding.task_id) == before
    assert binding.task_snapshot()["result_max_chars"] == 1000
    binding.assert_active()
    assert not binding.closed


@pytest.mark.parametrize("attempted_limit", [None, 2000])
def test_exec_tool_returns_recoverable_limit_denial_without_update(
    request, monkeypatch, attempted_limit
):
    from hub._services.chat import bach_tools

    binding = _binding_with_output_limit(request.getfixturevalue("mem_db"), 1000)
    before = binding._client.task_snapshot(binding.task_id)
    update_calls = []
    original_update = binding._client.update

    def track_update(*args, **kwargs):
        update_calls.append((args, kwargs))
        return original_update(*args, **kwargs)

    monkeypatch.setattr(binding._client, "update", track_update)
    message = bach_tools.exec_tool(
        "task_manage",
        {"action": "update", "task_id": binding.task_id,
         "result_max_chars": attempted_limit},
        mode="safe",
        worker_task_binding=binding,
    )

    assert message == "Das Task-Ausgabelimit darf von einem Worker nicht gelockert werden."
    assert update_calls == []
    assert binding._client.task_snapshot(binding.task_id) == before
    assert binding.task_snapshot()["result_max_chars"] == 1000
    binding.assert_active()
    assert not binding.closed


@pytest.mark.parametrize(("old_limit", "new_limit"), [(1000, 500), (None, 500)])
def test_worker_update_can_keep_or_tighten_output_limit(mem_db, old_limit, new_limit):
    binding = _binding_with_output_limit(mem_db, old_limit)
    previous_version = binding.task_snapshot()["task_version"]
    binding.execute_task_manage({
        "action": "update", "task_id": binding.task_id,
        "result_max_chars": new_limit,
    })
    current = binding._client.task_snapshot(binding.task_id)
    assert current["result_max_chars"] == new_limit
    assert current["task_version"] != previous_version
    binding.assert_active()
    assert not binding.closed


def test_bound_prompt_keeps_missing_and_null_correction_pointer_legacy_identical():
    from hub._services.chat.telegram_chat import _bound_worker_prompt

    class Binding:
        task_id = 42001
        def __init__(self, snapshot):
            self._snapshot = snapshot
            self.context_calls = 0
        def task_snapshot(self):
            return dict(self._snapshot)
        def correction_context(self):
            self.context_calls += 1
            raise AssertionError("Legacy prompt must not request correction context")

    missing = Binding({"id": 42001, "title": "Legacy"})
    null = Binding({"id": 42001, "title": "Legacy", "result_correction_request_id": None})
    assert _bound_worker_prompt(missing, "Prompt") == _bound_worker_prompt(null, "Prompt")
    assert missing.context_calls == null.context_calls == 0


@pytest.mark.parametrize("pointer", ["8", True, False, 0])
def test_bound_prompt_rejects_malformed_non_null_correction_pointer(pointer):
    from hub._services.chat.telegram_chat import _bound_worker_prompt

    class Binding:
        task_id = 42001
        def __init__(self):
            self.context_calls = 0
        def task_snapshot(self):
            return {"id": 42001, "title": "Malformed", "result_correction_request_id": pointer}
        def correction_context(self):
            self.context_calls += 1
            return {"task_id": self.task_id, "correction": None}

    binding = Binding()
    with pytest.raises(RuntimeError, match="Korrekturkontext"):
        _bound_worker_prompt(binding, "Prompt")
    assert binding.context_calls == 0


@pytest.mark.parametrize("args", [{}, {"action": "list"}])
def test_task_manage_list_returns_only_the_bound_task(binding, monkeypatch, args):
    foreign_id = binding.task_id + 1000
    foreign_title = "Foreign task title must stay private"
    candidates_calls = []

    def foreign_candidates(*, limit):
        candidates_calls.append(limit)
        return {"tasks": [{"id": foreign_id, "title": foreign_title,
                           "priority": "P1", "status": "pending"}]}

    monkeypatch.setattr(binding._client, "task_candidates", foreign_candidates)
    listed = binding.execute_task_manage(args)
    assert candidates_calls == []
    assert str(binding.task_id) in listed
    assert str(foreign_id) not in listed
    assert foreign_title not in listed


def test_task_manage_detail_reads_only_the_bound_snapshot(binding, monkeypatch):
    foreign_id = binding.task_id + 1000
    reads = []
    original = binding._client.task_snapshot

    def tracked_snapshot(task_id):
        reads.append(task_id)
        if task_id != binding.task_id:
            return {"id": task_id, "description": "Foreign secret"}
        return original(task_id)

    monkeypatch.setattr(binding._client, "task_snapshot", tracked_snapshot)
    with pytest.raises(LeaseError) as exc:
        binding.execute_task_manage({"action": "detail", "task_id": foreign_id})
    assert reads == []
    assert str(foreign_id) not in str(exc.value)
    assert "Foreign secret" not in str(exc.value)

    detail = binding.execute_task_manage({"action": "detail", "task_id": binding.task_id})
    assert reads == []
    assert f"id: {binding.task_id}" in detail
    assert "Foreign secret" not in detail


@pytest.mark.parametrize(("backend", "model", "owner"), [
    ("openrouter", "openrouter/free", "openrouter"),
    ("ollama-cloud", "glm-5.3:cloud", "ollama-cloud"),
])
def test_external_profile_route_runs_bound_picker_to_review(
        request, monkeypatch, tmp_path, backend, model, owner):
    """Exercise each external alias through canonical selection and result review."""
    conn = request.getfixturevalue("mem_db")
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    from hub._services.task_lease_client import LeaseProtocolError, WorkerResultAck
    from hub._services.task_schema import ensure_task_slot_columns

    conn.execute("ALTER TABLE tasks ADD COLUMN created_at TEXT")
    ensure_task_slot_columns(conn)
    task_id = _insert_task(conn, "Bound external profile task", "pending")
    conn.execute(
        "UPDATE tasks SET category = ?, priority = ?, assigned_to = ?, "
        "assigned_slot = ?, required_model = ? WHERE id = ?",
        ("WORKER", "P1", owner, f"profile-{backend}", model, task_id),
    )
    foreign_id = _insert_task(conn, "Unrelated private task", "pending")
    conn.execute(
        "UPDATE tasks SET category = ?, priority = ?, assigned_to = ? WHERE id = ?",
        ("WORKER", "P1", "unrelated-owner", foreign_id),
    )
    conn.commit()

    slot = {"id": f"profile-{backend}", "backend": backend, "model": model}
    client = TaskLeaseClient(conn=conn)
    native_acquire = WorkerLeaseBinding.acquire.__func__
    automatic_acquires = []
    def capture_acquire(cls, actual_client, actual_task_id, **kwargs):
        automatic_acquires.append((actual_task_id, kwargs.get("automatic"), kwargs.get("slot")))
        return native_acquire(cls, actual_client, actual_task_id, **kwargs)
    monkeypatch.setattr(WorkerLeaseBinding, "acquire", classmethod(capture_acquire))
    binding = WorkerLeaseBinding.acquire_next(
        client, slot, worker_id=f"fixture-{backend}@HOST", host="HOST",
        generation="fixture-generation-1", is_current=lambda: True,
        stop_event=threading.Event(), clock=lambda: T0,
    )
    assert automatic_acquires == [(task_id, True, slot)]
    from hub._services.task_lease_client import LeaseAck
    assert isinstance(binding._ack, LeaseAck)
    assert binding.task_id == task_id
    own = client.read(task_id, lease_id=binding._ack.lease_id, now=T0)
    assert own.own is True and own.leased is True and own.fence == binding._ack.fence

    listing = binding.execute_task_manage({"action": "list"})
    detail = binding.execute_task_manage({"action": "detail", "task_id": task_id})
    assert "Bound external profile task" in listing and "Unrelated private task" not in listing
    assert "Bound external profile task" in detail and "Unrelated private task" not in detail
    with pytest.raises(LeaseProtocolError):
        binding.execute_task_manage({"action": "detail", "task_id": foreign_id})

    harness = CompletionHarness(tmp_path, monkeypatch)
    actual_backend = "ollama" if backend == "ollama-cloud" else backend
    harness.prepare(binding, conn, backend_id=actual_backend, requested_model=model,
                    observed_model=model, slot_id=f"profile-{backend}")
    binding._test_completion_harness = harness
    _require_personal_review(binding)

    actual_submit = client.submit_result
    acknowledgements = []
    def capture_submit(*args, **kwargs):
        acknowledgement = actual_submit(*args, **kwargs)
        acknowledgements.append(acknowledgement)
        return acknowledgement
    monkeypatch.setattr(client, "submit_result", capture_submit)
    message = binding.execute_task_manage({
        "action": "submit_result", "task_id": task_id,
        "result": _self_check("Bound route produced a result with sources and limits."),
    })
    assert "Abschlussstatus wird nach Policy ermittelt" in message
    assert len(acknowledgements) == 1 and isinstance(acknowledgements[0], WorkerResultAck)
    result_ack = acknowledgements[0]
    assert result_ack.release.outcome == "review" and result_ack.release.status == "review"
    assert result_ack.record["task_id"] == task_id
    assert result_ack.record["generation"] == "fixture-generation-1"
    assert result_ack.record["fence"] == binding._ack.fence
    assert result_ack.record["task_version"] == binding._ack.task_version
    assert binding.closed and binding.reviewed_task_ids == (task_id,)
    approve_result(binding, conn=conn)
    assert binding.completed_task_ids == (task_id,)


@pytest.mark.parametrize(("backend", "model", "owner"), [
    ("openrouter", "openrouter/free", "openrouter"),
    ("ollama-cloud", "glm-5.3:cloud", "ollama-cloud"),
])
@pytest.mark.parametrize("mismatch", ["owner", "slot", "model"])
def test_external_profile_acquire_rejects_mismatched_route(
        request, backend, model, owner, mismatch):
    conn = request.getfixturevalue("mem_db")
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    from hub._services.task_lease_client import LeaseError
    from hub._services.task_schema import ensure_task_slot_columns

    conn.execute("ALTER TABLE tasks ADD COLUMN created_at TEXT")
    ensure_task_slot_columns(conn)
    task_id = _insert_task(conn, "Profile route mismatch", "pending")
    values = {"assigned_to": owner, "assigned_slot": f"profile-{backend}",
              "required_model": model}
    if mismatch == "owner":
        values["assigned_to"] = "another-provider"
    elif mismatch == "slot":
        values["assigned_slot"] = "different-profile"
    else:
        values["required_model"] = "different-model"
    conn.execute(
        "UPDATE tasks SET category = ?, priority = ?, assigned_to = ?, "
        "assigned_slot = ?, required_model = ? WHERE id = ?",
        ("WORKER", "P1", values["assigned_to"], values["assigned_slot"],
         values["required_model"], task_id),
    )
    conn.commit()
    client = TaskLeaseClient(conn=conn)
    slot = {"id": f"profile-{backend}", "backend": backend, "model": model}
    with pytest.raises(LeaseError):
        WorkerLeaseBinding.acquire(
            client, task_id, worker_id=f"fixture-{backend}@HOST", host="HOST",
            generation="fixture-generation-1", is_current=lambda: True,
            stop_event=threading.Event(), clock=lambda: T0,
            slot=slot, automatic=True,
        )
    assert client.read(task_id, now=T0).leased is False


def test_foreign_detail_names_the_bound_scope_and_keeps_the_binding(binding):
    """#2518: the model learns that only its own task is readable and keeps working."""
    from hub._services.chat.worker_lease_binding import WorkerTaskManageArgumentError
    with pytest.raises(WorkerTaskManageArgumentError) as exc:
        binding.execute_task_manage({"action": "detail", "task_id": binding.task_id + 999})
    assert exc.value.reason == "detail_scope" and "eigene ID" in exc.value.user_message
    binding.assert_active()
    assert f"id: {binding.task_id}" in binding.execute_task_manage({"action": "detail", "task_id": binding.task_id})


@pytest.mark.parametrize("owner, accepted", [("help-inventory", False), ("OLLAMA", True)])
def test_subtask_owner_must_be_a_known_assignee(binding, mem_db, owner, accepted):
    """#2518: Buddha wrote a topic into assigned_to; no worker could pick the children."""
    from hub._services.chat.worker_lease_binding import WorkerTaskManageArgumentError
    args = {"action": "decompose", "task_id": binding.task_id, "close_parent": False,
            "subtasks": [{"title": "Kind", "assigned_to": owner}]}
    if accepted:
        assert "in 1 Teilaufgaben" in binding.execute_task_manage(args)
    else:
        with pytest.raises(WorkerTaskManageArgumentError) as exc:
            binding.execute_task_manage(args)
        assert exc.value.reason == "decompose_assignee"
        assert mem_db.execute("SELECT COUNT(*) FROM tasks WHERE id<>?", (binding.task_id,)).fetchone()[0] == 0
    binding.assert_active()
