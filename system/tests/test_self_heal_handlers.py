# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Regression tests for small BACH self-heal handler fixes."""

import json
import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path


SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))


def _init_base(tmp_path):
    base = tmp_path / "system"
    (base / "data").mkdir(parents=True)
    return base


def _init_agent_runtime_tables(base: Path, name: str = "demo-agent"):
    db_path = base / "data" / "bach.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE agent_instances (
                name TEXT PRIMARY KEY,
                agent_type TEXT NOT NULL,
                capabilities TEXT,
                config TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT,
                last_used TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO agent_instances (
                name, agent_type, capabilities, config, is_active, created_at
            ) VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (name, "boss", "[]", "{}", 1),
        )


def _write_runtime_agent(base: Path, stem: str, message: str) -> Path:
    agents_dir = base / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    module_path = agents_dir / f"{stem}_agent.py"
    class_name = ''.join(part.capitalize() for part in stem.split('_')) + "Agent"
    module_path.write_text(
        (
            f"class {class_name}:\n"
            f"    def __init__(self, config):\n"
            f"        self.config = config\n"
            f"    def connect(self):\n"
            f"        return True\n"
            f"    def disconnect(self):\n"
            f"        return True\n"
            f"    def execute(self, operation, args):\n"
            f"        return True, {message!r}\n"
        ),
        encoding="utf-8",
    )
    return module_path


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
    assert payload["agents"][0]["available_actions"] == ["start"]


def test_agent_start_json_dry_run_is_machine_readable(tmp_path):
    from hub.agent_launcher import AgentLauncherHandler

    base = _init_base(tmp_path)
    agent_dir = base / "agents" / "demo"
    agent_dir.mkdir(parents=True)
    (agent_dir / "SKILL.md").write_text("# Demo\n", encoding="utf-8")

    success, message = AgentLauncherHandler(base).handle(
        "start",
        ["demo", "--mode", "plan", "--model", "opus", "--json"],
        dry_run=True,
    )

    assert success is True
    payload = json.loads(message)
    assert payload["action"] == "start"
    assert payload["requested_name"] == "demo"
    assert payload["resolved_name"] == "demo"
    assert payload["ok"] is True
    assert payload["agent"]["status"] == "planned"
    assert payload["agent"]["mode"] == "plan"
    assert payload["agent"]["model"] == "opus"
    assert payload["agent"]["available_actions"] == ["start"]
    assert payload["agent"]["dry_run"] is True


def test_agent_start_json_success_payload(tmp_path, monkeypatch):
    from hub.agent_launcher import AgentLauncherHandler

    base = _init_base(tmp_path)
    agent_dir = base / "agents" / "demo"
    agent_dir.mkdir(parents=True)
    (agent_dir / "SKILL.md").write_text("# Demo\n", encoding="utf-8")

    class FakeProc:
        pid = 4242

    monkeypatch.setattr("hub.agent_launcher.sys.platform", "linux")
    monkeypatch.setattr("hub.agent_launcher.subprocess.Popen", lambda *args, **kwargs: FakeProc())

    success, message = AgentLauncherHandler(base).handle("start", ["demo", "--json"])

    assert success is True
    payload = json.loads(message)
    assert payload["action"] == "start"
    assert payload["ok"] is True
    assert payload["agent"]["running"] is True
    assert payload["agent"]["status"] == "running"
    assert payload["agent"]["pid"] == 4242
    assert payload["agent"]["available_actions"] == ["stop", "steer"]
    assert (base / "data" / "agent_pids" / "demo.pid").exists()


