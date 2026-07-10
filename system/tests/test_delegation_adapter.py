# SPDX-License-Identifier: MIT
"""Regression tests for the BACH-to-clutch delegation adapter."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _clear_clutch_modules() -> None:
    for name in list(sys.modules):
        if name == "clutch" or name.startswith("clutch."):
            del sys.modules[name]


def _reload_delegation():
    _clear_clutch_modules()
    import hub._services.delegation as delegation

    return importlib.reload(delegation)


def test_external_clutch_path_can_supply_scorer(tmp_path, monkeypatch):
    pkg = tmp_path / "clutch"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "scorer.py").write_text(
        """
class ExternalScorer:
    def score(self, task):
        return 88, {"length": 8, "keywords": 80}

    def gang_level_fuer_score(self, score):
        return 5


def get_scorer():
    return ExternalScorer()
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("BACH_CLUTCH_PATH", str(tmp_path))
    monkeypatch.delenv("BACH_DISABLE_EXTERNAL_CLUTCH", raising=False)

    delegation = _reload_delegation()

    scorer = delegation.get_scorer()
    assert delegation.get_scorer_source() == "clutch"
    assert scorer.score("Migration pruefen")[0] == 88
    assert scorer.get_recommended_model(90) == "opus"


def test_external_clutch_path_can_supply_partner_registry(tmp_path, monkeypatch):
    pkg = tmp_path / "clutch"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "scorer.py").write_text(
        """
class ExternalScorer:
    def score(self, task):
        return 88, {"length": 8, "keywords": 80}

    def gang_level_fuer_score(self, score):
        return 5


def get_scorer():
    return ExternalScorer()
""".lstrip(),
        encoding="utf-8",
    )
    (pkg / "partner.py").write_text(
        """
class Partner:
    def __init__(self, name, typ="external_ai", cost_tier="medium", endpoint=None,
                 capabilities=None, success_rate=1.0, priority=50, verfuegbar=True):
        self.name = name
        self.typ = typ
        self.cost_tier = cost_tier
        self.endpoint = endpoint
        self.capabilities = list(capabilities or [])
        self.success_rate = success_rate
        self.priority = priority
        self.verfuegbar = verfuegbar


class PartnerRegistry:
    def __init__(self, partner=None):
        self._partner = list(partner or [])

    def erlaubt_in_zone(self, partner, zone):
        if zone >= 3 and partner.typ == "external_ai":
            return False
        return True

    def empfehle(self, zone=1, zweck=None):
        kandidaten = [
            partner for partner in self._partner
            if partner.verfuegbar and self.erlaubt_in_zone(partner, zone)
        ]
        if not kandidaten:
            return None
        if zweck:
            matches = [partner for partner in kandidaten if zweck in partner.capabilities]
            if matches:
                kandidaten = matches
        return max(kandidaten, key=lambda partner: partner.priority * partner.success_rate)
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("BACH_CLUTCH_PATH", str(tmp_path))
    monkeypatch.delenv("BACH_DISABLE_EXTERNAL_CLUTCH", raising=False)

    delegation = _reload_delegation()

    registry = delegation.build_partner_registry(
        [
            {
                "name": "Claude",
                "type": "external_ai",
                "token_cost": "high",
                "capabilities": ["coding"],
                "priority": 90,
                "success_rate": 1.0,
                "status": "active",
                "delegation_zones": [1, 2, 3, 4],
                "config": {"api_endpoint": "https://api.anthropic.com"},
            },
            {
                "name": "Ollama",
                "type": "local_ai",
                "token_cost": "free",
                "capabilities": ["bulk"],
                "priority": 40,
                "success_rate": 1.0,
                "status": "active",
                "delegation_zones": [1, 2, 3, 4],
                "config": {},
            },
        ]
    )

    assert delegation.get_partner_registry_source() == "clutch"
    assert registry.erlaubt_in_zone("Claude", 1) is True
    assert registry.erlaubt_in_zone("Claude", 3) is False
    assert registry.empfehle(3, purpose="bulk")["name"] == "Ollama"


def test_component_sources_show_external_and_legacy_boundaries(tmp_path, monkeypatch):
    pkg = tmp_path / "clutch"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "scorer.py").write_text(
        """
class ExternalScorer:
    def score(self, task):
        return 72, {}

    def gang_level_fuer_score(self, score):
        return 4


def get_scorer():
    return ExternalScorer()
""".lstrip(),
        encoding="utf-8",
    )
    (pkg / "partner.py").write_text(
        """
class Partner:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class PartnerRegistry:
    def __init__(self, partner=None):
        self.partner = list(partner or [])
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("BACH_CLUTCH_PATH", str(tmp_path))
    monkeypatch.delenv("BACH_DISABLE_EXTERNAL_CLUTCH", raising=False)

    delegation = _reload_delegation()

    assert delegation.get_component_sources() == {
        "external_clutch": "available",
        "scorer": "clutch",
        "partner_registry": "clutch",
        "streckenanalyse": "legacy",
        "gas_bremse": "legacy",
        "bordcomputer": "legacy",
        "fahrschule": "legacy",
        "fahrtenbuch": "legacy",
    }


def test_external_clutch_can_be_disabled(monkeypatch):
    monkeypatch.setenv("BACH_DISABLE_EXTERNAL_CLUTCH", "1")
    monkeypatch.delenv("BACH_CLUTCH_PATH", raising=False)

    delegation = _reload_delegation()

    assert delegation.get_scorer_source() == "legacy"
    assert delegation.get_partner_registry_source() == "legacy"
