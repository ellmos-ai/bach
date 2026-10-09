"""Bound managed invocation with actual isolated relay, no agent CLI starts."""
import asyncio
import json
import threading

import pytest

from system.tests.test_worker_tool_bridge import bridge
from hub._services.chat.worker_tool_client import WorkerToolClient
from hub._services.llm.model_backend import CLIBackend


def test_bound_claude_uses_only_private_tools_and_selected_configuration(bridge, monkeypatch):
    backend = CLIBackend(cli_name="claude", cli_path="configured-claude", default_model="selected-model",
                         max_turns=7, permission_mode="full", cwd="configured-workdir")
    backend._session_active = True  # A foreign earlier session must never be continued.
    calls = []
    def physical(cmd, prompt, env, flags):
        calls.append((cmd, prompt, env, flags))
        client = WorkerToolClient.from_environment(env)
        assert any(t["function"]["name"] == "task_manage" for t in client.tools())
        result, failed = client.call("task_manage", {"action": "done", "task_id": bridge.binding.task_id, "result": "Konkretes Ergebnis des CLI-Laufs"})
        assert not failed
        return result
    monkeypatch.setattr(backend, "_run_subprocess", physical)
    result = asyncio.run(backend.chat_bound([{"role": "system", "content": "Actual role"},
                                            {"role": "user", "content": "Actual task"}],
        binding=bridge.binding, mode="safe", guard=lambda: bridge.binding.assert_active(), model="override-model"))
    cmd, prompt, env, flags = calls[0]
    assert cmd[:6] == ["configured-claude", "-p", "--output-format", "text", "--model", "override-model"]
    assert cmd[cmd.index("--max-turns") + 1] == "7"
    assert "--continue" not in cmd and "--dangerously-skip-permissions" not in cmd
    assert "--strict-mcp-config" in cmd and "--no-session-persistence" in cmd
    assert "--bare" not in cmd  # Preserve configured subscription authentication.
    assert cmd[cmd.index("--setting-sources") + 1] == ""
    assert json.loads(cmd[cmd.index("--settings") + 1]) == {"disableAllHooks": True, "enabledPlugins": {}}
    assert "--disable-slash-commands" in cmd and "--no-chrome" in cmd
    assert cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--allowedTools") + 1] == "mcp__bach_worker__*"
    config = json.loads(cmd[cmd.index("--mcp-config") + 1])
    assert set(config["mcpServers"]) == {"bach_worker"}
    assert env["BACH_WORKER_TOOL_TOKEN"] not in str(cmd) + prompt + str(result)
    assert bridge.binding._ack.lease_id not in str(cmd) + prompt + str(result)
    assert "Actual role" in prompt and "Actual task" in prompt
    assert result["content"] == f"Task #{bridge.binding.task_id}: Ergebnis gespeichert, wartet in Review auf getrennte Abnahme."
    assert bridge.binding.completed_task_ids == ()
    assert bridge.binding.reviewed_task_ids == (bridge.binding.task_id,)
    assert backend.cwd == "configured-workdir"


def test_bound_claude_masks_private_environment_in_failure(bridge, monkeypatch):
    backend = CLIBackend(cli_name="claude", cli_path="unused")
    def physical(cmd, prompt, env, flags):
        return {"error": "failed: " + env["BACH_WORKER_TOOL_TOKEN"], "content": env["BACH_WORKER_TOOL_TOKEN"]}
    monkeypatch.setattr(backend, "_run_subprocess", physical)
    result = asyncio.run(backend.chat_bound([], binding=bridge.binding, mode="safe", guard=lambda: None))
    assert "[redacted]" in result["error"] and result["content"] == "[redacted]"
    assert not bridge.binding.completed_task_ids


def test_bound_invocation_rechecks_guard_before_physical_start(bridge, monkeypatch):
    backend = CLIBackend(cli_name="claude", cli_path="unused")
    calls = []
    monkeypatch.setattr(backend, "_run_subprocess", lambda *a: calls.append(a))
    def stopped(): raise RuntimeError("private policy detail")
    with pytest.raises(RuntimeError):
        asyncio.run(backend.chat_bound([], binding=bridge.binding, mode="safe", guard=stopped))
    assert not calls


