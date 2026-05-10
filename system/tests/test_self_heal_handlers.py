# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Regression tests for small BACH self-heal handler fixes."""

import json
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


def test_task_list_supports_in_progress_status(tmp_path):
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
        conn.execute(
            """
            INSERT INTO tasks (title, priority, category, description, status, created_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            ("Bearbeitung laeuft", "P2", "general", "", "in_progress"),
        )
        conn.execute(
            """
            INSERT INTO tasks (title, priority, category, description, status, created_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            ("Noch offen", "P3", "general", "", "pending"),
        )

    success, message = TaskHandler(base).handle("list", ["in_progress"])

    assert success is True
    assert "in_progress" in message
    assert "Bearbeitung laeuft" in message
    assert "Noch offen" not in message


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


def test_memory_provenance_shows_source_scope_and_privacy(tmp_path):
    from hub.memory import MemoryHandler

    base = _init_base(tmp_path)
    db_path = base / "data" / "bach.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE memory_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                value_type TEXT DEFAULT 'text',
                confidence REAL DEFAULT 1.0,
                source TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO memory_facts (category, key, value, confidence, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "user",
                "telefon",
                "030-123456",
                1.0,
                "user_stated",
                "2026-05-08T10:00:00",
                "2026-05-08T10:00:00",
            ),
        )

    success, message = MemoryHandler(base).handle("provenance", ["facts", "3"])

    assert success is True
    assert "MEMORY PROVENANCE" in message
    assert "Expliziter Fakt" in message
    assert "personenbezogen" in message
    assert "vertraulich" in message


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


def test_agent_list_json_is_machine_readable(tmp_path):
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

    success, message = AgentLauncherHandler(base).handle("list", ["--json"])

    assert success is True
    payload = json.loads(message)
    assert payload["active_count"] == 0
    assert payload["agents"][0]["display_name"] == "Theodor"
    assert payload["agents"][0]["status"] == "stopped"


def test_scheduler_jobs_json_computes_status(tmp_path):
    from hub.scheduler import SchedulerHandler

    base = _init_base(tmp_path)
    db_path = base / "data" / "bach.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE scheduler_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                job_type TEXT NOT NULL,
                schedule TEXT,
                command TEXT NOT NULL,
                script_path TEXT,
                arguments TEXT,
                is_active INTEGER DEFAULT 0,
                last_run TEXT,
                next_run TEXT,
                run_count INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                last_result TEXT,
                timeout_seconds INTEGER DEFAULT 300,
                retry_on_fail INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3
            )
            """
        )
        conn.execute(
            """
            INSERT INTO scheduler_jobs (
                name, description, job_type, schedule, command, is_active, next_run, last_result
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "scanner",
                "Scannt Aufgaben",
                "interval",
                "60m",
                "bach scan run",
                1,
                "2099-01-01T00:00:00",
                "success",
            ),
        )
        conn.execute(
            """
            INSERT INTO scheduler_jobs (
                name, description, job_type, schedule, command, is_active, last_result
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "backup",
                "Backup",
                "manual",
                "",
                "bach backup create",
                0,
                None,
            ),
        )

    success, message = SchedulerHandler(base).handle("jobs", ["--json"])

    assert success is True
    payload = json.loads(message)
    jobs = {job["name"]: job for job in payload["jobs"]}
    assert jobs["scanner"]["status"] == "scheduled"
    assert jobs["backup"]["status"] == "disabled"


def test_scheduler_status_json_includes_recent_runs(tmp_path):
    from hub.scheduler import SchedulerHandler

    base = _init_base(tmp_path)
    db_path = base / "data" / "bach.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE scheduler_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                job_type TEXT NOT NULL,
                schedule TEXT,
                command TEXT NOT NULL,
                script_path TEXT,
                arguments TEXT,
                is_active INTEGER DEFAULT 0,
                last_run TEXT,
                next_run TEXT,
                run_count INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                last_result TEXT,
                timeout_seconds INTEGER DEFAULT 300,
                retry_on_fail INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE scheduler_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                duration_seconds REAL,
                result TEXT,
                output TEXT,
                error TEXT,
                triggered_by TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO scheduler_jobs (id, name, description, job_type, schedule, command, is_active)
            VALUES (1, ?, ?, ?, ?, ?, ?)
            """,
            ("scanner", "Scannt Aufgaben", "interval", "60m", "bach scan run", 1),
        )
        conn.execute(
            """
            INSERT INTO scheduler_runs (
                job_id, started_at, finished_at, duration_seconds, result, triggered_by
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (1, "2026-05-09T11:00:00", "2026-05-09T11:00:05", 5.0, "success", "manual"),
        )

    success, message = SchedulerHandler(base).handle("status", ["--json"])

    assert success is True
    payload = json.loads(message)
    assert payload["jobs"]["active"] == 1
    assert payload["recent_runs"][0]["name"] == "scanner"
    assert payload["recent_runs"][0]["result"] == "success"


def test_wiki_provenance_shows_article_metadata(tmp_path):
    from hub.wiki import WikiHandler

    base = _init_base(tmp_path)
    wiki_dir = base / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "steuer.txt").write_text(
        "Steuer-Wissen\nIBAN und Steuerdaten nie öffentlich teilen.",
        encoding="utf-8",
    )

    success, message = WikiHandler(base).handle("provenance", ["steuer"])

    assert success is True
    assert "WIKI PROVENANCE" in message
    assert "steuer.txt" in message
    assert "Wiki-Artikel" in message
    assert "sensibel" in message


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


def test_maintain_docs_report_forwards_explicit_subcommand(tmp_path, monkeypatch):
    from hub.maintain import MaintainHandler

    base = _init_base(tmp_path)
    tools_dir = base / "tools"
    tools_dir.mkdir()
    (tools_dir / "doc_update_checker.py").write_text("print('stub')\n", encoding="utf-8")

    captured = {}

    class DummyResult:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs["cwd"]
        return DummyResult()

    monkeypatch.setattr("hub.maintain.subprocess.run", fake_run)

    success, message = MaintainHandler(base).handle("docs", ["report"])

    assert success is True
    assert message == "ok"
    assert captured["cmd"][2:] == ["report"]
    assert captured["cwd"] == str(base)


def test_maintain_docs_defaults_to_check_for_flag_only_args(tmp_path, monkeypatch):
    from hub.maintain import MaintainHandler

    base = _init_base(tmp_path)
    tools_dir = base / "tools"
    tools_dir.mkdir()
    (tools_dir / "doc_update_checker.py").write_text("print('stub')\n", encoding="utf-8")

    captured = {}

    class DummyResult:
        returncode = 0
        stdout = "json"
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return DummyResult()

    monkeypatch.setattr("hub.maintain.subprocess.run", fake_run)

    success, message = MaintainHandler(base).handle("docs", ["--json"])

    assert success is True
    assert message == "json"
    assert captured["cmd"][2:] == ["check", "--json"]
