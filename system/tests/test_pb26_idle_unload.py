"""Shared local model retention after a worker's queue becomes idle.

BACH #4214: queue ownership is not model ownership. Empty-worker polls must not
unload a model shared with chat or another worker, nor refresh its expiry.
Actual inference and empty warmup requests retain the existing finite adaptive
keep_alive (5m with compute competition, 30m otherwise).
"""
import asyncio
import importlib
import json
import sqlite3

import httpx
import pytest

from hub._services.chat import slots_config as slots
from hub._services.chat.chat_runtime import ChatRuntime
from hub._services.llm.model_backend import OllamaBackend, OpenRouterBackend
from system.tests.test_worker_backend_errors import _persistent_session_store

REAL_UNLOAD = OllamaBackend.unload  # conftest stubs it per test; these tests mock HTTP instead
MODEL = "qwen3.8:27b-mlx"
WAITING = {  # a verified empty-queue observation (schema bach.worker-queue.v1)
    "schema": "bach.worker-queue.v1", "state": "waiting", "reason": "empty_queue",
    "source": "canonical_task_api", "authority_mode": "local",
    "observed_at": "2026-11-07T22:00:00+00:00", "scan_complete": True,
    "candidate_count": 0, "matched_count": 0, "attempted_count": 0, "scanned_pages": 1,
    "rejected_counts": {},
}


def _controller():
    return importlib.import_module("hub._services.chat.telegram_chat")


@pytest.fixture
def ollama(monkeypatch):
    """Every HTTP request is recorded; nothing leaves the test."""
    events = []
    real_sync, real_async = httpx.Client, httpx.AsyncClient

    def reply(request):
        if request.url.path == "/api/generate":
            events.append(("unload", json.loads(request.content)))
            return httpx.Response(200, json={"done": True, "done_reason": "unload"})
        if request.url.path == "/api/chat":
            payload = json.loads(request.content)
            events.append(("chat_request", payload))
            reply = {"model": MODEL, "message": {"role": "assistant", "content": "OK"},
                     "done": True, "done_reason": "stop" if payload["messages"] else "load"}
            return httpx.Response(200, content=json.dumps(reply) + "\n",
                                  headers={"Content-Type": "application/x-ndjson"})
        events.append(("unexpected", request.url.path))
        return httpx.Response(500)
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_sync(transport=httpx.MockTransport(reply), **kw))
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: real_async(transport=httpx.MockTransport(reply), **kw))
    monkeypatch.setattr(OllamaBackend, "unload", REAL_UNLOAD)
    return events


