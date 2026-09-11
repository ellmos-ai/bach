# -*- coding: utf-8 -*-
"""Slot- and Worker-Configuration Manager for BACH OS.

Manages configuration and live metadata for:
1. Core Slots:
   - buddha_chat: Interactive Web & GUI Chat
   - buddha_always_on: Background task worker
   - buddha_connector: Messaging integrations (Telegram, WhatsApp, Signal)
2. Dynamic & Temporary Workers:
   - Specific tasks, custom system prompts, expiration dates/TTLs,
     custom models, turn limits, and execution modes.
3. Activity and execution history.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("bach.slots_config")

_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
DEFAULT_SLOTS_FILE = os.environ.get(
    "BACH_SLOTS_CONFIG_PATH",
    str(_DEFAULT_DATA_DIR / "slots_config.json")
)

_config_lock = threading.Lock()

DEFAULT_CORE_SLOTS: Dict[str, Dict[str, Any]] = {
    "buddha_chat": {
        "id": "buddha_chat",
        "name": "Buddha Chat",
        "description": "Interaktiver Chat (GUI & WebChat)",
        "backend": "ollama",
        "model": "qwen3.8:27b-mlx",
        "mode": "safe",
        "think": True,
        "max_tool_rounds": 12,
        "chat_id": "gui-web",
        "status": "ready",
        "current_activity": "",
    },
    "buddha_always_on": {
        "id": "buddha_always_on",
        "name": "Buddha Always-On",
        "description": "Hintergrundworker für offene Aufgaben im Leerlauf",
        "enabled": True,
        "backend": "ollama",
        "model": "qwen3.8:27b-mlx",
        "mode": "full",
        "think": True,
        "max_tool_rounds": 25,
        "category": "all",
        "chat_id": "idle-worker",
        "status": "idle",
        "current_activity": "",
    },
    "buddha_connector": {
        "id": "buddha_connector",
        "name": "Buddha Connector",
        "description": "Messaging-Konnektoren (Telegram, WhatsApp, Signal)",
        "backend": "ollama",
        "model": "qwen3.8:27b-mlx",
        "mode": "safe",
        "think": True,
        "max_tool_rounds": 10,
        "chat_id": "telegram",
        "status": "ready",
        "current_activity": "",
        "providers": {
            "telegram": {"backend": "ollama", "model": "qwen3.8:27b-mlx", "max_tool_rounds": 10},
            "whatsapp": {"backend": "ollama", "model": "qwen3.8:27b-mlx", "max_tool_rounds": 10},
            "signal": {"backend": "ollama", "model": "qwen3.8:27b-mlx", "max_tool_rounds": 10},
        },
    },
}


def _resolve_path(path: str | None = None) -> Path:
    target = path or DEFAULT_SLOTS_FILE
    return Path(os.path.expanduser(target)).resolve()


def load_slots_config(path: str | None = None) -> Dict[str, Any]:
    """Load the slots and dynamic workers configuration safely."""
    f = _resolve_path(path)
    with _config_lock:
        if not f.is_file():
            cfg = {
                "version": 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "slots": {k: dict(v) for k, v in DEFAULT_CORE_SLOTS.items()},
                "dynamic_workers": [],
                "activity_history": [],
            }
            try:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
            except OSError as e:
                log.warning("Could not create default slots_config at %s: %s", f, e)
            return cfg

        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            slots = data.get("slots", {})
            # Ensure all default core slots exist
            for k, default_val in DEFAULT_CORE_SLOTS.items():
                if k not in slots:
                    slots[k] = dict(default_val)
            data["slots"] = slots
            if "dynamic_workers" not in data or not isinstance(data["dynamic_workers"], list):
                data["dynamic_workers"] = []
            if "activity_history" not in data or not isinstance(data["activity_history"], list):
                data["activity_history"] = []
            return data
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Could not read slots config from %s: %s. Falling back to defaults.", f, e)
            return {
                "version": 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "slots": {k: dict(v) for k, v in DEFAULT_CORE_SLOTS.items()},
                "dynamic_workers": [],
                "activity_history": [],
            }


def save_slots_config(config: Dict[str, Any], path: str | None = None) -> None:
    """Save configuration atomically."""
    f = _resolve_path(path)
    config["updated_at"] = datetime.now(timezone.utc).isoformat()
    with _config_lock:
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(f)
        except OSError as e:
            log.error("Failed to write slots configuration to %s: %s", f, e)
            raise


def get_slot(slot_id: str, path: str | None = None) -> Dict[str, Any]:
    """Return configuration for a specific slot or worker."""
    cfg = load_slots_config(path)
    if slot_id in cfg.get("slots", {}):
        return cfg["slots"][slot_id]
    for w in cfg.get("dynamic_workers", []):
        if w.get("id") == slot_id:
            return w
    # Fallback to default if known
    if slot_id in DEFAULT_CORE_SLOTS:
        return dict(DEFAULT_CORE_SLOTS[slot_id])
    return {}


def update_slot(slot_id: str, updates: Dict[str, Any], path: str | None = None) -> Dict[str, Any]:
    """Update properties of a core slot or dynamic worker."""
    cfg = load_slots_config(path)
    slots = cfg.setdefault("slots", {})

    if slot_id in slots:
        slot = slots[slot_id]
        for k, v in updates.items():
            if k == "providers" and isinstance(v, dict):
                slot.setdefault("providers", {}).update(v)
            else:
                slot[k] = v
        save_slots_config(cfg, path)
        return slot

    # Check if it's a dynamic worker
    workers = cfg.setdefault("dynamic_workers", [])
    for w in workers:
        if w.get("id") == slot_id:
            w.update(updates)
            save_slots_config(cfg, path)
            return w

    raise KeyError(f"Slot or worker {slot_id!r} not found")


def list_workers(path: str | None = None, include_expired: bool = False) -> List[Dict[str, Any]]:
    """Return all dynamic workers, automatically updating expiration states."""
    cfg = load_slots_config(path)
    now_iso = datetime.now(timezone.utc).isoformat()
    workers = cfg.get("dynamic_workers", [])
    dirty = False

    result = []
    for w in workers:
        expires_at = w.get("expires_at")
        if expires_at and expires_at < now_iso and w.get("status") not in ("expired", "completed"):
            w["status"] = "expired"
            dirty = True
        if include_expired or w.get("status") != "expired":
            result.append(w)

    if dirty:
        save_slots_config(cfg, path)
    return result


def add_worker(worker_data: Dict[str, Any], path: str | None = None) -> Dict[str, Any]:
    """Create a new dynamic background worker."""
    cfg = load_slots_config(path)
    workers = cfg.setdefault("dynamic_workers", [])

    worker_id = worker_data.get("id") or f"worker-{uuid.uuid4().hex[:8]}"
    name = worker_data.get("name") or f"Worker {worker_id[-4:]}"
    role = worker_data.get("role", "general")
    backend = worker_data.get("backend", "ollama")
    model = worker_data.get("model", "qwen3.8:27b-mlx")
    mode = worker_data.get("mode", "full")
    think = bool(worker_data.get("think", True))
    max_tool_rounds = int(worker_data.get("max_tool_rounds", 20))
    system_prompt = worker_data.get("system_prompt", "")
    task_id = worker_data.get("task_id")
    category = worker_data.get("category", "")
    worker_type = worker_data.get("type", "once" if task_id else "persistent")

    expires_at = worker_data.get("expires_at")
    ttl_seconds = worker_data.get("ttl_seconds")
    if ttl_seconds and not expires_at:
        now_ts = time.time() + float(ttl_seconds)
        expires_at = datetime.fromtimestamp(now_ts, timezone.utc).isoformat()

    worker = {
        "id": worker_id,
        "name": name,
        "role": role,
        "backend": backend,
        "model": model,
        "mode": mode,
        "think": think,
        "max_tool_rounds": max_tool_rounds,
        "system_prompt": system_prompt,
        "task_id": task_id,
        "category": category,
        "type": worker_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expires_at,
        "status": "idle",
        "current_activity": "Bereit",
        "history": [],
    }

    workers.append(worker)
    save_slots_config(cfg, path)
    log.info("Created dynamic worker %s (%s, model=%s)", worker_id, name, model)
    return worker


def remove_worker(worker_id: str, path: str | None = None) -> bool:
    """Delete a dynamic worker by ID."""
    cfg = load_slots_config(path)
    workers = cfg.get("dynamic_workers", [])
    new_workers = [w for w in workers if w.get("id") != worker_id]
    if len(new_workers) == len(workers):
        return False
    cfg["dynamic_workers"] = new_workers
    save_slots_config(cfg, path)
    log.info("Removed dynamic worker %s", worker_id)
    return True


def record_activity(
    source: str,
    activity: str,
    status: str = "ok",
    details: Optional[Dict[str, Any]] = None,
    path: str | None = None
) -> None:
    """Record an action in the live activity history timeline."""
    cfg = load_slots_config(path)
    history = cfg.setdefault("activity_history", [])

    entry = {
        "id": f"act-{uuid.uuid4().hex[:6]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "activity": activity,
        "status": status,
        "details": details or {},
    }
    history.insert(0, entry)
    # Keep latest 100 entries
    if len(history) > 100:
        cfg["activity_history"] = history[:100]

    # Update slot current activity if matching
    if source in cfg.get("slots", {}):
        cfg["slots"][source]["current_activity"] = activity
    else:
        for w in cfg.get("dynamic_workers", []):
            if w.get("id") == source or w.get("name") == source:
                w["current_activity"] = activity
                w.setdefault("history", []).insert(0, entry)
                w["history"] = w["history"][:20]

    save_slots_config(cfg, path)


def get_activity_history(limit: int = 50, path: str | None = None) -> List[Dict[str, Any]]:
    """Return the recent activity history."""
    cfg = load_slots_config(path)
    return cfg.get("activity_history", [])[:limit]
