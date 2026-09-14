# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Contract tests for the read-only MediPlaner reminder consumer."""
# ruff: noqa: E402

from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.mediplaner_projection import (
    MediplanerProjectionError,
    format_mediplaner_briefing,
    read_mediplaner_projection,
)  # noqa: E402
from hub.daily_agent import DailyAgentHandler  # noqa: E402


def _create_projection(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE projection_metadata (
            contract_id TEXT NOT NULL PRIMARY KEY,
            contract_version TEXT NOT NULL,
            publisher_component TEXT NOT NULL,
            publisher_instance TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            source_checkpoint INTEGER NOT NULL
        );
        CREATE TABLE medication_due (
            record_ref TEXT NOT NULL PRIMARY KEY,
            due_at TEXT NOT NULL,
            window_end_at TEXT NOT NULL,
            reminder_kind TEXT NOT NULL,
            state TEXT NOT NULL,
            record_version INTEGER NOT NULL,
            source_checkpoint INTEGER NOT NULL,
            publisher_instance TEXT NOT NULL
        );
        CREATE TABLE inventory_warning (
            record_ref TEXT NOT NULL PRIMARY KEY,
            warning_band TEXT NOT NULL,
            event_at TEXT NOT NULL,
            record_version INTEGER NOT NULL,
            source_checkpoint INTEGER NOT NULL,
            publisher_instance TEXT NOT NULL
        );
        CREATE TABLE projection_tombstones (
            record_type TEXT NOT NULL,
            record_ref TEXT NOT NULL,
            deleted_at TEXT NOT NULL,
            retain_until TEXT NOT NULL,
            record_version INTEGER NOT NULL,
            source_checkpoint INTEGER NOT NULL,
            publisher_instance TEXT NOT NULL,
            PRIMARY KEY (record_type, record_ref)
        );
        """
    )
    conn.execute(
        "INSERT INTO projection_metadata VALUES (?, ?, ?, ?, ?, ?)",
        (
            "org.ellmos.mediplaner.reminder-projection",
            "1.0.0",
            "mediplaner-v5-projection-adapter",
            "mediplaner-primary",
            "2026-08-22T08:00:00Z",
            41,
        ),
    )
    conn.executemany(
        "INSERT INTO medication_due VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("a" * 32, "2026-08-22T08:00:00Z", "2026-08-22T08:30:00Z", "medication-due", "due", 1, 41, "mediplaner-primary"),
            ("c" * 32, "2026-08-22T09:00:00Z", "2026-08-22T09:30:00Z", "medication-due", "suppressed", 1, 41, "mediplaner-primary"),
        ],
    )
    conn.executemany(
        "INSERT INTO inventory_warning VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("b" * 32, "attention", "2026-08-22T08:00:00Z", 1, 41, "mediplaner-primary"),
            ("d" * 32, "none", "2026-08-22T08:00:00Z", 1, 41, "mediplaner-primary"),
        ],
    )
    conn.commit()
    conn.close()


def test_reads_only_actionable_opaque_records_without_mutation(tmp_path):
    path = tmp_path / "mediplaner.sqlite"
    _create_projection(path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    projection = read_mediplaner_projection(path, previous_checkpoint=40)
    text = format_mediplaner_briefing(projection, include_receipt=True)

    assert [row.record_ref for row in projection.due_records] == ["a" * 32]
    assert [row.record_ref for row in projection.inventory_warnings] == ["b" * 32]
    assert "MEDIPLANER-FÄLLIGKEITEN (1)" in text
    assert "BESTANDSWARNUNGEN (1)" in text
    assert "aaaaaaaaaaaa…" in text and "bbbbbbbbbbbb…" in text
    assert "cccccccccccc" not in text and "dddddddddddd" not in text
    assert "contract=org.ellmos.mediplaner.reminder-projection@1.0.0" in text
    assert "read_only=true" in text
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        ("ALTER TABLE medication_due ADD COLUMN medication_name TEXT", "Spalten-Allowlist"),
        ("UPDATE projection_metadata SET publisher_component = 'other'", "publisher_component"),
        ("UPDATE medication_due SET reminder_kind = 'other'", "reminder_kind"),
        ("UPDATE medication_due SET window_end_at = '2026-08-22T07:59:00Z'", "Fälligkeitsfenster"),
        ("UPDATE inventory_warning SET warning_band = 'secret'", "warning_band"),
    ],
)
def test_contract_drift_fails_closed(tmp_path, statement, message):
    path = tmp_path / "mediplaner.sqlite"
    _create_projection(path)
    conn = sqlite3.connect(path)
    conn.execute(statement)
    conn.commit()
    conn.close()

    with pytest.raises(MediplanerProjectionError, match=message):
        read_mediplaner_projection(path)


def test_unclosed_sidecar_and_consumer_loop_fail_closed(tmp_path):
    path = tmp_path / "mediplaner.sqlite"
    _create_projection(path)
    Path(f"{path}-wal").write_bytes(b"synthetic")
    with pytest.raises(MediplanerProjectionError, match="nicht geschlossen"):
        read_mediplaner_projection(path)

    Path(f"{path}-wal").unlink()
    conn = sqlite3.connect(path)
    conn.execute(
        "UPDATE projection_metadata SET publisher_instance = 'bach-reminder-consumer'"
    )
    conn.execute(
        "UPDATE medication_due SET publisher_instance = 'bach-reminder-consumer'"
    )
    conn.execute(
        "UPDATE inventory_warning SET publisher_instance = 'bach-reminder-consumer'"
    )
    conn.commit()
    conn.close()
    with pytest.raises(MediplanerProjectionError, match="Loop-Guard"):
        read_mediplaner_projection(path)


def test_tombstone_retention_and_active_collision_are_checked(tmp_path):
    path = tmp_path / "mediplaner.sqlite"
    _create_projection(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO projection_tombstones VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "inventory_warning", "b" * 32, "2026-08-22T08:00:00Z",
            "2026-10-22T08:00:00Z", 1, 41, "mediplaner-primary",
        ),
    )
    conn.commit()
    conn.close()

    with pytest.raises(MediplanerProjectionError, match="Tombstone kollidiert"):
        read_mediplaner_projection(path)


def test_checkpoint_must_advance(tmp_path):
    path = tmp_path / "mediplaner.sqlite"
    _create_projection(path)
    with pytest.raises(MediplanerProjectionError, match="nicht neuer"):
        read_mediplaner_projection(path, previous_checkpoint=41)


def test_sqlite_uri_metacharacters_in_path_are_quoted(tmp_path):
    directory = tmp_path / "projection # %"
    directory.mkdir()
    path = directory / "mediplaner.sqlite"
    _create_projection(path)

    projection = read_mediplaner_projection(path)

    assert projection.database_name == "mediplaner.sqlite"


def _handler_with_briefing_db(tmp_path: Path) -> DailyAgentHandler:
    system_dir = tmp_path / "system"
    (system_dir / "data").mkdir(parents=True)
    handler = DailyAgentHandler(system_dir)
    handler.db_path = system_dir / "data" / "bach.db"
    conn = sqlite3.connect(handler.db_path)
    conn.execute(
        """
        CREATE TABLE briefing_config (
            module_name TEXT PRIMARY KEY,
            is_active INTEGER NOT NULL,
            priority INTEGER NOT NULL,
            settings_json TEXT DEFAULT '{}'
        )
        """
    )
    conn.execute(
        "INSERT INTO briefing_config VALUES ('mediplaner_briefing', 0, 60, '{}')"
    )
    conn.commit()
    conn.close()
    return handler


def test_daily_agent_can_preview_mediplaner_projection(tmp_path):
    handler = _handler_with_briefing_db(tmp_path)
    projection = tmp_path / "mediplaner.sqlite"
    _create_projection(projection)

    ok, text = handler.handle(
        "briefing",
        [
            f"--mediplaner-projection={projection}",
            "--mediplaner-receipt",
            "--dry-run",
        ],
        dry_run=True,
    )

    assert ok is True
    assert "MEDIPLANER-FÄLLIGKEITEN (1)" in text
    assert "BESTANDSWARNUNGEN (1)" in text
    assert "publisher=mediplaner-primary" in text


def test_daily_agent_stores_only_inactive_consumer_settings(tmp_path):
    handler = _handler_with_briefing_db(tmp_path)
    projection = tmp_path / "future-mediplaner.sqlite"

    ok, text = handler.handle(
        "config",
        [
            "mediplaner_briefing",
            f"--projection={projection}",
            "--minimum-offline-seconds=2592000",
        ],
    )

    assert ok is True
    assert "bleibt deaktiviert" in text
    conn = sqlite3.connect(handler.db_path)
    row = conn.execute(
        "SELECT is_active, settings_json FROM briefing_config "
        "WHERE module_name = 'mediplaner_briefing'"
    ).fetchone()
    conn.close()
    assert row[0] == 0
    assert __import__("json").loads(row[1]) == {
        "minimum_offline_seconds": 2592000,
        "projection_path": str(projection.resolve()),
    }
