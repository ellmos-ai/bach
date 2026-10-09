"""Actual loopback relay, isolated authority, no CLI or provider starts."""
import json
import threading
import urllib.error
import urllib.request
import uuid

import pytest

from hub._services.chat.worker_tool_bridge import WorkerToolBridge


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    from system.tests.test_task_lease_service import _create_db, _connect, _insert
    from system.tests.test_task_lease_client_review import T0
    from hub._services import task_lease_client
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    database = tmp_path / "canonical.db"
    _create_db(database)
    conn = _connect(database)
    task_id = _insert(conn, title="Bridge task", assigned_to="BACH")
    conn.close()
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    monkeypatch.setattr(task_lease_client, "get_lead_config", lambda: {"mode": "isolated"})
    binding = WorkerLeaseBinding.acquire(task_lease_client.TaskLeaseClient(db_path=database), task_id,
        worker_id="worker@HOST", host="HOST", generation="a" * 32, is_current=lambda: True,
        stop_event=threading.Event(), clock=lambda: T0)
    with WorkerToolBridge(binding, mode="safe") as relay:
        yield relay


def request(bridge, path, payload=None, token=None):
    settings = bridge.private_environment()
    req = urllib.request.Request(settings["BACH_WORKER_TOOL_URL"] + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + (settings["BACH_WORKER_TOOL_TOKEN"] if token is None else token),
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as result:
        return json.load(result)


def call(bridge, args, previous=None, request_id=None):
    return request(bridge, "/call", {"request_id": request_id or uuid.uuid4().hex,
        "previous_receipt": previous, "name": "task_manage", "arguments": args})


def acknowledge(bridge, result):
    return request(bridge, "/ack", {key: result[key] for key in ("request_id", "receipt_id")})


def test_authentication_and_private_scope(bridge):
    with pytest.raises(urllib.error.HTTPError) as error:
        request(bridge, "/tools", token="wrong")
    assert error.value.code == 401
    tools = request(bridge, "/tools")["tools"]
    assert any(tool["function"]["name"] == "task_manage" for tool in tools)
    settings = bridge.private_environment()
    assert settings["BACH_WORKER_TOOL_TOKEN"] not in str(tools)
    assert bridge.binding._ack.lease_id not in str(tools)


def test_actual_completion_and_explicit_relay_ack(bridge):
    result = call(bridge, {"action": "done", "task_id": bridge.binding.task_id, "result": "Konkretes Ergebnis des gebundenen Tools"})
    assert result["result"] == f"Task #{bridge.binding.task_id}: Ergebnis gespeichert, wartet in Review auf getrennte Abnahme."
    assert result["generation"] == bridge.binding.generation
    assert result["task_id"] == bridge.binding.task_id
    assert result["is_error"] is False
    assert bridge.binding.completed_task_ids == ()
    assert bridge.binding.reviewed_task_ids == (bridge.binding.task_id,)
    assert acknowledge(bridge, result)["acknowledged"] is True


def test_lost_relay_response_cannot_duplicate_open_parent_decomposition(bridge):
    args = {"action": "decompose", "task_id": bridge.binding.task_id,
            "subtasks": [{"title": "One child"}], "close_parent": False}
    call(bridge, args)  # canonical ACK reached the broker; client never acknowledges receipt
    with pytest.raises(urllib.error.HTTPError) as error:
        call(bridge, args)
    assert error.value.code == 409
    assert len(bridge.binding._client.task_candidates()["tasks"]) == 2
    bridge.close()
    with pytest.raises(Exception): bridge.binding.assert_active()
    assert bridge.binding.return_lease() is False


def test_next_call_needs_previous_confirmed_receipt_and_new_request_id(bridge):
    first = call(bridge, {"action": "update", "task_id": bridge.binding.task_id, "title": "Updated"})
    acknowledge(bridge, first)
    for previous, request_id in [(None, None), (first["receipt_id"], first["request_id"])]:
        with pytest.raises(urllib.error.HTTPError) as error:
            call(bridge, {"action": "done", "task_id": bridge.binding.task_id, "result": "Konkretes Ergebnis des gebundenen Tools"}, previous, request_id)
        assert error.value.code == 409
    second = call(bridge, {"action": "done", "task_id": bridge.binding.task_id, "result": "Konkretes Ergebnis des gebundenen Tools"}, first["receipt_id"])
    acknowledge(bridge, second)
    assert bridge.binding.completed_task_ids == ()
    assert bridge.binding.reviewed_task_ids == (bridge.binding.task_id,)


def test_stop_blocks_rpc_before_canonical_mutation(bridge):
    bridge.binding._stop_event.set()
    with pytest.raises(urllib.error.HTTPError) as error:
        call(bridge, {"action": "done", "task_id": bridge.binding.task_id, "result": "Konkretes Ergebnis des gebundenen Tools"})
    assert error.value.code == 403
    assert not bridge.binding.completed_task_ids


def test_remote_caller_cannot_override_private_mode(bridge):
    payload = {"request_id": uuid.uuid4().hex, "previous_receipt": None,
               "name": "execute_command", "arguments": {"command": "not-run"}, "mode": "full"}
    with pytest.raises(urllib.error.HTTPError) as error:
        request(bridge, "/call", payload)
    assert error.value.code == 400


def test_stdio_client_scope_and_sequential_actual_task_calls(bridge):
    from hub._services.chat.worker_tool_client import WorkerToolClient
    client = WorkerToolClient.from_environment(bridge.private_environment())
    assert client.tools()
    first = client.call("task_manage", {"action": "update", "task_id": bridge.binding.task_id,
                                        "title": "Client update"})
    assert first[1] is False
    result, failed = client.call("task_manage", {"action": "done", "task_id": bridge.binding.task_id, "result": "Konkretes Ergebnis des gebundenen Tools"})
    assert not failed and "wartet in Review" in result
    assert bridge.binding.completed_task_ids == ()
    assert bridge.binding.reviewed_task_ids == (bridge.binding.task_id,)


def test_client_lost_response_disables_further_calls_without_retry(bridge, monkeypatch):
    from hub._services.chat.worker_tool_client import WorkerToolClient
    client = WorkerToolClient.from_environment(bridge.private_environment())
    original = client._http
    calls = []
    def lost(path, payload=None):
        calls.append(path)
        response = original(path, payload)
        if path == "/call": raise OSError("Lost response after actual commit")
        return response
    monkeypatch.setattr(client, "_http", lost)
    args = {"action": "decompose", "task_id": bridge.binding.task_id,
            "subtasks": [{"title": "One child"}], "close_parent": False}
    for _ in range(2):
        with pytest.raises(RuntimeError): client.call("task_manage", args)
    assert calls == ["/call"]
    assert len(bridge.binding._client.task_candidates()["tasks"]) == 2


def test_actual_mcp_stdio_subprocess_uses_bound_relay(bridge):
    import asyncio
    import sys
    from pathlib import Path
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    script = Path(__file__).resolve().parents[1] / "hub/_services/chat/worker_tool_mcp.py"
    async def run():
        async with stdio_client(StdioServerParameters(command=sys.executable,
                args=["-X", "utf8", str(script)], env=bridge.private_environment())) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert any(tool.name == "task_manage" for tool in tools.tools)
                answer = await session.call_tool("task_manage", {"action": "done", "task_id": bridge.binding.task_id, "result": "Konkretes Ergebnis des gebundenen Tools"})
                assert not answer.isError
                assert answer.content[0].text == f"Task #{bridge.binding.task_id}: Ergebnis gespeichert, wartet in Review auf getrennte Abnahme."
                assert bridge.binding._ack.lease_id not in str(answer)
                assert bridge.private_environment()["BACH_WORKER_TOOL_TOKEN"] not in str(answer)
    asyncio.run(run())
    assert bridge.binding.completed_task_ids == ()
    assert bridge.binding.reviewed_task_ids == (bridge.binding.task_id,)


def test_close_waits_for_actual_in_flight_tool_terminal_state(bridge, monkeypatch):
    started, finish, closed = threading.Event(), threading.Event(), threading.Event()
    original = bridge._provider.execute
    def blocking(*args):
        started.set()
        assert finish.wait(5)
        return original(*args)
    monkeypatch.setattr(bridge._provider, "execute", blocking)
    results = []
    worker = threading.Thread(target=lambda: results.append(call(bridge,
                              {"action": "detail", "task_id": bridge.binding.task_id})))
    closer = threading.Thread(target=lambda: (bridge.close(), closed.set()))
    worker.start()
    try:
        assert started.wait(2)
        closer.start()
        assert not closed.wait(.1)
    finally:
        finish.set()
        worker.join(5)
        if closer.ident is not None: closer.join(5)
    assert not worker.is_alive() and not closer.is_alive()
    assert closed.is_set() and len(results) == 1
    assert bridge.binding.return_lease() is False  # unacknowledged relay result


def test_client_missing_ack_confirmation_stops_without_reissuing_mutation(bridge, monkeypatch):
    from hub._services.chat.worker_tool_client import WorkerToolClient
    client = WorkerToolClient.from_environment(bridge.private_environment())
    original = client._http
    calls = []
    def missing_ack(path, payload=None):
        calls.append(path)
        result = original(path, payload)
        if path == "/ack": raise OSError("Acknowledgement response lost")
        return result
    monkeypatch.setattr(client, "_http", missing_ack)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            client.call("task_manage", {"action": "update", "task_id": bridge.binding.task_id, "title": "Once"})
    assert calls == ["/call", "/ack"]
    assert bridge.binding._client.task_snapshot(bridge.binding.task_id)["title"] == "Once"


@pytest.mark.parametrize("changed", ["generation", "task_id", "request_id", "receipt_id", "is_error"])
def test_client_rejects_uncorrelated_actual_result_without_ack_or_retry(bridge, monkeypatch, changed):
    from hub._services.chat.worker_tool_client import WorkerToolClient
    client = WorkerToolClient.from_environment(bridge.private_environment())
    original = client._http
    calls = []
    def corrupt(path, payload=None):
        calls.append(path)
        result = original(path, payload)
        result[changed] = "invalid"
        return result
    monkeypatch.setattr(client, "_http", corrupt)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            client.call("task_manage", {"action": "update", "task_id": bridge.binding.task_id, "title": "Once"})
    assert calls == ["/call"]
    assert bridge.binding._client.task_snapshot(bridge.binding.task_id)["title"] == "Once"


def test_policy_downgrade_refuses_tool_before_actual_mutation(bridge, monkeypatch):
    def denied(): raise ValueError("PRIVATE policy details")
    monkeypatch.setattr(bridge._provider, "_guard", denied)
    with pytest.raises(urllib.error.HTTPError) as error:
        call(bridge, {"action": "done", "task_id": bridge.binding.task_id, "result": "Konkretes Ergebnis des gebundenen Tools"})
    assert error.value.code == 403
    assert not bridge.binding.completed_task_ids


@pytest.mark.parametrize("url", ["https://127.0.0.1:1234", "http://localhost:1234", "http://example.com:1234",
                                 "http://user:password@127.0.0.1:1234", "http://127.0.0.1:1234/other",
                                 "http://127.0.0.1:1234?key=secret", "http://127.0.0.1:1234#fragment"])
def test_client_only_accepts_explicit_private_loopback_endpoint(bridge, url):
    from hub._services.chat.worker_tool_client import WorkerToolClient
    settings = bridge.private_environment() | {"BACH_WORKER_TOOL_URL": url}
    with pytest.raises(ValueError): WorkerToolClient.from_environment(settings)
