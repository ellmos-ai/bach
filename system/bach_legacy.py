#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
bach.py - BACH v1.2.0 Unified CLI
==================================

Kombiniert Handler-System (ex hub.py) mit DB-Funktionen (ex bach_legacy.py)

NEUE STRUKTUR (v1.2.0):
    BACH_test/              <- BACH_ROOT (Repository Root)
    ├── system/             <- SYSTEM_ROOT (wo diese Datei liegt)
    │   ├── bach.py         <- Diese Datei
    │   ├── hub/
    │   ├── data/
    │   ├── gui/
    │   └── skills/
    │       ├── tools/
    │       ├── docs/help/
    │       └── partners/
    └── user/

Usage:
    python bach.py --startup
    python bach.py --help [thema]
    python bach.py task add "Titel"
    python bach.py backup create [--to-nas]
    python bach.py --shutdown
"""

import sys
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

# ═══════════════════════════════════════════════════════════════
# PFADE (Neue Struktur v1.2.0)
# ═══════════════════════════════════════════════════════════════

# Diese Datei liegt in: system/bach.py
SYSTEM_ROOT = Path(__file__).parent              # system/
BACH_ROOT = SYSTEM_ROOT.parent                   # Repository Root (BACH_test/)

# Alte Variable für Rückwärtskompatibilität
BACH_DIR = SYSTEM_ROOT

# System-Verzeichnisse
DATA_DIR = SYSTEM_ROOT / "data"
HUB_DIR = SYSTEM_ROOT / "hub"
GUI_DIR = SYSTEM_ROOT / "gui"
SKILLS_DIR = SYSTEM_ROOT / "skills"

# Skills-Unterverzeichnisse (neue Struktur)
HELP_DIR = SKILLS_DIR / "help"
PARTNERS_DIR = SKILLS_DIR / "_partners"

# Tools-Verzeichnis (direkt unter system/, nicht unter skills/)
# KORRIGIERT 2026-02-05: Tools liegen unter system/tools/, nicht skills/tools/
TOOLS_DIR = SYSTEM_ROOT / "tools"

# Data-Unterverzeichnisse
LOGS_DIR = DATA_DIR / "logs"
BACKUPS_DIR = DATA_DIR / "_backups"
MEMORY_DIR = DATA_DIR / "memory"  # Falls verwendet

# Datenbanken — zentral erfragt (hub/bach_paths.py), nicht selbst gebaut.
# DATA_DIR/bach.db waere die veraltete Kopie im OneDrive-Ordner.
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))
from hub.bach_paths import BACH_DB as DB_PATH

USER_DB_PATH = DB_PATH    # User-DB (migriert v1.1.84)

# Root-Verzeichnisse
USER_DIR = BACH_ROOT / "user"
DOCS_DIR = BACH_ROOT / "docs"
EXPORTS_DIR = BACH_ROOT / "exports"
DISTRIBUTIONS_DIR = SYSTEM_ROOT / "dist"

# ═══════════════════════════════════════════════════════════════
# DATABASE FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def get_db():
    """System-Datenbank-Verbindung holen"""
    return sqlite3.connect(DB_PATH)

def get_user_db():
    """User-Datenbank-Verbindung holen (NEU v1.1)
    
    TODO: Aktuell ungenutzt - für zukünftige User-DB Features vorgesehen.
    """
    return sqlite3.connect(USER_DB_PATH)

def db_query(sql, params=()):
    """SQL-Query ausführen"""
    with get_db() as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql, params).fetchall()

def db_execute(sql, params=()):
    """SQL-Statement ausführen"""
    with get_db() as conn:
        conn.execute(sql, params)
        conn.commit()

# ═══════════════════════════════════════════════════════════════
# AUTO-LOGGER & PATH EXTENSION
# ═══════════════════════════════════════════════════════════════

# Skills_DIR zu sys.path hinzufügen damit 'import tools' funktioniert (v1.2.0)
if str(SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR))

try:
    # Neue Struktur: skills/tools/autolog.py
    sys.path.insert(0, str(SKILLS_DIR / "tools"))
    from autolog import get_logger, log, cmd
except ImportError:
    # Fallback wenn autolog nicht verfügbar
    def get_logger(path=None):
        class DummyLogger:
            def log(self, msg): pass
            def cmd(self, c, a=None, r=""): pass
            def chat(self, m, s="claude"): pass
        return DummyLogger()
    def log(msg): pass
    def chat(msg): pass
    def cmd(c, a=None, r=""): pass

# ═══════════════════════════════════════════════════════════════
# HANDLER IMPORTS
# ═══════════════════════════════════════════════════════════════

def get_handler(profile_name: str):
    """Erstellt passenden Handler fuer Profil."""
    handlers = {
        "help": lambda: _import_handler("help", "HelpHandler"),
        "memory": lambda: _import_handler("memory", "MemoryHandler"),
        "startup": lambda: _import_handler("startup", "StartupHandler"),
        "shutdown": lambda: _import_handler("shutdown", "ShutdownHandler"),
        "status": lambda: _import_handler("status", "StatusHandler"),
        "context": lambda: _import_handler("context", "ContextHandler"),
        "inject": lambda: _import_handler("inject", "InjectHandler"),
        "backup": lambda: _import_handler("backup", "BackupHandler"),
        "cv": lambda: _import_handler("cv", "CVHandler"),
        "db": lambda: _import_handler("db", "DbHandler"),
        "tokens": lambda: _import_handler("tokens", "TokensHandler"),
        "agents": lambda: _import_handler("agents", "AgentsHandler"),
        "dist": lambda: _import_handler("dist", "DistHandler"),
        "scan": lambda: _import_handler("scan", "ScanHandler"),
        "gui": lambda: _import_handler("gui", "GuiHandler"),
        "daemon": lambda: _import_handler("daemon", "DaemonHandler"),
        "steuer": lambda: _import_handler("steuer", "SteuerHandler"),
        "abo": lambda: _import_handler("abo", "AboHandler"),
        "ati": lambda: _import_handler("ati", "ATIHandler"),
        "skills": lambda: _import_handler("skills", "SkillsHandler"),
        "trash": lambda: _import_handler("trash", "TrashHandler"),
        "tools": lambda: _import_handler("tools", "ToolsHandler"),
        "logs": lambda: _import_handler("logs", "LogsHandler"),
        "docs": lambda: _import_handler("docs", "DocsHandler"),
        "doc": lambda: _import_handler("doc", "DocHandler"),
        "connections": lambda: _import_handler("connections", "ConnectionsHandler"),
        "lesson": lambda: _import_handler("lesson", "LessonHandler"),
        "wiki": lambda: _import_handler("wiki", "WikiHandler"),
        "msg": lambda: _import_handler("messages", "MessagesHandler"),
        "test": lambda: _import_handler("test", "TestHandler"),
        "maintain": lambda: _import_handler("maintain", "MaintainHandler"),
        "mount": lambda: _import_handler("mount", "MountHandler"),
        "sources": lambda: _import_handler("sources", "SourcesHandler"),
        "partner": lambda: _import_handler("partner", "PartnerHandler"),
        "ollama": lambda: _import_handler("ollama", "OllamaHandler"),
        "snapshot": lambda: _import_handler("snapshot", "SnapshotHandler"),
        "data": lambda: _import_handler("data_analysis", "DataAnalysisHandler"),
        "recurring": lambda: _import_handler("recurring", "RecurringHandler"),
        "routine": lambda: _import_handler("routine", "RoutineHandler"),
        "calendar": lambda: _import_handler("calendar_handler", "CalendarHandler"),
        "contact": lambda: _import_handler("contact", "ContactHandler"),
        "gesundheit": lambda: _import_handler("gesundheit", "GesundheitHandler"),
        "haushalt": lambda: _import_handler("haushalt", "HaushaltHandler"),
        "versicherung": lambda: _import_handler("versicherung", "VersicherungHandler"),
        "task": lambda: _import_handler("task", "TaskHandler"),
        "session": lambda: _import_handler("session", "SessionHandler"),
        "inbox": lambda: _import_handler("inbox", "InboxHandler"),
        "sync": lambda: _import_handler("sync", "SyncHandler"),
        "consolidate": lambda: _import_handler("consolidation", "ConsolidationHandler"),
        "bericht": lambda: _import_handler("bericht", "BerichtHandler"),
        "llm": lambda: _import_handler("multi_llm_protocol", "MultiLLMHandler"),
        "chain": lambda: _import_handler("chain", "ChainHandler"),
        # Zeit-System (v1.1.83)
        "clock": lambda: _import_handler("time", "ClockHandler"),
        "timer": lambda: _import_handler("time", "TimerHandler"),
        "countdown": lambda: _import_handler("time", "CountdownHandler"),
        "between": lambda: _import_handler("time", "BetweenHandler"),
        "beat": lambda: _import_handler("time", "BeatHandler"),
        # Workflow-TUeV (v1.1.83)
        "tuev": lambda: _import_handler("tuev", "TuevHandler"),
        "usecase": lambda: _import_handler("tuev", "UsecaseHandler"),
        # Filesystem Protection (v1.1.84)
        "fs": lambda: _import_handler("fs", "FSHandler"),
        # Path-Info (v1.1.74)
        "path": lambda: _import_handler("path", "PathHandler"),
        # Language/Translation System (v1.1.85)
        "lang": lambda: _import_handler("lang", "LangHandler"),
        # Extensions (v1.1.86)
        "extensions": lambda: _import_handler("extensions", "ExtensionsHandler"),
    }
    
    if profile_name in handlers:
        try:
            return handlers[profile_name]()
        except Exception as e:
            print(f"[WARN] Handler '{profile_name}' nicht ladbar: {e}")
            return None
    
    return None


def _import_handler(module_name: str, class_name: str):
    """Importiert Handler dynamisch."""
    import importlib
    module = importlib.import_module(f"hub.{module_name}")
    handler_class = getattr(module, class_name)
    return handler_class(BACH_DIR)

# ═══════════════════════════════════════════════════════════════
# LEGACY COMMANDS (aus bach_legacy.py)
# ═══════════════════════════════════════════════════════════════

# HINWEIS: Task-Funktionen wurden nach hub/handlers/task.py migriert
# Nutze: bach task add/list/done/block/unblock/reopen/delete

def cmd_mem_write(text):
    """In memory_working (DB) schreiben"""
    with get_db() as conn:
        now = datetime.now().isoformat()
        conn.execute("""
            INSERT INTO memory_working (type, content, created_at, updated_at)
            VALUES ('note', ?, ?, ?)
        """, (text, now, now))
        conn.commit()
    print(f"[OK] Notiz gespeichert.")

def cmd_mem_read():
    """Letzte Notizen aus memory_working lesen"""
    rows = db_query("""
        SELECT content, created_at FROM memory_working
        WHERE is_active = 1 ORDER BY created_at DESC LIMIT 10
    """)
    if not rows:
        print("Keine Notizen im Working Memory.")
    else:
        for r in rows:
            time = r['created_at'][11:16] if r['created_at'] else "?"
            print(f"[{time}] {r['content']}")

def cmd_mem_status():
    """Memory-Statistik anzeigen"""
    print("\n=== MEMORY STATUS ===\n")

    # Working Memory
    working = db_query("SELECT COUNT(*) as cnt FROM memory_working WHERE is_active = 1")
    working_cnt = working[0]['cnt'] if working else 0
    print(f"Working Memory:  {working_cnt} aktive Notizen")

    # Facts
    facts = db_query("SELECT category, COUNT(*) as cnt FROM memory_facts GROUP BY category")
    facts_total = sum(r['cnt'] for r in facts) if facts else 0
    print(f"Facts:           {facts_total} Eintraege")
    if facts:
        for r in facts:
            print(f"  - {r['category']}: {r['cnt']}")

    # Lessons
    lessons = db_query("SELECT COUNT(*) as cnt FROM memory_lessons")
    lessons_cnt = lessons[0]['cnt'] if lessons else 0
    print(f"Lessons:         {lessons_cnt} Eintraege")

    # Sessions
    sessions = db_query("SELECT COUNT(*) as cnt FROM memory_sessions")
    sessions_cnt = sessions[0]['cnt'] if sessions else 0
    print(f"Sessions:        {sessions_cnt} Eintraege")

    print()

def cmd_mem_clear():
    """Working Memory leeren (deaktivieren)"""
    with get_db() as conn:
        now = datetime.now().isoformat()
        result = conn.execute("""
            UPDATE memory_working SET is_active = 0, updated_at = ? WHERE is_active = 1
        """, (now,))
        conn.commit()
        count = result.rowcount
    print(f"[OK] {count} Notizen deaktiviert.")

def cmd_mem_archive():
    """Session archivieren - Working Memory in Session speichern"""
    # Hole alle aktiven Notizen
    rows = db_query("""
        SELECT content, created_at FROM memory_working
        WHERE is_active = 1 ORDER BY created_at ASC
    """)

    if not rows:
        print("Keine Notizen zum Archivieren.")
        return

    # Erstelle Session-Summary aus Notizen
    notes = [r['content'] for r in rows]
    summary = "Archivierte Notizen:\n- " + "\n- ".join(notes)

    with get_db() as conn:
        now = datetime.now().isoformat()
        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Session speichern
        conn.execute("""
            INSERT INTO memory_sessions (session_id, started_at, ended_at, summary)
            VALUES (?, ?, ?, ?)
        """, (session_id, rows[0]['created_at'], now, summary))

        # Working Memory deaktivieren
        conn.execute("UPDATE memory_working SET is_active = 0, updated_at = ? WHERE is_active = 1", (now,))
        conn.commit()

    print(f"[OK] {len(rows)} Notizen archiviert in Session {session_id}")

def cmd_mem_reset():
    """Working Memory komplett zuruecksetzen (loeschen)"""
    with get_db() as conn:
        result = conn.execute("DELETE FROM memory_working WHERE is_active = 1")
        conn.commit()
        count = result.rowcount
    print(f"[OK] {count} Notizen geloescht.")

def _get_backup_manager():
    """Importiert BackupManager bei Bedarf."""
    sys.path.insert(0, str(TOOLS_DIR))
    try:
        from backup_manager import BackupManager
        return BackupManager()
    except ImportError as e:
        print(f"[FEHLER] backup_manager.py nicht gefunden: {e}")
        return None

def cmd_backup_create(to_nas=False):
    """Backup erstellen"""
    manager = _get_backup_manager()
    if manager:
        success, msg = manager.create_backup(to_nas=to_nas)
        return success
    return False

def cmd_backup_list(show_nas=False):
    """Backups auflisten"""
    manager = _get_backup_manager()
    if manager:
        manager.print_backup_list(show_nas=show_nas)

def cmd_restore_backup(name, force=False, auto_backup=True):
    """Aus Backup wiederherstellen"""
    manager = _get_backup_manager()
    if manager:
        success, msg = manager.restore_backup(name, force=force, auto_backup=auto_backup)
        return success
    return False

def cmd_dist_create(name, version=None):
    """Distribution erstellen"""
    DISTRIBUTIONS_DIR.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y-%m-%d")
    version_str = version or "1.1.0"
    zip_name = f"{name}_v{version_str}_{timestamp}.zip"
    zip_path = DISTRIBUTIONS_DIR / zip_name
    
    print(f"\n[DIST] Erstelle Distribution: {zip_name}")
    
    import zipfile
    exclude_dirs = {"_backups", "memory", "logs", "user", "__pycache__", ".git", "distributions"}
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for item in BACH_DIR.rglob("*"):
            if item.is_file():
                rel_path = item.relative_to(BACH_DIR)
                skip = any(exc in rel_path.parts for exc in exclude_dirs)
                if not skip and not item.name.endswith(('.pyc', '.log')):
                    zf.write(item, rel_path)
        
        manifest = {"name": name, "version": version_str, "created_at": datetime.now().isoformat()}
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
    
    print(f"  ✓ Distribution erstellt: {zip_name}")
    return True

def cmd_dist_list():
    """Distributionen auflisten"""
    print("\n[DIST] Verfügbare Distributionen\n")
    if not DISTRIBUTIONS_DIR.exists():
        print("  Keine Distributionen gefunden.")
        return
    dists = list(DISTRIBUTIONS_DIR.glob("*.zip"))
    for d in sorted(dists, reverse=True):
        size = f"{d.stat().st_size / (1024*1024):.2f} MB"
        print(f"  {d.name:<40} {size:>10}")
    print()

def cmd_db_status():
    """Datenbank-Status"""
    print("\n[DB] BACH DATABASE\n")
    tables = db_query("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """)
    print(f"Tabellen: {len(tables)}")
    for t in tables:
        count = db_query(f"SELECT COUNT(*) as cnt FROM {t['name']}")[0]['cnt']
        print(f"  {t['name']}: {count} Einträge")
    print()

