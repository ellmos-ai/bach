#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
bach.py - BACH v2.0 Unified CLI (Registry-Based)
==================================================

Nutzt Auto-Discovery statt statischer Handler-Map.
Legacy-Backup: bach_legacy.py

Usage:
    python bach.py <befehl> [operation] [args]
    python bach.py --<handler> [operation] [args]
    python bach.py --startup
"""

import os
import sys
import json
from pathlib import Path
from typing import Optional

# UTF-8 Encoding fix - MUSS vor allen anderen Imports stehen
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ═══════════════════════════════════════════════════════════════
# PFADE (Auto-Detection fuer Root vs. system/ Installation)
# ═══════════════════════════════════════════════════════════════

SCRIPT_DIR = Path(__file__).parent

# Auto-Detect: Root-Installation (BACH Release v3.1.6) oder Legacy (Vanilla, bach.py in system/)
if (SCRIPT_DIR / "system").exists():
    # Root-Installation (BACH Release v3.1.6): bach.py liegt im BACH-Root
    BACH_ROOT = SCRIPT_DIR
    SYSTEM_ROOT = SCRIPT_DIR / "system"
else:
    # Legacy (Vanilla): bach.py liegt in system/
    SYSTEM_ROOT = SCRIPT_DIR
    BACH_ROOT = SYSTEM_ROOT.parent

BACH_DIR = SYSTEM_ROOT  # Rueckwaertskompatibilitaet
DATA_DIR = SYSTEM_ROOT / "data"
HUB_DIR = SYSTEM_ROOT / "hub"
SKILLS_DIR = SYSTEM_ROOT / "skills"
TOOLS_DIR = SYSTEM_ROOT / "tools"
DB_PATH = DATA_DIR / "bach.db"
LOGS_DIR = DATA_DIR / "logs"

# sys.path Setup fuer Handler-Imports
for p in [str(SYSTEM_ROOT), str(SKILLS_DIR), str(SKILLS_DIR / "tools")]:
    if p not in sys.path:
        sys.path.insert(0, p)

# ═══════════════════════════════════════════════════════════════
# AUTO-LOGGER
# ═══════════════════════════════════════════════════════════════

try:
    sys.path.insert(0, str(TOOLS_DIR))
    from autolog import get_logger, log, cmd
except ImportError:
    def get_logger(path=None):
        class DummyLogger:
            def log(self, msg): pass
            def cmd(self, c, a=None, r=""): pass
            def chat(self, m, s="claude"): pass
        return DummyLogger()
    def log(msg): pass
    def cmd(c, a=None, r=""): pass

# ═══════════════════════════════════════════════════════════════
# APP INITIALISIERUNG (Lazy)
# ═══════════════════════════════════════════════════════════════

_app = None

def _get_app():
    """Lazy App-Singleton."""
    global _app
    if _app is None:
        from core.app import App
        _app = App(SYSTEM_ROOT)
    return _app

# ═══════════════════════════════════════════════════════════════
# INJEKTOREN (Legacy)
# ═══════════════════════════════════════════════════════════════

_injector_system = None

def _get_injector():
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
    injector = _get_injector()
    if not injector:
        return
    injections = injector.process(text)
    for inj in injections:
        print(f"\n{inj}")
    if "done" in last_command.lower():
        between = injector.check_between(last_command)
        if between:
            print(f"\n{between}")

# ═══════════════════════════════════════════════════════════════
# LEGACY DB FUNCTIONS (fuer Rueckwaertskompatibilitaet)
# ═══════════════════════════════════════════════════════════════

import sqlite3

def get_db():
    """SQLite-Connection mit optimalen Einstellungen (BUG-HQ5-B-001 Fix)."""
    from core.db import get_db_connection
    return get_db_connection(DB_PATH)

def db_query(sql, params=()):
    with get_db() as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql, params).fetchall()

def db_execute(sql, params=()):
    with get_db() as conn:
        conn.execute(sql, params)
        conn.commit()

# ═══════════════════════════════════════════════════════════════
# INLINE COMMANDS (nicht-Handler, bleiben hier)
# ═══════════════════════════════════════════════════════════════

def _handle_fs(sub_cmd, args):
    """Filesystem-Schutz (tools-basiert, kein Handler)."""
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
        file_path = args[0] if args else None
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
        snapshots_dir = BACH_DIR / "dist" / "snapshots"
        snapshot_count = len(list(snapshots_dir.glob("*.orig"))) if snapshots_dir.exists() else 0
        print("[FS] Filesystem Protection Status")
        print(f"  Snapshots: {snapshot_count} Dateien")
        print(f"  Befehle: bach fs check, bach fs heal, bach dist snapshot")
    elif sub_cmd == "classify":
        if not args:
            print("Usage: bach fs classify <path>")
            return 1
        path = Path(args[0])
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
        tag = args[0] if args else "manual"
        success, msg = fs.create_backup(tag)
        print(msg)
    else:
        print(f"Unbekannter FS-Befehl: {sub_cmd}")
        return 1
    return 0


def _handle_llm(sub_cmd, args):
    """Multi-LLM Protocol (braucht partner-Argument)."""
    sys.path.insert(0, str(HUB_DIR))
    from multi_llm_protocol import MultiLLMHandler
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


def _handle_file(sub_cmd, args):
    """Filesystem-Manager (tools-basiert)."""
    sys.path.insert(0, str(TOOLS_DIR))
    try:
        import c_file_manager
    except ImportError:
        print("[ERROR] c_file_manager.py not found in tools/")
        return 1

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
            result = c_file_manager.write_file(args[0], args[1], overwrite="--overwrite" in args)
        elif sub_cmd == "append" and len(args) >= 2:
            result = c_file_manager.append_file(args[0], args[1])
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
        print(json.dumps({"error": error}, indent=2, ensure_ascii=False))
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if "error" not in result else 1


def _handle_ocr(sub_cmd, args):
    """OCR-Tool (tools-basiert)."""
    sys.path.insert(0, str(TOOLS_DIR))
    from c_ocr_engine import OCREngine, find_beleg_pdf

    if not sub_cmd:
        print("Usage: bach ocr <beleg_id|pdf_path>")
        return 1

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
        print(r.text[:2000])
    return 0


def _handle_map(sub_cmd, args):
    """Call Graph / Dependency Mapper (tools-basiert)."""
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
        return 0
    except Exception as e:
        print(f"[FEHLER] Call Graph: {e}")
        return 1


def _handle_skill_export(sub_cmd, args):
    """Skill-Export mit Dependency Resolution."""
    sys.path.insert(0, str(TOOLS_DIR))
    try:
        from skill_export import SkillExporter
        exporter = SkillExporter(SYSTEM_ROOT)
        skill_name = args[0] if args else sub_cmd
        dry_run = "--dry-run" in args or "-n" in args
        output_dir = None
        for i, a in enumerate(args):
            if a in ("--output", "-o") and i + 1 < len(args):
                output_dir = args[i + 1]
        success, message = exporter.export(name=skill_name, output_dir=output_dir, dry_run=dry_run)
        print(message)
        return 0 if success else 1
    except Exception as e:
        print(f"[ERROR] {e}")
        return 1


def _handle_export(sub_cmd, args):
    """Export-Tool fuer Spiegel-Dateien (AGENTS.md, etc.)."""
    sys.path.insert(0, str(TOOLS_DIR))

    if not sub_cmd or sub_cmd == "help":
        print("Usage: bach export <type> [args]")
        print("Types:")
        print("  agents                     Generiere AGENTS.md aus DB")
        print("  partners                   Generiere PARTNERS.md aus DB")
        print("  usecases                   Generiere USECASES.md aus DB")
        print("  chains                     Generiere CHAINS.md aus DB")
        print("  workflows                  Generiere WORKFLOWS.md aus Dateisystem")
        print("  mirrors                    Generiere alle Spiegel-Dateien")
        return 0

    if sub_cmd == "agents":
        try:
            from agents_export import AgentsExporter
            exporter = AgentsExporter(BACH_ROOT)
            success, msg = exporter.generate()
            print(msg)
            return 0 if success else 1
        except Exception as e:
            print(f"[ERROR] {e}")
            return 1

    elif sub_cmd == "partners":
        try:
            from partners_export import PartnersExporter
            exporter = PartnersExporter(BACH_ROOT)
            success, msg = exporter.generate()
            print(msg)
            return 0 if success else 1
        except Exception as e:
            print(f"[ERROR] {e}")
            return 1

    elif sub_cmd == "usecases":
        try:
            from usecases_export import UsecasesExporter
            exporter = UsecasesExporter(BACH_ROOT)
            success, msg = exporter.generate()
            print(msg)
            return 0 if success else 1
        except Exception as e:
            print(f"[ERROR] {e}")
            return 1

    elif sub_cmd == "chains":
        try:
            from chains_export import ChainsExporter
            exporter = ChainsExporter(BACH_ROOT)
            success, msg = exporter.generate()
            print(msg)
            return 0 if success else 1
        except Exception as e:
            print(f"[ERROR] {e}")
            return 1

    elif sub_cmd == "workflows":
        try:
            from workflows_export import WorkflowsExporter
            exporter = WorkflowsExporter(BACH_ROOT)
            success, msg = exporter.generate()
            print(msg)
            return 0 if success else 1
        except Exception as e:
            print(f"[ERROR] {e}")
            return 1

    elif sub_cmd == "mirrors":
        # Alle Spiegel-Dateien generieren
        results = []
        exit_code = 0

        # 1. AGENTS.md
        try:
            from agents_export import AgentsExporter
            exporter = AgentsExporter(BACH_ROOT)
            success, msg = exporter.generate()
            results.append(msg)
            if not success:
                exit_code = 1
        except Exception as e:
            results.append(f"✗ AGENTS.md: {e}")
            exit_code = 1

        # 2. PARTNERS.md
        try:
            from partners_export import PartnersExporter
            exporter = PartnersExporter(BACH_ROOT)
            success, msg = exporter.generate()
            results.append(msg)
            if not success:
                exit_code = 1
        except Exception as e:
            results.append(f"✗ PARTNERS.md: {e}")
            exit_code = 1

        # 3. USECASES.md
        try:
            from usecases_export import UsecasesExporter
            exporter = UsecasesExporter(BACH_ROOT)
            success, msg = exporter.generate()
            results.append(msg)
            if not success:
                exit_code = 1
        except Exception as e:
            results.append(f"✗ USECASES.md: {e}")
            exit_code = 1

        # 4. CHAINS.md
        try:
            from chains_export import ChainsExporter
            exporter = ChainsExporter(BACH_ROOT)
            success, msg = exporter.generate()
            results.append(msg)
            if not success:
                exit_code = 1
        except Exception as e:
            results.append(f"✗ CHAINS.md: {e}")
            exit_code = 1

        # 5. WORKFLOWS.md
        try:
            from workflows_export import WorkflowsExporter
            exporter = WorkflowsExporter(BACH_ROOT)
            success, msg = exporter.generate()
            results.append(msg)
            if not success:
                exit_code = 1
        except Exception as e:
            results.append(f"✗ WORKFLOWS.md: {e}")
            exit_code = 1

        for r in results:
            print(r)
        return exit_code

    else:
        print(f"[ERROR] Unbekannter Export-Typ: {sub_cmd}")
        print("Nutze 'bach export help' fuer Hilfe")
        return 1


def _handle_partner(sub_cmd, args):
    """Partner-Config-Manager (PartnerConfigManager)."""
    sys.path.insert(0, str(HUB_DIR))
    try:
        from partner_config_manager import PartnerConfigManager
    except ImportError:
        print("[ERROR] partner_config_manager.py nicht gefunden in hub/")
        return 1

    manager = PartnerConfigManager(BACH_ROOT)

    if not sub_cmd or sub_cmd == "help":
        print("Usage: bach partner <cmd> [args]")
        print("Commands:")
        print("  detect                     Erkenne installierte Partner")
        print("  register <name>            Trage BACH in Partner-Config ein")
        print("  register --all             Trage BACH in alle erkannten Partner ein")
        print("  unregister <name>          Entferne BACH aus Partner-Config")
        print("  list                       Liste unterstuetzte Partner")
        print("  status                     Zeige Status der Partner")
        return 0

    if sub_cmd == "detect":
        partners = manager.detect_active_partners()
        if partners:
            print(f"Erkannte Partner ({len(partners)}):")
            for p in partners:
                print(f"  ✓ {p}")
        else:
            print("Keine Partner erkannt")
        return 0

    elif sub_cmd == "register":
        if "--all" in args:
            results = manager.register_all_detected()
            for partner, success, msg in results:
                print(f"  {msg}")
            return 0

        if not args:
            print("[ERROR] Partner-Name erforderlich")
            print("Unterstuetzte Partner:", ", ".join(manager.SUPPORTED_PARTNERS.keys()))
            return 1

        partner_name = args[0]
        success, msg = manager.register_partner(partner_name)
        print(msg)
        return 0 if success else 1

    elif sub_cmd == "unregister":
        if not args:
            print("[ERROR] Partner-Name erforderlich")
            return 1

        partner_name = args[0]
        success, msg = manager.unregister_partner(partner_name)
        print(msg)
        return 0 if success else 1

    elif sub_cmd == "list":
        print("Unterstuetzte Partner:")
        for name, info in manager.SUPPORTED_PARTNERS.items():
            print(f"  • {name:<15} → {info['config_file']}")
        return 0

    elif sub_cmd == "status":
        detected = manager.detect_active_partners()
        print(f"Aktive Partner ({len(detected)}):")
        for p in detected:
            print(f"  ✓ {p}")
        return 0

    else:
        print(f"[ERROR] Unbekanntes Subkommando: {sub_cmd}")
        print("Nutze 'bach partner help' fuer Hilfe")
        return 1


def _handle_seal(sub_cmd, args):
    """Kernel-Seal-System (SealHandler)."""
    sys.path.insert(0, str(HUB_DIR))
    try:
        from seal import SealHandler
    except ImportError:
        print("[ERROR] seal.py nicht gefunden in hub/")
        return 1

    handler = SealHandler(BACH_ROOT)

    if not sub_cmd or sub_cmd == "help":
        print("Usage: bach seal <cmd>")
        print("Commands:")
        print("  check                      Vollstaendige Hash-Pruefung aller CORE-Dateien")
        print("  repair                     Neuen Kernel-Hash berechnen und speichern")
        print("  status                     Zeige aktuellen Seal-Status")
        return 0

    if sub_cmd == "check":
        return handler.check(verbose=("--verbose" in args or "-v" in args))

    elif sub_cmd == "repair":
        return handler.repair()

    elif sub_cmd == "status":
        return handler.status()

    else:
        print(f"[ERROR] Unbekanntes Subkommando: {sub_cmd}")
        print("Nutze 'bach seal help' fuer Hilfe")
        return 1


def _handle_integration(sub_cmd, args):
    """LLM-Partner-Integration (SQ038)."""
    sys.path.insert(0, str(HUB_DIR))
    try:
        from hub.integration import IntegrationHandler
        handler = IntegrationHandler(SYSTEM_ROOT)
        success, msg = handler.handle(sub_cmd, args)
        print(msg)
        return 0 if success else 1
    except Exception as e:
        print(f"[ERROR] Integration: {e}")
        return 1


def _handle_secrets(sub_cmd, args):
    """Secrets-Management (SQ076)."""
    sys.path.insert(0, str(HUB_DIR))
    try:
        from hub.secrets_handler import handle_secrets_command
        # sub_cmd + args zusammenf├╝gen
        full_args = [sub_cmd] + args if sub_cmd else args
        handle_secrets_command(full_args)
        return 0
    except Exception as e:
        print(f"[ERROR] Secrets: {e}")
        return 1


def _handle_settings(sub_cmd, args):
    """Settings-Management (SQ037)."""
    sys.path.insert(0, str(HUB_DIR))
    try:
        from hub.settings import handle_settings_command
        # sub_cmd + args zusammenfügen
        full_args = [sub_cmd] + args if sub_cmd else args
        handle_settings_command(full_args)
        return 0
    except Exception as e:
        print(f"[ERROR] Settings: {e}")
        return 1


def _handle_folders(sub_cmd, args):
    """User Data Folders Management (SQ070)."""
    sys.path.insert(0, str(HUB_DIR))
    try:
        from hub.folders import _handle_folders as handle_folders_command
        # sub_cmd + args zusammenfügen
        full_args = [sub_cmd] + args if sub_cmd else args
        db_path = DATA_DIR / "bach.db"
        return handle_folders_command(db_path, full_args)
    except Exception as e:
        print(f"[ERROR] Folders: {e}")
        return 1


def _handle_upgrade(sub_cmd, args):
    """Selektive Upgrades & Downgrades (SQ020)."""
    sys.path.insert(0, str(HUB_DIR))
    try:
        from hub.upgrade import UpgradeHandler
        handler = UpgradeHandler(SYSTEM_ROOT)
        operation = sub_cmd
        if sub_cmd in {"--help", "--status", "--check", "--list"}:
            operation = sub_cmd[2:]
        success, msg = handler.handle(operation, args)
        print(msg)
        return 0 if success else 1
    except Exception as e:
        print(f"[ERROR] Upgrade: {e}")
        return 1


def _handle_cookbook(sub_cmd, args):
    """Rezeptbuch-Tool fuer DB-Doku-Generierung (SQ069)."""
    sys.path.insert(0, str(HUB_DIR))
    try:
        from hub.cookbook import CookbookHandler
        handler = CookbookHandler(SYSTEM_ROOT)
        success, msg = handler.handle(sub_cmd, args)
        print(msg)
        return 0 if success else 1
    except Exception as e:
        print(f"[ERROR] Cookbook: {e}")
        return 1


def _handle_task(sub_cmd, args):
    """Task-Verwaltung (add, list, done, block, etc.)."""
    sys.path.insert(0, str(HUB_DIR))
    try:
        from hub.task import TaskHandler
        handler = TaskHandler(SYSTEM_ROOT)
        success, msg = handler.handle(sub_cmd, args)
        print(msg)
        return 0 if success else 1
    except Exception as e:
        print(f"[ERROR] Task: {e}")
        return 1


def _handle_pipeline(sub_cmd, args):
    """Pipeline-Management (SQ011)."""
    sys.path.insert(0, str(HUB_DIR))
    try:
        from hub.pipeline import _handle_pipeline as handle_pipeline_command
        full_args = [sub_cmd] + args if sub_cmd else args
        handle_pipeline_command(full_args)
        return 0
    except Exception as e:
        print(f"[ERROR] Pipeline: {e}")
        import traceback
        traceback.print_exc()
        return 1


# Inline-Commands die nicht ueber Handler laufen
INLINE_COMMANDS = {
    "fs": _handle_fs,
    "file": _handle_file,
    "ocr": _handle_ocr,
    "llm": _handle_llm,
    "map": _handle_map,
    "partner": _handle_partner,
    "export": _handle_export,
    "seal": _handle_seal,
    "integration": _handle_integration,
    "secrets": _handle_secrets,
    "settings": _handle_settings,
    "folders": _handle_folders,
    "upgrade": _handle_upgrade,
    "cookbook": _handle_cookbook,
    "task": _handle_task,
    "pipeline": _handle_pipeline,
}


def _try_run_tool(name: str, args: list) -> Optional[int]:
    """Versucht ein Tool aus tools/ auszufuehren."""
    import subprocess

    tool_file = None
    exact = TOOLS_DIR / f"{name}.py"
    if exact.exists():
        tool_file = exact
    else:
        # Prefix-Match statt Substring (verhindert z.B. "check" → "db_check")
        name_lower = name.lower()
        for f in TOOLS_DIR.glob("*.py"):
            if f.stem.lower().startswith(name_lower):
                tool_file = f
                break

    if not tool_file:
        return None

    log(f"[TOOL] {tool_file.stem} {' '.join(args)}")
    try:
        cmd_line = [sys.executable, str(tool_file)] + args
        result = subprocess.run(cmd_line, cwd=str(BACH_DIR))
        return result.returncode
    except Exception as e:
        print(f"[ERROR] Tool-Ausfuehrung: {e}")
        return 1


# ═══════════════════════════════════════════════════════════════
# HELP
# ═══════════════════════════════════════════════════════════════

def print_help():
    """Zeigt Hilfe an."""
    help_text = """
