# -*- coding: utf-8 -*-
"""Unit tests for BACH slots configuration, dynamic background workers,
multi-backend slot assignment, and activity dashboard.
"""

import importlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.chat.slots_config import (
    DEFAULT_CORE_SLOTS,
    add_worker,
    get_activity_history,
    get_slot,
    list_workers,
    load_slots_config,
    record_activity,
    remove_worker,
    save_slots_config,
    update_slot,
)
from hub._services.chat.chat_runtime import ChatRuntime, ChatSession
from hub._services.chat.telegram_chat import (
    _apply_slot_to_session,
    _get_or_create_backend,
    _resolve_slot_for_chat,
    _snapshot_chat_backend,
    ControlHandler,
)


class TestSlotsConfigCRUD:
    def test_default_slots_loaded(self, tmp_path):
        cfg_file = tmp_path / "test_slots.json"
        cfg = load_slots_config(str(cfg_file))
        assert "slots" in cfg
        assert "buddha_chat" in cfg["slots"]
        assert "buddha_always_on" in cfg["slots"]
        assert "buddha_connector" in cfg["slots"]
        assert cfg["slots"]["buddha_chat"]["model"] == "qwen3.8:27b-mlx"
        assert cfg["slots"]["buddha_always_on"]["max_tool_rounds"] == 25

    def test_update_core_slot(self, tmp_path):
        cfg_file = tmp_path / "test_slots.json"
        load_slots_config(str(cfg_file))

        updated = update_slot("buddha_always_on", {"model": "kimi-k3:cloud", "max_tool_rounds": 30}, path=str(cfg_file))
        assert updated["model"] == "kimi-k3:cloud"
        assert updated["max_tool_rounds"] == 30

        # Reload from disk
        loaded = get_slot("buddha_always_on", path=str(cfg_file))
        assert loaded["model"] == "kimi-k3:cloud"
        assert loaded["max_tool_rounds"] == 30

    def test_add_and_remove_worker(self, tmp_path):
        cfg_file = tmp_path / "test_slots.json"
        load_slots_config(str(cfg_file))

        worker = add_worker({
            "name": "Atlas Scanner",
            "role": "atlas",
            "backend": "claude",
            "model": "sonnet",
            "max_tool_rounds": 15,
            "task_id": 42,
        }, path=str(cfg_file))

        assert worker["name"] == "Atlas Scanner"
        assert worker["role"] == "atlas"
        assert worker["task_id"] == 42
        assert worker["id"].startswith("worker-")

        workers = list_workers(path=str(cfg_file))
        assert any(w["id"] == worker["id"] for w in workers)

        # Remove worker
        ok = remove_worker(worker["id"], path=str(cfg_file))
        assert ok is True
        workers_after = list_workers(path=str(cfg_file))
        assert not any(w["id"] == worker["id"] for w in workers_after)

    def test_worker_expiration(self, tmp_path):
        cfg_file = tmp_path / "test_slots.json"
        load_slots_config(str(cfg_file))

        # Add worker with 0.1s TTL
        worker = add_worker({
            "name": "Short-lived Worker",
            "ttl_seconds": 0.1,
        }, path=str(cfg_file))

        time.sleep(0.2)
        active_workers = list_workers(path=str(cfg_file), include_expired=False)
        assert not any(w["id"] == worker["id"] for w in active_workers)

        all_workers = list_workers(path=str(cfg_file), include_expired=True)
        exp = next(w for w in all_workers if w["id"] == worker["id"])
        assert exp["status"] == "expired"

    def test_activity_recording(self, tmp_path):
        cfg_file = tmp_path / "test_slots.json"
        load_slots_config(str(cfg_file))

        record_activity("buddha_chat", "Anfrage bearbeitet", status="ok", path=str(cfg_file))
        record_activity("buddha_always_on", "Task #99 ausgeführt", status="running", path=str(cfg_file))

        history = get_activity_history(limit=10, path=str(cfg_file))
        assert len(history) == 2
        assert history[0]["source"] == "buddha_always_on"
        assert history[1]["source"] == "buddha_chat"

        slot = get_slot("buddha_always_on", path=str(cfg_file))
        assert slot["current_activity"] == "Task #99 ausgeführt"


