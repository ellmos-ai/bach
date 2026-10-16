"""CLI/library access to the same worker settings service as the GUI."""
from __future__ import annotations

import json
from .base import BaseHandler
from ._services import worker_policy_settings as service


class WorkerPolicyHandler(BaseHandler):
    @property
    def profile_name(self):
        return "worker-policy"

    @property
    def target_file(self):
        return self._canonical_db

    def get_operations(self):
        return {"status": "Globale Worker-Regeln lesen", "set": "Globale Regeln als JSON mit CAS speichern",
                "task_show": "Taskregeln lesen: ID", "task_set": "Taskregeln speichern: ID JSON"}

    def handle(self, operation, args, dry_run=False):
        try:
            if operation in {"", "status"} and not args:
                result = service.read_global_policy(db_path=self.target_file)
            elif operation == "task_show" and len(args) == 1:
                result = service.read_task_policy(int(args[0]), db_path=self.target_file)
            elif operation in {"set", "task_set"}:
                if dry_run:
                    return False, "Schreibprüfung ohne Speichern: zuerst status/task_show lesen; kein CAS-Verbrauch"
                if operation == "set" and len(args) == 1:
                    result = service.write_global_policy(json.loads(args[0]), actor="local:worker-policy", db_path=self.target_file)
                elif operation == "task_set" and len(args) == 2:
                    result = service.write_task_policy(int(args[0]), json.loads(args[1]), actor="local:worker-policy", db_path=self.target_file)
                else:
                    return False, "Erwartet: set JSON oder task_set ID JSON"
            else:
                return False, "Erwartet: status | task_show ID | set JSON | task_set ID JSON"
            return True, json.dumps(result, ensure_ascii=False, sort_keys=True)
        except (service.PolicyUnavailable, service.PolicyConflict, ValueError, TypeError, KeyError) as exc:
            return False, str(exc)
