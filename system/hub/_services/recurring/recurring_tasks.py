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
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Literal

import sys
# Den DB-Pfad zentral erfragen, nicht selbst bauen: ein repo-relativer Pfad zeigt auf die
# veraltete Kopie im OneDrive-Ordner (bzw. auf ein Verzeichnis, das es gar nicht gibt —
# dort legt sqlite3.connect() still eine leere 0-KB-Datenbank an).
_SYSTEM_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "hub" / "bach_paths.py").exists()
)
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))
from hub.bach_paths import BACH_DB

# ============ PFADE ============

RECURRING_DIR = Path(__file__).parent.resolve()
SERVICES_DIR = RECURRING_DIR.parent
SKILLS_DIR = SERVICES_DIR.parent
BACH_DIR = SKILLS_DIR.parent

CONFIG_FILE = RECURRING_DIR / "config.json"
STATE_FILE = RECURRING_DIR / "state.json"
DATA_DIR = BACH_DIR / "data"
USER_DB = BACH_DB

# ============ CONFIG ============

def load_config() -> Dict:
    """Laedt recurring Tasks Konfiguration."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            pass

    # Default-Config
    return {
        "recurring_tasks": {}
    }

def save_config(config: Dict):
    """Speichert Konfiguration."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')


def load_state() -> Dict:
    """Laedt lokalen recurring Runtime-State."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            pass
    return {"last_runs": {}}


def save_state(state: Dict):
    """Speichert lokalen recurring Runtime-State."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')


def _last_run_for(task_id: str, task_config: Dict, state: Dict) -> str | None:
    last_runs = state.get("last_runs", {})
    return last_runs.get(task_id) or task_config.get('last_run')


def _set_last_run(task_id: str, when: datetime):
    state = load_state()
    state.setdefault("last_runs", {})[task_id] = when.isoformat()
    save_state(state)

# ============ TASK CREATION ============

@dataclass(frozen=True)
class CreationResult:
    """Eindeutiges Ergebnis einer Handler-basierten Task-Erstellung."""

    status: Literal["created", "duplicate", "error"]
    task_id: int | None = None
    message: str = ""


def _task_handler():
    from hub.task import TaskHandler

    return TaskHandler(_SYSTEM_ROOT)


def _ati_handler():
    from hub.ati import ATIHandler

    return ATIHandler(_SYSTEM_ROOT)


def _find_open_task_id(
    table: Literal["tasks", "ati_tasks"], title: str, original_title: str | None = None
) -> int | None:
    """Prueft Duplikate read-only; alle Schreibvorgaenge bleiben im Handler."""
    if table == "tasks":
        title_column = "title"
        statuses = ("pending", "open", "in_progress")
    else:
        title_column = "task_text"
        statuses = ("offen", "in_arbeit")

    placeholders = ", ".join("?" for _ in statuses)
    db_uri = f"file:{Path(USER_DB).resolve().as_posix()}?mode=ro"
    titles = (title, original_title) if original_title is not None else (title,)
    title_placeholders = ", ".join("?" for _ in titles)
    with sqlite3.connect(db_uri, uri=True) as conn:
        row = conn.execute(
            f"SELECT id FROM {table} WHERE {title_column} IN ({title_placeholders}) "
            f"AND status IN ({placeholders}) ORDER BY id LIMIT 1",
            (*titles, *statuses),
        ).fetchone()
    return int(row[0]) if row else None


def _task_id_from_message(message: str) -> int | None:
    match = re.search(r"(?:Task\s+#?|ID\s+)(-?\d+)", message)
    return int(match.group(1)) if match else None


def create_task_in_ati(
    task_text: str, aufwand: str, priority: float, tags: str
) -> CreationResult:
    """Erstellt einen ATI-Task ausschliesslich ueber den ATIHandler."""
    try:
        existing_id = _find_open_task_id("ati_tasks", task_text)
        if existing_id is not None:
            return CreationResult("duplicate", existing_id)

        ok, message = _ati_handler().handle(
            "task",
            [
                "add",
                task_text,
                "--tool",
                "BACH",
                "--aufwand",
                aufwand,
                "--priority-score",
                str(priority),
                "--source",
                "recurring",
                "--tags",
                tags,
            ],
        )
        task_id = _task_id_from_message(message)
        if ok and task_id is not None:
            return CreationResult("created", task_id, message)
        print(f"  [ERROR] ATI-Task Erstellung fehlgeschlagen: {message}")
        return CreationResult("error", message=message)

    except Exception as e:
        print(f"  [ERROR] ATI-Task Erstellung fehlgeschlagen: {e}")
        return CreationResult("error", message=str(e))