class TestTelegramSlotMapping:
    def test_chat_snapshot_discovers_arbitrary_no_tools_worker(self, monkeypatch):
        control = importlib.import_module("hub._services.chat.telegram_chat")

        session = ChatSession()
        session.chat_id = "alpha"
        worker = {"id": "alpha", "backend": "ollama-cloud",
                  "model": "kimi-k3:cloud", "allow_tools": False,
                  "max_tool_rounds": 0}
        backend = object()
        monkeypatch.setattr(control.runtime, "get_session", lambda _id: session)
        monkeypatch.setattr(control, "get_slot", lambda _id: worker)
        monkeypatch.setattr(control, "_get_or_create_backend", lambda *_args: backend)

        selected, model = control._snapshot_chat_backend("alpha")

        assert selected is backend
        assert model == "kimi-k3:cloud"
        assert session.allow_tools is False
        assert session.worker_slot_reader()["allow_tools"] is False

    def test_mismatched_worker_slot_fails_before_fallback(self, monkeypatch):
        control = importlib.import_module("hub._services.chat.telegram_chat")

        session = ChatSession()
        session.chat_id = "alpha"
        monkeypatch.setattr(control.runtime, "get_session", lambda _id: session)

        with pytest.raises(ValueError, match="Worker-Slot"):
            control._snapshot_chat_backend(
                "alpha", worker_slot={"id": "buddha_chat", "allow_tools": False}
            )
        assert session.allow_tools is False

    def test_arbitrary_worker_id_and_reused_session_refresh_capability(self, monkeypatch):
        control = importlib.import_module("hub._services.chat.telegram_chat")

        session = ChatSession()
        session.chat_id = "alpha"
        session.messages = [{"role": "user", "content": "voriger Lauf"}]
        slot = {"id": "alpha", "backend": "ollama-cloud",
                "model": "kimi-k3:cloud", "allow_tools": True,
                "max_tool_rounds": 0}
        backend = object()
        monkeypatch.setattr(control.runtime, "get_session", lambda _id: session)
        monkeypatch.setattr(control, "get_slot", lambda _id: slot)
        monkeypatch.setattr(control, "_get_or_create_backend",
                            lambda *_args: backend)

        selected, model = control._snapshot_chat_backend("alpha", worker_slot=slot)
        assert selected is backend
        assert model == "kimi-k3:cloud"
        assert session.allow_tools is True

        slot["allow_tools"] = False
        selected, model = control._snapshot_chat_backend("alpha", worker_slot=slot)
        assert selected is backend
        assert model == "kimi-k3:cloud"
        assert session.allow_tools is False
        assert session.worker_slot_reader()["allow_tools"] is False

    def test_malformed_worker_rounds_cannot_skip_no_tools_gate(self, monkeypatch):
        control = importlib.import_module("hub._services.chat.telegram_chat")

        session = ChatSession()
        session.chat_id = "alpha"
        slot = {"id": "alpha", "backend": "ollama-cloud",
                "model": "kimi-k3:cloud", "allow_tools": False,
                "max_tool_rounds": "kaputt"}
        monkeypatch.setattr(control.runtime, "get_session", lambda _id: session)
        monkeypatch.setattr(control, "get_slot", lambda _id: slot)
        monkeypatch.setattr(control, "_get_or_create_backend",
                            lambda *_args: object())

        with pytest.raises(ValueError, match="kaputt"):
            control._snapshot_chat_backend("alpha", worker_slot=slot)
        assert session.allow_tools is False

    def test_dynamic_worker_no_tools_flag_survives_config_and_slot(self, tmp_path):
        cfg_file = tmp_path / "no-tools-slots.json"
        worker = add_worker({
            "id": "worker-no-tools-test",
            "backend": "ollama-cloud",
            "model": "kimi-k3:cloud",
            "mode": "safe",
            "max_tool_rounds": 0,
            "allow_tools": False,
            "include_system_prompt": False,
            "task_prompt": "Nur CLOUD_OK antworten",
        }, path=str(cfg_file))
        assert worker["allow_tools"] is False
        assert worker["max_tool_rounds"] == 0

        cfg = load_slots_config(str(cfg_file))
        with patch("hub._services.chat.telegram_chat.load_slots_config", return_value=cfg):
            session = ChatSession()
            _apply_slot_to_session("worker-no-tools-test", session)
        assert session.allow_tools is False
        assert session.max_tool_rounds == 0
        assert session.model == "kimi-k3:cloud"

    def test_worker_no_tools_flag_rejects_non_boolean(self, tmp_path):
        cfg_file = tmp_path / "no-tools-invalid.json"
        with pytest.raises(ValueError, match="JSON-Boolean"):
            add_worker({"allow_tools": "false"}, path=str(cfg_file))

    def test_resolve_slot_for_various_chat_ids(self, tmp_path):
        cfg_file = tmp_path / "test_slots.json"
        with patch("hub._services.chat.telegram_chat.load_slots_config") as mock_load:
            mock_load.return_value = load_slots_config(str(cfg_file))

            # Web / GUI
            chat_slot = _resolve_slot_for_chat("gui-web")
            assert chat_slot["id"] == "buddha_chat"

            # Always-On / Idle Worker
            idle_slot = _resolve_slot_for_chat("idle-atlas-104")
            assert idle_slot["id"] == "buddha_always_on"

            # Telegram / Connectors (numeric chat_id)
            conn_slot = _resolve_slot_for_chat("123456789")
            assert conn_slot["id"] == "buddha_connector"

    def test_apply_slot_to_session(self, tmp_path):
        cfg_file = tmp_path / "test_slots.json"
        cfg = load_slots_config(str(cfg_file))
        cfg["slots"]["buddha_always_on"]["max_tool_rounds"] = 35
        cfg["slots"]["buddha_always_on"]["mode"] = "full"

        with patch("hub._services.chat.telegram_chat.load_slots_config", return_value=cfg):
            session = ChatSession()
            target_backend, model = _apply_slot_to_session("idle-paul-42", session)

            assert session.max_tool_rounds == 35
            assert session.mode == "full"
            assert session.backend is not None
            assert model == "qwen3.8:27b-mlx"

    def test_dynamic_worker_slot_resolution(self, tmp_path):
        cfg_file = tmp_path / "test_slots.json"
        load_slots_config(str(cfg_file))
        worker = add_worker({
            "id": "worker-special-1",
            "name": "Special Worker",
            "backend": "ollama",
            "model": "kimi-k3:cloud",
            "max_tool_rounds": 18,
            "include_system_prompt": False,
            "system_prompt": "Du bist ein Spezialagent",
        }, path=str(cfg_file))

        with patch("hub._services.chat.telegram_chat.load_slots_config", return_value=load_slots_config(str(cfg_file))):
            resolved = _resolve_slot_for_chat("worker-special-1")
            assert resolved["id"] == "worker-special-1"
            assert resolved["model"] == "kimi-k3:cloud"

            session = ChatSession()
            _apply_slot_to_session("worker-special-1", session)
            assert session.model == "kimi-k3:cloud"
            assert session.max_tool_rounds == 18
            assert session.custom_system_prompt == "Du bist ein Spezialagent"

        # Worker with default system prompt inclusion
        worker_with_sys = add_worker({
            "id": "worker-special-2",
            "name": "Special Worker 2",
            "backend": "ollama",
            "model": "kimi-k3:cloud",
            "sub_mode": "task_worker",
            "task_prompt": "Recherchiere die Logs",
        }, path=str(cfg_file))
        assert "Du bist Buddha" in worker_with_sys["system_prompt"]
        assert "Recherchiere die Logs" in worker_with_sys["system_prompt"]


