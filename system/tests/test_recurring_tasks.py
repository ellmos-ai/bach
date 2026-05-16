# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT

import sys
from datetime import datetime, timedelta
from pathlib import Path


SYSTEM_ROOT = Path(__file__).parent.parent
RECURRING_ROOT = SYSTEM_ROOT / "hub" / "_services" / "recurring"

if str(RECURRING_ROOT) not in sys.path:
    sys.path.insert(0, str(RECURRING_ROOT))

import recurring_tasks


def test_list_recurring_tasks_not_due_until_exact_timestamp(monkeypatch):
    last_run = datetime.now() - timedelta(days=14) + timedelta(hours=1)
    config = {
        "recurring_tasks": {
            "edge_case": {
                "enabled": True,
                "interval_days": 14,
                "task_text": "Edge case",
                "target": "tasks",
                "last_run": last_run.isoformat(),
            }
        }
    }

    monkeypatch.setattr(recurring_tasks, "load_config", lambda: config)

    tasks = recurring_tasks.list_recurring_tasks()

    assert tasks["edge_case"]["days_until"] == 0
    assert tasks["edge_case"]["is_due"] is False


def test_list_recurring_tasks_due_after_deadline_passes(monkeypatch):
    last_run = datetime.now() - timedelta(days=14, minutes=1)
    config = {
        "recurring_tasks": {
            "overdue": {
                "enabled": True,
                "interval_days": 14,
                "task_text": "Overdue case",
                "target": "tasks",
                "last_run": last_run.isoformat(),
            }
        }
    }

    monkeypatch.setattr(recurring_tasks, "load_config", lambda: config)

    tasks = recurring_tasks.list_recurring_tasks()

    assert tasks["overdue"]["days_until"] == 0
    assert tasks["overdue"]["is_due"] is True