def cmd_tokens_status():
    """Token-Status anzeigen"""
    print("\n[TOKENS] TOKEN STATUS\n")
    today = db_query("""
        SELECT SUM(tokens_total) as total, SUM(cost_eur) as cost
        FROM monitor_tokens WHERE date(timestamp) = date('now')
    """)[0]
    week = db_query("""
        SELECT SUM(tokens_total) as total, SUM(cost_eur) as cost
        FROM monitor_tokens WHERE timestamp >= date('now', '-7 days')
    """)[0]
    print(f"Heute:  {today['total'] or 0:,} Tokens ({today['cost'] or 0:.2f}€)")
    print(f"Woche:  {week['total'] or 0:,} Tokens ({week['cost'] or 0:.2f}€)")
    print()

# ═══════════════════════════════════════════════════════════════
# INJEKTOREN
# ═══════════════════════════════════════════════════════════════

_injector_system = None

def _get_injector():
    """Lazy-Load Injektor-System."""
    global _injector_system
    if _injector_system is None:
        try:
            sys.path.insert(0, str(TOOLS_DIR))
            from injectors import InjectorSystem
            _injector_system = InjectorSystem(SYSTEM_ROOT)
        except Exception:
            pass
    return _injector_system

def _run_injectors(text: str, last_command: str = ""):
    """Fuehrt Injektoren aus und gibt Ergebnisse aus."""
    injector = _get_injector()
    if not injector:
        return

    # Text-basierte Injektionen (Strategy, Context, Time)
    injections = injector.process(text)
    for inj in injections:
        print(f"\n{inj}")

    # Between-Tasks Check (nach task done)
    if "done" in last_command.lower():
        between = injector.check_between(last_command)
        if between:
            print(f"\n{between}")

