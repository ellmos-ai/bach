# BACH Adapter: decision_writer
# coding: utf-8
"""Schmaler BACH-Adapter für den vorhandenen DecisionClicker-Writer (v1.1.2).

Stellt einen Writer-Eintrag für den Policy-Registry-Adapter bereit.
Die GUI verlinkt mit http://127.0.0.1:8096; Vorschläge können über /api/new eingereicht werden.

Entscheidung: keine Proxy-/Einbettung, nur Loopback-Service; aktionsgebundene Bestätigung über die UI.
"""
from __future__ import annotations

import httpx
from typing import Any

ID = "decision-clicker"
VERSION = "1.1.2"
# Commit-Hash aus der Referenz
COMMIT = "bc57916fc340374af80c46d1bbd6530cb9d8bfaa"
UI_URL = "http://127.0.0.1:8096"
PROPOSAL_URL = UI_URL + "/api/new"


class DecisionWriterAdapter:
    """Adapter für den DecisionClicker-Writer."""

    @staticmethod
    def is_available(timeout: float = 0.2) -> tuple[bool, str]:
        """Überprüft, ob der DecisionClicker-Dienst erreichbar ist.
        Gibt (bool, fester Grundcode) ohne rohe Exception-Texte zurück.
        """
        try:
            # Leichter Ping auf den UI-Endpunkt (schlüssellose Anfrage).
            resp = httpx.get(UI_URL, timeout=timeout, headers={"X-Requested-With": "BACH-Scan"})
            if resp.status_code == 200:
                return True, "ok"
            return False, f"status_code={resp.status_code}"
        except Exception:
            return False, "unreachable"

    @staticmethod
    def get_status() -> dict[str, Any]:
        available, reason = DecisionWriterAdapter.is_available()
        return {
            "id": ID,
            "available": available,
            "reason": reason if not available else "separate_explicit_adoption_required",
            "ui_url": UI_URL,
            "proposal_url": PROPOSAL_URL,
        }

    @staticmethod
    def post_proposal(payload: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
        """Reicht einen VORSCHLAG an DecisionClicker ein — ausdrücklich KEINE Freigabe.

        Der Aufruf schreibt über /api/new ausschließlich einen neuen Vorschlag.
        Entscheidungen/Approve erfolgen ausschließlich durch Menschen in der UI;
        ein KI-Approve-Endpunkt existiert nicht und darf hier nicht entstehen.
        """
        try:
            resp = httpx.post(PROPOSAL_URL, json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            detail = f"status_code={status}" if isinstance(status, int) else "http_status"
            return {"error": "http_status", "detail": detail}
        except Exception:
            return {"error": "request_failed", "detail": "unreachable"}


# Modul-Ebene Fassade: der Policy-Registry-Adapter nutzt diese drei Funktionen.
def is_available(timeout: float = 0.2) -> tuple[bool, str]:
    return DecisionWriterAdapter.is_available(timeout=timeout)


def get_status() -> dict[str, Any]:
    return DecisionWriterAdapter.get_status()


def post_proposal(payload: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
    return DecisionWriterAdapter.post_proposal(payload, timeout=timeout)