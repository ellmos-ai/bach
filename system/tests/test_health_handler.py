# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
import os
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from hub.health import HealthCheckHandler


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def handler(tmp_path):
    db_path = tmp_path / "data" / "bach.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS memory_working "
        "(id INTEGER PRIMARY KEY, type TEXT, content TEXT, created_at TEXT, is_active INTEGER)"
    )
    conn.commit()
    conn.close()
    h = HealthCheckHandler(tmp_path)
    h._canonical_db = db_path
    h.db_path = db_path
    return h


@pytest.fixture
def handler_no_db(tmp_path):
    h = HealthCheckHandler(tmp_path)
    h._canonical_db = None
    h.db_path = None
    return h


# ── Init / Properties ────────────────────────────────────────────────

class TestInit:
    def test_profile_name(self, handler):
        assert handler.profile_name == "healthcheck"

    def test_target_file(self, handler):
        assert handler.target_file is not None

    def test_thresholds(self, handler):
        assert handler.DISK_WARN_GB == 100
        assert handler.NAS_WARN_PERCENT == 80

    def test_operations_include_all(self, handler):
        ops = handler.get_operations()
        for key in ["status", "disk", "ping", "dns", "network", "nas", "all"]:
            assert key in ops


# ── Handle Dispatch ──────────────────────────────────────────────────

class TestHandleDispatch:
    def test_dry_run(self, handler):
        ok, msg = handler.handle("status", [], dry_run=True)
        assert ok is True
        assert "[DRY-RUN]" in msg

    def test_dry_run_does_not_execute(self, handler):
        with patch.object(handler, "_check_ping") as mock_ping:
            handler.handle("ping", ["8.8.8.8"], dry_run=True)
            mock_ping.assert_not_called()

    def test_unknown_operation(self, handler):
        ok, msg = handler.handle("unknown", [])
        assert ok is False
        assert "Unbekannte Operation" in msg
        assert "Verfuegbar" in msg

    def test_dispatch_ping(self, handler):
        with patch.object(handler, "_check_ping", return_value=(True, "erreichbar")):
            ok, msg = handler.handle("ping", ["8.8.8.8"])
            assert ok is True
            assert "erreichbar" in msg


# ── _check_disk ──────────────────────────────────────────────────────

class TestCheckDisk:
    def test_disk_ok(self, handler):
        with patch("hub.health.shutil.disk_usage") as mock_usage:
            mock_usage.return_value = MagicMock(
                free=200 * 1024**3, total=500 * 1024**3, used=300 * 1024**3
            )
            ok, msg = handler._check_disk()
            assert ok is True
            assert "200.0 GB frei" in msg

    def test_disk_warn_low_space(self, handler):
        with patch("hub.health.shutil.disk_usage") as mock_usage:
            mock_usage.return_value = MagicMock(
                free=50 * 1024**3, total=500 * 1024**3, used=450 * 1024**3
            )
            ok, msg = handler._check_disk()
            assert ok is False
            assert "50.0 GB frei" in msg

    def test_disk_error(self, handler):
        with patch("hub.health.shutil.disk_usage", side_effect=OSError("Access denied")):
            ok, msg = handler._check_disk()
            assert ok is False
            assert "Fehler" in msg


class TestCheckAllDrives:
    def test_returns_list(self, handler):
        with patch("hub.health.shutil.disk_usage") as mock_usage:
            mock_usage.return_value = MagicMock(
                free=200 * 1024**3, total=500 * 1024**3, used=300 * 1024**3
            )
            lines = handler._check_all_drives()
            assert isinstance(lines, list)

    def test_marks_low_space_drive(self, handler):
        if os.name != "nt":
            pytest.skip("Windows-only test")
        with patch("hub.health.shutil.disk_usage") as mock_usage, \
             patch("hub.health.os.path.exists", return_value=True):
            mock_usage.return_value = MagicMock(
                free=10 * 1024**3, total=500 * 1024**3, used=490 * 1024**3
            )
            lines = handler._check_all_drives()
            found_warn = any("[!]" in l for l in lines)
            assert found_warn


# ── _check_ping ──────────────────────────────────────────────────────

