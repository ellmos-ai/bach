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
ATI Tool Discovery & Onboarding v1.1
====================================
Erkennt neue Tools und erstellt Onboarding-Tasks.

Portiert von: _BATCH/scanner.py (_check_new_tools, _create_onboarding_tasks)
Angepasst fuer: BACH v1.1 ATI Agent

v1.1 (2026-02-01): Migration auf bach.db - Tabellen umbenannt zu ati_*

Features:
  - Erkennung neuer Tools beim Scan
  - Automatische Onboarding-Task-Erstellung
  - Integration mit bach.db/ati_tasks
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Set, List, Dict

# Pfade relativ zu BACH
ONBOARDING_DIR = Path(__file__).parent.resolve()
ATI_DIR = ONBOARDING_DIR.parent
BACH_DIR = ATI_DIR.parent.parent.parent

KNOWN_TOOLS_FILE = ATI_DIR / "data" / "known_tools.json"

# Den DB-Pfad zentral erfragen, nicht selbst bauen. BACH_DIR zeigt auf den
# Repo-Root — BACH/data/bach.db existiert gar nicht, sqlite3.connect() legt dort
# still eine leere 0-KB-Datenbank an.
import sys

_SYSTEM_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "hub" / "bach_paths.py").exists()
)
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))
from hub.bach_paths import BACH_DB


def get_known_tools() -> Set[str]:
    """Laedt Liste bekannter Tools."""
    if KNOWN_TOOLS_FILE.exists():
        try:
            data = json.loads(KNOWN_TOOLS_FILE.read_text(encoding='utf-8'))
            return set(data.get('tools', []))
        except (json.JSONDecodeError, OSError):
            pass
    return set()


def save_known_tools(tools: Set[str]):
    """Speichert Liste bekannter Tools."""
    KNOWN_TOOLS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        'tools': sorted(tools),
        'updated_at': datetime.now().isoformat()
    }
    KNOWN_TOOLS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


def get_current_tools() -> Set[str]:
    """Holt aktuelle Tools aus ati_tool_registry in bach.db."""
    try:
        conn = sqlite3.connect(BACH_DB)
        tools = conn.execute("SELECT name FROM ati_tool_registry").fetchall()
        conn.close()
        return {t[0] for t in tools}
    except (sqlite3.OperationalError, sqlite3.DatabaseError, OSError):
        return set()


def check_new_tools() -> List[str]:
    """
    Prueft auf neu entdeckte Tools.

    Returns:
        Liste der neuen Tool-Namen
    """
    known = get_known_tools()
    current = get_current_tools()

    new_tools = current - known

    if new_tools:
        print(f"[ATI] {len(new_tools)} neue Tools entdeckt: {', '.join(sorted(new_tools))}")

        # Onboarding-Tasks erstellen
        for tool_name in new_tools:
            create_onboarding_tasks(tool_name)

        # Bekannte Tools aktualisieren
        save_known_tools(current)

    return sorted(new_tools)


