# -*- coding: utf-8 -*-
"""Wave 2 of the BACH-GUI module cut (D-20260830-002): the chat runtime lives in
``ellmos-chat``; BACH injects its tools and its snapshot transcripts and keeps
the surface telegram_chat.py, the tray and the GUI ``/chat`` page rely on."""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

import ellmos_chat  # noqa: E402
from hub._services.chat import bach_tools, chat_runtime  # noqa: E402
from hub._services.chat.chat_runtime import ChatRuntime  # noqa: E402
from hub._services.chat.session_store import SQLiteChatSessionStore  # noqa: E402

CHAT_RUNTIME_SRC = (
    SYSTEM_ROOT / "hub" / "_services" / "chat" / "chat_runtime.py"
).read_text(encoding="utf-8")


class _Backend:
    manages_own_tools = False

    def __init__(self, script=None):
        self.script = list(script or [])
        self.seen_tools: list[list[str]] = []

    def get_default_model(self):
        return "test-model"

    async def chat(self, messages, tools=None, think=True, model=None):
        self.seen_tools.append([t["function"]["name"] for t in (tools or [])])
        return self.script.pop(0) if self.script else {"content": "Antwort"}

    def tool_response_message(self, content, tool_call_id=""):
        return {"role": "tool", "content": content}


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

    @pytest.mark.asyncio
    async def test_full_mode_session_is_offered_the_full_surface(self):
        """String modes come from the Control API; the Safe surface must not be served."""
        backend = _Backend()
        runtime = ChatRuntime(backend)
        runtime.get_session("c1").mode = "full"

        await runtime.process("los", "c1")
        assert "execute_command" in backend.seen_tools[0]


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
            {"role": "assistant", "content": "Antwort"},
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
