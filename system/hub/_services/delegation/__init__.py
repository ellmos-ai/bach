#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Compat-Layer fuer die externe clutch-Anbindung.

Ziel:
- BACH importiert Delegations-Bausteine ueber genau einen Einstiegspunkt.
- Der externe clutch-Scorer wird bevorzugt, weil er bereits die
  provider-neutrale Quelle der Wahrheit ist.
- Der ehemalige BACH-Fork liegt nach gruenem Parallelbetrieb nur noch als
  archivierter Notfall-Fallback unter hub/_archive/delegation_legacy.
"""

from __future__ import annotations

import importlib
import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ..._archive.delegation_legacy.bordcomputer import (
    OverkillAlert as _LegacyOverkillAlert,
    TokenExplosionAlert as _LegacyTokenExplosionAlert,
    get_bordcomputer as _get_legacy_bordcomputer,
)
from ..._archive.delegation_legacy.fahrtenbuch import FahrtenbuchEintrag as _LegacyFahrtenbuchEintrag
from ..._archive.delegation_legacy.fahrtenbuch import get_fahrtenbuch as _get_legacy_fahrtenbuch
from ..._archive.delegation_legacy.fahrschule import get_fahrschule as _get_legacy_fahrschule
from ..._archive.delegation_legacy.gas_bremse import (
    GasStellung as _LegacyGasStellung,
    PromptStrategie as _LegacyPromptStrategie,
    berechne_gas as _legacy_berechne_gas,
    get_gas_bremse as _get_legacy_gas_bremse,
)
from ..._archive.delegation_legacy.strecken_analyse import (
    StreckenProfil as _LegacyStreckenProfil,
    analysiere_task as _legacy_analysiere_task,
    get_analyser as _get_legacy_analyser,
)

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
    package_dir = path / "clutch"
    if not package_dir.is_dir():
        return None
    known_modules = (
        "scorer.py",
        "partner.py",
        "fahrtenbuch.py",
        "fahrschule.py",
    )
    if any((package_dir / module).is_file() for module in known_modules):
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
        candidates.append(parent / ".MODULES" / ".ORCHESTRATION" / "clutch")

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


def _load_external_clutch_module(module_name: str):
    if _external_clutch_disabled():
        return None

    if os.environ.get(_CLUTCH_PATH_ENV):
        _ensure_external_clutch_on_path()
        importlib.invalidate_caches()

    try:
        return importlib.import_module(module_name)
    except ImportError:
        pass

    if _ensure_external_clutch_on_path() is None:
        return None

    importlib.invalidate_caches()
    try:
        return importlib.import_module(module_name)
    except ImportError:
        return None


_clutch_fahrtenbuch_module = _load_external_clutch_module("clutch.fahrtenbuch")
_clutch_fahrschule_module = _load_external_clutch_module("clutch.fahrschule")
_clutch_getriebe_module = _load_external_clutch_module("clutch.getriebe")
_clutch_kupplung_module = _load_external_clutch_module("clutch.kupplung")
_clutch_strecke_module = _load_external_clutch_module("clutch.strecke")
_clutch_gas_bremse_module = _load_external_clutch_module("clutch.gas_bremse")
_clutch_bordcomputer_module = _load_external_clutch_module("clutch.bordcomputer")

from ..._archive.delegation_legacy.complexity_scorer import get_scorer as _get_legacy_scorer


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


_EXTERNAL_STRECKEN_CODES = {
    "feldweg": 1,
    "landstrasse": 3,
    "bundesstrasse": 4,
    "autobahn": 6,
    "pruefstrecke": 4,
    "rallye": 9,
    "konvoi": 5,
    "teamfahrt": 6,
    "langstrecke": 10,
    "testfahrt": 6,
    "unbekannt": 4,
}

_EXTERNAL_STRECKEN_LABELS = {
    "feldweg": "Feldweg",
    "landstrasse": "Landstraße",
    "bundesstrasse": "Bundesstraße",
    "autobahn": "Autobahn",
    "pruefstrecke": "Prüfstrecke",
    "rallye": "Rallye",
    "konvoi": "Konvoi",
    "teamfahrt": "Teamfahrt",
    "langstrecke": "Langstrecke",
    "testfahrt": "Testfahrt",
    "unbekannt": "Unbekannt",
}

_EXTERNAL_TEMPO_LEVELS = {
    "gemuetlich": 2,
    "normal": 3,
    "eilig": 4,
}


def _external_streckenanalyse_ready() -> bool:
    return (
        _clutch_strecke_module is not None
        and getattr(_clutch_strecke_module, "StreckenAnalyse", None) is not None
    )


def _external_gas_bremse_ready() -> bool:
    return (
        _clutch_gas_bremse_module is not None
        and getattr(_clutch_gas_bremse_module, "GasBremse", None) is not None
    )


def _external_fahrtenbuch_ready() -> bool:
    return (
        _clutch_fahrtenbuch_module is not None
        and getattr(_clutch_fahrtenbuch_module, "Fahrtenbuch", None) is not None
        and getattr(_clutch_fahrtenbuch_module, "FahrtEintrag", None) is not None
    )


def _external_fahrschule_ready() -> bool:
    return (
        _external_fahrtenbuch_ready()
        and _clutch_fahrschule_module is not None
        and getattr(_clutch_fahrschule_module, "Fahrschule", None) is not None
        and _clutch_getriebe_module is not None
        and getattr(_clutch_getriebe_module, "Getriebe", None) is not None
        and _clutch_kupplung_module is not None
        and getattr(_clutch_kupplung_module, "Kupplung", None) is not None
    )


def _external_bordcomputer_ready() -> bool:
    return (
        _external_fahrtenbuch_ready()
        and _clutch_bordcomputer_module is not None
        and getattr(_clutch_bordcomputer_module, "Bordcomputer", None) is not None
    )


def _instance_key(db_path: str | os.PathLike[str] | None) -> str:
    if db_path is None:
        return "__memory__"
    return str(Path(db_path).expanduser().resolve())


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _canonical_bach_db_path() -> Path:
    try:
        from hub.bach_paths import BACH_DB

        return Path(BACH_DB).expanduser().resolve()
    except Exception:
        return (Path.home() / ".bach" / "bach.db").resolve()


class _StreckenAnalyseAdapter:
    """Legt clutch.strecke auf BACHs StreckenProfil-Schnittstelle ab."""

    source = "clutch"

    def __init__(self, analyser: Any):
        self._analyser = analyser

    def analysiere(
        self,
        task_beschreibung: str,
        kontext: dict[str, Any] | None = None,
    ) -> _LegacyStreckenProfil:
        profil = self._analyser.analysiere(task_beschreibung, kontext=kontext or None)
        typ_key = getattr(getattr(profil, "typ", None), "value", str(getattr(profil, "typ", "unbekannt")))
        typ_key = str(typ_key or "unbekannt").strip().lower()
        label = _EXTERNAL_STRECKEN_LABELS.get(typ_key, typ_key.title() or "Unbekannt")
        typ_code = _EXTERNAL_STRECKEN_CODES.get(typ_key, 4)
        tempo_key = getattr(getattr(profil, "tempo", None), "value", str(getattr(profil, "tempo", "normal")))
        tempo = _EXTERNAL_TEMPO_LEVELS.get(str(tempo_key or "normal").strip().lower(), 3)

        raw_schwierigkeit = _as_float(getattr(profil, "schwierigkeit", 0.5), 0.5)
        if raw_schwierigkeit > 1.0:
            raw_schwierigkeit = raw_schwierigkeit / 5.0
        schwierigkeit = max(1, min(5, int(round(1 + max(0.0, min(1.0, raw_schwierigkeit)) * 4))))
        etappen = max(1, _as_int(getattr(profil, "etappen", 1), 1))

        if typ_code <= 2 and schwierigkeit <= 2:
            empfohlener_gang = "haiku"
            budget_basis = 0.4
        elif typ_code >= 6 or schwierigkeit >= 4:
            empfohlener_gang = "opus"
            budget_basis = 1.6
        else:
            empfohlener_gang = "sonnet"
            budget_basis = 1.0

        token_budget_faktor = round(min(2.5, budget_basis + max(0, etappen - 1) * 0.15), 2)
        details = {
            "source": "clutch",
            "konfidenz": _as_float(getattr(profil, "konfidenz", 0.0), 0.0),
            "erkannte_keywords": list(getattr(profil, "erkannte_keywords", []) or []),
            "braucht_spezialisten": bool(getattr(profil, "braucht_spezialisten", False)),
            "ist_pipeline": bool(getattr(profil, "ist_pipeline", False)),
        }

        return _LegacyStreckenProfil(
            typ=label,
            typ_code=typ_code,
            tempo=tempo,
            schwierigkeit=schwierigkeit,
            etappen=etappen,
            beschreibung=f"{label} (clutch-kompatibel)",
            empfohlener_gang=empfohlener_gang,
            token_budget_faktor=token_budget_faktor,
            details=details,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._analyser, name)


class _GasBremseAdapter:
    """Legt clutch.gas_bremse auf BACHs Gas/Bremse-Schnittstelle ab."""

    source = "clutch"

    def __init__(self, gas_bremse: Any):
        self._gas_bremse = gas_bremse

    def berechne(
        self,
        gas_level: int | None = None,
        strecken_schwierigkeit: int | float | None = None,
        strecken_typ_code: int | None = None,
    ) -> _LegacyGasStellung:
        if gas_level is not None:
            gas = max(0.0, min(1.0, _as_float(gas_level, 50.0) / 100.0))
        else:
            raw_schwierigkeit = _as_float(strecken_schwierigkeit, 3.0)
            if raw_schwierigkeit > 1.0:
                raw_schwierigkeit = max(0.0, min(1.0, (raw_schwierigkeit - 1.0) / 4.0))
            gas = 0.2 + max(0.0, min(1.0, raw_schwierigkeit)) * 0.6
            if strecken_typ_code is not None and strecken_typ_code <= 2:
                gas = max(0.0, gas - 0.1)
            elif strecken_typ_code is not None and strecken_typ_code >= 9:
                gas = min(1.0, gas + 0.1)

        externe_stellung = self._gas_bremse.stellung(gas)
        strategie_key = str(getattr(externe_stellung, "prompt_strategie", "ausgewogen")).strip().lower()
        strategie = {
            "direkt": _LegacyPromptStrategie.DIREKT,
            "gruendlich": _LegacyPromptStrategie.GRUENDLICH,
            "gründlich": _LegacyPromptStrategie.GRUENDLICH,
        }.get(strategie_key, _LegacyPromptStrategie.AUSGEWOGEN)

        prompt_prefix = ""
        if hasattr(self._gas_bremse, "prompt_prefix"):
            prompt_prefix = str(self._gas_bremse.prompt_prefix(externe_stellung) or "")
        prompt_suffix = (
            "Validiere dein Ergebnis bevor du antwortest."
            if strategie is _LegacyPromptStrategie.GRUENDLICH
            else ""
        )

        return _LegacyGasStellung(
            level=max(0, min(100, int(round(_as_float(getattr(externe_stellung, "wert", gas), gas) * 100)))),
            strategie=strategie,
            token_multiplikator=_as_float(getattr(externe_stellung, "token_multiplikator", 1.0), 1.0),
            prompt_prefix=prompt_prefix,
            prompt_suffix=prompt_suffix,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._gas_bremse, name)


class _BordcomputerAdapter:
    """Legt clutch.bordcomputer auf BACHs Bordcomputer-Schnittstelle ab."""

    source = "clutch"

    def __init__(self, external_bordcomputer: Any):
        self._external = external_bordcomputer
        self._overkill_alerts: list[_LegacyOverkillAlert] = []
        self._token_alerts: list[_LegacyTokenExplosionAlert] = []

    def is_available(self, provider: str) -> bool:
        return bool(self._external.modell_verfuegbar(str(provider or "")))

    def check_overkill(
        self,
        task_beschreibung: str,
        gewaehltes_modell: str,
        strecken_typ: str = "",
        strecken_schwierigkeit: int = 0,
        empfohlener_gang: str = "",
    ) -> _LegacyOverkillAlert | None:
        modell_rang = {"haiku": 1, "sonnet": 2, "opus": 3}
        gewaehlt = modell_rang.get(str(gewaehltes_modell or "").strip().lower(), 0)
        empfohlen = modell_rang.get(str(empfohlener_gang or "").strip().lower(), 0)
        if gewaehlt > 0 and empfohlen > 0 and (gewaehlt - empfohlen) >= 2:
            alert = _LegacyOverkillAlert(
                timestamp=time.time(),
                task_beschreibung=task_beschreibung,
                strecken_typ=strecken_typ,
                strecken_schwierigkeit=_as_int(strecken_schwierigkeit),
                gewaehltes_modell=gewaehltes_modell,
                empfohlenes_modell=empfohlener_gang,
            )
            self._overkill_alerts.append(alert)
            self._overkill_alerts = self._overkill_alerts[-50:]
            return alert
        return None

    def check_token_explosion(
        self,
        provider: str,
        tokens_used: int,
        tokens_expected: int,
    ) -> _LegacyTokenExplosionAlert | None:
        if tokens_expected <= 0:
            return None

        factor = tokens_used / tokens_expected
        if factor > 3.0:
            alert = _LegacyTokenExplosionAlert(
                timestamp=time.time(),
                provider=provider,
                tokens_used=tokens_used,
                tokens_expected=tokens_expected,
                factor=factor,
            )
            self._token_alerts.append(alert)
            self._token_alerts = self._token_alerts[-50:]
            return alert
        return None

    def status(self) -> dict[str, Any]:
        try:
            health = self._external.pruefe()
        except TypeError:
            health = self._external.pruefe(0.0)

        circuits = {}
        for modell, circuit in getattr(self._external, "_circuits", {}).items():
            fehler = _as_int(getattr(circuit, "fehler_zaehler", 0))
            requests = max(1, fehler)
            circuits[str(modell)] = {
                "name": getattr(circuit, "modell", modell),
                "state": str(getattr(circuit, "zustand", "closed")),
                "failure_count": fehler,
                "success_count": 0,
                "total_requests": requests,
                "total_failures": fehler,
                "failure_rate": round(fehler / requests * 100, 1),
            }

        return {
            "circuits": circuits,
            "overkill_alerts": len(self._overkill_alerts),
            "token_alerts": len(self._token_alerts),
            "recent_overkill": [alert.to_dict() for alert in self._overkill_alerts[-5:]],
            "recent_token_alerts": [alert.to_dict() for alert in self._token_alerts[-5:]],
            "gesund": bool(getattr(health, "gesund", True)),
            "warnungen": list(getattr(health, "warnungen", []) or []),
            "gesperrte_modelle": list(getattr(health, "gesperrte_modelle", []) or []),
            "budget_zone": str(getattr(health, "budget_zone", "green")),
        }

    def format_status(self) -> str:
        status = self.status()
        lines = ["[BORDCOMPUTER] Health-Monitor Status", "=" * 50]

        if not status["circuits"]:
            lines.append("  Keine Provider registriert.")
        else:
            lines.append("")
            lines.append("  Provider-Status:")
            for name, info in status["circuits"].items():
                state_icon = {"closed": "✓", "half_open": "~", "open": "✗"}.get(info["state"], "?")
                lines.append(
                    f"    [{state_icon}] {name}: {info['state']} "
                    f"(Fehler: {info['failure_count']}, Rate: {info['failure_rate']}%)"
                )

        if status["overkill_alerts"] > 0:
            lines.append(f"\n  Overkill-Alerts: {status['overkill_alerts']}")
            for alert in status["recent_overkill"]:
                lines.append(
                    f"    ! {alert['strecke']}: {alert['gewaehlt']} statt {alert['empfohlen']}"
                )

        if status["token_alerts"] > 0:
            lines.append(f"\n  Token-Explosions: {status['token_alerts']}")
            for alert in status["recent_token_alerts"]:
                lines.append(
                    f"    ! {alert['provider']}: {alert['factor']}x Budget "
                    f"({alert['tokens_used']}/{alert['tokens_expected']})"
                )

        if status.get("warnungen"):
            lines.append("\n  Warnungen:")
            for warning in status["warnungen"]:
                lines.append(f"    ! {warning}")

        return "\n".join(lines)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._external, name)


class _FahrtenbuchAdapter:
    """BACH-Signatur auf externe clutch.Fahrtenbuch-API legen."""

    source = "clutch"

    def __init__(self, db_path: Path, external_buch: Any, entry_cls: Any):
        self.db_path = db_path
        self._external = external_buch
        self._entry_cls = entry_cls

    @property
    def external(self) -> Any:
        return self._external

    def eintrag(
        self,
        task_text: str,
        provider: str,
        model: str = "",
        strecken_typ: str = "",
        strecken_typ_code: int = 0,
        schwierigkeit: int = 0,
        etappen: int = 0,
        gas_level: int = 50,
        gas_strategie: str = "ausgewogen",
        token_budget_faktor: float = 1.0,
        tokens_input: int = 0,
        tokens_output: int = 0,
        latenz_sekunden: float = 0.0,
        erfolg: bool = True,
        zone: int = 1,
        kosten_eur: float = 0.0,
    ) -> _LegacyFahrtenbuchEintrag:
        timestamp = time.time()
        gas_level_int = max(0, min(100, _as_int(gas_level, 50)))
        total_tokens = max(0, _as_int(tokens_input) + _as_int(tokens_output))
        strecke = str(strecken_typ or strecken_typ_code or "unbekannt")
        gang = str(model or provider or "unknown")

        external_entry = self._entry_cls(
            fahrt_id=f"bach-{int(timestamp * 1000)}-{uuid.uuid4().hex[:8]}",
            strecken_typ=strecke,
            gang=gang,
            provider=str(provider or ""),
            gas=gas_level_int / 100.0,
            muster="einzelfahrt",
            total_tokens=total_tokens,
            latenz_sekunden=_as_float(latenz_sekunden),
            erfolg=bool(erfolg),
            entscheidungs_grund=str(task_text or "")[:200],
            timestamp=timestamp,
        )
        self._external.eintragen(external_entry)

        legacy_entry = _LegacyFahrtenbuchEintrag(
            timestamp=timestamp,
            task_text=str(task_text or "")[:200],
            provider=str(provider or ""),
            model=gang,
            strecken_typ=strecke,
            strecken_typ_code=_as_int(strecken_typ_code),
            schwierigkeit=_as_int(schwierigkeit),
            etappen=_as_int(etappen),
            gas_level=gas_level_int,
            gas_strategie=str(gas_strategie or "ausgewogen"),
            token_budget_faktor=_as_float(token_budget_faktor, 1.0),
            tokens_input=_as_int(tokens_input),
            tokens_output=_as_int(tokens_output),
            latenz_sekunden=_as_float(latenz_sekunden),
            erfolg=bool(erfolg),
            zone=_as_int(zone, 1),
            kosten_eur=_as_float(kosten_eur),
        )
        self._persist_bach_compat(legacy_entry)
        return legacy_entry

    def _persist_bach_compat(self, entry: _LegacyFahrtenbuchEintrag) -> None:
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS clutch_fahrtenbuch (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL NOT NULL,
                        task_text TEXT,
                        provider TEXT,
                        model TEXT,
                        strecken_typ TEXT,
                        strecken_typ_code INTEGER,
                        schwierigkeit INTEGER,
                        etappen INTEGER,
                        gas_level INTEGER,
                        gas_strategie TEXT,
                        token_budget_faktor REAL,
                        tokens_input INTEGER DEFAULT 0,
                        tokens_output INTEGER DEFAULT 0,
                        latenz_sekunden REAL DEFAULT 0,
                        erfolg INTEGER DEFAULT 1,
                        zone INTEGER DEFAULT 1,
                        kosten_eur REAL DEFAULT 0
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_fahrtenbuch_provider "
                    "ON clutch_fahrtenbuch(provider)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_fahrtenbuch_strecke "
                    "ON clutch_fahrtenbuch(strecken_typ_code)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_fahrtenbuch_time "
                    "ON clutch_fahrtenbuch(timestamp)"
                )
                conn.execute(
                    """
                    INSERT INTO clutch_fahrtenbuch
                        (timestamp, task_text, provider, model,
                         strecken_typ, strecken_typ_code, schwierigkeit, etappen,
                         gas_level, gas_strategie, token_budget_faktor,
                         tokens_input, tokens_output, latenz_sekunden,
                         erfolg, zone, kosten_eur)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.timestamp,
                        entry.task_text,
                        entry.provider,
                        entry.model,
                        entry.strecken_typ,
                        entry.strecken_typ_code,
                        entry.schwierigkeit,
                        entry.etappen,
                        entry.gas_level,
                        entry.gas_strategie,
                        entry.token_budget_faktor,
                        entry.tokens_input,
                        entry.tokens_output,
                        entry.latenz_sekunden,
                        1 if entry.erfolg else 0,
                        entry.zone,
                        entry.kosten_eur,
                    ),
                )
        except sqlite3.Error:
            pass

    def metriken(self, tage: int = 7) -> dict[str, Any]:
        metrics = self._metriken_from_bach_compat(tage)
        if metrics.get("total_delegations", 0) > 0:
            return metrics
        external_metrics = self._metriken_from_external(tage)
        return external_metrics if external_metrics.get("total_delegations", 0) > 0 else metrics

    def _metriken_from_bach_compat(self, tage: int) -> dict[str, Any]:
        since = time.time() - (tage * 86400)
        empty = {
            "zeitraum_tage": tage,
            "total_delegations": 0,
            "erfolgsrate": 0.0,
            "avg_latenz": 0.0,
            "total_tokens": 0,
            "total_kosten_eur": 0.0,
            "provider": [],
            "streckentypen": [],
            "gas_verteilung": {},
        }
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                if not _table_exists(conn, "clutch_fahrtenbuch"):
                    return empty
                row = conn.execute(
                    """
                    SELECT COUNT(*), SUM(erfolg), AVG(latenz_sekunden),
                           SUM(tokens_input + tokens_output), SUM(kosten_eur)
                    FROM clutch_fahrtenbuch WHERE timestamp > ?
                    """,
                    (since,),
                ).fetchone()
                total = row[0] or 0
                successful = row[1] or 0
                provider_rows = conn.execute(
                    """
                    SELECT provider, COUNT(*), SUM(erfolg), AVG(latenz_sekunden)
                    FROM clutch_fahrtenbuch WHERE timestamp > ?
                    GROUP BY provider ORDER BY COUNT(*) DESC
                    """,
                    (since,),
                ).fetchall()
                strecken_rows = conn.execute(
                    """
                    SELECT strecken_typ, strecken_typ_code, COUNT(*),
                           SUM(erfolg), AVG(gas_level)
                    FROM clutch_fahrtenbuch WHERE timestamp > ?
                    GROUP BY strecken_typ_code, strecken_typ ORDER BY COUNT(*) DESC
                    """,
                    (since,),
                ).fetchall()
                gas_rows = conn.execute(
                    """
                    SELECT gas_strategie, COUNT(*)
                    FROM clutch_fahrtenbuch WHERE timestamp > ?
                    GROUP BY gas_strategie
                    """,
                    (since,),
                ).fetchall()
        except sqlite3.Error:
            return empty

        return {
            "zeitraum_tage": tage,
            "total_delegations": total,
            "erfolgsrate": round(successful / max(1, total) * 100, 1),
            "avg_latenz": round(row[2] or 0, 2),
            "total_tokens": row[3] or 0,
            "total_kosten_eur": round(row[4] or 0, 2),
            "provider": [
                {
                    "name": r[0],
                    "delegations": r[1],
                    "erfolgsrate": round((r[2] or 0) / max(1, r[1]) * 100, 1),
                    "avg_latenz": round(r[3] or 0, 2),
                }
                for r in provider_rows
            ],
            "streckentypen": [
                {
                    "typ": r[0],
                    "code": r[1],
                    "delegations": r[2],
                    "erfolgsrate": round((r[3] or 0) / max(1, r[2]) * 100, 1),
                    "avg_gas": round(r[4] or 0, 0),
                }
                for r in strecken_rows
            ],
            "gas_verteilung": {r[0]: r[1] for r in gas_rows},
        }

    def _metriken_from_external(self, tage: int) -> dict[str, Any]:
        since = time.time() - (tage * 86400)
        empty = {
            "zeitraum_tage": tage,
            "total_delegations": 0,
            "erfolgsrate": 0.0,
            "avg_latenz": 0.0,
            "total_tokens": 0,
            "total_kosten_eur": 0.0,
            "provider": [],
            "streckentypen": [],
            "gas_verteilung": {},
        }
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                if not _table_exists(conn, "fahrten"):
                    return empty
                row = conn.execute(
                    """
                    SELECT COUNT(*), SUM(erfolg), AVG(latenz_sekunden), SUM(total_tokens)
                    FROM fahrten WHERE timestamp > ?
                    """,
                    (since,),
                ).fetchone()
                total = row[0] or 0
                successful = row[1] or 0
                provider_rows = conn.execute(
                    """
                    SELECT provider, COUNT(*), SUM(erfolg), AVG(latenz_sekunden)
                    FROM fahrten WHERE timestamp > ?
                    GROUP BY provider ORDER BY COUNT(*) DESC
                    """,
                    (since,),
                ).fetchall()
                strecken_rows = conn.execute(
                    """
                    SELECT strecken_typ, COUNT(*), SUM(erfolg), AVG(gas)
                    FROM fahrten WHERE timestamp > ?
                    GROUP BY strecken_typ ORDER BY COUNT(*) DESC
                    """,
                    (since,),
                ).fetchall()
        except sqlite3.Error:
            return empty

        return {
            "zeitraum_tage": tage,
            "total_delegations": total,
            "erfolgsrate": round(successful / max(1, total) * 100, 1),
            "avg_latenz": round(row[2] or 0, 2),
            "total_tokens": row[3] or 0,
            "total_kosten_eur": 0.0,
            "provider": [
                {
                    "name": r[0],
                    "delegations": r[1],
                    "erfolgsrate": round((r[2] or 0) / max(1, r[1]) * 100, 1),
                    "avg_latenz": round(r[3] or 0, 2),
                }
                for r in provider_rows
            ],
            "streckentypen": [
                {
                    "typ": r[0],
                    "code": 0,
                    "delegations": r[1],
                    "erfolgsrate": round((r[2] or 0) / max(1, r[1]) * 100, 1),
                    "avg_gas": round((r[3] or 0) * 100, 0),
                }
                for r in strecken_rows
            ],
            "gas_verteilung": {},
        }

    def format_metriken(self, tage: int = 7) -> str:
        m = self.metriken(tage)
        lines = [
            f"[FAHRTENBUCH] Metriken (letzte {tage} Tage)",
            "=" * 50,
            f"  Delegations: {m['total_delegations']}",
            f"  Erfolgsrate: {m['erfolgsrate']}%",
        ]
        if "avg_latenz" in m:
            lines.append(f"  Ø Latenz: {m['avg_latenz']}s")
            lines.append(f"  Tokens gesamt: {m.get('total_tokens', 0):,}")
            lines.append(f"  Kosten: {m.get('total_kosten_eur', 0):.2f} EUR")
        if m.get("provider"):
            lines.append("\n  Provider:")
            for provider in m["provider"]:
                lines.append(
                    f"    {provider['name']}: {provider['delegations']}x, "
                    f"{provider['erfolgsrate']}% Erfolg, "
                    f"Ø {provider['avg_latenz']}s"
                )
        if m.get("streckentypen"):
            lines.append("\n  Streckentypen:")
            for strecke in m["streckentypen"]:
                lines.append(
                    f"    {strecke['typ']} (Typ {strecke['code']}): "
                    f"{strecke['delegations']}x, {strecke['erfolgsrate']}% Erfolg, "
                    f"Ø Gas {strecke['avg_gas']}%"
                )
        if m.get("gas_verteilung"):
            lines.append("\n  Gas-Verteilung:")
            for strategie, count in m["gas_verteilung"].items():
                lines.append(f"    {strategie}: {count}x")
        return "\n".join(lines)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._external, name)


