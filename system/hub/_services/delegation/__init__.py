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

_CLUTCH_PATH_ENV = "BACH_CLUTCH_PATH"
_DISABLE_EXTERNAL_CLUTCH_ENV = "BACH_DISABLE_EXTERNAL_CLUTCH"


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


__all__ = [
    "SCORER_SOURCE",
    "analysiere_task",
    "berechne_gas",
    "get_analyser",
    "get_bordcomputer",
    "get_fahrschule",
    "get_fahrtenbuch",
    "get_gas_bremse",
    "get_scorer",
    "get_scorer_source",
]
