#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
BACH MCP Server v2.0 - Model Context Protocol Integration
==========================================================

Stellt BACH-Daten und -Funktionen ueber MCP bereit.
Nutzt die Handler-Architektur via bach_api statt direktem SQLite-Zugriff.

Resources (8):
  bach:/tasks/active      - Aktive Tasks
  bach:/tasks/stats       - Task-Statistiken
  bach:/status            - System-Status
  bach:/memory/lessons    - Gelernte Lessons
  bach:/memory/status     - Memory-Uebersicht
  bach:/skills/list       - Registrierte Skills
  bach:/contacts          - Kontakte
  bach:/version           - Server-Version und Capabilities

Tools (23):
  Task:     task_create, task_done, task_search, task_list
  Memory:   memory_write, memory_search, memory_facts, memory_status, memory_note
  Lesson:   lesson_search
  Backup:   backup_create, backup_list
  Steuer:   steuer_status
  Kontakt:  contact_search
  Komm:     msg_send, msg_unread, notify_send
  Session:  session_startup, session_shutdown
  Partner:  partner_list, partner_status
  System:   healthcheck, db_query

Prompts (3):
  daily_briefing          - Taegliches Briefing (Tasks, Nachrichten, Status)
  task_review             - Task-Analyse und Priorisierung
  session_summary         - Session-Zusammenfassung erstellen

Installation:
  pip install mcp
  python tools/mcp_server.py

Claude Code Config (~/.claude/claude_code_config.json):
  {
    "mcpServers": {
      "bach": {
        "command": "python",
        "args": ["C:/path/to/system/tools/mcp_server.py"]
      }
    }
  }

Changelog:
  v2.2.0 - Session-Tools (session_startup, session_shutdown)
         - Partner-Tools (partner_list, partner_status)
         - db_query Table-Whitelist (116 sichere Tabellen)
  v2.1.0 - MCP Prompts (3 Vorlagen: daily_briefing, task_review, session_summary)
         - Version-Resource (bach:/version) mit Server-Capabilities
         - Alle drei MCP-Primitives (Resources, Tools, Prompts) implementiert
  v2.0.0 - Refactoring auf bach_api (kein direkter SQLite-Zugriff mehr)
         - 19 Tools statt 10, 7 Resources statt 6
         - Alle Tools nutzen Handler-Logik statt rohem SQL
         - db_query bleibt als Power-User Escape-Hatch (SELECT-only)
  v1.1.0 - Initiale Version mit direktem SQLite
