# SPDX-License-Identifier: MIT
"""Audit Logger & System Audit Provider (fail-soft standalone service)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__version__ = "1.0.0"
log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    timestamp: str
    category: str
    action: str
    status: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def log_audit_event(
    category: str,
    action: str,
    status: str = "ok",
    details: dict[str, Any] | None = None,
    log_file: Path | None = None,
) -> dict[str, Any]:
    """Fail-soft audit event logging, appendable to structured audit log."""
    now_iso = datetime.now(timezone.utc).isoformat()
    evt = AuditEvent(
        timestamp=now_iso,
        category=category,
        action=action,
        status=status,
        details=details or {},
    )
    res = evt.to_dict()

    if log_file:
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(res, ensure_ascii=False) + "\n")
        except Exception as exc:
            log.warning("Could not persist audit event to %s: %s", log_file, exc)

    return res


def audit_system_health(data_dir: Path | None = None) -> dict[str, Any]:
    """Fail-soft system audit checking directory, locks and status."""
    now_iso = datetime.now(timezone.utc).isoformat()
    locks_found: list[str] = []
    if data_dir and Path(data_dir).is_dir():
        try:
            for p in Path(data_dir).glob("*.lock"):
                locks_found.append(p.name)
            for p in Path(data_dir).glob("*.pid"):
                locks_found.append(p.name)
        except OSError:
            pass

    return {
        "status": "healthy",
        "provider": "audit_logger",
        "version": __version__,
        "timestamp": now_iso,
        "active_locks": locks_found,
        "lock_count": len(locks_found),
    }


def get_audit_summary() -> dict[str, Any]:
    """Return static summary for provider metadata."""
    return {
        "provider": "audit_logger",
        "version": __version__,
        "schema": "bach.audit-logger.v1",
        "supported_categories": ["system", "auth", "worker", "task", "quota"],
    }
