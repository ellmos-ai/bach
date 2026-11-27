# SPDX-License-Identifier: MIT
"""Regression tests for Wave 4 worker return & Always-On startup recovery fixes.

Covers empirical failure patterns observed on mac-studio (2026-11-27):
1. Always-On startup monitor retrying while a dead prior process still holds an
   unexpired lease (`worker_delete_leased` -> `prior_lease_active`), while still
   failing closed (`retry=False`) for live/unconfirmed prior processes.
2. `_handoff` falling back once to `tools=None` when Ollama rejects the primary
   stable-prefix handover call (e.g. HTTP 500 on context+tool-schema overflow),
   preserving PB26 G23 stable-prefix behavior on normal runs.
3. Bound-worker prompt (`hintergrund_worker`) and `task_manage` schema clarity
   to prevent `detail_scope`, `followup_depth_exceeded`, and `no_progress` loops.
"""
from __future__ import annotations

import asyncio
import threading

import pytest
from hub._services.chat.bach_tools import tools_for_mode
from hub._services.chat.chat_runtime import HANDOFF_PROMPT, ChatRuntime
from hub._services.chat.slots_config import DEFAULT_ROLE_PROMPTS


def test_always_on_startup_retries_when_dead_prior_process_lease_is_still_active(
    monkeypatch,
):
    from hub import rheingold
    from hub._services import agent_manage_service
    from hub._services.chat import slots_config, telegram_chat

    monkeypatch.setattr(rheingold, "get_lead_config", lambda: {"mode": "lead"})
    monkeypatch.setattr(
        slots_config,
        "persistent_core_startup_snapshot",
        lambda: {"managed": False},
    )
    monkeypatch.setattr(
        slots_config,
        "always_on_startup_snapshot",
        lambda: {
            "configuration_version": "v-test",
            "slot": {
                "id": "buddha_always_on",
                "enabled": True,
                "status": "idle",
                "auto_paused": False,
                "backend": "ollama",
                "model": "inkling-2-mini:latest",
            },
        },
    )
    monkeypatch.setattr(telegram_chat, "_active_worker_ids", lambda: set())
    monkeypatch.setattr(
        telegram_chat,
        "_snapshot_chat_backend",
        lambda *_a, **_kw: (object(), "inkling-2-mini:latest"),
    )
    monkeypatch.setattr(
        agent_manage_service,
        "verified_local_agent_model",
        lambda *_a, **_kw: True,
    )
    monkeypatch.setattr(
        telegram_chat,
        "_start_worker_execution",
        lambda *_a, **_kw: (
            {
                "error": "Vorheriger Core-Lauf nicht beendet oder leasefrei bestätigt",
                "error_code": "core_previous_run_unconfirmed",
                "reason": "prior_lease_active",
                "admission": {"admitted": False},
            },
            409,
        ),
    )

    result = telegram_chat._resume_always_on_at_startup(threading.Event())
    assert result == {"state": "waiting_prior_lease", "retry": True}


def test_always_on_startup_still_denies_unconfirmed_prior_run_without_lease_reason(
    monkeypatch,
):
    """Negative control: live or foreign prior process stays fail-closed (retry=False)."""
    from hub import rheingold
    from hub._services import agent_manage_service
    from hub._services.chat import slots_config, telegram_chat

    monkeypatch.setattr(rheingold, "get_lead_config", lambda: {"mode": "lead"})
    monkeypatch.setattr(
        slots_config,
        "persistent_core_startup_snapshot",
        lambda: {"managed": False},
    )
    monkeypatch.setattr(
        slots_config,
        "always_on_startup_snapshot",
        lambda: {
            "configuration_version": "v-test",
            "slot": {
                "id": "buddha_always_on",
                "enabled": True,
                "status": "idle",
                "auto_paused": False,
                "backend": "ollama",
                "model": "inkling-2-mini:latest",
            },
        },
    )
    monkeypatch.setattr(telegram_chat, "_active_worker_ids", lambda: set())
    monkeypatch.setattr(
        telegram_chat,
        "_snapshot_chat_backend",
        lambda *_a, **_kw: (object(), "inkling-2-mini:latest"),
    )
    monkeypatch.setattr(
        agent_manage_service,
        "verified_local_agent_model",
        lambda *_a, **_kw: True,
    )
    monkeypatch.setattr(
        telegram_chat,
        "_start_worker_execution",
        lambda *_a, **_kw: (
            {
                "error": "Vorheriger Core-Lauf nicht beendet oder leasefrei bestätigt",
                "error_code": "core_previous_run_unconfirmed",
                "admission": {"admitted": False},
            },
            409,
        ),
    )

    result = telegram_chat._resume_always_on_at_startup(threading.Event())
    assert result["state"] == "denied"
    assert result["retry"] is False


