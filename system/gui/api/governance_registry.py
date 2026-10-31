"""Device-authenticated metadata reads from the canonical policy-registry.

Erweitert um den GUI-Bereich „Governance & Control“ (ocean-gui):
Erlaubnis-Raster, Permission-Prüfung über modul:ellmos-delegation-authority,
Sperren, Hooks & Guards sowie Logs & Audit. Die bestehenden
policy-registry-Endpunkte bleiben unverändert.
"""
import asyncio
import importlib.util
import sys
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from hub._services.policy_registry_adapter import (
    observe, PolicyProviderUnavailable, PolicySnapshotChanged, public_unavailable_reason,
)

router = APIRouter(prefix="/api/governance", tags=["policy-registry"])

# --- modul:ellmos-delegation-authority (lazy geladen und gecacht) ---------
# Repo-Root = parents[3] von system/gui/api/governance_registry.py
_AUTHORITY_MODULE_PATH = (
    Path(__file__).resolve().parents[3] / ".MODULES" / ".CONTROL"
    / "ellmos-delegation-authority" / "delegation_authority.py"
)
# system/hooks/ = parents[2] von system/gui/api/governance_registry.py
_HOOKS_DIR = Path(__file__).resolve().parents[2] / "hooks"

_authority_lock = threading.Lock()
_authority_module: Optional[Any] = None

# --- Audit-Puffer (In-Memory, letzter Ausschnitt, max. 200 Events) --------
_AUDIT_MAX_EVENTS = 200
_audit_events: deque = deque(maxlen=_AUDIT_MAX_EVENTS)
_audit_lock = threading.Lock()


async def read_registry(**options):
    try:
        return await asyncio.to_thread(observe, **options)
    except PolicyProviderUnavailable as exc:
        raise HTTPException(503, public_unavailable_reason(exc)) from None
    except PolicySnapshotChanged as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/policy-registry")
async def registry_entries(scope: str | None = Query(None, max_length=256),
        consumer: str | None = Query(None, max_length=256), query: str = Query("", max_length=512),
        kind: str | None = Query(None, pattern="^(policy|rule|decision|evidence|decision-candidate)$")):
    return await read_registry(scope=scope, consumer=consumer, query=query, kind=kind)


@router.get("/effective-policy")
async def effective_policy(scope: str = Query(..., min_length=1, max_length=256),
        consumer: str | None = Query(None, max_length=256), query: str = Query("", max_length=512)):
    return await read_registry(scope=scope, consumer=consumer, query=query, effective=True)


# --- Governance & Control: Erlaubnisse, Prüfung, Audit, Sperren, Hooks ----

def _load_authority() -> Any:
    """Lädt das Autoritäts-Modul lazy und gecacht; Fehler → HTTP 503."""
    global _authority_module
    if _authority_module is not None:
        return _authority_module
    with _authority_lock:
        if _authority_module is not None:
            return _authority_module
        if not _AUTHORITY_MODULE_PATH.is_file():
            raise HTTPException(
                503,
                "Erlaubnis-Modul „modul:ellmos-delegation-authority“ ist nicht "
                f"installiert (erwartet unter: {_AUTHORITY_MODULE_PATH}).",
            )
        try:
            spec = importlib.util.spec_from_file_location(
                "ellmos_delegation_authority", str(_AUTHORITY_MODULE_PATH)
            )
            if spec is None or spec.loader is None:
                raise ImportError("Modul-Spec konnte nicht erstellt werden.")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
        except Exception as exc:
            raise HTTPException(
                503,
                "Erlaubnis-Modul „modul:ellmos-delegation-authority“ konnte "
                f"nicht geladen werden: {exc}",
            ) from None
        _authority_module = module
        return _authority_module


def _record_audit(event: Dict[str, Any]) -> None:
    """Nimmt ein Audit-Event aus dem Autoritäts-Modul in den Puffer auf."""
    enriched = dict(event)
    enriched["received_at"] = datetime.now(timezone.utc).isoformat()
    with _audit_lock:
        _audit_events.append(enriched)


