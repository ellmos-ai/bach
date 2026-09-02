# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for MemHandler (hub/mem.py)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.mem import MemHandler


def _block_module_import(monkeypatch, module_name):
    """Force one optional tool import to fail regardless of sys.path state."""
    original_import = __import__

    def guarded_import(name, *args, **kwargs):
        if name == module_name:
            raise ImportError(f"blocked test import: {module_name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", guarded_import)


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def handler(tmp_path):
    """MemHandler with a temporary base path."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    return MemHandler(tmp_path)


# ═══════════════════════════════════════════════════════════════
# PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "mem"

    def test_target_file(self, handler):
        expected = handler.base_path / "tools" / "memory_working_cleanup.py"
        assert handler.target_file == expected

    def test_operations_contains_working(self, handler):
        ops = handler.get_operations()
        assert "working" in ops
        assert "decay" in ops
        assert "status" in ops
        assert "write" in ops
        assert "fact" in ops
        assert "search" in ops


# ═══════════════════════════════════════════════════════════════
# MEMORY ALIASES (delegation to MemoryHandler)
# ═══════════════════════════════════════════════════════════════


class TestMemoryAliases:
    @patch("hub.mem.MemoryHandler")
    def test_status_delegates_to_memory_handler(self, mock_mh_cls, handler):
        mock_instance = MagicMock()
        mock_instance.handle.return_value = (True, "Memory Status OK")
        mock_mh_cls.return_value = mock_instance

        ok, output = handler.handle("status", [])
        assert ok is True
        assert "Memory Status OK" in output
        mock_instance.handle.assert_called_once_with("status", [], False)

    @patch("hub.mem.MemoryHandler")
    def test_write_delegates_to_memory_handler(self, mock_mh_cls, handler):
        mock_instance = MagicMock()
        mock_instance.handle.return_value = (True, "Notiz gespeichert")
        mock_mh_cls.return_value = mock_instance

        ok, output = handler.handle("write", ["Test note"])
        assert ok is True
        mock_instance.handle.assert_called_once_with("write", ["Test note"], False)

    @patch("hub.mem.MemoryHandler")
    def test_empty_operation_delegates_as_status(self, mock_mh_cls, handler):
        mock_instance = MagicMock()
        mock_instance.handle.return_value = (True, "Status")
        mock_mh_cls.return_value = mock_instance

        ok, output = handler.handle("", [])
        assert ok is True
        mock_instance.handle.assert_called_once_with("", [], False)


# ═══════════════════════════════════════════════════════════════
# UNKNOWN OPERATION
# ═══════════════════════════════════════════════════════════════


class TestUnknownOperation:
    def test_unknown_operation_returns_error(self, handler):
        ok, output = handler.handle("nonexistent_op", [])
        assert ok is False
        assert "Unbekannte Operation" in output
        assert "nonexistent_op" in output


# ═══════════════════════════════════════════════════════════════
# WORKING MEMORY
# ═══════════════════════════════════════════════════════════════


class TestWorking:
    def test_working_status_calls_analyze(self, handler, monkeypatch):
        mock_cleanup = MagicMock()
        mock_cleanup.analyze.return_value = (True, "5 Eintraege aktiv")

        mock_module = MagicMock()
        mock_module.WorkingMemoryCleanup.return_value = mock_cleanup
        monkeypatch.setitem(sys.modules, "memory_working_cleanup", mock_module)

        ok, output = handler.handle("working", ["status"])
        assert ok is True
        assert "5 Eintraege aktiv" in output
        mock_cleanup.analyze.assert_called_once_with(dry_run=True)

    def test_working_cleanup_dry_run(self, handler, monkeypatch):
        mock_cleanup = MagicMock()
        mock_cleanup.cleanup_soft.return_value = (True, "3 wuerden geloescht")

        mock_module = MagicMock()
        mock_module.WorkingMemoryCleanup.return_value = mock_cleanup
        monkeypatch.setitem(sys.modules, "memory_working_cleanup", mock_module)

        ok, output = handler.handle("working", ["cleanup", "--dry-run"])
        assert ok is True
        mock_cleanup.cleanup_soft.assert_called_once_with(dry_run=True)

    def test_working_set_expires(self, handler, monkeypatch):
        mock_cleanup = MagicMock()
        mock_cleanup.set_expires_retroactive.return_value = (True, "Expires gesetzt")

        mock_module = MagicMock()
        mock_module.WorkingMemoryCleanup.return_value = mock_cleanup
        monkeypatch.setitem(sys.modules, "memory_working_cleanup", mock_module)

        ok, output = handler.handle("working", ["set-expires"])
        assert ok is True
        mock_cleanup.set_expires_retroactive.assert_called_once_with(dry_run=False)

    def test_working_unknown_subop(self, handler, monkeypatch):
        mock_module = MagicMock()
        mock_module.WorkingMemoryCleanup.return_value = MagicMock()
        monkeypatch.setitem(sys.modules, "memory_working_cleanup", mock_module)

        ok, output = handler.handle("working", ["invalid_subop"])
        assert ok is False
        assert "Unbekannte working-Operation" in output

    def test_working_import_failure(self, handler, monkeypatch):
        """If the tool cannot be imported, return error gracefully."""
        monkeypatch.delitem(sys.modules, "memory_working_cleanup", raising=False)
        _block_module_import(monkeypatch, "memory_working_cleanup")
        ok, output = handler.handle("working", ["status"])
        assert ok is False
        assert "Fehler bei Working Memory Cleanup" in output


# ═══════════════════════════════════════════════════════════════
# DECAY
# ═══════════════════════════════════════════════════════════════


class TestDecay:
    def test_decay_all(self, handler, monkeypatch):
        mock_decay = MagicMock()
        mock_decay.run_decay.return_value = "Decay: 3 Facts, 2 Lessons, 1 Working"

        mock_module = MagicMock()
        mock_module.MemoryDecay.return_value = mock_decay
        monkeypatch.setitem(sys.modules, "memory_decay", mock_module)

        ok, output = handler.handle("decay", [])
        assert ok is True
        assert "Decay" in output
        mock_decay.run_decay.assert_called_once_with(
            facts=True, lessons=True, working=True, dry_run=False
        )

    def test_decay_facts_only(self, handler, monkeypatch):
        mock_decay = MagicMock()
        mock_decay.run_decay.return_value = "Facts decayed"

        mock_module = MagicMock()
        mock_module.MemoryDecay.return_value = mock_decay
        monkeypatch.setitem(sys.modules, "memory_decay", mock_module)

        ok, output = handler.handle("decay", ["--facts"])
        assert ok is True
        mock_decay.run_decay.assert_called_once_with(
            facts=True, lessons=False, working=False, dry_run=False
        )

    def test_decay_dry_run(self, handler, monkeypatch):
        mock_decay = MagicMock()
        mock_decay.run_decay.return_value = "DRY-RUN: nothing changed"

        mock_module = MagicMock()
        mock_module.MemoryDecay.return_value = mock_decay
        monkeypatch.setitem(sys.modules, "memory_decay", mock_module)

        ok, output = handler.handle("decay", ["--dry-run"])
        assert ok is True
        mock_decay.run_decay.assert_called_once_with(
            facts=True, lessons=True, working=True, dry_run=True
        )

    def test_decay_import_failure(self, handler, monkeypatch):
        """If the tool cannot be imported, return error gracefully."""
        monkeypatch.delitem(sys.modules, "memory_decay", raising=False)
        _block_module_import(monkeypatch, "memory_decay")
        ok, output = handler.handle("decay", [])
        assert ok is False
        assert "Fehler bei Memory Decay" in output