def test_agent_stop_json_success_payload(tmp_path, monkeypatch):
    from hub.agent_launcher import AgentLauncherHandler

    base = _init_base(tmp_path)
    pid_dir = base / "data" / "agent_pids"
    pid_dir.mkdir(parents=True)
    pid_file = pid_dir / "demo.pid"
    pid_file.write_text(
        json.dumps(
            {
                "pid": 4242,
                "name": "demo",
                "display_name": "Demo",
                "type": "boss",
                "model": "sonnet",
                "mode": "default",
                "started": "2026-05-16T12:30:00",
                "temp_dir": str(base / "data" / "temp" / "agent_demo"),
                "window_title": "BACH: Demo",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    killed = {}

    def fake_kill(pid, sig):
        killed["pid"] = pid
        killed["sig"] = sig

    monkeypatch.setattr("hub.agent_launcher.sys.platform", "linux")
    monkeypatch.setattr("hub.agent_launcher.os.kill", fake_kill)

    success, message = AgentLauncherHandler(base).handle("stop", ["demo", "--json"])

    assert success is True
    payload = json.loads(message)
    assert payload["action"] == "stop"
    assert payload["requested_name"] == "demo"
    assert payload["resolved_name"] == "demo"
    assert payload["ok"] is True
    assert payload["agent"]["status"] == "stopped"
    assert payload["agent"]["pid"] == 4242
    assert payload["agent"]["available_actions"] == ["start"]
    assert killed["pid"] == 4242
    assert not pid_file.exists()


def test_agent_doctor_json_flags_missing_claude_cli(tmp_path, monkeypatch):
    from hub.agent_launcher import AgentLauncherHandler

    base = _init_base(tmp_path)
    agent_dir = base / "agents" / "demo"
    agent_dir.mkdir(parents=True)
    (agent_dir / "SKILL.md").write_text("# Demo\n", encoding="utf-8")

    monkeypatch.setattr("hub.agent_launcher.shutil.which", lambda _cmd: None)

    success, message = AgentLauncherHandler(base).handle("doctor", ["demo", "--json"])

    assert success is True
    payload = json.loads(message)
    checks = {check["name"]: check for check in payload["checks"]}

    assert payload["requested_name"] == "demo"
    assert payload["resolved_name"] == "demo"
    assert payload["summary"]["overall_status"] == "error"
    assert payload["summary"]["ready"] is False
    assert payload["summary"]["can_start"] is False
    assert checks["claude_cli"]["status"] == "error"
    assert checks["agent_exists"]["status"] == "ok"
    assert any("Claude Code CLI installieren" in step for step in payload["next_steps"])


def test_agent_doctor_json_reports_ready_agent_and_start_steps(tmp_path, monkeypatch):
    from hub.agent_launcher import AgentLauncherHandler

    base = _init_base(tmp_path)
    agent_dir = base / "agents" / "demo"
    agent_dir.mkdir(parents=True)
    (agent_dir / "SKILL.md").write_text("# Demo\n", encoding="utf-8")

    class FakeCompletedProcess:
        returncode = 0
        stdout = "Claude Code 1.2.3\n"
        stderr = ""

    monkeypatch.setattr("hub.agent_launcher.shutil.which", lambda _cmd: "C:/Tools/claude.cmd")
    monkeypatch.setattr("hub.agent_launcher.subprocess.run", lambda *args, **kwargs: FakeCompletedProcess())

    success, message = AgentLauncherHandler(base).handle("doctor", ["demo", "--json"])

    assert success is True
    payload = json.loads(message)
    checks = {check["name"]: check for check in payload["checks"]}

    assert payload["summary"]["overall_status"] == "ok"
    assert payload["summary"]["ready"] is True
    assert payload["summary"]["can_start"] is True
    assert checks["claude_cli"]["status"] == "ok"
    assert checks["claude_cli"]["details"]["version"] == "Claude Code 1.2.3"
    assert checks["skill_file"]["status"] == "ok"
    assert any("bach agent start demo --dry-run" in step for step in payload["next_steps"])
    assert any("bach agent start demo" in step for step in payload["next_steps"])


def test_startup_resource_summary_uses_current_layout_and_db_counts(tmp_path):
    from hub.startup import StartupHandler

    base = _init_base(tmp_path)
    (base / "skills" / "workflows").mkdir(parents=True)
    (base / "skills" / "workflows" / "daily-check.md").write_text("# workflow\n", encoding="utf-8")
    (base / "skills" / "workflows" / "_archive").mkdir()
    (base / "skills" / "workflows" / "_archive" / "weekly.md").write_text("# archived\n", encoding="utf-8")
    (base / "docs" / "help").mkdir(parents=True)
    (base / "docs" / "help" / "agent.txt").write_text("help\n", encoding="utf-8")
    (base / "docs" / "help" / "startup.txt").write_text("help\n", encoding="utf-8")

    db_path = base / "data" / "bach.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE bach_agents (id INTEGER PRIMARY KEY, is_active INTEGER DEFAULT 1)")
        conn.execute("CREATE TABLE bach_experts (id INTEGER PRIMARY KEY, is_active INTEGER DEFAULT 1)")
        conn.execute("CREATE TABLE skills (id INTEGER PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE tools (id INTEGER PRIMARY KEY, is_available INTEGER DEFAULT 1)"
        )
        conn.executemany("INSERT INTO bach_agents (is_active) VALUES (?)", [(1,), (1,)])
        conn.executemany("INSERT INTO bach_experts (is_active) VALUES (?)", [(1,), (0,), (1,)])
        conn.executemany("INSERT INTO skills DEFAULT VALUES", [(), (), (), ()])
        conn.executemany(
            "INSERT INTO tools (is_available) VALUES (?)",
            [(1,), (0,), (1,)],
        )

    counts = StartupHandler(base)._count_startup_resources()

    assert counts == {
        "agents": 4,
        "workflows": 1,
        "skills": 4,
        "tools": 2,
        "help": 2,
    }


def test_path_handler_json_uses_runtime_base_path(tmp_path):
    from hub.path import PathHandler

    base = _init_base(tmp_path)
    db_path = base / "data" / "bach.db"
    db_path.touch()

    success, message = PathHandler(base).handle("db", ["--json"])

    assert success is True
    payload = json.loads(message)
    assert payload["name"] == "db"
    assert Path(payload["path"]) == db_path.resolve()
    assert payload["source"] == "default"
    assert payload["exists"] is True


def test_path_handler_set_and_report_overrides_via_canonical_db(tmp_path):
    from hub.path import PathHandler

    base = _init_base(tmp_path)
    override_path = base / "custom wiki"

    success, _ = PathHandler(base).handle("set", ["wissensdatenbank", str(override_path)])
    assert success is True

    success, message = PathHandler(base).handle("overrides", ["--json"])

    assert success is True
    payload = json.loads(message)
    assert payload["count"] == 1
    assert payload["overrides"][0]["name"] == "wissensdatenbank"
    assert payload["overrides"][0]["path"] == str(override_path)

    with sqlite3.connect(base / "data" / "bach.db") as conn:
        stored = conn.execute(
            "SELECT value FROM system_config WHERE key = 'path.wissensdatenbank'"
        ).fetchone()

    assert stored == (str(override_path),)


def test_path_handler_resolve_supports_repo_root_json(tmp_path):
    from hub.path import PathHandler

    base = _init_base(tmp_path)

    success, message = PathHandler(base).handle(
        "resolve",
        ["docs/README.md", "--from-root", "--json"],
    )

    assert success is True
    payload = json.loads(message)
    assert payload["from_root"] is True
    assert Path(payload["resolved_path"]) == (base.parent / "docs" / "README.md").resolve()


def test_agent_start_uses_long_lived_windows_console_pid(tmp_path, monkeypatch):
    from hub.agent_launcher import AgentLauncherHandler

    base = _init_base(tmp_path)
    agent_dir = base / "agents" / "demo"
    agent_dir.mkdir(parents=True)
    (agent_dir / "SKILL.md").write_text("# Demo\n", encoding="utf-8")

    class FakeProc:
        pid = 4321

    calls = {}

    def fake_popen(cmd, cwd=None, creationflags=0, **kwargs):
        calls["cmd"] = cmd
        calls["cwd"] = cwd
        calls["creationflags"] = creationflags
        return FakeProc()

    monkeypatch.setattr("hub.agent_launcher.sys.platform", "win32")
    monkeypatch.setattr("hub.agent_launcher.subprocess.Popen", fake_popen)
    monkeypatch.setattr("hub.agent_launcher.subprocess.CREATE_NEW_CONSOLE", subprocess.CREATE_NEW_CONSOLE)

    success, message = AgentLauncherHandler(base).handle("start", ["demo"])

    assert success is True
    assert "PID:    4321" in message
    assert calls["cmd"][0:2] == ["cmd", "/c"]
    assert calls["cmd"][2].endswith("start.bat")
    assert calls["creationflags"] == subprocess.CREATE_NEW_CONSOLE

    pid_file = base / "data" / "agent_pids" / "demo.pid"
    payload = json.loads(pid_file.read_text(encoding="utf-8"))
    assert payload["pid"] == 4321
    assert payload["window_title"] == "BACH: demo"


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
    assert payload["service"]["available_actions"] == ["start"]
    assert payload["recent_runs"][0]["name"] == "scanner"
    assert payload["recent_runs"][0]["result"] == "success"


def test_scheduler_status_json_reports_operator_control_snapshot(tmp_path):
    from hub.scheduler import SchedulerHandler

    base = _init_base(tmp_path)
    gui_dir = base / "gui"
    gui_dir.mkdir(parents=True)
    (gui_dir / "daemon_service.py").write_text("# daemon\n", encoding="utf-8")

    control_dir = base / "data" / "scheduler_control"
    control_dir.mkdir(parents=True)
    (control_dir / "scheduler.pause.json").write_text(
        json.dumps(
            {"reason": "Wartung", "requested_at": "2026-05-20T12:30:00"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (control_dir / "scheduler.steer.json").write_text(
        json.dumps(
            [{"message": "Bitte nur Health-Checks fahren.", "requested_at": "2026-05-20T12:31:00"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    success, message = SchedulerHandler(base).handle("status", ["--json"])

    assert success is True
    payload = json.loads(message)
    assert payload["service"]["control_actions"] == ["pause", "resume", "steer", "clear-steer"]
    assert payload["operator_control"]["pause_requested"] is True
    assert payload["operator_control"]["pause_reason"] == "Wartung"
    assert payload["operator_control"]["pending_steer_count"] == 1
    assert payload["operator_control"]["latest_steer_message"] == "Bitte nur Health-Checks fahren."
    assert payload["operator_control"]["available_actions"] == ["resume", "steer", "clear-steer"]


def test_scheduler_doctor_json_cleans_stale_pid_and_reports_db_counts(tmp_path):
    from hub.scheduler import SchedulerHandler

    base = _init_base(tmp_path)
    gui_dir = base / "gui"
    gui_dir.mkdir(parents=True)
    (gui_dir / "daemon_service.py").write_text("# daemon\n", encoding="utf-8")

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

    pid_file = base / "data" / "daemon.pid"
    pid_file.write_text("43210", encoding="utf-8")

    success, message = SchedulerHandler(base).handle("doctor", ["--json"])

    assert success is True
    payload = json.loads(message)
    checks = {check["name"]: check for check in payload["checks"]}

    assert payload["summary"]["overall_status"] == "warn"
    assert payload["summary"]["ready"] is True
    assert payload["summary"]["can_start"] is True
    assert checks["runtime_state"]["status"] == "warn"
    assert checks["runtime_state"]["details"]["previous_pid"] == 43210
    assert checks["database"]["status"] == "ok"
    assert checks["database"]["details"]["jobs_active"] == 1
    assert not pid_file.exists()
    assert any("bach scheduler start --bg" in step for step in payload["next_steps"])


def test_scheduler_session_doctor_json_reports_ready_profiled_service(tmp_path):
    from hub.scheduler import SchedulerHandler

    base = _init_base(tmp_path)
    session_dir = base / "hub" / "_services" / "daemon"
    profiles_dir = session_dir / "profiles"
    profiles_dir.mkdir(parents=True)
    (session_dir / "session_daemon.py").write_text("# daemon\n", encoding="utf-8")
    (session_dir / "auto_session.py").write_text("# trigger\n", encoding="utf-8")
    (session_dir / "config.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "quiet_start": "22:00",
                "quiet_end": "08:00",
                "jobs": [{"profile": "ati", "interval_minutes": 30, "enabled": True}],
            }
        ),
        encoding="utf-8",
    )
    (profiles_dir / "ati.json").write_text("{}", encoding="utf-8")

    success, message = SchedulerHandler(base).handle("session", ["doctor", "--json"])

    assert success is True
    payload = json.loads(message)
    checks = {check["name"]: check for check in payload["checks"]}

    assert payload["summary"]["overall_status"] == "ok"
    assert payload["summary"]["ready"] is True
    assert payload["summary"]["can_start"] is True
    assert checks["script"]["status"] == "ok"
    assert checks["config"]["status"] == "ok"
    assert checks["profiles"]["status"] == "ok"
    assert any("bach scheduler session start --profile ati" in step for step in payload["next_steps"])


def test_scheduler_session_pause_resume_and_steer_status_json(tmp_path):
    from hub.scheduler import SchedulerHandler

    base = _init_base(tmp_path)
    session_dir = base / "hub" / "_services" / "daemon"
    profiles_dir = session_dir / "profiles"
    profiles_dir.mkdir(parents=True)
    (session_dir / "session_daemon.py").write_text("# daemon\n", encoding="utf-8")
    (session_dir / "auto_session.py").write_text("# trigger\n", encoding="utf-8")
    (session_dir / "config.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "quiet_start": "22:00",
                "quiet_end": "08:00",
                "jobs": [{"profile": "ati", "interval_minutes": 30, "enabled": True}],
            }
        ),
        encoding="utf-8",
    )
    (profiles_dir / "ati.json").write_text("{}", encoding="utf-8")

    handler = SchedulerHandler(base)

    success, message = handler.handle("session", ["pause", "--profile", "ati", "Maintenance window"])
    assert success is True
    assert "pausiert" in message

    success, message = handler.handle("session", ["steer", "--profile", "ati", "Bitte zuerst Docs pruefen"])
    assert success is True
    assert "vorgemerkt" in message

    success, message = handler.handle("session", ["status", "--json"])
    assert success is True
    payload = json.loads(message)
    control = next(item for item in payload["operator_controls"] if item["profile"] == "ati")
    assert control["pause_requested"] is True
    assert control["pause_reason"] == "Maintenance window"
    assert control["pending_steer_count"] == 1
    assert "Docs pruefen" in control["latest_steer_message"]

    success, message = handler.handle("session", ["resume", "--profile", "ati"])
    assert success is True
    assert "aufgehoben" in message

    success, message = handler.handle("session", ["status", "--json"])
    assert success is True
    payload = json.loads(message)
    control = next(item for item in payload["operator_controls"] if item["profile"] == "ati")
    assert control["pause_requested"] is False
    assert control["pending_steer_count"] == 1


def test_auto_session_prompt_includes_operator_steer_section(monkeypatch):
    module_path = SYSTEM_ROOT / "hub" / "_services" / "daemon" / "auto_session.py"
    spec = importlib.util.spec_from_file_location("bach_auto_session_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    monkeypatch.setenv(
        "BACH_SESSION_OPERATOR_STEER",
        json.dumps([{"message": "Priorisiere zuerst die Roadmap.", "requested_at": "2026-05-16T12:00:00"}]),
    )
    steer = module.load_operator_steer()
    prompt = module.create_prompt({"name": "ati", "timeout_minutes": 15}, operator_steer=steer)

    assert len(steer) == 1
    assert "Operator-Hinweise fuer diese Session" in prompt
    assert "Priorisiere zuerst die Roadmap." in prompt


def test_scheduler_session_status_json_lists_control_actions(tmp_path):
    from hub.scheduler import SchedulerHandler

    base = _init_base(tmp_path)
    session_dir = base / "hub" / "_services" / "daemon"
    profiles_dir = session_dir / "profiles"
    profiles_dir.mkdir(parents=True)
    (session_dir / "config.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "jobs": [{"profile": "ati", "interval_minutes": 30, "enabled": True}],
            }
        ),
        encoding="utf-8",
    )
    (profiles_dir / "ati.json").write_text("{}", encoding="utf-8")
    control_dir = session_dir / "control"
    control_dir.mkdir(parents=True)
    (control_dir / "ati.steer.json").write_text(
        json.dumps(
            [
                {
                    "profile": "ati",
                    "message": "Bitte nur Health-Checks anfassen.",
                    "requested_at": "2026-05-16T12:40:00",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    success, message = SchedulerHandler(base).handle("session", ["status", "--json"])

    assert success is True
    payload = json.loads(message)
    assert payload["service"]["control_actions"] == ["pause", "resume", "steer", "clear-steer"]
    assert payload["operator_controls"][0]["profile"] == "ati"
    assert payload["operator_controls"][0]["pending_steer_count"] == 1
    assert payload["operator_controls"][0]["latest_steer_message"] == "Bitte nur Health-Checks anfassen."
    assert payload["operator_controls"][0]["latest_steer_requested_at"] == "2026-05-16T12:40:00"
    assert payload["operator_controls"][0]["available_actions"] == ["pause", "steer", "clear-steer"]


def test_scheduler_session_clear_steer_deletes_profile_queue(tmp_path):
    from hub.scheduler import SchedulerHandler

    base = _init_base(tmp_path)
    session_dir = base / "hub" / "_services" / "daemon"
    control_dir = session_dir / "control"
    control_dir.mkdir(parents=True)
    steer_file = control_dir / "ati.steer.json"
    steer_file.write_text(
        json.dumps(
            [
                {
                    "profile": "ati",
                    "message": "Doku zuerst pruefen.",
                    "requested_at": "2026-05-16T12:41:00",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    success, message = SchedulerHandler(base).handle("session", ["clear-steer", "--profile", "ati"])

    assert success is True
    assert "1 Session-Steering-Hinweis(e)" in message
    assert not steer_file.exists()


def test_scheduler_session_steer_json_response_exposes_control_snapshot(tmp_path):
    from hub.scheduler import SchedulerHandler

    base = _init_base(tmp_path)
    success, message = SchedulerHandler(base).handle(
        "session",
        ["steer", "--profile", "ati", "Bitte", "Logs", "--json"],
    )

    assert success is True
    payload = json.loads(message)
    assert payload["action"] == "steer"
    assert payload["control"]["profile"] == "ati"
    assert payload["control"]["pending_steer_count"] == 1
    assert payload["control"]["latest_steer_message"] == "Bitte Logs"
    assert payload["control"]["latest_steer_requested_at"] is not None
    assert payload["control"]["available_actions"] == ["pause", "steer", "clear-steer"]


def test_scheduler_session_trigger_keeps_steer_queue_on_failure(tmp_path, monkeypatch):
    from hub.scheduler import SchedulerHandler

    base = _init_base(tmp_path)
    session_dir = base / "hub" / "_services" / "daemon"
    control_dir = session_dir / "control"
    control_dir.mkdir(parents=True)
    (session_dir / "auto_session.py").write_text("# auto session\n", encoding="utf-8")
    steer_file = control_dir / "ati.steer.json"
    steer_file.write_text(
        json.dumps(
            [
                {
                    "profile": "ati",
                    "message": "Bitte Logs zuerst lesen.",
                    "requested_at": "2026-05-16T12:42:00",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class _Result:
        returncode = 1
        stdout = ""
        stderr = "kaputt"

    def fake_run(*args, **kwargs):
        return _Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    success, message = SchedulerHandler(base).handle("session", ["trigger", "--profile", "ati"])

    assert success is False
    assert steer_file.exists()
    payload = json.loads(steer_file.read_text(encoding="utf-8"))
    assert payload[0]["message"] == "Bitte Logs zuerst lesen."
    assert "Session-Trigger fehlgeschlagen" in message


def test_upgrade_handler_routes_extended_categories(tmp_path, monkeypatch):
    from hub.upgrade import UpgradeHandler

    base = _init_base(tmp_path)
    db_path = base / "data" / "bach.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE dist_file_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT,
                version TEXT,
                file_hash TEXT,
                dist_type INTEGER,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE distribution_releases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT,
                release_date TEXT,
                status TEXT,
                is_stable INTEGER DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE distribution_manifest (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT,
                dist_type INTEGER
            )
            """
        )

    calls = []

    def fake_restore_by_category(self, category, dry_run=False):
        calls.append((category, dry_run))
        return True, f"restored:{category}:{dry_run}"

    monkeypatch.setattr("hub.restore.RestoreHandler.restore_by_category", fake_restore_by_category)

    success, message = UpgradeHandler(base).handle("agents", ["--dry-run"])
    assert success is True
    assert message == "restored:agents:True"

    success, message = UpgradeHandler(base).handle("docs", [])
    assert success is True
    assert message == "restored:docs:False"

    success, message = UpgradeHandler(base).handle("connectors", ["--dry-run"])
    assert success is True
    assert message == "restored:connectors:True"

    success, message = UpgradeHandler(base).handle("partners", [])
    assert success is True
    assert message == "restored:partners:False"

    success, message = UpgradeHandler(base).handle("gui", ["--dry-run"])
    assert success is True
    assert message == "restored:gui:True"

    assert calls == [
        ("agents", True),
        ("docs", False),
        ("connectors", True),
        ("partners", False),
        ("gui", True),
    ]


def test_restore_by_category_returns_info_when_manifest_is_empty(tmp_path):
    from hub.restore import RestoreHandler

    bach_root = tmp_path / "bach"
    system_root = bach_root / "system"
    data_dir = system_root / "data"
    data_dir.mkdir(parents=True)

    db_path = data_dir / "bach.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE distribution_manifest (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT,
                dist_type INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE dist_file_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT,
                version TEXT,
                file_hash TEXT,
                dist_type INTEGER,
                created_at TEXT
            )
            """
        )

    success, message = RestoreHandler(bach_root).restore_by_category("docs", dry_run=True)

    assert success is True
    assert "Keine Dateien gefunden" in message


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


def test_usecase_run_accepts_legacy_plain_text_payloads(tmp_path):
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
                "Irregulaere Kosten Vorschau",
                "system-synopse",
                "Benutzer fragt nach kommenden Kosten",
                "Liste erwarteter Zahlungen mit Datum und Betrag",
                "user",
            ),
        )

    success, message = UsecaseHandler(base).handle("run", ["1"])

    assert success is True
    assert "Benutzer fragt nach kommenden Kosten" in message
    assert "Liste erwarteter Zahlungen mit Datum und Betrag" in message

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


def test_agent_runtime_registry_is_scoped_per_base_path(tmp_path):
    from core.agent_runtime import clear_registry_cache, get_agent

    clear_registry_cache()
    base_a = _init_base(tmp_path / "a")
    base_b = _init_base(tmp_path / "b")
    _init_agent_runtime_tables(base_a)
    _init_agent_runtime_tables(base_b)
    _write_runtime_agent(base_a, "demo", "alpha")
    _write_runtime_agent(base_b, "demo", "beta")

    agent_a = get_agent("demo-agent", base_a)
    agent_b = get_agent("demo-agent", base_b)

    assert agent_a is not None
    assert agent_b is not None
    assert agent_a.execute("status", [])[1] == "alpha"
    assert agent_b.execute("status", [])[1] == "beta"


def test_agent_runtime_invalidates_cached_module_after_code_change(tmp_path):
    from core.agent_runtime import AgentRegistry

    base = _init_base(tmp_path)
    _init_agent_runtime_tables(base)
    module_path = _write_runtime_agent(base, "demo", "version-1")

    registry = AgentRegistry(base)
    first = registry.get("demo-agent")

    assert first is not None
    assert first.execute("status", [])[1] == "version-1"

    module_path.write_text(
        (
            "class DemoAgent:\n"
            "    def __init__(self, config):\n"
            "        self.config = config\n"
            "    def connect(self):\n"
            "        return True\n"
            "    def disconnect(self):\n"
            "        return True\n"
            "    def execute(self, operation, args):\n"
            "        return True, 'version-2-reloaded'\n"
        ),
        encoding="utf-8",
    )

    second = registry.get("demo-agent")

    assert second is not None
    assert second is not first
    assert second.execute("status", [])[1] == "version-2-reloaded"


def test_financial_mail_paths_follow_hub_services_layout():
    import gui.server as gui_server

    profile_path = SYSTEM_ROOT / "hub" / "_services" / "daemon" / "profiles" / "financial_mail.json"
    chain_path = SYSTEM_ROOT / "tools" / "llmauto" / "chains" / "session_financial_mail.json"
    skill_path = SYSTEM_ROOT / "hub" / "_services" / "financial" / "SKILL.md"

    profile_payload = json.loads(profile_path.read_text(encoding="utf-8"))
    chain_payload = json.loads(chain_path.read_text(encoding="utf-8"))
    skill_text = skill_path.read_text(encoding="utf-8")

    assert profile_payload["script_path"] == "hub/_services/mail/mail_service.py"
    assert "python hub/_services/mail/mail_service.py sync" in chain_payload["prompts"]["financial_mail_worker"]
    assert "hub/_services/mail/schema_financial.sql" in skill_text
    assert str(gui_server.FINANCIAL_SCHEMA_FILE).endswith("hub\\_services\\mail\\schema_financial.sql")


def test_doc_update_checker_scans_help_and_current_layout_paths(tmp_path):
    from tools.doc_update_checker import DocUpdateChecker

    base = _init_base(tmp_path)
    help_dir = base / "docs" / "help"
    help_dir.mkdir(parents=True, exist_ok=True)
    (base / "hub").mkdir(parents=True, exist_ok=True)
    (base / "hub" / "startup.py").write_text("def handle():\n    return True\n", encoding="utf-8")
    (base / "hub" / "_services" / "mail").mkdir(parents=True, exist_ok=True)

    help_doc = help_dir / "maintenance.txt"
    help_doc.write_text(
        (
            "Altpfad Service: skills/_services/mail/mail_service.py\n"
            "Altpfad Handler: hub/handlers/startup.py\n"
        ),
        encoding="utf-8",
    )

    checker = DocUpdateChecker(base_path=base)
    docs = checker._get_all_docs()

    scanned = next(item for item in docs if item["path"] == "docs/help/maintenance.txt")
    assert scanned["doc_type"] == "help"

    results = checker.check_all()
    assert any(
        issue["invalid_path"] == "skills/_services/mail/" and issue["correct_path"] == "hub/_services/mail/"
        for issue in results["invalid_paths"]
    )
    assert any(
        issue["invalid_path"] == "hub/handlers/startup.py" and issue["correct_path"] == "hub/startup.py"
        for issue in results["invalid_paths"]
    )


def test_doc_update_checker_auto_fix_preserves_correct_hub_service_paths(tmp_path):
    from tools.doc_update_checker import DocUpdateChecker

    base = _init_base(tmp_path)
    docs_dir = base / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (base / "hub").mkdir(parents=True, exist_ok=True)
    (base / "hub" / "startup.py").write_text("def handle():\n    return True\n", encoding="utf-8")
    (base / "hub" / "_services" / "mail").mkdir(parents=True, exist_ok=True)

    doc_file = docs_dir / "paths.md"
    doc_file.write_text(
        (
            "Alt: skills/_services/mail/mail_service.py\n"
            "Schon korrekt: hub/_services/mail/mail_service.py\n"
            "Alt-Handler: handlers/startup.py\n"
        ),
        encoding="utf-8",
    )

    checker = DocUpdateChecker(base_path=base)
    fixed = checker.auto_fix_paths(dry_run=False)
    updated = doc_file.read_text(encoding="utf-8")

    assert any(item["path"] == "docs/paths.md" for item in fixed)
    assert "skills/_services/mail/" not in updated
    assert "hub/_services/mail/mail_service.py" in updated
    assert "hub/startup.py" in updated
    assert "hub/hub/_services" not in updated


def test_agent_steer_creates_operator_note_and_status_json_reports_queue(tmp_path, monkeypatch):
    from hub.agent_launcher import AgentLauncherHandler

    base = _init_base(tmp_path)
    agent_dir = base / "agents" / "demo"
    agent_dir.mkdir(parents=True)
    (agent_dir / "SKILL.md").write_text("# Demo\n", encoding="utf-8")

    temp_dir = base / "data" / "temp" / "agent_demo"
    temp_dir.mkdir(parents=True)
    pid_dir = base / "data" / "agent_pids"
    pid_dir.mkdir(parents=True)
    pid_file = pid_dir / "demo.pid"
    pid_file.write_text(
        json.dumps(
            {
                "pid": 4242,
                "name": "demo",
                "display_name": "Demo",
                "type": "boss",
                "model": "sonnet",
                "mode": "default",
                "started": "2026-05-16T12:00:00",
                "temp_dir": str(temp_dir),
                "window_title": "BACH: Demo",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("hub.agent_launcher.AgentLauncherHandler._is_agent_running", lambda self, _name: 4242)

    handler = AgentLauncherHandler(base)
    success, message = handler.handle("steer", ["demo", "Bitte", "zuerst", "Logs", "pruefen"])

    assert success is True
    assert "vorgemerkt" in message

    notes_json = temp_dir / "operator_notes.json"
    notes_md = temp_dir / "OPERATOR_NOTES.md"
    notes = json.loads(notes_json.read_text(encoding="utf-8"))
    assert len(notes) == 1
    assert "Logs pruefen" in notes[0]["message"]
    assert "Logs pruefen" in notes_md.read_text(encoding="utf-8")

    success, message = handler.handle("status", ["--json"])
    assert success is True
    payload = json.loads(message)
    assert payload["active_count"] == 1
    agent = payload["agents"][0]
    assert agent["pending_operator_notes"] == 1
    assert agent["latest_operator_note"] == "Bitte zuerst Logs pruefen"
    assert agent["latest_operator_note_at"] is not None
    assert "steer" in agent["available_actions"]
    assert "clear-steer" in agent["available_actions"]

    success, message = handler.handle("clear-steer", ["demo"])
    assert success is True
    assert "gelöscht" in message
    assert not notes_json.exists()
    assert not notes_md.exists()

    success, message = handler.handle("status", ["--json"])
    assert success is True
    payload = json.loads(message)
    agent = payload["agents"][0]
    assert agent["pending_operator_notes"] == 0
    assert agent["latest_operator_note"] is None
    assert agent["latest_operator_note_at"] is None
    assert "steer" in agent["available_actions"]
    assert "clear-steer" not in agent["available_actions"]


def test_agent_clear_steer_deletes_operator_queue_and_updates_json(tmp_path, monkeypatch):
    from hub.agent_launcher import AgentLauncherHandler

    base = _init_base(tmp_path)
    agent_dir = base / "agents" / "demo"
    agent_dir.mkdir(parents=True)
    (agent_dir / "SKILL.md").write_text("# Demo\n", encoding="utf-8")

    temp_dir = base / "data" / "temp" / "agent_demo"
    temp_dir.mkdir(parents=True)
    pid_dir = base / "data" / "agent_pids"
    pid_dir.mkdir(parents=True)
    (pid_dir / "demo.pid").write_text(
        json.dumps(
            {
                "pid": 4242,
                "name": "demo",
                "display_name": "Demo",
                "type": "boss",
                "model": "sonnet",
                "mode": "default",
                "started": "2026-05-16T12:00:00",
                "temp_dir": str(temp_dir),
                "window_title": "BACH: Demo",
            }
        ),
        encoding="utf-8",
    )
    (temp_dir / "operator_notes.json").write_text(
        json.dumps(
            [
                {
                    "message": "Bitte zuerst Logs pruefen",
                    "requested_at": "2026-05-16T12:20:00",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (temp_dir / "OPERATOR_NOTES.md").write_text("# Operator Notes\n", encoding="utf-8")

    monkeypatch.setattr("hub.agent_launcher.AgentLauncherHandler._is_agent_running", lambda self, _name: 4242)

    handler = AgentLauncherHandler(base)
    success, message = handler.handle("clear-steer", ["demo", "--json"])

    assert success is True
    payload = json.loads(message)
    assert payload["action"] == "clear-steer"
    assert payload["agent"]["pending_operator_notes"] == 0
    assert payload["agent"]["latest_operator_note"] is None
    assert "clear-steer" not in payload["agent"]["available_actions"]
    assert not (temp_dir / "operator_notes.json").exists()
    assert not (temp_dir / "OPERATOR_NOTES.md").exists()
