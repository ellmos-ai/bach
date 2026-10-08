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

import hashlib
import base64
import inspect
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any

from hub._services.user_config_store import _exclusive_lock

log = logging.getLogger("bach.slots_config")

_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
DEFAULT_SLOTS_FILE = os.environ.get(
    "BACH_SLOTS_CONFIG_PATH",
    str(_DEFAULT_DATA_DIR / "slots_config.json")
)

_config_lock = threading.RLock()

DEFAULT_CORE_SLOTS: dict[str, dict[str, Any]] = {
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
        "pause_after": 5,
        "pause_minutes": 1,
        "pause_basis": "runs",
        "pause_counter": 0,
        "pause_started_at": "",
    },
    "buddha_always_on": {
        "id": "buddha_always_on",
        "name": "Buddha Always-On",
        "description": "Hintergrundworker für offene Aufgaben; lokale Inferenz teilt die Fackel mit dem Vordergrund",
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
        "pause_after": 5,
        "pause_minutes": 1,
        "pause_basis": "runs",
        "pause_counter": 0,
        "pause_started_at": "",
        "pickup_filter": {
            "enabled": True,
            "categories": ["INBOX"],
            "priorities": ["P1", "P2"],
            "tags": [],
            "exclude_tags": ["delegated", "waiting"],
        },
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
        "pause_after": 5,
        "pause_minutes": 1,
        "pause_basis": "runs",
        "pause_counter": 0,
        "pause_started_at": "",
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
- Codeänderungen nur über start_task_worktree → finish_task. Der Live-Ordner ist gesperrt.
- Nichts Unfertiges committen: Bricht ein Worker ab, sichert er seinen Stand als Commit mit „WIP“ im Titel und pusht ihn, ohne PR.
- Keine Geheimnisse: Vor jedem Commit laufen Prüfung auf Zugangsdaten (Secrets-Scan) und git diff --check.
"""

DEFAULT_ROLE_PROMPTS: dict[str, str] = {
    "personal-assistant": (
        "Du bist der persönliche Assistent. Unterstütze den Nutzer bei Planung, Recherche und Umsetzung. "
        "Erstelle bei Bedarf eigene Agentenvorlagen, Skills und klar abgegrenzte Aufgaben. "
        "Neue Agenten werden zunächst als Living konfiguriert; Cloud-Ausführung benötigt einen ausdrücklichen Nutzerstart."
    ),
    "connector": (
        "Du bist der Kommunikationsassistent. Bearbeite den aktuellen Dialog und koordiniere die angebundenen Kanäle. "
        "Versende Nachrichten an Dritte nur mit ausdrücklicher Nutzerautorisierung."
    ),
    "hintergrund_worker": (
        "Du agierst als autonomer Hintergrundworker für das BACH-System.\n"
        "Deine Hauptaufgabe ist es, zugewiesene oder offene Aufgaben fokussiert abzuarbeiten.\n"
        "Arbeite nach dem 4-Stufen-Protokoll: 1. Direkt lösen bei klaren, überschaubaren Aufgaben.\n"
        "2. Wenn eine Anforderung komplex oder vielschichtig ist: Zerlege sie eigenständig in 3-5 handhabbare Teilaufgaben\n"
        "(nutze `task_manage(action='decompose', subtasks=[...], sequential=True)` oder lege konkrete Sub-Tasks an).\n"
        "3. Bei Mehrdeutigkeit präzise Auswahlfrage als TO-DECIDE Task einstellen. 4. Bei Modellgrenzen an Claude/Codex übergeben.\n"
        "Lies nur Dateien, die zwingend nötig sind, führe Änderungen präzise aus, teste sorgfältig und schließe mit FERTIG ab."
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
    "task-divider": (
        "Du agierst als Task-Divider und Dekompositions-Experte im BACH-System.\n"
        "Deine Kernaufgabe ist die methodische Analyse komplexer, umfangreicher Großaufgaben im Backlog.\n"
        "Sobald eine Aufgabe mehr als 2-3 Teilschritte oder Fachbereiche betrifft: Zerlege sie vorab in handhabbare,\n"
        "atomare Teilpakete (nutze `task_manage(action='decompose', subtasks=[...], sequential=True)` oder erstelle Teil-Tasks).\n"
        "Formuliere präzise Akzeptanzkriterien für jeden Teilschritt und weise sie passenden Rollen zu."
    ),
    "ticket-master": (
        "Du agierst als Ticket-Master und Triage-Experte für offene Aufgaben im BACH-System.\n"
        "Deine Aufgabe ist es, heimatlose, unzugewiesene oder unsortierte Tickets zu sichten, Prioritäten zu bewerten,\n"
        "Kategorien zu schärfen und die Aufgaben der jeweils passenden Persona/Fachrolle zuzuweisen (task_manage action='assign')."
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
    "haushaltsmanagement": (
        "Du bist der Haushalts- und Alltagsmanager im BACH-System.\n"
        "Schwerpunkte: Einkaufslisten, Haushaltsroutinen, Vorratsmanagement, Inventar und alltägliche Haushaltslogistik."
    ),
    "aboservice": (
        "Du bist der Vertrags- und Abo-Manager im BACH-System.\n"
        "Schwerpunkte: Prüfung von Vertragslaufzeiten, Kündigungsfristen, Optimierungspotenzialen und monatlichen Fixkosten."
    ),
    "data-analysis": (
        "Du bist der Datenanalyse- und Reporting-Experte im BACH-System.\n"
        "Schwerpunkte: Strukturierte Auswertung von Kennzahlen, Logs, CSV-Dateien und Zeitreihen sowie visuelle Zusammenfassungen."
    ),
    "decision-briefing": (
        "Du bist der Entscheidungs- und Strategieberater im BACH-System.\n"
        "Schwerpunkte: Ausgewogene Pro-Contra-Analysen, Risikobewertungen, Szenarienvergleiche und fundierte Entscheidungsvorlagen."
    ),
}

# Roles are configuration, not evidence of a running process.
for _core_id, _core_defaults in DEFAULT_CORE_SLOTS.items():
    _core_defaults.setdefault("enabled", True)
    _core_defaults.setdefault("include_system_prompt", True)
    _core_defaults.setdefault("custom_system_prompt", "")
    _core_defaults.setdefault("custom_role_prompt", "")
    _core_defaults.setdefault("allow_tools", True)
    _core_defaults.setdefault("avatar", "")
    _core_defaults.setdefault("role_id", {
        "buddha_chat": "personal-assistant", "buddha_connector": "connector",
        "buddha_always_on": "hintergrund_worker",
    }[_core_id])
    _core_defaults.setdefault("sub_mode", "task_worker" if _core_id == "buddha_always_on" else "expert_role")

SYSTEM_SLOT_PRESETS = {
    "boss": {"name": "Boss · Koordination", "role_id": "boss_routing", "sub_mode": "boss_routing", "icon": "🧭"},
    "developer": {"name": "Experte · Entwicklung", "role_id": "entwickler", "icon": "🛠️"},
    "research": {"name": "Experte · Recherche", "role_id": "recherche", "icon": "🔎"},
    "assistant": {"name": "Persönlicher Assistent", "role_id": "personal-assistant", "icon": "💬"},
}


def validate_agent_avatar(value: Any) -> str:
    if value == "":
        return ""
    if not isinstance(value, str) or len(value) > 240_000:
        raise ValueError("Agentenbild ist zu groß")
    match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)", value)
    if not match:
        raise ValueError("Agentenbild muss PNG, JPEG oder WebP sein")
    try:
        raw = base64.b64decode(match[2], validate=True)
    except ValueError as exc:
        raise ValueError("Agentenbild ist ungültig") from exc
    valid = {"png": raw.startswith(b"\x89PNG\r\n\x1a\n"),
             "jpeg": raw.startswith(b"\xff\xd8\xff"),
             "webp": raw.startswith(b"RIFF") and raw[8:12] == b"WEBP"}
    if len(raw) > 180_000 or not valid[match[1]]:
        raise ValueError("Agentenbild hat kein gültiges Bildformat")
    return value


def get_system_slot(slot_id: str, path: str | None = None) -> dict[str, Any]:
    config = load_slots_config(path, strict=True)
    slot = config["slots"].get(slot_id)
    if not isinstance(slot, dict) or slot.get("id") != slot_id:
        return {}
    if slot_id not in DEFAULT_CORE_SLOTS and slot.get("system") is not True:
        return {}
    return {**DEFAULT_CORE_SLOTS.get(slot_id, {}), **slot}


def system_slot_chat_id(chat_id: str) -> str | None:
    match = re.fullmatch(r"(?:agent:[1-9][0-9]*:)?slot:([A-Za-z0-9_-]{1,80}):[a-f0-9]{32}", str(chat_id))
    return match[1] if match else None


def _resolve_path(path: str | None = None) -> Path:
    target = path or DEFAULT_SLOTS_FILE
    return Path(os.path.expanduser(target)).resolve()


def _fresh_slots_config() -> dict[str, Any]:
    return {
        "version": 3,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "slots": {k: dict(v) for k, v in DEFAULT_CORE_SLOTS.items()},
        "dynamic_workers": [],
        "activity_history": [],
    }


def initialize_slots_config(path: str | None = None) -> dict[str, Any]:
    """Explicit bootstrap; never overwrite a config another writer created."""
    f = _resolve_path(path)
    with _exclusive_lock(f), _config_lock:
        if f.is_file():
            return load_slots_config(path, strict=True)
        cfg = _fresh_slots_config()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f"{f.name}.init-{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(f)
        finally:
            tmp.unlink(missing_ok=True)
        return cfg


def _serialized_mutation(func):
    """Hold one OS lock across the complete read-modify-write cycle."""
    signature = inspect.signature(func)

    @wraps(func)
    def guarded(*args, **kwargs):
        bound = signature.bind_partial(*args, **kwargs)
        target = _resolve_path(bound.arguments.get("path"))
        with _exclusive_lock(target), _config_lock:
            return func(*args, **kwargs)

    return guarded


def load_slots_config(path: str | None = None, *, strict: bool = False) -> dict[str, Any]:
    """Load the slots and dynamic workers configuration safely."""
    f = _resolve_path(path)
    if not f.is_file():
        if strict:
            raise ValueError(f"Slots-Konfiguration fehlt: {f}")
        log.warning("Slots-Konfiguration fehlt: %s. Defaults nur im Speicher.", f)
        return _fresh_slots_config()
    with _config_lock:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Slots-Konfiguration muss ein JSON-Objekt enthalten")
            slots = data.get("slots", {})
            if strict and not isinstance(slots, dict):
                raise ValueError("Slots-Konfiguration enthält keine gültigen Core-Slots")
            # Ensure all default core slots exist
            for k, default_val in DEFAULT_CORE_SLOTS.items():
                if k not in slots:
                    slots[k] = dict(default_val)
                else:
                    for field in ("pause_after", "pause_minutes", "pause_basis",
                                  "pause_counter", "pause_started_at"):
                        slots[k].setdefault(field, default_val[field])
            if data.get("version", 1) < 2:
                data["version"] = 2
            # Migrate version 2 -> 3: add pickup_filter to buddha_always_on
            if data.get("version", 1) < 3:
                always_on = slots.get("buddha_always_on")
                if always_on is not None and "pickup_filter" not in always_on:
                    always_on["pickup_filter"] = dict(
                        DEFAULT_CORE_SLOTS["buddha_always_on"]["pickup_filter"]
                    )
                data["version"] = 3
            data["slots"] = slots
            if strict and not isinstance(data.get("dynamic_workers"), list):
                raise ValueError("Slots-Konfiguration enthält keine gültige Worker-Liste")
            if "dynamic_workers" not in data or not isinstance(data["dynamic_workers"], list):
                data["dynamic_workers"] = []
            if "activity_history" not in data or not isinstance(data["activity_history"], list):
                data["activity_history"] = []
            return data
        except (json.JSONDecodeError, OSError, ValueError, TypeError) as e:
            if strict:
                raise ValueError(f"Slots-Konfiguration ist nicht lesbar: {e}") from e
            log.warning("Could not read slots config from %s: %s. Falling back to defaults.", f, e)
            return _fresh_slots_config()


def save_slots_config(config: dict[str, Any], path: str | None = None) -> None:
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


def is_slot_paused(slot: dict[str, Any]) -> bool:
    """Return whether the slot's pause window has not yet elapsed."""
    started_at = slot.get("pause_started_at")
    minutes = slot.get("pause_minutes", 0) or 0
    if not started_at or not minutes:
        return False
    try:
        started = datetime.fromisoformat(started_at)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - started).total_seconds() < float(minutes) * 60
    except (TypeError, ValueError):
        return False


