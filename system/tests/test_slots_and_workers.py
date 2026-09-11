# -*- coding: utf-8 -*-
"""Unit tests for BACH slots configuration, dynamic background workers,
multi-backend slot assignment, and activity dashboard.
"""

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


