"""CLI/library access to the same task-lease setting service as the GUI (BACH #2231)."""
from __future__ import annotations

import json
from .base import BaseHandler
from ._services import task_lease_settings as service


class TaskLeaseHandler(BaseHandler):
    @property
    def profile_name(self):
        return "task-lease"

    @property
    def target_file(self):
        return self._canonical_db

    def get_operations(self):
        return {"status": "Ersteller-Vorrang für Task-Leases lesen",
                "set": "Ersteller-Vorrang als JSON mit CAS speichern"}

    def handle(self, operation, args, dry_run=False):
        try:
            if operation in {"", "status"} and not args:
                result = service.read_setting(db_path=self.target_file)
            elif operation == "set":
                if dry_run:
                    return False, "Schreibprüfung ohne Speichern: zuerst status lesen; kein CAS-Verbrauch"
                if len(args) == 1:
                    result = service.write_setting(json.loads(args[0]), actor="local:task-lease",
                                                   db_path=self.target_file)
                else:
                    return False, "Erwartet: set JSON mit configuration_version, enabled und window_seconds"
            else:
                return False, "Erwartet: status | set JSON"
            return True, json.dumps(result, ensure_ascii=False, sort_keys=True)
        except (service.PolicyUnavailable, service.PolicyConflict, ValueError, TypeError, KeyError) as exc:
            return False, str(exc)
