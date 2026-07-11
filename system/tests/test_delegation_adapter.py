# SPDX-License-Identifier: MIT
"""Regression tests for the BACH-to-clutch delegation adapter."""

from __future__ import annotations

import importlib
import sqlite3
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


def test_external_clutch_data_bridge_keeps_bach_signature_and_db(tmp_path, monkeypatch):
    pkg = tmp_path / "clutch"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "fahrtenbuch.py").write_text(
        """
import sqlite3
from dataclasses import dataclass


@dataclass
class FahrtEintrag:
    fahrt_id: str
    strecken_typ: str
    gang: str
    provider: str
    gas: float
    muster: str
    total_tokens: int = 0
    thinking_tokens: int = 0
    tool_calls: int = 0
    files_read: int = 0
    files_changed: int = 0
    latenz_sekunden: float = 0.0
    erfolg: bool = True
    wiederholungen: int = 0
    user_korrekturen: int = 0
    fehler_anzahl: int = 0
    ist_erkundung: bool = False
    entscheidungs_grund: str = ""
    timestamp: float = 0.0


class Fahrtenbuch:
    def __init__(self, db_path=None):
        self.db_path = db_path
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS fahrten ("
                "fahrt_id TEXT PRIMARY KEY, strecken_typ TEXT, gang TEXT, "
                "provider TEXT, gas REAL, muster TEXT, total_tokens INTEGER, "
                "latenz_sekunden REAL, erfolg INTEGER, timestamp REAL)"
            )

    def eintragen(self, eintrag):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO fahrten VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    eintrag.fahrt_id,
                    eintrag.strecken_typ,
                    eintrag.gang,
                    eintrag.provider,
                    eintrag.gas,
                    eintrag.muster,
                    eintrag.total_tokens,
                    eintrag.latenz_sekunden,
                    1 if eintrag.erfolg else 0,
                    eintrag.timestamp,
                ),
            )

    def gesamte_fahrten(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            return conn.execute("SELECT COUNT(*) FROM fahrten").fetchone()[0]
""".lstrip(),
        encoding="utf-8",
    )
    (pkg / "fahrschule.py").write_text(
        """
class Fahrschule:
    def __init__(self, buch, kupplung, config_dir=None):
        self.buch = buch
        self.kupplung = kupplung
        self.erkundungsrate = 0.1
        self.min_fahrten = 200

    def trainieren(self):
        return {
            "phase": "sammeln",
            "gesamte_fahrten": self.buch.gesamte_fahrten(),
            "updates": [],
            "erkundungsrate": self.erkundungsrate,
        }
""".lstrip(),
        encoding="utf-8",
    )
    (pkg / "getriebe.py").write_text(
        "class Getriebe:\n    pass\n",
        encoding="utf-8",
    )
    (pkg / "kupplung.py").write_text(
        """
class Kupplung:
    def __init__(self, getriebe, config_dir=None):
        self.getriebe = getriebe

    def override(self, strecken_typ, config):
        pass

    def set_erkundungsrate(self, rate):
        self.erkundungsrate = rate
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("BACH_CLUTCH_PATH", str(tmp_path))
    monkeypatch.delenv("BACH_DISABLE_EXTERNAL_CLUTCH", raising=False)

    delegation = _reload_delegation()
    db_path = tmp_path / "bach.db"

    sources = delegation.get_component_sources()
    assert sources["fahrtenbuch"] == "clutch"
    assert sources["fahrschule"] == "clutch"

    fahrtenbuch = delegation.get_fahrtenbuch(db_path=db_path)
    assert fahrtenbuch.source == "clutch"
    entry = fahrtenbuch.eintrag(
        task_text="Datenbruecke testen",
        provider="Claude",
        model="claude-sonnet",
        strecken_typ="bundesstrasse",
        strecken_typ_code=3,
        schwierigkeit=2,
        etappen=1,
        gas_level=60,
        gas_strategie="ausgewogen",
        token_budget_faktor=1.2,
        tokens_input=10,
        tokens_output=20,
        latenz_sekunden=1.5,
        erfolg=True,
        zone=2,
    )
    assert entry.provider == "Claude"

    metrics = fahrtenbuch.metriken(tage=7)
    assert metrics["total_delegations"] == 1
    assert metrics["total_tokens"] == 30
    assert metrics["provider"][0]["name"] == "Claude"

    with sqlite3.connect(str(db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM fahrten").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM clutch_fahrtenbuch").fetchone()[0] == 1

    fahrschule = delegation.get_fahrschule(db_path=db_path)
    assert fahrschule.source == "clutch"
    assert fahrschule.trainieren()["gesamte_fahrten"] == 1
    status = fahrschule.status()
    assert status["total_kombinationen"] == 1
    assert status["top_5"][0]["model"] == "claude-sonnet"
    assert "claude-sonnet" in fahrschule.format_status()


def test_external_clutch_can_be_disabled(monkeypatch):
    monkeypatch.setenv("BACH_DISABLE_EXTERNAL_CLUTCH", "1")
    monkeypatch.delenv("BACH_CLUTCH_PATH", raising=False)

    delegation = _reload_delegation()

    assert delegation.get_scorer_source() == "legacy"
    assert delegation.get_partner_registry_source() == "legacy"
