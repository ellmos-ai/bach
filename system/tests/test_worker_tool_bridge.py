"""Actual loopback relay, isolated authority, no CLI or provider starts."""
from datetime import datetime, timezone
import json
import threading
import urllib.error
import urllib.request
import uuid

import pytest

from hub._services.chat.worker_tool_bridge import WorkerToolBridge


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    from hub._services import task_lease_client
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding

    from system.tests.test_task_lease_service import _connect, _create_db, _insert
    database = tmp_path / "canonical.db"
    _create_db(database)
    conn = _connect(database)
    task_id = _insert(conn, title="Bridge task", assigned_to="BACH")
    conn.close()
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    monkeypatch.setattr(task_lease_client, "get_lead_config", lambda: {"mode": "isolated"})
    binding = WorkerLeaseBinding.acquire(task_lease_client.TaskLeaseClient(db_path=database), task_id,
        worker_id="worker@HOST", host="HOST", generation="a" * 32, is_current=lambda: True,
        stop_event=threading.Event(), clock=lambda: datetime.now(timezone.utc))
    with WorkerToolBridge(binding, mode="safe") as relay:
        yield relay


_READ_ONLY_PROFILE_TOOLS = ("read_file", "search_text", "task_manage")


def _make_fenced_readonly_worker(
    tmp_path, monkeypatch, *, backend="openrouter", model="openrouter/free",
    required_model="", profile_tools=_READ_ONLY_PROFILE_TOOLS, model_fallbacks=None,
):
    from hub._services import task_lease_client
    from hub._services.chat import chat_runtime, telegram_chat, slots_config
    from hub._services.chat.chat_runtime import ChatRuntime, ChatSession
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding

    from system.tests.test_task_lease_service import _connect, _create_db, _insert

    database = tmp_path / "fenced-readonly-worker.db"
    _create_db(database)
    conn = _connect(database)
    conn.execute("ALTER TABLE tasks ADD COLUMN assigned_slot TEXT")
    conn.execute("ALTER TABLE tasks ADD COLUMN required_model TEXT")
    task_id = _insert(conn, title="BACH-owned read-only worker fixture", assigned_to="BACH")
    conn.execute(
        "UPDATE tasks SET assigned_slot = ?, required_model = ? WHERE id = ?",
        ("", required_model, task_id),
    )
    conn.commit()
    conn.close()

    profile_id = "readonly-" + backend.replace("-", "_")
    profile = {
        "id": profile_id,
        "name": "Isolated read-only worker",
        "backend": backend,
        "model": model,
        "status": "running",
        "enabled": True,
        "allow_tools": True,
        "allowed_tools": list(profile_tools),
        "task_prompt": "fixture profile only",
        "expires_at": None,
    }
    if model_fallbacks is not None:
        profile["model_fallbacks"] = model_fallbacks
    slots_path = tmp_path / "slots.json"
    config = slots_config._fresh_slots_config()
    config["dynamic_workers"] = [profile]
    slots_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(
        slots_config, "_resolve_path",
        lambda path=None: __import__("pathlib").Path(path).expanduser() if path else slots_path,
    )

    live_reads = []
    original_slot_reader = telegram_chat._execution_worker_slot
    def counted_slot_read(worker_id):
        current = original_slot_reader(worker_id)
        live_reads.append(worker_id)
        return current
    monkeypatch.setattr(telegram_chat, "_execution_worker_slot", counted_slot_read)
    reader = telegram_chat._execution_slot_reader(profile)
    session = ChatSession()
    session.chat_id = profile_id
    session.worker_slot_reader = reader
    session.require_task_binding = True
    assert ChatRuntime._refresh_worker_tools(session) is None
    assert session.allowed_tools == list(profile_tools)
    admitted_slot = reader()
    assert live_reads == [profile_id, profile_id]
    assert admitted_slot["backend"] == backend and admitted_slot["model"] == model
    assert admitted_slot.get("model_fallbacks", []) == (model_fallbacks or [])

    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    monkeypatch.setattr(task_lease_client, "get_lead_config", lambda: {"mode": "isolated"})
    binding = WorkerLeaseBinding.acquire_next(
        task_lease_client.TaskLeaseClient(db_path=database), admitted_slot,
        worker_id=f"{profile_id}@HOST", host="HOST", generation="b" * 32,
        is_current=lambda: True, stop_event=threading.Event(),
        clock=lambda: datetime.now(timezone.utc),
    )
    assert binding._snapshot["assigned_to"] == "BACH"
    assert binding._snapshot.get("assigned_slot") == ""
    assert (binding._snapshot.get("required_model") or "") == required_model
    binding.assert_active()
    session.worker_task_binding = binding
    from hub._services.llm.model_backend import OllamaBackend, OpenRouterBackend
    if backend == "openrouter":
        selected_backend = OpenRouterBackend(api_key="fixture-only", default_model=model)
    else:
        endpoint = "https://ollama.example.invalid" if backend == "ollama-cloud" else "http://127.0.0.1:11434"
        selected_backend = OllamaBackend(base_url=endpoint, default_model=model, num_ctx=512)
    def live_runtime_guard():
        reads_before = len(live_reads)
        problem = ChatRuntime._worker_backend_gate(session, selected_backend, model)
        if len(live_reads) != reads_before + 2:
            raise RuntimeError("Live-Workerprofil wurde nicht an beiden Laufzeitgrenzen gelesen")
        if problem is not None:
            raise RuntimeError("Gebundene Workerfreigabe ist nicht mehr aktuell")
    monkeypatch.setattr(
        chat_runtime, "_ALLOWED_FS_ROOTS",
        (*chat_runtime._ALLOWED_FS_ROOTS, tmp_path.resolve()),
    )
    return binding, session, profile, slots_path, live_runtime_guard


