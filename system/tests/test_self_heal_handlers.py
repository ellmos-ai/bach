# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Regression tests for small BACH self-heal handler fixes."""

import sqlite3
import sys
from pathlib import Path


SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))


def _init_base(tmp_path):
    base = tmp_path / "system"
    (base / "data").mkdir(parents=True)
    return base


def test_task_add_returns_created_id(tmp_path):
    from hub.task import TaskHandler

    base = _init_base(tmp_path)
    db_path = base / "data" / "bach.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                priority TEXT,
                category TEXT,
                description TEXT,
                status TEXT,
                created_at TEXT,
                updated_at TEXT,
                completed_at TEXT,
                assigned_to TEXT,
                delegated_to TEXT,
                depends_on TEXT
            )
            """
        )

    success, message = TaskHandler(base).handle("add", ["Self-Heal Test"])

    assert success is True
    assert message == "[OK] Task 1 erstellt: Self-Heal Test"


def test_wiki_read_alias_shows_article(tmp_path):
    from hub.wiki import WikiHandler

    base = _init_base(tmp_path)
    wiki_dir = base / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "bach.txt").write_text("BACH Wiki Body", encoding="utf-8")

    success, message = WikiHandler(base).handle("read", ["bach"])

    assert success is True
    assert "WIKI: BACH" in message
    assert "BACH Wiki Body" in message


def test_mem_write_alias_uses_memory_handler(tmp_path):
    from hub.mem import MemHandler

    base = _init_base(tmp_path)
    db_path = base / "data" / "bach.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE memory_working (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT,
                content TEXT,
                created_at TEXT,
                updated_at TEXT,
                is_active INTEGER DEFAULT 1
            )
            """
        )

    success, message = MemHandler(base).handle("write", ["Kompatible", "Notiz"])

    assert success is True
    assert "Notiz gespeichert" in message

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT type, content FROM memory_working").fetchone()

    assert row == ("note", "Kompatible Notiz")


def test_agent_start_resolves_expert_display_name_to_skill_directory(tmp_path):
    from hub.agent_launcher import AgentLauncherHandler

    base = _init_base(tmp_path)
    expert_dir = base / "agents" / "_experts" / "steuer"
    expert_dir.mkdir(parents=True)
    (expert_dir / "SKILL.md").write_text("# Steuer\n", encoding="utf-8")

    db_path = base / "data" / "bach.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE bach_experts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                display_name TEXT NOT NULL,
                agent_id INTEGER,
                description TEXT,
                skill_path TEXT,
                persona TEXT,
                is_active INTEGER DEFAULT 1
            )
            """
        )
        conn.execute(
            """
            INSERT INTO bach_experts (name, display_name, description, skill_path, persona)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "steuer-agent",
                "Theodor",
                "Steuerbelege",
                "agents/_experts/steuer/",
                "Penibler Steuerberater",
            ),
        )

    success, message = AgentLauncherHandler(base).handle("start", ["Theodor"], dry_run=True)

    assert success is True
    assert "steuer" in message


def test_usecase_run_works_without_linked_workflow_file(tmp_path):
    from hub.tuev import UsecaseHandler

    base = _init_base(tmp_path)
    db_path = base / "data" / "bach.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE usecases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                description TEXT,
                workflow_name TEXT,
                workflow_path TEXT,
                test_input TEXT,
                expected_output TEXT,
                last_tested TEXT,
                test_result TEXT,
                test_score INTEGER,
                created_by TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE workflow_tuev (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_name TEXT,
                workflow_path TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO usecases (
                title, workflow_name, test_input, expected_output, created_by
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "FormBuilder Formulare erstellen",
                "SOFTWARE",
                '{"form": "briefing"}',
                '{"status": "ok"}',
                "user",
            ),
        )

    success, message = UsecaseHandler(base).handle("run", ["1"])

    assert success is True
    assert "FormBuilder Formulare erstellen" in message
    assert "Keine verknuepfte Workflow-Datei gefunden" in message

    with sqlite3.connect(db_path) as conn:
        last_tested = conn.execute(
            "SELECT last_tested FROM usecases WHERE id = 1"
        ).fetchone()[0]

    assert last_tested is not None