@router.get("/permission-matrix")
async def permission_matrix():
    """Raster „Erlaubnisse für Außenwirkung“: Übersicht + effektive Zellen."""
    authority = _load_authority()

    def _build() -> Dict[str, Any]:
        overview = authority.get_permission_matrix_overview()
        effective_cells: Dict[str, Dict[str, Any]] = {}
        # Nur Anzeige: bewusst ohne event_recorder, damit das Raster-Rendern
        # den Audit-Puffer nicht mit 16 Events pro Seitenaufruf flutet.
        for action in overview["actions"]:
            for actor in overview["actors"]:
                decision = authority.evaluate_permission(action, actor)
                effective_cells[f"{action}|{actor}"] = {
                    "action": decision.action,
                    "actor": decision.actor,
                    "decision": decision.decision,
                    "reason": decision.reason,
                    "source": decision.source,
                    "needs_ticket": decision.needs_ticket,
                    "escalation_hint": decision.escalation_hint,
                }
        overview["effective_cells"] = effective_cells
        return overview

    matrix = await asyncio.to_thread(_build)
    return {"success": True, **matrix}


class EvaluatePermissionRequest(BaseModel):
    action: str = Field(..., min_length=1, max_length=64)
    actor: str = Field(..., min_length=1, max_length=64)


@router.post("/evaluate-permission")
async def evaluate_permission(request: EvaluatePermissionRequest):
    """Prüfung einer Handlung × Akteur über controlcenter_evaluate_permission.

    Q6: Dieser Aufruf entscheidet über die Außenwirkung; Datei- und
    Projektrechte (LOCK.permissions.json / lock-master) sind ein getrennter
    Bereich und werden hier nicht mit entschieden.
    """
    authority = _load_authority()
    try:
        decision = await asyncio.to_thread(
            authority.controlcenter_evaluate_permission,
            request.action,
            request.actor,
            None,
            _record_audit,
        )
    except authority.PermissionDenied as exc:
        raise HTTPException(400, str(exc)) from None
    return {
        "success": True,
        "action": decision.action,
        "actor": decision.actor,
        "decision": decision.decision,
        "reason": decision.reason,
        "source": decision.source,
        "needs_ticket": decision.needs_ticket,
        "escalation_hint": decision.escalation_hint,
        "revision": decision.revision,
    }


@router.get("/audit")
async def audit_log(limit: int = Query(50, ge=1, le=_AUDIT_MAX_EVENTS)):
    """Letzte Audit-Events aus dem In-Memory-Puffer (neueste zuerst)."""
    with _audit_lock:
        events = list(_audit_events)
    events.reverse()
    return {
        "success": True,
        "count": min(len(events), limit),
        "total_buffered": len(events),
        "capacity": _AUDIT_MAX_EVENTS,
        "events": events[:limit],
    }


@router.get("/locks")
async def locks():
    """Sperren — ehrlicher strukturierter Platzhalter.

    Ein zentraler Lock-Master bzw. eine LOCK.permissions.json ist als Konzept
    vorgesehen, existiert aber als ausführbarer Code noch nicht. Deshalb wird
    hier nichts vorgetäuscht: available=false mit klarer Erklärung.
    """
    return {
        "success": True,
        "available": False,
        "concept": "LOCK.permissions.json / lock-master",
        "detail": (
            "Ein zentraler Lock-Master bzw. eine LOCK.permissions.json ist als "
            "Konzept vorgesehen, liegt aber als ausführbarer Code noch nicht "
            "vor. Sobald er existiert, liefert dieser Endpunkt die realen "
            "Sperr-Daten; bis dahin gilt: keine Sperren erfunden."
        ),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/hooks")
async def hooks_and_guards():
    """Hooks & Guards — reale Existenzprüfung, kein erfundener hook-master.

    Der hook-master ist als Konzept vorgesehen, aber als Code noch nicht
    vorhanden. Die gelisteten Guard-Dateien werden zur Laufzeit auf echte
    Existenz geprüft (Ordner system/hooks/).
    """
    def _build() -> Dict[str, Any]:
        hooks: List[Dict[str, Any]] = []
        if _HOOKS_DIR.is_dir():
            for path in sorted(p for p in _HOOKS_DIR.iterdir() if p.is_file()):
                hooks.append(
                    {"name": path.name, "present": True, "path": str(path)}
                )
        db_guard = _HOOKS_DIR / "bach-db-guard.sh"
        return {
            "success": True,
            "available": bool(hooks),
            "concept": "hook-master",
            "detail": (
                "Ein zentraler hook-master ist als Konzept vorgesehen, aber "
                "als Code noch nicht vorhanden. Die unten gelisteten Guards "
                "werden zur Laufzeit echt geprüft."
            ),
            "db_guard_present": db_guard.is_file(),
            "hooks": hooks,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    return await asyncio.to_thread(_build)