# ═══════════════════════════════════════════════════════════════
# HELP
# ═══════════════════════════════════════════════════════════════

def print_help():
    """Zeigt Hilfe an."""
    help_text = """
BACH v1.1.32 - Best-of CLI

USAGE:
  python bach.py <befehl> [operation] [args]
  python bach.py --<handler> [operation] [args]

SESSION:
  --startup              Komplettes Startprotokoll
  --shutdown [note]      Session beenden
  --status               Schnelle System-Uebersicht

TASKS:
  task add "Titel"       Task hinzufuegen
  task list              Offene Tasks
  task done <id>         Task erledigen

MEMORY:
  mem write "Text"       Notiz schreiben
  mem read               Session-Memory lesen
  --memory status        Memory-Handler (facts, sessions, context)

LESSONS:
  lesson add "Titel"     Lesson hinzufuegen
  lesson list            Lessons auflisten
  lesson search "..."    Durchsuchen

MESSAGES:
  msg list               Nachrichten anzeigen
  msg send <to> <text>   Nachricht senden

PARTNER:
  partner list           Partner-Netzwerk (10 Partner)
  partner status         Aktive Partner
  partner delegate       Task delegieren

GUI & DAEMON:
  gui start              Web-Dashboard starten
  gui start-bg           Im Hintergrund starten
  daemon start           Daemon-Service (zeitgesteuerte Jobs)
  daemon jobs            Jobs anzeigen

RECURRING (Task-Erinnerungen):
  --recurring            Wiederkehrende Tasks anzeigen
  --recurring check      Faellige Tasks erstellen

WARTUNG:
  --maintain heal        Pfad-Korrektur
  --maintain registry    DB/JSON Konsistenz
  --maintain skills      Skill-Gesundheit

SCANNER:
  scan run               Task-Scan starten
  scan tasks             Gescannte Tasks

BACKUP:
  backup create          Backup erstellen
  backup list            Backups auflisten

STEUER:
  steuer status          Beleg-/Posten-Status
  steuer beleg list      Alle Belege

DATABASE:
  --db status            DB-Uebersicht
  --tokens status        Token-Verbrauch

HILFE:
  help                   Diese Hilfe (auch: --help)
  help <topic>           Hilfe zu Thema (auch: --help <topic>)
  help cli               CLI-Konventionen
"""
    print(help_text)
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    """Haupteinstiegspunkt."""
    # Windows-Konsolen-Encoding fixen
    if sys.platform == 'win32':
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        except:
            pass
    
    # Auto-Logger initialisieren (Cleanup passiert automatisch)
    logger = get_logger(BACH_DIR)
    
    if len(sys.argv) < 2 or sys.argv[1] in ['-h', '--help', 'help']:
        if len(sys.argv) > 2:
            # --help <topic> oder help <topic>
            handler = get_handler("help")
            if handler:
                topic = sys.argv[2]
                success, message = handler.handle(topic, [])
                print(message)
                return 0
        print_help()
        return 0

    arg = sys.argv[1]
    
    # Handler-basierte Befehle (--startup, --shutdown, etc.)
    if arg.startswith('--'):
        profile_name = arg[2:]
        
        # Spezielle DB-Befehle
        if profile_name == "db":
            cmd_db_status()
            return 0
        elif profile_name == "tokens":
            cmd_tokens_status()
            return 0
        
        # Handler laden (inkl. agents - nutzt jetzt den erweiterten Handler)
        handler = get_handler(profile_name)
        if handler:
            # Args ab Position 2 holen
            remaining_args = sys.argv[2:] if len(sys.argv) > 2 else []

            # Erste Nicht-Flag-Argument ist Operation (für startup/shutdown gibt es keine)
            # Flags (--partner=X, --mode=X) bleiben in args
            operation = ""
            args = []
            for i, a in enumerate(remaining_args):
                if not a.startswith("--") and not operation:
                    operation = a
                else:
                    args.append(a)

            # Bei startup/shutdown: kein Operation-Argument nötig
            if profile_name in ("startup", "shutdown") and operation:
                # operation war eigentlich ein arg
                args = [operation] + args
                operation = ""

            try:
                cmd(profile_name, [operation] + args)
                success, message = handler.handle(operation, args)
                print(message)
                # Injektoren auf Output anwenden
                _run_injectors(message, f"{profile_name} {operation}")
                
                # v1.1.73: Auto-Watch bei --startup --watch
                if profile_name == "startup" and "--watch" in args:
                    # Partner aus args extrahieren
                    partner = "user"
                    for a in args:
                        if a.startswith("--partner="):
                            partner = a.split("=")[1]
                    print(f"\n[AUTO-WATCH] Starte Nachrichten-Polling fuer {partner.upper()}...")
                    from hub.messages import MessagesHandler
                    msg_handler = MessagesHandler(SYSTEM_ROOT)
                    msg_handler._watch_messages(partner)
                
                return 0 if success else 1
            except Exception as e:
                log(f"[ERROR] {e}")
                print(f"[ERROR] {e}")
                return 1
        else:
            suggestion = _suggest_command(arg)
            print(f"Unbekannter Befehl: {arg}")
            if suggestion:
                print(suggestion)
            return 1
    
    # Subcommands (task, mem, backup, etc.)
    command = arg
    sub_cmd = sys.argv[2] if len(sys.argv) > 2 else ""
    args = sys.argv[3:] if len(sys.argv) > 3 else []
    
    if command == "task":
        # Task-Handler aufrufen (mit Multi-ID Support)
        handler = get_handler("task")
        if handler:
            operation = sub_cmd or "list"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                _run_injectors(message, f"task {operation}")
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Task-Handler nicht verfuegbar")
            return 1
    
    
    elif command == "mem":
        if sub_cmd == "write" and args:
            cmd_mem_write(" ".join(args))
        elif sub_cmd == "read":
            cmd_mem_read()
        elif sub_cmd == "status":
            cmd_mem_status()
        elif sub_cmd == "clear":
            cmd_mem_clear()
        elif sub_cmd == "archive":
            cmd_mem_archive()
        elif sub_cmd == "reset":
            cmd_mem_reset()
        else:
            print("Usage: bach mem write|read|status|clear|archive|reset")
    
    elif command == "backup":
        if sub_cmd == "create":
            cmd_backup_create("--to-nas" in args)
        elif sub_cmd == "list":
            cmd_backup_list()
        else:
            print("Usage: bach backup create|list")
    
    elif command == "cv":
        handler = get_handler("cv")
        if handler:
            op = sub_cmd or "status"
            ok, msg = handler.handle(op, args, dry_run="--dry-run" in args)
            print(msg)
        else:
            print("[FEHLER] CV-Handler nicht verfuegbar")

    elif command == "map":
        # Call Graph / Dependency Mapper
        if str(TOOLS_DIR) not in sys.path:
            sys.path.insert(0, str(TOOLS_DIR))
        try:
            from call_graph import generate_view
            view = sub_cmd or "status"
            filt = None
            for i, a in enumerate(args):
                if a in ("--filter", "-f") and i + 1 < len(args):
                    filt = args[i + 1]
            print(generate_view(view, filt))
        except Exception as e:
            print(f"[FEHLER] Call Graph: {e}")

    elif command == "restore":
        if sub_cmd == "backup" and args:
            cmd_restore_backup(args[0])
        else:
            print("Usage: bach restore backup <name>")

    elif command == "dist":
        if sub_cmd == "create" and args:
            cmd_dist_create(args[0])
        elif sub_cmd == "list":
            cmd_dist_list()
        else:
            print("Usage: bach dist create|list")
    
    elif command == "steuer":
        # Steuer-Handler aufrufen
        handler = get_handler("steuer")
        if handler:
            operation = sub_cmd or "status"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Steuer-Handler nicht verfuegbar")
            return 1
    
    elif command == "ati":
        # ATI Agent-Handler aufrufen
        handler = get_handler("ati")
        if handler:
            operation = sub_cmd or "status"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] ATI-Handler nicht verfuegbar")
            return 1

    elif command == "abo":
        # Abo-Handler aufrufen (Expert Agent)
        handler = get_handler("abo")
        if handler:
            operation = sub_cmd or "list"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Abo-Handler nicht verfuegbar")
            return 1
    
    elif command == "gui":
        # GUI-Handler aufrufen
        handler = get_handler("gui")
        if handler:
            operation = sub_cmd or "info"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] GUI-Handler nicht verfuegbar")
            return 1
    
    elif command == "daemon":
        # Daemon-Handler aufrufen
        handler = get_handler("daemon")
        if handler:
            operation = sub_cmd or "status"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Daemon-Handler nicht verfuegbar")
            return 1
    
    elif command == "inbox":
        # Inbox-Handler aufrufen
        handler = get_handler("inbox")
        if handler:
            operation = sub_cmd or "status"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Inbox-Handler nicht verfuegbar")
            return 1
    
    elif command == "scan":
        # Scan-Handler aufrufen
        handler = get_handler("scan")
        if handler:
            operation = sub_cmd or "status"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Scan-Handler nicht verfuegbar")
            return 1
    
    elif command == "calendar":
        # Calendar-Handler aufrufen (Termine + Routinen)
        handler = get_handler("calendar")
        if handler:
            operation = sub_cmd or "week"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Calendar-Handler nicht verfuegbar")
            return 1

    elif command == "contact":
        # Contact-Handler aufrufen (Kontaktverwaltung)
        handler = get_handler("contact")
        if handler:
            operation = sub_cmd or "list"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Contact-Handler nicht verfuegbar")
            return 1

    elif command == "doc":
        # Doc-Handler aufrufen (Dokumentensuche)
        handler = get_handler("doc")
        if handler:
            operation = sub_cmd or "help"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Doc-Handler nicht verfuegbar")
            return 1

    elif command == "haushalt":
        # Haushalt-Handler aufrufen (Haushaltsmanagement)
        handler = get_handler("haushalt")
        if handler:
            operation = sub_cmd or "status"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Haushalt-Handler nicht verfuegbar")
            return 1

    elif command == "versicherung":
        # Versicherungs-Handler aufrufen (Versicherungsverwaltung)
        handler = get_handler("versicherung")
        if handler:
            operation = sub_cmd or "status"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Versicherung-Handler nicht verfuegbar")
            return 1

    elif command == "gesundheit":
        # Gesundheits-Handler aufrufen (Gesundheitsassistent)
        handler = get_handler("gesundheit")
        if handler:
            operation = sub_cmd or "status"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Gesundheit-Handler nicht verfuegbar")
            return 1

    elif command == "lang":
        # Lang-Handler aufrufen (Sprach/Übersetzungssystem v1.1.85)
        handler = get_handler("lang")
        if handler:
            operation = sub_cmd or "status"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Lang-Handler nicht verfuegbar")
            return 1

    elif command == "chain":
        # Chain-Handler aufrufen (Toolchain Engine)
        handler = get_handler("chain")
        if handler:
            operation = sub_cmd or "list"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Chain-Handler nicht verfuegbar")
            return 1

    elif command == "routine":
        # Routine-Handler aufrufen (Haushaltsroutinen)
        handler = get_handler("routine")
        if handler:
            operation = sub_cmd or "list"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Routine-Handler nicht verfuegbar")
            return 1

    elif command == "lesson":
        # Lesson-Handler aufrufen
        handler = get_handler("lesson")
        if handler:
            operation = sub_cmd or "list"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Lesson-Handler nicht verfuegbar")
            return 1
    
    elif command == "wiki":
        # Wiki-Handler aufrufen
        handler = get_handler("wiki")
        if handler:
            operation = sub_cmd or "list"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Wiki-Handler nicht verfuegbar")
            return 1
    
    elif command == "tools":
        # Tools-Handler aufrufen
        handler = get_handler("tools")
        if handler:
            operation = sub_cmd or "list"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Tools-Handler nicht verfuegbar")
            return 1
    
    elif command == "tool":
        # Tool-Handler aufrufen (Alias fuer tools)
        handler = get_handler("tools")
        if handler:
            operation = sub_cmd or "list"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Tools-Handler nicht verfuegbar")
            return 1
    
    elif command == "msg":
        # Messages-Handler aufrufen
        handler = get_handler("msg")
        if handler:
            operation = sub_cmd or "list"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Messages-Handler nicht verfuegbar")
            return 1
    
    elif command == "mount":
        # Mount-Handler aufrufen (SYS_001)
        handler = get_handler("mount")
        if handler:
            operation = sub_cmd or "list"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Mount-Handler nicht verfuegbar")
            return 1

    elif command == "partner":
        # Partner-Handler aufrufen
        handler = get_handler("partner")
        if handler:
            operation = sub_cmd or "list"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Partner-Handler nicht verfuegbar")
            return 1

    elif command == "session":
        # Session-Handler aufrufen (SESSION_001)
        handler = get_handler("session")
        if handler:
            operation = sub_cmd or "status"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                _run_injectors(message, f"session {operation}")
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Session-Handler nicht verfuegbar")
            return 1
    
    elif command == "consolidate":
        # Consolidation-Handler aufrufen
        handler = get_handler("consolidate")
        if handler:
            operation = sub_cmd or "status"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Consolidation-Handler nicht verfuegbar")
            return 1

    elif command == "bericht":
        # Foerderbericht-Handler aufrufen
        handler = get_handler("bericht")
        if handler:
            operation = sub_cmd or "help"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Bericht-Handler nicht verfuegbar")
            return 1

    elif command == "path":
        # Path-Handler aufrufen (v2.0 - Single Source of Truth)
        handler = get_handler("path")
        if handler:
            operation = sub_cmd or ""
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Path-Handler nicht verfuegbar")
            return 1

    # ═══════════════════════════════════════════════════════════════
    # ZEIT-SYSTEM (v1.1.83)
    # ═══════════════════════════════════════════════════════════════

    elif command == "clock":
        # Clock-Handler (Uhrzeit-Anzeige)
        handler = get_handler("clock")
        if handler:
            operation = sub_cmd or "status"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Clock-Handler nicht verfuegbar")
            return 1

    elif command == "timer":
        # Timer-Handler (Stoppuhr)
        handler = get_handler("timer")
        if handler:
            operation = sub_cmd or "list"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Timer-Handler nicht verfuegbar")
            return 1

    elif command == "countdown":
        # Countdown-Handler
        handler = get_handler("countdown")
        if handler:
            operation = sub_cmd or "list"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Countdown-Handler nicht verfuegbar")
            return 1

    elif command == "between":
        # Between-Handler (Between-Checks)
        handler = get_handler("between")
        if handler:
            operation = sub_cmd or "status"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Between-Handler nicht verfuegbar")
            return 1

    elif command == "beat":
        # Beat-Handler (Unified Zeit-Anzeige)
        handler = get_handler("beat")
        if handler:
            operation = sub_cmd or ""
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Beat-Handler nicht verfuegbar")
            return 1

    # ═══════════════════════════════════════════════════════════════
    # WORKFLOW-TUEV (v1.1.83)
    # ═══════════════════════════════════════════════════════════════

    elif command == "tuev":
        # TUeV-Handler (Workflow-Qualitaetssicherung)
        handler = get_handler("tuev")
        if handler:
            operation = sub_cmd or "status"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] TUeV-Handler nicht verfuegbar")
            return 1

    elif command == "usecase":
        # Usecase-Handler (Testfaelle)
        handler = get_handler("usecase")
        if handler:
            operation = sub_cmd or "list"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Usecase-Handler nicht verfuegbar")
            return 1

    elif command == "extensions":
        # Extensions-Handler aufrufen (v1.1.86)
        handler = get_handler("extensions")
        if handler:
            operation = sub_cmd or "list"
            try:
                success, message = handler.handle(operation, args)
                print(message)
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            print("[ERROR] Extensions-Handler nicht verfuegbar")
            return 1

    elif command == "skill":
        # Skill-Befehle (v2.0 - Task 905/906)
        # "skill export <name>" nutzt das erweiterte skill_export.py Tool
        # Andere Operationen delegieren an den SkillsHandler
        if sub_cmd == "export" and args:
            # Skill-Export mit Dependency Resolution
            sys.path.insert(0, str(TOOLS_DIR))
            try:
                from skill_export import SkillExporter
                exporter = SkillExporter(SYSTEM_ROOT)
                skill_name = args[0]
                dry_run = "--dry-run" in args or "-n" in args
                output_dir = None
                for i, a in enumerate(args):
                    if a in ("--output", "-o") and i + 1 < len(args):
                        output_dir = args[i + 1]
                success, message = exporter.export(
                    name=skill_name,
                    output_dir=output_dir,
                    dry_run=dry_run,
                )
                print(message)
                return 0 if success else 1
            except ImportError as e:
                print(f"[ERROR] skill_export.py nicht gefunden: {e}")
                return 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1
        else:
            # Alle anderen Skill-Befehle -> SkillsHandler
            handler = get_handler("skills")
            if handler:
                operation = sub_cmd or "list"
                try:
                    success, message = handler.handle(operation, args)
                    print(message)
                    return 0 if success else 1
                except Exception as e:
                    print(f"[ERROR] {e}")
                    return 1
            else:
                print("[ERROR] Skills-Handler nicht verfuegbar")
                return 1

    elif command == "fs":
        # Filesystem-Schutz (v1.1.84 - Tasks 773-778)
        sys.path.insert(0, str(TOOLS_DIR))
        from fs_protection import FSProtection, PathClassifier
        fs = FSProtection(SYSTEM_ROOT)
        classifier = PathClassifier(SYSTEM_ROOT)

        if not sub_cmd:
            print("Usage: bach fs [check|heal|status|classify|scan|backup]")
            return 1

        if sub_cmd == "check":
            success, msg = fs.check_integrity()
            print(msg)
        elif sub_cmd == "heal":
            file_path = extra_args[0] if extra_args else None
            force = "--force" in sys.argv
            if "--all" in sys.argv:
                success, msg = fs.heal(force=force)
            elif file_path:
                success, msg = fs.heal(file_path, force)
            else:
                print("Usage: bach fs heal <file> oder bach fs heal --all")
                return 1
            print(msg)
        elif sub_cmd == "status":
            # Status anzeigen
            snapshots_dir = BACH_DIR / "dist" / "snapshots"
            snapshot_count = len(list(snapshots_dir.glob("*.orig"))) if snapshots_dir.exists() else 0
            print("[FS] Filesystem Protection Status")
            print(f"  Snapshots: {snapshot_count} Dateien")
            print(f"  Befehle: bach fs check, bach fs heal, bach dist snapshot")
        elif sub_cmd == "classify":
            if not extra_args:
                print("Usage: bach fs classify <path>")
                return 1
            path = Path(extra_args[0])
            dist_type = classifier.classify_path(path)
            level = classifier.get_protection_level(path)
            print(f"{path}: dist_type={dist_type} ({level})")
        elif sub_cmd == "scan":
            result = classifier.scan_directory()
            print("[FS] Dateisystem-Scan")
            print(f"  CORE (dist_type=2): {len(result[2])} Dateien")
            print(f"  TEMPLATE (dist_type=1): {len(result[1])} Dateien")
            print(f"  USER (dist_type=0): {len(result[0])} Dateien")
        elif sub_cmd == "backup":
            tag = extra_args[0] if extra_args else "manual"
            success, msg = fs.create_backup(tag)
            print(msg)
        else:
            print(f"Unbekannter FS-Befehl: {sub_cmd}")
            print("Verfuegbar: check, heal, status, classify, scan, backup")
            return 1
        return 0

    elif command == "llm":
        # Multi-LLM Protocol Handler (NEU v1.1.70)
        sys.path.insert(0, str(HUB_DIR))
        from multi_llm_protocol import MultiLLMHandler
        # Partner-Identitaet feststellen
        current_partner = 'user'
        for a in sys.argv:
            if a.startswith('--partner='):
                current_partner = a.split('=')[1]

        handler = MultiLLMHandler(SYSTEM_ROOT, current_partner)
        operation = sub_cmd or "status"
        try:
            success, message = handler.handle(operation, args)
            print(message)
            return 0 if success else 1
        except Exception as e:
            print(f"[ERROR] {e}")
            return 1

    elif command == "file":
        # Filesystem-Manager (FILE_002)
        sys.path.insert(0, str(TOOLS_DIR))
        try:
            import c_file_manager
            
            if not sub_cmd:
                print("Usage: bach file <cmd> [args]...")
                print("Commands: read, write, append, delete, copy, move, info, list")
                return 1

            result = {}
            error = None
            
            try:
                if sub_cmd == "read" and len(args) >= 1:
                    result = c_file_manager.read_file(args[0])
                
                elif sub_cmd == "write" and len(args) >= 2:
                    content = args[1]
                    overwrite = "--overwrite" in args
                    result = c_file_manager.write_file(args[0], content, overwrite=overwrite)
                
                elif sub_cmd == "append" and len(args) >= 2:
                    content = args[1]
                    result = c_file_manager.append_file(args[0], content)
                
                elif sub_cmd == "delete" and len(args) >= 1:
                    result = c_file_manager.delete_file(args[0])
                
                elif sub_cmd == "copy" and len(args) >= 2:
                    result = c_file_manager.copy_file(args[0], args[1])
                
                elif sub_cmd == "move" and len(args) >= 2:
                    result = c_file_manager.move_file(args[0], args[1])
                
                elif sub_cmd == "info" and len(args) >= 1:
                    result = c_file_manager.get_file_info(args[0])
                
                elif sub_cmd == "list" and len(args) >= 1:
                    result = c_file_manager.list_dir(args[0])
                
                else:
                    error = f"Invalid arguments or unknown command: {sub_cmd}"

            except Exception as e:
                error = str(e)
            
            if error:
                print(json.dumps({"error": error}, indent=2))
                return 1
                
            print(json.dumps(result, indent=2))
            return 0 if "error" not in result else 1
            
        except ImportError:
            print("[ERROR] c_file_manager.py not found in tools/")
            return 1

    elif command == "ocr":
        # OCR-Tool aufrufen
        sys.path.insert(0, str(TOOLS_DIR))
        from c_ocr_engine import OCREngine, find_beleg_pdf
        
        if not sub_cmd:
            print("Usage: bach ocr <beleg_id|pdf_path>")
            print("       bach ocr B0006")
            print("       bach ocr 6")
            return 1
        
        # Beleg finden
        if sub_cmd.lower().startswith("b") or sub_cmd.isdigit():
            pdf_path = find_beleg_pdf(sub_cmd)
            if not pdf_path:
                print(f"[ERROR] Beleg {sub_cmd} nicht gefunden")
                return 1
            print(f"[INFO] Gefunden: {pdf_path.name}")
        else:
            pdf_path = Path(sub_cmd)
            if not pdf_path.exists():
                print(f"[ERROR] Datei nicht gefunden: {sub_cmd}")
                return 1
        
        # OCR
        engine = OCREngine()
        if not engine.is_available:
            print("[ERROR] Tesseract nicht verfuegbar!")
            return 1
        
        print(f"\n[OCR] Scanne {pdf_path.name}...")
        results = engine.recognize_pdf(str(pdf_path))
        
        if not results:
            print("[WARN] Keine Ergebnisse")
            return 1
        
        for r in results:
            print(f"\n--- Seite {r.page_num} ({r.confidence:.0f}% Konfidenz) ---\n")
            print(r.text[:2000])  # Max 2000 Zeichen
        
        return 0
    
    else:
        # Pruefen ob es ein Tool ist (bach <tool> [args])
        tool_result = _try_run_tool(command, [sub_cmd] + args if sub_cmd else args)
        if tool_result is not None:
            return tool_result
        
        suggestion = _suggest_command(command)
        print(f"Unbekannter Befehl: {command}")
        if suggestion:
            print(suggestion)
        print_help()
        return 1
    
    return 0