class TestCheckPing:
    def test_ping_success(self, handler):
        mock_result = MagicMock(
            returncode=0,
            stdout=b"Reply from 8.8.8.8: time=12ms TTL=120\n"
        )
        with patch("hub.health.subprocess.run", return_value=mock_result):
            ok, msg = handler._check_ping("8.8.8.8")
            assert ok is True
            assert "erreichbar" in msg

    def test_ping_success_german(self, handler):
        mock_result = MagicMock(
            returncode=0,
            stdout="Antwort von 8.8.8.8: Zeit=12ms TTL=120\n".encode("utf-8")
        )
        with patch("hub.health.subprocess.run", return_value=mock_result):
            ok, msg = handler._check_ping("8.8.8.8")
            assert ok is True
            assert "erreichbar" in msg

    def test_ping_success_no_time_line(self, handler):
        mock_result = MagicMock(returncode=0, stdout=b"Success\n")
        with patch("hub.health.subprocess.run", return_value=mock_result):
            ok, msg = handler._check_ping("8.8.8.8")
            assert ok is True
            assert "erreichbar" in msg

    def test_ping_failure(self, handler):
        mock_result = MagicMock(returncode=1, stdout=b"")
        with patch("hub.health.subprocess.run", return_value=mock_result):
            ok, msg = handler._check_ping("nonexistent.host")
            assert ok is False
            assert "nicht erreichbar" in msg

    def test_ping_timeout(self, handler):
        with patch("hub.health.subprocess.run", side_effect=subprocess.TimeoutExpired("ping", 5)):
            ok, msg = handler._check_ping("slow.host")
            assert ok is False
            assert "Timeout" in msg

    def test_ping_not_found(self, handler):
        with patch("hub.health.subprocess.run", side_effect=FileNotFoundError):
            ok, msg = handler._check_ping("any.host")
            assert ok is False
            assert "nicht gefunden" in msg

    def test_ping_uses_correct_flags_nt(self, handler):
        with patch("hub.health.os.name", "nt"), \
             patch("hub.health.subprocess.run", return_value=MagicMock(returncode=1, stdout=b"")) as mock_run:
            handler._check_ping("test.host")
            args = mock_run.call_args[0][0]
            assert "-n" in args
            assert "-w" in args

    def test_ping_uses_correct_flags_posix(self, handler):
        with patch("hub.health.os.name", "posix"), \
             patch("hub.health.subprocess.run", return_value=MagicMock(returncode=1, stdout=b"")) as mock_run:
            handler._check_ping("test.host")
            args = mock_run.call_args[0][0]
            assert "-c" in args
            assert "-W" in args


# ── _check_dns ───────────────────────────────────────────────────────

class TestCheckDns:
    def test_all_resolved(self, handler):
        with patch("hub.health.socket.gethostbyname", return_value="1.2.3.4"):
            ok, msg = handler._check_dns()
            assert ok is True
            assert "3/3" in msg

    def test_partial_resolution(self, handler):
        call_count = [0]
        def side_effect(host):
            call_count[0] += 1
            if call_count[0] == 2:
                raise socket.gaierror("fail")
            return "1.2.3.4"
        with patch("hub.health.socket.gethostbyname", side_effect=side_effect):
            ok, msg = handler._check_dns()
            assert ok is True
            assert "Teilweise" in msg
            assert "2/3" in msg

    def test_all_fail(self, handler):
        with patch("hub.health.socket.gethostbyname", side_effect=socket.gaierror("fail")):
            ok, msg = handler._check_dns()
            assert ok is False
            assert "fehlgeschlagen" in msg


# ── _check_db ────────────────────────────────────────────────────────

class TestCheckDb:
    def test_db_exists_small(self, handler):
        ok, msg = handler._check_db()
        assert ok is True
        assert "bach.db" in msg
        assert "MB" in msg

    def test_db_not_found(self, handler, tmp_path):
        handler.db_path = tmp_path / "nonexistent.db"
        ok, msg = handler._check_db()
        assert ok is False
        assert "nicht gefunden" in msg

    def test_db_path_none(self, handler_no_db):
        ok, msg = handler_no_db._check_db()
        assert ok is False
        assert "nicht konfiguriert" in msg

    def test_db_large(self, handler, tmp_path):
        large_db = tmp_path / "large.db"
        large_db.write_bytes(b"\x00" * (600 * 1024 * 1024))
        handler.db_path = large_db
        ok, msg = handler._check_db()
        assert ok is False
        assert "600" in msg or "MB" in msg


# ── _network (Bug-Fix: aggregates results) ──────────────────────────

class TestNetwork:
    def test_all_ok(self, handler):
        with patch.object(handler, "_check_ping", return_value=(True, "ok")), \
             patch.object(handler, "_check_dns", return_value=(True, "ok")):
            ok, msg = handler._network([])
            assert ok is True
            assert "Netzwerk-Checks" in msg

    def test_ping_fails_returns_false(self, handler):
        with patch.object(handler, "_check_ping", return_value=(False, "timeout")), \
             patch.object(handler, "_check_dns", return_value=(True, "ok")):
            ok, msg = handler._network([])
            assert ok is False
            assert "[FAIL]" in msg

    def test_dns_fails_returns_false(self, handler):
        with patch.object(handler, "_check_ping", return_value=(True, "ok")), \
             patch.object(handler, "_check_dns", return_value=(False, "fail")):
            ok, msg = handler._network([])
            assert ok is False

    def test_all_fail_returns_false(self, handler):
        with patch.object(handler, "_check_ping", return_value=(False, "fail")), \
             patch.object(handler, "_check_dns", return_value=(False, "fail")):
            ok, msg = handler._network([])
            assert ok is False


# ── _nas ─────────────────────────────────────────────────────────────