def task_matches_slot_binding(task: dict[str, Any], slot: dict[str, Any] | None) -> bool:
    """Enforce task model and slot binding even when pickup filtering is off."""
    slot = slot or {}
    if slot.get("require_assigned_slot") is True and task.get("assigned_slot") != slot.get("id"):
        return False
    for task_key, slot_key in (("required_model", "model"), ("assigned_slot", "id")):
        required = str(task.get(task_key) or "").strip().casefold()
        if required and required != str(slot.get(slot_key) or "").strip().casefold():
            return False
    return True


def match_task_to_pickup_filter(task: dict[str, Any], slot: dict[str, Any]) -> bool:
    """Return True if *task* satisfies the slot's pickup_filter rules.

    A missing or disabled filter rejects every task when checking against a
    slot's pickup_filter, so callers like chat_tray can fall back to standard
    assignee matching.
    """
    if not isinstance(slot, dict):
        return False
    if not task_matches_slot_binding(task, slot):
        return False
    pickup_filter = slot if "enabled" in slot else slot.get("pickup_filter")
    if not isinstance(pickup_filter, dict):
        return False
    if not pickup_filter.get("enabled", False):
        return False

    task_categories = []
    if task.get("category"):
        task_categories.append(task["category"])
    if task.get("project") and task["project"] != task.get("category"):
        task_categories.append(task["project"])
    raw_cats = task.get("categories")
    if raw_cats:
        if isinstance(raw_cats, str):
            task_categories.extend([c.strip() for c in raw_cats.split(",") if c.strip()])
        elif isinstance(raw_cats, (list, tuple, set)):
            task_categories.extend(raw_cats)

    filter_categories = pickup_filter.get("categories", []) or []
    if filter_categories:
        filter_cats_norm = {str(c).strip().lower() for c in filter_categories if str(c).strip()}
        if not any(str(c).strip().lower() in filter_cats_norm for c in task_categories):
            return False

    task_priority = str(task.get("priority") or "").strip().upper()
    filter_priorities = pickup_filter.get("priorities", []) or []
    if filter_priorities:
        filter_prios_norm = {str(p).strip().upper() for p in filter_priorities if str(p).strip()}
        if task_priority not in filter_prios_norm:
            return False

    raw_tags = task.get("tags") or []
    if isinstance(raw_tags, str):
        task_tags = [t.strip().lower() for t in raw_tags.split(",") if t.strip()]
    elif isinstance(raw_tags, (list, tuple, set)):
        task_tags = [str(t).strip().lower() for t in raw_tags if str(t).strip()]
    else:
        task_tags = []

    filter_tags = pickup_filter.get("tags", []) or []
    if filter_tags:
        filter_tags_norm = {str(t).strip().lower() for t in filter_tags if str(t).strip()}
        if not any(t in filter_tags_norm for t in task_tags):
            return False

    exclude_tags = pickup_filter.get("exclude_tags", []) or []
    if exclude_tags:
        exclude_tags_norm = {str(t).strip().lower() for t in exclude_tags if str(t).strip()}
        if any(t in exclude_tags_norm for t in task_tags):
            return False

    return True