# ═══════════════════════════════════════════════════════════════
# COMMAND SUGGESTION (Did-you-mean)
# ═══════════════════════════════════════════════════════════════

# Bekannte Befehle ohne --
KNOWN_COMMANDS = [
    "task", "mem", "backup", "cv", "map", "restore", "dist", "steuer", "ati", "abo",
    "gui", "daemon", "scan", "lesson", "wiki", "tools", "tool", "msg",
    "partner", "ocr", "session", "inbox", "consolidate", "bericht", "routine", "calendar", "contact", "gesundheit", "haushalt", "versicherung", "file", "doc",
    # Zeit-System (v1.1.83)
    "clock", "timer", "countdown", "between", "beat",
    # Workflow-TUeV (v1.1.83)
    "tuev", "usecase",
    # Language System (v1.1.85)
    "lang",
    # Extensions (v1.1.86)
    "extensions",
    # Skill-Export (v2.0 - Task 905)
    "skill"
]

# Bekannte Profile mit --
KNOWN_PROFILES = [
    "help", "startup", "shutdown", "status", "memory", "context", "inject",
    "backup", "db", "tokens", "agents", "dist", "scan", "gui", "daemon",
    "steuer", "abo", "ati", "skills", "trash", "tools", "logs", "docs", "doc",
    "connections", "lesson", "wiki", "msg", "test", "maintain", "sources",
    "partner", "snapshot", "data", "recurring", "consolidate", "lang"
]