class _OverflowThenOkBackend:
    manages_own_tools = False

    def __init__(self, *, fail_without_tools: bool = False):
        self.calls: list[dict] = []
        self.fail_without_tools = fail_without_tools

    def get_default_model(self) -> str:
        return "inkling-2-mini:latest"

    async def chat(self, messages, tools=None, think=False, model=None):
        self.calls.append({"has_tools": tools is not None, "last": messages[-1]["content"]})
        if tools is not None:
            return {"error": "HTTPStatusError: Ollama: Anfrage vom Anbieter abgelehnt. HTTP 500."}
        if self.fail_without_tools:
            return {"error": "HTTPStatusError: Ollama: Anfrage vom Anbieter abgelehnt. HTTP 500."}
        return {"content": "AUFTRAG: X\nERLEDIGT: Y\nFAKTEN: Z\nOFFEN: W\nRESUME: weiter"}


def test_handoff_falls_back_once_without_tools_on_backend_error():
    backend = _OverflowThenOkBackend()
    runtime = ChatRuntime(backend)
    session = runtime.get_session("buddha_always_on")
    session.model = "inkling-2-mini:latest"
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "arbeite"},
    ]
    sample_tools = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]

    resumed = asyncio.run(
        runtime._handoff(msgs, session, backend=backend, model="inkling-2-mini:latest", tools=sample_tools)
    )
    assert len(backend.calls) == 2
    assert backend.calls[0]["has_tools"] is True
    assert backend.calls[1]["has_tools"] is False
    assert backend.calls[0]["last"] == HANDOFF_PROMPT
    assert len(resumed) == 1
    assert "AUFTRAG: X" in resumed[0]["content"]
    assert "RESUME: weiter" in resumed[0]["content"]


def test_handoff_strict_still_raises_when_both_attempts_fail():
    backend = _OverflowThenOkBackend(fail_without_tools=True)
    runtime = ChatRuntime(backend)
    session = runtime.get_session("buddha_always_on")
    session.model = "inkling-2-mini:latest"
    msgs = [{"role": "user", "content": "arbeite"}]
    sample_tools = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]

    with pytest.raises(RuntimeError, match="Kontext-Übergabe fehlgeschlagen"):
        asyncio.run(
            runtime._handoff(
                msgs, session, backend=backend, model="inkling-2-mini:latest", strict=True, tools=sample_tools
            )
        )
    assert len(backend.calls) == 2


def test_hintergrund_worker_prompt_and_task_manage_schema_document_bound_rules():
    prompt = DEFAULT_ROLE_PROMPTS["hintergrund_worker"]
    assert "start_task_worktree" in prompt
    assert "action='detail'" in prompt
    assert "submit_result(complete=false)" in prompt
    assert "no_progress" in prompt

    tm = next(t for t in tools_for_mode("full") if t["function"]["name"] == "task_manage")
    props = tm["function"]["parameters"]["properties"]
    assert "NUR eigene task_id" in props["action"]["description"]
    assert "worker-erstellten Tasks gesperrt" in props["action"]["description"]
    assert "eigene Task-ID" in props["task_id"]["description"]
    assert "Steckplatz" not in props["assigned_slot"]["description"]
