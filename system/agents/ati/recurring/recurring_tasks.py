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
ATI Recurring Tasks v1.0
========================
Verwaltet wiederkehrende Tasks.

Features:
  - Intervall-basierte Task-Erstellung
  - Automatische Faelligkeitspruefung
  - Integration mit bach.db/ati_tasks
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Pfade
RECURRING_DIR = Path(__file__).parent.resolve()
ATI_DIR = RECURRING_DIR.parent
BACH_DIR = ATI_DIR.parent.parent.parent

CONFIG_FILE = ATI_DIR / "data" / "config.json"
USER_DB = BACH_DIR / "data" / "bach.db"


def load_config() -> Dict:
    """Laedt ATI-Konfiguration."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_config(config: Dict):
    """Speichert Konfiguration."""
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')


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
                    continue  # Noch nicht faellig
            except (ValueError, TypeError):
                pass  # Bei Parse-Fehler erstellen

        # Task erstellen
        task_text = task_config.get('task_text', f'Recurring: {task_id}')

        # Pruefen ob Task schon existiert (nicht doppelt erstellen)
        try:
            conn = sqlite3.connect(USER_DB)
            existing = conn.execute(
                "SELECT id FROM ati_tasks WHERE task_text = ? AND status = 'offen'",
                (task_text,)
            ).fetchone()

            if existing:
                print(f"  [SKIP] Task existiert bereits: {task_text[:40]}")
                conn.close()
                continue

            # Task erstellen
            conn.execute("""
                INSERT INTO ati_tasks
                (tool_name, tool_path, task_text, aufwand, status, priority_score,
                 source_file, line_number, synced_at, is_synced, tags)
                VALUES ('BACH', '', ?, ?, 'offen', ?, 'recurring', 0, ?, 1, ?)
            """, (
                task_text,
                task_config.get('aufwand', 'mittel'),
                task_config.get('priority_score', 50),
                now.isoformat(),
                f"recurring,{task_id}"
            ))
            conn.commit()
            conn.close()

            # last_run aktualisieren
            config['recurring_tasks'][task_id]['last_run'] = now.isoformat()
            save_config(config)

            created.append(task_text)
            print(f"  [+] Recurring Task erstellt: {task_text[:50]}")

        except Exception as e:
            print(f"  [ERROR] Task-Erstellung fehlgeschlagen: {e}")

    return created


def list_recurring_tasks() -> Dict[str, Dict]:
    """
    Listet alle konfigurierten recurring Tasks.

    Returns:
        Dict mit Task-Konfigurationen
    """
    config = load_config()
    recurring = config.get('recurring_tasks', {})

    result = {}
    now = datetime.now()

    for task_id, task_config in recurring.items():
        last_run_str = task_config.get('last_run')
        interval_days = task_config.get('interval_days', 7)

        # Naechste Faelligkeit berechnen
        if last_run_str:
            try:
                last_run = datetime.fromisoformat(last_run_str)
                next_due = last_run + timedelta(days=interval_days)
                days_until = (next_due - now).days
            except (ValueError, TypeError):
                days_until = 0
                next_due = now
        else:
            days_until = 0
            next_due = now

        result[task_id] = {
            'enabled': task_config.get('enabled', False),
            'task_text': task_config.get('task_text', ''),
            'interval_days': interval_days,
            'last_run': last_run_str,
            'next_due': next_due.isoformat() if next_due else None,
            'days_until': days_until,
            'is_due': days_until <= 0
        }

    return result


def trigger_recurring_task(task_id: str) -> bool:
    """
    Loest einen recurring Task manuell aus.

    Args:
        task_id: ID des recurring Tasks

    Returns:
        True wenn erfolgreich
    """
    config = load_config()
    recurring = config.get('recurring_tasks', {})

    if task_id not in recurring:
        print(f"[ERROR] Recurring Task nicht gefunden: {task_id}")
        return False

    task_config = recurring[task_id]
    task_text = task_config.get('task_text', f'Recurring: {task_id}')

    try:
        conn = sqlite3.connect(USER_DB)

        # Task erstellen
        conn.execute("""
            INSERT INTO ati_tasks
            (tool_name, tool_path, task_text, aufwand, status, priority_score,
             source_file, line_number, synced_at, is_synced, tags)
            VALUES ('BACH', '', ?, ?, 'offen', ?, 'recurring', 0, ?, 1, ?)
        """, (
            task_text,
            task_config.get('aufwand', 'mittel'),
            task_config.get('priority_score', 50),
            datetime.now().isoformat(),
            f"recurring,{task_id}"
        ))
        conn.commit()
        conn.close()

        # last_run aktualisieren
        config['recurring_tasks'][task_id]['last_run'] = datetime.now().isoformat()
        save_config(config)

        print(f"[+] Recurring Task ausgeloest: {task_text[:50]}")
        return True

    except Exception as e:
        print(f"[ERROR] Task-Erstellung fehlgeschlagen: {e}")
        return False


# CLI
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "check":
            print("[ATI RECURRING] Pruefe faellige Tasks...")
            created = check_recurring_tasks()
            if created:
                print(f"\n{len(created)} Tasks erstellt")
            else:
                print("\nKeine Tasks faellig")

        elif cmd == "list":
            tasks = list_recurring_tasks()
            print("[ATI RECURRING TASKS]")
            print("-" * 60)
            for task_id, info in tasks.items():
                status = "AKTIV" if info['enabled'] else "DEAKTIVIERT"
                due = "FAELLIG" if info['is_due'] else f"in {info['days_until']} Tagen"
                print(f"\n{task_id} [{status}]")
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
