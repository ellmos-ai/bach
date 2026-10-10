# SPDX-License-Identifier: MIT
"""Native model socket CLI. Same configuration/CAS as the GUI, no auto-start."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ._services.chat import model_sockets as service
from ._services.chat import slots_config
from .base import BaseHandler


class ModelSocketsHandler(BaseHandler):
    def __init__(self, base_path_or_app):
        # BaseHandler's legacy hasattr(app, "db") triggers App.db and its
        # lazy schema initialization. This handler does not use a task DB.
        self.app = None if isinstance(base_path_or_app, (str, Path)) else base_path_or_app
        self.base_path = Path(self.app.base_path if self.app is not None else base_path_or_app)

    @property
    def profile_name(self):
        return "model-sockets"

    @property
    def target_file(self):
        return slots_config._resolve_path(None)

    def get_operations(self):
        return {"list": "Steckplätze und Bindungen lesen", "catalog": "Lokale Modellmetadaten lesen",
                "migrate": "Bestehende Profile ausdrücklich migrieren",
                "configure": "Modellsteckplatz konfigurieren, ohne Modellstart",
                "bind": "Agent an Modellsteckplatz binden", "unbind": "Bindung entfernen"}

    def handle(self, operation, args, dry_run=False):
        if operation not in self.get_operations():
            return False, "Unbekannte Modellsteckplatzaktion"
        parser = argparse.ArgumentParser(prog="bach model-sockets " + operation, add_help=False)
        parser.add_argument("--json", action="store_true")
        if operation not in {"list", "catalog"}:
            parser.add_argument("--version", required=True)
        if operation == "configure":
            parser.add_argument("--backend", choices=["ollama", "lmstudio"], required=True)
            parser.add_argument("--model", required=True)
            parser.add_argument("--enabled", choices=["true", "false"])
            parser.add_argument("--max-active-slots", type=int)
            parser.add_argument("--residency-policy", choices=["exclusive", "shared"])
        elif operation == "bind":
            parser.add_argument("--agent", required=True)
            parser.add_argument("--socket", required=True)
            parser.add_argument("--enabled", choices=["true", "false"])
            parser.add_argument("--priority", choices=["foreground", "background"])
            parser.add_argument("--context-tokens", type=int)
        elif operation == "unbind":
            parser.add_argument("--binding", required=True)
        try:
            options = parser.parse_args(args)
        except SystemExit:
            return False, "Ungültige Argumente; Writes benötigen --version aus dem aktuellen list-Read"
        try:
            if operation == "catalog":
                from ._services.chat.local_model_catalog import local_model_catalog
                result = local_model_catalog()
            elif operation == "list":
                result = service.model_sockets_snapshot()
            elif dry_run:
                result = {"dry_run": True, "configuration_saved": False, "worker_started": False,
                          "operation": operation}
            else:
                if (len(options.version) != 64 or
                        any(c not in "0123456789abcdef" for c in options.version)):
                    raise ValueError("Gültige Konfigurationsversion erforderlich")
                changes = {key: value for key, value in vars(options).items() if value is not None
                           and key in {"enabled", "max_active_slots", "residency_policy", "priority", "context_tokens"}}
                if "enabled" in changes:
                    changes["enabled"] = changes["enabled"] == "true"
                if operation == "migrate":
                    result = service.migrate_model_sockets(options.version)
                elif operation == "configure":
                    result = service.configure_model_socket(options.version, {
                        "backend": options.backend, "model": options.model, **changes})
                elif operation == "bind":
                    result = service.bind_model_agent(options.version, options.agent, options.socket, changes)
                else:
                    result = service.remove_model_binding(options.version, options.binding)
                result["ack"] = {"configuration_saved": True, "worker_started": False, "runtime_verified": False}
            return True, json.dumps(result, ensure_ascii=False, indent=2)
        except (OSError, ValueError, TypeError, KeyError, RuntimeError):
            return False, "Modellsteckplatzaktion nicht bestätigt; Konfiguration, CAS-Version und Locks prüfen"
