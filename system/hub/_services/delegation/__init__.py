#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Compat-Layer fuer die schrittweise clutch-Migration.

Ziel:
- BACH importiert Delegations-Bausteine ueber genau einen Einstiegspunkt.
- Der externe clutch-Scorer wird bevorzugt, weil er bereits die
  provider-neutrale Quelle der Wahrheit ist.
- Die restlichen clutch-bridge-Bausteine bleiben vorerst auf den
  BACH-internen Modulen, bis ihre DB-/API-Vertraege voll abgeglichen sind.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any

from .bordcomputer import get_bordcomputer
from .fahrtenbuch import get_fahrtenbuch
from .fahrschule import get_fahrschule
from .gas_bremse import berechne_gas, get_gas_bremse
from .strecken_analyse import analysiere_task, get_analyser

SCORER_SOURCE = "legacy"
PARTNER_REGISTRY_SOURCE = "legacy"

_CLUTCH_PATH_ENV = "BACH_CLUTCH_PATH"
_DISABLE_EXTERNAL_CLUTCH_ENV = "BACH_DISABLE_EXTERNAL_CLUTCH"
_PARTNER_ZONE_RULES = {
    1: {"typen": {"external_ai", "local_ai", "human"}, "max_cost": {"low", "medium", "high", "free"}},
    2: {"typen": {"external_ai", "local_ai", "human"}, "max_cost": {"low", "medium", "free"}},
    3: {"typen": {"local_ai", "human"}, "max_cost": {"low", "free"}},
    4: {"typen": {"human"}, "max_cost": {"free"}},
}


