"""Autonomie- und Budget-Governance (automation-master).

Einstellbare Autonomiestufe je Bereich:

* „manuell“ (Standard) – keine Überführung von Rückfragen.
* „teilautomatisch“ – interne Handlungen erlaubt; außenwirkende
  Bereiche (linkedin, youtube, mail) nur bei direktem Auftrag.
* „vollautomatisch“ – handeln und informieren: „rueckfrage“ wird
  automatisch in „erlaubt“ überführt und inform=True gesetzt.

EINE Setting-Quelle: dieses Modul hält die Stufen, den Testmodus, das
Budget und die Messung. Die Entscheidung selbst bleibt bei
ellmos-delegation-authority (evaluate_permission); die Besetzung läuft
über agents-heart. Kein Parallelsystem, keine zweite Entscheidungsebene.

Der Testmodus kappt „vollautomatisch“ wirksam auf „teilautomatisch“ –
Außenwirkung dann nur bei direktem Auftrag –, ohne die eingestellte
Stufe selbst zu ändern. Einstellungen werden als JSON gespeichert;
Budget-Limits und Overrides (befristete Mehrgrenzen durch buddha oder
claude-konsole) gelten nur für Bereiche mit Geldfluss.
"""

from __future__ import annotations

import copy
import datetime as _dt
import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

MODULE_NAME = "ellmos-automation-master"
STORE_REVISION = "v1"
DELEGATION_MODULE_NAME = "ellmos-delegation-authority"

AREAS = ("bildschirmsteuerung", "linkedin", "youtube", "mail")
AUTONOMY_LEVELS = ("manuell", "teilautomatisch", "vollautomatisch")
SPENDING_AREAS = ("linkedin", "youtube")
DEFAULT_AUTONOMY = "manuell"

OVERRIDE_GRANTERS = ("buddha", "claude-konsole")
OVERRIDE_MAX_HOURS = 168

_METRIC_FIELDS = (
    "outcomes_success",
    "outcomes_total",
    "errors",
    "interventions_human",
    "interventions_override",
)


class AutomationSettingsError(RuntimeError):
    """Unzulässige oder unlesbare Automatisierungs-Einstellung."""


def _utc_now() -> str:
    """ISO-UTC-Zeitstempel für Events und Overrides."""
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _require_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise AutomationSettingsError(f"{label} darf nicht leer sein")
    return text


def _validate_area(area: Any) -> str:
    text = str(area or "").strip()
    if text not in AREAS:
        raise AutomationSettingsError(
            f"Unbekannter Bereich {area!r}; erlaubt: bildschirmsteuerung, linkedin, youtube, mail"
        )
    return text


def _validate_level(level: Any) -> str:
    text = str(level or "").strip()
    if text not in AUTONOMY_LEVELS:
        raise AutomationSettingsError(
            f"Unbekannte Autonomiestufe {level!r}; erlaubt: manuell, teilautomatisch, vollautomatisch"
        )
    return text


def _validate_cents(cents: Any) -> int:
    if isinstance(cents, bool) or not isinstance(cents, int):
        raise AutomationSettingsError("Cent-Betrag muss eine ganze Zahl sein")
    if cents < 0:
        raise AutomationSettingsError("Cent-Betrag darf nicht negativ sein")
    return cents


