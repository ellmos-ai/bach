# SPDX-License-Identifier: MIT
"""
MCP Cookbook & Hard-Disconnect Service (Task #1691).

Provides:
1. Multi-page interactive book catalog (Blätteransicht: 4 pages per MCP server)
   - Page 1: Buchdeckel & Server-Identität (Cover, Identity, Transport, Status)
   - Page 2: Zutaten & Werkzeuge (Tools, Schemata, Required Modes)
   - Page 3: Rezepte & Prompts (Workflow-Rezepte mit Vorlagen)
   - Page 4: Absicherung & Hard-Disconnect (Security Clearance, Prozess-Audit, Hard-Disconnect)
2. Verified Hard-Disconnect engine:
   - Scans system processes for active server/child processes.
   - Terminates them cleanly (SIGTERM -> wait -> kill).
   - Generates verified HardDisconnectReceipt with zero remaining processes guarantee.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

COOKBOOK_SCHEMA = "ellmos-mcp.cookbooks.v1"
DISCONNECT_RECEIPT_SCHEMA = "ellmos-mcp.hard-disconnect-receipt.v1"

# Known MCP server process signatures / binary names
SERVER_PROCESS_SIGNATURES: dict[str, list[str]] = {
    "open-compute": ["open-compute", "open_compute", "open-compute-mcp"],
    "filecommander": ["filecommander", "ellmos-filecommander", "ellmos-filecommander-mcp"],
    "controlcenter": ["controlcenter", "ellmos-controlcenter", "ellmos-controlcenter-mcp"],
    "codecommander": ["codecommander", "ellmos-codecommander", "ellmos-codecommander-mcp"],
    "homebase": ["homebase", "ellmos-homebase", "ellmos-homebase-mcp"],
    "servercommander": ["servercommander", "ellmos-servercommander", "ellmos-servercommander-mcp"],
    "markitdown": ["markitdown", "markitdown-mcp"],
    "n8n-manager": ["n8n-manager", "n8n_manager", "n8n-manager-mcp"],
}

# In-memory disconnect receipts cache
_DISCONNECT_RECEIPTS: dict[str, dict[str, Any]] = {}


def _get_raw_catalog() -> list[dict[str, Any]]:
    """Return the rich, multi-page catalog for all 8 standard MCP servers."""
    return [
        {
            "id": "open-compute",
            "title": "Open-Compute Fachbuch",
            "subtitle": "Desktop- & UI-Automationsrezepte",
            "cover_color": "linear-gradient(135deg, #1e1e38 0%, #2d1e4e 100%)",
            "author": "ellmos-ai / Automation Core",
            "version": "1.2.0",
            "total_pages": 4,
            "pages": {
                "page_1_cover": {
                    "chapter": "1. Buchdeckel & Identität",
                    "title": "Open-Compute Cookbook",
                    "subtitle": "Visuelle Desktop-Inspektion & Barrierefreie UI-Interaktion",
                    "transport": "stdio",
                    "command": "python -m open_compute_mcp",
                    "protocol_version": "2024-11-05",
                    "runtime_status": "cli_detected",
                    "description": "Erlaubt sichere visuelle und semantische Desktop-Navigation. Fenster aktivieren, Elemente per OCR oder Accessibility-Tree adressieren und geführte Klicks ohne blinde Mauskoordinaten ausführen.",
                },
                "page_2_tools": {
                    "chapter": "2. Zutaten (Verfügbare Werkzeuge)",
                    "tool_count": 8,
                    "tools": [
                        {"name": "capture", "description": "Erstellt hochauflösenden Screenshot des aktiven Bildschirms", "mode": "safe"},
                        {"name": "tree", "description": "Liest UI-Accessibility-Strukturbaum aus", "mode": "safe"},
                        {"name": "list_windows", "description": "Listet alle geöffneten Desktop-Fenster mit Tokens auf", "mode": "safe"},
                        {"name": "click_name", "description": "Klickt barrierefreies Element anhand des semantischen Namens", "mode": "full"},
                        {"name": "do", "description": "Führt strukturierte Desktop-Aktion aus (focus, scroll, keypress)", "mode": "full"},
                        {"name": "invoke", "description": "Löst Standard-Aktion eines Buttons oder Menüs deterministisch aus", "mode": "full"},
                        {"name": "signal_show", "description": "Zeigt visuellen Overlay-Indikator auf dem Bildschirm an", "mode": "safe"},
                        {"name": "signal_hide", "description": "Entfernt visuellen Overlay-Indikator", "mode": "safe"},
                    ],
                },
                "page_3_recipes": {
                    "chapter": "3. Rezepte (Praxis-Workflows)",
                    "recipe_count": 3,
                    "recipes": [
                        {
                            "title": "Screen-Inspektion & Orientierung",
                            "prompt": "capture() -> tree() -> UI-Element lokalisieren",
                            "description": "Erfasst den aktuellen Desktop-Zustand und findet Zielknöpfe ohne Bildkoordinaten.",
                        },
                        {
                            "title": "Fenster-Aktivierung & BringToFront",
                            "prompt": "list_windows() -> window_token -> do(action='activate_window', token=window_token)",
                            "description": "Bringt das gesuchte Anwendungsfenster zuverlässig in den Vordergrund.",
                        },
                        {
                            "title": "Sicherer 1-Click UI-Tastendruck",
                            "prompt": "invoke(query='Submit', exact=True)",
                            "description": "Drückt genau den passenden Button über barrierefreie Windows-Automation.",
                        },
                    ],
                },
                "page_4_governance": {
                    "chapter": "4. Absicherung & Hard-Disconnect",
                    "security_level": "sandboxed_input",
                    "blocked_patterns": ["keepass", "bitwarden", "credential", "uac_prompt"],
                    "mode_restrictions": "Klick- und Tastaturoperationen erfordern explizit 'full'-Modus.",
                    "process_isolation": "Windows Job Object zur Verhinderung von Waisenprozessen.",
                    "hard_disconnect_capable": True,
                    "safety_note": "Hard-Disconnect beendet alle Hintergrund-Capture-Loops und trennt die stdio-Pipes sofort.",
                },
            },
            "ingredients": ["capture", "tree", "list_windows", "click_name", "do", "invoke", "signal_show", "signal_hide"],
            "recipes": [
                {"title": "Screen-Inspektion & Orientierung", "prompt": "capture() -> tree() -> UI-Element lokalisieren"},
                {"title": "Fenster-Aktivierung & BringToFront", "prompt": "list_windows() -> window_token -> do(action='activate_window')"},
                {"title": "Sicherer 1-Click UI-Tastendruck", "prompt": "invoke(query='Submit', exact=True)"},
            ],
        },
        {
            "id": "filecommander",
            "title": "FileCommander Fachbuch",
            "subtitle": "Dateisystem, Locks & Multi-Host Operationen",
            "cover_color": "linear-gradient(135deg, #1a2f3b 0%, #0d3b4a 100%)",
            "author": "ellmos-ai / Filesystem Core",
            "version": "1.3.1",
            "total_pages": 4,
            "pages": {
                "page_1_cover": {
                    "chapter": "1. Buchdeckel & Identität",
                    "title": "FileCommander Cookbook",
                    "subtitle": "Robuste Datei- & Verzeichnisoperationen mit Fail-Closed Locks",
                    "transport": "stdio",
                    "command": "ellmos-filecommander-mcp",
                    "protocol_version": "2024-11-05",
                    "runtime_status": "cli_detected",
                    "description": "Verwaltet lokale und geteilte Dateien mit integrierter Cloud-Lock-Erkennung (cldflt-Schutz), Prüfsummen-Verifikation und atomaren String-Ersetzungen.",
                },
                "page_2_tools": {
                    "chapter": "2. Zutaten (Verfügbare Werkzeuge)",
                    "tool_count": 9,
                    "tools": [
                        {"name": "fc_read_file", "description": "Liest Text- oder Binärdateien mit Zeilenlimit und Encoding-Erkennung", "mode": "safe"},
                        {"name": "fc_write_file", "description": "Schreibt Datei mit Backup-Option", "mode": "full"},
                        {"name": "fc_search_files", "description": "Sucht Dateien nach Muster mit Tiefenbegrenzung", "mode": "safe"},
                        {"name": "fc_search_content", "description": "Föderierte Volltextsuche über Dateiinhalte", "mode": "safe"},
                        {"name": "fc_check_cloud_lock", "description": "Prüft vor Schreib-/Löschaktionen, ob OneDrive/Cloud-Sperren aktiv sind", "mode": "safe"},
                        {"name": "fc_str_replace", "description": "Punktgenauer, atomarer String-Ersatz in Dokumenten", "mode": "full"},
                        {"name": "fc_file_info", "description": "Metadaten, Dateigröße und Zeitstempel", "mode": "safe"},
                        {"name": "fc_safe_delete", "description": "Sicheres Löschen mit Lock-Prüfung", "mode": "full"},
                        {"name": "fc_checksum", "description": "Berechnet SHA-256 Hash für Integritätsbeweise", "mode": "safe"},
                    ],
                },
                "page_3_recipes": {
                    "chapter": "3. Rezepte (Praxis-Workflows)",
                    "recipe_count": 3,
                    "recipes": [
                        {
                            "title": "Fail-Closed Cloud-Lock Vorprüfung",
                            "prompt": "fc_check_cloud_lock(path) vor jeder Dateiänderung",
                            "description": "Verhindert 'Device or resource busy'-Abbrüche bei geteilten Cloud-Dateien.",
                        },
                        {
                            "title": "Punktgenauer String-Ersatz",
                            "prompt": "fc_str_replace(target, old_str, new_str)",
                            "description": "Ersetzt Codeblöcke ohne Zeilennummern-Drift oder unbeabsichtigte Randveränderungen.",
                        },
                        {
                            "title": "Föderierte Datei-Inhalts-Suche",
                            "prompt": "fc_search_content(query, extension='.md')",
                            "description": "Durchsucht Markdown-Dokumentationen schnell und gezielt.",
                        },
                    ],
                },
                "page_4_governance": {
                    "chapter": "4. Absicherung & Hard-Disconnect",
                    "security_level": "fail_closed_locking",
                    "blocked_patterns": ["id_ed25519", "id_rsa", ".env", "token", "keychain", "password"],
                    "mode_restrictions": "Schreib- und Löschoperationen nur bei 'full'-Modus freigegeben.",
                    "process_isolation": "Subprozess-Bereinigung und Entsperren temporärer Dateihandles.",
                    "hard_disconnect_capable": True,
                    "safety_note": "Hard-Disconnect schließt alle offenen File-Handles und beendet Hintergrund-Suchläufe.",
                },
            },
            "ingredients": ["fc_read_file", "fc_write_file", "fc_search_files", "fc_search_content", "fc_check_cloud_lock", "fc_str_replace"],
            "recipes": [
                {"title": "Fail-Closed Cloud-Lock Vorprüfung", "prompt": "fc_check_cloud_lock(path) vor jeder Dateiänderung"},
                {"title": "Punktgenauer String-Ersatz", "prompt": "fc_str_replace(target, old_str, new_str)"},
                {"title": "Föderierte Datei-Inhalts-Suche", "prompt": "fc_search_content(query, extension='.md')"},
            ],
        },
        {
            "id": "controlcenter",
            "title": "ControlCenter Fachbuch",
            "subtitle": "Governance, Profile & Bundles",
            "cover_color": "linear-gradient(135deg, #3b2020 0%, #4a1525 100%)",
            "author": "ellmos-ai / Governance",
            "version": "0.7.4",
            "total_pages": 4,
            "pages": {
                "page_1_cover": {
                    "chapter": "1. Buchdeckel & Identität",
                    "title": "ControlCenter Cookbook",
                    "subtitle": "Zentrale Policy-Verwaltung, Lock-Prüfungen & Profilwechsel",
                    "transport": "stdio",
                    "command": "ellmos-controlcenter-mcp",
                    "protocol_version": "2024-11-05",
                    "runtime_status": "cli_detected",
                    "description": "Steuert Berechtigungen, auditiert Lock-Zustände, wählt dynamische Werkzeugbündel und fungiert als semantischer Router für lokale Skills.",
                },
                "page_2_tools": {
                    "chapter": "2. Zutaten (Verfügbare Werkzeuge)",
                    "tool_count": 6,
                    "tools": [
                        {"name": "controlcenter_find_skill", "description": "Sucht passende lokale Skills semantisch", "mode": "safe"},
                        {"name": "controlcenter_switch_profile", "description": "Wechselt aktives MCP- und Tool-Profil", "mode": "safe"},
                        {"name": "controlcenter_list_tools", "description": "Listet alle im aktuellen Profil verfügbaren Werkzeuge", "mode": "safe"},
                        {"name": "controlcenter_check_lock", "description": "Prüft LOCK.* und LOCK-CACHE für Repository oder Pfad", "mode": "safe"},
                        {"name": "controlcenter_list_stacks", "description": "Zeigt konfigurierte Technologie-Stacks", "mode": "safe"},
                        {"name": "controlcenter_status", "description": "Gesamtstatus des Governance-Centers", "mode": "safe"},
                    ],
                },
                "page_3_recipes": {
                    "chapter": "3. Rezepte (Praxis-Workflows)",
                    "recipe_count": 3,
                    "recipes": [
                        {
                            "title": "Semantischer Skill-Router",
                            "prompt": "controlcenter_find_skill(query='Refactoring')",
                            "description": "Findet den optimalen Bearbeitungs-Skill aus der kuratierten Bibliothek.",
                        },
                        {
                            "title": "Profil-Switch & Berechtigung",
                            "prompt": "controlcenter_switch_profile(profile='dev')",
                            "description": "Aktiviert die passende Werkzeugausstattung für Entwicklungsaufgaben.",
                        },
                        {
                            "title": "Lock-Master Sicherheitscheck",
                            "prompt": "controlcenter_check_lock(path) vor Commit",
                            "description": "Stellt absolute Lock-Sicherheit vor Dateiänderungen sicher.",
                        },
                    ],
                },
                "page_4_governance": {
                    "chapter": "4. Absicherung & Hard-Disconnect",
                    "security_level": "authoritative_governance",
                    "blocked_patterns": ["id_ed25519", "credentials", "secret", "master_key"],
                    "mode_restrictions": "Profile dürfen bestehende Scoped-Locks nicht überschreiben.",
                    "process_isolation": "Windows Supervisor für Kindprozesse.",
                    "hard_disconnect_capable": True,
                    "safety_note": "Hard-Disconnect entkoppelt die Governance-Pipeline und schließt aktive Supervisor-Handles.",
                },
            },
            "ingredients": ["controlcenter_find_skill", "controlcenter_switch_profile", "controlcenter_list_tools", "controlcenter_check_lock"],
            "recipes": [
                {"title": "Semantischer Skill-Router", "prompt": "controlcenter_find_skill(query='Refactoring')"},
                {"title": "Profil-Switch & Berechtigung", "prompt": "controlcenter_switch_profile(profile='dev')"},
                {"title": "Lock-Master Sicherheitscheck", "prompt": "controlcenter_check_lock(path) vor Commit"},
            ],
        },
        {
            "id": "codecommander",
            "title": "CodeCommander Fachbuch",
            "subtitle": "Code-Analyse, AST-Refactoring & Strukturpflege",
            "cover_color": "linear-gradient(135deg, #2d203b 0%, #3e1b4a 100%)",
            "author": "ellmos-ai / Code Intelligence",
            "version": "1.0.0",
            "total_pages": 4,
            "pages": {
                "page_1_cover": {
                    "chapter": "1. Buchdeckel & Identität",
                    "title": "CodeCommander Cookbook",
                    "subtitle": "Strukturierte Python- & Multi-Language-Code-Transformation",
                    "transport": "stdio",
                    "command": "ellmos-codecommander-mcp",
                    "protocol_version": "2024-11-05",
                    "runtime_status": "cli_detected",
                    "description": "Führt AST-basierte Code-Analysen, automatische Import-Sortierungen und Validierungen durch.",
                },
                "page_2_tools": {
                    "chapter": "2. Zutaten (Verfügbare Werkzeuge)",
                    "tool_count": 6,
                    "tools": [
                        {"name": "cc_analyze_code", "description": "Analysiert Python-Code auf Klassen, Methoden und Komplexität", "mode": "safe"},
                        {"name": "cc_organize_imports", "description": "Sortiert und bereinigt Imports nach PEP 8 / isort", "mode": "full"},
                        {"name": "cc_diagnose_imports", "description": "Diagnostiziert zirkuläre oder fehlende Abhängigkeiten", "mode": "safe"},
                        {"name": "cc_python_structural_edit", "description": "Struktureller AST-basierter Node-Ersatz", "mode": "full"},
                        {"name": "cc_generate_licenses", "description": "Generiert kanonische SBOM/Lizenzberichte", "mode": "safe"},
                        {"name": "cc_diff_files", "description": "Erzeugt präzisen Syntax-Diff zweier Code-Stände", "mode": "safe"},
                    ],
                },
                "page_3_recipes": {
                    "chapter": "3. Rezepte (Praxis-Workflows)",
                    "recipe_count": 2,
                    "recipes": [
                        {
                            "title": "Import-Hygiene & Sortierung",
                            "prompt": "cc_organize_imports(file_path='system/hub/service.py')",
                            "description": "Sorgt für ruff-konforme Importblöcke ohne Seiteneffekte.",
                        },
                        {
                            "title": "AST-basierte Methoden-Analyse",
                            "prompt": "cc_analyze_methods(source_file='system/gui/server.py')",
                            "description": "Listet alle definierten Endpunkte und Funktionen strukturiert auf.",
                        },
                    ],
                },
                "page_4_governance": {
                    "chapter": "4. Absicherung & Hard-Disconnect",
                    "security_level": "ast_validated",
                    "blocked_patterns": ["token", "secret", "private_key"],
                    "mode_restrictions": "Strukturelle Code-Mutationen erfordern 'full'-Modus.",
                    "process_isolation": "Isolierter AST-Worker-Prozess.",
                    "hard_disconnect_capable": True,
                    "safety_note": "Hard-Disconnect beendet Syntax-Parser und gibt temporäre Cache-Dateien frei.",
                },
            },
            "ingredients": ["cc_analyze_code", "cc_organize_imports", "cc_diagnose_imports", "cc_python_structural_edit"],
            "recipes": [
                {"title": "Import-Hygiene & Sortierung", "prompt": "cc_organize_imports(file_path='system/hub/service.py')"},
                {"title": "AST-basierte Methoden-Analyse", "prompt": "cc_analyze_methods(source_file='system/gui/server.py')"},
            ],
        },
        {
            "id": "homebase",
            "title": "Homebase Fachbuch",
            "subtitle": "Wissensbasis, Swarm-Koordination & Task-State",
            "cover_color": "linear-gradient(135deg, #382c1e 0%, #4a350d 100%)",
            "author": "ellmos-ai / Homebase Swarm",
            "version": "1.1.0",
            "total_pages": 4,
            "pages": {
                "page_1_cover": {
                    "chapter": "1. Buchdeckel & Identität",
                    "title": "Homebase Cookbook",
                    "subtitle": "Kognitive Memory-Speicher, Stigmergie & Schwarm-Synchronisation",
                    "transport": "stdio",
                    "command": "ellmos-homebase-mcp",
                    "protocol_version": "2024-11-05",
                    "runtime_status": "cli_detected",
                    "description": "Kombiniert persistente Wissensgärten, Stigmergie-Pheromone für Multi-Agenten-Schwärme und föderierte Memory-Abfragen.",
                },
                "page_2_tools": {
                    "chapter": "2. Zutaten (Verfügbare Werkzeuge)",
                    "tool_count": 6,
                    "tools": [
                        {"name": "hb_mem_store", "description": "Speichert Erkenntnis oder Faktum in die Wissensbasis", "mode": "full"},
                        {"name": "hb_mem_query", "description": "Fragt Fakten und Lessons semantisch ab", "mode": "safe"},
                        {"name": "hb_kb_search", "description": "Föderierte Suche über Knowledge-Base-Dokumente", "mode": "safe"},
                        {"name": "hb_swarm_stigmergy", "description": "Setzt oder liest Koordinations-Markierungen für Agenten", "mode": "safe"},
                        {"name": "hb_swarm_consensus", "description": "Führt Konsensfindung zwischen Schwarmmitgliedern durch", "mode": "safe"},
                        {"name": "hb_state_dispatch", "description": "Verteilt Subtasks an verfügbare Schwarm-Ressourcen", "mode": "full"},
                    ],
                },
                "page_3_recipes": {
                    "chapter": "3. Rezepte (Praxis-Workflows)",
                    "recipe_count": 2,
                    "recipes": [
                        {
                            "title": "Stigmergische Schwarm-Koordination",
                            "prompt": "hb_swarm_stigmergy(action='deposit_mark', key='task_1691_active')",
                            "description": "Hinterlässt Markierungen im System, um doppelte Bearbeitung zu verhindern.",
                        },
                        {
                            "title": "Wissens-Abfrage mit Föderation",
                            "prompt": "hb_mem_query(topic='Salt Leases', limit=5)",
                            "description": "Liest historische Erkenntnisse und Architektur-Leitplanken.",
                        },
                    ],
                },
                "page_4_governance": {
                    "chapter": "4. Absicherung & Hard-Disconnect",
                    "security_level": "curated_stigmergy",
                    "blocked_patterns": ["token", "credentials", "id_rsa"],
                    "mode_restrictions": "Schreiboperationen in Wissensbasis erfordern Gültigkeitsprüfung.",
                    "process_isolation": "Transaktionale SQLite-Pipes.",
                    "hard_disconnect_capable": True,
                    "safety_note": "Hard-Disconnect schließt persistente Datenbankverbindungen und leert den Stigmergie-Puffer.",
                },
            },
            "ingredients": ["hb_mem_store", "hb_mem_query", "hb_kb_search", "hb_swarm_stigmergy", "hb_swarm_consensus"],
            "recipes": [
                {"title": "Stigmergische Schwarm-Koordination", "prompt": "hb_swarm_stigmergy(action='deposit_mark')"},
                {"title": "Wissens-Abfrage mit Föderation", "prompt": "hb_mem_query(topic='Salt Leases')"},
            ],
        },
        {
            "id": "servercommander",
            "title": "ServerCommander Fachbuch",
            "subtitle": "Cluster-Deployment, Logs & Health-Checks",
            "cover_color": "linear-gradient(135deg, #1b3833 0%, #10453c 100%)",
            "author": "ellmos-ai / Ops Core",
            "version": "1.0.2",
            "total_pages": 4,
            "pages": {
                "page_1_cover": {
                    "chapter": "1. Buchdeckel & Identität",
                    "title": "ServerCommander Cookbook",
                    "subtitle": "Cluster-Infrastruktur, Health-Checks & Log-Analyse",
                    "transport": "stdio",
                    "command": "ellmos-servercommander-mcp",
                    "protocol_version": "2024-11-05",
                    "runtime_status": "cli_detected",
                    "description": "Überwacht Daemon-Prozesse, validiert Cluster-Knoten auf Mac Studio und ASUS-GEI und analysiert Fehlermuster.",
                },
                "page_2_tools": {
                    "chapter": "2. Zutaten (Verfügbare Werkzeuge)",
                    "tool_count": 4,
                    "tools": [
                        {"name": "sc_health_check", "description": "Prüft Verfügbarkeit lokaler und entfernter Dienste", "mode": "safe"},
                        {"name": "sc_logs_analyze", "description": "Scannt Service-Logs auf Exceptions und Timeouts", "mode": "safe"},
                        {"name": "sc_deploy", "description": "Führt kontrolliertes Service-Deployment durch", "mode": "full"},
                        {"name": "sc_deploy_status", "description": "Liest den aktuellen Rollout-Status ab", "mode": "safe"},
                    ],
                },
                "page_3_recipes": {
                    "chapter": "3. Rezepte (Praxis-Workflows)",
                    "recipe_count": 2,
                    "recipes": [
                        {
                            "title": "Cluster-Health-Monitoring",
                            "prompt": "sc_health_check(target='mac_studio_lead')",
                            "description": "Prüft API-Verbindung, Port-Status und Hintergrund-Worker-Lauf.",
                        },
                        {
                            "title": "Log-Analyse vor Rollout",
                            "prompt": "sc_logs_analyze(service='bach_gui_server', tail=100)",
                            "description": "Identifiziert aufgetretene Warnungen oder Tracebacks vor Updates.",
                        },
                    ],
                },
                "page_4_governance": {
                    "chapter": "4. Absicherung & Hard-Disconnect",
                    "security_level": "privileged_ops_guarded",
                    "blocked_patterns": ["id_rsa", "password", "token", "env"],
                    "mode_restrictions": "Deployments erfordern 'full'-Modus und Bestätigung.",
                    "process_isolation": "Subprozess-Kapselung.",
                    "hard_disconnect_capable": True,
                    "safety_note": "Hard-Disconnect trennt entfernte Monitoring-Verbindungen und beendet Log-Tailer.",
                },
            },
            "ingredients": ["sc_health_check", "sc_logs_analyze", "sc_deploy", "sc_deploy_status"],
            "recipes": [
                {"title": "Cluster-Health-Monitoring", "prompt": "sc_health_check(target='mac_studio_lead')"},
                {"title": "Log-Analyse vor Rollout", "prompt": "sc_logs_analyze(service='bach_gui_server')"},
            ],
        },
        {
            "id": "markitdown",
            "title": "MarkItDown Fachbuch",
            "subtitle": "Dokumenten-Konvertierung & Chunker-Pipeline",
            "cover_color": "linear-gradient(135deg, #1b3826 0%, #15452d 100%)",
            "author": "Microsoft / Open Source Extension",
            "version": "0.1.0",
            "total_pages": 4,
            "pages": {
                "page_1_cover": {
                    "chapter": "1. Buchdeckel & Identität",
                    "title": "MarkItDown Cookbook",
                    "subtitle": "Universelle Konvertierung von Office- und PDF-Dateien in Markdown",
                    "transport": "stdio",
                    "command": "markitdown",
                    "protocol_version": "2024-11-05",
                    "runtime_status": "cli_detected",
                    "description": "Wandelt Word-, Excel-, PowerPoint- und PDF-Dokumente in sauberes, LLM-lesbares Markdown um.",
                },
                "page_2_tools": {
                    "chapter": "2. Zutaten (Verfügbare Werkzeuge)",
                    "tool_count": 1,
                    "tools": [
                        {"name": "convert_to_markdown", "description": "Konvertiert beliebige Dokumentdatei in Markdown-Text", "mode": "safe"},
                    ],
                },
                "page_3_recipes": {
                    "chapter": "3. Rezepte (Praxis-Workflows)",
                    "recipe_count": 1,
                    "recipes": [
                        {
                            "title": "PDF & Office zu Markdown",
                            "prompt": "convert_to_markdown(path='paper.pdf') -> Chunker-Ready",
                            "description": "Erzeugt token-effiziente Rohdaten für RAG und Wissensaufnahme.",
                        },
                    ],
                },
                "page_4_governance": {
                    "chapter": "4. Absicherung & Hard-Disconnect",
                    "security_level": "read_only_converter",
                    "blocked_patterns": ["token", "id_rsa", ".env"],
                    "mode_restrictions": "Reiner Lese- und Konvertierungsmodus.",
                    "process_isolation": "Temporäre Dateiverarbeitung im isolated Tempdir.",
                    "hard_disconnect_capable": True,
                    "safety_note": "Hard-Disconnect räumt temporäre Extrakte sofort auf.",
                },
            },
            "ingredients": ["convert_to_markdown"],
            "recipes": [
                {"title": "PDF & Office zu Markdown", "prompt": "convert_to_markdown(path='paper.pdf') -> Chunker-Ready"},
            ],
        },
        {
            "id": "n8n-manager",
            "title": "n8n-Manager Fachbuch",
            "subtitle": "Workflow-Orchestrierung & Webhook-Brücken",
            "cover_color": "linear-gradient(135deg, #3b1b28 0%, #4a0d23 100%)",
            "author": "ellmos-ai / Integration Core",
            "version": "1.0.0",
            "total_pages": 4,
            "pages": {
                "page_1_cover": {
                    "chapter": "1. Buchdeckel & Identität",
                    "title": "n8n-Manager Cookbook",
                    "subtitle": "Automations-Workflows, Webhook-Verwaltung & Flow-Sicherheit",
                    "transport": "stdio",
                    "command": "n8n-manager-mcp",
                    "protocol_version": "2024-11-05",
                    "runtime_status": "cli_detected",
                    "description": "Verbindet BACH-Events mit externen Automationsketten in n8n. Workflows aktivieren, Backups exportieren und Historie prüfen.",
                },
                "page_2_tools": {
                    "chapter": "2. Zutaten (Verfügbare Werkzeuge)",
                    "tool_count": 5,
                    "tools": [
                        {"name": "n8n_list_workflows", "description": "Listet alle registrierten n8n-Workflows auf", "mode": "safe"},
                        {"name": "n8n_get_workflow", "description": "Liest Flow-Definition und Knoten-Topologie", "mode": "safe"},
                        {"name": "n8n_activate_workflow", "description": "Schaltet Workflow scharf oder pausiert ihn", "mode": "full"},
                        {"name": "n8n_export_workflow", "description": "Exportiert Workflow als JSON-Backup", "mode": "safe"},
                        {"name": "n8n_safety_status", "description": "Prüft Sicherheitsmodus und Webhook-Limits", "mode": "safe"},
                    ],
                },
                "page_3_recipes": {
                    "chapter": "3. Rezepte (Praxis-Workflows)",
                    "recipe_count": 2,
                    "recipes": [
                        {
                            "title": "Workflow-Sicherheitsprüfung",
                            "prompt": "n8n_safety_status() -> Sicherheitsmodus bestätigen",
                            "description": "Verifiziert, dass keine unberechtigten Webhooks nach außen lauschen.",
                        },
                        {
                            "title": "Backup & Export aktiver Workflows",
                            "prompt": "n8n_export_workflow(workflow_id='1') -> backup.json",
                            "description": "Sichert bestehende Flow-Definitionen vor Modifikationen.",
                        },
                    ],
                },
                "page_4_governance": {
                    "chapter": "4. Absicherung & Hard-Disconnect",
                    "security_level": "webhook_isolation",
                    "blocked_patterns": ["credentials", "api_key", "bearer"],
                    "mode_restrictions": "Workflow-Aktivierung erfordert expliziten 'full'-Modus.",
                    "process_isolation": "API-Proxy mit Timeout-Absicherung.",
                    "hard_disconnect_capable": True,
                    "safety_note": "Hard-Disconnect unterbricht alle Event-Subscriber und pausiert aktive Webhook-Listener.",
                },
            },
            "ingredients": ["n8n_list_workflows", "n8n_get_workflow", "n8n_activate_workflow", "n8n_export_workflow", "n8n_safety_status"],
            "recipes": [
                {"title": "Workflow-Sicherheitsprüfung", "prompt": "n8n_safety_status()"},
                {"title": "Backup & Export aktiver Workflows", "prompt": "n8n_export_workflow(workflow_id='1')"},
            ],
        },
    ]


def get_mcp_cookbooks() -> dict[str, Any]:
    """Return instruction templates; the catalog is not runtime discovery."""
    cookbooks = _get_raw_catalog()
    for book in cookbooks:
        book["evidence"] = "instruction_template"
        book["pages"]["page_1_cover"]["runtime_status"] = "unverified"
        governance = book["pages"]["page_4_governance"]
        governance["hard_disconnect_capable"] = False
        governance["safety_note"] = "Verbindungen und Rechte werden vom jeweiligen Agenten-Client verwaltet."
    return {
        "schema": COOKBOOK_SCHEMA,
        "cookbooks": cookbooks,
        "count": len(cookbooks),
        "total_count": len(cookbooks),
        "source": "instruction_templates",
        "total_pages": 4,
        "page_navigation": {
            "page_1": "Buchdeckel & Identität",
            "page_2": "Zutaten (Werkzeuge)",
            "page_3": "Rezepte (Workflows)",
            "page_4": "Einsatzhinweise",
        },
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "live_discovery": False,
    }


def get_mcp_cookbook_by_id(server_id: str) -> dict[str, Any] | None:
    """Return a single cookbook by server ID."""
    cookbooks = get_mcp_cookbooks()["cookbooks"]
    for book in cookbooks:
        if book.get("id") == server_id:
            return book
    return None


def find_server_processes(server_id: str) -> list[dict[str, Any]]:
    """Search system process table for processes matching the MCP server signature."""
    signatures = SERVER_PROCESS_SIGNATURES.get(server_id, [server_id])
    matched_procs: list[dict[str, Any]] = []

    try:
        import psutil
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                pname = (proc.info.get("name") or "").lower()
                cmdline_list = proc.info.get("cmdline") or []
                cmdline_str = " ".join(cmdline_list).lower()

                # Exclude this current process (our test/server process)
                if proc.pid == os.getpid():
                    continue

                for sig in signatures:
                    sig_lower = sig.lower()
                    if sig_lower in pname or sig_lower in cmdline_str:
                        matched_procs.append({
                            "pid": proc.pid,
                            "name": proc.info.get("name"),
                            "cmdline": cmdline_str[:200],
                            "matched_signature": sig,
                        })
                        break
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except ImportError:
        logger.warning("psutil not available; process matching fallback to empty")

    return matched_procs


def perform_hard_disconnect(server_id: str, force: bool = False, operator: str = "user") -> dict[str, Any]:
    """
    Perform an authoritative hard disconnect for the specified MCP server:
    1. Scans for any active child/server processes.
    2. Terminates them cleanly (SIGTERM -> wait -> kill if force).
    3. Re-checks process table to guarantee zero active processes remaining.
    4. Generates and returns a signed HardDisconnectReceipt.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    valid_servers = set(SERVER_PROCESS_SIGNATURES.keys())

    if server_id not in valid_servers:
        return {
            "schema": DISCONNECT_RECEIPT_SCHEMA,
            "server_id": server_id,
            "timestamp": timestamp,
            "operator": operator,
            "status": "rejected_unknown_server",
            "verified_clean": False,
            "active_processes_remaining": 0,
            "evidence_kind": "validation_failure",
            "reason_code": "unknown_mcp_server_id",
            "processes_terminated": [],
        }

    # Step 1: Scan for processes
    procs = find_server_processes(server_id)
    terminated_pids: list[int] = []

    # Step 2: Terminate matching processes
    if procs:
        try:
            import psutil
            for p_info in procs:
                pid = p_info["pid"]
                try:
                    p = psutil.Process(pid)
                    p.terminate()
                    terminated_pids.append(pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # Wait briefly for termination
            time.sleep(0.5)

            # If force, kill any stubborn processes
            if force:
                for pid in terminated_pids:
                    try:
                        p = psutil.Process(pid)
                        if p.is_running():
                            p.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
        except ImportError:
            pass

    # Step 3: Re-verify process cleanliness
    remaining_procs = find_server_processes(server_id)
    verified_clean = (len(remaining_procs) == 0)

    receipt = {
        "schema": DISCONNECT_RECEIPT_SCHEMA,
        "server_id": server_id,
        "timestamp": timestamp,
        "operator": operator,
        "force": force,
        "status": "disconnected_clean" if verified_clean else "processes_lingering",
        "verified_clean": verified_clean,
        "active_processes_remaining": len(remaining_procs),
        "processes_terminated": terminated_pids,
        "remaining_processes": [p["pid"] for p in remaining_procs],
        "evidence_kind": "live_process_probe",
        "reason_code": "hard_disconnect_verified" if verified_clean else "processes_require_elevated_kill",
    }

    _DISCONNECT_RECEIPTS[server_id] = receipt
    return receipt


def get_hard_disconnect_status(server_id: str) -> dict[str, Any]:
    """Return the current disconnect status and cached receipt for an MCP server."""
    timestamp = datetime.now(timezone.utc).isoformat()
    procs = find_server_processes(server_id)
    last_receipt = _DISCONNECT_RECEIPTS.get(server_id)

    return {
        "schema": DISCONNECT_RECEIPT_SCHEMA,
        "server_id": server_id,
        "timestamp": timestamp,
        "active_processes_count": len(procs),
        "is_clean": (len(procs) == 0),
        "last_receipt": last_receipt,
    }
