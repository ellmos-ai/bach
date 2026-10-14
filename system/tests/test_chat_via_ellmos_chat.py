# -*- coding: utf-8 -*-
"""Wave 2 of the BACH-GUI module cut (D-20260830-002): the chat runtime lives in
``ellmos-chat``; BACH injects its tools and its snapshot transcripts and keeps
the surface telegram_chat.py, the tray and the GUI ``/chat`` page rely on."""
from __future__ import annotations

import asyncio
import copy
import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

import pytest

ellmos_chat = pytest.importorskip("ellmos_chat")
from hub._services.chat import bach_tools, chat_runtime  # noqa: E402
from hub._services.chat.chat_runtime import ChatRuntime  # noqa: E402
from hub._services.chat.session_store import SQLiteChatSessionStore  # noqa: E402

CHAT_RUNTIME_SRC = (
    SYSTEM_ROOT / "hub" / "_services" / "chat" / "chat_runtime.py"
).read_text(encoding="utf-8")


class _Backend:
    manages_own_tools = False

    def __init__(self, script=None, on_chat=None):
        self.script = list(script or [])
        self.on_chat = on_chat
        self.seen_tools: list[list[str]] = []
        self.seen_tool_schemas: list[list[dict]] = []
        self.seen_models: list[str | None] = []

    def get_default_model(self):
        return "test-model"

    async def chat(self, messages, tools=None, think=True, model=None):
        self.seen_tools.append([t["function"]["name"] for t in (tools or [])])
        self.seen_tool_schemas.append(copy.deepcopy(tools or []))
        self.seen_models.append(model)
        if self.on_chat is not None:
            self.on_chat(tools or [], model)
        if self.script:
            response = self.script.pop(0)
            if isinstance(response, BaseException):
                raise response
            return response
        return {"content": "Antwort"}

    def tool_response_message(self, content, tool_call_id=""):
        return {"role": "tool", "content": content}


_READ_ONLY_REVIEW_TOOLS = ["read_file", "search_text", "task_manage"]


def _live_bound_worker(runtime, chat_id, *, allowed_tools=None, required_model=""):
    from datetime import datetime, timedelta, timezone
    from threading import Event
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    from hub._services.task_lease_client import LeaseAck, ToolTraceStartAck

    class _TraceClient:
        def __init__(self):
            self.started = []
            self.phases = []

        def tool_trace_start(self, identity, **kwargs):
            self.started.append(identity)
            return ToolTraceStartAck(
                schema="bach.worker-tool-trace-start.v1", accepted=True,
                event_id=len(self.started), task_id=identity.task_id,
                request_id=identity.request_id, phase="started",
                completion_token="test-only-completion-token",
            )

        def tool_trace_phase(self, identity, phase, **kwargs):
            self.phases.append((identity.tool_name, phase))
            return {"accepted": True}

    class _TestBinding(WorkerLeaseBinding):
        @property
        def completed_task_ids(self):
            return ()

    now = datetime.now(timezone.utc)
    task_id = 42001
    version = "a" * 64
    generation = "test-generation-2197"
    snapshot = {
        "id": task_id, "task_id": task_id, "assigned_to": "BACH",
        "assigned_slot": "", "required_model": required_model,
        "task_version": version,
    }
    ack = LeaseAck(
        task_id=task_id, lease_id="00000000-0000-4000-8000-000000000001", fence=1,
        worker_id="readonly-reviewer@ASUS-GEI", host="ASUS-GEI",
        issued_at=now.isoformat(), expires_at=(now + timedelta(minutes=10)).isoformat(),
        ttl_profile="M", server_now=now.isoformat(), local_receive_time=now,
        task_version=version, result_generation=generation,
    )
    trace_client = _TraceClient()
    binding = _TestBinding(
        trace_client, snapshot, ack, generation=generation,
        is_current=lambda: True, stop_event=Event(), clock=lambda: now,
    )
    profile = {
        "id": chat_id, "enabled": True, "allow_tools": True,
        "allowed_tools": list(allowed_tools) if allowed_tools is not None else list(_READ_ONLY_REVIEW_TOOLS),
        "skill_refs": [], "backend": "openrouter", "model": "test-model",
        "model_fallbacks": [],
    }
    session = runtime.get_session(chat_id)
    session.worker_task_binding = binding
    session.require_task_binding = True
    session.worker_slot_reader = lambda: dict(profile)
    session.custom_system_prompt = "isolated runtime caller fixture"
    runtime._get_bach_context = lambda *args: ""
    return binding, profile, trace_client, session