class TestPromptTemplates:
    def test_get_prompt_templates_defaults(self, tmp_path):
        from hub._services.chat.slots_config import (
            DEFAULT_ROLE_PROMPTS,
            DEFAULT_SYSTEM_PROMPT,
            get_prompt_templates,
        )
        cfg_file = tmp_path / "test_slots.json"
        templates = get_prompt_templates(path=str(cfg_file))
        assert "system_default" in templates
        assert templates["system_default"]["text"] == DEFAULT_SYSTEM_PROMPT
        assert templates["system_default"]["is_custom"] is False

        assert "roles" in templates
        assert "hintergrund_worker" in templates["roles"]
        assert "boss_routing" in templates["roles"]
        assert "entwickler" in templates["roles"]
        assert templates["roles"]["entwickler"]["is_custom"] is False
        assert templates["roles"]["entwickler"]["text"] == DEFAULT_ROLE_PROMPTS["entwickler"]

    def test_update_and_reset_prompt_template(self, tmp_path):
        from hub._services.chat.slots_config import (
            DEFAULT_SYSTEM_PROMPT,
            get_prompt_templates,
            reset_prompt_template,
            update_prompt_template,
        )
        cfg_file = tmp_path / "test_slots.json"

        # Update system default
        custom_sys = "Du bist ein custom Buddha-System."
        update_prompt_template("system_default", custom_sys, path=str(cfg_file))
        templates = get_prompt_templates(path=str(cfg_file))
        assert templates["system_default"]["text"] == custom_sys
        assert templates["system_default"]["is_custom"] is True

        # Update a role
        update_prompt_template("role_entwickler", "Custom Developer Role", path=str(cfg_file))
        templates2 = get_prompt_templates(path=str(cfg_file))
        assert templates2["roles"]["entwickler"]["text"] == "Custom Developer Role"
        assert templates2["roles"]["entwickler"]["is_custom"] is True

        # Reset single key
        reset_prompt_template("role_entwickler", path=str(cfg_file))
        templates3 = get_prompt_templates(path=str(cfg_file))
        assert templates3["roles"]["entwickler"]["is_custom"] is False
        assert templates3["system_default"]["is_custom"] is True

        # Reset all
        reset_prompt_template(None, path=str(cfg_file))
        templates_all_reset = get_prompt_templates(path=str(cfg_file))
        assert templates_all_reset["system_default"]["is_custom"] is False
        assert templates_all_reset["system_default"]["text"] == DEFAULT_SYSTEM_PROMPT