class _FahrschuleAdapter:
    """BACH-Statusoberflaeche auf externe clutch.Fahrschule legen."""

    source = "clutch"

    def __init__(self, db_path: Path, external_fahrschule: Any, fahrtenbuch: _FahrtenbuchAdapter):
        self.db_path = db_path
        self._external = external_fahrschule
        self._fahrtenbuch = fahrtenbuch

    def trainieren(self) -> dict[str, Any]:
        return self._external.trainieren()

    def status(self) -> dict[str, Any]:
        rows = self._fitness_rows()
        if not rows:
            rows = self._rows_from_fahrten()
        top = rows[:5]
        bottom = rows[-5:] if rows else []
        return {
            "total_kombinationen": len(rows),
            "total_delegations": sum(row["delegations"] for row in rows),
            "epsilon": getattr(self._external, "erkundungsrate", 0.0),
            "policy_update_interval": getattr(self._external, "min_fahrten", 0),
            "top_5": top,
            "bottom_5": bottom,
        }

    def _fitness_rows(self) -> list[dict[str, Any]]:
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                if not _table_exists(conn, "clutch_fitness"):
                    return []
                rows = conn.execute(
                    """
                    SELECT model, strecken_typ, fitness, total_delegations, successful
                    FROM clutch_fitness
                    ORDER BY fitness DESC, total_delegations DESC
                    """
                ).fetchall()
        except sqlite3.Error:
            return []
        return [
            {
                "model": row[0],
                "strecken_typ": row[1],
                "fitness": round(row[2] or 0.0, 3),
                "success_rate": round((row[4] or 0) / max(1, row[3] or 0) * 100, 1),
                "delegations": row[3] or 0,
            }
            for row in rows
        ]

    def _rows_from_fahrten(self) -> list[dict[str, Any]]:
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                if not _table_exists(conn, "fahrten"):
                    return []
                rows = conn.execute(
                    """
                    SELECT gang, strecken_typ, COUNT(*), SUM(erfolg)
                    FROM fahrten
                    GROUP BY gang, strecken_typ
                    ORDER BY COUNT(*) DESC
                    """
                ).fetchall()
        except sqlite3.Error:
            return []
        return [
            {
                "model": row[0],
                "strecken_typ": row[1],
                "fitness": round((row[3] or 0) / max(1, row[2] or 0), 3),
                "success_rate": round((row[3] or 0) / max(1, row[2] or 0) * 100, 1),
                "delegations": row[2] or 0,
            }
            for row in rows
        ]

    def empfehle(
        self,
        strecken_typ: int,
        verfuegbare_modelle: list[str],
        default_model: str = "sonnet",
    ) -> SimpleNamespace:
        candidates = [row for row in self.status()["top_5"] if row["model"] in verfuegbare_modelle]
        if candidates:
            chosen = candidates[0]
            return SimpleNamespace(
                recommended_model=chosen["model"],
                fitness=chosen["fitness"],
                is_exploration=False,
                reason=f"Beste Fitness: {chosen['fitness']:.2f}",
                alternatives=[
                    {"model": row["model"], "fitness": row["fitness"]}
                    for row in candidates[1:]
                ],
            )
        return SimpleNamespace(
            recommended_model=default_model,
            fitness=0.5,
            is_exploration=False,
            reason="Keine Fitnessdaten",
            alternatives=[],
        )

    def record_ergebnis(
        self,
        model: str,
        strecken_typ: int,
        erfolg: bool,
        tokens_used: int = 0,
        latency: float = 0.0,
    ) -> float:
        now = time.time()
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS clutch_fitness (
                        model TEXT,
                        strecken_typ INTEGER,
                        fitness REAL DEFAULT 0.5,
                        total_delegations INTEGER DEFAULT 0,
                        successful INTEGER DEFAULT 0,
                        avg_tokens REAL DEFAULT 0,
                        avg_latency REAL DEFAULT 0,
                        last_updated REAL,
                        PRIMARY KEY (model, strecken_typ)
                    )
                    """
                )
                row = conn.execute(
                    """
                    SELECT fitness, total_delegations, successful, avg_tokens, avg_latency
                    FROM clutch_fitness WHERE model = ? AND strecken_typ = ?
                    """,
                    (model, strecken_typ),
                ).fetchone()
                if row:
                    fitness, total, successful, avg_tokens, avg_latency = row
                else:
                    fitness, total, successful, avg_tokens, avg_latency = 0.5, 0, 0, 0.0, 0.0
                total += 1
                successful += 1 if erfolg else 0
                reward = 1.0 if erfolg else 0.0
                fitness = fitness * 0.9 + reward * 0.1
                if tokens_used:
                    avg_tokens = float(tokens_used) if not avg_tokens else avg_tokens * 0.8 + tokens_used * 0.2
                if latency:
                    avg_latency = float(latency) if not avg_latency else avg_latency * 0.8 + latency * 0.2
                conn.execute(
                    """
                    INSERT OR REPLACE INTO clutch_fitness
                        (model, strecken_typ, fitness, total_delegations,
                         successful, avg_tokens, avg_latency, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (model, strecken_typ, fitness, total, successful, avg_tokens, avg_latency, now),
                )
                return fitness
        except sqlite3.Error:
            return 0.5

    def format_status(self) -> str:
        status = self.status()
        lines = [
            "[FAHRSCHULE] Lern-Loop Status",
            "=" * 50,
            f"  Kombinationen: {status['total_kombinationen']}",
            f"  Delegations: {status['total_delegations']}",
            f"  Epsilon: {status['epsilon']}",
        ]
        if status["top_5"]:
            lines.append("\n  Top-Kombinationen:")
            for row in status["top_5"]:
                lines.append(
                    f"    {row['model']}×Typ{row['strecken_typ']}: "
                    f"Fitness {row['fitness']}, "
                    f"Erfolg {row['success_rate']}% "
                    f"({row['delegations']} Runs)"
                )
        return "\n".join(lines)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._external, name)


