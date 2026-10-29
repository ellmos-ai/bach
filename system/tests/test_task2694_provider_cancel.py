# -*- coding: utf-8 -*-
"""Task 2694: deterministischer No-Chunk-Abbruch (worker_stop) und _WorkerControl-Isolation."""

import asyncio
import os
import sys
import threading
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402
from hub._services.llm import model_backend as backend_module  # noqa: E402
from hub._services.llm.model_backend import OllamaBackend  # noqa: E402
from hub._services.chat import telegram_chat  # noqa: E402


def test_no_chunk_stream_obeys_worker_stop_without_ping(monkeypatch):
    """Stream liefert nie eine Zeile; worker_stop bricht ab, ohne dass ein Ping abgesetzt wird."""
    read_started = threading.Event()
    read_cancelled = threading.Event()
    response_closed = threading.Event()
    client_closed = threading.Event()
    ping_calls = 0
    total_cap = 2.0
    idle_timeout = 1.0
    original_limit = backend_module.limit

    def bounded_limit(name):
        if name == "BACH_LLM_TOTAL_CAP":
            return total_cap
        if name == "BACH_LLM_IDLE_TIMEOUT":
            return idle_timeout
        if name == "BACH_LLM_IDLE_GRACE":
            return 2
        if name == "BACH_LLM_PING_TIMEOUT":
            return 10
        return original_limit(name)

    monkeypatch.setattr(backend_module, "limit", bounded_limit)

    class NoChunkStream:
        def __init__(self):
            self.status_code = 200
            self.headers = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            response_closed.set()
            return False

        def raise_for_status(self):
            pass

        async def aiter_lines(self):
            read_started.set()
            try:
                await asyncio.Event().wait()
                yield ""  # Unerreichbar: wait() endet nie regulär -> nie eine Zeile.
            finally:
                read_cancelled.set()

    class NoChunkClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            client_closed.set()
            return False

        def stream(self, *_args, **_kwargs):
            return NoChunkStream()

        async def get(self, *_args, **_kwargs):
            global ping_calls
            ping_calls += 1
            await asyncio.Event().wait()

    client = NoChunkClient()
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: client)

    async def run():
        cancel_event = asyncio.Event()
        asyncio.get_running_loop().call_later(0.05, cancel_event.set)
        result = await OllamaBackend(default_model="m").chat(
            [{"role": "user", "content": "bounded liveness probe"}],
            cancel_event=cancel_event,
        )
        pending = [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()
        ]
        return result, pending

    result, pending = asyncio.run(run())

    assert result["provider_request_aborted"] == "worker_stop"
    assert result["tool_calls"] is None
    assert result["content"] in (None, "")
    assert read_started.is_set()
    assert read_cancelled.is_set()
    assert response_closed.is_set()
    assert client_closed.is_set()
    assert ping_calls == 0
    assert pending == []


def test_worker_control_register_guards_and_finish():
    """register_provider_request-Wächter und finish_provider_request-Isolation."""
    binding = object()
    control = telegram_chat._WorkerControl(worker_id=f"task2694-{uuid.uuid4().hex}")
    control.task_binding = binding
    try:
        # (a) Ohne Map-Eintrag wird die Registrierung abgelehnt.
        assert control.register_provider_request(binding, None, None) is None
        # (b) Map-Eintrag herstellen.
        telegram_chat._WORKER_CONTROLS[control.worker_id] = control
        # (c) task_binding None wird abgelehnt.
        assert control.register_provider_request(None, None, None) is None
        # (d) Fremdes Binding wird abgelehnt.
        assert control.register_provider_request(object(), None, None) is None
        # (e) Gesetztes stop_event verhindert die Registrierung.
        control.stop_event.set()
        assert control.register_provider_request(binding, None, None) is None
        control.stop_event.clear()
        # (f) Erfolgreiche Registrierung.
        handle = control.register_provider_request(binding, None, None)
        assert handle is not None
        assert handle.task_binding is binding
        assert handle.worker_generation == control.generation
        assert control.active_model_request is handle
        # (g) Doppelte Registrierung wird abgelehnt.
        assert control.register_provider_request(binding, None, None) is None
        # (h) Fremdes finish veraendert active_model_request nicht.
        control.finish_provider_request(object())
        assert control.active_model_request is handle
        # (i) Passendes finish raumt den Handle ab.
        control.finish_provider_request(handle)
        assert control.active_model_request is None
        # (j) Re-Register nach finish ist moeglich.
        handle2 = control.register_provider_request(binding, None, None)
        assert handle2 is not None
        assert handle2 is not handle
        control.finish_provider_request(handle2)
    finally:
        telegram_chat._WORKER_CONTROLS.pop(control.worker_id, None)


