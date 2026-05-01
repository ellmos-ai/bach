#!/usr/bin/env python3
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
BACH Recurring Tasks v1.1
=========================
System-Service fuer wiederkehrende Tasks.

WICHTIG: Dies ist ein SYSTEM-SERVICE, nicht ATI-spezifisch!
Kann fuer alle Agenten und System-Wartung verwendet werden.

Usage:
  python recurring_tasks.py check           # Prueft faellige Tasks
  python recurring_tasks.py list            # Listet alle recurring Tasks
  python recurring_tasks.py trigger ID      # Loest Task manuell aus

Konfiguration:
  Die recurring Tasks werden in config.json definiert.
  Jeder Task kann einem "target" zugewiesen werden:
    - "ati_tasks" -> bach.db/ati_tasks (ATI Agent)
    - "tasks" -> bach.db/tasks (BACH System)
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List

# ============ PFADE ============

RECURRING_DIR = Path(__file__).parent.resolve()
SERVICES_DIR = RECURRING_DIR.parent
SKILLS_DIR = SERVICES_DIR.parent
BACH_DIR = SKILLS_DIR.parent

CONFIG_FILE = RECURRING_DIR / "config.json"
DATA_DIR = BACH_DIR / "data"
USER_DB = DATA_DIR / "bach.db"
BACH_DB = DATA_DIR / "bach.db"

# ============ CONFIG ============

def load_config() -> Dict:
    """Laedt recurring Tasks Konfiguration."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        except:
            pass

    # Default-Config
    return {
        "recurring_tasks": {}
    }

def save_config(config: Dict):
    """Speichert Konfiguration."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')

# ============ TASK CREATION ============

def create_task_in_ati(task_text: str, aufwand: str, priority: float, tags: str) -> int:
    """Erstellt Task in bach.db/ati_tasks."""
    try:
        conn = sqlite3.connect(USER_DB)

        # Pruefen ob Task schon existiert
        existing = conn.execute(
            "SELECT id FROM ati_tasks WHERE task_text = ? AND status = 'offen'",
            (task_text,)
        ).fetchone()

        if existing:
            conn.close()
            return -1  # Bereits vorhanden

        cursor = conn.execute("""
            INSERT INTO ati_tasks
            (tool_name, tool_path, task_text, aufwand, status, priority_score,
             source_file, line_number, synced_at, is_synced, tags)
            VALUES ('BACH', '', ?, ?, 'offen', ?, 'recurring', 0, ?, 1, ?)
        """, (task_text, aufwand, priority, datetime.now().isoformat(), tags))

        task_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return task_id

    except Exception as e:
        print(f"  [ERROR] ATI-Task Erstellung fehlgeschlagen: {e}")
        return 0

def create_task_in_bach(task_text: str, priority: str, project: str) -> int:
    """Erstellt Task in bach.db/tasks."""
    try:
        conn = sqlite3.connect(BACH_DB)

        # Pruefen ob Task schon existiert
        existing = conn.execute(
            "SELECT id FROM tasks WHERE title = ? AND status IN ('pending', 'open')",
            (task_text,)
        ).fetchone()

        if existing:
            conn.close()
            return -1

        cursor = conn.execute("""
            INSERT INTO tasks (title, status, priority, project, created_at, source)
            VALUES (?, 'pending', ?, ?, ?, 'recurring')
        """, (task_text, priority, project, datetime.now().isoformat()))

        task_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return task_id

    except Exception as e:
        print(f"  [ERROR] BACH-Task Erstellung fehlgeschlagen: {e}")
        return 0

# ============ RECURRING LOGIC ============

def check_recurring_tasks() -> List[str]:
    """
    Prueft ob wiederkehrende Tasks faellig sind und erstellt sie.

    Returns:
        Liste der erstellten Task-Texte
    """
    config = load_config()
    recurring = config.get('recurring_tasks', {})

    if not recurring:
        return []

    created = []
    now = datetime.now()

    for task_id, task_config in recurring.items():
        if not task_config.get('enabled', False):
            continue

        # Pruefen ob faellig
        last_run_str = task_config.get('last_run')
        interval_days = task_config.get('interval_days', 7)

        if last_run_str:
            try:
                last_run = datetime.fromisoformat(last_run_str)
                next_due = last_run + timedelta(days=interval_days)
                if now < next_due:
                    continue
            except:
                pass

        # Task erstellen
        task_text = task_config.get('task_text', f'Recurring: {task_id}')
        target = task_config.get('target', 'ati_tasks')

        if target == 'ati_tasks':
            result = create_task_in_ati(
                task_text,
                task_config.get('aufwand', 'mittel'),
                task_config.get('priority_score', 50),
                f"recurring,{task_id}"
            )
        else:
            result = create_task_in_bach(
                task_text,
                task_config.get('priority', 'P3'),
                task_config.get('project', 'BACH')
            )

        if result == -1:
            print(f"  [SKIP] Task existiert bereits: {task_text[:40]}")
            # Bestehender offener Task gilt als bereits eingeplanter Lauf.
            config['recurring_tasks'][task_id]['last_run'] = now.isoformat()
            save_config(config)
        elif result > 0:
            # last_run aktualisieren
            config['recurring_tasks'][task_id]['last_run'] = now.isoformat()
            save_config(config)
            created.append(task_text)
            print(f"  [+] Recurring Task erstellt: {task_text[:50]}")
        # result == 0 bedeutet Fehler (bereits geloggt)

    return created

