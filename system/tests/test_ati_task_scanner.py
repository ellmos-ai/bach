# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Regression tests for ATI task scanner multi-file task sources."""

import sqlite3
import sys
from pathlib import Path


SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))


def _init_ati_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE ati_scan_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT,
                finished_at TEXT,
                duration_seconds REAL,
                tools_scanned INTEGER DEFAULT 0,
                tasks_found INTEGER DEFAULT 0,
                tasks_new INTEGER DEFAULT 0,
                tasks_updated INTEGER DEFAULT 0,
                tasks_removed INTEGER DEFAULT 0,
                triggered_by TEXT,
                errors TEXT
            );

            CREATE TABLE ati_tool_registry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                status TEXT DEFAULT 'aktiv',
                has_aufgaben INTEGER DEFAULT 0,
                has_test INTEGER DEFAULT 0,
                has_feedback INTEGER DEFAULT 0,
                task_count INTEGER DEFAULT 0,
                last_scan TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE ati_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name TEXT NOT NULL,
                tool_path TEXT NOT NULL,
                task_text TEXT NOT NULL,
                aufwand TEXT DEFAULT 'mittel',
                status TEXT DEFAULT 'offen',
                priority_score REAL DEFAULT 0,
                source_file TEXT NOT NULL,
                line_number INTEGER,
                file_hash TEXT,
                last_modified TEXT,
                synced_at TEXT,
                is_synced INTEGER DEFAULT 1,
                tags TEXT,
                depends_on TEXT,
                created_at TEXT
            );
            """
        )


def test_task_scanner_reads_markdown_task_sources_per_tool(tmp_path):
    from agents.ati.scanner.task_scanner import TaskScanner

    workspace = tmp_path / "workspace"
    tool_dir = workspace / "SINGLE" / "SampleTool"
    tool_dir.mkdir(parents=True)
    (tool_dir / "TODO.md").write_text("- TODO task\n", encoding="utf-8")
    (tool_dir / "AUFGABEN.md").write_text("- Markdown task\n", encoding="utf-8")
    (tool_dir / "DONE.md").write_text("- Released feature\n", encoding="utf-8")
    (tool_dir / "ROADMAP.md").write_text(
        "| ID | Thema | Status | Notiz |\n"
        "| --- | --- | --- | --- |\n"
        "| OPS-1 | Active steering | OFFEN | Pilot |\n"
        "| OPS-2 | Sunset old path | DONE | shipped |\n",
        encoding="utf-8",
    )

    db_path = tmp_path / "bach.db"
    _init_ati_db(db_path)

    scanner = TaskScanner(
        db_path,
        config={
            "base_path": str(workspace),
            "scan_folders": ["SINGLE"],
            "task_files": ["AUFGABEN.txt"],
            "ignore_folders": [],
        },
    )

    result = scanner.scan_all()

    assert result["tools_scanned"] == 1
    assert result["tasks_found"] == 4

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT task_text, status, source_file, line_number FROM ati_tasks ORDER BY task_text"
        ).fetchall()
        task_count = conn.execute(
            "SELECT task_count FROM ati_tool_registry WHERE name = 'SampleTool'"
        ).fetchone()[0]

    assert task_count == 4
    assert any(text == "TODO task" and status == "offen" for text, status, _, _ in rows)
    assert any(text == "Markdown task" and status == "offen" for text, status, _, _ in rows)
    assert any(text == "Released feature" and status == "erledigt" for text, status, _, _ in rows)
    assert any(text == "OPS-1: Active steering" and status == "offen" for text, status, _, _ in rows)
    assert any(source_file.endswith("DONE.md") for _, _, source_file, _ in rows)
    assert any(source_file.endswith("ROADMAP.md") for _, _, source_file, _ in rows)
    assert any(text == "OPS-1: Active steering" and line_number == 3 for text, _, _, line_number in rows)


def test_ati_handler_scan_accepts_trailing_dry_run_flag(tmp_path):
    from hub.ati import ATIHandler

    base = tmp_path / "system"
    (base / "data").mkdir(parents=True)
    (base / "agents" / "ati").mkdir(parents=True)

    success, message = ATIHandler(base).handle("scan", ["--dry-run"])

    assert success is True
    assert "[DRY-RUN]" in message
