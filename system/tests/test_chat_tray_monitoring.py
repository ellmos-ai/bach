"""Unit tests for chat tray server-worker monitoring & deprecation of client idle-worker.

Tests ticket T-20260909-202877265:
- WP1: Local task-pulling/idle loop is neutralized and sends no unrequested chat posts.
- WP2: Server-worker status (idle, working, paused) in /api/status is reflected in tray menu & icon.
- WP3: Remote pause/toggle signal is dispatched to server.
- WP4: Transparent target host display in tray menu head.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from hub._services.chat.chat_tray import BACHTray


class TestChatTrayMonitoring(unittest.TestCase):
    def setUp(self):
        # Instantiate tray with mocked components
        with patch.object(BACHTray, "_load_prompts", return_value={}), \
             patch.object(BACHTray, "_refresh", return_value=None):
            self.tray = BACHTray(host="127.0.0.1", port=8081, gui_port=8000, remote=False)
            self.tray.icon = MagicMock()

    def test_wp1_idle_tick_and_process_task_are_neutralized(self):
        """Verify that _idle_tick does not run on remote tray and never initiates naive chat posts."""
        with patch.object(self.tray, "_api") as mock_api:
            # When remote=True, tick is completely suppressed
            self.tray.remote = True
            self.tray._idle_tick()
            mock_api.assert_not_called()

            # And even when local, the tray NEVER polls tasks via GET /api/tasks or fires POST /api/chat
            self.tray.remote = False
            self.tray._idle_tick()
            for call in mock_api.call_args_list:
                method, path = call.args[0], call.args[1]
                self.assertFalse(method == "POST" and path == "/api/chat", "Tray must never POST /api/chat")
                self.assertFalse(method == "GET" and path.startswith("/api/tasks"), "Tray must not poll tasks")

    def test_wp2_worker_status_reflected_in_menu_and_icon(self):
        """Verify that worker_status (idle, working, paused) updates menu labels and icon colors."""
        # 1. Idle state
        self.tray.state = {
            "connected": True,
            "mode": "safe",
            "think": True,
            "worker_status": "idle",
            "task_id": None,
            "task_title": "",
            "active_sessions": 0,
        }
        menu = tuple(self.tray._build_menu())
        menu_texts = [item.text for item in menu]
        self.assertTrue(any("🟢 Buddha: Bereit (Leerlauf)" in t for t in menu_texts))
        self.assertTrue(any("Hintergrundarbeit erlauben [✔]" in t for t in menu_texts))

        # 2. Working state
        self.tray.state["worker_status"] = "working"
        self.tray.state["task_id"] = 42
        self.tray.state["task_title"] = "Dokumente analysieren"
        menu = tuple(self.tray._build_menu())
        menu_texts = [item.text for item in menu]
        self.assertTrue(any("🔵 Buddha: Rechnet an Task #42" in t for t in menu_texts))

        # 3. Paused state
        self.tray.state["worker_status"] = "paused"
        self.tray.state["task_id"] = None
        self.tray.state["task_title"] = ""
        menu = tuple(self.tray._build_menu())
        menu_texts = [item.text for item in menu]
        self.assertTrue(any("⏸️ Buddha: Pausiert" in t for t in menu_texts))
        self.assertTrue(any("Hintergrundarbeit erlauben [❌]" in t for t in menu_texts))

    def test_wp3_toggle_server_worker_dispatches_post(self):
        """Verify that _toggle_server_worker dispatches POST /api/worker/toggle."""
        with patch.object(self.tray, "_api") as mock_api:
            self.tray._toggle_server_worker()
            mock_api.assert_any_call("POST", "/api/worker/toggle", body={"worker_id": "buddha_always_on"})

    def test_wp4_target_host_display(self):
        """Verify transparent display of connected target host in the menu head."""
        # Local connection
        self.tray.host = "127.0.0.1"
        self.tray.port = 8081
        self.tray.remote = False
        menu = tuple(self.tray._build_menu())
        self.assertEqual(menu[0].text, "Verbunden mit: Lokal (127.0.0.1:8081)")

        # Remote connection (Mac Studio)
        self.tray.host = "100.119.69.90"
        self.tray.port = 8081
        self.tray.remote = True
        menu = tuple(self.tray._build_menu())
        self.assertEqual(menu[0].text, "Verbunden mit: Mac Studio (100.119.69.90:8081)")


if __name__ == "__main__":
    unittest.main()