@pytest.fixture
def snapshot_db(tmp_path):
    db_path = tmp_path / "bach.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE session_snapshots ("
            "id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, snapshot_type TEXT NOT NULL,"
            " snapshot_data TEXT, name TEXT, created_at TEXT)"
        )
    return db_path


# ---------------------------------------------------------------------------
# Guard: no tool implementations left in the seam
# ---------------------------------------------------------------------------


class TestSeamIsThin:
    def test_chat_runtime_defines_no_tools_and_no_exec_tool(self):
        """The tools moved to bach_tools.py; the seam only wires them in."""
        for forbidden in ("def exec_tool", "def run_shell", "TOOLS_SAFE = ", "def _tool("):
            assert forbidden not in CHAT_RUNTIME_SRC, forbidden
        assert "BachToolProvider(bach_app" in CHAT_RUNTIME_SRC

    def test_runtime_comes_from_the_module(self):
        assert issubclass(ChatRuntime, ellmos_chat.ChatRuntime)
        assert ChatRuntime is not ellmos_chat.ChatRuntime

    def test_import_path_and_db_constant_stay_stable(self):
        """telegram_chat.py imports both names from here (lines 77 and 1427)."""
        assert chat_runtime.RUNTIME_BACH_DB is bach_tools.RUNTIME_BACH_DB


# ---------------------------------------------------------------------------
# Tool provider injection
# ---------------------------------------------------------------------------