def create_task_in_bach(
    task_text: str, priority: str, project: str
) -> CreationResult:
    """Erstellt einen BACH-Task ueber den federationsfaehigen TaskHandler."""
    try:
        from hub.task import TaskHandler

        normalized_title = TaskHandler._sanitize_title(task_text)
        existing_id = _find_open_task_id("tasks", normalized_title, task_text)
        if existing_id is not None:
            return CreationResult("duplicate", existing_id)

        ok, message = _task_handler().handle(
            "add",
            [
                task_text,
                "--priority",
                priority,
                "--category",
                project,
                "--creation-origin",
                "recurring",
            ],
        )
        task_id = _task_id_from_message(message)
        if ok and task_id is not None:
            return CreationResult("created", task_id, message)
        print(f"  [ERROR] BACH-Task Erstellung fehlgeschlagen: {message}")
        return CreationResult("error", message=message)

    except Exception as e:
        print(f"  [ERROR] BACH-Task Erstellung fehlgeschlagen: {e}")
        return CreationResult("error", message=str(e))


# ============ RECURRING LOGIC ============

def check_recurring_tasks() -> List[str]:
    """
    Prueft ob wiederkehrende Tasks faellig sind und erstellt sie.

    Returns:
        Liste der erstellten Task-Texte
    """
    config = load_config()
    recurring = config.get('recurring_tasks', {})
    state = load_state()

    if not recurring:
        return []

    created = []
    now = datetime.now()

    for task_id, task_config in recurring.items():
        from hub._services.docs.maintenance_recurring import delegated_to_maintenance
        if delegated_to_maintenance(Path(USER_DB), task_id):
            continue
        if not task_config.get('enabled', False):
            continue

        # Pruefen ob faellig
        last_run_str = _last_run_for(task_id, task_config, state)
        interval_days = task_config.get('interval_days', 7)

        if last_run_str:
            try:
                last_run = datetime.fromisoformat(last_run_str)
                next_due = last_run + timedelta(days=interval_days)
                if now < next_due:
                    continue
            except (ValueError, TypeError):
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

        if result.status == "duplicate":
            print(f"  [SKIP] Task existiert bereits: {task_text[:40]}")
            # Bestehender offener Task gilt als bereits eingeplanter Lauf.
            _set_last_run(task_id, now)
        elif result.status == "created":
            # last_run aktualisieren
            _set_last_run(task_id, now)
            created.append(task_text)
            print(f"  [+] Recurring Task erstellt: {task_text[:50]}")
        # status == "error" bedeutet Fehler (bereits geloggt)

    return created

def list_recurring_tasks() -> Dict[str, Dict]:
    """Listet alle konfigurierten recurring Tasks."""
    config = load_config()
    recurring = config.get('recurring_tasks', {})
    state = load_state()

    result = {}
    now = datetime.now()

    for task_id, task_config in recurring.items():
        last_run_str = _last_run_for(task_id, task_config, state)
        interval_days = task_config.get('interval_days', 7)

        if last_run_str:
            try:
                last_run = datetime.fromisoformat(last_run_str)
                next_due = last_run + timedelta(days=interval_days)
                remaining = next_due - now
                is_due = remaining.total_seconds() <= 0
                days_until = 0 if is_due else max(0, remaining.days)
            except (ValueError, TypeError):
                days_until = 0
                next_due = now
                is_due = True
        else:
            days_until = 0
            next_due = now
            is_due = True

        result[task_id] = {
            'enabled': task_config.get('enabled', False),
            'task_text': task_config.get('task_text', ''),
            'target': task_config.get('target', 'ati_tasks'),
            'interval_days': interval_days,
            'last_run': last_run_str,
            'next_due': next_due.isoformat() if next_due else None,
            'days_until': days_until,
            'is_due': is_due
        }

    return result

def trigger_recurring_task(task_id: str) -> bool:
    """Loest einen recurring Task manuell aus."""
    from hub._services.docs.maintenance_recurring import delegated_to_maintenance
    if delegated_to_maintenance(Path(USER_DB), task_id):
        print("  [SKIP] Doku-Routine ist dem nativen Wartungsbetrieb zugeordnet")
        return False
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

    if result.status == "created":
        _set_last_run(task_id, datetime.now())
        print(f"[+] Recurring Task ausgeloest: {task_text[:50]}")
        return True
    elif result.status == "duplicate":
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

    _set_last_run(task_id, datetime.now())
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
