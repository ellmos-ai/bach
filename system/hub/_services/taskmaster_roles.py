# SPDX-License-Identifier: MIT
"""Native Taskmaster role contracts and deterministic queue policy helpers.

The BACH task table and Salt-Lease service remain authoritative.  This module
only describes the five system roles and provides pure selection primitives;
it never creates a second task store and never starts a worker.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any, Iterable


SCHEMA = "bach.taskmaster.roles.v1"
REVISION = "1.0.0"
_PRIORITY = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
_OPEN_STATUSES = frozenset({"pending", "open"})


_ROLE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "stable_id": "taskmaster.coding",
        "blueprint_name": "taskmaster_coding",
        "title": "Taskmaster · Coding",
        "description": "Implementiert und prüft versionierte Softwareaufgaben mit klarer Lease- und Ergebnisgrenze.",
        "persona_role": "entwickler",
        "persona_prompt": "Du bist die Coding-Rolle des nativen Taskmasters. Bearbeite genau eine zugewiesene Softwareaufgabe, prüfe den Bestand, arbeite reproduzierbar und gib ein quellengebundenes Ergebnis mit offenem Reviewstatus ab.",
        "skills": ["dev-cycle", "bugfix-protocol", "work-autonomous"],
        "animus_type": "cli",
        "contractus": {"turns": 24, "cooldown_seconds": 30, "task_types": ["code", "architecture"]},
        "modus": "usus",
        "governance": {"profile": "full_dev_guarded", "tool_whitelist": ["read_files", "search_content", "write_files", "execute_command", "run_tests", "task_manage"]},
        "task_types": ["code", "architecture"],
    },
    {
        "stable_id": "taskmaster.writer",
        "blueprint_name": "taskmaster_writer",
        "title": "Taskmaster · Writer",
        "description": "Findet freigegebene Dokumentations- und Rechercheaufgaben und schreibt deduplizierte Entwürfe.",
        "persona_role": "recherche",
        "persona_prompt": "Du bist die Writer-Rolle des nativen Taskmasters. Prüfe Quellen und bestehende Ergebnisse, schreibe nur im freigegebenen Umfang und markiere Unsicherheit, Herkunft und Reviewbedarf ausdrücklich.",
        "skills": ["docs-analysis", "find-docs", "llm-text-hygiene"],
        "animus_type": "api",
        "contractus": {"turns": 18, "cooldown_seconds": 60, "task_types": ["recherche", "routine"]},
        "modus": "usus",
        "governance": {"profile": "fail_closed_standard", "tool_whitelist": ["read_files", "search_content", "task_manage"]},
        "task_types": ["recherche", "routine"],
    },
    {
        "stable_id": "taskmaster.solver",
        "blueprint_name": "taskmaster_solver",
        "title": "Taskmaster · Solver",
        "description": "Übernimmt passende reale Aufgaben über die Lead-Lease und liefert ein getrennt prüfbares Ergebnis.",
        "persona_role": "task-divider",
        "persona_prompt": "Du bist die Solver-Rolle des nativen Taskmasters. Übernimm nur eine eigene, leasefähige Aufgabe, halte die Taskversion und Fencebindung ein und trenne Arbeitsergebnis, technische Ausführung und fachliche Abnahme.",
        "skills": ["agents-bridge", "work-autonomous", "decide"],
        "animus_type": "api",
        "contractus": {"turns": 20, "cooldown_seconds": 30, "task_types": ["allround", "code", "audit", "routing"]},
        "modus": "usus",
        "governance": {"profile": "fail_closed_standard", "tool_whitelist": ["read_files", "search_content", "task_manage"]},
        "task_types": ["allround", "code", "audit", "routing"],
    },
    {
        "stable_id": "taskmaster.maintainer",
        "blueprint_name": "taskmaster_maintainer",
        "title": "Taskmaster · Maintainer",
        "description": "Hält freigegebene Projekt- und Dokumentationsbestände geordnet und prüft Integrität.",
        "persona_role": "wartungsagent",
        "persona_prompt": "Du bist die Maintainer-Rolle des nativen Taskmasters. Prüfe Locks, Quellen, Status und Integrität zuerst; ändere nur den eigenen Umfang und hinterlasse einen nachvollziehbaren Wartungsbeleg.",
        "skills": ["sync", "work-autonomous", "decide"],
        "animus_type": "cli",
        "contractus": {"turns": 14, "cooldown_seconds": 300, "task_types": ["maintenance", "hygiene"]},
        "modus": "usus",
        "governance": {"profile": "fail_closed_standard", "tool_whitelist": ["read_files", "search_content", "write_files", "execute_command", "task_manage"]},
        "task_types": ["maintenance", "hygiene"],
    },
    {
        "stable_id": "taskmaster.operator",
        "blueprint_name": "taskmaster_operator",
        "title": "Taskmaster · Operator",
        "description": "Koordiniert Rollen, Reihenfolge, Budgets und getrennte Abnahme ohne eine zweite Taskquelle.",
        "persona_role": "boss_routing",
        "persona_prompt": "Du bist die Operator-Rolle des nativen Taskmasters. Koordiniere Auswahl, Budget, Reihenfolge und Abnahme anhand der kanonischen TaskDB; starte keinen Cloud-Worker ohne ausdrückliche Nutzeraktivierung.",
        "skills": ["decide", "agents-bridge", "work-autonomous"],
        "animus_type": "api",
        "contractus": {"turns": 16, "cooldown_seconds": 120, "task_types": ["routing", "triage", "allround"]},
        "modus": "usus",
        "governance": {"profile": "fail_closed_standard", "tool_whitelist": ["read_files", "search_content", "task_manage"]},
        "task_types": ["routing", "triage", "allround"],
    },
)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _content_hash(value: dict[str, Any]) -> str:
    return sha256(_canonical(value)).hexdigest()


def role_specs() -> tuple[dict[str, Any], ...]:
    """Return immutable-by-convention seed data for the five system roles."""
    return tuple({**deepcopy(item), "origin": "bach-native-taskmaster", "revision": REVISION}
                 for item in _ROLE_SPECS)


def role_catalog() -> dict[str, Any]:
    """Return the versioned role contract used by BACH and the shared GUI."""
    roles = []
    for source in role_specs():
        role = deepcopy(source)
        role["schema"] = SCHEMA
        role["revision"] = REVISION
        role["source"] = SCHEMA
        role["content_sha256"] = _content_hash(role)
        roles.append(role)
    return {"schema": SCHEMA, "revision": REVISION, "source": "bach-native", "roles": roles}


def role_for_task(task: dict[str, Any]) -> str:
    """Choose a role by explicit category, with Solver as the safe fallback."""
    category = str(task.get("category") or "").strip().lower()
    tags = {part.strip().lower() for part in str(task.get("tags") or "").replace(";", ",").split(",") if part.strip()}
    if category in {"development", "code", "software", "architecture", "gui", "frontend", "backend", "feature", "bugfix"} or tags & {"code", "software", "gui", "frontend", "backend", "feature", "bugfix"}:
        return "taskmaster.coding"
    if category in {"research", "recherche", "documentation", "docs"} or tags & {"docs", "research", "recherche"}:
        return "taskmaster.writer"
    if category in {"maintenance", "hygiene", "operations", "ops"} or tags & {"maintenance", "hygiene"}:
        return "taskmaster.maintainer"
    if category in {"routing", "triage", "coordination"} or tags & {"routing", "triage"}:
        return "taskmaster.operator"
    return "taskmaster.solver"


def deduplication_key(task_id: int, task_version: str, role_id: str) -> str:
    """Create a stable attempt key without storing a second task record."""
    if type(task_id) is not int or task_id <= 0:
        raise ValueError("task_id muss positiv sein")
    if not isinstance(task_version, str) or not task_version.strip():
        raise ValueError("task_version erforderlich")
    if not isinstance(role_id, str) or role_id not in {item["stable_id"] for item in _ROLE_SPECS}:
        raise ValueError("Unbekannte Taskmaster-Rolle")
    return sha256(f"{role_id}\0{task_id}\0{task_version}".encode("utf-8")).hexdigest()


def backoff_seconds(failures: int, *, base: int = 30, maximum: int = 3600) -> int:
    """Return deterministic exponential backoff for a retryable role attempt."""
    if type(failures) is not int or failures < 0:
        raise ValueError("failures muss eine nichtnegative Ganzzahl sein")
    if type(base) is not int or base < 1 or type(maximum) is not int or maximum < base:
        raise ValueError("Ungültige Backoff-Grenzen")
    return min(maximum, base * (2 ** min(failures, 31)))


def select_candidates(tasks: Iterable[dict[str, Any]], role_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Select task snapshots for preview; acquisition stays with the Lead API."""
    role = next((item for item in _ROLE_SPECS if item["stable_id"] == role_id), None)
    if role is None:
        raise ValueError("Unbekannte Taskmaster-Rolle")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit muss zwischen 1 und 100 liegen")
    allowed = set(role["task_types"])
    result = []
    for task in tasks:
        if not isinstance(task, dict) or task.get("status") not in _OPEN_STATUSES:
            continue
        if task.get("blocked") is True or task.get("dependencies_ready") is False:
            continue
        if task.get("required_model") or task.get("assigned_slot"):
            continue
        task_type = str(task.get("category") or "allround").strip().lower()
        if (task_type not in allowed and "allround" not in allowed
                and role_for_task(task) != role_id):
            continue
        result.append({
            "task_id": task.get("id"),
            "role_id": role_id,
            "priority": task.get("priority") or "P4",
            "created_at": task.get("created_at") or "",
            "deduplication_scope": "task_id+task_version+role_id",
        })
    result.sort(key=lambda item: (_PRIORITY.get(str(item["priority"]).upper(), 5),
                                  str(item["created_at"]), int(item["task_id"] or 0)))
    return result[:limit]
