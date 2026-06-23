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

from typing import Any

from .bordcomputer import get_bordcomputer
from .fahrtenbuch import get_fahrtenbuch
from .fahrschule import get_fahrschule
from .gas_bremse import berechne_gas, get_gas_bremse
from .strecken_analyse import analysiere_task, get_analyser

SCORER_SOURCE = "legacy"

try:
    from clutch.scorer import get_scorer as _get_clutch_scorer
except ImportError:
    _get_clutch_scorer = None

from .complexity_scorer import get_scorer as _get_legacy_scorer


class _ScorerAdapter:
    """Gleicht clutch.scorer an die bestehende BACH-Signatur an."""

    def __init__(self, scorer: Any):
        self._scorer = scorer

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
        _scorer_instance = _ScorerAdapter(_get_clutch_scorer())
        return _scorer_instance

    SCORER_SOURCE = "legacy"
    _scorer_instance = _ScorerAdapter(_get_legacy_scorer())
    return _scorer_instance


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
]
