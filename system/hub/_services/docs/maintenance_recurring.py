"""Consume four existing doc routines; due/claim authority remains the module."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .maintenance_dispatch import read_state, stamp, write_state

ROUTINES = ("help_forensic", "roadmap_review", "doc_freshness", "docs_changelog_review")


def routine_definitions(root: Path, now: datetime) -> list[dict]:
    base = root / "system/hub/_services/recurring"

    def read(path, optional=False):
        if optional and not path.exists():
            return {}
        if path.is_symlink() or path.stat().st_size > 65536:
            raise TypeError("Invalid recurring source")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError("Invalid recurring source")
        return data

    config = read(base / "config.json").get("recurring_tasks", {})
    state = read(base / "state.json", optional=True).get("last_runs", {})
    if not isinstance(config, dict) or not isinstance(state, dict):
        raise TypeError("Invalid recurring source")
    definitions = []
    for name in ROUTINES:
        value = config.get(name)
        if (
            not isinstance(value, dict)
            or type(value.get("enabled")) is not bool
            or value.get("target") != "tasks"
            or type(value.get("interval_days")) is not int
            or not 1 <= value["interval_days"] <= 366
        ):
            raise ValueError("Invalid documentation routine")
        marker = state.get(name) or value.get("last_run")
        # Existing legacy timestamps are host-local, never invent UTC for them.
        previous = (
            datetime.fromisoformat(marker).astimezone(timezone.utc) if marker else None
        )
        due = previous + timedelta(days=value["interval_days"]) if previous else now
        definitions.append(
            {
                "name": name,
                "enabled": value["enabled"],
                "seconds": value["interval_days"] * 86400,
                "next_due_at": due,
                "dispatch_marker": marker,
                "legacy_title": value.get("task_text"),
                "priority": value.get("priority", "P3"),
            }
        )
    return definitions


def dispatch_routine(dispatcher, definition, *, scheduled_for):
    dispatcher.guard(dispatcher.root)
    state = read_state(dispatcher.state_path)
    entries = state.setdefault("routines", {})
    name = definition["name"]
    old = entries.get(name)
    if old:
        old.update(dispatcher._task_state(old))
        if old["task_status"] not in {"done", "completed", "cancelled"}:
            write_state(dispatcher.state_path, state, dispatcher.guard)
            return {
                "state": "waiting_review_or_work",
                "task_id": old["task_id"],
                "semantic_review_completed": False,
            }
    # Existing legacy work is retained rather than duplicated or taken over.
    from hub.task import TaskHandler

    legacy = definition["legacy_title"]
    if not isinstance(legacy, str) or not legacy:
        raise ValueError("Invalid legacy documentation title")
    title = TaskHandler._sanitize_title(legacy)
    candidates = dispatcher.tasks.list(status=None, filter_text=title, limit=50)
    if len(candidates) >= 50:
        raise RuntimeError("legacy_documentation_lookup_budget")
    if any(
        row.get("title") == title
        and row.get("status") not in {"done", "completed", "cancelled"}
        for row in candidates
    ):
        return {
            "state": "existing_legacy_work",
            "task_id": None,
            "semantic_review_completed": False,
        }
    revision, _ = dispatcher.snapshot(dispatcher.root, None)
    if (
        not isinstance(scheduled_for, str)
        or len(scheduled_for) > 40
        or datetime.fromisoformat(scheduled_for).tzinfo is None
    ):
        raise ValueError("Native routine occurrence required")
    epoch = scheduled_for
    epoch_id = hashlib.sha256(str(epoch).encode()).hexdigest()[:12]
    root_id = hashlib.sha256(str(dispatcher.root.resolve()).encode()).hexdigest()[:8]
    task_title = f"Doku-Routine {name} {root_id} {epoch_id}"
    description = dispatcher._description(
        name, revision, ["system/hub/_services/recurring/config.json"]
    )
    description += (
        f"\nAuslöser: native Routine {name}; native Fälligkeit: {epoch!r}; "
        f"bisheriger Dispatchmarker: {definition['dispatch_marker']!r}."
    )
    task_id, action = dispatcher._ensure_task(
        task_title, description, priority=definition["priority"]
    )
    item = {
        "revision": revision,
        "task_id": task_id,
        "dispatched_at": stamp(dispatcher.clock()),
        "scheduled_for": scheduled_for,
    }
    item.update(dispatcher._task_state(item))
    entries[name] = item
    write_state(dispatcher.state_path, state, dispatcher.guard)
    return {
        "state": "dispatched",
        "task_id": task_id,
        "dispatch_action": action,
        "semantic_review_completed": False,
    }


def delegated_to_maintenance(task_db: Path, routine: str) -> bool:
    if routine not in ROUTINES:
        return False
    path = task_db.parent / "maintenance/config.json"
    if not path.exists():
        return False
    # Invalid/unknown owner configuration blocks only these four legacy routines.
    try:
        from .maintenance_runtime import load_config

        return load_config(path)["enabled"]
    except (OSError, ValueError):
        return True