def load_delegation_authority(module_path: Any = None) -> Any:
    """Modul ellmos-delegation-authority laden (EINE Entscheidungsebene).

    Reihenfolge: explizites module_path, dann Umgebungsvariable
    ELLMOS_DELEGATION_AUTHORITY_PATH, dann der Default-Pfad nebenan.
    Zeigt das bereits in sys.modules liegende Modul auf dieselbe Datei,
    wird es wiederverwendet (idempotent, identische Klassen).
    """
    if module_path:
        raw_path = str(module_path)
    else:
        env_path = os.environ.get("ELLMOS_DELEGATION_AUTHORITY_PATH", "")
        if env_path:
            raw_path = env_path
        else:
            raw_path = str(
                Path(__file__).resolve().parent.parent
                / "ellmos-delegation-authority"
                / "delegation_authority.py"
            )
    normalized = os.path.realpath(raw_path)
    existing = sys.modules.get(DELEGATION_MODULE_NAME)
    if existing is not None:
        existing_file = str(getattr(existing, "__file__", "") or "")
        if existing_file and os.path.realpath(existing_file) == normalized:
            return existing
    if not os.path.isfile(normalized):
        raise AutomationSettingsError(f"delegation-authority nicht gefunden: {raw_path}")
    spec = importlib.util.spec_from_file_location(DELEGATION_MODULE_NAME, normalized)
    if spec is None or spec.loader is None:
        raise AutomationSettingsError(f"delegation-authority nicht ladbar: {raw_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[DELEGATION_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class AutonomySettings:
    """Unveränderliche Sicht auf einen Bereich."""

    area: str
    autonomy_level: str
    effective_level: str
    test_mode: bool


def _empty_store() -> Dict[str, Any]:
    """Leerer, vollständiger Einstellungs-Store."""
    return {
        "module": MODULE_NAME,
        "revision": STORE_REVISION,
        "test_mode": False,
        "autonomy": {area: DEFAULT_AUTONOMY for area in AREAS},
        "budget": {
            "limits": {},
            "spent": {area: 0 for area in SPENDING_AREAS},
            "spends": {area: [] for area in SPENDING_AREAS},
            "overrides": [],
            "override_counter": 0,
        },
        "metrics": {area: {field: 0 for field in _METRIC_FIELDS} for area in AREAS},
    }


class AutomationMaster:
    """Einstellbare Autonomiestufen je Bereich mit Testmodus und Messung.

    EINE Setting-Quelle: Stufen, Testmodus, Budget und Metriken liegen in
    einem JSON-Store (oder im Speicher, wenn kein Pfad gegeben ist).
    Die Entscheidung selbst bleibt bei ellmos-delegation-authority;
    ``decide`` reicht die wirksame Stufe nur weiter.
    """

    def __init__(
        self,
        path: Any = None,
        event_recorder: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self._path = str(path) if path is not None else None
        self._event_recorder = event_recorder
        self._store: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if self._path is None:
            return _empty_store()
        file = Path(self._path)
        if not file.exists():
            return _empty_store()
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AutomationSettingsError(
                f"Einstellungen unlesbar ({self._path}): {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise AutomationSettingsError("Einstellungen müssen ein JSON-Objekt sein")
        if data.get("module") != MODULE_NAME:
            raise AutomationSettingsError(
                "Einstellungsdatei gehört nicht zu ellmos-automation-master"
            )
        if data.get("revision") != STORE_REVISION:
            raise AutomationSettingsError(
                f"Unbekannte Revisions der Einstellungen: {data.get('revision')!r}"
            )
        store = _empty_store()
        test_mode = data.get("test_mode")
        if not isinstance(test_mode, bool):
            raise AutomationSettingsError("test_mode muss true oder false sein")
        store["test_mode"] = test_mode
        autonomy = data.get("autonomy")
        if autonomy is not None:
            if not isinstance(autonomy, dict):
                raise AutomationSettingsError("autonomy muss ein Objekt Bereich->Stufe sein")
            for key, value in autonomy.items():
                area = _validate_area(key)
                store["autonomy"][area] = _validate_level(value)
        budget = data.get("budget")
        if isinstance(budget, dict):
            limits = budget.get("limits")
            if isinstance(limits, dict):
                for key, value in limits.items():
                    if (
                        str(key or "").strip() in SPENDING_AREAS
                        and isinstance(value, int)
                        and not isinstance(value, bool)
                        and value >= 0
                    ):
                        store["budget"]["limits"][str(key).strip()] = value
            spent = budget.get("spent")
            if isinstance(spent, dict):
                for key, value in spent.items():
                    if (
                        str(key or "").strip() in SPENDING_AREAS
                        and isinstance(value, int)
                        and not isinstance(value, bool)
                        and value >= 0
                    ):
                        store["budget"]["spent"][str(key).strip()] = value
            spends = budget.get("spends")
            if isinstance(spends, dict):
                for key, value in spends.items():
                    if str(key or "").strip() in SPENDING_AREAS and isinstance(value, list):
                        store["budget"]["spends"][str(key).strip()] = list(value)
            overrides = budget.get("overrides")
            if isinstance(overrides, list):
                store["budget"]["overrides"] = list(overrides)
            counter = budget.get("override_counter")
            if isinstance(counter, int) and not isinstance(counter, bool) and counter >= 0:
                store["budget"]["override_counter"] = counter
        metrics = data.get("metrics")
        if isinstance(metrics, dict):
            for key, value in metrics.items():
                area = str(key or "").strip()
                if area not in AREAS or not isinstance(value, dict):
                    continue
                for field in _METRIC_FIELDS:
                    raw_value = value.get(field)
                    if (
                        isinstance(raw_value, int)
                        and not isinstance(raw_value, bool)
                        and raw_value >= 0
                    ):
                        store["metrics"][area][field] = raw_value
        return store

    def _persist(self) -> None:
        if self._path is None:
            return
        file = Path(self._path)
        tmp = file.parent / (file.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(self._store, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, file)

    def _emit(self, event: str, details: Optional[Dict[str, Any]] = None) -> None:
        if self._event_recorder is None:
            return
        payload: Dict[str, Any] = {
            "module": MODULE_NAME,
            "event": str(event),
            "timestamp": _utc_now(),
        }
        if details:
            payload.update(details)
        self._event_recorder(payload)

    def get_autonomy(self, area: Any) -> str:
        """Eingestellte Stufe des Bereichs (unabhängig vom Testmodus)."""
        return str(self._store["autonomy"].get(_validate_area(area), DEFAULT_AUTONOMY))

    def set_autonomy(self, area: Any, level: Any, *, actor: Any, reason: Any) -> str:
        """Stufe eines Bereichs setzen; löst Event „autonomy.changed“ aus."""
        key = _validate_area(area)
        value = _validate_level(level)
        actor_text = _require_text(actor, "actor")
        reason_text = _require_text(reason, "reason")
        self._store["autonomy"][key] = value
        self._persist()
        self._emit(
            "autonomy.changed",
            {
                "area": key,
                "autonomy_level": value,
                "actor": actor_text,
                "reason": reason_text,
            },
        )
        return value

    def set_test_mode(self, enabled: Any, *, actor: Any, reason: Any) -> bool:
        """Testmodus schalten; löst Event „test_mode.changed“ aus."""
        if not isinstance(enabled, bool):
            raise AutomationSettingsError("enabled muss true oder false sein")
        actor_text = _require_text(actor, "actor")
        reason_text = _require_text(reason, "reason")
        self._store["test_mode"] = enabled
        self._persist()
        self._emit(
            "test_mode.changed",
            {"enabled": enabled, "actor": actor_text, "reason": reason_text},
        )
        return enabled

    def is_test_mode(self) -> bool:
        return bool(self._store["test_mode"])

    def get_effective_autonomy(self, area: Any) -> str:
        """Wirksame Stufe: im Testmodus wird „vollautomatisch“ gekappt."""
        key = _validate_area(area)
        level = self.get_autonomy(key)
        if self.is_test_mode() and level == "vollautomatisch":
            return "teilautomatisch"
        return level

    def effective_autonomy_snapshot(self) -> Dict[str, str]:
        """Wirksame Stufen aller Bereiche als Kopie."""
        return {area: self.get_effective_autonomy(area) for area in AREAS}

    def get_autonomy_settings(self, area: Any) -> AutonomySettings:
        """Einstellung, wirksame Stufe und Testmodus eines Bereichs."""
        key = _validate_area(area)
        return AutonomySettings(
            area=key,
            autonomy_level=self.get_autonomy(key),
            effective_level=self.get_effective_autonomy(key),
            test_mode=self.is_test_mode(),
        )

    def snapshot(self) -> Dict[str, Any]:
        """Deepcopy des gesamten Stores."""
        return copy.deepcopy(self._store)

    @property
    def budget(self) -> "BudgetGovernance":
        """Budget-Governance (Limits, Ausgaben, Overrides)."""
        return BudgetGovernance(
            self._store["budget"], persist=self._persist, emit=self._emit
        )

    @property
    def metrics(self) -> "MetricsRecorder":
        """Messung je Bereich (Ergebnisse, Fehler, Interventionen)."""
        return MetricsRecorder(self._store["metrics"], persist=self._persist)

    def decide(
        self,
        action: Any,
        actor: Any,
        *,
        direct_order: bool = False,
        matrix: Any = None,
        event_recorder: Any = None,
        delegation_module_path: Any = None,
    ) -> Any:
        """Entscheidung über ellmos-delegation-authority mit wirksamer Stufe.

        Die EINE Entscheidungsebene bleibt delegation-authority; dieses
        Modul liefert nur die eingestellte (wirksame) Stufe und den
        Recorder. Nach der Entscheidung wird ein „automation.decide“-
        Event ausgelöst, wenn ein Recorder vorliegt.
        """
        action = _validate_area(action)
        level = self.get_effective_autonomy(action)
        delegation = load_delegation_authority(delegation_module_path)
        effective_recorder = (
            event_recorder if event_recorder is not None else self._event_recorder
        )
        decision = delegation.evaluate_permission(
            action,
            actor,
            matrix=matrix,
            event_recorder=effective_recorder,
            autonomy_level=level,
            direct_order=bool(direct_order),
        )
        if effective_recorder is not None:
            effective_recorder(
                {
                    "module": MODULE_NAME,
                    "event": "automation.decide",
                    "timestamp": _utc_now(),
                    "action": action,
                    "actor": actor,
                    "decision": decision.decision,
                    "autonomy_level": level,
                    "direct_order": bool(direct_order),
                    "inform": decision.inform,
                }
            )
        return decision


class BudgetGovernance:
    """Budget-Limits, Ausgaben und Overrides für Bereiche mit Geldfluss.

    Nur linkedin und youtube sind budgetiert; alle anderen Bereiche
    haben keinen Geldfluss und damit keine Budget-Governance.
    """

    def __init__(
        self,
        budget: Dict[str, Any],
        *,
        persist: Optional[Callable[[], None]] = None,
        emit: Optional[Callable[[str, Optional[Dict[str, Any]]], None]] = None,
    ) -> None:
        self._budget = budget
        self._persist = persist
        self._emit = emit

    @staticmethod
    def _require_spending(area: str) -> str:
        if area not in SPENDING_AREAS:
            raise AutomationSettingsError(
                f"Für Bereich {area!r} gibt es keine Budget-Governance (kein Geldfluss)"
            )
        return area

    def get_limit(self, area: Any) -> int:
        key = str(area or "").strip()
        limits = self._budget.get("limits")
        value = limits.get(key, 0) if isinstance(limits, dict) else 0
        return int(value or 0)

    def set_limit(self, area: Any, cents: Any) -> int:
        key = _validate_area(area)
        self._require_spending(key)
        amount = _validate_cents(cents)
        limits = self._budget.setdefault("limits", {})
        limits[key] = amount
        if self._persist is not None:
            self._persist()
        return amount

    def get_spent(self, area: Any) -> int:
        key = str(area or "").strip()
        spent = self._budget.get("spent")
        value = spent.get(key, 0) if isinstance(spent, dict) else 0
        return int(value or 0)

    def _active_overrides(self, area: Optional[str] = None) -> List[Dict[str, Any]]:
        now = _dt.datetime.now(_dt.timezone.utc)
        active: List[Dict[str, Any]] = []
        overrides = self._budget.get("overrides")
        if not isinstance(overrides, list):
            return active
        wanted = str(area).strip() if area else None
        for entry in overrides:
            if not isinstance(entry, dict):
                continue
            if wanted is not None and str(entry.get("area", "")) != wanted:
                continue
            raw = str(entry.get("expires_at", "") or "")
            if not raw:
                continue
            try:
                expires = _dt.datetime.fromisoformat(raw)
            except ValueError:
                continue
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=_dt.timezone.utc)
            if expires > now:
                active.append(entry)
        return active

    def effective_limit(self, area: Any) -> int:
        """Limit zzgl. aktiver Overrides."""
        key = str(area or "").strip()
        limit = self.get_limit(key)
        extra = 0
        for entry in self._active_overrides(key):
            amount = entry.get("extra_budget_cents", 0)
            if isinstance(amount, int) and not isinstance(amount, bool):
                extra += amount
        return limit + extra

    def check_spend_allowed(self, area: Any, cents: Any) -> Tuple[bool, str]:
        """Prüft eine geplante Ausgabe; gibt (erlaubt, Grund) zurück."""
        amount = _validate_cents(cents)
        key = str(area or "").strip()
        if key not in SPENDING_AREAS:
            return True, "keine Budget-Governance (kein Geldfluss)"
        limit = self.effective_limit(key)
        spent = self.get_spent(key)
        if spent + amount <= limit:
            return True, f"Budget ok: {spent + amount} von {limit} Cent"
        return False, f"Budget überschritten: {spent + amount} von {limit} Cent"

    def record_spend(
        self,
        area: Any,
        cents: Any,
        *,
        purpose: Any,
        override_id: Any = None,
        actor: Any,
    ) -> int:
        """Ausgabe buchen; vorherige Prüfung, Ablehnung als Fehler."""
        key = _validate_area(area)
        self._require_spending(key)
        amount = _validate_cents(cents)
        purpose_text = _require_text(purpose, "purpose")
        actor_text = _require_text(actor, "actor")
        allowed, reason = self.check_spend_allowed(key, amount)
        if not allowed:
            raise AutomationSettingsError(f"Ausgabe abgelehnt: {reason}")
        spent = self._budget.setdefault("spent", {})
        spent[key] = int(spent.get(key, 0) or 0) + amount
        spends = self._budget.setdefault("spends", {})
        spends.setdefault(key, []).append(
            {
                "timestamp": _utc_now(),
                "cents": amount,
                "purpose": purpose_text,
                "override_id": str(override_id).strip() if override_id else None,
                "actor": actor_text,
            }
        )
        if self._persist is not None:
            self._persist()
        return amount

    def grant_override(
        self,
        area: Any,
        *,
        granted_by: Any,
        reason: Any,
        extra_budget_cents: Any,
        hours: Any,
    ) -> Dict[str, Any]:
        """Befristete Mehrgrenze; nur buddha oder claude-konsole."""
        key = _validate_area(area)
        self._require_spending(key)
        granter = _require_text(granted_by, "granted_by")
        if granter not in OVERRIDE_GRANTERS:
            raise AutomationSettingsError(
                f"Unbekannter Override-Geber {granter!r}; erlaubt: buddha, claude-konsole"
            )
        reason_text = _require_text(reason, "reason")
        extra = extra_budget_cents
        if isinstance(extra, bool) or not isinstance(extra, int):
            raise AutomationSettingsError("extra_budget_cents muss eine ganze Zahl sein")
        if extra <= 0:
            raise AutomationSettingsError("extra_budget_cents muss positiv sein")
        if isinstance(hours, bool) or not isinstance(hours, (int, float)):
            raise AutomationSettingsError("hours muss eine Zahl sein")
        if not (0 < hours <= OVERRIDE_MAX_HOURS):
            raise AutomationSettingsError(
                f"hours muss zwischen 1 und {OVERRIDE_MAX_HOURS} liegen"
            )
        counter = int(self._budget.get("override_counter", 0) or 0) + 1
        self._budget["override_counter"] = counter
        override_id = f"ovr-{counter:04d}"
        granted_at = _dt.datetime.now(_dt.timezone.utc)
        expires_at = granted_at + _dt.timedelta(hours=hours)
        entry = {
            "override_id": override_id,
            "area": key,
            "granted_by": granter,
            "granted_at": granted_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "reason": reason_text,
            "extra_budget_cents": extra,
        }
        self._budget.setdefault("overrides", []).append(entry)
        if self._persist is not None:
            self._persist()
        if self._emit is not None:
            self._emit(
                "budget.override_granted",
                {
                    "override_id": override_id,
                    "area": key,
                    "granted_by": granter,
                    "reason": reason_text,
                    "extra_budget_cents": extra,
                    "expires_at": entry["expires_at"],
                },
            )
        return copy.deepcopy(entry)

    def get_overrides(
        self, area: Any = None, active_only: bool = False
    ) -> List[Dict[str, Any]]:
        """Overrides als Kopien; optional gefiltert und nur aktive."""
        wanted = str(area).strip() if area else None
        if active_only:
            entries = self._active_overrides(wanted)
        else:
            overrides = self._budget.get("overrides")
            entries = list(overrides) if isinstance(overrides, list) else []
            if wanted is not None:
                entries = [
                    entry
                    for entry in entries
                    if isinstance(entry, dict) and str(entry.get("area", "")) == wanted
                ]
        return [copy.deepcopy(entry) for entry in entries]


class MetricsRecorder:
    """Messung je Bereich: Ergebnisse, Fehler, Interventionen."""

    def __init__(
        self,
        metrics: Dict[str, Any],
        *,
        persist: Optional[Callable[[], None]] = None,
    ) -> None:
        self._metrics = metrics
        self._persist = persist

    def _area_metrics(self, area: Any) -> Dict[str, int]:
        key = _validate_area(area)
        area_metrics = self._metrics.setdefault(key, {})
        for field in _METRIC_FIELDS:
            area_metrics.setdefault(field, 0)
        return area_metrics

    def record_outcome(self, area: Any, success: Any) -> Dict[str, int]:
        area_metrics = self._area_metrics(area)
        area_metrics["outcomes_total"] = int(area_metrics.get("outcomes_total", 0)) + 1
        if success:
            area_metrics["outcomes_success"] = int(area_metrics.get("outcomes_success", 0)) + 1
        if self._persist is not None:
            self._persist()
        return dict(area_metrics)

    def record_error(self, area: Any) -> Dict[str, int]:
        area_metrics = self._area_metrics(area)
        area_metrics["errors"] = int(area_metrics.get("errors", 0)) + 1
        if self._persist is not None:
            self._persist()
        return dict(area_metrics)

    def record_intervention(self, area: Any, kind: Any) -> Dict[str, int]:
        key = str(kind or "").strip()
        if key not in ("human", "override"):
            raise AutomationSettingsError(
                f"Unbekannte Interventionsart {kind!r}; erlaubt: human, override"
            )
        area_metrics = self._area_metrics(area)
        field = "interventions_human" if key == "human" else "interventions_override"
        area_metrics[field] = int(area_metrics.get(field, 0)) + 1
        if self._persist is not None:
            self._persist()
        return dict(area_metrics)

    def get_metrics(self, area: Any = None) -> Any:
        if area is None:
            return copy.deepcopy(self._metrics)
        key = _validate_area(area)
        area_metrics = self._metrics.get(key)
        if not isinstance(area_metrics, dict):
            return {field: 0 for field in _METRIC_FIELDS}
        return {field: area_metrics.get(field, 0) for field in _METRIC_FIELDS}

    def quality_rate(self, area: Any) -> Optional[float]:
        key = _validate_area(area)
        area_metrics = self._metrics.get(key, {})
        total = int(area_metrics.get("outcomes_total", 0) or 0)
        if total == 0:
            return None
        success = int(area_metrics.get("outcomes_success", 0) or 0)
        return success / total

    def snapshot(self) -> Dict[str, Any]:
        return copy.deepcopy(self._metrics)


def decide(
    action: Any,
    actor: Any,
    *,
    autonomy_level: Any = None,
    direct_order: bool = False,
    matrix: Any = None,
    event_recorder: Any = None,
    delegation_module_path: Any = None,
) -> Any:
    """Dünner Wrapper auf evaluate_permission (ohne Store).

    Für Ad-hoc-Prüfungen ohne Einstellungs-Quelle; Standardstufe ist
    „manuell“.
    """
    delegation = load_delegation_authority(delegation_module_path)
    level = DEFAULT_AUTONOMY if autonomy_level is None else autonomy_level
    return delegation.evaluate_permission(
        action,
        actor,
        matrix=matrix,
        event_recorder=event_recorder,
        autonomy_level=level,
        direct_order=bool(direct_order),
    )