_analyser_instance: Any | None = None
_gas_bremse_instance: Any | None = None
_bordcomputer_instances: dict[str, Any] = {}
_fahrtenbuch_instances: dict[str, Any] = {}
_fahrschule_instances: dict[str, Any] = {}


def get_analyser():
    global _analyser_instance
    if _analyser_instance is not None:
        return _analyser_instance

    if _external_streckenanalyse_ready():
        analyser_cls = getattr(_clutch_strecke_module, "StreckenAnalyse")
        _analyser_instance = _StreckenAnalyseAdapter(analyser_cls())
        return _analyser_instance

    _analyser_instance = _get_legacy_analyser()
    return _analyser_instance


def analysiere_task(task_beschreibung: str):
    return get_analyser().analysiere(task_beschreibung)


def get_gas_bremse():
    global _gas_bremse_instance
    if _gas_bremse_instance is not None:
        return _gas_bremse_instance

    if _external_gas_bremse_ready():
        gas_bremse_cls = getattr(_clutch_gas_bremse_module, "GasBremse")
        _gas_bremse_instance = _GasBremseAdapter(gas_bremse_cls())
        return _gas_bremse_instance

    _gas_bremse_instance = _get_legacy_gas_bremse()
    return _gas_bremse_instance


def berechne_gas(
    gas_level: int | None = None,
    strecken_schwierigkeit: int | float | None = None,
    strecken_typ_code: int | None = None,
):
    return get_gas_bremse().berechne(gas_level, strecken_schwierigkeit, strecken_typ_code)


