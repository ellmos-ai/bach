# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for Time Handlers (hub/time.py): Clock, Timer, Countdown, Between, Beat."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.time import (
    ClockHandler,
    TimerHandler,
    CountdownHandler,
    BetweenHandler,
    BeatHandler,
)


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def base_path(tmp_path):
    """Create minimal directory structure."""
    (tmp_path / "data").mkdir()
    (tmp_path / "tools").mkdir()
    return tmp_path


@pytest.fixture
def mock_time_system(monkeypatch):
    """Mock the tools.time_system module for all handlers."""
    fake_module = MagicMock()
    monkeypatch.setitem(sys.modules, "tools.time_system", fake_module)
    monkeypatch.setitem(sys.modules, "tools", MagicMock())
    return fake_module


# ═══════════════════════════════════════════════════════════════
# CLOCK HANDLER
# ═══════════════════════════════════════════════════════════════


class TestClockHandler:
    def test_profile_name(self, base_path):
        handler = ClockHandler(base_path)
        assert handler.profile_name == "clock"

    def test_operations(self, base_path):
        handler = ClockHandler(base_path)
        ops = handler.get_operations()
        assert "on" in ops
        assert "off" in ops
        assert "status" in ops
        assert "interval" in ops

    def test_clock_on(self, base_path, mock_time_system):
        mock_clock = MagicMock()
        mock_clock.enable.return_value = "[CLOCK] Aktiviert"
        mock_time_system.ClockModule.return_value = mock_clock

        handler = ClockHandler(base_path)
        ok, output = handler.handle("on", [])
        assert ok is True
        assert "Aktiviert" in output
        mock_clock.enable.assert_called_once_with(True)

    def test_clock_off(self, base_path, mock_time_system):
        mock_clock = MagicMock()
        mock_clock.enable.return_value = "[CLOCK] Deaktiviert"
        mock_time_system.ClockModule.return_value = mock_clock

        handler = ClockHandler(base_path)
        ok, output = handler.handle("off", [])
        assert ok is True
        mock_clock.enable.assert_called_once_with(False)

    def test_clock_interval_valid(self, base_path, mock_time_system):
        mock_clock = MagicMock()
        mock_clock.set_interval.return_value = "Intervall: 30s"
        mock_time_system.ClockModule.return_value = mock_clock

        handler = ClockHandler(base_path)
        ok, output = handler.handle("interval", ["30"])
        assert ok is True
        mock_clock.set_interval.assert_called_once_with(30)

    def test_clock_interval_no_args(self, base_path, mock_time_system):
        mock_time_system.ClockModule.return_value = MagicMock()
        handler = ClockHandler(base_path)
        ok, output = handler.handle("interval", [])
        assert ok is False
        assert "Usage" in output

    def test_clock_interval_invalid(self, base_path, mock_time_system):
        mock_time_system.ClockModule.return_value = MagicMock()
        handler = ClockHandler(base_path)
        ok, output = handler.handle("interval", ["abc"])
        assert ok is False
        assert "Ungueltige Zahl" in output

    def test_clock_unknown_op(self, base_path, mock_time_system):
        mock_time_system.ClockModule.return_value = MagicMock()
        handler = ClockHandler(base_path)
        ok, output = handler.handle("nonsense", [])
        assert ok is False
        assert "Unbekannte Operation" in output


# ═══════════════════════════════════════════════════════════════
# TIMER HANDLER
# ═══════════════════════════════════════════════════════════════