matches_pickup_filter = match_task_to_pickup_filter


def get_slot_pause_info(slot: dict[str, Any]) -> dict[str, Any]:
    """Return structured pause status and remaining duration for a slot or worker."""
    if not isinstance(slot, dict):
        return {
            "is_paused": False,
            "pause_after": 0,
            "pause_minutes": 0,
            "pause_basis": "runs",
            "pause_counter": 0,
            "pause_started_at": "",
            "remaining_seconds": 0.0,
            "remaining_minutes": 0.0,
        }
    is_paused = is_slot_paused(slot)
    pause_after = int(slot.get("pause_after", 0) or 0)
    pause_minutes = float(slot.get("pause_minutes", 0) or 0)
    pause_basis = str(slot.get("pause_basis") or "runs")
    pause_counter = int(slot.get("pause_counter", 0) or 0)
    started_at = slot.get("pause_started_at", "")
    remaining_seconds = 0.0
    if is_paused and started_at and pause_minutes > 0:
        try:
            started = datetime.fromisoformat(started_at)
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            remaining_seconds = max(0.0, (pause_minutes * 60.0) - elapsed)
        except (ValueError, TypeError):
            remaining_seconds = 0.0
    return {
        "is_paused": is_paused,
        "pause_after": pause_after,
        "pause_minutes": pause_minutes,
        "pause_basis": pause_basis,
        "pause_counter": pause_counter,
        "pause_started_at": started_at,
        "remaining_seconds": round(remaining_seconds, 1),
        "remaining_minutes": round(remaining_seconds / 60.0, 1),
    }


def bump_pause_counter(
    slot: dict[str, Any] | str,
    event_type: str = "runs",
    path: str | None = None,
) -> bool:
    """Count a run or completed task; persist updates when given a slot ID."""
    if isinstance(slot, str):
        slot_id = slot
        current = get_slot(slot_id, path=path)
        if not current:
            return False
        started = bump_pause_counter(current, event_type=event_type)
        update_slot(slot_id, {
            "pause_counter": current["pause_counter"],
            "pause_started_at": current.get("pause_started_at", ""),
        }, path=path)
        return started

    if is_slot_paused(slot):
        return False
    basis = str(slot.get("pause_basis") or "runs").lower()
    if basis == "tasks" and event_type != "tasks":
        return False
    if basis == "runs" and event_type != "runs":
        return False
    threshold = int(slot.get("pause_after", 0) or 0)
    minutes = float(slot.get("pause_minutes", 0) or 0)
    if threshold <= 0 or minutes <= 0:
        return False
    slot["pause_counter"] = int(slot.get("pause_counter", 0) or 0) + 1
    if slot["pause_counter"] < threshold:
        return False
    slot["pause_started_at"] = datetime.now(timezone.utc).isoformat()
    slot["pause_counter"] = 0
    return True


def get_slot(slot_id: str, path: str | None = None) -> dict[str, Any]:
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


def get_worker_slot(worker_id: str, path: str | None = None) -> dict[str, Any]:
    """Return only a unique dynamic worker; ambiguity fails closed."""
    cfg = load_slots_config(path, strict=True)
    matches = [w for w in cfg.get("dynamic_workers", []) if w.get("id") == worker_id]
    if len(matches) > 1 or (matches and (
        worker_id in cfg.get("slots", {}) or worker_id in DEFAULT_CORE_SLOTS
    )):
        raise ValueError(f"Worker-ID {worker_id!r} ist nicht eindeutig")
    return matches[0] if matches else {}


def get_always_on_execution_slot(path: str | None = None) -> dict[str, Any]:
    """Read the persisted core worker once, without defaults or dynamic aliases."""
    with _config_lock:
        config = json.loads(_resolve_path(path).read_text(encoding="utf-8"))
    if (not isinstance(config, dict) or not isinstance(config.get("slots"), dict)
            or not isinstance(config.get("dynamic_workers"), list)):
        raise ValueError("Always-On-Konfiguration ist nicht verifizierbar")
    slot = config["slots"].get("buddha_always_on")
    if (not isinstance(slot, dict) or slot.get("id") != "buddha_always_on"
            or type(slot.get("enabled")) is not bool
            or any(not isinstance(worker, dict) for worker in config["dynamic_workers"])
            or any(worker.get("id") == "buddha_always_on" for worker in config["dynamic_workers"])):
        raise ValueError("Always-On-Slot fehlt oder ist nicht eindeutig")
    return {**slot, "type": "continuous", "sub_mode": slot.get("sub_mode") or "task_worker"}