class TestComposeWorkerPrompt:
    def test_compose_hintergrund_worker(self, tmp_path):
        from hub._services.chat.slots_config import compose_worker_prompt
        cfg_file = tmp_path / "test_slots.json"

        p = compose_worker_prompt({
            "sub_mode": "hintergrund_worker",
            "include_system_prompt": True,
        }, path=str(cfg_file))
        assert "Du bist Buddha" in p
        assert "ROLLE: HINTERGRUNDWORKER" in p

    def test_compose_boss_routing(self, tmp_path):
        from hub._services.chat.slots_config import compose_worker_prompt
        cfg_file = tmp_path / "test_slots.json"

        p = compose_worker_prompt({
            "sub_mode": "boss_routing",
            "include_system_prompt": True,
            "max_experts": 5,
            "expert_models": {"entwickler": "claude", "steuer": "gpt-4o"},
            "task_prompt": "Optimiere die Pipeline",
        }, path=str(cfg_file))
        assert "Du bist Buddha" in p
        assert "ROLLE: BOSSAGENT & KOORDINATOR" in p
        assert "Max. Unter-Experten: 5" in p
        assert '"entwickler": "claude"' in p
        assert "Optimiere die Pipeline" in p

    def test_compose_expert_role(self, tmp_path):
        from hub._services.chat.slots_config import compose_worker_prompt
        cfg_file = tmp_path / "test_slots.json"

        p = compose_worker_prompt({
            "sub_mode": "expert_role",
            "role_id": "steuer",
            "include_system_prompt": True,
            "task_prompt": "Prüfe EÜR 2025",
        }, path=str(cfg_file))
        assert "Du bist Buddha" in p
        assert "ROLLE: EXPERTE (STEUER)" in p
        assert "Prüfe EÜR 2025" in p

    def test_compose_expert_role_multi(self, tmp_path):
        from hub._services.chat.slots_config import compose_worker_prompt
        cfg_file = tmp_path / "test_slots.json"

        p = compose_worker_prompt({
            "sub_mode": "expert_role",
            "multi_role": True,
            "include_system_prompt": True,
        }, path=str(cfg_file))
        assert "Du bist Buddha" in p
        assert "ROLLE: MULTI-ROLE EXPERTEN-POOL" in p

    def test_compose_isolated_worker(self, tmp_path):
        from hub._services.chat.slots_config import compose_worker_prompt
        cfg_file = tmp_path / "test_slots.json"

        p = compose_worker_prompt({
            "sub_mode": "task_worker",
            "include_system_prompt": False,
            "task_prompt": "Isolierter Task",
        }, path=str(cfg_file))
        assert "Du bist Buddha" not in p
        assert "ROLLE: TASK-WORKER" in p
        assert "Isolierter Task" in p


