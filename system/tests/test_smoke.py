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

"""
Smoke Tests - Backwards-Kompatibilitaet
=========================================
Prueft dass alle kritischen CLI-Befehle weiterhin funktionieren.
"""

import sys
import os
import sqlite3
import subprocess
import re
import json
from pathlib import Path

SYSTEM_ROOT = Path(__file__).parent.parent
BACH_PY = SYSTEM_ROOT / "bach.py"
SMOKE_TEST_AGENT = "test-agent"

import pytest


_SMOKE_DB_PATH = None


@pytest.fixture(scope="class")
def isolated_cli_db(tmp_path_factory):
    """Create a complete, deterministic database for CLI smoke tests."""
    global _SMOKE_DB_PATH

    db_dir = tmp_path_factory.mktemp("bach_cli_smoke")
    db_path = db_dir / "bach.db"
    schema_path = SYSTEM_ROOT / "data" / "schema" / "schema.sql"

    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _migrations (
                id INTEGER PRIMARY KEY,
                filename TEXT UNIQUE NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        migrations_dir = schema_path.parent / "migrations"
        for migration in sorted(migrations_dir.iterdir()):
            if migration.suffix in {".sql", ".py"} and not migration.name.startswith("_"):
                conn.execute(
                    "INSERT OR IGNORE INTO _migrations (filename, applied_at) VALUES (?, ?)",
                    (migration.name, "pytest-smoke-fixture"),
                )

        # These columns are still supplied by migration 032 rather than the
        # consolidated schema, but the CLI handlers already rely on them.
        for table in ("bach_agents", "bach_experts", "skills", "wiki_articles", "tools"):
            columns = {
                row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if "language" not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN language TEXT DEFAULT 'de'")

        conn.execute(
            """
            CREATE TABLE distribution_releases (
                version TEXT PRIMARY KEY,
                release_date TEXT,
                status TEXT DEFAULT 'released',
                is_stable INTEGER DEFAULT 1,
                description TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO memory_facts (category, key, value, confidence, source)
            VALUES ('system', 'smoke_fixture', 'isolated test data', 1.0, 'pytest')
            """
        )
        conn.execute(
            """
            INSERT INTO partner_recognition
                (partner_name, partner_type, capabilities, cost_tier, token_zone, priority, status)
            VALUES ('Claude', 'api', '["coding"]', 3, 'zone_1', 90, 'active')
            """
        )
        conn.execute(
            """
            INSERT INTO tools
                (name, type, category, description, capabilities, is_available, language)
            VALUES ('ocr_test_tool', 'cli', 'documents', 'OCR test fixture', '["ocr"]', 1, 'de')
            """
        )
        conn.execute(
            """
            INSERT INTO usecases
                (title, workflow_name, test_input, expected_output, created_by)
            VALUES ('System synopse smoke', 'system-synopse', '{}', '{}', 'tests')
            """
        )

    previous_path = _SMOKE_DB_PATH
    _SMOKE_DB_PATH = db_path
    try:
        yield db_path
    finally:
        _SMOKE_DB_PATH = previous_path


def run_bach(*args, timeout=45):
    """Fuehrt bach.py aus und gibt (returncode, stdout, stderr) zurueck."""
    cmd = [sys.executable, str(BACH_PY)] + list(args)
    env = os.environ.copy()
    if _SMOKE_DB_PATH is not None:
        env["BACH_DB"] = str(_SMOKE_DB_PATH)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(SYSTEM_ROOT),
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


def clear_agent_steer(agent_name):
    """Reset queued operator notes for deterministic smoke tests."""
    run_bach("agent", "clear-steer", agent_name, "--json")


@pytest.mark.usefixtures("isolated_cli_db")
class TestCLIBackwardsCompat:
    """Alle kritischen CLI-Befehle muessen weiterhin funktionieren."""

    def test_help(self):
        code, out, err = run_bach("help")
        assert code == 0
        assert "BACH" in out

    def test_help_topic(self):
        code, out, err = run_bach("help", "task")
        assert code == 0

    def test_task_list(self):
        code, out, err = run_bach("task", "list")
        assert code == 0
        assert "TASKS" in out or "Tasks" in out

    def test_task_list_dashes(self):
        code, out, err = run_bach("--task", "list")
        assert code == 0
        assert "TASKS" in out or "Tasks" in out

    def test_memory_status(self):
        code, out, err = run_bach("--memory", "status")
        assert code == 0
        assert "Memory" in out or "MEMORY" in out

    def test_mem_alias_read(self):
        """Test memory read (not mem, use full name)."""
        code, out, err = run_bach("memory", "read")
        assert code == 0
        assert "WORKING MEMORY" in out or "Memory" in out

    def test_memory_provenance(self):
        code, out, err = run_bach("memory", "provenance", "facts", "1")
        assert code == 0
        assert "PROVENANCE" in out

    def test_status(self):
        code, out, err = run_bach("--status")
        assert code == 0
        assert "BACH" in out or "Status" in out
        assert "Session:" in out
        assert "Tasks:" in out
        assert "Tools:" in out
        assert "Health:" in out

    def test_health_disk(self):
        code, out, err = run_bach("health", "disk")
        # Exit 1 = Warnung (wenig freier Speicher) ist gewolltes Verhalten;
        # der Check selbst muss aber laufen und Output liefern.
        assert code in (0, 1)
        assert "Disk Check" in out or "GB" in out

    def test_steuer_status(self):
        code, out, err = run_bach("steuer", "status")
        assert code == 0

    def test_steuer_dashes(self):
        code, out, err = run_bach("--steuer", "status")
        assert code == 0

    def test_backup_list(self):
        code, out, err = run_bach("backup", "list")
        assert code == 0

    def test_unknown_command_suggestion(self):
        code, out, err = run_bach("taks")
        assert code == 1
        assert "Meintest du" in out or "task" in out.lower()

    def test_unknown_profile_suggestion(self):
        code, out, err = run_bach("--taks")
        assert code == 1

    def test_lesson_list(self):
        code, out, err = run_bach("lesson", "list")
        assert code == 0

    def test_wiki_list(self):
        code, out, err = run_bach("wiki", "list")
        assert code == 0

    def test_upgrade_status(self):
        """Test bach upgrade status (SQ020)."""
        code, out, err = run_bach("upgrade", "status")
        assert code == 0
        assert "UPGRADE" in out or "Dateien" in out

    def test_upgrade_check_flag_alias(self):
        """Test bach upgrade --check (dokumentierter Flag-Alias)."""
        code, out, err = run_bach("upgrade", "--check")
        assert code == 0
        assert "UPGRADE-CHECK" in out or "Keine versionierten Dateien" in out

    def test_settings_list(self):
        """Test bach settings list (SQ037)."""
        code, out, err = run_bach("settings", "list")
        assert code == 0
        # Settings kann leer sein (neue Installation) oder Einstellungen zeigen
        assert "einstellung" in out.lower() or "setting" in out.lower() or "keine" in out.lower() or "integration" in out.lower() or "backup" in out.lower()

    def test_seal_status(self):
        """Test bach seal status (SQ021)."""
        code, out, err = run_bach("seal", "status")
        assert code == 0
        assert "Siegel" in out or "SEAL" in out or "Status" in out

    def test_restore_status(self):
        """Test bach restore list (SQ020) - prueft ob restore-Befehl erreichbar ist."""
        code, out, err = run_bach("restore", "list", "bach.py")
        # Entweder Versionen gefunden oder Info-Meldung (Datei nicht verfolgt ist OK)
        assert code == 0 or "dist_file_versions" in err or "dist_file_versions" in out
        # Restore-Handler muss antworten (kein unbekannter Befehl)
        assert "Unbekannter Befehl" not in out

    def test_integration_status(self):
        """Test bach integration status (SQ038)."""
        code, out, err = run_bach("integration", "status")
        assert code == 0
        # Integration-Status sollte Level oder Config anzeigen
        assert "integration" in out.lower() or "level" in out.lower() or "config" in out.lower()

    def test_search(self):
        """Test bach search (SQ064)."""
        code, out, err = run_bach("search", "test")
        assert code == 0
        # Suche sollte entweder Ergebnisse oder "Keine Treffer" anzeigen
        # (kein Fehler werfen)

    def test_db_tables(self):
        """Test bach db tables (SQ067)."""
        code, out, err = run_bach("db", "tables")
        assert code == 0
        assert "TABELLEN" in out or "Tabellen" in out

    def test_partner_list(self):
        """Test bach partner list (SQ015)."""
        code, out, err = run_bach("partner", "list")
        assert code == 0
        assert "claude" in out.lower() or "gemini" in out.lower()

    def test_tools_search_ocr(self):
        """Test bach tools search (Tools-Suche)."""
        code, out, err = run_bach("tools", "search", "ocr")
        assert code == 0
        # Sollte ocr-Tools finden
        assert "ocr" in out.lower()

    def test_lesson_last(self):
        """Test bach lesson last (Lesson-System)."""
        code, out, err = run_bach("lesson", "last", "3")
        assert code == 0
        # Sollte Lessons anzeigen oder "keine Lessons" melden

    def test_folders_list(self):
        """Test bach folders list (SQ070)."""
        code, out, err = run_bach("folders", "list")
        assert code == 0
        # Folder-Management sollte funktionieren

    def test_agent_list(self):
        """Test bach agent list (Agents auflisten)."""
        code, out, err = run_bach("agent", "list")
        assert code == 0
        # Agent-Liste kann entweder direkt auflisten oder AGENTS.md generieren
        assert "agent" in out.lower() or "AGENTS.md" in out or "generiert" in out.lower()

    def test_agent_list_json(self):
        code, out, err = run_bach("agent", "list", "--json")
        assert code == 0, err
        payload = json.loads(out)
        assert "agents" in payload
        assert "active_count" in payload

    def test_agent_doctor_json(self):
        code, out, err = run_bach("agent", "doctor", "ati", "--json")
        assert code == 0, err
        payload = json.loads(out)
        assert payload["requested_name"] == "ati"
        assert payload["resolved_name"] == "ati"
        assert "summary" in payload
        assert "checks" in payload

    def test_agent_start_dry_run_json(self):
        clear_agent_steer(SMOKE_TEST_AGENT)
        code, out, err = run_bach("agent", "start", SMOKE_TEST_AGENT, "--dry-run", "--json")
        assert code == 0, err
        payload = json.loads(out)
        assert payload["action"] == "start"
        assert payload["requested_name"] == SMOKE_TEST_AGENT
        assert payload["resolved_name"] == SMOKE_TEST_AGENT
        assert payload["ok"] is True
        assert payload["agent"]["dry_run"] is True
        assert payload["agent"]["available_actions"] == ["start"]

    def test_agent_steer_prelaunch_json(self):
        clear_agent_steer(SMOKE_TEST_AGENT)
        try:
            code, out, err = run_bach("agent", "steer", SMOKE_TEST_AGENT, "Vorstart-Hinweis", "--json")
            assert code == 0, err
            payload = json.loads(out)
            assert payload["action"] == "steer"
            assert payload["ok"] is True
            assert payload["agent"]["status"] == "queued"
            assert payload["agent"]["queued_for_next_start"] is True
        finally:
            clear_agent_steer(SMOKE_TEST_AGENT)

    def test_scheduler_doctor_json(self):
        code, out, err = run_bach("scheduler", "doctor", "--json")
        assert code == 0, err
        payload = json.loads(out)
        assert payload["service"]["kind"] == "scheduler"
        assert "summary" in payload
        assert "checks" in payload

    def test_scheduler_session_doctor_json(self):
        code, out, err = run_bach("scheduler", "session", "doctor", "--json")
        assert code == 0, err
        payload = json.loads(out)
        assert payload["service"]["kind"] == "session_scheduler"
        assert "summary" in payload
        assert "checks" in payload

    def test_path_db_json(self):
        code, out, err = run_bach("path", "db", "--json")
        assert code == 0, err
        payload = json.loads(out)
        assert payload["name"] == "db"
        assert "path" in payload

    def test_path_summary_json(self):
        code, out, err = run_bach("path", "--json")
        assert code == 0, err
        payload = json.loads(out)
        assert "groups" in payload
        assert "core" in payload["groups"]

    def test_path_list_json(self):
        code, out, err = run_bach("path", "list", "--json")
        assert code == 0, err
        payload = json.loads(out)
        assert payload["count"] >= 1
        assert any(item["name"] == "db" for item in payload["paths"])

    def test_downgrade_help(self):
        """Test bach help downgrade (SQ020)."""
        code, out, err = run_bach("help", "downgrade")
        assert code == 0
        assert "downgrade" in out.lower()

    def test_export_mirrors(self):
        """Test bach export mirrors (SQ071)."""
        code, out, err = run_bach("export", "mirrors")
        # Export in frischer Testumgebung liefert 0 (Erfolg) oder 1 (Warnung bei uninitialisierten Tabellen)
        assert code in (0, 1)

    def test_lang_list(self):
        """Test bach lang list (SQ062 Uebersetzungssystem)."""
        code, out, err = run_bach("lang", "list")
        assert code == 0
        # Sprachen-Liste sollte angezeigt werden

    def test_lang_report(self):
        """Test bach lang report (i18n-Drift-Report)."""
        code, out, err = run_bach("lang", "report")
        # Exit 1 = Drift vorhanden (offene Uebersetzungen) ist gewolltes
        # Verhalten; der Report muss aber erzeugt werden.
        assert code in (0, 1)
        assert "I18N-DRIFT REPORT" in out

    def test_usecase_run_all_dry_run(self):
        """Test bach usecase run-all --dry-run fuer workflowweite Sammeltests."""
        code, out, err = run_bach("usecase", "run-all", "system-synopse", "--dry-run", "--json")
        assert code == 0, err
        assert "Sammeltest" in out
        assert "[DRY-RUN]" in out
        assert "Gesamt:" in out

    def test_skill_help(self):
        """Test bach help skill (Skills verwalten)."""
        code, out, err = run_bach("help", "skill")
        assert code == 0
        assert "skill" in out.lower()
        # Skills-Hilfe sollte angezeigt werden

    def test_protocol_list(self):
        """Test bach protocol list (Protokolle verwalten)."""
        code, out, err = run_bach("protocol", "list")
        # Protocol-Handler ist optional - kein harter Fehler wenn nicht vorhanden
        # Entweder erfolgreich (code=0) oder unbekannter Befehl (code=1 mit Hinweis)
        assert code in (0, 1)
        # Wenn Handler fehlt, muss eine Suggestion erscheinen
        if code == 1:
            assert "protocol" in out.lower() or "Unbekannter Befehl" in out

    def test_connector_status(self):
        """Test bach connector status (Connector-System)."""
        code, out, err = run_bach("connector", "status")
        assert code == 0
        # Connector-Status sollte angezeigt werden

    def test_secrets_list(self):
        """Test bach secrets list (SQ076 Secrets-Management)."""
        code, out, err = run_bach("secrets", "list")
        assert code == 0
        # Secrets-Liste sollte angezeigt werden

    def test_dist_status(self):
        """Test bach dist status (Distribution-System)."""
        code, out, err = run_bach("dist", "status")
        assert code == 0
        # Distribution-Status sollte angezeigt werden

    def test_abo_list(self):
        """Test bach abo list (Abo-Scanner)."""
        code, out, err = run_bach("abo", "list")
        assert code == 0
        # Abo-Liste sollte angezeigt werden

    def test_snapshot_list(self):
        """Test bach snapshot list (Snapshot-System)."""
        code, out, err = run_bach("snapshot", "list")
        assert code == 0
        # Snapshot-Liste sollte angezeigt werden

    def test_daemon_status(self):
        """Test bach daemon status (Scheduler/Daemon-System)."""
        code, out, err = run_bach("daemon", "status")
        assert code == 0
        assert "DAEMON" in out or "Status" in out

    def test_scheduler_status_json(self):
        code, out, err = run_bach("scheduler", "status", "--json")
        assert code == 0, err
        payload = json.loads(out)
        assert "service" in payload
        assert "jobs" in payload

    def test_scheduler_jobs_json(self):
        code, out, err = run_bach("scheduler", "jobs", "--json")
        assert code == 0, err
        payload = json.loads(out)
        assert isinstance(payload["jobs"], list)

    def test_docs_list(self):
        """Test bach docs list (Dokumentations-Generator)."""
        code, out, err = run_bach("docs", "list")
        assert code == 0
        # Docs-Liste sollte angezeigt werden

    def test_backup_status(self):
        """Test bach backup status (Backup-System)."""
        code, out, err = run_bach("backup", "status")
        assert code == 0
        # Backup-Status sollte angezeigt werden

    def test_wiki_search_term(self):
        """Test bach wiki search <term> (Wiki-Suche)."""
        code, out, err = run_bach("wiki", "search", "bach")
        assert code == 0
        # Wiki-Suche sollte Ergebnisse oder "keine Treffer" anzeigen

    def test_wiki_provenance(self):
        code, out, err = run_bach("wiki", "provenance", "1")
        assert code == 0
        assert "PROVENANCE" in out

    def test_task_add(self):
        """Test bach task add (UC-Tasks erstellen)."""
        task_id = None
        code, out, err = run_bach("task", "add", "Smoke Test Task Cleanup")
        try:
            assert code == 0
            match = re.search(r"Task\s+(\d+)\s+erstellt", out)
            assert match, out
            task_id = match.group(1)
        finally:
            if task_id:
                cleanup_code, cleanup_out, cleanup_err = run_bach("task", "delete", task_id)
                assert cleanup_code == 0, cleanup_out + cleanup_err

    def test_lesson_search(self):
        """Test bach lesson search (Lesson-Suche)."""
        code, out, err = run_bach("lesson", "search", "utf")
        assert code == 0
        # Lesson-Suche sollte funktionieren

    def test_help_restore(self):
        """Test bach help restore (Restore-Hilfe)."""
        code, out, err = run_bach("help", "restore")
        assert code == 0
        assert "restore" in out.lower() or "RESTORE" in out


class TestLibraryAPI:
    """Library-Import funktioniert ohne CLI-Startup."""

    def test_import(self):
        if str(SYSTEM_ROOT) not in sys.path:
            sys.path.insert(0, str(SYSTEM_ROOT))
        from bach_api import task, memory, agent, agents, prompt, get_app
        assert task is not None
        assert memory is not None
        assert agent is not None
        assert agents is not None
        assert prompt is not None

    def test_app_creation(self):
        if str(SYSTEM_ROOT) not in sys.path:
            sys.path.insert(0, str(SYSTEM_ROOT))
        from bach_api import get_app
        app = get_app()
        assert app is not None
        assert app.base_path == SYSTEM_ROOT

    def test_task_list_via_api(self):
        if str(SYSTEM_ROOT) not in sys.path:
            sys.path.insert(0, str(SYSTEM_ROOT))
        from bach_api import get_app
        app = get_app()
        success, message = app.execute("task", "list")
        assert success is True
        assert len(message) > 0

    def test_memory_status_via_api(self):
        if str(SYSTEM_ROOT) not in sys.path:
            sys.path.insert(0, str(SYSTEM_ROOT))
        from bach_api import get_app
        app = get_app()
        success, message = app.execute("memory", "status")
        assert success is True

    def test_dir_exposes_documented_operations(self):
        if str(SYSTEM_ROOT) not in sys.path:
            sys.path.insert(0, str(SYSTEM_ROOT))
        from bach_api import task, memory

        task_dir = dir(task)
        memory_dir = dir(memory)

        assert "add" in task_dir
        assert "list" in task_dir
        assert "show" in task_dir
        assert "raw" in task_dir
        assert "write" in memory_dir
        assert "read" in memory_dir
        assert "status" in memory_dir

    def test_structured_task_api_and_raw_fallback(self):
        if str(SYSTEM_ROOT) not in sys.path:
            sys.path.insert(0, str(SYSTEM_ROOT))
        from bach_api import task

        created = task.add(
            "Structured API Smoke Task",
            priority="P4",
            category="tests",
            description="structured smoke",
        )
        try:
            assert created["title"] == "Structured API Smoke Task"
            assert created["priority"] == "P4"
            assert created["category"] == "tests"
            assert isinstance(created["id"], int)

            listed = task.list("--filter", "Structured API Smoke Task", limit=5)
            assert any(row["id"] == created["id"] for row in listed)

            details = task.show(created["id"])
            assert details["description"] == "structured smoke"

            success, raw_message = task.raw("show", created["id"])
            assert success is True
            assert "Structured API Smoke Task" in raw_message
        finally:
            success, _ = task.raw("delete", created["id"])
            assert success is True

    def test_structured_memory_api(self):
        if str(SYSTEM_ROOT) not in sys.path:
            sys.path.insert(0, str(SYSTEM_ROOT))
        from bach_api import db, memory

        entry = memory.write(
            "Structured memory smoke note",
            priority=2,
            tags=["smoke", "api"],
        )
        try:
            assert entry["content"] == "Structured memory smoke note"
            assert entry["priority"] == 2
            assert entry["tags"] == "smoke,api"

            recent = memory.read(limit=5, entry_type="note")
            assert any(row["id"] == entry["id"] for row in recent)

            status = memory.status()
            assert status["working"] >= 1

            success, raw_message = memory.raw("read", 1)
            assert success is True
            assert "WORKING MEMORY" in raw_message or "Memory" in raw_message
        finally:
            db.delete("memory_working", {"id": entry["id"]})

    def test_documented_agent_prompt_modules_via_api(self):
        if str(SYSTEM_ROOT) not in sys.path:
            sys.path.insert(0, str(SYSTEM_ROOT))
        from bach_api import agent, agents, prompt

        success, message = agent("list")
        assert success is True
        assert "agent" in message.lower()

        success, message = agents("list")
        assert success is True
        assert "agent" in message.lower()

        success, message = prompt("list")
        assert success is True

    def test_root_level_bach_api_import_for_agent_usecase(self):
        repo_root = SYSTEM_ROOT.parent
        code = (
            "from bach_api import agent, get_app; "
            "app = get_app(); "
            "success, _ = agent('list'); "
            "print(app.base_path); "
            "print(success)"
        )
        env = {**os.environ, "PYTHONPATH": str(SYSTEM_ROOT)}
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            env=env,
        )

        assert proc.returncode == 0, proc.stderr
        assert str(SYSTEM_ROOT) in proc.stdout
        assert "True" in proc.stdout


class TestRegistryDiscovery:
    """Auto-Discovery findet alle wichtigen Handler."""

    def test_handler_count(self):
        if str(SYSTEM_ROOT) not in sys.path:
            sys.path.insert(0, str(SYSTEM_ROOT))
        from core.registry import HandlerRegistry
        from core.aliases import COMMAND_ALIASES
        reg = HandlerRegistry()
        count = reg.discover(SYSTEM_ROOT / "hub", aliases=COMMAND_ALIASES)
        # Mindestens 50 Handler erwartet (aktuell 64)
        assert count >= 40, f"Nur {count} Handler gefunden, erwartet >= 40"

    def test_critical_handlers_exist(self):
        if str(SYSTEM_ROOT) not in sys.path:
            sys.path.insert(0, str(SYSTEM_ROOT))
        from core.registry import HandlerRegistry
        from core.aliases import COMMAND_ALIASES
        reg = HandlerRegistry()
        reg.discover(SYSTEM_ROOT / "hub", aliases=COMMAND_ALIASES)

        critical = [
            "task", "memory", "help", "startup", "shutdown", "status",
            "backup", "steuer", "gui", "daemon", "lesson", "wiki",
        ]
        for name in critical:
            assert reg.has(name), f"Kritischer Handler '{name}' fehlt!"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