@pytest.fixture
def worker(tmp_path, monkeypatch, ollama):
    """A continuous local-model worker on a real isolated task authority."""
    pytest.importorskip("taskplan.return_policy")
    from hub._services import task_lease_client as client_module
    from hub._services.task_lease_client import TaskLeaseClient
    from system.tests.test_task_lease_client import _init_db
    from hub._services.chat import worker_repo_registry
    control = _controller()
    # The host's real repo registry (present on the Mac) would mark test tasks "repository_unverified".
    monkeypatch.setattr(worker_repo_registry, "registry_path", lambda: tmp_path / "no-repo-registry.json")
    path = str(tmp_path / "slots.json")
    slots.initialize_slots_config(path)
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", path)
    ident = slots.add_worker({"name": "Idle unload fixture", "type": "continuous"}, path)["id"]
    slots.update_slot(ident, {"backend": "ollama", "model": MODEL, "enabled": True,
        "mode": "safe", "pause_after": 0, "max_tool_rounds": 5}, path)
    for registry in ("_WORKER_CONTROLS", "_WORKER_EXECUTIONS", "_ACTIVE_WORKER_THREADS"):
        monkeypatch.setattr(control, registry, {})
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    monkeypatch.setattr(client_module, "get_lead_config", lambda: {"mode": "isolated"})
    conn = sqlite3.connect(tmp_path / "tasks.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    client = TaskLeaseClient(conn=conn)
    monkeypatch.setattr(control, "_native_task_client", lambda: client)
    acquire = control._acquire_worker_task
    trace = []  # acquired task IDs, or why the selector found nothing

    def acquire_or_stop(*args, **kwargs):
        bound = acquire(*args, **kwargs)
        if bound is None:  # queue drained: end this run after the idle branch
            status = getattr(control._WORKER_CONTROLS.get(ident), "queue_status", None) or {}
            trace.append((status.get("reason"), status.get("rejected_counts")))
            control._WORKER_EXECUTIONS[ident].stop_event.set()
        else:
            trace.append(bound.task_id)
        return bound
    monkeypatch.setattr(control, "_acquire_worker_task", acquire_or_stop)
    backend = OllamaBackend(default_model=MODEL)
    runtime = ChatRuntime(backend, session_store=_persistent_session_store(tmp_path))
    monkeypatch.setattr(control, "runtime", runtime)
    monkeypatch.setattr(control, "_snapshot_chat_backend", lambda *a, **kw: (backend, MODEL))
    monkeypatch.setattr(control, "_wait_worker_cooldown", lambda *a, **kw: True)
    # This fixture performs only native task handback; its model is mocked and
    # never edits files. Git provisioning has dedicated scope tests and must
    # not inspect the developer's live repository locks during this test.
    monkeypatch.setattr(control, "_prepare_bound_task_scope",
                        lambda binding, _slot: binding.assert_active())

    async def process(*_args, **_kwargs):
        # The model works on the bound task and hands it back open, the most
        # frequent outcome on the Mac (37 of 39 bindings on 07.11.).
        ollama.append(("chat", None))
        binding = runtime.get_session(ident).worker_task_binding
        assert binding is not None and not binding.closed
        binding.execute_task_manage({"action": "update", "task_id": binding.task_id, "status": "pending"})
        return "Teilstand"
    monkeypatch.setattr(runtime, "process", process)

    class Worker:
        def __init__(self):
            self.trace = trace

        def add(self, task_id):
            conn.execute("INSERT INTO tasks (id,title,status,priority,category,assigned_to,assigned_slot) "
                         "VALUES (?,?,'pending','P2','INBOX','BACH',?)", (task_id, f"Task {task_id}", ident))
            conn.commit()

        def run(self):
            response, code = control.start_worker_execution(ident)
            assert code == 200 and response["ok"] is True, response
            thread = control._WORKER_EXECUTIONS[ident].thread
            thread.join(30)
            assert not thread.is_alive()

    try:
        yield Worker()
    finally:
        execution = control._WORKER_EXECUTIONS.get(ident)
        if execution is not None and execution.thread is not None and execution.thread.is_alive():
            execution.stop_event.set()
            execution.thread.join(5)
        conn.close()


def test_empty_queue_preserves_shared_model_retention(worker, ollama):
    worker.run()
    assert ollama == []


def test_queue_drain_does_not_unload_after_the_last_task(worker, ollama):
    worker.add(41)
    worker.run()
    assert ollama == [("chat", None)], worker.trace


def test_idle_polls_never_unload_or_extend_model_retention(ollama):
    control = _controller()
    run = control._WorkerControl(worker_id="w", queue_status=dict(WAITING))
    backend = OllamaBackend(default_model=MODEL)
    for _ in range(3):
        control._observe_idle_model_retention(run, backend, MODEL)
    assert run.idle_retention_reported is True
    assert ollama == []  # no unload and no keep_alive refresh on empty polls

    run.idle_retention_reported = False  # a task was acquired between idle periods
    control._observe_idle_model_retention(run, backend, MODEL)
    assert run.idle_retention_reported is True
    assert ollama == []

    for status in (None, {**WAITING, "state": "error", "reason": "selection_error",
                          "scan_complete": False, "scanned_pages": 0}):
        fresh = control._WorkerControl(worker_id="w", queue_status=status)
        control._observe_idle_model_retention(fresh, backend, MODEL)
        assert fresh.idle_retention_reported is False
    for model in ("glm-5.3:cloud", "gpt-oss:120b-cloud"):
        fresh = control._WorkerControl(worker_id="w", queue_status=dict(WAITING))
        control._observe_idle_model_retention(fresh, backend, model)
        assert fresh.idle_retention_reported is False
    fresh = control._WorkerControl(worker_id="w", queue_status=dict(WAITING))
    control._observe_idle_model_retention(fresh, OpenRouterBackend.__new__(OpenRouterBackend), MODEL)
    assert fresh.idle_retention_reported is False
    assert ollama == []


def test_idle_worker_cannot_unload_an_active_foreground_model(ollama, tmp_path, monkeypatch):
    from hub._services.chat.host_inference_gate import HostInferenceGate

    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    control = _controller()
    worker = control._WorkerControl(worker_id="idle-worker", queue_status=dict(WAITING))
    backend = OllamaBackend(default_model=MODEL)
    gate = HostInferenceGate()

    async def foreground():
        async with gate.turn("user-chat", "foreground"):
            control._observe_idle_model_retention(worker, backend, MODEL)
            assert gate.status()["active"] is True
            assert gate.status()["chat_id"] == "user-chat"
            assert ollama == []

    asyncio.run(foreground())


@pytest.mark.parametrize("compute_active,compute_paused,expected", [
    (False, False, "30m"), (True, False, "5m"), (False, True, "5m"),
])
@pytest.mark.parametrize("messages", [[], [{"role": "user", "content": "Hello"}]])
def test_real_requests_keep_finite_adaptive_retention_and_idle_poll_leaves_it_alone(
        ollama, monkeypatch, tmp_path, compute_active, compute_paused, expected, messages):
    from hub import compute_lock

    paused = tmp_path / "paused.json"
    if compute_paused:
        paused.write_text("{}")
    monkeypatch.setattr(compute_lock, "PAUSED_PIDS_FILE", str(paused))
    monkeypatch.setattr(compute_lock, "check_compute_active", lambda: (compute_active, {}))
    backend = OllamaBackend(default_model=MODEL)
    answer = asyncio.run(backend.chat(messages, think=False, model=MODEL))
    assert not answer.get("error")
    assert len(ollama) == 1 and ollama[0][0] == "chat_request"
    assert ollama[0][1]["keep_alive"] == expected

    control = _controller()
    worker = control._WorkerControl(worker_id="idle-worker", queue_status=dict(WAITING))
    for _ in range(3):
        control._observe_idle_model_retention(worker, backend, MODEL)
    assert len(ollama) == 1  # finite expiry remains owned by the actual model request