@pytest.fixture
def fenced_readonly_bridge(tmp_path, monkeypatch):
    binding, session, _profile, _slots_path, live_guard = _make_fenced_readonly_worker(tmp_path, monkeypatch)
    with WorkerToolBridge(
        binding, mode="safe", guard=live_guard, allowed_tools=session.allowed_tools,
    ) as relay:
        yield relay

def _install_fake_read_evidence_formatter(monkeypatch):
    import sys
    from types import ModuleType

    module = ModuleType("ellmos_chat.read_evidence")
    module.READ_EVIDENCE_SCHEMA = "ellmos.read-evidence.v1"
    module.MAX_LINES = 200
    module.MAX_CHARS = 4000

    def format_read_evidence(
        text, *, start_line, source_eof, start_char_offset=0, max_lines=200,
        max_chars=4000, source_complete=False, source_sha256=None,
    ):
        values = text.splitlines()
        if text == "":
            values = []
        emitted = []
        remaining = max_chars
        for index, value in enumerate(values[:max_lines]):
            offset = start_char_offset if index == 0 else 0
            piece = value[:remaining]
            emitted.append({
                "line": start_line + index, "char_offset": offset,
                "text": piece, "line_complete": source_eof,
            })
            remaining -= len(piece)
        payload = {
            "schema": module.READ_EVIDENCE_SCHEMA,
            "start_line": emitted[0]["line"] if emitted else None,
            "end_line": emitted[-1]["line"] if emitted else None,
            "lines": emitted,
            "eof": source_eof,
            "truncated": not source_eof,
            "truncation_reason": None if source_eof else "source_chunk",
            "next_cursor": None if source_eof else {
                "line": (emitted[-1]["line"] if emitted else start_line),
                "char_offset": (emitted[-1]["char_offset"] + len(emitted[-1]["text"]) if emitted else start_char_offset),
            },
            "source_complete": False,
            "source_sha256": None,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    module.format_read_evidence = format_read_evidence
    monkeypatch.setitem(sys.modules, "ellmos_chat.read_evidence", module)


def call_tool(bridge, name, arguments, previous=None):
    return request(bridge, "/call", {
        "request_id": uuid.uuid4().hex,
        "previous_receipt": previous,
        "name": name,
        "arguments": arguments,
    })


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


def test_bound_readonly_worker_gets_separate_v1_schema_without_global_mutation(
    fenced_readonly_bridge,
):
    import copy

    from hub._services.chat import bach_tools

    global_tool = next(
        tool for tool in bach_tools.TOOLS_SAFE if tool["function"]["name"] == "read_file"
    )
    before = copy.deepcopy(global_tool)
    tools = request(fenced_readonly_bridge, "/tools")["tools"]
    read_file = next(tool for tool in tools if tool["function"]["name"] == "read_file")
    schema = read_file["function"]["parameters"]
    assert schema["required"] == ["path", "output_format"]
    assert schema["properties"]["output_format"]["enum"] == ["ellmos.read-evidence.v1"]
    assert schema["additionalProperties"] is False
    assert {"read_file", "search_text", "task_manage"} <= {tool["function"]["name"] for tool in tools}
    assert "start_task_worktree" not in {tool["function"]["name"] for tool in tools}
    assert global_tool == before


@pytest.mark.parametrize(("backend", "model", "required_model", "fallbacks"), [
    ("openrouter", "openrouter/free", "", [{"backend": "ollama", "model": "qwen3.5:4b"}]),
    ("ollama-cloud", "glm-5.3:cloud", "glm-5.3:cloud", None),
    ("ollama", "qwen3.5:4b", "", [{"backend": "openrouter", "model": "openrouter/free"}]),
])
def test_read_evidence_profile_is_provider_neutral_for_bach_tasks(
    tmp_path, monkeypatch, backend, model, required_model, fallbacks,
):
    binding, session, _profile, _slots_path, live_guard = _make_fenced_readonly_worker(
        tmp_path, monkeypatch, backend=backend, model=model,
        required_model=required_model, model_fallbacks=fallbacks,
    )
    with WorkerToolBridge(binding, mode="safe", guard=live_guard,
                           allowed_tools=session.allowed_tools) as relay:
        tools = request(relay, "/tools")["tools"]
        read_file = next(tool for tool in tools if tool["function"]["name"] == "read_file")
        schema = read_file["function"]["parameters"]
        assert schema["required"] == ["path", "output_format"]
        assert schema["properties"]["output_format"]["enum"] == ["ellmos.read-evidence.v1"]
        assert binding._snapshot["assigned_to"] == "BACH"
        assert binding._snapshot.get("assigned_slot") == ""
        assert (binding._snapshot.get("required_model") or "") == required_model


def test_other_live_worker_allowlist_keeps_legacy_read_file_schema(tmp_path, monkeypatch):
    allowed = ("read_file", "search_text")
    binding, session, _profile, _slots_path, live_guard = _make_fenced_readonly_worker(
        tmp_path, monkeypatch, profile_tools=allowed,
    )
    with WorkerToolBridge(binding, mode="safe", guard=live_guard,
                           allowed_tools=session.allowed_tools) as relay:
        tools = request(relay, "/tools")["tools"]
        read_file = next(tool for tool in tools if tool["function"]["name"] == "read_file")
        properties = read_file["function"]["parameters"]["properties"]
        assert "line_numbers" in properties
        assert "output_format" not in properties

def test_missing_formatter_returns_unavailable_before_path_or_file_io(
    fenced_readonly_bridge, tmp_path, monkeypatch,
):
    import builtins

    from hub._services.chat import bach_tools

    path = tmp_path / "must-not-open.txt"
    path.write_text("private fixture", encoding="utf-8")
    open_calls = []
    path_checks = []
    def unexpected_open(*args, **kwargs):
        open_calls.append(args)
        raise AssertionError("missing formatter must fail before file I/O")
    def unexpected_path_check(*args, **kwargs):
        path_checks.append(args)
        raise AssertionError("missing formatter must fail before path authorization")
    monkeypatch.setattr(bach_tools, "_read_evidence_formatter", lambda: None)
    monkeypatch.setattr(bach_tools, "_fs_root_allowed", unexpected_path_check)
    monkeypatch.setattr(builtins, "open", unexpected_open)
    result = call_tool(fenced_readonly_bridge, "read_file", {
        "path": str(path), "output_format": "ellmos.read-evidence.v1",
    })
    assert json.loads(result["result"]) == {
        "schema": "bach.read-evidence-capability.v1",
        "requested_schema": "ellmos.read-evidence.v1",
        "available": False,
        "reason_code": "formatter_capability_unverified",
    }
    assert open_calls == [] and path_checks == []
    acknowledge(fenced_readonly_bridge, result)


@pytest.mark.parametrize("formatter_mode", ["fake", "installed"])
def test_versioned_read_result_survives_bridge_and_mcp(formatter_mode, fenced_readonly_bridge,
                                                               tmp_path, monkeypatch):
    from hub._services.chat import bach_tools

    if formatter_mode == "fake":
        _install_fake_read_evidence_formatter(monkeypatch)
    elif bach_tools._read_evidence_formatter() is None:
        pytest.skip("Exact upstream formatter is injected only in isolated candidate conformance QA")
    path = tmp_path / "read-evidence.txt"
    base = {"path": str(path), "output_format": "ellmos.read-evidence.v1"}
    if formatter_mode == "installed":
        path.write_text("αβγ\r\nsecond line\r\nthird\r\n", encoding="utf-8", newline="")
    else:
        path.write_text("BACH v1 content\n", encoding="utf-8")
    tools = request(fenced_readonly_bridge, "/tools")["tools"]
    tool = next(tool for tool in tools if tool["function"]["name"] == "read_file")
    assert "output_format" in tool["function"]["parameters"]["required"]

    # The MCP subprocess uses the ordinary bridge/client string transport; the
    # formatter runs in the bound provider process and its JSON is not reparsed.
    import asyncio
    import sys
    from pathlib import Path as FilePath
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    script = FilePath(__file__).resolve().parents[1] / "hub/_services/chat/worker_tool_mcp.py"
    async def run():
        async with stdio_client(StdioServerParameters(
            command=sys.executable, args=["-X", "utf8", str(script)],
            env=fenced_readonly_bridge.private_environment(),
        )) as streams, ClientSession(*streams) as session:
                await session.initialize()
                mcp_tools = await session.list_tools()
                assert "read_file" in {item.name for item in mcp_tools.tools}
                if formatter_mode == "installed":
                    pages = []
                    for cursor in (
                        {"start_line": 1, "start_char_offset": 1, "max_lines": 1, "max_chars": 1},
                        {"start_line": 1, "start_char_offset": 2, "max_lines": 1, "max_chars": 20},
                        {"start_line": 2, "start_char_offset": 0, "max_lines": 1, "max_chars": 20},
                        {"start_line": 3, "start_char_offset": 0, "max_lines": 1, "max_chars": 20},
                    ):
                        answer = await session.call_tool("read_file", base | cursor)
                        assert not answer.isError
                        output = answer.content[0].text
                        assert len(output) <= 4000
                        payload = json.loads(output)
                        assert payload["schema"] == "ellmos.read-evidence.v1"
                        assert payload["source_complete"] is False
                        assert payload["source_sha256"] is None
                        pages.append(payload)
                        assert fenced_readonly_bridge.private_environment()["BACH_WORKER_TOOL_TOKEN"] not in output
                    assert pages[0]["lines"] == [{
                        "line": 1, "char_offset": 1, "text": "β", "line_complete": False,
                    }]
                    assert pages[0]["truncation_reason"] == "max_chars"
                    assert pages[0]["next_cursor"] == {"line": 1, "char_offset": 2}
                    assert pages[1]["lines"][0]["text"] == "γ"
                    assert pages[1]["truncation_reason"] == "max_lines"
                    assert pages[1]["next_cursor"] == {"line": 2, "char_offset": 0}
                    assert pages[2]["lines"][0]["text"] == "second line"
                    assert pages[2]["next_cursor"] == {"line": 3, "char_offset": 0}
                    assert pages[3]["lines"] == [{
                        "line": 3, "char_offset": 0, "text": "third", "line_complete": True,
                    }]
                    assert pages[3]["eof"] is True and pages[3]["next_cursor"] is None
                    large_path = tmp_path / "read-evidence-budget.txt"
                    large_path.write_text(("é" * 1500 + "\r\n") * 4, encoding="utf-8", newline="")
                    large_answer = await session.call_tool("read_file", {
                        "path": str(large_path), "output_format": "ellmos.read-evidence.v1",
                    })
                    assert not large_answer.isError
                    large_output = large_answer.content[0].text
                    assert len(large_output) <= 4000
                    large_payload = json.loads(large_output)
                    assert large_payload["truncated"] is True
                    assert large_payload["next_cursor"] is not None
                    assert sum(len(row["text"]) for row in large_payload["lines"]) <= 4000
                    cursor = large_payload["next_cursor"]
                    continuation = await session.call_tool("read_file", {
                        "path": str(large_path), "output_format": "ellmos.read-evidence.v1",
                        "start_line": cursor["line"], "start_char_offset": cursor["char_offset"],
                    })
                    assert not continuation.isError
                    next_payload = json.loads(continuation.content[0].text)
                    assert next_payload["lines"][0]["line"] == cursor["line"]
                    assert next_payload["lines"][0]["char_offset"] == cursor["char_offset"]
                else:
                    answer = await session.call_tool("read_file", base | {
                        "start_line": 1, "start_char_offset": 0,
                    })
                    assert not answer.isError
                    output = answer.content[0].text
                    payload = json.loads(output)
                    assert payload["schema"] == "ellmos.read-evidence.v1"
                    assert payload["source_complete"] is False
                    assert payload["source_sha256"] is None
                    assert payload["lines"][0]["text"] == "BACH v1 content"
                    assert fenced_readonly_bridge.private_environment()["BACH_WORKER_TOOL_TOKEN"] not in output
    asyncio.run(run())
    events = fenced_readonly_bridge.binding._client.tool_trace_events(
        fenced_readonly_bridge.binding.task_id,
    )["events"]
    assert [event["phase"] for event in events[-3:]] == ["started", "returned", "acknowledged"]
    assert "BACH v1 content" not in json.dumps(events)


def test_versioned_read_requires_schema_before_file_io(fenced_readonly_bridge, tmp_path, monkeypatch):
    import builtins

    from hub._services.chat import bach_tools

    open_calls = []
    def unexpected_open(*args, **kwargs):
        open_calls.append(args)
        raise AssertionError("reviewer without the required schema must not open a file")
    monkeypatch.setattr(bach_tools, "_fs_root_allowed", lambda *_: pytest.fail("path check should not run"))
    monkeypatch.setattr(builtins, "open", unexpected_open)
    result = call_tool(fenced_readonly_bridge, "read_file", {"path": str(tmp_path / "no-open.txt")})
    payload = json.loads(result["result"])
    assert payload["reason_code"] == "versioned_format_required"
    assert open_calls == []
    acknowledge(fenced_readonly_bridge, result)


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
    assert bridge.binding.tool_dispatch_count == 1
    with pytest.raises(urllib.error.HTTPError) as error:
        call(bridge, args)
    assert error.value.code == 409
    assert len(bridge.binding._client.task_candidates()["tasks"]) == 2
    bridge.close()
    assert bridge.binding.tool_dispatch_count == 1  # unknown receipt cannot reset proof
    with pytest.raises(Exception): bridge.binding.assert_active()
    assert bridge.binding.return_lease() is False


def test_next_call_needs_previous_confirmed_receipt_and_new_request_id(bridge):
    from hub._services.chat.worker_tool_trace import TraceIdentity
    from hub._services.task_lease_client import LeaseProtocolError

    task_id = bridge.binding.task_id
    first = call(bridge, {"action": "update", "task_id": task_id, "title": "Updated"})
    acknowledge(bridge, first)
    events = bridge.binding._client.tool_trace_events(task_id)["events"]
    first_events = [event for event in events if event["request_id"] == first["request_id"]]
    assert [event["phase"] for event in first_events] == ["started", "returned", "acknowledged"]
    first_version = first_events[0]["task_version"]
    assert all(event["task_version"] == first_version for event in first_events)
    updated_version = bridge.binding._ack.task_version
    assert updated_version == bridge.binding.task_snapshot()["task_version"]
    assert updated_version != first_version

    stale_identity = TraceIdentity(
        task_id=task_id, fence=bridge.binding._ack.fence,
        worker_id=bridge.binding._ack.worker_id, generation=bridge.binding._generation,
        task_version=first_version, request_id=uuid.uuid4().hex,
        source="cli-relay", tool_name="task_manage",
    )
    with pytest.raises(LeaseProtocolError):
        bridge.binding._client.tool_trace_start(
            stale_identity, lease_id=bridge.binding._ack.lease_id,
            arguments_sha256="a" * 64,
        )
    assert len(bridge.binding._client.tool_trace_events(task_id)["events"]) == len(events)

    for previous, request_id in [(None, None), (first["receipt_id"], first["request_id"])]:
        with pytest.raises(urllib.error.HTTPError) as error:
            call(bridge, {"action": "done", "task_id": bridge.binding.task_id, "result": "Konkretes Ergebnis des gebundenen Tools"}, previous, request_id)
        assert error.value.code == 409
    second = call(bridge, {"action": "done", "task_id": task_id, "result": "Konkretes Ergebnis des gebundenen Tools"}, first["receipt_id"])
    acknowledge(bridge, second)
    events = bridge.binding._client.tool_trace_events(task_id)["events"]
    second_events = [event for event in events if event["request_id"] == second["request_id"]]
    assert [event["phase"] for event in second_events] == ["started", "returned", "acknowledged"]
    assert all(event["task_version"] == updated_version for event in second_events)
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