BACH v2.0 - Registry-Based CLI

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
  --memory status        Memory-Handler

LESSONS:
  lesson add "Titel"     Lesson hinzufuegen
  lesson list            Lessons auflisten

PARTNER:
  partner list           Partner-Netzwerk
  partner status         Aktive Partner

GUI & DAEMON:
  gui start              Web-Dashboard starten
  daemon start           Daemon-Service

STEUER:
  steuer status          Beleg-/Posten-Status

BACKUP:
  backup create          Backup erstellen

DB-SYNC (Multi-PC):
  db sync enable         Multi-PC-Sync aktivieren
  db sync disable        Multi-PC-Sync deaktivieren
  db sync                Backups syncen und mergen
  db sync status         Sync-Status und Backups
  db backup              Manuelles Backup erstellen
  db cleanup             Alte Backups loeschen
  config sync backend <type>  Backend waehlen (onedrive|dropbox|google_drive|local)
  config sync path <path>     Custom Sync-Pfad setzen

HILFE:
  help                   Diese Hilfe
  help <topic>           Hilfe zu Thema
"""
    print(help_text)

    # Verfuegbare Handler anzeigen
    try:
        app = _get_app()
        names = app.registry.names
        if names:
            print(f"Registrierte Handler ({len(names)}):")
            # In Spalten anzeigen
            cols = 6
            for i in range(0, len(names), cols):
                row = names[i:i + cols]
                print("  " + "  ".join(f"{n:<14}" for n in row))
            print()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    """Haupteinstiegspunkt."""
    # Windows-Konsolen-Encoding
    if sys.platform == 'win32':
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

    json_requested = "--json" in sys.argv[1:]
    logger = get_logger(BACH_DIR)

    # ProSync: Pull bei Start, Push bei Exit (nur wenn aktiviert)
    sync_config = DATA_DIR / "config" / "db_sync_enabled"
    if sync_config.exists():
        try:
            from hub.db_sync import DBSyncManager
            manager = DBSyncManager()
            ok, msg = manager.sync_on_start()
            if not json_requested:
                print(f"[ProSync] {msg}")
        except Exception as e:
            if not json_requested:
                print(f"[ProSync] Start-Fehler: {e}")

        import atexit
        def _exit_sync():
            try:
                from hub.db_sync import DBSyncManager
                ok, msg = DBSyncManager().sync_on_exit()
                if not json_requested:
                    print(f"[ProSync] {msg}")
            except Exception:
                pass
        atexit.register(_exit_sync)

    # Keine Argumente oder Help
    if len(sys.argv) < 2 or sys.argv[1] in ['-h', '--help', 'help']:
        if len(sys.argv) > 2:
            topic = sys.argv[2]
            app = _get_app()
            handler = app.get_handler("help")
            if handler:
                success, message = handler.handle(topic, [])
                print(message)
                return 0
        print_help()
        return 0

    arg = sys.argv[1]
    sub_cmd = sys.argv[2] if len(sys.argv) > 2 else ""
    args = sys.argv[3:] if len(sys.argv) > 3 else []

    # ── --help Abfangen (CLI --help Parsing-Bug Fix, Runde 24) ──
    # Wenn --help oder -h als sub_cmd ODER in args vorkommt -> Hilfe anzeigen
    if sub_cmd in ('--help', '-h') or '--help' in args or '-h' in args:
        app = _get_app()
        handler = app.get_handler("help")
        if handler:
            success, message = handler.handle(arg, [])
            print(message)
            return 0 if success else 1
        # Fallback wenn kein help-Handler
        print(f"Hilfe fuer '{arg}' nicht verfuegbar.")
        return 1

    # ── Activity Tracking (SQ022) ──
    # EOD-Timer + Idle-Check + Tick bei jedem Befehl (außer --startup/--shutdown)
    if not (arg == "--startup" or arg == "--shutdown"):
        try:
            import sqlite3
            from tools.activity_tracker import ActivityTracker

            # session_id aus system_activity lesen
            session_id = None
            try:
                conn = sqlite3.connect(str(DB_PATH))
                cursor = conn.execute("SELECT session_id FROM system_activity WHERE id = 1")
                row = cursor.fetchone()
                if row:
                    session_id = row[0]
                conn.close()
            except Exception:
                pass  # session_id bleibt None

            tracker = ActivityTracker(DB_PATH, idle_threshold_minutes=30)
            if not json_requested:
                tracker.check_eod_and_finalize(BACH_ROOT, eod_hour=23)  # EOD-Timer (23:00 Uhr)
                tracker.check_idle_and_finalize(BACH_ROOT)
            tracker.tick(session_id=session_id)
        except Exception as e:
            # Graceful Degradation: Activity-Tracking-Fehler blockieren nicht den CLI-Befehl
            pass

    # ── Handler-basierte Befehle (--startup, --shutdown, etc.) ──

    if arg.startswith('--'):
        profile_name = arg[2:]

        app = _get_app()
        handler = app.get_handler(profile_name)
        if handler:
            # Operation + Args aufteilen
            operation = ""
            handler_args = []
            remaining = sys.argv[2:] if len(sys.argv) > 2 else []
            for a in remaining:
                if not a.startswith("--") and not operation:
                    operation = a
                else:
                    handler_args.append(a)

            # startup/shutdown brauchen keine Operation
            if profile_name in ("startup", "shutdown") and operation:
                handler_args = [operation] + handler_args
                operation = ""

            try:
                cmd(profile_name, [operation] + handler_args)
                dry_run = "--dry-run" in handler_args or "-n" in handler_args
                success, message = handler.handle(operation, handler_args, dry_run)
                print(message)
                if not json_requested:
                    _run_injectors(message, f"{profile_name} {operation}")

                # Auto-Watch bei --startup --watch
                if profile_name == "startup" and "--watch" in handler_args:
                    partner = "user"
                    for a in handler_args:
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
            suggestions = app.registry.suggest(profile_name)
            print(f"Unbekannter Befehl: {arg}")
            if suggestions:
                print(f"  Meintest du: {', '.join('--' + s for s in suggestions)}?")
            return 1

    # ── Subcommands (task, mem, backup, etc.) ──

    command = arg

    # 1. Inline-Commands (nicht-Handler)
    if command in INLINE_COMMANDS:
        return INLINE_COMMANDS[command](sub_cmd, args)

    # 2. Skill-Export Spezialfall
    if command == "skill" and sub_cmd == "export":
        return _handle_skill_export(sub_cmd, args)

    # 3. Restore-Befehl (spezielle Logik)
    if command == "restore":
        # a) Backup-Restore (Legacy)
        if sub_cmd == "backup" and args:
            sys.path.insert(0, str(TOOLS_DIR))
            try:
                from backup_manager import BackupManager
                manager = BackupManager()
                success, msg = manager.restore_backup(args[0])
                print(msg if msg else ("OK" if success else "Fehler"))
                return 0 if success else 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1

        # b) File-Restore (SQ020/HQ6)
        if sub_cmd and sub_cmd != "help":
            sys.path.insert(0, str(HUB_DIR))
            try:
                from hub.restore import RestoreHandler
                handler = RestoreHandler(BACH_ROOT)

                # Neue Handler-Integration über handle()
                # Unterstützt: bach restore list <file>, bach restore category <cat>, bach restore <file>
                operation = None
                operation_args = []
                dry_run = "--dry-run" in args

                if sub_cmd in ["list", "--list", "info"] and args:
                    operation = "list" if sub_cmd in ["list", "--list"] else "info"
                    operation_args = args
                elif sub_cmd in ["category", "--category"] and args:
                    operation = "category"
                    operation_args = args
                else:
                    # Datei-Restore: bach restore <file> [--version X]
                    operation = "file"
                    operation_args = [sub_cmd] + args

                success, msg = handler.handle(operation, operation_args, dry_run)
                if msg:
                    print(msg)
                return 0 if success else 1

            except Exception as e:
                print(f"[ERROR] {e}")
                import traceback
                traceback.print_exc()
                return 1

        # c) Help
        print("Usage: bach restore <subcommand>")
        print("Subcommands:")
        print("  backup <name>              Restore von Backup")
        print("  <file>                     Restore einzelne Datei (SQ020)")
        print("  <file> --version <ver>     Restore spezifische Version")
        print("  --list <file>              Zeige verfuegbare Versionen")
        return 0

    # 3b. Downgrade-Befehl (SQ020: CLI-Alias fuer 'bach upgrade downgrade', Runde 24)
    if command == "downgrade":
        sys.path.insert(0, str(HUB_DIR))
        try:
            from upgrade import UpgradeHandler
            handler = UpgradeHandler(BACH_ROOT)
            # Delegiere an UpgradeHandler mit operation="downgrade"
            # sub_cmd + args werden als Argumente uebergeben
            success, msg = handler.handle("downgrade", [sub_cmd] + args if sub_cmd else args)
            print(msg)
            return 0 if success else 1
        except Exception as e:
            print(f"[ERROR] {e}")
            return 1

    # 4. Registry-basiertes Routing (Hauptpfad)
    # NEU: Über Launcher wenn aktiviert (ermöglicht Agent-Delegation)
    use_launcher = os.environ.get("BACH_USE_LAUNCHER", "0") == "1"

    if use_launcher:
        try:
            from core.launcher import route_command
            cmd(command, [sub_cmd] + args)
            success, message = route_command(
                command=command,
                operation=sub_cmd or "",
                args=args,
                source="cli",
                user="user",
                base_path=SYSTEM_ROOT
            )
            print(message)
            if not json_requested:
                _run_injectors(message, f"{command} {sub_cmd}")
            return 0 if success else 1
        except Exception as e:
            log(f"[ERROR] Launcher: {e}")
            print(f"[ERROR] Launcher: {e}")
            # Fallback auf Direct Execute
            use_launcher = False

    # Fallback oder wenn Launcher deaktiviert: Direct Execute
    if not use_launcher:
        app = _get_app()
        handler = app.get_handler(command)
        if handler:
            operation = sub_cmd or ""
            try:
                cmd(command, [operation] + args)
                dry_run = "--dry-run" in args or "-n" in args
                success, message = handler.handle(operation, args, dry_run)
                print(message)
                if not json_requested:
                    _run_injectors(message, f"{command} {operation}")
                return 0 if success else 1
            except Exception as e:
                log(f"[ERROR] {e}")
                print(f"[ERROR] {e}")
                return 1

    # 5. Tool-Fallback (bach <toolname> [args])
    tool_result = _try_run_tool(command, [sub_cmd] + args if sub_cmd else args)
    if tool_result is not None:
        return tool_result

    # 6. Unbekannter Befehl
    suggestions = app.registry.suggest(command)
    print(f"Unbekannter Befehl: {command}")
    if suggestions:
        print(f"  Meintest du: {', '.join(suggestions)}?")
    print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