def get_bordcomputer(db_path: str | os.PathLike[str] | None = None):
    if not _external_bordcomputer_ready():
        return _get_legacy_bordcomputer()

    resolved_db = _canonical_bach_db_path() if db_path is None else Path(db_path).expanduser().resolve()
    key = _instance_key(resolved_db)
    if key not in _bordcomputer_instances:
        fahrtenbuch = get_fahrtenbuch(db_path=resolved_db)
        bordcomputer_cls = getattr(_clutch_bordcomputer_module, "Bordcomputer")
        _bordcomputer_instances[key] = _BordcomputerAdapter(
            bordcomputer_cls(fahrtenbuch.external),
        )
    return _bordcomputer_instances[key]


def get_fahrtenbuch(db_path: str | os.PathLike[str] | None = None):
    if db_path is None or not _external_fahrtenbuch_ready():
        return _get_legacy_fahrtenbuch(db_path=db_path)

    key = _instance_key(db_path)
    if key not in _fahrtenbuch_instances:
        resolved_db = Path(db_path).expanduser().resolve()
        fahrtenbuch_cls = getattr(_clutch_fahrtenbuch_module, "Fahrtenbuch")
        entry_cls = getattr(_clutch_fahrtenbuch_module, "FahrtEintrag")
        _fahrtenbuch_instances[key] = _FahrtenbuchAdapter(
            resolved_db,
            fahrtenbuch_cls(db_path=resolved_db),
            entry_cls,
        )
    return _fahrtenbuch_instances[key]


