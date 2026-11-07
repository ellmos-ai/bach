"""PB-26 (T-20261107-173490917): unload the local model once the worker queue is empty.

Lukas, 07.11.2026: "solange arbeit in der bach queue ist" the model stays; "wenn keine
aufgaben da sind sollte tatsächlich ein entladen folgen". Measured on the Mac Studio the
same day: qwen3.8:27b-mlx holds 27.5 GB at num_ctx 16384 and BACH sends keep_alive 30m,
so an idle queue kept the model resident for another half hour.

Contract: a verified "no claimable task" observation sends exactly one
``keep_alive: 0`` per idle period; the next acquired task re-arms it and its model call
loads the model again through the normal reserve gate.
"""
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
    control = _controller()
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


def test_empty_queue_unloads_the_model_exactly_once(worker, ollama):
    worker.run()
    assert ollama == [("unload", {"model": MODEL, "keep_alive": 0})]


def test_no_unload_while_work_is_queued_only_after_the_last_task(worker, ollama):
    worker.add(41)
    worker.run()
    assert ollama == [("chat", None), ("unload", {"model": MODEL, "keep_alive": 0})], worker.trace


def test_one_unload_per_idle_period_and_never_without_a_verified_empty_queue(ollama):
    control = _controller()
    run = control._WorkerControl(worker_id="w")
    backend = OllamaBackend(default_model=MODEL)
    run.queue_status = dict(WAITING)
    for _ in range(3):  # three empty polls, one unload
        control._unload_idle_worker_model(run, backend, MODEL)
    assert ollama == [("unload", {"model": MODEL, "keep_alive": 0})]
    run.idle_model_unloaded = False  # the worker acquired a task in between
    control._unload_idle_worker_model(run, backend, MODEL)
    assert len(ollama) == 2

    ollama.clear()
    for status in (None, {**WAITING, "state": "error", "reason": "selection_error",
                          "scan_complete": False, "scanned_pages": 0}):
        fresh = control._WorkerControl(worker_id="w", queue_status=status)
        control._unload_idle_worker_model(fresh, backend, MODEL)  # unverified queue: keep the model
    for model in ("glm-5.3:cloud", "gpt-oss:120b-cloud"):
        fresh = control._WorkerControl(worker_id="w", queue_status=dict(WAITING))
        control._unload_idle_worker_model(fresh, backend, model)  # cloud models hold no local memory
    fresh = control._WorkerControl(worker_id="w", queue_status=dict(WAITING))
    control._unload_idle_worker_model(fresh, OpenRouterBackend.__new__(OpenRouterBackend), MODEL)
    assert ollama == []
