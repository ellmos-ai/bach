#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
BACH Recurring Tasks Handler v1.0.0
===================================
CLI-Handler fuer wiederkehrende Tasks.

Befehle:
  bach --recurring check    - Prueft faellige Tasks
  bach --recurring list     - Listet alle recurring Tasks
  bach --recurring trigger ID - Loest Task manuell aus
  bach --recurring enable ID  - Aktiviert Task
  bach --recurring disable ID - Deaktiviert Task
"""

import sys
from pathlib import Path
from typing import Tuple, List

# BACH Pfade
HANDLER_DIR = Path(__file__).parent.resolve()  # system/hub/
SYSTEM_DIR = HANDLER_DIR.parent                 # system/
RECURRING_DIR = HANDLER_DIR / "_services" / "recurring"  # system/hub/_services/recurring/

sys.path.insert(0, str(RECURRING_DIR))

from .base import BaseHandler


from hub._services.ocean_stack_bridge import deprecated_legacy_bach
@deprecated_legacy_bach("ellmos-scheduler")
class RecurringHandler(BaseHandler):
    """Handler fuer recurring Tasks."""

    @property
    def profile_name(self) -> str:
        return "recurring"

    @property
    def target_file(self) -> Path:
        return RECURRING_DIR / "config.json"

    def get_operations(self) -> dict:
        return {
            "list": "Alle recurring Tasks anzeigen",
            "check": "Faellige Tasks erstellen",
            "trigger": "Task manuell ausloesen (+ ID)",
            "done": "Task als erledigt markieren (+ ID) - aktualisiert last_run",
            "enable": "Task aktivieren (+ ID)",
            "disable": "Task deaktivieren (+ ID)",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        """Verarbeitet recurring Befehle."""
        from recurring_tasks import (
            check_recurring_tasks,
            list_recurring_tasks,
            trigger_recurring_task,
            mark_recurring_done,
            load_config,
            save_config
        )

        output = []

        if not operation:
            operation = 'list'

        cmd = operation.lower()

        if cmd == 'check':
            output.append("[RECURRING] Pruefe faellige Tasks...")
            created = check_recurring_tasks()
            if created:
                output.append(f"\n[OK] {len(created)} Tasks erstellt")
            else:
                output.append("\n[OK] Keine Tasks faellig")

        elif cmd == 'list':
            tasks = list_recurring_tasks()
            output.append("\n[RECURRING TASKS]")
            output.append("=" * 65)
            if not tasks:
                output.append("  Keine recurring Tasks konfiguriert")
                output.append("  -> Bearbeite: skills/_services/recurring/config.json")
                return True, "\n".join(output)

            for task_id, info in tasks.items():
                status = "[x]" if info['enabled'] else "[ ]"
                due = "FAELLIG!" if info['is_due'] else f"in {info['days_until']}d"
                target = "ATI" if info['target'] == 'ati_tasks' else "BACH"
                output.append(f"\n  {status} {task_id} -> {target}")
                output.append(f"      Text: {info['task_text'][:50]}")
                output.append(f"      Intervall: {info['interval_days']}d | Status: {due}")

            output.append("\n" + "-" * 65)
            active = sum(1 for t in tasks.values() if t['enabled'])
            due = sum(1 for t in tasks.values() if t['is_due'] and t['enabled'])
            output.append(f"  {len(tasks)} Tasks | {active} aktiv | {due} faellig")

        elif cmd == 'trigger' and args:
            task_id = args[0]
            success = trigger_recurring_task(task_id)
            if success:
                output.append(f"[OK] Task '{task_id}' ausgeloest")
            else:
                return False, f"[ERROR] Task '{task_id}' konnte nicht ausgeloest werden"

        elif cmd == 'done' and args:
            task_id = args[0]
            success = mark_recurring_done(task_id)
            if success:
                output.append(f"[OK] Recurring Task '{task_id}' als erledigt markiert")
            else:
                return False, f"[ERROR] Task nicht gefunden: {task_id}"

        elif cmd == 'enable' and args:
            task_id = args[0]
            config = load_config()
            if task_id in config.get('recurring_tasks', {}):
                config['recurring_tasks'][task_id]['enabled'] = True
                save_config(config)
                output.append(f"[OK] Task '{task_id}' aktiviert")
            else:
                return False, f"[ERROR] Task nicht gefunden: {task_id}"

        elif cmd == 'disable' and args:
            task_id = args[0]
            config = load_config()
            if task_id in config.get('recurring_tasks', {}):
                config['recurring_tasks'][task_id]['enabled'] = False
                save_config(config)
                output.append(f"[OK] Task '{task_id}' deaktiviert")
            else:
                return False, f"[ERROR] Task nicht gefunden: {task_id}"

        else:
            output.append("[RECURRING] Wiederkehrende Tasks")
            output.append("-" * 40)
            output.append("  bach --recurring list           Alle Tasks anzeigen")
            output.append("  bach --recurring check          Faellige Tasks erstellen")
            output.append("  bach --recurring trigger ID     Task manuell ausloesen")
            output.append("  bach --recurring enable ID      Task aktivieren")
            output.append("  bach --recurring disable ID     Task deaktivieren")

        return True, "\n".join(output)
