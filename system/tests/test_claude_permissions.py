# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for ClaudePermissionsHandler.

Tests profile operations (list, show, set, remove, init, activate) using
a temporary DB so no real settings are touched.
"""

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))


@pytest.fixture
def handler(tmp_path, monkeypatch):
    """ClaudePermissionsHandler with a temp DB and fake settings path."""
    db_path = tmp_path / "test_bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value TEXT,
            type TEXT DEFAULT 'text',
            category TEXT,
            description TEXT,
            updated_at TEXT,
            dist_type INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

    from hub.claude_permissions import ClaudePermissionsHandler
    h = ClaudePermissionsHandler(SYSTEM_ROOT)
    monkeypatch.setattr(h, "db_path", db_path)

    fake_settings = tmp_path / "settings.json"
    fake_settings.write_text("{}", encoding="utf-8")
    import hub.claude_permissions as cp_mod
    monkeypatch.setattr(cp_mod, "SETTINGS_PATH", fake_settings)

    return h


class TestOperations:
    def test_get_operations_returns_dict(self, handler):
        ops = handler.get_operations()
        assert isinstance(ops, dict)
        assert "list" in ops
        assert "activate" in ops

    def test_list_empty(self, handler):
        ok, msg = handler.handle("list", [])
        assert ok is True
        assert "Keine Profile" in msg or "PERMISSION" in msg

    def test_init_creates_defaults(self, handler):
        ok, msg = handler.handle("init", [])
        assert ok is True
        assert "normal" in msg.lower() or "angelegt" in msg.lower() or "erstellt" in msg.lower() or "Default" in msg

    def test_list_after_init(self, handler):
        handler.handle("init", [])
        ok, msg = handler.handle("list", [])
        assert ok is True
        assert "normal" in msg
        assert "remote_control" in msg

    def test_show_profile(self, handler):
        handler.handle("init", [])
        ok, msg = handler.handle("show", ["normal"])
        assert ok is True
        assert "normal" in msg.lower()

    def test_show_nonexistent_profile(self, handler):
        ok, msg = handler.handle("show", ["nonexistent_xyz"])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_set_rule(self, handler):
        handler.handle("init", [])
        ok, msg = handler.handle("set", ["normal", "allow=WebSearch"])
        assert ok is True
        ok2, msg2 = handler.handle("show", ["normal"])
        assert "WebSearch" in msg2

    def test_remove_rule(self, handler):
        handler.handle("init", [])
        handler.handle("set", ["normal", "allow=WebSearch"])
        ok, msg = handler.handle("remove", ["normal", "allow=WebSearch"])
        assert ok is True

    def test_activate_profile(self, handler):
        handler.handle("init", [])
        ok, msg = handler.handle("activate", ["remote_control"])
        assert ok is True

    def test_activate_writes_settings(self, handler):
        import hub.claude_permissions as cp_mod
        handler.handle("init", [])
        handler.handle("activate", ["remote_control"])
        settings = json.loads(cp_mod.SETTINGS_PATH.read_text(encoding="utf-8"))
        assert "permissions" in settings
        assert "allow" in settings["permissions"]
        assert any("Bash" in r for r in settings["permissions"]["allow"])

    def test_deactivate(self, handler):
        handler.handle("init", [])
        handler.handle("activate", ["remote_control"])
        ok, msg = handler.handle("deactivate", [])
        assert ok is True

    def test_status(self, handler):
        handler.handle("init", [])
        ok, msg = handler.handle("status", [])
        assert ok is True

    def test_reset_profile(self, handler):
        handler.handle("init", [])
        handler.handle("set", ["normal", "allow=WebSearch"])
        ok, msg = handler.handle("reset", ["normal"])
        assert ok is True
        ok2, msg2 = handler.handle("show", ["normal"])
        assert "WebSearch" not in msg2

    def test_dry_run_does_not_write(self, handler):
        import hub.claude_permissions as cp_mod
        handler.handle("init", [])
        handler.handle("activate", ["remote_control"], dry_run=True)
        settings = json.loads(cp_mod.SETTINGS_PATH.read_text(encoding="utf-8"))
        assert "permissions" not in settings or "allow" not in settings.get("permissions", {})

    def test_no_operation_shows_help(self, handler):
        ok, msg = handler.handle("", [])
        assert ok is True
        assert "PERMISSIONS" in msg