def list_recurring_tasks() -> Dict[str, Dict]:
    """Listet alle konfigurierten recurring Tasks."""
    config = load_config()
    recurring = config.get('recurring_tasks', {})

    result = {}
    now = datetime.now()

    for task_id, task_config in recurring.items():
        last_run_str = task_config.get('last_run')
        interval_days = task_config.get('interval_days', 7)

        if last_run_str:
            try:
                last_run = datetime.fromisoformat(last_run_str)
                next_due = last_run + timedelta(days=interval_days)
                days_until = (next_due - now).days
            except:
                days_until = 0
                next_due = now
        else:
            days_until = 0
            next_due = now

        result[task_id] = {
            'enabled': task_config.get('enabled', False),
            'task_text': task_config.get('task_text', ''),
            'target': task_config.get('target', 'ati_tasks'),
            'interval_days': interval_days,
            'last_run': last_run_str,
            'next_due': next_due.isoformat() if next_due else None,
            'days_until': days_until,
            'is_due': days_until <= 0
        }

    return result

def trigger_recurring_task(task_id: str) -> bool:
    """Loest einen recurring Task manuell aus."""
    config = load_config()
    recurring = config.get('recurring_tasks', {})

    if task_id not in recurring:
        print(f"[ERROR] Recurring Task nicht gefunden: {task_id}")
        return False

    task_config = recurring[task_id]
    task_text = task_config.get('task_text', f'Recurring: {task_id}')
    target = task_config.get('target', 'ati_tasks')

    if target == 'ati_tasks':
        result = create_task_in_ati(
            task_text,
            task_config.get('aufwand', 'mittel'),
            task_config.get('priority_score', 50),
            f"recurring,{task_id}"
        )
    else:
        result = create_task_in_bach(
            task_text,
            task_config.get('priority', 'P3'),
            task_config.get('project', 'BACH')
        )

    if result > 0:
        config['recurring_tasks'][task_id]['last_run'] = datetime.now().isoformat()
        save_config(config)
        print(f"[+] Recurring Task ausgeloest: {task_text[:50]}")
        return True
    elif result == -1:
        print(f"[SKIP] Task existiert bereits")
        return False
    else:
        return False


def mark_recurring_done(task_id: str) -> bool:
    """
    Markiert einen recurring Task als erledigt (aktualisiert last_run).
    
    Verwendet nach manuellem Erledigen des Tasks oder nach Self-Check.
    """
    config = load_config()
    recurring = config.get('recurring_tasks', {})

    if task_id not in recurring:
        print(f"[ERROR] Recurring Task nicht gefunden: {task_id}")
        return False

    config['recurring_tasks'][task_id]['last_run'] = datetime.now().isoformat()
    save_config(config)
    print(f"[OK] Recurring Task '{task_id}' als erledigt markiert")
    return True

# ============ CLI ============

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "check":
            print("[RECURRING] Pruefe faellige Tasks...")
            created = check_recurring_tasks()
            if created:
                print(f"\n{len(created)} Tasks erstellt")
            else:
                print("\nKeine Tasks faellig")

        elif cmd == "list":
            tasks = list_recurring_tasks()
            print("[RECURRING TASKS]")
            print("-" * 60)
            for task_id, info in tasks.items():
                status = "AKTIV" if info['enabled'] else "DEAKTIVIERT"
                due = "FAELLIG" if info['is_due'] else f"in {info['days_until']} Tagen"
                target = info['target']
                print(f"\n{task_id} [{status}] -> {target}")
                print(f"  Text: {info['task_text'][:50]}")
                print(f"  Intervall: {info['interval_days']} Tage")
                print(f"  Status: {due}")

        elif cmd == "trigger" and len(sys.argv) > 2:
            trigger_recurring_task(sys.argv[2])

        else:
            print("Usage:")
            print("  python recurring_tasks.py check       - Prueft faellige Tasks")
            print("  python recurring_tasks.py list        - Listet alle recurring Tasks")
            print("  python recurring_tasks.py trigger ID  - Loest Task manuell aus")
    else:
        check_recurring_tasks()