class TestDynamicContextScaling:
    def test_get_model_context_limit(self):
        backend = MagicMock()
        rt = ChatRuntime(backend=backend)
        rt.context_limit = 32768
        # Local model
        assert rt.get_model_context_limit("qwen3.8:27b-mlx", backend=None) == 32768

        # Cloud / Kimi
        assert rt.get_model_context_limit("kimi-k3:cloud", backend=None) == 131072
        assert rt.get_model_context_limit("glm-4:cloud", backend=None) == 131072

        # Claude / Anthropic
        assert rt.get_model_context_limit("claude-3-7-sonnet", backend=None) == 200000

        # OpenAI / GPT-4o / Codex
        assert rt.get_model_context_limit("gpt-4o", backend=None) == 128000
        assert rt.get_model_context_limit("codex", backend=None) == 128000

    def test_context_voll_respects_scaled_limit(self):
        backend = MagicMock()
        rt = ChatRuntime(backend=backend)
        rt.context_limit = 32768
        rt.handoff_percent = 80
        # 80% of 32768 is 26214
        session_local = ChatSession()
        session_local.model = "qwen3.8:27b-mlx"
        assert rt._context_voll({"prompt_tokens": 27000}, session_local) is True
        assert rt._context_voll({"prompt_tokens": 20000}, session_local) is False

        # For cloud model with 131072, 80% is 104857
        session_cloud = ChatSession()
        session_cloud.model = "kimi-k3:cloud"
        # 27000 tokens should NOT be full for cloud model!
        assert rt._context_voll({"prompt_tokens": 27000}, session_cloud) is False
        assert rt._context_voll({"prompt_tokens": 110000}, session_cloud) is True