def _external_clutch_disabled() -> bool:
    value = os.environ.get(_DISABLE_EXTERNAL_CLUTCH_ENV, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _normalise_clutch_root(raw_path: str | os.PathLike[str]) -> Path | None:
    path = Path(os.path.expandvars(os.path.expanduser(str(raw_path)))).resolve()
    if (path / "clutch" / "scorer.py").is_file():
        return path
    return None


def _candidate_clutch_roots() -> list[Path]:
    candidates: list[Path] = []

    env_value = os.environ.get(_CLUTCH_PATH_ENV)
    if env_value:
        candidates.extend(Path(part) for part in env_value.split(os.pathsep) if part.strip())

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates.append(parent / ".MODULES" / "clutch")

    return candidates


def _ensure_external_clutch_on_path() -> Path | None:
    for candidate in _candidate_clutch_roots():
        root = _normalise_clutch_root(candidate)
        if root is None:
            continue

        root_str = str(root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
        return root
    return None


def _load_external_clutch_scorer():
    if _external_clutch_disabled():
        return None

    if os.environ.get(_CLUTCH_PATH_ENV):
        _ensure_external_clutch_on_path()
        importlib.invalidate_caches()

    try:
        return importlib.import_module("clutch.scorer").get_scorer
    except ImportError:
        pass

    if _ensure_external_clutch_on_path() is None:
        return None

    importlib.invalidate_caches()
    try:
        return importlib.import_module("clutch.scorer").get_scorer
    except ImportError:
        return None


_get_clutch_scorer = _load_external_clutch_scorer()


def _load_external_clutch_partner_module():
    if _external_clutch_disabled():
        return None

    if os.environ.get(_CLUTCH_PATH_ENV):
        _ensure_external_clutch_on_path()
        importlib.invalidate_caches()

    try:
        return importlib.import_module("clutch.partner")
    except ImportError:
        pass

    if _ensure_external_clutch_on_path() is None:
        return None

    importlib.invalidate_caches()
    try:
        return importlib.import_module("clutch.partner")
    except ImportError:
        return None


_clutch_partner_module = _load_external_clutch_partner_module()

from .complexity_scorer import get_scorer as _get_legacy_scorer


class _ScorerAdapter:
    """Gleicht clutch.scorer an die bestehende BACH-Signatur an."""

    def __init__(self, scorer: Any, source: str):
        self._scorer = scorer
        self.source = source

    def score(self, task_description: str):
        return self._scorer.score(task_description)

    def get_recommended_model(self, score: int) -> str:
        if hasattr(self._scorer, "get_recommended_model"):
            return self._scorer.get_recommended_model(score)

        level = self._scorer.gang_level_fuer_score(score)
        if level <= 2:
            return "haiku"
        if level <= 4:
            return "sonnet"
        return "opus"

    def get_partner_recommendation(self, score: int, zone: int) -> dict[str, Any]:
        if hasattr(self._scorer, "get_partner_recommendation"):
            return self._scorer.get_partner_recommendation(score, zone)

        model = self.get_recommended_model(score)
        if model == "opus":
            cost_tier = "high"
        elif model == "sonnet":
            cost_tier = "medium"
        else:
            cost_tier = "low"

        return {
            "model": model,
            "score": score,
            "zone": zone,
            "cost_tier": cost_tier,
        }


def _partner_name_key(name: str) -> str:
    return str(name or "").strip().lower()


def _normalise_partner_type(partner_type: str) -> str:
    value = str(partner_type or "external_ai").strip().lower()
    if value in {"api", "external_ai"}:
        return "external_ai"
    if value in {"local", "local_ai"}:
        return "local_ai"
    if value == "human":
        return "human"
    return "external_ai"


def _normalise_partner_cost(cost_tier: str) -> str:
    value = str(cost_tier or "medium").strip().lower()
    if value == "none":
        return "free"
    if value in {"free", "low", "medium", "high"}:
        return value
    return "medium"


def _normalise_zone(zone: int | str) -> int:
    try:
        zone_num = int(str(zone).replace("zone_", ""))
    except (TypeError, ValueError):
        zone_num = 4
    return max(1, min(4, zone_num))


class _PartnerRegistryAdapter:
    """Legt BACH-Partnerdaten auf clutchs PartnerRegistry-API ab."""

    def __init__(
        self,
        partners: list[dict[str, Any]],
        registry: Any | None,
        partner_objects: dict[str, Any] | None = None,
        source: str = "legacy",
    ):
        self._partners = {
            _partner_name_key(partner.get("name", "")): dict(partner)
            for partner in partners
        }
        self._registry = registry
        self._partner_objects = partner_objects or {}
        self.source = source

    def get(self, name: str) -> dict[str, Any] | None:
        return self._partners.get(_partner_name_key(name))

    def alle(self) -> list[dict[str, Any]]:
        return list(self._partners.values())

    def verfuegbare(self) -> list[dict[str, Any]]:
        return [partner for partner in self.alle() if partner.get("status") == "active"]

    def erlaubt_in_zone(
        self,
        partner: dict[str, Any] | str,
        zone: int | str,
        allowed_partner_names: list[str] | None = None,
    ) -> bool:
        partner_data = partner if isinstance(partner, dict) else self.get(partner)
        if partner_data is None or partner_data.get("status") != "active":
            return False

        zone_num = _normalise_zone(zone)

        explicit_zones = partner_data.get("delegation_zones") or []
        if explicit_zones:
            try:
                if zone_num not in {int(value) for value in explicit_zones}:
                    return False
            except (TypeError, ValueError):
                pass

        if allowed_partner_names:
            allowed_keys = {
                _partner_name_key(name)
                for name in allowed_partner_names
                if str(name).strip()
            }
            if allowed_keys and _partner_name_key(partner_data.get("name", "")) not in allowed_keys:
                return False

        partner_key = _partner_name_key(partner_data.get("name", ""))
        partner_object = self._partner_objects.get(partner_key)
        if self._registry is not None and partner_object is not None:
            return bool(self._registry.erlaubt_in_zone(partner_object, zone_num))

        zone_rule = _PARTNER_ZONE_RULES.get(zone_num, _PARTNER_ZONE_RULES[4])
        partner_type = _normalise_partner_type(partner_data.get("type", "external_ai"))
        partner_cost = _normalise_partner_cost(partner_data.get("token_cost", "medium"))
        return partner_type in zone_rule["typen"] and partner_cost in zone_rule["max_cost"]

    def verfuegbare_in_zone(
        self,
        zone: int | str,
        allowed_partner_names: list[str] | None = None,
        excluded_names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        excluded_keys = {
            _partner_name_key(name)
            for name in (excluded_names or [])
            if str(name).strip()
        }
        candidates: list[dict[str, Any]] = []
        for partner in self.verfuegbare():
            if not self.erlaubt_in_zone(partner, zone, allowed_partner_names=allowed_partner_names):
                continue
            if _partner_name_key(partner.get("name", "")) in excluded_keys:
                continue
            candidates.append(partner)
        return candidates

    def empfehle(
        self,
        zone: int | str,
        purpose: str | None = None,
        allowed_partner_names: list[str] | None = None,
        excluded_names: list[str] | None = None,
    ) -> dict[str, Any] | None:
        candidates = self.verfuegbare_in_zone(
            zone,
            allowed_partner_names=allowed_partner_names,
            excluded_names=excluded_names,
        )
        if not candidates:
            return None

        if self._registry is not None:
            partner_objects = [
                self._partner_objects[_partner_name_key(partner.get("name", ""))]
                for partner in candidates
                if _partner_name_key(partner.get("name", "")) in self._partner_objects
            ]
            if partner_objects:
                filtered_registry = self._registry.__class__(partner_objects)
                chosen = filtered_registry.empfehle(
                    zone=_normalise_zone(zone),
                    zweck=purpose,
                )
                if chosen is not None:
                    return self.get(getattr(chosen, "name", ""))

        purpose_key = str(purpose or "").strip().lower()

        def rank_key(partner: dict[str, Any]) -> tuple[int, float]:
            capabilities = [
                str(capability).strip().lower()
                for capability in partner.get("capabilities", [])
            ]
            capability_match = 1 if purpose_key and purpose_key in capabilities else 0
            priority = float(partner.get("priority", 50) or 50)
            success_rate = float(partner.get("success_rate", 1.0) or 0.0)
            return capability_match, priority * success_rate

        return max(candidates, key=rank_key)


def build_partner_registry(partners: list[dict[str, Any]]) -> _PartnerRegistryAdapter:
    """Erzeugt eine BACH-kompatible PartnerRegistry auf Basis von clutch."""

    global PARTNER_REGISTRY_SOURCE

    partner_snapshots = [dict(partner) for partner in partners]
    partner_module = _clutch_partner_module
    partner_cls = getattr(partner_module, "Partner", None) if partner_module else None
    registry_cls = getattr(partner_module, "PartnerRegistry", None) if partner_module else None

    if partner_cls is not None and registry_cls is not None:
        partner_objects: dict[str, Any] = {}
        registry_partners: list[Any] = []

        for partner in partner_snapshots:
            config = partner.get("config") if isinstance(partner.get("config"), dict) else {}
            partner_object = partner_cls(
                name=partner.get("name", ""),
                typ=_normalise_partner_type(partner.get("type", "external_ai")),
                cost_tier=_normalise_partner_cost(partner.get("token_cost", "medium")),
                endpoint=config.get("api_endpoint"),
                capabilities=list(partner.get("capabilities", [])),
                success_rate=float(partner.get("success_rate", 1.0) or 0.0),
                priority=int(partner.get("priority", 50) or 50),
                verfuegbar=partner.get("status") == "active",
            )
            partner_key = _partner_name_key(partner.get("name", ""))
            partner_objects[partner_key] = partner_object
            registry_partners.append(partner_object)

        PARTNER_REGISTRY_SOURCE = "clutch"
        return _PartnerRegistryAdapter(
            partner_snapshots,
            registry_cls(registry_partners),
            partner_objects,
            source=PARTNER_REGISTRY_SOURCE,
        )

    PARTNER_REGISTRY_SOURCE = "legacy"
    return _PartnerRegistryAdapter(partner_snapshots, None, source=PARTNER_REGISTRY_SOURCE)


_scorer_instance: _ScorerAdapter | None = None


def get_scorer() -> _ScorerAdapter:
    global _scorer_instance, SCORER_SOURCE
    if _scorer_instance is not None:
        return _scorer_instance

    if _get_clutch_scorer is not None:
        SCORER_SOURCE = "clutch"
        _scorer_instance = _ScorerAdapter(_get_clutch_scorer(), SCORER_SOURCE)
        return _scorer_instance

    SCORER_SOURCE = "legacy"
    _scorer_instance = _ScorerAdapter(_get_legacy_scorer(), SCORER_SOURCE)
    return _scorer_instance


def get_scorer_source() -> str:
    if _scorer_instance is None:
        get_scorer()
    if _scorer_instance is None:
        return SCORER_SOURCE
    return _scorer_instance.source


def get_partner_registry_source() -> str:
    return PARTNER_REGISTRY_SOURCE


__all__ = [
    "SCORER_SOURCE",
    "PARTNER_REGISTRY_SOURCE",
    "analysiere_task",
    "berechne_gas",
    "build_partner_registry",
    "get_analyser",
    "get_bordcomputer",
    "get_fahrschule",
    "get_fahrtenbuch",
    "get_gas_bremse",
    "get_partner_registry_source",
    "get_scorer",
    "get_scorer_source",
]