def _suggest_command(unknown: str) -> str:
    """Schlaegt aehnliche Befehle vor bei Tippfehlern."""
    unknown_lower = unknown.lower().lstrip("-")
    suggestions = []
    
    # Substring-Match in Commands
    for cmd in KNOWN_COMMANDS:
        if unknown_lower in cmd or cmd in unknown_lower:
            suggestions.append(cmd)
    
    # Substring-Match in Profiles (mit --)
    for profile in KNOWN_PROFILES:
        if unknown_lower in profile or profile in unknown_lower:
            suggestions.append(f"--{profile}")
    
    # Levenshtein-artig: Gleicher Anfang (mind. 2 Zeichen)
    if len(unknown_lower) >= 2 and not suggestions:
        prefix = unknown_lower[:2]
        for cmd in KNOWN_COMMANDS:
            if cmd.startswith(prefix):
                suggestions.append(cmd)
        for profile in KNOWN_PROFILES:
            if profile.startswith(prefix):
                suggestions.append(f"--{profile}")
    
    if suggestions:
        unique = list(dict.fromkeys(suggestions))[:3]  # Max 3, dedupliziert
        return f"Meinten Sie: {', '.join(unique)}?"
    return ""


def _try_run_tool(name: str, args: list) -> Optional[int]:
    """Versucht ein Tool aus tools/ auszufuehren.
    
    Ermoeglicht: bach c_encoding_fixer datei.py
    Statt:       python tools/c_encoding_fixer.py datei.py
    """
    import subprocess
    
    # Tool suchen
    tool_file = None
    
    # Exakter Match
    exact = TOOLS_DIR / f"{name}.py"
    if exact.exists():
        tool_file = exact
    else:
        # Prefix-Match (z.B. "encoding" findet "c_encoding_fixer")
        for f in TOOLS_DIR.glob("*.py"):
            if name.lower() in f.stem.lower():
                tool_file = f
                break
    
    if not tool_file:
        return None  # Kein Tool gefunden
    
    # Tool ausfuehren
    log(f"[TOOL] {tool_file.stem} {' '.join(args)}")
    
    try:
        cmd_line = [sys.executable, str(tool_file)] + args
        result = subprocess.run(cmd_line, cwd=str(BACH_DIR))
        return result.returncode
    except Exception as e:
        print(f"[ERROR] Tool-Ausfuehrung: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
