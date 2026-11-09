# BACH Adapter: automation-master
"""BACH Adapter for module automations via automation-master, SQLite and sync manifests.

T-20261107-206833979 / PB-6 follow-up:
Probes module automations across available sources:
1. `automation_master` python package if installed or importable.
2. `automation_routines`, `automation_triggers`, and `scheduler_jobs` tables in `bach.db` (or given `db_path`).
3. `.SYNC/_automations` manifests (e.g. laptop.json, ideapad.json) if present.
4. Module manifests (.AUTOMATION/automation-master/ellmos-module.v2.json, etc.).

Returns stable items with IDs <source>:<id> and unified fields:
- id: str (<source>:<id>)
- name: str
- title: str
- schedule: str | None
- last_run: str | None
- last_result: str | None
- next_run: str | None
- enabled: bool
- source: str
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _connect_db(db_path: str | Path) -> sqlite3.Connection | None:
    path = Path(db_path)
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as exc:
        logger.warning("Could not connect to database %s: %s", db_path, exc)
        return None


def _get_table_names(conn: sqlite3.Connection) -> set[str]:
    try:
        cursor = conn.cursor()
        rows = cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {str(row[0]) for row in rows}
    except Exception as exc:
        logger.warning("Could not read table names: %s", exc)
        return set()


def _get_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    try:
        cursor = conn.cursor()
        rows = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {str(row[1]) for row in rows}
    except Exception:
        return set()


def _extract_from_automation_routines(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    columns = _get_table_columns(conn, "automation_routines")
    if not columns:
        return items

    has_is_active = "is_active" in columns
    has_last_run = "last_run" in columns
    has_next_run = "next_run" in columns
    has_interval = "interval" in columns

    try:
        cursor = conn.cursor()
        rows = cursor.execute("SELECT * FROM automation_routines ORDER BY id").fetchall()
        for row in rows:
            row_dict = dict(row)
            raw_id = str(row_dict.get("id", ""))
            name = str(row_dict.get("name") or f"routine-{raw_id}")
            source = "automation-routine"
            item = {
                "id": f"{source}:{raw_id}",
                "name": name,
                "title": name,
                "schedule": str(row_dict.get("interval")) if has_interval and row_dict.get("interval") else "periodic",
                "last_run": str(row_dict.get("last_run")) if has_last_run and row_dict.get("last_run") else None,
                "last_result": str(row_dict.get("last_result")) if "last_result" in row_dict and row_dict.get("last_result") else None,
                "next_run": str(row_dict.get("next_run")) if has_next_run and row_dict.get("next_run") else None,
                "enabled": bool(row_dict.get("is_active")) if has_is_active else True,
                "source": source,
                "kind": "routine",
                "origin": "Modul-Routine",
            }
            items.append(item)
    except Exception as exc:
        logger.warning("Error reading automation_routines: %s", exc)

    return items


def _extract_from_automation_triggers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    columns = _get_table_columns(conn, "automation_triggers")
    if not columns:
        return items

    has_is_active = "is_active" in columns
    try:
        cursor = conn.cursor()
        rows = cursor.execute("SELECT * FROM automation_triggers ORDER BY id").fetchall()
        for row in rows:
            row_dict = dict(row)
            raw_id = str(row_dict.get("id", ""))
            name = str(row_dict.get("name") or f"trigger-{raw_id}")
            source = "automation-trigger"
            item = {
                "id": f"{source}:{raw_id}",
                "name": name,
                "title": f"Trigger: {name}",
                "schedule": "bei Ereignis",
                "last_run": str(row_dict.get("last_run")) if "last_run" in row_dict and row_dict.get("last_run") else None,
                "last_result": str(row_dict.get("last_result")) if "last_result" in row_dict and row_dict.get("last_result") else None,
                "next_run": None,
                "enabled": bool(row_dict.get("is_active")) if has_is_active else True,
                "source": source,
                "kind": "job",
                "origin": "Modul-Trigger",
            }
            items.append(item)
    except Exception as exc:
        logger.warning("Error reading automation_triggers: %s", exc)

    return items


def _extract_from_scheduler_jobs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    columns = _get_table_columns(conn, "scheduler_jobs")
    if not columns:
        return items

    has_is_active = "is_active" in columns
    has_last_run = "last_run" in columns
    has_next_run = "next_run" in columns
    has_last_result = "last_result" in columns
    has_schedule = "schedule" in columns
    has_job_type = "job_type" in columns
    has_desc = "description" in columns

    try:
        cursor = conn.cursor()
        rows = cursor.execute("SELECT * FROM scheduler_jobs ORDER BY id").fetchall()
        for row in rows:
            row_dict = dict(row)
            raw_id = str(row_dict.get("id", ""))
            name = str(row_dict.get("name") or f"job-{raw_id}")
            desc = str(row_dict.get("description") or "").strip() if has_desc else ""
            title = desc or name
            sched = str(row_dict.get("schedule") or "") if has_schedule else ""
            if not sched and has_job_type and row_dict.get("job_type"):
                sched = str(row_dict.get("job_type"))
            source = "scheduler"
            item = {
                "id": f"{source}:{raw_id}",
                "name": name,
                "title": title,
                "schedule": sched or "Nicht geplant",
                "last_run": str(row_dict.get("last_run")) if has_last_run and row_dict.get("last_run") else None,
                "last_result": str(row_dict.get("last_result")) if has_last_result and row_dict.get("last_result") else None,
                "next_run": str(row_dict.get("next_run")) if has_next_run and row_dict.get("next_run") else None,
                "enabled": bool(row_dict.get("is_active")) if has_is_active else True,
                "source": source,
                "kind": "job",
                "origin": "Scheduler-Job",
            }
            items.append(item)
    except Exception as exc:
        logger.warning("Error reading scheduler_jobs: %s", exc)

    return items


def _extract_from_sync_dir(sync_dir: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not sync_dir.is_dir():
        return items

    for json_file in sorted(sync_dir.glob("*.json")):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            cells = data.get("zellen")
            if not isinstance(cells, list):
                continue
            for cell in cells:
                if not isinstance(cell, dict):
                    continue
                raw_id = str(cell.get("id") or "").strip()
                if not raw_id:
                    continue
                source = "sync"
                status = str(cell.get("status") or "").lower()
                enabled = status in ("enabled", "active")
                schedule = str(cell.get("zeitplan") or "Nicht geplant")
                last_run = cell.get("letzter_nachweis")
                last_result = "success" if enabled and last_run else (status or None)
                title = str(cell.get("bereich") or cell.get("zielobjekt") or raw_id)
                items.append({
                    "id": f"{source}:{raw_id}",
                    "name": raw_id,
                    "title": title,
                    "schedule": schedule,
                    "last_run": str(last_run) if last_run else None,
                    "last_result": str(last_result) if last_result else None,
                    "next_run": None,
                    "enabled": enabled,
                    "source": source,
                    "kind": "job",
                    "origin": f"Sync-Automation ({json_file.stem})",
                })
        except Exception as exc:
            logger.warning("Error reading sync automation file %s: %s", json_file, exc)

    return items


def _extract_from_automation_master_package() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        import automation_master
        if hasattr(automation_master, "list_automations") and callable(automation_master.list_automations):
            raw_specs = automation_master.list_automations()
            for spec in raw_specs:
                if isinstance(spec, dict):
                    spec_id = str(spec.get("automation_id") or spec.get("id") or "")
                    name = str(spec.get("name") or spec_id)
                    enabled = bool(spec.get("enabled", True))
                    source = "automation-master"
                    items.append({
                        "id": f"{source}:{spec_id}",
                        "name": name,
                        "title": str(spec.get("title") or name),
                        "schedule": str(spec.get("schedule") or "manuell"),
                        "last_run": str(spec.get("last_run")) if spec.get("last_run") else None,
                        "last_result": str(spec.get("last_result")) if spec.get("last_result") else None,
                        "next_run": str(spec.get("next_run")) if spec.get("next_run") else None,
                        "enabled": enabled,
                        "source": source,
                        "kind": "routine",
                        "origin": "automation-master",
                    })
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("Error reading from automation_master package: %s", exc)

    return items


def _extract_from_module_manifests(repo_root: Path | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[3]

    candidates = [
        repo_root / ".AUTOMATION" / "automation-master" / "ellmos-module.v2.json",
        repo_root / ".MODULES" / ".CONTROL" / "automation-master" / "ellmos-module.v2.json",
    ]

    for cand in candidates:
        if cand.exists():
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                mod_id = manifest.get("id") or "automation-master"
                source = "automation-master"
                items.append({
                    "id": f"{source}:{mod_id}",
                    "name": str(mod_id),
                    "title": str(manifest.get("name") or manifest.get("title") or "Automation Master"),
                    "schedule": "bereit",
                    "last_run": None,
                    "last_result": "ready",
                    "next_run": None,
                    "enabled": True,
                    "source": source,
                    "kind": "routine",
                    "origin": "Modul-Manifest",
                })
                break
            except Exception as exc:
                logger.warning("Error reading manifest %s: %s", cand, exc)

    return items


def list_module_automations(
    db_path: str | Path | None = None,
    *,
    include_sync: bool | None = None,
    sync_dir: str | Path | None = None,
    include_manifests: bool = True,
    include_package: bool = True,
    default_source: str | None = None,
) -> list[dict[str, Any]]:
    """List available module automations from all configured sources."""
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    # Determine sync inclusion: if db_path was explicitly passed and sync_dir is not,
    # default include_sync to False to keep unit tests isolated.
    if include_sync is None:
        include_sync = False if (db_path is not None and sync_dir is None) else True

    # 1. Resolve DB path
    resolved_db = db_path
    if resolved_db is None:
        env_db = os.environ.get("BACH_DB")
        if env_db:
            resolved_db = env_db
        else:
            try:
                from hub.bach_paths import BACH_DB
                resolved_db = BACH_DB
            except Exception:
                resolved_db = None

    if resolved_db:
        conn = _connect_db(resolved_db)
        if conn:
            try:
                tables = _get_table_names(conn)
                if "automation_routines" in tables:
                    for item in _extract_from_automation_routines(conn):
                        if item["id"] not in seen_ids:
                            seen_ids.add(item["id"])
                            items.append(item)

                if "automation_triggers" in tables:
                    for item in _extract_from_automation_triggers(conn):
                        if item["id"] not in seen_ids:
                            seen_ids.add(item["id"])
                            items.append(item)

                if "scheduler_jobs" in tables:
                    for item in _extract_from_scheduler_jobs(conn):
                        if item["id"] not in seen_ids:
                            seen_ids.add(item["id"])
                            items.append(item)
            finally:
                conn.close()

    # 2. Extract from automation_master package if requested
    if include_package:
        for item in _extract_from_automation_master_package():
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                items.append(item)

    # 3. Extract from sync automations if requested
    if include_sync:
        resolved_sync_dir: Path | None = None
        if sync_dir:
            resolved_sync_dir = Path(sync_dir)
        else:
            env_sync = os.environ.get("SYNC_AUTOMATIONS_DIR")
            if env_sync and Path(env_sync).is_dir():
                resolved_sync_dir = Path(env_sync)
            else:
                default_sync = Path.home() / "OneDrive" / ".SYNC" / "_automations"
                if default_sync.is_dir():
                    resolved_sync_dir = default_sync

        if resolved_sync_dir and resolved_sync_dir.is_dir():
            for item in _extract_from_sync_dir(resolved_sync_dir):
                if item["id"] not in seen_ids:
                    seen_ids.add(item["id"])
                    items.append(item)

    # 4. Extract from module manifests if requested and no package items
    if include_manifests and not any(it["source"] == "automation-master" for it in items):
        for item in _extract_from_module_manifests():
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                items.append(item)

    # If default_source is specified, re-prefix ID and override source field
    if default_source:
        for it in items:
            raw_ident = it["id"].split(":", 1)[1] if ":" in it["id"] else it["id"]
            it["source"] = default_source
            it["id"] = f"{default_source}:{raw_ident}"

    items.sort(key=lambda x: (x.get("source", ""), x.get("name", "")))
    return items