class TestToolProvider:
    def test_provider_satisfies_the_module_protocol(self):
        assert isinstance(bach_tools.BachToolProvider(), ellmos_chat.ToolProvider)

    def test_unbound_provider_keeps_pr372_legacy_read_file_schema(self):
        import copy

        from hub._services.chat import bach_tools

        original = copy.deepcopy(next(
            tool for tool in bach_tools.TOOLS_SAFE if tool["function"]["name"] == "read_file"
        ))
        provider_tool = next(
            tool for tool in bach_tools.BachToolProvider().get_tools("safe")
            if tool["function"]["name"] == "read_file"
        )
        properties = provider_tool["function"]["parameters"]["properties"]
        assert provider_tool == original
        assert "line_numbers" in properties
        assert "output_format" not in properties
        assert next(
            tool for tool in bach_tools.TOOLS_SAFE if tool["function"]["name"] == "read_file"
        ) == original

    def test_exact_read_only_allowlist_without_fenced_binding_keeps_legacy_schema(self):
        from hub._services.chat import bach_tools

        provider = bach_tools.BachToolProvider(
            worker_task_binding=None,
            allowed_tools={"read_file", "search_text", "task_manage"},
        )
        read_file = next(
            tool for tool in provider.get_tools("safe")
            if tool["function"]["name"] == "read_file"
        )
        properties = read_file["function"]["parameters"]["properties"]
        assert "line_numbers" in properties
        assert "output_format" not in properties

    def test_safe_and_full_surfaces_are_bachs_own(self):
        provider = bach_tools.BachToolProvider()
        safe = {t["function"]["name"] for t in provider.get_tools("safe")}
        full = {t["function"]["name"] for t in provider.get_tools(ellmos_chat.Mode.FULL)}

        assert "bach_command" in safe
        assert {"edit_file", "create_directory", "recycle"} <= safe
        assert "execute_command" not in safe
        assert {"execute_command", "write_file"} <= full
        # A tool only the module knows must not leak into BACH's surface.
        assert "read_file_write" not in safe | full

    def test_full_only_tools_are_refused_in_safe_mode(self):
        provider = bach_tools.BachToolProvider()
        assert "Full-Modus" in provider.execute("execute_command", {"command": "echo x"}, "safe")
        assert "Full-Modus" in provider.execute("write_file", {"path": "x", "content": "y"}, "safe")

    def test_bach_command_reaches_the_injected_app(self):
        calls = []

        class _App:
            def execute(self, handler, operation, args):
                calls.append((handler, operation, args))
                return True, "42 Tasks"

        provider = bach_tools.BachToolProvider(_App())
        result = provider.execute(
            "bach_command", {"handler": "kalender", "operation": "today", "args": []}, "safe"
        )
        assert result == "42 Tasks"
        # The handler alias table stays BACH's.
        assert calls == [("calendar", "today", [])]

    def test_bach_command_without_an_app_is_reported_not_raised(self):
        assert bach_tools.BachToolProvider().execute("bach_command", {"handler": "status"}, "safe") == (
            "BACH nicht verfügbar"
        )

    @pytest.mark.asyncio
    async def test_runtime_dispatches_tool_calls_through_the_provider(self):
        backend = _Backend([
            {"tool_calls": [{"function": {"name": "get_datetime", "arguments": {}}}]},
            {"content": "fertig"},
        ])
        runtime = ChatRuntime(backend)

        assert await runtime.process("wie spät?", "c1") == "fertig"
        assert "get_datetime" in backend.seen_tools[0]
        assert "bach_command" in backend.seen_tools[0]
        legacy_read_file = next(
            tool for tool in backend.seen_tool_schemas[0]
            if tool["function"]["name"] == "read_file"
        )
        properties = legacy_read_file["function"]["parameters"]["properties"]
        assert "line_numbers" in properties
        assert "output_format" not in properties

    @pytest.mark.asyncio
    async def test_full_mode_session_is_offered_the_full_surface(self):
        """String modes come from the Control API; the Safe surface must not be served."""
        backend = _Backend()
        runtime = ChatRuntime(backend)
        runtime.get_session("c1").mode = "full"

        await runtime.process("los", "c1")
        assert "execute_command" in backend.seen_tools[0]


    @pytest.mark.asyncio
    @pytest.mark.parametrize("required_model", ["", "test-model"])
    async def test_bound_readonly_schema_is_rebuilt_for_each_fallback_request(
        self, monkeypatch, required_model,
    ):
        httpx = pytest.importorskip("httpx")
        from hub._services.chat import model_sockets

        profile_box = {}
        def primary_attempt(_tools, _model):
            profile_box["profile"]["allowed_tools"] = ["search_text", "task_manage"]

        primary = _Backend([httpx.ConnectError("test-only pre-answer failure")], on_chat=primary_attempt)
        fallback = _Backend([{"content": "fallback answer"}])
        runtime = ChatRuntime(primary)
        binding, profile, _, session = _live_bound_worker(
            runtime, "review-worker", required_model=required_model,
        )
        profile_box["profile"] = profile
        runtime._native_model_fallback_route = lambda _session, _backend, _model: {
            "targets": [
                {"backend": "openrouter", "model": "test-model"},
                {"backend": "openrouter", "model": "test-model"},
            ],
            "index": 0,
        }
        monkeypatch.setattr(model_sockets, "resolve_fallback_backend", lambda _target: fallback)

        answer = await runtime.process("review", "review-worker", backend=primary, model="test-model")

        assert answer == "fallback answer"
        assert primary.seen_models == ["test-model"]
        assert fallback.seen_models == ["test-model"]
        first_read = next(t for t in primary.seen_tool_schemas[0] if t["function"]["name"] == "read_file")
        first_props = first_read["function"]["parameters"]["properties"]
        assert first_props["output_format"]["enum"] == ["ellmos.read-evidence.v1"]
        assert "line_numbers" not in first_props
        assert all(t["function"]["name"] != "read_file" for t in fallback.seen_tool_schemas[0])
        assert session.worker_task_binding is binding

    @pytest.mark.asyncio
    async def test_runtime_dispatch_uses_same_binding_and_refreshes_schema_after_read(
        self, monkeypatch, tmp_path,
    ):
        import json

        source = tmp_path / "review.txt"
        source.write_text("alpha\nbeta\n", encoding="utf-8")
        backend = _Backend([
            {"tool_calls": [{"function": {"name": "read_file", "arguments": {
                "path": str(source), "output_format": "ellmos.read-evidence.v1",
            }}}]},
            {"content": "done"},
        ])
        runtime = ChatRuntime(backend)
        binding, profile, trace_client, _session = _live_bound_worker(runtime, "review-worker")
        fake_formatter = lambda text, **_kwargs: json.dumps({"schema": "ellmos.read-evidence.v1", "text": text})
        monkeypatch.setattr(bach_tools, "_read_evidence_formatter", lambda: fake_formatter)
        monkeypatch.setattr(
            bach_tools, "_format_read_evidence_within_budget",
            lambda _formatter, text, **_kwargs: json.dumps({"schema": "ellmos.read-evidence.v1", "text": text}),
        )
        original_exec_tool = chat_runtime.exec_tool
        dispatch_context = []
        def recording_exec_tool(name, args, mode, **kwargs):
            dispatch_context.append((name, kwargs.get("worker_task_binding"), kwargs.get("allowed_tools")))
            result = original_exec_tool(name, args, mode, **kwargs)
            if name == "read_file":
                profile["allowed_tools"] = ["search_text", "task_manage"]
            return result
        monkeypatch.setattr(chat_runtime, "exec_tool", recording_exec_tool)

        answer = await runtime.process("read the source", "review-worker", backend=backend, model="test-model")

        assert answer == "done"
        assert len(dispatch_context) == 1
        name, dispatched_binding, dispatched_tools = dispatch_context[0]
        assert name == "read_file"
        assert dispatched_binding is binding
        assert set(dispatched_tools) == set(_READ_ONLY_REVIEW_TOOLS)
        assert [(identity.tool_name, identity.task_id, identity.fence) for identity in trace_client.started] == [
            ("read_file", 42001, 1),
        ]
        assert trace_client.phases == [("read_file", "returned"), ("read_file", "acknowledged")]
        first_read = next(t for t in backend.seen_tool_schemas[0] if t["function"]["name"] == "read_file")
        assert first_read["function"]["parameters"]["properties"]["output_format"]["enum"] == [
            "ellmos.read-evidence.v1",
        ]
        assert all(t["function"]["name"] != "read_file" for t in backend.seen_tool_schemas[1])

    @pytest.mark.asyncio
    async def test_revoked_binding_blocks_fallback_request_schema(self, monkeypatch):
        httpx = pytest.importorskip("httpx")
        from hub._services.chat import model_sockets

        binding_box = {}
        def revoke_before_fallback(_tools, _model):
            binding_box["binding"].invalidate()

        primary = _Backend([httpx.ConnectError("test-only pre-answer failure")], on_chat=revoke_before_fallback)
        fallback = _Backend([{"content": "must not run"}])
        runtime = ChatRuntime(primary)
        binding, _profile, _, _session = _live_bound_worker(runtime, "review-worker")
        binding_box["binding"] = binding
        runtime._native_model_fallback_route = lambda _session, _backend, _model: {
            "targets": [
                {"backend": "openrouter", "model": "test-model"},
                {"backend": "openrouter", "model": "test-model"},
            ],
            "index": 0,
        }
        monkeypatch.setattr(model_sockets, "resolve_fallback_backend", lambda _target: fallback)

        answer = await runtime.process("review", "review-worker", backend=primary, model="test-model")

        assert "Taskbindung" in str(answer) or "Workerlauf" in str(answer)
        assert len(primary.seen_tool_schemas) == 1
        assert fallback.seen_tool_schemas == []


