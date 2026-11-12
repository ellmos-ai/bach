# coding: utf-8
"""Automationsagenten, Miniagenten und Jobs ohne Modell: Gemeinsamer Routinen-,
Ready- und Kalender-Lifecycle (#2329).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

FAMILIES = frozenset({"job", "automation_agent", "mini_agent"})
TRIGGERS = frozenset({"manual", "event", "routine", "calendar_once"})


@dataclass
class AutomationLifecycleRegistry:
    """Verwaltet Jobs ohne Modell, Miniagenten und Automations-Agenten mit Fence-Schutz."""
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    active_triggers: dict[str, str] = field(default_factory=dict)

    def register_entry(self, payload: dict[str, Any]) -> dict[str, Any]:
        eid = str(payload.get("id") or "").strip()
        family = str(payload.get("family") or "").strip()
        trigger = str(payload.get("trigger") or "routine").strip()
        if not eid:
            raise ValueError("id fehlt")
        if family not in FAMILIES:
            raise ValueError(f"Ungültige Familie: {family}")
        if trigger not in TRIGGERS:
            raise ValueError(f"Ungültige Startart: {trigger}")

        if family == "job" and payload.get("requires_model"):
            raise ValueError("Jobs ohne Modell dürfen kein Sprachmodell anfordern")
        if family == "mini_agent":
            if not payload.get("input_schema") or not payload.get("output_schema"):
                raise ValueError("Miniagenten benötigen festen Ein-/Ausgabevertrag (input_schema/output_schema)")
            if payload.get("allows_open_work") or payload.get("allows_reviews"):
                raise ValueError("Miniagenten erlauben keine offene Agentenarbeit oder Reviews")

        record = {
            "id": eid,
            "title": str(payload.get("title") or eid),
            "family": family,
            "trigger": trigger,
            "timezone": str(payload.get("timezone") or "Europe/Berlin"),
            "state": "available" if payload.get("from_module") and not payload.get("scheduled") else "ready",
            "fence": int(payload.get("fence") or 1),
            "last_start_trigger": None,
            "input_schema": payload.get("input_schema"),
            "output_schema": payload.get("output_schema"),
        }
        self.entries[eid] = record
        return record

    def trigger_start(self, eid: str, *, start_trigger: str, dedup_key: str, tz_now: datetime | None = None) -> dict[str, Any]:
        if eid not in self.entries:
            raise KeyError(f"Unbekannter Eintrag: {eid}")
        if start_trigger not in TRIGGERS:
            raise ValueError(f"Ungültiger Startanlass: {start_trigger}")
        if self.active_triggers.get(eid) == dedup_key:
            return {**self.entries[eid], "deduplicated": True}

        rec = self.entries[eid]
        if rec["state"] == "available":
            raise RuntimeError("Mitgelieferte Pflegeaufgaben laufen erst nach bestätigter Planung")

        tz = ZoneInfo(rec["timezone"])
        now_local = (tz_now or datetime.now(tz)).astimezone(tz)
        rec["fence"] += 1
        rec["state"] = "running"
        rec["last_start_trigger"] = start_trigger
        rec["started_at_local"] = now_local.isoformat()
        self.active_triggers[eid] = dedup_key
        return {**rec, "deduplicated": False}

    def stop_entry(self, eid: str, *, expected_fence: int) -> dict[str, Any]:
        rec = self.entries[eid]
        if rec["fence"] != expected_fence:
            raise RuntimeError(f"Fence-Konflikt beim Stopp: erwartet {expected_fence}, aktuell {rec['fence']}")
        rec["fence"] += 1
        rec["state"] = "ready"
        self.active_triggers.pop(eid, None)
        return rec
