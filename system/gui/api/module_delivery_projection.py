# coding: utf-8
"""GUI-Projektion für mitgelieferte Agenten-Vorlagen (roles[]) in der Agenten-Bibliothek
und Pflegeaufgaben (maintenance[]) unter Routinen (#2448).
"""
from __future__ import annotations
from typing import Any
from hub._services.module_delivery_lifecycle import ModuleDeliveryCatalog

CLASS_UI_META: dict[str, dict[str, Any]] = {
    "job": {
        "badge": "Reiner Skript-Job",
        "execution_options": ["job"],
        "default_execution_mode": "job",
        "description": "Läuft deterministisch ohne Sprachmodell.",
    },
    "agent-recommended": {
        "badge": "Agent empfohlen",
        "execution_options": ["job", "agent"],
        "default_execution_mode": "agent",
        "description": "Kann als einfacher Job oder mit Agenten-Urteilskraft geplant werden.",
    },
    "agent-required": {
        "badge": "Agent erforderlich",
        "execution_options": ["agent"],
        "default_execution_mode": "agent",
        "description": "Setzt zwingend einen zugewiesenen Agenten mit Sprachmodell voraus.",
    },
}


def project_module_library_and_routines(catalog: ModuleDeliveryCatalog) -> dict[str, Any]:
    """Erzeugt das GUI-View-Model für Agenten-Bibliothek und Routinen je Modul."""
    library_cards: list[dict[str, Any]] = []
    for key, tpl in sorted(catalog.role_templates.items()):
        library_cards.append({
            "key": key,
            "id": tpl["id"],
            "label": tpl["label"],
            "origin_module": tpl["origin_module"],
            "origin_badge": tpl.get("origin_badge") or f"Modul: {tpl['origin_module']}",
            "origin_removed": bool(tpl.get("origin_removed")),
            "default_access": tpl.get("default_access", "api"),
            "actions": ["Agent anlegen", "In Werkstatt öffnen"],
        })

    instance_cards: list[dict[str, Any]] = []
    for iid, inst in sorted(catalog.agent_instances.items()):
        instance_cards.append({
            "instance_id": iid,
            "label": inst["label"],
            "origin_module": inst["origin_module"],
            "origin_removed": bool(inst.get("origin_removed")),
            "origin_badge": inst.get("origin_badge") or f"Modul: {inst['origin_module']}",
            "default_access": inst.get("default_access", "api"),
        })

    routine_items: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for key, item in sorted(catalog.maintenance_catalog.items()):
        seen_keys.add(key)
        sched = catalog.scheduled_maintenance.get(key)
        meta = CLASS_UI_META[item["class"]]
        routine_items.append({
            "key": key,
            "id": item["id"],
            "label": item["label"],
            "origin_module": item["origin_module"],
            "class": item["class"],
            "class_badge": meta["badge"],
            "execution_options": list(meta["execution_options"]),
            "selected_execution_mode": sched["execution_mode"] if sched else meta["default_execution_mode"],
            "trigger": item["trigger"],
            "requires_model": item["requires_model"],
            "difficulty": item["difficulty"],
            "requirements": list(item.get("requirements", [])),
            "scheduled": bool(sched and sched.get("active")),
            "origin_removed": False,
            "origin_badge": f"Modul: {item['origin_module']}",
        })

    for key, sched in sorted(catalog.scheduled_maintenance.items()):
        if key in seen_keys:
            continue
        meta = CLASS_UI_META[sched["class"]]
        routine_items.append({
            "key": key,
            "id": sched["id"],
            "label": sched["label"],
            "origin_module": sched["origin_module"],
            "class": sched["class"],
            "class_badge": meta["badge"],
            "execution_options": list(meta["execution_options"]),
            "selected_execution_mode": sched["execution_mode"],
            "trigger": sched["trigger"],
            "requires_model": sched["requires_model"],
            "difficulty": sched["difficulty"],
            "requirements": list(sched.get("requirements", [])),
            "scheduled": bool(sched.get("active")),
            "origin_removed": bool(sched.get("origin_removed")),
            "origin_badge": sched.get("origin_badge") or f"Modul: {sched['origin_module']}",
        })

    return {
        "agent_library": library_cards,
        "agent_instances": instance_cards,
        "routines": routine_items,
    }