@_serialized_mutation
def update_slot(slot_id: str, updates: dict[str, Any], path: str | None = None) -> dict[str, Any]:
    """Update properties of a core slot or dynamic worker."""
    if "id" in updates and updates["id"] != slot_id:
        raise ValueError("Slot-/Worker-ID darf nicht geändert werden")
    if "allow_tools" in updates and not isinstance(updates["allow_tools"], bool):
        raise ValueError("allow_tools muss ein JSON-Boolean sein")
    cfg = load_slots_config(path, strict=True)
    slots = cfg.setdefault("slots", {})
    workers = cfg.setdefault("dynamic_workers", [])
    matches = [w for w in workers if w.get("id") == slot_id]
    if len(matches) > 1 or (matches and slot_id in slots):
        raise ValueError(f"Worker-ID {slot_id!r} ist nicht eindeutig")

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
    if matches:
        worker = matches[0]
        worker.update(updates)
        save_slots_config(cfg, path)
        return worker

    raise KeyError(f"Slot or worker {slot_id!r} not found")


CORE_SYSTEM_AGENT_IDS = tuple(DEFAULT_CORE_SLOTS)
CORE_SYSTEM_AGENT_ICONS = {
    "buddha_chat": "💬",
    "buddha_always_on": "⚡",
    "buddha_connector": "📱",
}
CORE_EDITABLE_FIELDS = frozenset({
    "name", "icon", "backend", "model", "mode", "think",
    "max_tool_rounds", "pause_after", "pause_minutes", "pause_basis",
    "enabled", "description", "include_system_prompt", "custom_system_prompt",
    "custom_role_prompt", "role_id", "sub_mode", "avatar", "allow_tools", "allowed_tools",
})
CORE_KNOWN_BACKENDS = frozenset({
    "ollama", "ollama-cloud", "lmstudio", "hermes", "openrouter",
    "claude", "claude-api", "codex", "openai",
})


