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
