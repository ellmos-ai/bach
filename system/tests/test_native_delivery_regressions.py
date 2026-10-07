"""Native delivery review regressions; isolated authority, no provider starts."""
import asyncio
import ast
import plistlib
from pathlib import Path

import pytest

from system.tests.test_task_lease_client import mem_db
from system.tests.test_worker_lease_binding import binding
from system.tests.test_worker_tool_bridge import bridge
from hub._services.chat import bach_tools
from hub._services.chat.chat_runtime import ChatRuntime
from hub._services.llm.model_backend import CLIBackend


@pytest.mark.parametrize("mode", ["safe", "full", "plan"])
def test_bound_tools_hide_paid_delegation_and_destructive_cleanup(binding, mode, monkeypatch):
    monkeypatch.setattr(bach_tools, "_delegate_claude_api", lambda *_a: pytest.fail("paid fallback"))
    provider = bach_tools.BachToolProvider(worker_task_binding=binding, require_task_binding=True)
    offered = {tool["function"]["name"] for tool in provider.get_tools(mode)}
    assert "delegate" not in offered and "cleanup_task_worktree" not in offered
    for name in ["delegate", "cleanup_task_worktree"]:
        assert "BLOCKIERT" in provider.execute(name, {"task_id": binding.task_id}, mode)


@pytest.mark.parametrize("foreign", [True, False])
def test_bound_worktree_start_checks_exact_task_before_dispatch(binding, monkeypatch, foreign):
    from hub import worker_git
    calls = []
    monkeypatch.setattr(worker_git, "start_task_worktree", lambda tid: calls.append(tid) or "isolated-worktree")
    tid = binding.task_id + int(foreign)
    result = bach_tools.exec_tool("start_task_worktree", {"task_id": tid}, "safe",
                                 worker_task_binding=binding, require_task_binding=True)
    assert calls == ([] if foreign else [tid])
    assert ("BLOCKIERT" in result) is foreign


def test_runtime_uses_private_claude_transport_and_authoritative_completion(bridge, monkeypatch):
    backend = CLIBackend(cli_name="claude", cli_path="not-started")
    runtime = ChatRuntime(backend=backend)
    session = runtime.get_session("leased-chat")
    session.mode = "safe"
    session.worker_task_binding = bridge.binding
    session.require_task_binding = True
    calls = []

    async def forbidden(*_a, **_kw):
        pytest.fail("unbound CLI fallback")

    async def private(messages, *, binding, mode, guard, **_kw):
        guard()
        assert binding is bridge.binding and mode == "safe"
        calls.append(messages)
        result = binding.execute_task_manage({"action": "done", "task_id": binding.task_id})
        return {"content": result, "tool_calls": None, "raw_message": {"content": result}}

    monkeypatch.setattr(backend, "chat", forbidden)
    monkeypatch.setattr(backend, "chat_bound", private)
    result = asyncio.run(runtime.process("Complete the bound task", "leased-chat", work_priority="background"))
    assert len(calls) == 1
    assert bridge.binding.completed_task_ids == (bridge.binding.task_id,)
    assert "erledigt" in result


def test_direct_script_imports_and_launchagent_use_package_safe_entry():
    system = Path(__file__).resolve().parents[1]
    source = (system / "hub/_services/chat/telegram_chat.py").read_text(encoding="utf-8")
    assert not any(isinstance(node, ast.ImportFrom) and node.level for node in ast.walk(ast.parse(source)))
    plist = plistlib.loads((system / "launchd/com.bach.telegram-bot.plist").read_bytes())
    assert " -m hub._services.chat.telegram_chat" in " ".join(plist["ProgramArguments"])


@pytest.mark.parametrize("action", ["handoff", "decompose"])
def test_managed_worker_refuses_unimplemented_step_actions(bridge, monkeypatch, action):
    from hub._services.chat import telegram_chat as controller
    control = controller._WorkerControl("private-worker", generation=bridge.binding.generation)
    control.thread = type("Thread", (), {"is_alive": lambda self: True})()
    control.task_binding = bridge.binding
    slot = {"id": "private-worker", "status": "running", "backend": "claude",
            "enabled": True, "allow_tools": True}
    monkeypatch.setattr(controller, "_WORKER_CONTROLS", {"private-worker": control})
    monkeypatch.setattr(controller, "_WORKER_EXECUTIONS", {})
    monkeypatch.setattr(controller, "_execution_worker_slot", lambda *_: slot)
    with pytest.raises(ValueError, match="keine verifizierte"):
        if action == "handoff":
            controller._request_worker_handoff("private-worker", control.generation)
        else:
            controller._request_worker_decomposition("private-worker", control.generation,
                bridge.binding.task_id, bridge.binding.task_snapshot()["task_version"])
    snapshot = controller._worker_handoff_snapshot(slot)
    assert snapshot["action_capabilities"] == {"handoff": False, "decompose": False}
    assert "task_action_binding" not in snapshot
    assert control.handoff.snapshot() is None and control.task_actions.snapshot() is None


@pytest.mark.parametrize("action", ["handoff", "decompose"])
def test_pending_action_after_backend_change_stops_private_cli(bridge, monkeypatch, action):
    from hub._services.chat.worker_handoff import WorkerHandoff
    from hub._services.chat.worker_task_actions import WorkerTaskActions
    from hub._services.chat.chat_runtime import FailedAnswer
    backend = CLIBackend(cli_name="claude", cli_path="not-started")
    runtime = ChatRuntime(backend=backend)
    session = runtime.get_session("leased-chat")
    session.worker_task_binding = bridge.binding
    session.require_task_binding = True
    if action == "handoff":
        session.worker_handoff = WorkerHandoff("private-worker", bridge.binding.generation)
        session.worker_handoff.request(bridge.binding.generation)
    else:
        session.worker_task_actions = WorkerTaskActions("private-worker", bridge.binding.generation)
        session.worker_task_actions.request(bridge.binding.generation, bridge.binding.task_id,
            bridge.binding.task_snapshot()["task_version"], bridge.binding)
    async def forbidden(*_a, **_kw):
        pytest.fail("pending action reached unsupported CLI")
    monkeypatch.setattr(backend, "chat_bound", forbidden)
    answer = asyncio.run(runtime.process("Auftrag", "leased-chat", work_priority="background"))
    assert isinstance(answer, FailedAnswer)