def _core_snapshot_from_bytes(raw: bytes) -> dict[str, Any]:
    config = json.loads(raw.decode("utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("slots"), dict):
        raise ValueError("System-Agentenkonfiguration hat kein gültiges Slots-Schema")
    slots = config["slots"]
    if any(not isinstance(slots.get(slot_id), dict) for slot_id in CORE_SYSTEM_AGENT_IDS):
        raise ValueError("Mindestens eine feste System-Agenten-ID fehlt")
    version = hashlib.sha256(raw).hexdigest()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict) or any(not isinstance(value, str) for value in prompts.values()):
        raise ValueError("Promptkonfiguration ist ungültig")
    public_slots = []
    system_ids = list(CORE_SYSTEM_AGENT_IDS) + [
        key for key, value in slots.items()
        if key not in CORE_SYSTEM_AGENT_IDS and isinstance(value, dict) and value.get("system") is True
    ]
    for slot_id in system_ids:
        slot = slots[slot_id]
        if slot.get("id") != slot_id:
            raise ValueError("System-Steckplatz-ID stimmt nicht überein")
        defaults = DEFAULT_CORE_SLOTS.get(slot_id, DEFAULT_CORE_SLOTS["buddha_chat"])
        pause_info = get_slot_pause_info(slot)
        public_slots.append({
            "id": slot_id,
            "system": True,
            "deletable": slot_id not in CORE_SYSTEM_AGENT_IDS,
            "name": slot.get("name", defaults["name"]),
            "icon": slot.get("icon", CORE_SYSTEM_AGENT_ICONS.get(slot_id, "🤖")),
            "avatar": slot.get("avatar", ""),
            "description": slot.get("description", defaults["description"]),
            "execution_kind": ("worker" if slot_id == "buddha_always_on" else
                               "connector" if slot_id == "buddha_connector" else
                               slot.get("execution_kind", "chat")),
            "include_system_prompt": slot.get("include_system_prompt", True),
            "custom_system_prompt": slot.get("custom_system_prompt", ""),
            "custom_role_prompt": slot.get("custom_role_prompt", ""),
            "role_id": slot.get("role_id", defaults["role_id"]),
            "sub_mode": slot.get("sub_mode", defaults["sub_mode"]),
            "allow_tools": slot.get("allow_tools", True),
            "allowed_tools": slot.get("allowed_tools"),
            "blueprint_id": slot.get("blueprint_id"),
            "blueprint_version": slot.get("blueprint_version"),
            "type": slot.get("type", "continuous"),
            "backend": slot.get("backend"),
            "model": slot.get("model"),
            "resolved_model": slot.get("resolved_model") or "",
            "mode": slot.get("mode"),
            "think": slot.get("think"),
            "max_tool_rounds": slot.get("max_tool_rounds"),
            "pause_after": slot.get("pause_after"),
            "pause_minutes": slot.get("pause_minutes"),
            "pause_basis": slot.get("pause_basis", defaults.get("pause_basis", "runs")),
            "configured_enabled": slot.get("enabled"),
            "enabled": bool(slot.get("enabled", defaults.get("enabled", True))),
            "status": slot.get("status", defaults.get("status", "idle")),
            "current_activity": slot.get("current_activity", ""),
            "pause_info": pause_info,
            "living": None,
            "running": None,
            "runtime_reason_code": "runtime_not_probed",
        })
    return {
        "schema": "bach.core-system-agents.v1",
        "configuration_version": version,
        "updated_at": config.get("updated_at"),
        "agents": public_slots,
        "supported_backend_ids": sorted(CORE_KNOWN_BACKENDS),
        "role_ids": list(DEFAULT_ROLE_PROMPTS),
        "slot_presets": SYSTEM_SLOT_PRESETS,
        "prompt_templates": {
            "system_default": prompts.get("system_default", DEFAULT_SYSTEM_PROMPT),
            "roles": {role: prompts.get("role_" + role, text)
                      for role, text in DEFAULT_ROLE_PROMPTS.items()},
        },
    }


def core_system_agents_snapshot(path: str | None = None) -> dict[str, Any]:
    """Read only the allowlisted fields of the existing Control slots file."""
    target = _resolve_path(path)
    return _core_snapshot_from_bytes(target.read_bytes())


def _validated_core_edits(changes: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(changes, dict) or not changes or set(changes) - CORE_EDITABLE_FIELDS:
        raise ValueError("Nur dokumentierte System-Agentenfelder dürfen geändert werden")
    result: dict[str, Any] = {}
    for field, value in changes.items():
        if field == "allowed_tools":
            from .bach_tools import TOOLS_FULL
            known = {tool["function"]["name"] for tool in TOOLS_FULL}
            if (value is not None and (not isinstance(value, list) or len(value) > 100
                    or any(not isinstance(name, str) or name not in known for name in value)
                    or len(set(value)) != len(value))):
                raise ValueError("Toolfreigabe enthält unbekannte oder doppelte Werkzeuge")
        elif field == "avatar":
            value = validate_agent_avatar(value)
        elif field in {"description", "custom_system_prompt", "custom_role_prompt"}:
            if not isinstance(value, str) or len(value) > 20000 or "\x00" in value:
                raise ValueError(f"{field} enthält ungültigen Text")
        elif field == "role_id":
            if value not in DEFAULT_ROLE_PROMPTS:
                raise ValueError("Unbekannte Rollen-ID")
        elif field == "sub_mode":
            if value not in {"expert_role", "boss_routing", "task_worker", "hintergrund_worker"}:
                raise ValueError("Unbekannter Rollenmodus")
        elif field in {"name", "icon", "backend", "model", "mode"}:
            limit = 8 if field == "icon" else 120
            if (not isinstance(value, str) or not value.strip()
                    or len(value) > limit or any(ord(c) < 32 for c in value)):
                raise ValueError(f"{field} muss ein kurzer, lesbarer Text sein")
            value = value.strip()
            if field == "backend" and value not in CORE_KNOWN_BACKENDS:
                raise ValueError("Backend-ID ist im vorhandenen Control-Katalog nicht bekannt")
            if field == "mode" and value not in {"safe", "full"}:
                raise ValueError("Modus muss safe oder full sein")
        elif field in {"think", "enabled", "include_system_prompt", "allow_tools"}:
            if not isinstance(value, bool):
                raise ValueError(f"{field} muss wahr oder falsch sein")
        elif field == "pause_basis":
            if value not in {"runs", "tasks"}:
                raise ValueError("pause_basis muss runs oder tasks sein")
        else:
            upper = 100 if field == "max_tool_rounds" else 1440
            lower = 0
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f"{field} liegt außerhalb des erlaubten Bereichs")
        result[field] = value
    return result


@_serialized_mutation
def change_core_system_agent(
    slot_id: str, expected_version: str, changes: dict[str, Any] | None = None,
    *, reset: bool = False, path: str | None = None,
) -> dict[str, Any]:
    """Atomically update existing Core config only; never start a worker."""
    if not get_system_slot(slot_id, path):
        raise KeyError("Unbekannte System-Agenten-ID")
    target = _resolve_path(path)
    raw = target.read_bytes()
    snapshot = _core_snapshot_from_bytes(raw)
    if expected_version != snapshot["configuration_version"]:
        raise RuntimeError("configuration_version_conflict")
    config = json.loads(raw.decode("utf-8"))
    slot = config["slots"][slot_id]
    if reset:
        if changes:
            raise ValueError("Reset akzeptiert keine gleichzeitigen Änderungen")
        defaults = DEFAULT_CORE_SLOTS.get(slot_id, DEFAULT_CORE_SLOTS["buddha_chat"])
        updates = {field: defaults[field] for field in CORE_EDITABLE_FIELDS if field in defaults}
        updates["icon"] = CORE_SYSTEM_AGENT_ICONS.get(slot_id, "🤖")
    else:
        updates = _validated_core_edits(changes)
    slot.update(updates)
    save_slots_config(config, path)
    return core_system_agents_snapshot(path)


@_serialized_mutation
def create_system_slot(changes: dict[str, Any], expected_version: str, *,
                       preset: str = "assistant", path: str | None = None) -> dict[str, Any]:
    target = _resolve_path(path)
    raw = target.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_version:
        raise RuntimeError("configuration_version_conflict")
    if preset not in SYSTEM_SLOT_PRESETS:
        raise ValueError("Unbekannte Steckplatzvorlage")
    config = json.loads(raw.decode("utf-8"))
    _core_snapshot_from_bytes(raw)
    template = SYSTEM_SLOT_PRESETS[preset]
    core = {**DEFAULT_CORE_SLOTS["buddha_chat"], **template,
            "id": "system-" + uuid.uuid4().hex[:12], "system": True,
            "type": "continuous", "execution_kind": "worker", "status": "idle",
            "enabled": True, "sub_mode": template.get("sub_mode", "expert_role"), "require_assigned_slot": True,
            "current_activity": "", "chat_id": "", "category": "all"}
    core.update(_validated_core_edits(changes) if changes else {})
    config["slots"][core["id"]] = core
    save_slots_config(config, path)
    return {"slot_id": core["id"], **core_system_agents_snapshot(path)}


@_serialized_mutation
def delete_system_slot(slot_id: str, expected_version: str, path: str | None = None) -> bool:
    if slot_id in CORE_SYSTEM_AGENT_IDS or not get_system_slot(slot_id, path):
        raise ValueError("Dieser Systemsteckplatz kann nicht gelöscht werden")
    raw = _resolve_path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_version:
        raise RuntimeError("configuration_version_conflict")
    config = json.loads(raw.decode("utf-8"))
    del config["slots"][slot_id]
    save_slots_config(config, path)
    return True


@_serialized_mutation
def materialize_system_blueprint(blueprint_id: int, blueprint_version: int,
                                 changes: dict[str, Any], expected_version: str,
                                 *, path: str | None = None) -> dict[str, Any]:
    """Create one explicit Living instance without starting a provider.

    The stable ID reconciles a failed database commit on retry. Callers must
    verify a terminal controller before refreshing an existing instance.
    """
    if type(blueprint_id) is not int or blueprint_id <= 0 or type(blueprint_version) is not int:
        raise ValueError("Gültige Blueprint-ID und Version erforderlich")
    raw = _resolve_path(path).read_bytes()
    snapshot = _core_snapshot_from_bytes(raw)
    if snapshot["configuration_version"] != expected_version:
        raise RuntimeError("configuration_version_conflict")
    config = json.loads(raw.decode("utf-8"))
    slot_id = f"system-blueprint-{blueprint_id}"
    existing = config["slots"].get(slot_id)
    if existing is not None and (not isinstance(existing, dict)
            or existing.get("id") != slot_id or existing.get("system") is not True
            or existing.get("blueprint_id") != blueprint_id):
        raise ValueError("Blueprint-Steckplatz ist bereits anders belegt")
    if any(worker.get("id") == slot_id for worker in config.get("dynamic_workers", [])):
        raise ValueError("Blueprint-Steckplatz kollidiert mit einem Worker")
    fields = dict(changes)
    worker_type = fields.pop("worker_type", None)
    if worker_type not in {"once", "continuous"}:
        raise ValueError("Worker-Laufbegrenzung muss ausdrücklich festgelegt werden")
    edits = _validated_core_edits(fields)
    core = {**DEFAULT_CORE_SLOTS["buddha_chat"], **(existing or {}),
            "id": slot_id, "system": True, "execution_kind": "worker",
            "type": worker_type, "require_assigned_slot": True,
            "blueprint_id": blueprint_id, "blueprint_version": blueprint_version,
            "enabled": True, "status": "idle", "current_activity": "",
            "chat_id": "", "task_id": None, "category": "all", **edits}
    config["slots"][slot_id] = core
    save_slots_config(config, path)
    return {"slot_id": slot_id, **core_system_agents_snapshot(path)}


def system_worker_at_version(slot_id: str, expected_version: str,
                             *, path: str | None = None) -> dict[str, Any]:
    """Read the exact config approved by the caller from one atomic file image."""
    raw = _resolve_path(path).read_bytes()
    snapshot = _core_snapshot_from_bytes(raw)
    if expected_version != snapshot["configuration_version"]:
        raise RuntimeError("configuration_version_conflict")
    config = json.loads(raw.decode("utf-8"))
    slot = config["slots"].get(slot_id)
    if (not isinstance(slot, dict) or slot.get("id") != slot_id
            or (slot_id != "buddha_always_on" and
                (slot.get("system") is not True or slot.get("execution_kind") != "worker"))
            or any(worker.get("id") == slot_id for worker in config.get("dynamic_workers", []))):
        raise ValueError("System-Worker ist nicht eindeutig vorhanden")
    worker_type = slot.get("type", "continuous")
    if worker_type not in {"once", "continuous"}:
        raise ValueError("System-Worker-Laufbegrenzung ist ungültig")
    return {**DEFAULT_CORE_SLOTS.get(slot_id, {}), **slot, "type": worker_type, "system": True}


def _core_prompt_definitions() -> dict[str, str]:
    return {
        "system_default": DEFAULT_SYSTEM_PROMPT,
        **{"role_" + role_id: body for role_id, body in DEFAULT_ROLE_PROMPTS.items()},
    }


def core_prompt_snapshot(path: str | None = None) -> dict[str, Any]:
    """Project immutable source defaults and user overrides from Control config."""
    target = _resolve_path(path)
    raw = target.read_bytes()
    config = json.loads(raw.decode("utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("slots"), dict):
        raise ValueError("Control-Konfiguration ist ungültig")
    custom = config.get("prompts", {})
    if not isinstance(custom, dict):
        raise ValueError("Prompt-Overrides sind ungültig")
    definitions = _core_prompt_definitions()
    prompts = {}
    for key, default in definitions.items():
        override = custom.get(key)
        if override is not None and not isinstance(override, str):
            raise ValueError("Prompt-Override ist ungültig")
        prompts[key] = {
            "key": key,
            "default": default,
            "effective": override if override is not None else default,
            "is_custom": override is not None,
        }
    source_bytes = json.dumps(definitions, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return {
        "schema": "bach.core-prompts.v1",
        "configuration_version": hashlib.sha256(raw).hexdigest(),
        "source_version": hashlib.sha256(source_bytes).hexdigest(),
        "prompts": prompts,
    }


@_serialized_mutation
def change_core_prompt(
    key: str, expected_version: str, *, text: str | None = None,
    reset: bool = False, path: str | None = None,
) -> dict[str, Any]:
    """CAS update a known override; reset removes only that override."""
    definitions = _core_prompt_definitions()
    if key not in definitions:
        raise KeyError("Unbekannte Prompt-ID")
    target = _resolve_path(path)
    raw = target.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_version:
        raise RuntimeError("configuration_version_conflict")
    config = json.loads(raw.decode("utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("slots"), dict):
        raise ValueError("Control-Konfiguration ist ungültig")
    custom = config.setdefault("prompts", {})
    if not isinstance(custom, dict):
        raise ValueError("Prompt-Overrides sind ungültig")
    if reset:
        if text is not None:
            raise ValueError("Reset nimmt keinen Prompttext an")
        custom.pop(key, None)
    else:
        if (not isinstance(text, str) or not text.strip()
                or len(text) > 50000 or "\x00" in text):
            raise ValueError("Prompttext fehlt oder ist ungültig")
        custom[key] = text
    save_slots_config(config, path)
    return core_prompt_snapshot(path)


@_serialized_mutation
def reconcile_workers(
    active_worker_ids: set[str] | None = None,
    path: str | None = None
) -> list[dict[str, Any]]:
    """Reconcile dynamic worker states against active thread IDs and TTLs.

    Any worker marked as 'running' whose ID is not in active_worker_ids
    (when provided) is considered orphaned/frozen and reset to 'idle' or 'completed'.
    """
    cfg = load_slots_config(path, strict=True)
    now_iso = datetime.now(timezone.utc).isoformat()
    workers = cfg.get("dynamic_workers", [])
    dirty = False

    for w in workers:
        # 1. TTL expiration
        expires_at = w.get("expires_at")
        if expires_at and expires_at < now_iso and w.get("status") not in ("expired", "completed"):
            w["status"] = "expired"
            w["current_activity"] = "Ablaufzeit erreicht (Beendet)"
            dirty = True

        # 2. Frozen/orphaned running status
        if active_worker_ids is not None and w.get("status") == "running":
            wid = w.get("id")
            if wid not in active_worker_ids:
                next_st = "completed" if w.get("type") == "once" else "idle"
                w["status"] = next_st
                w["current_activity"] = "Bereit (wiederhergestellt)"
                dirty = True

    if dirty:
        save_slots_config(cfg, path)
    return workers


def list_workers(
    path: str | None = None,
    include_expired: bool = False,
    active_worker_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return all dynamic workers, automatically updating expiration and running states."""
    workers = reconcile_workers(active_worker_ids=active_worker_ids, path=path)
    result = []
    for w in workers:
        if include_expired or w.get("status") != "expired":
            result.append(w)
    return result


def get_prompt_templates(path: str | None = None) -> dict[str, Any]:
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


@_serialized_mutation
def update_prompt_template(key: str, text: str, path: str | None = None) -> bool:
    """Save a customized prompt template."""
    cfg = load_slots_config(path, strict=True)
    prompts = cfg.setdefault("prompts", {})
    prompts[key] = text
    save_slots_config(cfg, path)
    log.info("Updated prompt template for %r", key)
    return True


@_serialized_mutation
def reset_prompt_template(key: str | None = None, path: str | None = None) -> bool:
    """Reset a customized prompt template (or all) back to factory default."""
    cfg = load_slots_config(path, strict=True)
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


@_serialized_mutation
def update_fackel_preference(preference: str, path: str | None = None) -> str:
    """Persist the compute preference without a stale whole-file write."""
    cfg = load_slots_config(path, strict=True)
    cfg["fackel_preference"] = preference
    save_slots_config(cfg, path)
    return preference


def compose_worker_prompt(worker_dict: dict[str, Any], path: str | None = None) -> str:
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
        parts.append((custom_sys or sys_default_text).strip() if
                     worker_dict.get("system") or worker_dict.get("id") in DEFAULT_CORE_SLOTS
                     else sys_default_text.strip())

    # 2. Role Instruction
    custom_role = str(worker_dict.get("custom_role_prompt") or "").strip()
    if custom_role:
        parts.append(f"--- ROLLE: {role_id or sub_mode} ---\n{custom_role}")
    elif sub_mode == "hintergrund_worker":
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
    if custom_sys and custom_sys not in parts and not (
            worker_dict.get("system") or worker_dict.get("id") in DEFAULT_CORE_SLOTS):
        parts.append(f"--- ZUSATZ-INSTRUKTION ---\n{custom_sys}")

    # 4. User Task Prompt
    if task_prompt:
        parts.append(f"--- AUFTRAG / AUFGABE ---\n{task_prompt}")

    return "\n\n".join(parts)


@_serialized_mutation
def add_worker(worker_data: dict[str, Any], path: str | None = None) -> dict[str, Any]:
    """Create a new dynamic background worker."""
    cfg = load_slots_config(path, strict=True)
    workers = cfg.setdefault("dynamic_workers", [])

    supplied_id = worker_data.get("id")
    if supplied_id is not None and (
        not isinstance(supplied_id, str)
        or not supplied_id.strip()
        or supplied_id.strip() != supplied_id
    ):
        raise ValueError("Worker-ID muss ein nichtleerer String ohne Rand-Leerraum sein")
    worker_id = supplied_id or f"worker-{uuid.uuid4().hex[:8]}"
    if (worker_id in cfg.get("slots", {}) or worker_id in DEFAULT_CORE_SLOTS
            or any(w.get("id") == worker_id for w in workers)):
        raise ValueError(f"Worker-ID {worker_id!r} ist bereits belegt")
    name = worker_data.get("name") or f"Worker {worker_id[-4:]}"
    role = worker_data.get("role", "general")
    backend = worker_data.get("backend", "ollama")
    model = worker_data.get("model", "qwen3.8:27b-mlx")
    mode = worker_data.get("mode", "full")
    think = bool(worker_data.get("think", True))
    max_tool_rounds = int(worker_data.get("max_tool_rounds", 20))
    allow_tools = worker_data.get("allow_tools", True)
    if not isinstance(allow_tools, bool):
        raise ValueError("allow_tools muss ein JSON-Boolean sein")
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
        "resolved_model": worker_data.get("resolved_model") or "",
        "mode": mode,
        "think": think,
        "max_tool_rounds": max_tool_rounds,
        "allow_tools": allow_tools,
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
        "pause_after": int(worker_data.get("pause_after", 0) or 0),
        "pause_minutes": int(worker_data.get("pause_minutes", 0) or 0),
        "pause_basis": str(worker_data.get("pause_basis", "runs") or "runs"),
        "pause_counter": 0,
        "pause_started_at": "",
    }

    workers.append(worker)
    save_slots_config(cfg, path)
    log.info("Created dynamic worker %s (%s, sub_mode=%s, model=%s)", worker_id, name, sub_mode, model)
    return worker


@_serialized_mutation
def remove_worker(worker_id: str, path: str | None = None) -> bool:
    """Delete a dynamic worker by ID."""
    cfg = load_slots_config(path, strict=True)
    workers = cfg.get("dynamic_workers", [])
    matches = [w for w in workers if w.get("id") == worker_id]
    if len(matches) > 1 or (matches and (
        worker_id in cfg.get("slots", {}) or worker_id in DEFAULT_CORE_SLOTS
    )):
        raise ValueError(f"Worker-ID {worker_id!r} ist nicht eindeutig")
    new_workers = [w for w in workers if w.get("id") != worker_id]
    if len(new_workers) == len(workers):
        return False
    cfg["dynamic_workers"] = new_workers
    save_slots_config(cfg, path)
    log.info("Removed dynamic worker %s", worker_id)
    return True


@_serialized_mutation
def record_activity(
    source: str,
    activity: str,
    status: str = "ok",
    details: dict[str, Any] | None = None,
    path: str | None = None
) -> None:
    """Record an action in the live activity history timeline."""
    cfg = load_slots_config(path)  # non-strict: frische Defaults falls Datei fehlt;
    # save_slots_config schreibt sie (Fix Task #1469 Finding d: strict crashte
    # bei frischer Installation ohne Config-Datei)
    history = cfg.setdefault("activity_history", [])

    entry = {
        "id": f"act-{uuid.uuid4().hex[:6]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "activity": activity,
        "status": status,
        "details": details or {},
    }
    # Assignment-Ereignisse bleiben zusätzlich auf der bestehenden flachen
    # Aktivitätsform sichtbar. Alte /api/activity-Leser ignorieren die neuen
    # Felder; neue Leser müssen nicht in details hineinwechseln.
    assignment_details = entry["details"] if isinstance(entry["details"], dict) else {}
    for key in (
        "assignment_id", "event", "role_id", "role_revision",
        "agent_instance_id", "backend_id", "model_id", "slot_id",
        "task_id", "session_id", "initiated_by", "started_at", "ended_at",
        "result", "reason",
    ):
        if key in assignment_details:
            entry[key] = assignment_details[key]
    history.insert(0, entry)
    # Keep latest 100 entries
    if len(history) > 100:
        cfg["activity_history"] = history[:100]

    # Update slot current activity if matching
    if source in cfg.get("slots", {}):
        cfg["slots"][source]["current_activity"] = activity
    else:
        for w in cfg.get("dynamic_workers", []):
            if w.get("id") == source:
                w["current_activity"] = activity
                w.setdefault("history", []).insert(0, entry)
                w["history"] = w["history"][:20]

    save_slots_config(cfg, path)


WORKER_EDITABLE_FIELDS = frozenset({
    "name", "backend", "model", "mode", "think", "max_tool_rounds", "allow_tools",
    "task_prompt", "sub_mode", "include_system_prompt", "role_id", "multi_role",
    "max_experts", "expert_models", "task_id", "pause_after", "pause_minutes", "pause_basis",
})


def _worker_configuration(worker: dict[str, Any]) -> dict[str, Any]:
    configuration = {field: worker.get(field) for field in sorted(WORKER_EDITABLE_FIELDS)}
    raw = json.dumps({"id": worker["id"], **configuration}, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return {"id": worker["id"], "configuration": configuration,
            "configuration_version": hashlib.sha256(raw).hexdigest()}


def worker_configuration_snapshot(worker_id: str, *, path: str | None = None) -> dict[str, Any]:
    worker = get_worker_slot(worker_id, path=path)
    if not worker:
        raise KeyError("Workerprofil nicht gefunden")
    return _worker_configuration(worker)


@_serialized_mutation
def change_worker_configuration(worker_id: str, expected_version: str, changes: dict[str, Any],
                                *, path: str | None = None) -> dict[str, Any]:
    config = load_slots_config(path, strict=True)
    workers = [w for w in config.get("dynamic_workers", []) if w.get("id") == worker_id]
    if len(workers) != 1:
        raise KeyError("Workerprofil nicht eindeutig gefunden")
    worker = workers[0]
    if expected_version != _worker_configuration(worker)["configuration_version"]:
        raise RuntimeError("configuration_version_conflict")
    if worker.get("status") not in {"idle", "paused", "completed", "error"}:
        raise RuntimeError("worker_not_editable")
    expiry = _parse_timestamp(worker.get("expires_at"))
    if worker.get("expires_at") and (expiry is None or expiry <= datetime.now(timezone.utc)):
        raise RuntimeError("worker_not_editable")
    if not isinstance(changes, dict) or not changes or set(changes) - WORKER_EDITABLE_FIELDS:
        raise ValueError("Unbekannte Worker-Konfigurationsfelder")
    boolean_fields = {"think", "allow_tools", "include_system_prompt", "multi_role"}
    ranges = {"max_tool_rounds": (0, 100), "pause_after": (0, 100),
              "pause_minutes": (0, 1440), "max_experts": (1, 10)}
    edits = dict(changes)
    for field, value in edits.items():
        if field in boolean_fields and type(value) is not bool:
            raise ValueError(f"{field} muss wahr oder falsch sein")
        if field in ranges:
            low, high = ranges[field]
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{field} liegt außerhalb des erlaubten Bereichs")
        if field in {"name", "backend", "model", "mode", "sub_mode", "role_id", "pause_basis", "task_prompt"}:
            maximum = 20000 if field == "task_prompt" else 180
            if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
                raise ValueError(f"{field} ist ungültig")
            if field not in {"role_id", "task_prompt"} and not value.strip():
                raise ValueError(f"{field} darf nicht leer sein")
        if field == "task_id" and value is not None and (type(value) is not int or not 1 <= value <= 2147483647):
            raise ValueError("Task-ID ist ungültig")
        if field == "expert_models" and (not isinstance(value, dict) or len(value) > 10 or any(
                key not in {*DEFAULT_ROLE_PROMPTS, "default"} or not isinstance(model, str)
                or not model.strip() or len(model) > 180 for key, model in value.items())):
            raise ValueError("Experten-Modellzuordnung ist ungültig")
    updated = {**worker, **edits}
    if (updated.get("backend") not in {"ollama", "ollama-cloud", "openrouter"}
            or updated.get("mode") not in {"safe", "full"}
            or updated.get("pause_basis") not in {"runs", "tasks"}
            or updated.get("sub_mode") not in {"hintergrund_worker", "task_worker", "boss_routing", "expert_role"}):
        raise ValueError("Worker-Modus oder Provider ist ungültig")
    if updated["sub_mode"] == "expert_role":
        if not updated.get("multi_role") and updated.get("role_id") not in DEFAULT_ROLE_PROMPTS:
            raise ValueError("Fachrolle ist nicht registriert")
    elif updated.get("role_id") or updated.get("multi_role"):
        raise ValueError("Fachrollenoptionen gelten nur für Expertenrollen")
    if updated["sub_mode"] != "boss_routing" and updated.get("expert_models"):
        raise ValueError("Experten-Modellzuordnungen gelten nur für Bossrouting")
    if updated["sub_mode"] == "task_worker" and not updated.get("task_id") and not updated.get("task_prompt"):
        raise ValueError("Taskworker benötigen eine Task-ID oder einen Auftragstext")
    updated["system_prompt"] = compose_worker_prompt(updated, path=path)
    worker.update(updated)
    save_slots_config(config, path)
    return _worker_configuration(worker)


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO timestamp string or datetime object, returning UTC aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        val = value.strip()
        if not val:
            return None
        if val.endswith("Z"):
            val = val[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(val)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _entry_timestamp(entry: dict[str, Any]) -> datetime | None:
    """Return the parsed UTC timestamp of an activity entry."""
    ts = entry.get("timestamp")
    if not ts:
        return None
    parsed = _parse_timestamp(ts)
    if parsed and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def get_activity_history(
    limit: int = 50,
    offset: int = 0,
    source: str | list[str] | None = None,
    status: str | list[str] | None = None,
    since: str | datetime | None = None,
    until: str | datetime | None = None,
    order: str = "desc",
    path: str | None = None,
) -> list[dict[str, Any]]:
    """Return filtered and paginated activity history.

    Parameters
    ----------
    limit: Maximum number of entries to return (default 50).
    offset: Number of entries to skip after sorting.
    source: Filter by source slot/worker id(s); string or list of strings.
    status: Filter by status value(s); string or list of strings.
    since: ISO timestamp or datetime; only return entries at or after this.
    until: ISO timestamp or datetime; only return entries at or before this.
    order: "desc" (newest first, default) or "asc" (oldest first).
    path: Optional override path for the slots config file.
    """
    cfg = load_slots_config(path)
    history = list(cfg.get("activity_history", []))

    since_dt = _parse_timestamp(since)
    until_dt = _parse_timestamp(until)
    sources = {source} if isinstance(source, str) else (set(source) if source else set())
    statuses = {status} if isinstance(status, str) else (set(status) if status else set())

    def _matches(entry: dict[str, Any]) -> bool:
        if sources and entry.get("source") not in sources:
            return False
        if statuses and entry.get("status") not in statuses:
            return False
        ts = _entry_timestamp(entry)
        if ts is None:
            return False
        if since_dt is not None and ts < since_dt:
            return False
        return not (until_dt is not None and ts > until_dt)

    filtered = [e for e in history if _matches(e)]

    reverse = (order.lower() == "desc")
    if reverse:
        # history is already newest-first, but re-sort to be safe.
        sorted_entries = sorted(filtered, key=_entry_timestamp, reverse=True)
    else:
        sorted_entries = sorted(filtered, key=_entry_timestamp, reverse=False)

    return sorted_entries[offset:offset + limit]
