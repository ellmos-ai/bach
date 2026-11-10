# coding: utf-8
"""Schmaler BACH-Adapter für den vorhandenen DecisionClicker-Writer (v1.1.2).

Stellt einen Writer-Eintrag für den Policy-Registry-Adapter bereit.
Die GUI verlinkt mit http://127.0.0.1:8096; Vorschläge können über /api/new abgefragt werden.

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
    def is_available(timeout: float = 2.0) -> tuple[bool, str]:
        """Überprüft, ob der DecisionClicker-Dienst erreichbar ist.
        Gibt (bool, Grund) zurück.
        """
        try:
            # Leichter Ping auf den UI-Endpunkt (schlüssellose Anfrage).
            resp = httpx.get(UI_URL, timeout=timeout, headers={"X-Requested-With": "BACH-Scan"})
            # Wir akzeptieren jede Antwort; der spezifische Zweck ist lediglich die Konnektivität.
            if resp.status_code == 200:
                return True, "ok"
            else:
                return False, f"status_code={resp.status_code}"
        except Exception as exc:
            return False, str(exc)

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
        """Sendet einen neuen Vorschlag an DecisionClicker.
        Erwartet ein JSON-Payload; gibt die Antwort zurück.
        Wird für KI-Vorschläge über BACH/Ocean verwendet.
        """
        try:
            resp = httpx.post(PROPOSAL_URL, json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            return {"error": "http_status", "detail": str(e)}
        except Exception as exc:
            return {"error": "request_failed", "detail": str(exc)}