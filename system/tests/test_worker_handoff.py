import asyncio
from unittest.mock import AsyncMock

import pytest

from hub._services.chat.worker_handoff import WorkerHandoff
from hub._services.chat.chat_runtime import ChatRuntime, FailedAnswer


def test_request_is_bound_to_generation_and_consumed_once():
    control = WorkerHandoff("worker-1", "generation-1")
    with pytest.raises(ValueError):
        control.request("old-generation")
    receipt = control.request("generation-1")
    assert receipt["state"] == "pending"
    assert receipt["confirmed_at"] is None
    with pytest.raises(ValueError):
        control.request("generation-1")
    assert control.consume() == receipt["request_id"]
    assert control.consume() is None
    assert control.snapshot()["state"] == "running"
    control.finish(receipt["request_id"], succeeded=True)
    assert control.snapshot()["state"] == "confirmed"
    assert control.snapshot()["confirmed_at"]


def test_stale_confirmation_and_cancel_cannot_confirm():
    control = WorkerHandoff("worker-1", "generation-1")
    receipt = control.request("generation-1")
    control.consume()
    assert control.finish("wrong-request", succeeded=True) is False
    control.cancel()
    assert control.finish(receipt["request_id"], succeeded=True) is False
    assert control.snapshot()["state"] == "cancelled"
    assert control.snapshot()["confirmed_at"] is None
    with pytest.raises(ValueError):
        control.request("generation-1")


def test_cancel_before_boundary_prevents_model_call():
    backend = type("Backend", (), {
        "get_default_model": lambda self: "test-model",
        "chat": AsyncMock(return_value={"content": "unreachable"}),
    })()
    runtime = ChatRuntime(backend)
    session = runtime.get_session("worker-1")
    session.worker_handoff = WorkerHandoff("worker-1", "generation-1")
    session.worker_handoff.request("generation-1")
    session.worker_handoff.cancel()
    answer = asyncio.run(runtime._tool_loop([], session, tools=[]))
    assert isinstance(answer, FailedAnswer)
    backend.chat.assert_not_awaited()


@pytest.mark.parametrize("empty,cancelled", [(False, False), (True, False), (False, True)])
def test_real_handoff_path_requires_nonempty_summary_and_current_run(empty, cancelled):
    calls = []
    handoff_control = WorkerHandoff("worker-1", "generation-1")
    handoff_control.request("generation-1")

    class Backend:
        def get_default_model(self):
            return "test-model"

        async def chat(self, messages, **kwargs):
            calls.append(messages)
            if len(calls) == 1:
                if cancelled:
                    handoff_control.cancel()
                return {"content": "" if empty else "RESUME: Tests ausführen"}
            return {"content": "Weiter"}

    runtime = ChatRuntime(Backend())
    runtime.auto_continue = 0
    session = runtime.get_session("worker-1")
    session.worker_handoff = handoff_control
    answer = asyncio.run(runtime._tool_loop([
        {"role": "system", "content": "Rolle: Entwickler"},
        {"role": "user", "content": "Aufgabe"},
    ], session, tools=[]))
    if empty or cancelled:
        assert isinstance(answer, FailedAnswer)
        assert len(calls) == 1
        assert handoff_control.snapshot()["state"] == ("cancelled" if cancelled else "error")
        assert handoff_control.snapshot()["confirmed_at"] is None
    else:
        assert answer == "Weiter"
        assert len(calls) == 2
        assert calls[1][0] == {"role": "system", "content": "Rolle: Entwickler"}
        assert "RESUME: Tests ausführen" in calls[1][1]["content"]
        assert handoff_control.snapshot()["state"] == "confirmed"


@pytest.mark.parametrize("condition", ["current", "stale", "paused", "expired", "stopping"])
def test_controller_checks_current_run_status_and_expiry(monkeypatch, condition):
    from hub._services.chat import telegram_chat as controller
    control = controller._WorkerControl("worker-1")
    control.thread = type("Thread", (), {"is_alive": lambda self: True})()
    slot = {"id": "worker-1", "status": "paused" if condition == "paused" else "running"}
    if condition == "expired":
        slot["expires_at"] = "2020-01-01T00:00:00+00:00"
    if condition == "stopping":
        control.stop_event.set()
    monkeypatch.setattr(controller, "_WORKER_CONTROLS", {"worker-1": control})
    monkeypatch.setattr(controller, "get_worker_slot", lambda worker_id: slot)
    generation = "old" if condition == "stale" else control.generation
    if condition != "current":
        with pytest.raises(ValueError):
            controller._request_worker_handoff("worker-1", generation)
        assert control.handoff.snapshot() is None
    else:
        receipt = controller._request_worker_handoff("worker-1", generation)
        snapshot = controller._worker_handoff_snapshot(slot)
        assert snapshot["handoff_receipt"] == receipt
        assert snapshot["generation"] == generation


@pytest.mark.parametrize("fails", [False, True])
def test_runtime_performs_requested_handoff_before_model_call(fails):
    backend = type("Backend", (), {
        "get_default_model": lambda self: "test-model",
        "chat": AsyncMock(return_value={"content": "Weiter"}),
    })()
    runtime = ChatRuntime(backend)
    runtime.auto_continue = 0
    session = runtime.get_session("worker-1")
    session.worker_handoff = WorkerHandoff("worker-1", "generation-1")
    session.worker_handoff.request("generation-1")
    handoff = AsyncMock(side_effect=RuntimeError("unavailable")) if fails else AsyncMock(
        return_value=[{"role": "user", "content": "Zusammenfassung"}]
    )
    runtime._handoff = handoff
    answer = asyncio.run(runtime._tool_loop(
        [{"role": "user", "content": "Aufgabe"}], session, tools=[]
    ))
    handoff.assert_awaited_once()
    if fails:
        assert isinstance(answer, FailedAnswer)
        backend.chat.assert_not_awaited()
        assert session.worker_handoff.snapshot()["state"] == "error"
    else:
        assert answer == "Weiter"
        assert session.worker_handoff.snapshot()["state"] == "confirmed"
        contents = [m["content"] for m in backend.chat.await_args.args[0]]
        assert contents == ["Zusammenfassung", "[Werkzeugrunde 0/12 · noch 12]"]