class TestControlHandlerEndpoints:
    def test_chat_api_cannot_bypass_arbitrary_no_tools_worker(self, monkeypatch):
        control = importlib.import_module("hub._services.chat.telegram_chat")

        worker = {"id": "alpha", "backend": "ollama-cloud",
                  "model": "kimi-k3:cloud", "allow_tools": False,
                  "max_tool_rounds": 0}
        session = ChatSession()
        session.chat_id = "alpha"
        observed = []
        monkeypatch.setattr(control.runtime, "get_session", lambda _id: session)
        monkeypatch.setattr(control, "get_slot", lambda _id: worker)
        monkeypatch.setattr(control, "_get_or_create_backend", lambda *_args: object())
        monkeypatch.setattr(control, "_checked_backend_availability",
                            lambda *_args: (True, "available"))

        async def fake_process(*_args, **_kwargs):
            observed.append(session.allow_tools)
            return "CLOUD_OK"

        monkeypatch.setattr(control.runtime, "process", fake_process)
        handler = control.ControlHandler.__new__(control.ControlHandler)
        handler.path = "/api/chat"
        handler.headers = {"X-Delegation-Depth": "0"}
        monkeypatch.setattr(handler, "_allow_json_post", lambda: True)
        monkeypatch.setattr(handler, "_read_body", lambda: {
            "chat_id": "alpha", "prompt": "Nur CLOUD_OK",
        })
        monkeypatch.setattr(handler, "_json", lambda *_args, **_kwargs: None)

        handler.do_POST()

        assert observed == [False]

    def test_worker_run_rejects_core_slot_without_worker_id(self, monkeypatch):
        control = importlib.import_module("hub._services.chat.telegram_chat")

        monkeypatch.setattr(control, "get_slot", lambda _id: {"backend": "ollama"})
        handler = control.ControlHandler.__new__(control.ControlHandler)
        handler.path = "/api/workers/run"
        monkeypatch.setattr(handler, "_allow_json_post", lambda: True)
        monkeypatch.setattr(handler, "_read_body", lambda: {"id": "buddha_chat"})
        replies = []
        monkeypatch.setattr(handler, "_json", lambda data, code=200: replies.append((data, code)))

        handler.do_POST()

        assert replies[0][1] == 404

    @pytest.mark.parametrize("rounds, expected_status", [
        (0, "completed"), ("ungültig", "error"),
    ])
    def test_api_worker_custom_id_binds_no_tools_fail_closed(
        self, monkeypatch, rounds, expected_status,
    ):
        control = importlib.import_module("hub._services.chat.telegram_chat")

        worker = {"id": "alpha", "name": "Alpha", "status": "running",
                  "type": "once", "expires_at": None,
                  "backend": "ollama-cloud", "model": "kimi-k3:cloud",
                  "allow_tools": False, "max_tool_rounds": rounds,
                  "task_prompt": "Nur CLOUD_OK"}
        session = ChatSession()
        session.chat_id = "alpha"
        session.messages = [{"role": "user", "content": "persistierter Verlauf"}]
        updates = []
        process_calls = []
        monkeypatch.setattr(control, "get_slot", lambda _id: worker)
        monkeypatch.setattr(control.runtime, "get_session", lambda _id: session)
        monkeypatch.setattr(control, "_get_or_create_backend",
                            lambda *_args: object())
        monkeypatch.setattr(control, "update_slot",
                            lambda _id, change: updates.append(change) or worker)
        monkeypatch.setattr(control, "record_activity",
                            lambda *_args, **_kwargs: None)

        async def fake_process(*_args, **_kwargs):
            process_calls.append(session.allow_tools)
            return "CLOUD_OK"

        monkeypatch.setattr(control.runtime, "process", fake_process)

        class _SynchronousThread:
            def __init__(self, target, **_kwargs):
                self.target = target

            def start(self):
                self.target()

        monkeypatch.setattr(control.threading, "Thread", _SynchronousThread)
        handler = control.ControlHandler.__new__(control.ControlHandler)
        handler.path = "/api/workers/run"
        monkeypatch.setattr(handler, "_allow_json_post", lambda: True)
        monkeypatch.setattr(handler, "_read_body", lambda: {"id": "alpha"})
        monkeypatch.setattr(handler, "_json", lambda *_args, **_kwargs: None)

        handler.do_POST()

        statuses = [change["status"] for change in updates if "status" in change]
        assert statuses[-1] == expected_status
        assert session.allow_tools is False
        if expected_status == "completed":
            assert process_calls == [False]
        else:
            assert process_calls == []

    @pytest.mark.parametrize("flag, expected_code", [(False, 200), ("false", 400)])
    def test_worker_create_api_validates_no_tools_boolean(
        self, tmp_path, monkeypatch, flag, expected_code,
    ):
        control = importlib.import_module("hub._services.chat.telegram_chat")
        from hub._services.chat.slots_config import add_worker as add_to_temp

        cfg_file = tmp_path / "api-no-tools-slots.json"
        monkeypatch.setattr(control, "add_worker",
                            lambda body: add_to_temp(body, path=str(cfg_file)))
        monkeypatch.setattr(control, "record_activity",
                            lambda *_args, **_kwargs: None)
        handler = control.ControlHandler.__new__(control.ControlHandler)
        handler.path = "/api/workers"
        monkeypatch.setattr(handler, "_allow_json_post", lambda: True)
        monkeypatch.setattr(handler, "_read_body", lambda: {
            "id": "worker-api-no-tools", "allow_tools": flag,
            "backend": "ollama-cloud", "model": "kimi-k3:cloud",
            "type": "once", "task_prompt": "Nur CLOUD_OK",
        })
        responses = []
        monkeypatch.setattr(handler, "_json",
                            lambda body, code=200: responses.append((body, code)))

        handler.do_POST()

        assert responses[-1][1] == expected_code
        if expected_code == 200:
            assert responses[-1][0]["worker"]["allow_tools"] is False
        else:
            assert "JSON-Boolean" in responses[-1][0]["error"]

    def test_worker_gui_exposes_truthful_no_tools_control(self):
        from hub._services.chat import telegram_chat

        source = Path(telegram_chat.__file__).read_text(encoding="utf-8")
        assert 'id="nw-allow-tools" checked' in source
        assert "allow_tools: allowTools" in source
        assert "Max Turns 0“ bedeutet unbegrenzt" in source
        assert "Safe (begrenzte Schreibtools, keine freie Shell)" in source

    @pytest.mark.parametrize("answer_kind", ["ok", "failed-type", "failed-text"])
    def test_once_worker_marks_failed_answer_as_error(self, monkeypatch, answer_kind):
        control = importlib.import_module("hub._services.chat.telegram_chat")

        worker_id = "worker-test-failed-answer"
        worker = {"id": worker_id, "name": "Probe", "status": "running",
                  "type": "once", "expires_at": None, "task_prompt": "Probe"}
        updates = []
        activities = []
        monkeypatch.setattr(control, "get_slot", lambda _id: worker)
        monkeypatch.setattr(control, "update_slot",
                            lambda _id, change: updates.append(change) or worker)
        monkeypatch.setattr(control, "record_activity",
                            lambda _id, message, status: activities.append(status))
        monkeypatch.setattr(control, "_snapshot_chat_backend",
                            lambda _id, **_kwargs: (object(), "glm-5.3:cloud"))

        async def fake_process(*_args, **_kwargs):
            if answer_kind == "ok":
                return "CLOUD_OK"
            text = "Backend-Fehler: GLM think=false gesperrt"
            return (control.FailedAnswer(text) if answer_kind == "failed-type"
                    else text)

        monkeypatch.setattr(control.runtime, "process", fake_process)

        class _SynchronousThread:
            def __init__(self, target, **_kwargs):
                self.target = target

            def start(self):
                self.target()

        monkeypatch.setattr(control.threading, "Thread", _SynchronousThread)
        handler = control.ControlHandler.__new__(control.ControlHandler)
        handler.path = "/api/workers/run"
        monkeypatch.setattr(handler, "_allow_json_post", lambda: True)
        monkeypatch.setattr(handler, "_read_body", lambda: {"id": worker_id})
        monkeypatch.setattr(handler, "_json", lambda *_args, **_kwargs: None)

        handler.do_POST()

        statuses = [change["status"] for change in updates if "status" in change]
        if answer_kind == "ok":
            assert statuses[-1] == "completed"
            assert activities[-1] == "ok"
        else:
            assert statuses[-1] == "error"
            assert "completed" not in statuses
            assert activities[-1] == "error"

    def test_get_slots_and_activity(self):
        handler = ControlHandler.__new__(ControlHandler)
        handler.headers = {}
        handler.wfile = MagicMock()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        # Mock GET /api/slots
        handler.path = "/api/slots"
        with patch.object(handler, "_json") as mock_json:
            handler.do_GET()
            mock_json.assert_called_once()
            args = mock_json.call_args[0][0]
            assert args.get("ok") is True
            assert "slots" in args
            assert "buddha_chat" in args["slots"]

        # Mock GET /activity
        handler.path = "/activity"
        with patch.object(handler, "_html") as mock_html:
            handler.do_GET()
            mock_html.assert_called_once()
            html = mock_html.call_args[0][0]
            assert "Aktivit" in html
            assert "buddha_chat" in html
            assert "buddha_always_on" in html

    def test_get_prompts_and_history(self):
        handler = ControlHandler.__new__(ControlHandler)
        handler.headers = {}
        handler.wfile = MagicMock()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        # Mock GET /api/prompts
        handler.path = "/api/prompts"
        with patch.object(handler, "_json") as mock_json:
            handler.do_GET()
            mock_json.assert_called_once()
            res = mock_json.call_args[0][0]
            assert res.get("ok") is True
            assert "templates" in res
            assert "system_default" in res["templates"]
            assert "roles" in res["templates"]

        # Mock GET /api/chat/history
        handler.path = "/api/chat/history?chat_id=gui-web"
        with patch.object(handler, "_json") as mock_json:
            handler.do_GET()
            mock_json.assert_called_once()
            res = mock_json.call_args[0][0]
            assert res.get("ok") is True
            assert res.get("chat_id") == "gui-web"
            assert "messages" in res

    def test_post_prompts_crud(self):
        handler = ControlHandler.__new__(ControlHandler)
        handler.headers = {"Origin": "http://127.0.0.1:8000", "Content-Type": "application/json"}
        handler.wfile = MagicMock()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        # Mock POST /api/prompts
        handler.path = "/api/prompts"
        with patch.object(handler, "_read_body", return_value={"key": "system_default", "text": "New Text"}), \
             patch("hub._services.chat.telegram_chat.update_prompt_template") as mock_upd, \
             patch.object(handler, "_json") as mock_json:
            handler.do_POST()
            mock_upd.assert_called_once_with("system_default", "New Text")
            mock_json.assert_called_once()
            res = mock_json.call_args[0][0]
            assert res.get("ok") is True

        # Mock POST /api/prompts/reset
        handler.path = "/api/prompts/reset"
        with patch.object(handler, "_read_body", return_value={"key": "system_default"}), \
             patch("hub._services.chat.telegram_chat.reset_prompt_template") as mock_reset, \
             patch.object(handler, "_json") as mock_json:
            handler.do_POST()
            mock_reset.assert_called_once_with("system_default")
            mock_json.assert_called_once()
            res = mock_json.call_args[0][0]
            assert res.get("ok") is True

    def test_allowed_origins_and_tailscale(self):
        from hub._services.chat.telegram_chat import _is_allowed_origin

        # Localhost & loopback
        assert _is_allowed_origin("http://localhost:8081") is True
        assert _is_allowed_origin("http://127.0.0.1:8081") is True

        # Tailscale CGNAT IP (100.64.0.0/10)
        assert _is_allowed_origin("http://100.119.69.90:8081") is True
        assert _is_allowed_origin("http://100.108.34.112:8000") is True

        # Private LAN
        assert _is_allowed_origin("http://192.168.1.100:8081") is True
        assert _is_allowed_origin("http://10.0.0.5:8081") is True

        # Same-origin host match
        assert _is_allowed_origin("http://custom-box:8081", req_host="custom-box:8081") is True

        # Untrusted external origin
        assert _is_allowed_origin("http://evil.com") is False
        assert _is_allowed_origin("https://attacker.org:8081") is False

    def test_reconcile_workers_heals_frozen_running_status(self, tmp_path):
        from hub._services.chat.slots_config import add_worker, update_slot, reconcile_workers, load_slots_config
        cfg_file = tmp_path / "test_slots.json"

        w = add_worker({
            "name": "Frozen-Worker",
            "type": "persistent",
            "status": "idle",
        }, path=str(cfg_file))
        wid = w["id"]

        # Simulate stuck running status
        update_slot(wid, {"status": "running", "current_activity": "Arbeitet seit Stunden..."}, path=str(cfg_file))
        cfg_before = load_slots_config(str(cfg_file))
        assert cfg_before["dynamic_workers"][0]["status"] == "running"

        # Reconcile with empty active_worker_ids (no thread alive)
        reconciled = reconcile_workers(active_worker_ids=set(), path=str(cfg_file))
        target = next(item for item in reconciled if item["id"] == wid)
        assert target["status"] == "idle"
        assert "Bereit (wiederhergestellt)" in target["current_activity"]

    def test_compose_task_divider_prompt(self, tmp_path):
        from hub._services.chat.slots_config import compose_worker_prompt
        cfg_file = tmp_path / "test_slots.json"

        p = compose_worker_prompt({
            "sub_mode": "expert_role",
            "role_id": "task-divider",
            "include_system_prompt": True,
            "task_prompt": "Zerlege Großaufgabe #42",
        }, path=str(cfg_file))
        assert "ROLLE: EXPERTE (TASK-DIVIDER)" in p
        assert "decompose" in p or "Zerlegung" in p or "Teilpakete" in p
        assert "Zerlege Großaufgabe #42" in p

    def test_api_workers_stop_endpoint(self, tmp_path):
        from hub._services.chat.telegram_chat import ControlHandler
        from hub._services.chat.slots_config import add_worker, update_slot, get_slot
        cfg_file = tmp_path / "test_slots.json"

        w = add_worker({"name": "Stop-Target", "type": "persistent"}, path=str(cfg_file))
        wid = w["id"]
        update_slot(wid, {"status": "running"}, path=str(cfg_file))

        handler = object.__new__(ControlHandler)
        handler.headers = {"Origin": "http://127.0.0.1:8000", "Content-Type": "application/json", "Content-Length": "30"}
        handler.wfile = MagicMock()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.path = "/api/workers/stop"

        with patch("hub._services.chat.telegram_chat.get_slot", return_value={"id": wid, "type": "persistent"}), \
             patch("hub._services.chat.telegram_chat.update_slot", return_value={"id": wid, "status": "idle"}) as mock_upd, \
             patch.object(handler, "_read_body", return_value={"id": wid}), \
             patch.object(handler, "_json") as mock_json:
            handler.do_POST()
            mock_upd.assert_called_once_with(wid, {"status": "idle", "current_activity": "Manuell gestoppt"})
            mock_json.assert_called_once()
            res = mock_json.call_args[0][0]
            assert res.get("ok") is True
