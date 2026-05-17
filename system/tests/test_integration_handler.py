# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for IntegrationHandler."""

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.integration import IntegrationHandler


@pytest.fixture
def int_env(tmp_path):
    """IntegrationHandler with temporary DB."""
    base = tmp_path / "bach" / "system"
    data = base / "data"
    data.mkdir(parents=True)
    db_path = data / "bach.db"

    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE system_config (
            key TEXT PRIMARY KEY, value TEXT, category TEXT, description TEXT
        )
    """)
    conn.commit()
    conn.close()

    handler = IntegrationHandler(base)
    return handler, base, db_path


class TestIntegrationBasic:
    def test_profile_name(self, int_env):
        handler, _, _ = int_env
        assert handler.profile_name == "integration"

    def test_operations(self, int_env):
        handler, _, _ = int_env
        ops = handler.get_operations()
        assert "status" in ops
        assert "push-claude" in ops
        assert "config" in ops
        assert "set" in ops

    def test_unknown_operation(self, int_env):
        handler, _, _ = int_env
        ok, msg = handler.handle("nonexistent", [])
        assert ok is False
        assert "Unbekannte Operation" in msg


class TestIntegrationStatus:
    def test_status_no_config(self, int_env):
        handler, base, _ = int_env
        # Create a CLAUDE.md to avoid "not found" branch
        claude_md = base.parent / "CLAUDE.md"
        claude_md.write_text("# Test", encoding="utf-8")

        ok, msg = handler.handle("status", [])
        assert ok is True
        assert "INTEGRATION STATUS" in msg
        assert "Keine Integration konfiguriert" in msg

    def test_status_with_config(self, int_env):
        handler, base, db_path = int_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO system_config (key, value, category) VALUES (?, ?, ?)",
            ("integration.claude.level", "managed", "integration"),
        )
        conn.commit()
        conn.close()

        claude_md = base.parent / "CLAUDE.md"
        claude_md.write_text("# Test", encoding="utf-8")

        ok, msg = handler.handle("status", [])
        assert ok is True
        assert "managed" in msg

    def test_status_detects_bach_marker(self, int_env):
        handler, base, _ = int_env
        claude_md = base.parent / "CLAUDE.md"
        claude_md.write_text(
            "# Test\n<!-- BACH:START -->\nBACH Block\n<!-- BACH:END -->\n",
            encoding="utf-8",
        )

        ok, msg = handler.handle("status", [])
        assert ok is True
        assert "BACH-Block: Ja" in msg

    def test_status_no_claude_md(self, int_env):
        handler, _, _ = int_env
        ok, msg = handler.handle("status", [])
        assert ok is True
        assert "Existiert: Nein" in msg


class TestIntegrationConfig:
    def test_config_empty(self, int_env):
        handler, _, _ = int_env
        ok, msg = handler.handle("config", [])
        assert ok is True
        assert "Keine Integration-Config" in msg

    def test_config_shows_entries(self, int_env):
        handler, _, db_path = int_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO system_config (key, value, category, description) VALUES (?, ?, ?, ?)",
            ("integration.gemini.level", "sync", "integration", "Gemini sync level"),
        )
        conn.commit()
        conn.close()

        ok, msg = handler.handle("config", [])
        assert ok is True
        assert "gemini" in msg
        assert "sync" in msg


class TestIntegrationSetLevel:
    def test_set_invalid_level(self, int_env):
        handler, _, _ = int_env
        ok, msg = handler.handle("set", ["claude", "invalid"])
        assert ok is False
        assert "Ungültiges Level" in msg

    def test_set_missing_args(self, int_env):
        handler, _, _ = int_env
        ok, msg = handler.handle("set", ["claude"])
        assert ok is False
        assert "Usage" in msg

    def test_set_new_level(self, int_env):
        handler, _, db_path = int_env
        ok, msg = handler.handle("set", ["claude", "managed"])
        assert ok is True
        assert "gesetzt" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT value FROM system_config WHERE key='integration.claude.level'"
        ).fetchone()
        conn.close()
        assert row[0] == "managed"

    def test_set_update_existing(self, int_env):
        handler, _, db_path = int_env
        handler.handle("set", ["claude", "sync"])
        handler.handle("set", ["claude", "full"])

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT value FROM system_config WHERE key='integration.claude.level'"
        ).fetchone()
        conn.close()
        assert row[0] == "full"

    def test_set_managed_shows_hint(self, int_env):
        handler, _, _ = int_env
        ok, msg = handler.handle("set", ["claude", "managed"])
        assert ok is True
        assert "push-claude" in msg


class TestIntegrationPush:
    def test_pull_not_implemented(self, int_env):
        handler, _, _ = int_env
        ok, msg = handler.handle("pull-claude", [])
        assert ok is False
        assert "nicht implementiert" in msg