# ---------------------------------------------------------------------------
# Store adapter: BACH's snapshots stay the only chat storage
# ---------------------------------------------------------------------------


class TestStoreAdapter:
    def test_adapter_writes_only_into_bachs_snapshot_store(self, snapshot_db):
        store = SQLiteChatSessionStore(snapshot_db)
        runtime = ChatRuntime(_Backend(), session_store=store)
        asyncio.run(runtime.process("Hallo", "gui-web"))

        with sqlite3.connect(snapshot_db) as conn:
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        assert tables == {"session_snapshots"}, "a second chat table would break the cut"
        assert store.load("gui-web") == [
            {"role": "user", "content": "Hallo"},
            {"role": "assistant", "content": "Antwort", "answer_status": "success"},
        ]

    def test_runtime_without_a_store_keeps_working(self):
        runtime = ChatRuntime(_Backend())
        assert asyncio.run(runtime.process("Hallo", "c1")) == "Antwort"
        assert runtime.persistence_status() == {"enabled": False, "ok": False, "error": ""}

    def test_a_broken_store_does_not_break_the_chat(self, tmp_path):
        """The module appends unguarded; the adapter is what keeps a write failure quiet."""
        db_path = tmp_path / "bach.db"
        sqlite3.connect(db_path).close()  # no session_snapshots table
        runtime = ChatRuntime(_Backend(), session_store=SQLiteChatSessionStore(db_path))

        assert asyncio.run(runtime.process("Hallo", "gui-web")) == "Antwort"
        assert runtime.persistence_status()["ok"] is False