def get_fahrschule(db_path: str | os.PathLike[str] | None = None):
    if db_path is None or not _external_fahrschule_ready():
        return _get_legacy_fahrschule(db_path=db_path)

    key = _instance_key(db_path)
    if key not in _fahrschule_instances:
        resolved_db = Path(db_path).expanduser().resolve()
        fahrtenbuch = get_fahrtenbuch(db_path=resolved_db)
        getriebe_cls = getattr(_clutch_getriebe_module, "Getriebe")
        kupplung_cls = getattr(_clutch_kupplung_module, "Kupplung")
        fahrschule_cls = getattr(_clutch_fahrschule_module, "Fahrschule")
        getriebe = getriebe_cls()
        kupplung = kupplung_cls(getriebe)
        _fahrschule_instances[key] = _FahrschuleAdapter(
            resolved_db,
            fahrschule_cls(fahrtenbuch.external, kupplung),
            fahrtenbuch,
        )
    return _fahrschule_instances[key]


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


def get_component_sources() -> dict[str, str]:
    """Report which delegation components already use external clutch."""

    partner_module_ready = (
        _clutch_partner_module is not None
        and getattr(_clutch_partner_module, "Partner", None) is not None
        and getattr(_clutch_partner_module, "PartnerRegistry", None) is not None
    )

    return {
        "external_clutch": "available"
        if _get_clutch_scorer is not None
        or partner_module_ready
        or _external_streckenanalyse_ready()
        or _external_gas_bremse_ready()
        or _external_bordcomputer_ready()
        or _external_fahrtenbuch_ready()
        or _external_fahrschule_ready()
        else "unavailable",
        "scorer": get_scorer_source(),
        "partner_registry": "clutch"
        if partner_module_ready
        else get_partner_registry_source(),
        "streckenanalyse": "clutch" if _external_streckenanalyse_ready() else "legacy",
        "gas_bremse": "clutch" if _external_gas_bremse_ready() else "legacy",
        "bordcomputer": "clutch" if _external_bordcomputer_ready() else "legacy",
        "fahrschule": "clutch" if _external_fahrschule_ready() else "legacy",
        "fahrtenbuch": "clutch" if _external_fahrtenbuch_ready() else "legacy",
    }


__all__ = [
    "SCORER_SOURCE",
    "PARTNER_REGISTRY_SOURCE",
    "analysiere_task",
    "berechne_gas",
    "build_partner_registry",
    "get_component_sources",
    "get_analyser",
    "get_bordcomputer",
    "get_fahrschule",
    "get_fahrtenbuch",
    "get_gas_bremse",
    "get_partner_registry_source",
    "get_scorer",
    "get_scorer_source",
]
