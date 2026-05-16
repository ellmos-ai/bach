# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for LogsHandler (hub/logs.py)."""

import sys
from pathlib import Path
from datetime import datetime, timedelta

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.logs import LogsHandler


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def logs_env(tmp_path, monkeypatch):
    """Minimal logs environment."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    db_path.write_bytes(b"")
    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)

    logs_dir = data_dir / "logs"
    logs_dir.mkdir()
    return tmp_path, logs_dir


@pytest.fixture
def handler(logs_env):
    base, _ = logs_env
    return LogsHandler(base)


# ═══════════════════════════════════════════════════════════════
# TESTS: PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "logs"

    def test_target_file(self, handler):
        assert handler.target_file.name == "logs"

    def test_get_operations(self, handler):
        ops = handler.get_operations()
        assert isinstance(ops, dict)
        assert "status" in ops
        assert "show" in ops
        assert "tail" in ops
        assert "clear" in ops


# ═══════════════════════════════════════════════════════════════
# TESTS: HANDLE — STATUS
# ═══════════════════════════════════════════════════════════════


class TestStatus:
    def test_status_empty_logs_dir(self, handler):
        ok, msg = handler.handle("status", [])
        assert ok is True
        assert "LOGS STATUS" in msg

    def test_status_with_log_files(self, logs_env):
        base, logs_dir = logs_env
        (logs_dir / "auto_log.txt").write_text("line1\nline2\n", encoding="utf-8")
        (logs_dir / "error_log.txt").write_text("err1\n", encoding="utf-8")
        h = LogsHandler(base)
        ok, msg = h.handle("status", [])
        assert ok is True
        assert "auto_log.txt" in msg
        assert "error_log.txt" in msg

    def test_status_with_sessions(self, logs_env):
        base, logs_dir = logs_env
        sessions = logs_dir / "sessions"
        sessions.mkdir()
        (sessions / "session_2026-05-16.txt").write_text("data", encoding="utf-8")
        h = LogsHandler(base)
        ok, msg = h.handle("status", [])
        assert ok is True
        assert "SESSION-LOGS" in msg

    def test_status_without_logs_dir(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        db_path = data_dir / "bach.db"
        db_path.write_bytes(b"")
        monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
        h = LogsHandler(tmp_path)
        ok, msg = h.handle("status", [])
        assert ok is True
        assert "nicht vorhanden" in msg

    def test_default_operation_is_status(self, handler):
        """Unknown/empty ops fall through to _status."""
        ok, msg = handler.handle("", [])
        assert ok is True
        assert isinstance(msg, str)


# ═══════════════════════════════════════════════════════════════
# TESTS: HANDLE — SHOW
# ═══════════════════════════════════════════════════════════════


class TestShow:
    def test_show_existing_log(self, logs_env):
        base, logs_dir = logs_env
        (logs_dir / "auto_log.txt").write_text("line1\nline2\nline3\n", encoding="utf-8")
        h = LogsHandler(base)
        ok, msg = h.handle("show", ["auto_log"])
        assert ok is True
        assert "auto_log.txt" in msg
        assert "line1" in msg

    def test_show_not_found(self, handler):
        ok, msg = handler.handle("show", ["nonexistent_xyz"])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_show_no_args_falls_to_status(self, handler):
        """show without args doesn't match the first branch, falls to _status."""
        ok, msg = handler.handle("show", [])
        assert ok is True
        assert "LOGS STATUS" in msg


# ═══════════════════════════════════════════════════════════════
# TESTS: HANDLE — TAIL
# ═══════════════════════════════════════════════════════════════


class TestTail:
    def test_tail_no_auto_log(self, handler):
        ok, msg = handler.handle("tail", [])
        assert ok is False
        assert "auto_log.txt" in msg

    def test_tail_with_auto_log(self, logs_env):
        base, logs_dir = logs_env
        lines = [f"line {i}" for i in range(100)]
        (logs_dir / "auto_log.txt").write_text("\n".join(lines), encoding="utf-8")
        h = LogsHandler(base)
        ok, msg = h.handle("tail", [])
        assert ok is True
        # default 50 lines
        assert "LOG TAIL" in msg
        assert "line 99" in msg

    def test_tail_with_count(self, logs_env):
        base, logs_dir = logs_env
        lines = [f"line {i}" for i in range(20)]
        (logs_dir / "auto_log.txt").write_text("\n".join(lines), encoding="utf-8")
        h = LogsHandler(base)
        ok, msg = h.handle("tail", ["5"])
        assert ok is True
        assert "letzte 5 Zeilen" in msg


# ═══════════════════════════════════════════════════════════════
# TESTS: HANDLE — CLEAR
# ═══════════════════════════════════════════════════════════════


class TestClear:
    def test_clear_no_old_logs(self, handler):
        ok, msg = handler.handle("clear", [])
        assert ok is True
        assert "Keine alten Logs" in msg

    def test_clear_dry_run(self, logs_env):
        base, logs_dir = logs_env
        sessions = logs_dir / "sessions"
        sessions.mkdir()
        old_file = sessions / "old_session.txt"
        old_file.write_text("old data", encoding="utf-8")
        # set mtime to 10 days ago
        import os
        old_ts = (datetime.now() - timedelta(days=10)).timestamp()
        os.utime(old_file, (old_ts, old_ts))

        h = LogsHandler(base)
        ok, msg = h.handle("clear", [], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg
        assert old_file.exists()  # not deleted in dry run

    def test_clear_actually_deletes(self, logs_env):
        base, logs_dir = logs_env
        sessions = logs_dir / "sessions"
        sessions.mkdir()
        old_file = sessions / "old_session.txt"
        old_file.write_text("old data", encoding="utf-8")
        import os
        old_ts = (datetime.now() - timedelta(days=10)).timestamp()
        os.utime(old_file, (old_ts, old_ts))

        h = LogsHandler(base)
        ok, msg = h.handle("clear", [], dry_run=False)
        assert ok is True
        assert "gelöscht" in msg
        assert not old_file.exists()


# ═══════════════════════════════════════════════════════════════
# TESTS: HANDLE — UNKNOWN
# ═══════════════════════════════════════════════════════════════


class TestUnknown:
    def test_unknown_operation_falls_to_status(self, handler):
        """LogsHandler routes unknown operations to _status."""
        ok, msg = handler.handle("nonexistent", [])
        assert ok is True
        assert isinstance(msg, str)
