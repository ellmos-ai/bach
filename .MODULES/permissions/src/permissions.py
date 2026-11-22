# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Standalone Module: permissions
=================================
Self-contained permission policy evaluation and Claude settings allow/deny rule manager.
Zero coupling to BACH core DB or hub handlers.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DANGEROUS_PATTERNS = (
    "rm -rf",
    "del /f /s /q",
    "format ",
    "mkfs",
    "shutdown",
    "reboot",
    ":(){:|:&};:",
)


@dataclass
class PermissionDecision:
    allowed: bool
    reason: str
    matched_rule: Optional[str] = None
    action: str = ""


@dataclass
class PermissionPolicy:
    """Evaluates allow/deny rules with fail-closed deny precedence."""

    allow_rules: List[str] = field(default_factory=list)
    deny_rules: List[str] = field(default_factory=list)
    default_allow: bool = False

    def evaluate(self, action: str) -> PermissionDecision:
        normalized = str(action or "").strip()
        if not normalized:
            return PermissionDecision(allowed=False, reason="empty_action", action=normalized)

        low = normalized.lower()
        for pat in DANGEROUS_PATTERNS:
            if pat in low:
                return PermissionDecision(
                    allowed=False,
                    reason="dangerous_builtin_block",
                    matched_rule=pat,
                    action=normalized,
                )

        for rule in self.deny_rules:
            if self._matches(rule, normalized):
                return PermissionDecision(
                    allowed=False,
                    reason="explicit_deny",
                    matched_rule=rule,
                    action=normalized,
                )

        for rule in self.allow_rules:
            if self._matches(rule, normalized):
                return PermissionDecision(
                    allowed=True,
                    reason="explicit_allow",
                    matched_rule=rule,
                    action=normalized,
                )

        if self.default_allow:
            return PermissionDecision(allowed=True, reason="default_allow", action=normalized)
        return PermissionDecision(allowed=False, reason="default_deny", action=normalized)

    @staticmethod
    def _matches(rule: str, action: str) -> bool:
        r = str(rule or "").strip()
        if not r:
            return False
        if r == action:
            return True
        if "*" in r or "?" in r:
            return fnmatch.fnmatchcase(action, r)
        if r.endswith(":*") and action.startswith(r[:-1]):
            return True
        return False


def normalize_rules(rules: Iterable[str]) -> List[str]:
    """Deduplicate and preserve order of normalized permission rule strings."""
    seen = set()
    cleaned: List[str] = []
    for raw in rules:
        item = str(raw or "").strip()
        if item and item not in seen:
            seen.add(item)
            cleaned.append(item)
    return cleaned


def merge_settings_permissions(
    settings_path: Path | str,
    allow_add: Iterable[str] = (),
    deny_add: Iterable[str] = (),
    *,
    write: bool = True,
) -> Dict[str, Any]:
    """Load, merge, normalize and optionally persist Claude-style permissions JSON."""
    target = Path(settings_path)
    data: Dict[str, Any] = {}
    if target.is_file():
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}

    perms = dict(data.get("permissions") or {})
    perms["allow"] = normalize_rules(list(perms.get("allow") or []) + list(allow_add))
    perms["deny"] = normalize_rules(list(perms.get("deny") or []) + list(deny_add))
    data["permissions"] = perms

    if write:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data
