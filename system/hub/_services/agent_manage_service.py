# SPDX-License-Identifier: MIT
"""Agent creation and local dispatch through the native controller.

Callbacks belong to the running controller. Tools cannot choose an endpoint,
token, filesystem path, or arbitrary provider. Creating a slot never starts it.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from hub._services.skill_source_service import check_write_locks


class AgentManager:
    def __init__(self, *, db_path, slots_path=None, execution_receipt, start_worker,
                 local_provider, guard=None):
        self.db_path = Path(db_path)
        self.slots_path = slots_path
        self.execution_receipt = execution_receipt
        self.start_worker = start_worker
        self.local_provider = local_provider
        self.guard = guard or check_write_locks

    def __call__(self, args, *, mode, allowed_tools):
        from hub._services.chat.slots_config import (
            core_system_agents_snapshot, get_system_slot, get_worker_slot, load_slots_config,
        )
        from hub._services.blueprint_service import save_blueprint, materialize_blueprint
        if not isinstance(args, dict):
            raise ValueError("Agentenwerkzeug erwartet ein Objekt")
        action = args.get("action")
        if action == "list":
            if set(args) != {"action"}:
                raise ValueError("Unbekannte Katalogargumente")
            snapshot = core_system_agents_snapshot(self.slots_path)
            snapshot["agents"].extend({**worker, "execution_kind": "worker"}
                for worker in load_slots_config(self.slots_path, strict=True)["dynamic_workers"])
            for slot in snapshot["agents"]:
                slot["execution"] = self.execution_receipt(slot["id"])
            fields = {"id", "name", "role_id", "backend", "model", "mode", "enabled", "execution_kind", "allowed_tools", "execution"}
            return {"source": "native_controller", "configuration_version": snapshot["configuration_version"],
                    "role_ids": snapshot["role_ids"],
                    "agents": [{k: v for k, v in slot.items() if k in fields} for slot in snapshot["agents"]]}
        if not self.db_path.is_file():
            raise RuntimeError("Kanonische TaskDB fehlt")
        if mode not in {"safe", "full"}:
            raise PermissionError("Agentenverwaltung ist in diesem Modus nicht verfügbar")
        if action == "blueprint_create":
            if set(args) != {"action", "blueprint"} or not isinstance(args["blueprint"], dict):
                raise ValueError("Blueprint erforderlich")
            payload = dict(args["blueprint"])
            if payload.get("expected_version", 0) != 0 or payload.get("is_template"):
                raise ValueError("Agenten legen eigene neue Blueprints an")
            governance = payload.get("governance", {})
            if not isinstance(governance, dict):
                raise ValueError("Blueprint benötigt gültige Werkzeugrechte")
            grants = governance.get("tool_whitelist", ["read_file", "list_directory", "search_text", "task_manage"])
            if not isinstance(grants, list) or any(tool not in allowed_tools for tool in grants):
                raise PermissionError("Neue Agenten erhalten höchstens die Werkzeugrechte ihres Erstellers")
            payload["expected_version"] = 0
            self.guard(self.db_path)
            with sqlite3.connect(self.db_path, timeout=5) as conn:
                saved = save_blueprint(conn, payload)
            return {**saved, "worker_started": False}
        if action == "materialize":
            if set(args) != {"action", "blueprint_id", "expected_version", "configuration_version", "execution"}:
                raise ValueError("Blueprint- und Konfigurationsversion erforderlich")
            blueprint_id = args["blueprint_id"]
            if type(blueprint_id) is not int or blueprint_id <= 0:
                raise ValueError("Gültige Blueprint-ID erforderlich")
            if get_system_slot(f"system-blueprint-{blueprint_id}", self.slots_path):
                raise PermissionError("Bestehende Steckplätze werden ausdrücklich im Editor aktualisiert")
            execution = args["execution"]
            if not isinstance(execution, dict) or execution.get("mode", "safe") not in {"safe", mode}:
                raise PermissionError("Steckplatz darf den Erstellermodus nicht erweitern")
            self.guard(self.db_path)
            from hub._services.chat.slots_config import _resolve_path
            self.guard(_resolve_path(self.slots_path))
            with sqlite3.connect(self.db_path, timeout=5) as conn:
                row = conn.execute("SELECT governance_json FROM agent_blueprints WHERE id=?", (blueprint_id,)).fetchone()
                if not row:
                    raise KeyError("Blueprint fehlt")
                grants = json.loads(row[0] or "{}").get("tool_whitelist", ["read_file", "list_directory", "search_text", "task_manage"])
                if not isinstance(grants, list) or any(tool not in allowed_tools for tool in grants):
                    raise PermissionError("Blueprint überschreitet die Werkzeugrechte seines Erstellers")
                return materialize_blueprint(conn, blueprint_id,
                    expected_version=args["expected_version"], execution=execution,
                    configuration_version=args["configuration_version"], slots_path=self.slots_path)
        if action == "start_local":
            if set(args) != {"action", "slot_id", "configuration_version"}:
                raise ValueError("Steckplatz und aktuelle Konfigurationsversion erforderlich")
            snapshot = core_system_agents_snapshot(self.slots_path)
            if args["configuration_version"] != snapshot["configuration_version"]:
                raise RuntimeError("configuration_version_conflict")
            slot_id = args["slot_id"]
            if not isinstance(slot_id, str) or not slot_id:
                raise ValueError("Gültige Steckplatz-ID erforderlich")
            slot = get_system_slot(slot_id, self.slots_path)
            if not slot:
                worker = get_worker_slot(slot_id, self.slots_path)
                slot = {**worker, "execution_kind": "worker"} if worker else {}
            if (not slot or slot.get("execution_kind") != "worker" or slot.get("enabled", True) is not True
                    or slot.get("backend") not in {"ollama", "lmstudio"}
                    or not slot.get("model") or ":cloud" in str(slot.get("model")).lower()
                    or ":cloud" in str(slot.get("resolved_model", "")).lower()):
                raise PermissionError("Agenten starten ausschließlich verfügbare lokale Worker")
            if slot.get("mode", "safe") not in {"safe", mode}:
                raise PermissionError("Worker-Modus überschreitet die Rechte des Erstellers")
            grants = slot.get("allowed_tools")
            if grants is None:
                from hub._services.chat.bach_tools import tools_for_mode
                grants = [tool["function"]["name"] for tool in tools_for_mode(slot.get("mode", "safe"), bound_worker=True)]
            if slot.get("allow_tools", True) is False:
                grants = []
            if not isinstance(grants, list) or any(tool not in allowed_tools for tool in grants):
                raise PermissionError("Worker-Werkzeugrechte sind nicht als Teilmenge bestätigt")
            if not self.local_provider(slot):
                raise PermissionError("Lokaler Provider-Endpunkt ist nicht bestätigt")
            self.guard(self.db_path)
            from hub._services.chat.slots_config import _resolve_path
            self.guard(_resolve_path(self.slots_path))
            previous = self.execution_receipt(slot["id"])
            if previous.get("state") not in {"idle", "terminal"}:
                raise PermissionError("Worker ist bereits aktiv oder ungeprüft")
            response, status = self.start_worker(slot["id"], start_request_id=uuid.uuid4().hex,
                expected_service_instance=previous["service_instance"],
                expected_configuration_version=args["configuration_version"])
            if status != 200 or response.get("execution", {}).get("worker_thread_started") is not True:
                raise RuntimeError("Lokaler Workerstart nicht bestätigt")
            return {"source": "native_controller", "cloud_started": False, **response}
        raise ValueError("Unbekannte Agentenaktion")
