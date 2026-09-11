# -*- coding: utf-8 -*-
"""Regressionen für den fail-closed Token-Monitor (Task 1209)."""

import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path


SYSTEM_ROOT = Path(__file__).resolve().parents[1]
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub import bach_paths
from tools import token_monitor


def test_token_monitor_uses_canonical_database(tmp_path, monkeypatch):
    canonical_db = tmp_path / "canonical-bach.db"
    with sqlite3.connect(canonical_db) as conn:
        conn.execute(
            "CREATE TABLE monitor_tokens (budget_percent REAL, timestamp TEXT)"
        )
        conn.execute(
            "INSERT INTO monitor_tokens VALUES (?, ?)",
            (42.0, datetime.now().isoformat()),
        )

    monkeypatch.setattr(bach_paths, "BACH_DB", canonical_db)

    assert token_monitor.get_db_path() == canonical_db
    assert token_monitor.get_current_budget_percent() == 42.0


def test_direct_cli_can_resolve_canonical_database(tmp_path):
    canonical_db = tmp_path / "direct-cli.db"
    with sqlite3.connect(canonical_db) as conn:
        conn.execute(
            "CREATE TABLE monitor_tokens (budget_percent REAL, timestamp TEXT)"
        )
        conn.execute(
            "INSERT INTO monitor_tokens VALUES (?, ?)",
            (42.0, datetime.now().isoformat()),
        )

    result = subprocess.run(
        [sys.executable, str(Path(token_monitor.__file__).resolve())],
        cwd=tmp_path,
        env={**os.environ, "BACH_DB": str(canonical_db)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 1
    assert "Budget: 42.0%" in result.stdout
    assert "DB-Fehler" not in result.stdout


def test_direct_cli_reports_unknown_with_distinct_exit_code(tmp_path):
    empty_db = tmp_path / "empty.db"
    empty_db.touch()

    result = subprocess.run(
        [sys.executable, str(Path(token_monitor.__file__).resolve())],
        cwd=tmp_path,
        env={**os.environ, "BACH_DB": str(empty_db)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 5
    assert "Token-Zone unbekannt" in result.stdout
    assert "Budget: unbekannt" in result.stdout
    assert "0.0%" not in result.stdout


def test_missing_telemetry_stays_unknown_and_fail_closed(monkeypatch):
    monkeypatch.setattr(token_monitor, "get_current_budget_percent", lambda: None)

    zone, description, details = token_monitor.get_token_zone()
    status = token_monitor.format_zone_status(zone, description, details)

    assert zone is None
    assert details["budget_percent"] is None
    assert details["telemetry_status"] == "unknown"
    assert details["partners_allowed"] == ["human"]
    assert "unbekannt" in status.lower()
    assert "0.0%" not in status
    assert "Alle Partner" not in status


def test_stale_telemetry_is_unknown(tmp_path):
    stale_db = tmp_path / "stale.db"
    with sqlite3.connect(stale_db) as conn:
        conn.execute(
            "CREATE TABLE monitor_tokens (budget_percent REAL, timestamp TEXT)"
        )
        conn.execute(
            "INSERT INTO monitor_tokens VALUES (?, ?)",
            (12.0, (datetime.now() - timedelta(hours=2)).isoformat()),
        )

    assert token_monitor.get_current_budget_percent(
        stale_db,
        max_age_seconds=3600,
    ) is None


def test_explicit_zero_is_a_measured_zone_one_value():
    zone, description, details = token_monitor.get_token_zone(0.0)

    assert zone == 1
    assert details["budget_percent"] == 0.0
    assert details["telemetry_status"] == "known"
    assert "Alle Partner" in description


def test_emergency_check_does_not_report_unknown_as_ok(monkeypatch):
    monkeypatch.setattr(token_monitor, "get_current_budget_percent", lambda: None)

    should_stop, message = token_monitor.check_emergency_shutdown()

    assert should_stop is False
    assert "unbekannt" in message.lower()
    assert "[OK]" not in message