def test_unverified_managed_cli_cannot_start_with_binding(bridge, monkeypatch):
    backend = CLIBackend(cli_name="codex", cli_path="unused")
    calls = []
    monkeypatch.setattr(backend, "_run_subprocess", lambda *a: calls.append(a))
    with pytest.raises(RuntimeError):
        asyncio.run(backend.chat_bound([], binding=bridge.binding, mode="safe", guard=lambda: None))
    assert not calls


def test_cancelled_bound_call_waits_for_actual_owned_process(bridge, monkeypatch):
    backend = CLIBackend(cli_name="claude", cli_path="unused")
    entered, release = threading.Event(), threading.Event()
    def physical(cmd, prompt, env, flags):
        entered.set()
        assert release.wait(5)
        return "actual exit"
    monkeypatch.setattr(backend, "_run_subprocess", physical)
    async def exercise():
        task = asyncio.create_task(backend.chat_bound([], binding=bridge.binding, mode="safe", guard=lambda: None))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            task.cancel()
            await asyncio.sleep(.05)
            assert not task.done()
            task.cancel()  # Repeated cancellation is not physical terminal evidence.
            await asyncio.sleep(.05)
            assert not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(exercise())


def test_private_cli_does_not_mark_global_continue_session_active(bridge, monkeypatch):
    backend = CLIBackend(cli_name="claude", cli_path="unused")
    monkeypatch.setattr(backend, "_run_subprocess", lambda *a: "actual answer")
    result = asyncio.run(backend.chat_bound([], binding=bridge.binding, mode="plan", guard=lambda: None))
    assert result["content"] == "actual answer"
    assert backend._session_active is False


def test_bound_command_mcp_child_uses_actual_stdio_and_reaches_terminal(bridge, monkeypatch):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    backend = CLIBackend(cli_name="claude", cli_path="not-started")
    def physical(cmd, prompt, environment, flags):
        config = json.loads(cmd[cmd.index("--mcp-config") + 1])["mcpServers"]["bach_worker"]
        # Exercise the declared shim command with the SDK. Claude's expansion
        # itself is a later installed CLI acceptance gate, not proven here.
        env = {key: environment[value[2:-1]] for key, value in config["env"].items()}
        async def use_shim():
            async with stdio_client(StdioServerParameters(command=config["command"], args=config["args"], env=env)) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    assert any(t.name == "task_manage" for t in tools.tools)
                    response = await session.call_tool("task_manage", {"action": "done", "task_id": bridge.binding.task_id, "result": "Konkretes Ergebnis des CLI-Laufs"})
                    assert not response.isError
                    return response.content[0].text
        return asyncio.run(use_shim())  # Both SDK contexts close the actual child.
    monkeypatch.setattr(backend, "_run_subprocess", physical)
    result = asyncio.run(backend.chat_bound([], binding=bridge.binding, mode="safe", guard=lambda: None))
    assert result["content"] == f"Task #{bridge.binding.task_id}: Ergebnis gespeichert, wartet in Review auf getrennte Abnahme."
    assert bridge.binding.completed_task_ids == ()
    assert bridge.binding.reviewed_task_ids == (bridge.binding.task_id,)


def test_unknown_tool_response_revokes_bound_cli_without_returning_lease(bridge, monkeypatch):
    backend = CLIBackend(cli_name="claude", cli_path="unused")
    def physical(cmd, prompt, environment, flags):
        client = WorkerToolClient.from_environment(environment)
        original = client._http
        def lost(path, payload=None):
            result = original(path, payload)
            if path == "/call": raise OSError("lost response after canonical commit")
            return result
        monkeypatch.setattr(client, "_http", lost)
        client.call("task_manage", {"action": "update", "task_id": bridge.binding.task_id, "title": "Actual commit"})
    monkeypatch.setattr(backend, "_run_subprocess", physical)
    with pytest.raises(RuntimeError, match="Privater CLI-Aufruf konnte nicht bestätigt werden"):
        asyncio.run(backend.chat_bound([], binding=bridge.binding, mode="safe", guard=lambda: None))
    assert bridge.binding._client.task_snapshot(bridge.binding.task_id)["title"] == "Actual commit"
    with pytest.raises(Exception): bridge.binding.assert_active()
    assert bridge.binding.return_lease() is False