# ---------------------------------------------------------------------------
# Surface the Control API (:8081), the tray and the GUI depend on
# ---------------------------------------------------------------------------


class TestConsumerSurface:
    def test_sessions_map_is_reachable_under_bachs_name(self):
        runtime = ChatRuntime(_Backend())
        session = runtime.get_session("c1")
        assert runtime.sessions["c1"] is session
        assert len(runtime.sessions) == 1

    def test_session_carries_bachs_voice_output_flag(self):
        session = ChatRuntime(_Backend()).get_session("c1")
        assert session.voice_output is False
        session.voice_output = True
        assert session.voice_output is True

    def test_mode_reads_back_as_a_plain_string_for_status_output(self):
        """/status and /mode print the mode straight into a Telegram reply."""
        session = ChatRuntime(_Backend()).get_session("c1")
        assert f"Modus: {session.mode}" == "Modus: safe"
        session.mode = "full"
        assert f"Modus: {session.mode}" == "Modus: full"

    def test_system_prompt_stays_bachs_own(self):
        runtime = ChatRuntime(_Backend(), system_prompt="Du bist BACH.")
        prompt = runtime.build_system_prompt(runtime.get_session("c1"))
        assert "Du bist BACH." in prompt
        assert "WICHTIGSTE REGEL — SUCHE ALS FALLBACK" in prompt
        assert "BACH hat 110+ Handler" in prompt
        assert "[Modus=safe, Denken=AN, Modell=test-model]" in prompt

    def test_get_session_can_still_be_monkeypatched(self):
        """telegram_chat.py wraps get_session to apply its global defaults."""
        runtime = ChatRuntime(_Backend())
        original = runtime.get_session

        def patched(chat_id):
            session = original(chat_id)
            session.mode = "full"
            return session

        runtime.get_session = patched
        assert runtime.get_session("c1").mode == "full"
        assert asyncio.run(runtime.process("los", "c1")) == "Antwort"

    def test_max_tool_rounds_is_settable_and_zero_disables_tools(self):
        """Changed meaning: BACH's 0 used to mean an unbounded loop (see PR)."""
        backend = _Backend()
        runtime = ChatRuntime(backend)
        assert runtime.max_tool_rounds == 12

        runtime.max_tool_rounds = 0
        asyncio.run(runtime.process("los", "c1"))
        assert backend.seen_tools[0] == []

    def test_bach_context_hook_keeps_its_name(self):
        runtime = ChatRuntime(_Backend(), memory_fn=lambda *a: "Erinnerung an frueher")
        assert "Erinnerung an frueher" in runtime._get_bach_context("egal")