class TestTimerHandler:
    def test_profile_name(self, base_path):
        handler = TimerHandler(base_path)
        assert handler.profile_name == "timer"

    def test_timer_start_default_name(self, base_path, mock_time_system):
        mock_timer = MagicMock()
        mock_timer.start.return_value = "Timer 'default' gestartet"
        mock_time_system.TimerModule.return_value = mock_timer

        handler = TimerHandler(base_path)
        ok, output = handler.handle("start", [])
        assert ok is True
        mock_timer.start.assert_called_once_with("default")

    def test_timer_start_with_name(self, base_path, mock_time_system):
        mock_timer = MagicMock()
        mock_timer.start.return_value = "Timer 'coding' gestartet"
        mock_time_system.TimerModule.return_value = mock_timer

        handler = TimerHandler(base_path)
        ok, output = handler.handle("start", ["coding"])
        assert ok is True
        mock_timer.start.assert_called_once_with("coding")

    def test_timer_stop(self, base_path, mock_time_system):
        mock_timer = MagicMock()
        mock_timer.stop.return_value = "Timer gestoppt: 00:05:30"
        mock_time_system.TimerModule.return_value = mock_timer

        handler = TimerHandler(base_path)
        ok, output = handler.handle("stop", ["coding"])
        assert ok is True
        mock_timer.stop.assert_called_once_with("coding")

    def test_timer_list(self, base_path, mock_time_system):
        mock_timer = MagicMock()
        mock_timer.list_timers.return_value = "Keine aktiven Timer"
        mock_time_system.TimerModule.return_value = mock_timer

        handler = TimerHandler(base_path)
        ok, output = handler.handle("list", [])
        assert ok is True
        mock_timer.list_timers.assert_called_once()

    def test_timer_clear(self, base_path, mock_time_system):
        mock_timer = MagicMock()
        mock_timer.clear.return_value = "Alle Timer geloescht"
        mock_time_system.TimerModule.return_value = mock_timer

        handler = TimerHandler(base_path)
        ok, output = handler.handle("clear", [])
        assert ok is True
        mock_timer.clear.assert_called_once()

    def test_timer_unknown_op(self, base_path, mock_time_system):
        mock_time_system.TimerModule.return_value = MagicMock()
        handler = TimerHandler(base_path)
        ok, output = handler.handle("nonsense", [])
        assert ok is False
        assert "Unbekannte Operation" in output


# ═══════════════════════════════════════════════════════════════
# COUNTDOWN HANDLER
# ═══════════════════════════════════════════════════════════════


class TestCountdownHandler:
    def test_profile_name(self, base_path):
        handler = CountdownHandler(base_path)
        assert handler.profile_name == "countdown"

    def test_countdown_start_name_and_duration(self, base_path, mock_time_system):
        mock_cd = MagicMock()
        mock_cd.start.return_value = "Countdown 'pomodoro' gestartet: 00:25:00"
        mock_time_system.CountdownModule.return_value = mock_cd

        handler = CountdownHandler(base_path)
        ok, output = handler.handle("start", ["pomodoro", "00:25:00"])
        assert ok is True
        mock_cd.start.assert_called_once_with("pomodoro", "00:25:00", None)

    def test_countdown_start_single_duration(self, base_path, mock_time_system):
        """Single arg -> name='timer', duration=arg."""
        mock_cd = MagicMock()
        mock_cd.start.return_value = "Countdown gestartet"
        mock_time_system.CountdownModule.return_value = mock_cd

        handler = CountdownHandler(base_path)
        ok, output = handler.handle("start", ["00:10:00"])
        assert ok is True
        mock_cd.start.assert_called_once_with("timer", "00:10:00", None)

    def test_countdown_start_with_after(self, base_path, mock_time_system):
        mock_cd = MagicMock()
        mock_cd.start.return_value = "Countdown + Befehl"
        mock_time_system.CountdownModule.return_value = mock_cd

        handler = CountdownHandler(base_path)
        ok, output = handler.handle("start", ["break", "00:05:00", "--after", "bach notify done"])
        assert ok is True
        mock_cd.start.assert_called_once_with("break", "00:05:00", "bach notify done")

    def test_countdown_start_no_args(self, base_path, mock_time_system):
        mock_time_system.CountdownModule.return_value = MagicMock()
        handler = CountdownHandler(base_path)
        ok, output = handler.handle("start", [])
        assert ok is False
        assert "Usage" in output

    def test_countdown_stop_no_args(self, base_path, mock_time_system):
        mock_time_system.CountdownModule.return_value = MagicMock()
        handler = CountdownHandler(base_path)
        ok, output = handler.handle("stop", [])
        assert ok is False
        assert "Usage" in output

    def test_countdown_auto_detect_numeric(self, base_path, mock_time_system):
        """If operation starts with digit, treat as 'start' with duration."""
        mock_cd = MagicMock()
        mock_cd.start.return_value = "Countdown gestartet"
        mock_time_system.CountdownModule.return_value = mock_cd

        handler = CountdownHandler(base_path)
        # Simulate: bach countdown 5:00 -> operation="5:00", args=[]
        ok, output = handler.handle("5:00", [])
        assert ok is True
        mock_cd.start.assert_called_once_with("timer", "5:00", None)

    def test_countdown_unknown_op(self, base_path, mock_time_system):
        mock_time_system.CountdownModule.return_value = MagicMock()
        handler = CountdownHandler(base_path)
        ok, output = handler.handle("nonsense", [])
        assert ok is False
        assert "Unbekannte Operation" in output