def test_worker_control_cancel_active_model_request():
    """cancel_active_model_request setzt cancel_requested und signalisiert das Event."""

    async def run():
        loop = asyncio.get_running_loop()
        binding = object()
        control = telegram_chat._WorkerControl(worker_id=f"task2694-{uuid.uuid4().hex}")
        control.task_binding = binding
        telegram_chat._WORKER_CONTROLS[control.worker_id] = control
        try:
            cancel_event = asyncio.Event()
            handle = control.register_provider_request(binding, loop, cancel_event)
            assert handle is not None
            assert handle.cancel_requested is False
            assert not cancel_event.is_set()
            control.stop_event.set()
            assert control.cancel_active_model_request() is True
            assert handle.cancel_requested is True
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert cancel_event.is_set()
        finally:
            telegram_chat._WORKER_CONTROLS.pop(control.worker_id, None)

    asyncio.run(run())


def test_worker_control_cancel_rejects_unauthorized_states():
    """cancel_active_model_request lehnt unautorisierte Zustaende ab."""

    async def run():
        base = f"task2694-{uuid.uuid4().hex}"
        loop = asyncio.get_running_loop()

        # Szenario A: Ohne stop_event wird der Abbruch abgelehnt.
        binding_a = object()
        control_a = telegram_chat._WorkerControl(worker_id=f"{base}-a")
        control_a.task_binding = binding_a
        telegram_chat._WORKER_CONTROLS[control_a.worker_id] = control_a
        try:
            event_a = asyncio.Event()
            handle_a = control_a.register_provider_request(binding_a, loop, event_a)
            assert handle_a is not None
            assert control_a.cancel_active_model_request() is False
            await asyncio.sleep(0)
            assert not event_a.is_set()
        finally:
            telegram_chat._WORKER_CONTROLS.pop(control_a.worker_id, None)

        # Szenario B: Generations-Mismatch wird abgelehnt.
        binding_b = object()
        control_b = telegram_chat._WorkerControl(worker_id=f"{base}-b")
        control_b.task_binding = binding_b
        telegram_chat._WORKER_CONTROLS[control_b.worker_id] = control_b
        try:
            event_b = asyncio.Event()
            handle_b = control_b.register_provider_request(binding_b, loop, event_b)
            assert handle_b is not None
            handle_b.worker_generation = "andere-generation"
            control_b.stop_event.set()
            assert control_b.cancel_active_model_request() is False
            await asyncio.sleep(0)
            assert not event_b.is_set()
        finally:
            telegram_chat._WORKER_CONTROLS.pop(control_b.worker_id, None)

        # Szenario C: Binding-Mismatch nach Registrierung wird abgelehnt.
        binding_c = object()
        control_c = telegram_chat._WorkerControl(worker_id=f"{base}-c")
        control_c.task_binding = binding_c
        telegram_chat._WORKER_CONTROLS[control_c.worker_id] = control_c
        try:
            event_c = asyncio.Event()
            handle_c = control_c.register_provider_request(binding_c, loop, event_c)
            assert handle_c is not None
            control_c.task_binding = object()
            control_c.stop_event.set()
            assert control_c.cancel_active_model_request() is False
            await asyncio.sleep(0)
            assert not event_c.is_set()
        finally:
            telegram_chat._WORKER_CONTROLS.pop(control_c.worker_id, None)

    asyncio.run(run())