def test_policy_downgrade_after_tools_list_blocks_actual_cli_mutation(bridge, monkeypatch):
    backend = CLIBackend(cli_name="claude", cli_path="unused")
    permitted = [True]
    def guard():
        if not permitted[0]: raise RuntimeError("private downgrade")
    def physical(cmd, prompt, environment, flags):
        client = WorkerToolClient.from_environment(environment)
        assert client.tools()
        permitted[0] = False
        with pytest.raises(RuntimeError):
            client.call("task_manage", {"action": "done", "task_id": bridge.binding.task_id, "result": "Konkretes Ergebnis des CLI-Laufs"})
        return "downgrade was denied"
    monkeypatch.setattr(backend, "_run_subprocess", physical)
    result = asyncio.run(backend.chat_bound([], binding=bridge.binding, mode="safe", guard=guard))
    assert result["content"] == "downgrade was denied"
    assert not bridge.binding.completed_task_ids


@pytest.mark.parametrize("abort", [False, True])
def test_private_cli_cannot_return_before_parent_and_owned_group_exit(monkeypatch, abort):
    import subprocess
    import time
    import signal
    from system.tests.test_model_backend import _CliProcess
    from hub._services.llm import model_backend
    exited, settling, returned = threading.Event(), threading.Event(), threading.Event()
    process = _CliProcess(stdout=b"actual response", stdin_error=BrokenPipeError() if abort else None)
    process.pid = 4242
    process.poll = lambda: (1 if abort else 0) if exited.is_set() or not abort else None
    def wait(timeout=None):
        if abort and not exited.is_set():
            raise subprocess.TimeoutExpired("owned-child", timeout)
        return 1 if abort else 0
    process.wait = wait
    def signal_group(pid, sig):
        assert pid == process.pid
        settling.set()
        if exited.is_set():
            raise ProcessLookupError()
        raise PermissionError("exit remains unconfirmed")
    calls = []
    monkeypatch.setattr(model_backend.sys, "platform", "darwin")
    monkeypatch.setattr(signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(model_backend.os, "killpg", signal_group, raising=False)
    monkeypatch.setattr(model_backend.subprocess, "Popen", lambda *_a, **kw: calls.append(kw) or process)
    backend = CLIBackend(cli_name="claude", cli_path="not-started")
    result = []
    def invoke():
        result.append(backend._run_subprocess(["not-started"], "task",
                      {"BACH_WORKER_TOOL_GENERATION": "private-generation"}, 0))
        returned.set()
    thread = threading.Thread(target=invoke)
    thread.start()
    try:
        assert settling.wait(3)
        time.sleep(.1)
        assert not returned.is_set()
        assert calls[0]["start_new_session"] is True
    finally:
        exited.set()
        thread.join(timeout=4)
    assert returned.is_set() and not thread.is_alive()
    if abort:
        assert "Broken pipe" in result[0]["error"]


def test_private_windows_cli_is_denied_before_any_process(monkeypatch):
    from hub._services.llm import model_backend
    monkeypatch.setattr(model_backend.sys, "platform", "win32")
    monkeypatch.setattr(model_backend.subprocess, "Popen", lambda *_a, **_kw: pytest.fail("unverified Windows child"))
    backend = CLIBackend(cli_name="claude", cli_path="not-started")
    result = backend._run_subprocess(["not-started"], "task", {"BACH_WORKER_TOOL_GENERATION": "private"}, 0)
    assert "Windows noch nicht abgenommen" in result["error"]
