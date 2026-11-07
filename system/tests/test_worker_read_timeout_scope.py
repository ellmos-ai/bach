"""T-20261107-718218941 (follow-up to #673): where a ReadTimeout without backend detail counts.

Measured 07.11.2026 on the Mac Studio (BACH read-only task-returns API, 30 days):
74 returns with ``model_failure:unclassified``, at most one per task, none blocked a
task. 68 of them came less than 3600 s after the same worker's previous release, so
they were no ReadTimeouts (read timeout there: 3600 s). The ReadTimeouts hid in that
bucket and showed only as a gap of about 3610 s.

Decision: a ReadTimeout gets its own code. It counts for the host
(``backend_error:transient:httpx_read_timeout``) only during a host-wide stall:
another task timed out before it and no worker run has succeeded since. Otherwise it
counts for the task (``model_failure:httpx_read_timeout``), so an oversized prompt
still blocks after five identical returns (PB-1, #681).
"""
import importlib
import json
import sqlite3

import httpx
import pytest

from hub._services.chat import slots_config as slots
from hub._services.chat.chat_runtime import ChatRuntime
from hub._services.llm.model_backend import OllamaBackend
from system.tests.test_worker_backend_errors import _persistent_session_store

TASK_NOTE = "model_failure:httpx_read_timeout"
HOST_NOTE = "backend_error:transient:httpx_read_timeout"


def _controller():
    return importlib.import_module("hub._services.chat.telegram_chat")


@pytest.fixture
def stalled_host(tmp_path, monkeypatch):
    """A continuous worker whose every model call ends in an httpx ReadTimeout."""
    pytest.importorskip("taskplan.return_policy")
    from hub._services import task_lease_client as client_module
    from hub._services.task_lease_client import TaskLeaseClient
    from system.tests.test_task_lease_client import _init_db
    control = _controller()
    monkeypatch.setattr(control, "_last_read_timeout", {}, raising=False)  # fresh host signal
    model = "glm-5.3:cloud"
    path = str(tmp_path / "slots.json")
    slots.initialize_slots_config(path)
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", path)
    ident = slots.add_worker({"name": "Stalled host fixture", "type": "continuous"}, path)["id"]
    slots.update_slot(ident, {"backend": "ollama", "model": model, "enabled": True,
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

    def acquire_or_stop(*args, **kwargs):
        bound = acquire(*args, **kwargs)
        if bound is None:  # queue drained: end this run instead of polling
            control._WORKER_EXECUTIONS[ident].stop_event.set()
        return bound
    monkeypatch.setattr(control, "_acquire_worker_task", acquire_or_stop)
    backend = OllamaBackend(default_model=model)
    runtime = ChatRuntime(backend, session_store=_persistent_session_store(tmp_path))
    monkeypatch.setattr(runtime, "_get_bach_context", lambda _: "")
    monkeypatch.setattr(runtime, "_get_memory_hook_context", lambda *a: "")
    monkeypatch.setattr(control, "runtime", runtime)
    monkeypatch.setattr(control, "_snapshot_chat_backend", lambda *a, **kw: (backend, model))
    monkeypatch.setattr(control, "_wait_worker_cooldown", lambda *a, **kw: True)
    real_client = httpx.AsyncClient

    def reply(request):
        if request.url.path == "/api/ps":
            return httpx.Response(500)  # no grace probe: the stall ends at once
        raise httpx.ReadTimeout("timed out", request=request)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw:
        real_client(transport=httpx.MockTransport(reply), **kw))

    class Host:
        def add(self, task_id, priority="P2"):
            conn.execute("INSERT INTO tasks (id,title,status,priority,category,assigned_to,assigned_slot) "
                         "VALUES (?,?,'pending',?,'INBOX','BACH',?)",
                         (task_id, f"Stalling task {task_id}", priority, ident))
            conn.commit()

        def run(self):
            response, code = control.start_worker_execution(ident)
            assert code == 200 and response["ok"] is True, response
            thread = control._WORKER_EXECUTIONS[ident].thread
            thread.join(15)
            assert not thread.is_alive()

        def notes(self, task_id):
            return [json.loads(row["new_value"])["note"] for row in conn.execute(
                "SELECT new_value FROM task_history WHERE task_id=? AND action='lease_release' "
                "ORDER BY id", (task_id,))]

        def status(self, task_id):
            return client.task_snapshot(task_id)["status"]

    try:
        yield Host()
    finally:
        execution = control._WORKER_EXECUTIONS.get(ident)
        if execution is not None and execution.thread is not None and execution.thread.is_alive():
            execution.stop_event.set()
            execution.thread.join(5)
        conn.close()


def test_oversized_prompt_on_a_healthy_host_still_blocks_after_five(stalled_host):
    """PB-1 stays closed: the same task stalls every time, nothing else stalls."""
    stalled_host.add(42)
    for _ in range(5):
        stalled_host.run()
    assert stalled_host.notes(42) == [TASK_NOTE] * 4 + [f"repeated_return:{TASK_NOTE}"]
    assert stalled_host.status(42) == "blocked"


def test_stalled_host_never_blocks_an_intact_task(stalled_host):
    """A4: every task stalls; only the first stall of the episode counts for its task."""
    stalled_host.add(41, "P1")
    stalled_host.add(42, "P2")
    for _ in range(6):
        stalled_host.run()
    assert stalled_host.notes(41) == [TASK_NOTE] + [HOST_NOTE] * 5
    assert stalled_host.notes(42) == [HOST_NOTE] * 6
    assert stalled_host.status(41) == stalled_host.status(42) == "pending"


def test_worker_still_stops_after_three_stalled_tasks(stalled_host):
    """The host note never blocks, so the worker's own stop keeps bounding the rotation."""
    for task_id in (41, 42, 43, 44):
        stalled_host.add(task_id, "P1" if task_id < 44 else "P3")
    stalled_host.run()
    returned = sorted(note for t in (41, 42, 43) for note in stalled_host.notes(t))
    assert returned == [HOST_NOTE, HOST_NOTE, TASK_NOTE]  # pickup order among equals is open
    assert stalled_host.notes(44) == []


def test_success_or_age_ends_the_host_stall(monkeypatch):
    control = _controller()
    monkeypatch.setattr(control, "_last_read_timeout", {}, raising=False)
    clock = [1000.0]
    monkeypatch.setattr(control.time, "monotonic", lambda: clock[0])

    def note(task_id):
        return control._worker_return_note(None, None, "httpx_read_timeout", task_id=task_id)
    assert note(1) == TASK_NOTE      # first stall: nothing says the host is at fault
    assert note(2) == HOST_NOTE      # a second task stalls right after
    assert note(2) == TASK_NOTE      # the same task again: its own fault
    control._note_worker_model_success()
    assert note(3) == TASK_NOTE      # a run succeeded in between: the host serves
    clock[0] += control._READ_TIMEOUT_HOST_WINDOW_SECONDS + 1
    assert note(4) == TASK_NOTE      # the earlier stall is too old to speak for the host
    assert control._worker_return_note(None, None, "httpx_read_timeout") == TASK_NOTE
    assert control._worker_return_note(None, None) == "model_failure:unclassified"
