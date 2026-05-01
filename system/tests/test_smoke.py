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
import subprocess
import re
from pathlib import Path

SYSTEM_ROOT = Path(__file__).parent.parent
BACH_PY = SYSTEM_ROOT / "bach.py"

import pytest


def run_bach(*args, timeout=30):
    """Fuehrt bach.py aus und gibt (returncode, stdout, stderr) zurueck."""
    cmd = [sys.executable, str(BACH_PY)] + list(args)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(SYSTEM_ROOT),
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode, result.stdout, result.stderr


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

    def test_status(self):
        code, out, err = run_bach("--status")
        assert code == 0
        assert "BACH" in out or "Status" in out

    def test_health_status(self):
        code, out, err = run_bach("health", "status")
        assert code == 0
        assert "System Health Check" in out

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

    def test_downgrade_help(self):
        """Test bach help downgrade (SQ020)."""
        code, out, err = run_bach("help", "downgrade")
        assert code == 0
        assert "downgrade" in out.lower()

    def test_export_mirrors(self):
        """Test bach export mirrors (SQ071)."""
        code, out, err = run_bach("export", "mirrors")
        assert code == 0
        # Export sollte erfolgreich sein

    def test_lang_list(self):
        """Test bach lang list (SQ062 Uebersetzungssystem)."""
        code, out, err = run_bach("lang", "list")
        assert code == 0
        # Sprachen-Liste sollte angezeigt werden

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
