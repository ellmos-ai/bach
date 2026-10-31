# coding: utf-8
"""ellmos.module.v2 — Schema, Validierung und Lebenszyklus für mitgelieferte
Agentenrollen (roles[]) und Pflegeaufgaben (maintenance[]) (#2447).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

VALID_MAINTENANCE_CLASSES = frozenset({"job", "agent-recommended", "agent-required"})
VALID_DIFFICULTIES = frozenset({"low", "medium", "high"})
VALID_ACCESS_TYPES = frozenset({"api", "cli", "browser", "local"})
ORIGIN_REMOVED_BADGE = "Herkunft entfernt"


def validate_module_delivery_manifest(manifest: dict[str, Any]) -> list[str]:
    """Prüft roles[] und maintenance[] in einem ellmos.module.v2-Manifest."""
    errors: list[str] = []
    module_id = str(manifest.get("id") or "").strip()
    if not module_id:
        errors.append("module.id fehlt")

    roles = manifest.get("roles", [])
    if not isinstance(roles, list):
        errors.append("roles muss eine Liste sein")
        roles = []

    role_ids: set[str] = set()
    for idx, role in enumerate(roles):
        if not isinstance(role, dict):
            errors.append(f"roles[{idx}] muss ein Objekt sein")
            continue
        rid = str(role.get("id") or "").strip()
        label = str(role.get("label") or "").strip()
        if not rid:
            errors.append(f"roles[{idx}].id fehlt")
        elif rid in role_ids:
            errors.append(f"roles[{idx}].id doppelt: {rid}")
        else:
            role_ids.add(rid)
        if not label:
            errors.append(f"roles[{idx}].label fehlt")
        access = str(role.get("default_access") or "api").strip()
        if access not in VALID_ACCESS_TYPES:
            errors.append(f"roles[{idx}].default_access ungültig: {access}")

    maintenance = manifest.get("maintenance", [])
    if not isinstance(maintenance, list):
        errors.append("maintenance muss eine Liste sein")
        maintenance = []

    maint_ids: set[str] = set()
    for idx, item in enumerate(maintenance):
        if not isinstance(item, dict):
            errors.append(f"maintenance[{idx}] muss ein Objekt sein")
            continue
        mid = str(item.get("id") or "").strip()
        label = str(item.get("label") or "").strip()
        mclass = str(item.get("class") or "").strip()
        trigger = str(item.get("trigger") or "").strip()
        requires_model = item.get("requires_model")
        difficulty = str(item.get("difficulty") or "low").strip()
        requirements = item.get("requirements", [])

        if not mid:
            errors.append(f"maintenance[{idx}].id fehlt")
        elif mid in maint_ids:
            errors.append(f"maintenance[{idx}].id doppelt: {mid}")
        else:
            maint_ids.add(mid)
        if not label:
            errors.append(f"maintenance[{idx}].label fehlt")
        if mclass not in VALID_MAINTENANCE_CLASSES:
            errors.append(f"maintenance[{idx}].class ungültig: {mclass}")
        if not trigger:
            errors.append(f"maintenance[{idx}].trigger fehlt")
        if not isinstance(requires_model, bool):
            errors.append(f"maintenance[{idx}].requires_model muss bool sein")
        elif mclass == "job" and requires_model is True:
            errors.append(f"maintenance[{idx}] (class=job) darf kein Modell voraussetzen")
        elif mclass == "agent-required" and requires_model is False:
            errors.append(f"maintenance[{idx}] (class=agent-required) benötigt requires_model=True")
        if difficulty not in VALID_DIFFICULTIES:
            errors.append(f"maintenance[{idx}].difficulty ungültig: {difficulty}")
        if not isinstance(requirements, list):
            errors.append(f"maintenance[{idx}].requirements muss eine Liste sein")

    return errors


@dataclass
class ModuleDeliveryCatalog:
    """Verwaltet den Lebenszyklus (Install, Update, Uninstall) von Modul-Rollen und Pflegeaufgaben."""
    role_templates: dict[str, dict[str, Any]] = field(default_factory=dict)
    agent_instances: dict[str, dict[str, Any]] = field(default_factory=dict)
    maintenance_catalog: dict[str, dict[str, Any]] = field(default_factory=dict)
    scheduled_maintenance: dict[str, dict[str, Any]] = field(default_factory=dict)

    def install_or_update_module(self, manifest: dict[str, Any]) -> None:
        errors = validate_module_delivery_manifest(manifest)
        if errors:
            raise ValueError("; ".join(errors))
        module_id = str(manifest["id"]).strip()
        version = str(manifest.get("version") or "1.0.0")

        for role in manifest.get("roles", []):
            key = f"{module_id}:{role['id']}"
            self.role_templates[key] = {
                **role,
                "key": key,
                "origin_module": module_id,
                "origin_version": version,
                "is_template": True,
                "active": False,
                "origin_removed": False,
                "origin_badge": None,
            }
            for inst in self.agent_instances.values():
                if inst.get("template_key") == key:
                    inst["origin_removed"] = False
                    inst["origin_badge"] = None

        for maint in manifest.get("maintenance", []):
            key = f"{module_id}:{maint['id']}"
            self.maintenance_catalog[key] = {
                **maint,
                "key": key,
                "origin_module": module_id,
                "origin_version": version,
                "active": False,
                "origin_removed": False,
                "origin_badge": None,
            }
            if key in self.scheduled_maintenance:
                self.scheduled_maintenance[key]["origin_removed"] = False
                self.scheduled_maintenance[key]["origin_badge"] = None

    def instantiate_agent(self, template_key: str, instance_id: str, **overrides: Any) -> dict[str, Any]:
        if template_key not in self.role_templates:
            raise KeyError(f"Unbekannte Rollenvorlage: {template_key}")
        tpl = self.role_templates[template_key]
        inst = {
            "instance_id": instance_id,
            "template_key": template_key,
            "origin_module": tpl["origin_module"],
            "label": overrides.get("label", tpl["label"]),
            "default_access": overrides.get("default_access", tpl.get("default_access", "api")),
            "is_template": False,
            "origin_removed": False,
            "origin_badge": None,
        }
        self.agent_instances[instance_id] = inst
        return inst

    def schedule_maintenance(self, maint_key: str, *, execution_mode: str | None = None) -> dict[str, Any]:
        if maint_key not in self.maintenance_catalog:
            raise KeyError(f"Unbekannte Pflegeaufgabe: {maint_key}")
        item = self.maintenance_catalog[maint_key]
        mode = execution_mode or ("job" if item["class"] == "job" else "agent")
        if item["class"] == "job" and mode != "job":
            raise ValueError("Reine Skript-Jobs starten keinen Agenten")
        sched = {
            **item,
            "active": True,
            "execution_mode": mode,
            "origin_removed": False,
            "origin_badge": None,
        }
        self.scheduled_maintenance[maint_key] = sched
        return sched

    def uninstall_module(self, module_id: str) -> dict[str, Any]:
        """Entfernt Vorlagen des Moduls, erhält aber angelegte Instanzen und geplante
        Pflegeaufgaben mit dem Hinweis 'Herkunft entfernt'.
        """
        removed_templates = [k for k, v in self.role_templates.items() if v["origin_module"] == module_id]
        for k in removed_templates:
            del self.role_templates[k]

        removed_maint = [k for k, v in self.maintenance_catalog.items() if v["origin_module"] == module_id]
        for k in removed_maint:
            del self.maintenance_catalog[k]

        marked_instances = []
        for iid, inst in self.agent_instances.items():
            if inst.get("origin_module") == module_id:
                inst["origin_removed"] = True
                inst["origin_badge"] = ORIGIN_REMOVED_BADGE
                marked_instances.append(iid)

        marked_schedules = []
        for skey, sched in self.scheduled_maintenance.items():
            if sched.get("origin_module") == module_id:
                sched["origin_removed"] = True
                sched["origin_badge"] = ORIGIN_REMOVED_BADGE
                marked_schedules.append(skey)

        return {
            "module_id": module_id,
            "removed_templates": removed_templates,
            "removed_maintenance": removed_maint,
            "marked_instances": marked_instances,
            "marked_schedules": marked_schedules,
        }