class TestNas:
    def test_nas_not_found(self, handler):
        with patch("hub.health.os.path.exists", return_value=False):
            ok, msg = handler._nas([])
            assert ok is False
            assert "nicht erreichbar" in msg

    def test_nas_ok(self, handler):
        with patch("hub.health.os.path.exists", side_effect=lambda p: p == r"\\fritz.nas"), \
             patch("hub.health.shutil.disk_usage") as mock_usage:
            mock_usage.return_value = MagicMock(
                total=4000 * 1024**3, used=2000 * 1024**3, free=2000 * 1024**3
            )
            ok, msg = handler._nas([])
            assert ok is True
            assert "50.0%" in msg

    def test_nas_warn_high_usage(self, handler):
        with patch("hub.health.os.path.exists", side_effect=lambda p: p == r"\\fritz.nas"), \
             patch("hub.health.shutil.disk_usage") as mock_usage:
            mock_usage.return_value = MagicMock(
                total=4000 * 1024**3, used=3600 * 1024**3, free=400 * 1024**3
            )
            ok, msg = handler._nas([])
            assert ok is False
            assert "WARNUNG" in msg

    def test_nas_error(self, handler):
        with patch("hub.health.os.path.exists", side_effect=lambda p: p == r"\\fritz.nas"), \
             patch("hub.health.shutil.disk_usage", side_effect=PermissionError("denied")):
            ok, msg = handler._nas([])
            assert ok is False
            assert "Fehler" in msg


# ── _all (integration) ───────────────────────────────────────────────

class TestAll:
    def test_all_ok(self, handler):
        with patch.object(handler, "_check_disk", return_value=(True, "200 GB frei")), \
             patch.object(handler, "_check_ping", return_value=(True, "erreichbar")), \
             patch.object(handler, "_check_dns", return_value=(True, "OK")), \
             patch.object(handler, "_check_db", return_value=(True, "bach.db: 10 MB")), \
             patch.object(handler, "_log_check"):
            ok, msg = handler._all([])
            assert ok is True
            assert "ALLES OK" in msg

    def test_all_with_warnings(self, handler):
        with patch.object(handler, "_check_disk", return_value=(False, "50 GB frei")), \
             patch.object(handler, "_check_ping", return_value=(True, "erreichbar")), \
             patch.object(handler, "_check_dns", return_value=(True, "OK")), \
             patch.object(handler, "_check_db", return_value=(True, "bach.db: 10 MB")), \
             patch.object(handler, "_log_check"):
            ok, msg = handler._all([])
            assert ok is False
            assert "WARNUNGEN VORHANDEN" in msg
            assert "[WARN]" in msg

    def test_status_delegates_to_all(self, handler):
        with patch.object(handler, "_all", return_value=(True, "ok")) as mock_all:
            handler._status([])
            mock_all.assert_called_once_with([])


# ── _log_check ───────────────────────────────────────────────────────

class TestLogCheck:
    def test_log_creates_entry(self, handler):
        handler._log_check(True)
        conn = sqlite3.connect(str(handler.db_path))
        rows = conn.execute("SELECT content FROM memory_working WHERE is_active = 1").fetchall()
        conn.close()
        assert len(rows) == 1
        assert "Health-Check: OK" in rows[0][0]

    def test_log_updates_existing(self, handler):
        handler._log_check(True)
        handler._log_check(False)
        conn = sqlite3.connect(str(handler.db_path))
        rows = conn.execute("SELECT content FROM memory_working WHERE is_active = 1").fetchall()
        conn.close()
        assert len(rows) == 1
        assert "WARNUNGEN" in rows[0][0]

    def test_log_no_db(self, handler_no_db):
        handler_no_db._log_check(True)

    def test_log_db_missing_file(self, handler, tmp_path):
        handler.db_path = tmp_path / "nonexistent.db"
        handler._log_check(True)


# ── Handle integration ───────────────────────────────────────────────

class TestHandleIntegration:
    def test_handle_disk(self, handler):
        with patch.object(handler, "_check_disk", return_value=(True, "200 GB frei")), \
             patch.object(handler, "_check_all_drives", return_value=["  C: 200/500 GB"]):
            ok, msg = handler.handle("disk", [])
            assert ok is True

    def test_handle_ping_with_host(self, handler):
        with patch.object(handler, "_check_ping", return_value=(True, "erreichbar")) as mock_ping:
            ok, msg = handler.handle("ping", ["google.com"])
            assert ok is True
            mock_ping.assert_called_once_with("google.com")

    def test_handle_ping_default_host(self, handler):
        with patch.object(handler, "_check_ping", return_value=(True, "ok")) as mock_ping:
            handler.handle("ping", [])
            mock_ping.assert_called_once_with("fritz.box")

    def test_handle_dns(self, handler):
        with patch.object(handler, "_check_dns", return_value=(True, "OK")):
            ok, msg = handler.handle("dns", [])
            assert ok is True
            assert "DNS Check" in msg

    def test_handle_network(self, handler):
        with patch.object(handler, "_check_ping", return_value=(True, "ok")), \
             patch.object(handler, "_check_dns", return_value=(True, "ok")):
            ok, msg = handler.handle("network", [])
            assert ok is True