def create_onboarding_tasks(tool_name: str) -> List[int]:
    """
    Erstellt Onboarding-Tasks fuer ein neues Tool.

    Args:
        tool_name: Name des Tools

    Returns:
        Liste der erstellten Task-IDs
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    created_ids = []

    # Onboarding-Task-Definitionen
    onboarding_tasks = [
        {
            "task_text": f"Feature-Analyse erstellen: {tool_name}",
            "aufwand": "mittel",
            "priority_score": 70,
            "tags": "onboarding,analyse"
        },
        {
            "task_text": f"Code-Qualitaetspruefung: {tool_name}",
            "aufwand": "niedrig",
            "priority_score": 60,
            "tags": "onboarding,qualitaet"
        },
        {
            "task_text": f"AUFGABEN.txt erstellen/pruefen: {tool_name}",
            "aufwand": "niedrig",
            "priority_score": 50,
            "tags": "onboarding,setup"
        }
    ]

    try:
        conn = sqlite3.connect(BACH_DB)

        # Tool-Pfad aus Registry holen
        tool_info = conn.execute(
            "SELECT path FROM ati_tool_registry WHERE name = ?",
            (tool_name,)
        ).fetchone()
        tool_path = tool_info[0] if tool_info else ""

        for task in onboarding_tasks:
            # Pruefen ob Task schon existiert
            existing = conn.execute(
                "SELECT id FROM ati_tasks WHERE tool_name = ? AND task_text LIKE ?",
                (tool_name, f"%{task['task_text'].split(':')[0]}%")
            ).fetchone()

            if existing:
                print(f"  [SKIP] Task existiert bereits: {task['task_text'][:50]}")
                continue

            cursor = conn.execute("""
                INSERT INTO ati_tasks
                (tool_name, tool_path, task_text, aufwand, status, priority_score,
                 source_file, line_number, synced_at, is_synced, tags)
                VALUES (?, ?, ?, ?, 'offen', ?, 'onboarding', 0, ?, 1, ?)
            """, (
                tool_name,
                tool_path,
                task['task_text'],
                task['aufwand'],
                task['priority_score'],
                datetime.now().isoformat(),
                task['tags']
            ))
            created_ids.append(cursor.lastrowid)
            print(f"  [+] Onboarding-Task erstellt: {task['task_text'][:50]}")

        conn.commit()
        conn.close()

    except Exception as e:
        print(f"  [ERROR] Onboarding-Tasks fehlgeschlagen: {e}")

    return created_ids


def onboard_project(path: str) -> Dict:
    """
    Onboardet ein neues Projekt manuell.

    Args:
        path: Pfad zum Projekt-Ordner

    Returns:
        Dict mit Status und erstellten Tasks
    """
    project_path = Path(path)

    if not project_path.exists():
        return {"success": False, "error": f"Pfad existiert nicht: {path}"}

    if not project_path.is_dir():
        return {"success": False, "error": f"Kein Verzeichnis: {path}"}

    tool_name = project_path.name

    # In ati_tool_registry eintragen falls nicht vorhanden
    try:
        conn = sqlite3.connect(BACH_DB)

        existing = conn.execute(
            "SELECT id FROM ati_tool_registry WHERE path = ?",
            (str(project_path),)
        ).fetchone()

        if not existing:
            # AUFGABEN.txt vorhanden?
            has_aufgaben = (project_path / "AUFGABEN.txt").exists()

            conn.execute("""
                INSERT INTO ati_tool_registry
                (name, path, has_aufgaben, created_at)
                VALUES (?, ?, ?, ?)
            """, (
                tool_name,
                str(project_path),
                1 if has_aufgaben else 0,
                datetime.now().isoformat()
            ))
            conn.commit()
            print(f"[ATI] Tool registriert: {tool_name}")

        conn.close()

    except Exception as e:
        return {"success": False, "error": f"Registry-Fehler: {e}"}

    # Onboarding-Tasks erstellen
    task_ids = create_onboarding_tasks(tool_name)

    # Bekannte Tools aktualisieren
    known = get_known_tools()
    known.add(tool_name)
    save_known_tools(known)

    return {
        "success": True,
        "tool_name": tool_name,
        "path": str(project_path),
        "tasks_created": len(task_ids),
        "task_ids": task_ids
    }


# CLI
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "check":
            new = check_new_tools()
            if new:
                print(f"\nNeue Tools: {', '.join(new)}")
            else:
                print("Keine neuen Tools gefunden")

        elif cmd == "onboard" and len(sys.argv) > 2:
            result = onboard_project(sys.argv[2])
            print(json.dumps(result, indent=2, ensure_ascii=False))

        elif cmd == "list":
            known = get_known_tools()
            print(f"Bekannte Tools ({len(known)}):")
            for t in sorted(known):
                print(f"  - {t}")
        else:
            print("Usage:")
            print("  python tool_discovery.py check      - Prueft auf neue Tools")
            print("  python tool_discovery.py onboard PATH - Onboardet Projekt")
            print("  python tool_discovery.py list       - Zeigt bekannte Tools")
    else:
        # Default: check
        check_new_tools()
