# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""PB26 Massnahme 2 (G23): Stable prompt prefix across Kontext-Uebergabe handovers.

At context handover, Ollama's KV prefix cache previously matched only ~633 tokens
(the system prompt) out of 9,673 tokens because:
1. `_handoff` dropped `tools=None`, stripping the ~3,000-token `# Tools` block
   right after the 633-token system prompt during handover and invalidating the
   KV cache for both the handover call and the resumed tool-loop call.
2. `build_system_prompt` and `_process_turn` appended volatile values
   (`[Modus=..., Denken=..., Modell=...]`, `--- BACH ---` with `[CLOCK] HH:MM`,
   `--- MEMORY-HOOK ---`) directly into `messages[0]["content"]` around token ~600.
3. `_summarize` inserted a second `role="system"` message (`Bisheriger Kontext: ...`)
   at the start of `session.messages`.
"""

from __future__ import annotations

import asyncio
import copy
import json
import sys
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parents[1]
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.chat.bach_tools import tools_for_mode
from hub._services.chat.chat_runtime import (
    HANDOFF_PROMPT,
    SELF_DECOMPOSE_INSTRUCTION,
    ChatRuntime,
    ChatSession,
    _deterministic_tools,
    _resume_handoff_context,
)
from hub._services.chat.slots_config import compose_worker_prompt


def _serialize_prefix(messages: list[dict], tools: list[dict] | None) -> str:
    """Serialize the Ollama prompt prefix (system prompt + tool definitions)."""
    assert messages and messages[0].get("role") == "system"
    payload_prefix = {
        "system": messages[0]["content"],
        "tools": tools or [],
    }
    return json.dumps(payload_prefix, ensure_ascii=False, separators=(",", ":"))


class _RecordingOllamaBackend:
    manages_own_tools = False

    def __init__(self):
        self.calls: list[dict] = []

    def get_default_model(self) -> str:
        return "qwen3.8:27b-mlx"

    def get_context_limit(self) -> int:
        return 16384

    def tool_response_message(self, content: str, tool_call_id: str = "") -> dict:
        return {"role": "tool", "content": content, "tool_call_id": tool_call_id}

    async def chat(self, messages, tools=None, think=False, model=None):
        self.calls.append({
            "messages": copy.deepcopy(messages),
            "tools": copy.deepcopy(tools),
            "think": think,
            "model": model,
        })
        if messages[-1].get("content") == HANDOFF_PROMPT:
            return {
                "content": (
                    "AUFTRAG: PB26 Prefix-Cache stabilisieren\n"
                    "ERLEDIGT: chat_runtime.py analysiert\n"
                    "FAKTEN: Systemprompt 633 Token, Tools folgen direkt danach\n"
                    "OFFEN: Tests ausfuehren\n"
                    "RESUME: pytest starten"
                ),
                "prompt_tokens": 9673,
            }
        # First normal call executes read_file (populating read_trail); second triggers Kontext-Uebergabe
        if len(self.calls) == 1:
            return {
                "content": "",
                "prompt_tokens": 4200,
                "tool_calls": [{
                    "id": "call-1",
                    "function": {
                        "name": "read_file",
                        "arguments": {"path": "system/hub/_services/chat/chat_runtime.py", "offset": 1, "lines": 50},
                    },
                }],
            }
        if len(self.calls) == 2:
            return {"content": "", "prompt_tokens": 13500}
        return {"content": "Aufgabe abgeschlossen.", "prompt_tokens": 1800}


def test_buddha_worker_prefix_stays_byte_identical_across_handover(monkeypatch):
    """Simulate a buddha_always_on worker run before, during, and after handover."""
    monkeypatch.setattr(
        "hub._services.chat.chat_runtime.exec_tool",
        lambda *_a, **_kw: "Physische Zeilen 1–50 von 3900; Offset=1; angezeigt=50/200.\n     1 | #!/usr/bin/env python3",
    )
    backend = _RecordingOllamaBackend()
    runtime = ChatRuntime(backend)
    runtime.handoff_percent = 75
    runtime.hook_every = 999
    runtime.auto_continue = 0

    slot = {
        "id": "buddha_always_on",
        "name": "Buddha (immer aktiv)",
        "role_id": "entwickler",
        "mode": "safe",
        "model": "qwen3.8:27b-mlx",
        "think": False,
        "allow_tools": True,
        "max_tool_rounds": 12,
    }
    session = runtime.get_session("buddha_always_on")
    session.chat_id = "buddha_always_on"
    session.mode = "safe"
    session.model = "qwen3.8:27b-mlx"
    session.think = False
    session.allow_tools = True
    session.max_tool_rounds = 12
    session.custom_system_prompt = compose_worker_prompt(slot)

    # Pass tools in reversed order to verify deterministic canonical ordering
    raw_tools = list(reversed(tools_for_mode("safe", bound_worker=session.worker_task_binding is not None)))

    answer = asyncio.run(
        runtime.process(
            "Bearbeite Task #2600: Prefix-Stabilitaet",
            "buddha_always_on",
            work_priority="background",
        )
    )

    assert answer == "Aufgabe abgeschlossen."
    # Calls: 0 = round 0 (tool call), 1 = round 1 (triggers handoff), 2 = _handoff, 3 = resumed round 1
    assert len(backend.calls) == 4

    before_call = backend.calls[0]
    pre_handoff_call = backend.calls[1]
    during_handoff_call = backend.calls[2]
    after_handoff_call = backend.calls[3]

    # All calls must carry non-empty, deterministically ordered tools
    expected_tool_names = [t["function"]["name"] for t in _deterministic_tools(raw_tools)]
    for call in (before_call, pre_handoff_call, during_handoff_call, after_handoff_call):
        assert call["tools"] is not None and len(call["tools"]) > 0
        assert [t["function"]["name"] for t in call["tools"]] == expected_tool_names
        # Only messages[0] is role="system"
        sys_msgs = [m for m in call["messages"] if m.get("role") == "system"]
        assert len(sys_msgs) == 1
        assert call["messages"][0]["role"] == "system"

    prefix_before = _serialize_prefix(before_call["messages"], before_call["tools"])
    prefix_pre_handoff = _serialize_prefix(pre_handoff_call["messages"], pre_handoff_call["tools"])
    prefix_during = _serialize_prefix(during_handoff_call["messages"], during_handoff_call["tools"])
    prefix_after = _serialize_prefix(after_handoff_call["messages"], after_handoff_call["tools"])

    n_chars = len(prefix_before)
    assert n_chars > 5000, "serialized system prompt + tools must cover the full prefix"
    assert prefix_before[:n_chars] == prefix_pre_handoff[:n_chars]
    assert prefix_before[:n_chars] == prefix_during[:n_chars]
    assert prefix_before[:n_chars] == prefix_after[:n_chars]

    # Verify ordering in the resumed post-handover call:
    # 0: stable system prompt
    # 1: handover summary ("Uebergabezettel")
    # 2: read trail ("LESESPUR")
    # late messages at the end: SELF_DECOMPOSE_INSTRUCTION and [Werkzeugrunde ...]
    resumed_msgs = after_handoff_call["messages"]
    assert resumed_msgs[0]["role"] == "system"
    assert "Uebergabezettel" in resumed_msgs[1]["content"]
    assert "RESUME: pytest starten" in resumed_msgs[1]["content"]
    assert "[LESESPUR" in resumed_msgs[2]["content"]
    assert resumed_msgs[-2]["content"] == SELF_DECOMPOSE_INSTRUCTION
    assert resumed_msgs[-1]["content"].startswith("[Werkzeugrunde ")


def test_volatile_values_excluded_from_system_prompt_and_moved_to_late_message(monkeypatch):
    """Volatile clock/status/hook values must not appear in messages[0] across turns and handovers."""
    backend = _RecordingOllamaBackend()
    runtime = ChatRuntime(backend)
    runtime.handoff_percent = 75
    runtime.hook_every = 999
    runtime.auto_continue = 0

    clocks = iter(["[CLOCK] 14:31", "[CLOCK] 14:47"])
    runtime._get_bach_context = lambda _text: f"Kontext:\n{next(clocks, '[CLOCK] 15:00')}"
    runtime._get_memory_hook_context = lambda _text, _cid: "Aktive Erinnerung: PB26"

    session = runtime.get_session("volatile-prefix-test")
    session.mode = "safe"
    session.think = True
    session.model = "qwen3.8:27b-mlx"
    session.allow_tools = True
    session.max_tool_rounds = 8
    # Pre-populate a _summarize entry to ensure it does not become a second system message
    session.messages = [
        {"role": "system", "content": "Bisheriger Kontext: Fruehere Sitzung zusammengefasst."},
    ]

    monkeypatch.setattr(
        "hub._services.chat.chat_runtime.exec_tool",
        lambda *_a, **_kw: "ok",
    )

    answer = asyncio.run(runtime.process("Pruefe Cache-Prefix", "volatile-prefix-test"))
    assert answer == "Aufgabe abgeschlossen."

    before_call = backend.calls[0]
    during_handoff_call = backend.calls[2]
    after_handoff_call = backend.calls[3]

    for call in (before_call, during_handoff_call, after_handoff_call):
        sys_content = call["messages"][0]["content"]
        assert "[CLOCK]" not in sys_content
        assert "[Modus=" not in sys_content
        assert "--- BACH ---" not in sys_content
        assert "--- MEMORY-HOOK ---" not in sys_content
        assert "Bisheriger Kontext:" not in sys_content
        assert "[Werkzeugrunde" not in sys_content
        # Exactly one system message at index 0
        assert [i for i, m in enumerate(call["messages"]) if m.get("role") == "system"] == [0]

    # Prefix (system prompt + tools) is byte-identical before, during, and after handover
    prefix_before = _serialize_prefix(before_call["messages"], before_call["tools"])
    prefix_during = _serialize_prefix(during_handoff_call["messages"], during_handoff_call["tools"])
    prefix_after = _serialize_prefix(after_handoff_call["messages"], after_handoff_call["tools"])
    n_chars = len(prefix_before)
    assert prefix_before[:n_chars] == prefix_during[:n_chars] == prefix_after[:n_chars]

    # The model still receives all volatile information in late user messages
    before_tail = "\n".join(m["content"] for m in before_call["messages"][1:])
    assert "[Modus=safe, Denken=AN, Modell=qwen3.8:27b-mlx]" in before_tail
    assert "--- BACH ---\nKontext:\n[CLOCK] 14:31" in before_tail
    assert "--- MEMORY-HOOK ---\nAktive Erinnerung: PB26" in before_tail
    assert "Bisheriger Kontext: Fruehere Sitzung zusammengefasst." in before_tail

    after_msgs = after_handoff_call["messages"]
    after_tail = "\n".join(m["content"] for m in after_msgs[1:])
    assert "Uebergabezettel" in after_msgs[1]["content"]
    assert "[Modus=safe, Denken=AN, Modell=qwen3.8:27b-mlx]" in after_tail
    assert "--- BACH ---\nKontext:\n[CLOCK] 14:31" in after_tail
    assert "--- MEMORY-HOOK ---\nAktive Erinnerung: PB26" in after_tail
    # Volatile context appears after the handover summary, never before it
    summary_idx = next(i for i, m in enumerate(after_msgs) if "Uebergabezettel" in m.get("content", ""))
    volatile_idx = next(i for i, m in enumerate(after_msgs) if "[Modus=" in m.get("content", ""))
    assert volatile_idx > summary_idx


def test_resume_handoff_context_strips_legacy_volatile_system_suffixes():
    """Even if a caller passes a legacy system prompt with volatile suffixes, _resume_handoff_context cleans it."""
    legacy_sys = (
        "Du bist BACH.\n"
        "[Modus=safe, Denken=AUS, Modell=qwen3.8:27b-mlx]\n\n"
        "--- BACH ---\nKontext:\n[CLOCK] 09:15\n\n"
        "--- MEMORY-HOOK ---\nNotiz A"
    )
    original = [
        {"role": "system", "content": legacy_sys},
        {"role": "user", "content": "Alte Nachricht"},
    ]
    summary = [{"role": "user", "content": "Uebergabezettel:\nRESUME: weiter"}]
    resumed, history = _resume_handoff_context(
        original,
        summary,
        background_task=True,
        has_tools=True,
        round_num=4,
        max_rounds=12,
        read_trail="[LESESPUR dieses Laufs, automatisch aus deinen Werkzeugaufrufen]\n- gelesen a.py: Zeilen 1–10",
    )
    assert resumed[0] == {"role": "system", "content": "Du bist BACH."}
    assert "Uebergabezettel" in resumed[1]["content"]
    assert "[LESESPUR" in resumed[2]["content"]
    assert "[Modus=safe, Denken=AUS, Modell=qwen3.8:27b-mlx]" in resumed[3]["content"]
    assert "--- BACH ---\nKontext:\n[CLOCK] 09:15" in resumed[3]["content"]
    assert "--- MEMORY-HOOK ---\nNotiz A" in resumed[3]["content"]
    assert resumed[4]["content"] == SELF_DECOMPOSE_INSTRUCTION
    assert resumed[5]["content"] == "[Werkzeugrunde 4/12 · noch 8]"
    assert all("[Modus=" not in m.get("content", "") for m in history)
