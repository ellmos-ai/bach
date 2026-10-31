# SPDX-License-Identifier: MIT
"""Shared runtime registry for BACH/Ocean skills (module `skill-registry`).

Pure stdlib-only registry core: ID/revision/locale patterns, pin validation,
binding-state computation and SkillRecord registration. This module performs NO
filesystem access, no catalog scanning and keeps no path defaults; those
concerns stay with the consuming adapters (BACH: skill_source_service.py,
Ocean: its own adapter). Task #2449.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "SKILL_ID_PATTERN",
    "REVISION_PATTERN",
    "LOCALE_PATTERN",
    "SkillRecord",
    "SkillRegistryError",
    "SkillRegistry",
    "validate_skill_pins",
    "skill_binding_states",
]

SKILL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
REVISION_PATTERN = re.compile(r"^[a-f0-9]{64}$")
LOCALE_PATTERN = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")

MAX_PINS = 30
_PIN_KEYS = {"id", "source_version", "version"}


@dataclass
class SkillRecord:
    """Registry entry for one skill; one active record per skill ID."""

    id: str
    version: str
    locale: str | None = None
    source: str | None = None
    name: str | None = None
    category: str | None = None
    symbol: str | None = None
    source_version: str | None = None
    evidence_type: str | None = None
    source_kind: str | None = None


class SkillRegistryError(Exception):
    """Registry invariant violated; the operation is refused (fail-closed)."""


class SkillRegistry:
    """In-memory runtime registry; all mutation paths validate fail-closed."""

    def __init__(self) -> None:
        self._records: dict[str, SkillRecord] = {}

    def register(self, record: SkillRecord) -> SkillRecord:
        """Register a record; re-registering an ID replaces its active record."""
        if not isinstance(record, SkillRecord):
            raise SkillRegistryError("SkillRegistry.register erwartet SkillRecord")
        if not isinstance(record.id, str) or not SKILL_ID_PATTERN.fullmatch(record.id):
            raise SkillRegistryError("Ungültige Skill-ID")
        if not isinstance(record.version, str) or not record.version:
            raise SkillRegistryError("Skill benötigt eine Version")
        if record.locale is not None and (not isinstance(record.locale, str)
                                          or not LOCALE_PATTERN.fullmatch(record.locale)):
            raise SkillRegistryError("Ungültiges Locale")
        if record.source_version is not None and (not isinstance(record.source_version, str)
                                                  or not REVISION_PATTERN.fullmatch(record.source_version)):
            raise SkillRegistryError("Ungültige Quellversion")
        for field in ("source", "name", "category", "symbol", "evidence_type", "source_kind"):
            value = getattr(record, field)
            if value is not None and not isinstance(value, str):
                raise SkillRegistryError("Ungültige Skill-Metadaten")
        self._records[record.id] = record
        return record

    def get(self, record_id: str) -> SkillRecord:
        if not isinstance(record_id, str) or not SKILL_ID_PATTERN.fullmatch(record_id):
            raise SkillRegistryError("Ungültige Skill-ID")
        if record_id not in self._records:
            raise SkillRegistryError("Skill nicht registriert: " + record_id)
        return self._records[record_id]

    def list(self) -> list[SkillRecord]:
        return [self._records[key] for key in sorted(self._records)]

    def remove(self, record_id: str) -> None:
        if not isinstance(record_id, str) or not SKILL_ID_PATTERN.fullmatch(record_id):
            raise SkillRegistryError("Ungültige Skill-ID")
        if record_id not in self._records:
            raise SkillRegistryError("Skill nicht registriert: " + record_id)
        del self._records[record_id]

    def __contains__(self, record_id: object) -> bool:
        return isinstance(record_id, str) and record_id in self._records

    def __len__(self) -> int:
        return len(self._records)


def validate_skill_pins(pins: list[dict]) -> list[dict]:
    """Validate saved pin metadata without requiring its source to remain current.

    Pure structural check: a list of at most 30 dicts with exactly the keys
    id/source_version/version, a full-matching SKILL_ID_PATTERN id, a
    full-matching REVISION_PATTERN source_version and no duplicate ids.
    Returns copies of the pins; raises ValueError otherwise (fail-closed).
    """
    if not isinstance(pins, list) or len(pins) > MAX_PINS:
        raise ValueError("Ungültige Skill-Bindung")
    seen = set()
    for pin in pins:
        if (not isinstance(pin, dict) or set(pin) != _PIN_KEYS
                or not isinstance(pin["id"], str) or not SKILL_ID_PATTERN.fullmatch(pin["id"])
                or not isinstance(pin["source_version"], str) or not REVISION_PATTERN.fullmatch(pin["source_version"])
                or not isinstance(pin["version"], str) or pin["id"] in seen):
            raise ValueError("Skill benötigt eine gültige Quellenversion")
        seen.add(pin["id"])
    return [dict(pin) for pin in pins]


def skill_binding_states(refs: list[dict], catalog: dict | None = None) -> list[dict]:
    """Compute binding states for validated refs against a catalog mapping.

    Pure dict comparison; no filesystem access. `catalog` maps a skill ID to a
    mapping with at least `source_version`; None means the catalog is
    unavailable. States: unavailable/missing/current/source_changed.
    """
    if not isinstance(refs, list):
        raise ValueError("Ungültige Skill-Bindung")
    if catalog is not None and not isinstance(catalog, dict):
        raise SkillRegistryError("Katalog muss ein Mapping oder None sein")
    return [{"id": pin["id"], "source_version": pin["source_version"], "state":
             "unavailable" if catalog is None else "missing" if pin["id"] not in catalog else
             "current" if catalog[pin["id"]]["source_version"] == pin["source_version"] else "source_changed"}
            for pin in refs]