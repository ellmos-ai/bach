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

DEFAULT_SYSTEM_PROMPT = """Du bist Buddha, der integrierte KI-Assistent für BACH (Basic Automated Computer Hub).
Deine Aufgabe ist es, den Benutzer bei der Arbeit mit dem System, bei Programmierung, Recherche, Organisation und Systempflege zu unterstützen.

WICHTIGSTE REGELN:
- Antworte immer auf Deutsch, präzise und lösungsorientiert.
- Nutze Werkzeuge (Tools) aktiv und direkt, wenn Aufgaben erledigt werden sollen.
- Bei unklaren Aufgaben: Code-Präzedenzfälle suchen, minimal-invasive Lösungen wählen.
- 4-STUFEN-PRIORITÄT: 1. Direkt lösen, 2. Zerlegen (task_manage add), 3. Mehrdeutigkeit auflösen, 4. Delegieren.
- Behalte das Werkzeug-Rundenbudget im Auge.
"""

DEFAULT_ROLE_PROMPTS: Dict[str, str] = {
    "hintergrund_worker": (
        "Du agierst als autonomer Hintergrundworker für das BACH-System.\n"
        "Deine Hauptaufgabe ist es, zugewiesene oder offene Aufgaben fokussiert abzuarbeiten.\n"
        "Lies nur Dateien, die für die Aufgabe zwingend nötig sind. Führe Änderungen direkt auf der Platte aus,\n"
        "teste deine Änderungen sorgfältig und schließe die Arbeit mit einer präzisen Zusammenfassung und dem Wort FERTIG ab."
    ),
    "task_worker": (
        "Du agierst als spezialisierter Task-Worker für einen gezielten Nutzerauftrag.\n"
        "Konzentriere dich ausschließlich auf die übergebene Aufgabenstellung. Führe die notwendigen Schritte\n"
        "pragmatisch, qualitätsgesichert und ohne Abschweifen aus."
    ),
    "boss_routing": (
        "Du agierst als koordinierender Boss-Agent im BACH-System.\n"
        "Deine Kernkompetenz liegt in der Situationsanalyse, Problemlösung auf hoher Ebene und Arbeitsorganisation.\n"
        "Wenn eine Anforderung komplex oder vielschichtig ist, zerlege sie in logische Teilaufgaben (task_manage action='decompose')\n"
        "und weise sie den passenden Experten zu. Führe selbst keine riskanten Massenänderungen aus, sondern koordiniere,\n"
        "überwache den Fortschritt und stelle die Gesamterfüllung des Ziels sicher."
    ),
    "entwickler": (
        "Du agierst als Senior Software-Entwickler für BACH und angebundene Repositories.\n"
        "Schwerpunkte: Python, System-Architektur, Test Driven Development (pytest), saubere Git-Commits und Fail-Closed Lock-Disziplin."
    ),
    "bueroassistent": (
        "Du agierst als Büro- und Organisations-Experte im BACH-System.\n"
        "Schwerpunkte: Strukturierung von Aufgaben, Ablageordnung, Terminverwaltung, Korrespondenz und Dokumentation."
    ),
    "gesundheitsassistent": (
        "Du agierst als Gesundheits- und Dokumentations-Assistent.\n"
        "Schwerpunkte: Verwaltung medizinischer Dokumente, strukturierte Arztberichte, Laborwerte und Medikationspläne im Ordner user/gesundheit/."
    ),
    "steuer": (
        "Du agierst als Steuer- und Beleg-Experte für BACH.\n"
        "Schwerpunkte: Prüfung, Zuordnung und Aufbereitung von Belegen, Rechnungen und Werbungskosten im Ordner user/buero/steuer/."
    ),
    "foerderplaner": (
        "Du agierst als Förderplaner- und Pädagogik-Experte.\n"
        "Schwerpunkte: ICF-basierte Zielformulierung, Förderdiagnostik, Materialrecherche und Förderberichte gemäß Richtlinien."
    ),
    "recherche": (
        "Du agierst als wissenschaftlicher Recherche- und Analyse-Experte.\n"
        "Schwerpunkte: Fundierte Quellenauswertung, strukturierte Synthesen, Faktenprüfung und Ausarbeitung thematischer Dossiers."
    ),
    "psycho-berater": (
        "Du agierst als beratender Reflexions- und Psycho-Assistent.\n"
        "Schwerpunkte: Strukturierung therapeutischer Reflexionen, Vorbereitung von Beratungsgesprächen und Verhaltensdokumentation."
    ),
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


def get_prompt_templates(path: str | None = None) -> Dict[str, Any]:
    """Return active prompt templates, tracking custom modifications."""
    cfg = load_slots_config(path)
    custom_prompts = cfg.get("prompts", {})

    sys_default = custom_prompts.get("system_default", DEFAULT_SYSTEM_PROMPT)
    roles = {}
    for r_id, r_def in DEFAULT_ROLE_PROMPTS.items():
        custom_text = custom_prompts.get(f"role_{r_id}")
        roles[r_id] = {
            "id": r_id,
            "text": custom_text if custom_text is not None else r_def,
            "is_custom": custom_text is not None,
            "default": r_def,
        }

    return {
        "system_default": {
            "id": "system_default",
            "text": sys_default,
            "is_custom": "system_default" in custom_prompts,
            "default": DEFAULT_SYSTEM_PROMPT,
        },
        "roles": roles,
    }


def update_prompt_template(key: str, text: str, path: str | None = None) -> bool:
    """Save a customized prompt template."""
    cfg = load_slots_config(path)
    prompts = cfg.setdefault("prompts", {})
    prompts[key] = text
    save_slots_config(cfg, path)
    log.info("Updated prompt template for %r", key)
    return True


def reset_prompt_template(key: str | None = None, path: str | None = None) -> bool:
    """Reset a customized prompt template (or all) back to factory default."""
    cfg = load_slots_config(path)
    prompts = cfg.setdefault("prompts", {})
    if key:
        if key in prompts:
            del prompts[key]
            save_slots_config(cfg, path)
            log.info("Reset prompt template for %r", key)
            return True
        return False
    else:
        cfg["prompts"] = {}
        save_slots_config(cfg, path)
        log.info("Reset all prompt templates to factory defaults")
        return True


def compose_worker_prompt(worker_dict: Dict[str, Any], path: str | None = None) -> str:
    """Compose the final system prompt based on sub_mode, role, and checkboxes."""
    templates = get_prompt_templates(path)
    sys_default_text = templates["system_default"]["text"]
    role_templates = templates["roles"]

    include_sys = worker_dict.get("include_system_prompt", True)
    sub_mode = worker_dict.get("sub_mode", "task_worker")
    role_id = worker_dict.get("role_id", "")
    multi_role = bool(worker_dict.get("multi_role", False))
    max_experts = int(worker_dict.get("max_experts", 3))
    expert_models = worker_dict.get("expert_models", {})
    task_prompt = (worker_dict.get("task_prompt") or worker_dict.get("prompt") or "").strip()
    custom_sys = (worker_dict.get("custom_system_prompt") or "").strip()

    if custom_sys and not include_sys and not role_id and sub_mode not in ("hintergrund_worker", "boss_routing"):
        return custom_sys

    parts = []

    # 1. System Default Prompt (if checkbox checked)
    if include_sys:
        parts.append(sys_default_text.strip())

    # 2. Role Instruction
    if sub_mode == "hintergrund_worker":
        hw = role_templates.get("hintergrund_worker", {}).get("text", DEFAULT_ROLE_PROMPTS["hintergrund_worker"])
        parts.append(f"--- ROLLE: HINTERGRUNDWORKER ---\n{hw}")

    elif sub_mode == "boss_routing":
        boss = role_templates.get("boss_routing", {}).get("text", DEFAULT_ROLE_PROMPTS["boss_routing"])
        cfg_str = f"Max. Unter-Experten: {max_experts}"
        if expert_models:
            cfg_str += f"\nModellallokation je Experte: {json.dumps(expert_models, ensure_ascii=False)}"
        parts.append(f"--- ROLLE: BOSSAGENT & KOORDINATOR ---\n{boss}\n\n[Experten-Konfiguration]\n{cfg_str}")

    elif sub_mode == "expert_role":
        if multi_role:
            parts.append(
                "--- ROLLE: MULTI-ROLE EXPERTEN-POOL ---\n"
                "Du kannst und sollst alle Expertenrollen flexibel ausfüllen. Prüfe anstehende Aufgaben und wechsle\n"
                "nach jedem Lauf dynamisch in die passende Fachrolle (z. B. Entwickler, Büro, Gesundheit, Steuer, Förderplaner)."
            )
        elif role_id and role_id in role_templates:
            r_text = role_templates[role_id]["text"]
            parts.append(f"--- ROLLE: EXPERTE ({role_id.upper()}) ---\n{r_text}")
        elif role_id:
            parts.append(f"--- ROLLE: EXPERTE ({role_id}) ---")

    elif sub_mode == "task_worker":
        tw = role_templates.get("task_worker", {}).get("text", DEFAULT_ROLE_PROMPTS["task_worker"])
        parts.append(f"--- ROLLE: TASK-WORKER ---\n{tw}")

    # 3. Custom addition or override
    if custom_sys and custom_sys not in parts:
        parts.append(f"--- ZUSATZ-INSTRUKTION ---\n{custom_sys}")

    # 4. User Task Prompt
    if task_prompt:
        parts.append(f"--- AUFTRAG / AUFGABE ---\n{task_prompt}")

    return "\n\n".join(parts)


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
    task_id = worker_data.get("task_id")
    category = worker_data.get("category", "")
    worker_type = worker_data.get("type", "once" if task_id else "persistent")

    # Mode and prompt composition
    sub_mode = worker_data.get("sub_mode", "task_worker")
    include_system_prompt = bool(worker_data.get("include_system_prompt", True))
    role_id = worker_data.get("role_id", "")
    multi_role = bool(worker_data.get("multi_role", False))
    max_experts = int(worker_data.get("max_experts", 3))
    expert_models = worker_data.get("expert_models", {})
    task_prompt = (worker_data.get("task_prompt") or worker_data.get("prompt") or "").strip()
    custom_system_prompt = worker_data.get("custom_system_prompt") or worker_data.get("system_prompt", "")

    composed_prompt = compose_worker_prompt({
        "sub_mode": sub_mode,
        "include_system_prompt": include_system_prompt,
        "role_id": role_id,
        "multi_role": multi_role,
        "max_experts": max_experts,
        "expert_models": expert_models,
        "task_prompt": task_prompt,
        "custom_system_prompt": custom_system_prompt,
    }, path)

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
        "system_prompt": composed_prompt,
        "custom_system_prompt": custom_system_prompt,
        "task_prompt": task_prompt,
        "sub_mode": sub_mode,
        "include_system_prompt": include_system_prompt,
        "role_id": role_id,
        "multi_role": multi_role,
        "max_experts": max_experts,
        "expert_models": expert_models,
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
    log.info("Created dynamic worker %s (%s, sub_mode=%s, model=%s)", worker_id, name, sub_mode, model)
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