"""

__version__ = "2.2.0"
__author__ = "BACH Team"

import os
import sys
import sqlite3
import logging
from datetime import datetime
from pathlib import Path

# BACH system/ Verzeichnis ermitteln
SYSTEM_ROOT = Path(__file__).resolve().parents[1]
BACH_SYSTEM = str(SYSTEM_ROOT)

# sys.path fuer bach_api und Handler-Imports
if BACH_SYSTEM not in sys.path:
    sys.path.insert(0, BACH_SYSTEM)

from hub.bach_paths import BACH_DB
BACH_DB_PATH = Path(BACH_DB)
BACH_DB_STR = str(BACH_DB_PATH)

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("MCP SDK nicht installiert. Bitte: pip install mcp")
    print("Danach: python tools/mcp_server.py")
    sys.exit(1)

from bach_api import get_app

# Server initialisieren
mcp = FastMCP("BACH Personal Assistant")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bach-mcp")


# ------------------------------------------------------------------
# Core Helper
# ------------------------------------------------------------------

def _execute(handler: str, operation: str, args: list = None) -> str:
    """Fuehrt eine BACH-Handler-Operation via bach_api aus.

    Alle Handler-Aufrufe laufen ueber app.execute(), das die Registry,
    Validierung und Fehlerbehandlung der Handler-Schicht nutzt.
    """
    try:
        app = get_app()
        success, message = app.execute(handler, operation, args or [])
        return message
    except Exception as e:
        return f"[FEHLER] {handler} {operation}: {e}"


# ------------------------------------------------------------------
# Resources (read-only, 7 Stueck)
# ------------------------------------------------------------------

@mcp.resource("bach:/tasks/active")
def get_active_tasks() -> str:
    """Alle offenen/aktiven Tasks aus der BACH-Datenbank."""
    return _execute("task", "list")


@mcp.resource("bach:/tasks/stats")
def get_task_stats() -> str:
    """Task-Statistiken: offen, erledigt, nach Prioritaet."""
    # Eigene Aggregation, da kein Handler eine Stats-Operation hat
    try:
        conn = sqlite3.connect(BACH_DB_STR)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        done = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = 'done'"
        ).fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = 'pending'"
        ).fetchone()[0]
        by_prio = conn.execute("""
            SELECT priority, COUNT(*) as cnt
            FROM tasks WHERE status != 'done'
            GROUP BY priority ORDER BY priority
        """).fetchall()
        conn.close()

        lines = [
            f"Tasks: {total} gesamt, {done} erledigt, {pending} offen",
            "",
            "Nach Prioritaet (offen):",
        ]
        for r in by_prio:
            lines.append(f"  {r['priority'] or '?'}: {r['cnt']}")
        return "\n".join(lines)
    except Exception as e:
        return f"[FEHLER] Stats: {e}"


@mcp.resource("bach:/status")
def get_system_status() -> str:
    """BACH System-Status mit Uebersicht."""
    return _execute("status", "run")


@mcp.resource("bach:/memory/lessons")
def get_memory_lessons() -> str:
    """Gelernte Lessons aus dem Memory-System."""
    return _execute("lesson", "list")


@mcp.resource("bach:/memory/status")
def get_memory_status_resource() -> str:
    """Memory-System Uebersicht (Working, Lessons, Facts)."""
    return _execute("memory", "status")


@mcp.resource("bach:/skills/list")
def get_skills_list() -> str:
    """Alle registrierten und aktiven Skills."""
    return _execute("skills", "list")


@mcp.resource("bach:/contacts")
def get_contacts() -> str:
    """Alle aktiven Kontakte."""
    return _execute("contact", "list")


# ------------------------------------------------------------------
# Tools: Task-Management (4)
# ------------------------------------------------------------------

@mcp.tool()
def task_create(title: str, priority: str = "P3",
                category: str = "general",
                assigned_to: str = "") -> str:
    """Erstellt einen neuen Task in BACH.

    Args:
        title: Titel des Tasks
        priority: P1 (kritisch), P2 (hoch), P3 (normal), P4 (niedrig)
        category: Kategorie (general, bug, feature, etc.)
        assigned_to: Zugewiesen an (user, claude, gemini, etc.)
    """
    args = [title, "--priority", priority]
    if category and category != "general":
        args.extend(["--category", category])
    if assigned_to:
        args.extend(["--assign", assigned_to])
    return _execute("task", "add", args)


@mcp.tool()
def task_done(task_id: int) -> str:
    """Markiert einen Task als erledigt."""
    return _execute("task", "done", [str(task_id)])


@mcp.tool()
def task_search(query: str, status: str = "pending") -> str:
    """Durchsucht Tasks nach Titel oder Beschreibung.

    Args:
        query: Suchbegriff
        status: Filter (pending, done, in_progress, all)
    """
    args = ["--filter", query]
    if status and status != "all":
        args.append(status)
    return _execute("task", "list", args)


@mcp.tool()
def task_list(status: str = "pending", priority: str = "") -> str:
    """Listet Tasks auf mit optionalen Filtern.

    Args:
        status: Filter (pending, done, in_progress, all)
        priority: Optional: nur diese Prioritaet (P1, P2, P3, P4)
    """
    args = []
    if status:
        args.extend(["--status", status])
    if priority:
        args.extend(["--priority", priority])
    return _execute("task", "list", args)


# ------------------------------------------------------------------
# Tools: Memory & Lessons (6)
# ------------------------------------------------------------------

@mcp.tool()
def memory_write(lesson: str, category: str = "general",
                 source: str = "mcp") -> str:
    """Schreibt eine neue Lesson ins Memory-System (Langzeitgedaechtnis).

    Args:
        lesson: Text der Lesson/Erkenntnis
        category: Kategorie (general, code, workflow, etc.)
        source: Quelle (mcp, user, system)
    """
    args = [lesson]
    if category and category != "general":
        args.extend(["--category", category])
    return _execute("lesson", "add", args)


@mcp.tool()
def memory_note(text: str) -> str:
    """Schreibt eine Notiz ins Working Memory (Kurzzeitgedaechtnis).

    Args:
        text: Notiz-Text
    """
    return _execute("memory", "write", [text])


@mcp.tool()
def memory_search(query: str) -> str:
    """Durchsucht Lessons und Working Memory nach Stichworten.

    Args:
        query: Suchbegriff
    """
    lesson_result = _execute("lesson", "search", [query])
    memory_result = _execute("memory", "search", [query])
    return f"{lesson_result}\n\n{memory_result}"


@mcp.tool()
def memory_facts(category: str = "", min_confidence: float = 0.0) -> str:
    """Fakten aus dem Memory-System abrufen (verifiziertes Wissen).

    Args:
        category: Optional: nur Fakten dieser Kategorie
        min_confidence: Minimale Konfidenz (0.0 - 1.0)
    """
    args = []
    if category:
        args.extend(["--category", category])
    return _execute("memory", "facts", args)


@mcp.tool()
def memory_status() -> str:
    """Zeigt Memory-System Status (Working Memory, Lessons, Facts Counts)."""
    return _execute("memory", "status")


@mcp.tool()
def lesson_search(query: str, category: str = "") -> str:
    """Durchsucht gezielt die Lessons-Datenbank.

    Args:
        query: Suchbegriff
        category: Optional: nur in dieser Kategorie suchen
    """
    args = [query]
    if category:
        args.extend(["--category", category])
    return _execute("lesson", "search", args)


# ------------------------------------------------------------------
# Tools: Backup (2)
# ------------------------------------------------------------------

@mcp.tool()
def backup_create() -> str:
    """Erstellt ein Backup der BACH-Datenbank."""
    return _execute("backup", "create")


@mcp.tool()
def backup_list() -> str:
    """Zeigt alle vorhandenen Backups mit Groesse und Datum."""
    return _execute("backup", "list")


# ------------------------------------------------------------------
# Tools: Domain (2)
# ------------------------------------------------------------------

@mcp.tool()
def steuer_status(jahr: str = "") -> str:
    """Steuer-Status: Posten, Summen und offene Belege fuer ein Jahr.

    Args:
        jahr: Steuerjahr (Default: aktuelles Jahr)
    """
    args = [jahr] if jahr else []
    return _execute("steuer", "status", args)


@mcp.tool()
def contact_search(query: str) -> str:
    """Durchsucht Kontakte nach Name, Email, Telefon, Firma.

    Args:
        query: Suchbegriff
    """
    return _execute("contact", "search", [query])


# ------------------------------------------------------------------
# Tools: Kommunikation (3)
# ------------------------------------------------------------------

@mcp.tool()
def msg_send(recipient: str, text: str) -> str:
    """Sendet eine Nachricht an einen BACH-Partner.

    Args:
        recipient: Empfaenger (user, claude, gemini, bach, ollama)
        text: Nachrichtentext
    """
    return _execute("msg", "send", [recipient, text])


@mcp.tool()
def msg_unread() -> str:
    """Zeigt ungelesene Nachrichten in der BACH-Inbox."""
    return _execute("msg", "unread")


@mcp.tool()
def notify_send(channel: str, text: str) -> str:
    """Sendet eine Benachrichtigung ueber einen konfigurierten Channel.

    Args:
        channel: discord, signal, email, telegram, webhook
        text: Benachrichtigungstext
    """
    return _execute("notify", "send", [channel, text])


# ------------------------------------------------------------------
# Tools: Session (2)
# ------------------------------------------------------------------

@mcp.tool()
def session_startup() -> str:
    """Fuehrt das BACH-Startprotokoll aus.

    Initialisiert die Session: Directory-Scan, Memory-Check,
    Partner-Status, ungelesene Nachrichten, Briefing.
    """
    return _execute("startup", "run")


@mcp.tool()
def session_shutdown() -> str:
    """Fuehrt das BACH-Shutdown-Protokoll aus.

    Beendet die Session: Working Memory sichern, Auto-Summary,
    Task-Statistik, Directory-Scan, Session-Speicherung.
    """
    return _execute("shutdown", "complete")


# ------------------------------------------------------------------
# Tools: Partner (2)
# ------------------------------------------------------------------

@mcp.tool()
def partner_list() -> str:
    """Listet alle BACH-Partner auf (Human, Local AI, External AI)."""
    return _execute("partner", "list")


@mcp.tool()
def partner_status() -> str:
    """Zeigt den Status aller Partner (aktiv, verfuegbar, Token-Zone)."""
    return _execute("partner", "status")


# ------------------------------------------------------------------
# Tools: System (2)
# ------------------------------------------------------------------

@mcp.tool()
def healthcheck() -> str:
    """Fuehrt System-Gesundheitschecks aus (Disk, Netzwerk, DB)."""
    return _execute("healthcheck", "status")


# Erlaubte Tabellen fuer db_query (Whitelist statt Blacklist)
SAFE_TABLES = {
    # System
    "system_config", "system_identity", "boot_checks", "distribution_manifest",
    # Tasks
    "tasks", "task_history", "ati_tasks", "ati_scan_config", "ati_scan_runs", "ati_tool_registry",
    # Memory
    "memory_working", "memory_lessons", "memory_facts", "memory_sessions",
    "memory_context", "memory_consolidation",
    # Messages / Kommunikation
    "messages", "comm_messages", "connector_messages",
    # Kontakte / Partner
    "contacts", "partner_recognition", "partner_presence",
    # Skills / Tools / Agents
    "skills", "agents", "bach_agents", "bach_experts", "agent_expert_mapping", "agent_synergies",
    "tools", "tool_registry", "tool_patterns", "toolchains", "toolchain_runs",
    "usecases", "wiki_articles",
    # Kalender / Gesundheit
    "calendar_events", "health_appointments", "health_contacts", "health_diagnoses",
    "health_documents", "health_lab_values", "health_medications", "vorsorge_checks",
    # Finanzen / Steuer
    "steuer_posten", "steuer_dokumente", "steuer_profile", "steuer_auswertung",
    "steuer_anbieter", "steuer_ocr_cache", "steuer_watch_ordner",
    "household_finances", "household_inventory", "household_routines",
    "household_shopping_items", "household_shopping_lists",
    "abo_subscriptions", "abo_payments", "abo_patterns",
    "bank_accounts", "fin_contracts", "fin_insurances", "fin_insurance_claims",
    "financial_emails", "financial_subscriptions", "financial_summary",
    "credits", "irregular_costs", "monitor_pricing", "insurance_types",
    # Monitoring / Logs
    "monitor_tokens", "monitor_processes", "monitor_success",
    "folder_scans", "folder_scan_files", "scan_config", "scan_runs",
    "session_snapshots", "backup_snapshots", "import_runs",
    # Automation / Daemon
    "scheduler_jobs", "scheduler_runs", "routines", "automation_routines",
    "automation_triggers", "automation_injectors",
    "delegation_rules", "context_triggers", "hierarchy_types",
    "hierarchy_items", "hierarchy_assignments",
    # Sonstiges
    "assistant_briefings", "assistant_calendar", "assistant_contacts",
    "document_index", "files_trash", "files_truth",
    "interactionworkflows", "languages_config", "languages_dictionary", "languages_translations",
    "psycho_observations", "psycho_sessions", "user_preferences", "user_data_folders",
    "selfmgmt_adhd_strategies", "selfmgmt_career_goals", "selfmgmt_life_circles", "selfmgmt_milestones",
    "workflow_tuev", "between_profiles",
}


def _extract_table_names(sql: str) -> set:
    """Extrahiert Tabellennamen nach FROM und JOIN aus SQL."""
    import re
    tables = set()
    for match in re.finditer(r'\b(?:FROM|JOIN)\s+(\w+)', sql, re.IGNORECASE):
        tables.add(match.group(1).lower())
    return tables


@mcp.tool()
def db_query(query: str) -> str:
    """Fuehrt eine SELECT-Query auf der BACH-Datenbank aus (read-only).

    Power-User Tool fuer direkte DB-Abfragen. Nur SELECT erlaubt.
    Maximal 50 Zeilen Ergebnis. Table-Whitelist verhindert Zugriff
    auf sensitive Tabellen (mail_accounts, connections).

    Args:
        query: SQL SELECT-Query
    """
    q_upper = query.strip().upper()
    if not q_upper.startswith("SELECT"):
        return "Nur SELECT-Queries erlaubt."

    for kw in ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE",
                "ATTACH", "DETACH", "PRAGMA"]:
        if kw in q_upper:
            return f"Query enthaelt verbotenes Keyword: {kw}"

    # Table-Whitelist pruefen
    tables = _extract_table_names(query)
    blocked = tables - SAFE_TABLES
    if blocked:
        return f"Tabelle(n) nicht erlaubt: {', '.join(sorted(blocked))}"

    try:
        conn = sqlite3.connect(BACH_DB_STR)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query).fetchall()
        conn.close()

        if not rows:
            return "(keine Ergebnisse)"

        result_rows = rows[:50]
        cols = result_rows[0].keys()
        lines = [" | ".join(cols), "-" * 60]
        for r in result_rows:
            vals = [str(r[c]) if r[c] is not None else "" for c in cols]
            lines.append(" | ".join(vals))

        if len(rows) > 50:
            lines.append(f"... ({len(rows) - 50} weitere Zeilen)")

        return "\n".join(lines)
    except Exception as e:
        return f"Query-Fehler: {e}"


# ------------------------------------------------------------------
# Resource: Server-Info / Versionierung
# ------------------------------------------------------------------

@mcp.resource("bach:/version")
def get_version_info() -> str:
    """BACH MCP Server Version und Capabilities."""
    db_size = ""
    if BACH_DB_PATH.exists():
        db_size = f"{BACH_DB_PATH.stat().st_size / (1024*1024):.1f} MB"

    return "\n".join([
        f"BACH MCP Server v{__version__}",
        f"Backend: bach_api (Handler-basiert)",
        f"DB: {db_size}",
        "",
        "Capabilities:",
        f"  Resources: 8",
        f"  Tools: 23",
        f"  Prompts: 3",
        "",
        "Transport: stdio",
        "Protokoll: JSON-RPC 2.0 (MCP)",
        f"SDK: FastMCP (Python)",
    ])


# ------------------------------------------------------------------
# Prompts (wiederverwendbare Vorlagen)
# ------------------------------------------------------------------

@mcp.prompt()
def daily_briefing() -> str:
    """Erstellt ein taegliches Briefing mit Tasks, Nachrichten und Systemstatus.

    Fasst den aktuellen BACH-Status zusammen und gibt Empfehlungen
    fuer den Tag.
    """
    tasks = _execute("task", "list")
    messages = _execute("msg", "unread")
    mem_status = _execute("memory", "status")

    return (
        "Erstelle ein kurzes taegliches Briefing basierend auf diesen BACH-Daten.\n"
        "Fasse zusammen: offene Tasks (nach Prioritaet), ungelesene Nachrichten, "
        "Memory-Status. Gib 2-3 konkrete Empfehlungen fuer heute.\n\n"
        f"=== TASKS ===\n{tasks}\n\n"
        f"=== NACHRICHTEN ===\n{messages}\n\n"
        f"=== MEMORY ===\n{mem_status}"
    )


@mcp.prompt()
def task_review() -> str:
    """Analysiert offene Tasks und schlaegt Priorisierung vor.

    Sammelt alle offenen Tasks und fragt nach einer Bewertung
    der Prioritaeten und naechsten Schritte.
    """
    tasks = _execute("task", "list")
    return (
        "Analysiere diese offenen BACH-Tasks. Pruefe ob die Prioritaeten "
        "sinnvoll sind und schlage eine Reihenfolge fuer die Bearbeitung vor. "
        "Identifiziere Tasks die zusammengehoeren oder blockiert sein koennten.\n\n"
        f"{tasks}"
    )


@mcp.prompt()
def session_summary(topic: str = "diese Session") -> str:
    """Erstellt eine Session-Zusammenfassung fuer BACH.

    Generiert einen strukturierten Summary der aktuellen Arbeit,
    der als Memory-Eintrag gespeichert werden kann.

    Args:
        topic: Thema oder Kontext der Session
    """
    return (
        f"Erstelle eine kurze, strukturierte Zusammenfassung zum Thema: {topic}\n\n"
        "Format:\n"
        "- Was wurde gemacht (2-3 Saetze)\n"
        "- Ergebnisse / Entscheidungen\n"
        "- Offene Punkte / Naechste Schritte\n\n"
        "Die Zusammenfassung soll als BACH Memory-Eintrag tauglich sein "
        "(kompakt, informativ, ohne Floskeln)."
    )


# ------------------------------------------------------------------
# Server starten
# ------------------------------------------------------------------

if __name__ == "__main__":
    logger.info(f"BACH MCP Server v{__version__} startet")
    logger.info(f"  System: {BACH_SYSTEM}")
    logger.info(f"  DB: {BACH_DB_PATH}")
    logger.info(f"  Backend: bach_api (Handler-basiert)")
    logger.info(f"  Resources: 8 | Tools: 23 | Prompts: 3")
    mcp.run()
