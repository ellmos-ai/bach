# SPDX-License-Identifier: MIT
"""Native BACH policy compatibility adapter, without independent storage authority."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__version__ = "1.0.0"

CONTRACT = "worker-review-policy.v1alpha1"
GLOBAL_SCHEMA = "bach.worker-review-policy-settings.v1"
TASK_SCHEMA = "bach.task-worker-policy-override.v1"

class PolicyUnavailable(RuntimeError):
    pass

class PolicyConflict(ValueError):
    pass

try:
    from hub._services import worker_policy_settings as _service
except ImportError:
    _service = None
else:
    # Keep the native error identity: callers must observe real CAS/readiness failures.
    PolicyUnavailable = _service.PolicyUnavailable
    PolicyConflict = _service.PolicyConflict


def _native():
    if _service is None:
        raise PolicyUnavailable("Nativer Worker-Policydienst nicht verfügbar")
    return _service


def read_global_policy(db_path: Path | str | None = None) -> dict[str, Any]:
    return _native().read_global_policy(db_path=db_path)


def write_global_policy(
    policy: dict[str, Any],
    actor: str = "local:worker-policy",
    db_path: Path | str | None = None,
    *,
    operator_token: str | None = None,
) -> dict[str, Any]:
    return _native().write_global_policy(
        policy, actor=actor, db_path=db_path, operator_token=operator_token
    )


def read_task_policy(task_id: int, db_path: Path | str | None = None) -> dict[str, Any]:
    return _native().read_task_policy(task_id, db_path=db_path)


def write_task_policy(
    task_id: int,
    policy: dict[str, Any],
    actor: str = "local:worker-policy",
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    return _native().write_task_policy(task_id, policy, actor=actor, db_path=db_path)


class WorkerPolicyHandler:
    """CLI/API handler for worker policy."""

    def __init__(self, base_path: Path | None = None):
        self.base_path = Path(base_path) if base_path else Path.cwd()

    @property
    def profile_name(self) -> str:
        return "worker-policy"

    def get_operations(self) -> dict[str, str]:
        return {
            "status": "Globale Worker-Regeln lesen",
            "set": "Globale Regeln als JSON mit CAS speichern",
            "task_show": "Taskregeln lesen: ID",
            "task_set": "Taskregeln speichern: ID JSON",
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple[bool, str]:
        try:
            if operation in {"", "status"} and not args:
                result = read_global_policy()
            elif operation == "task_show" and len(args) == 1:
                result = read_task_policy(int(args[0]))
            elif operation in {"set", "task_set"}:
                if dry_run:
                    return False, "Schreibprüfung ohne Speichern: zuerst status/task_show lesen; kein CAS-Verbrauch"
                if operation == "set" and len(args) == 1:
                    result = write_global_policy(json.loads(args[0]), actor="local:worker-policy")
                elif operation == "task_set" and len(args) == 2:
                    result = write_task_policy(int(args[0]), json.loads(args[1]), actor="local:worker-policy")
                else:
                    return False, "Erwartet: set JSON oder task_set ID JSON"
            else:
                return False, "Erwartet: status | task_show ID | set JSON | task_set ID JSON"
            return True, json.dumps(result, ensure_ascii=False, sort_keys=True)
        except (PolicyUnavailable, PolicyConflict, PermissionError, ValueError, TypeError, KeyError) as exc:
            return False, str(exc)