# ═══════════════════════════════════════════════════════════════
# BETWEEN HANDLER
# ═══════════════════════════════════════════════════════════════


class TestBetweenHandler:
    def test_profile_name(self, base_path):
        handler = BetweenHandler(base_path)
        assert handler.profile_name == "between"

    def test_between_on(self, base_path, mock_time_system):
        mock_between = MagicMock()
        mock_between.enable.return_value = "[BETWEEN] Aktiviert"
        mock_time_system.BetweenManager.return_value = mock_between

        handler = BetweenHandler(base_path)
        ok, output = handler.handle("on", [])
        assert ok is True
        mock_between.enable.assert_called_once_with(True)

    def test_between_use_no_args(self, base_path, mock_time_system):
        mock_time_system.BetweenManager.return_value = MagicMock()
        handler = BetweenHandler(base_path)
        ok, output = handler.handle("use", [])
        assert ok is False
        assert "Usage" in output


# ═══════════════════════════════════════════════════════════════
# BEAT HANDLER
# ═══════════════════════════════════════════════════════════════


class TestBeatHandler:
    def test_profile_name(self, base_path):
        handler = BeatHandler(base_path)
        assert handler.profile_name == "beat"

    def test_beat_empty_op_shows_beat(self, base_path, mock_time_system):
        mock_manager = MagicMock()
        mock_manager.get_beat.return_value = "14:32 | Timer: coding 00:05:12"
        mock_time_system.TimeManager.return_value = mock_manager

        handler = BeatHandler(base_path)
        ok, output = handler.handle("", [])
        assert ok is True
        assert "14:32" in output
        mock_manager.get_beat.assert_called_once()

    def test_beat_interval_no_args(self, base_path, mock_time_system):
        mock_time_system.TimeManager.return_value = MagicMock()
        handler = BeatHandler(base_path)
        ok, output = handler.handle("interval", [])
        assert ok is False
        assert "Usage" in output

    def test_beat_unknown_op(self, base_path, mock_time_system):
        mock_time_system.TimeManager.return_value = MagicMock()
        handler = BeatHandler(base_path)
        ok, output = handler.handle("nonsense", [])
        assert ok is False
        assert "Unbekannte Operation" in output


# ═══════════════════════════════════════════════════════════════
# ERROR HANDLING (import failure)
# ═══════════════════════════════════════════════════════════════


class TestImportFailure:
    def test_clock_handles_import_error(self, base_path, monkeypatch):
        """If time_system cannot be imported, handler returns graceful error."""
        # Inject a module that raises ImportError when ClockModule is accessed
        broken_module = MagicMock()
        broken_module.ClockModule = property(
            lambda self: (_ for _ in ()).throw(ImportError("no module"))
        )
        monkeypatch.setitem(sys.modules, "tools.time_system", broken_module)

        handler = ClockHandler(base_path)
        # The import statement `from tools.time_system import ClockModule`
        # should fail because the attribute raises. Use patch to simulate.
        with pytest.MonkeyPatch.context() as m:
            import builtins
            original_import = builtins.__import__

            def failing_import(name, *a, **kw):
                if name == "tools.time_system":
                    raise ImportError("mocked import failure")
                return original_import(name, *a, **kw)

            m.setattr(builtins, "__import__", failing_import)
            ok, output = handler.handle("status", [])

        assert ok is False
        assert "nicht verfuegbar" in output

    def test_timer_handles_import_error(self, base_path, monkeypatch):
        """If time_system cannot be imported, handler returns graceful error."""
        import builtins
        original_import = builtins.__import__

        def failing_import(name, *a, **kw):
            if name == "tools.time_system":
                raise ImportError("mocked import failure")
            return original_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", failing_import)

        handler = TimerHandler(base_path)
        ok, output = handler.handle("list", [])
        assert ok is False
        assert "nicht verfuegbar" in output
