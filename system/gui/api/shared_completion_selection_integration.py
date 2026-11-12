# coding: utf-8
"""Gemeinsame Integration der Abschluss- und Auswahlbedienung für BACH und Ocean
im kanonischen ellmos-system-gui-Vertrag (#2259).
- Keine Wiederbelebung von system/gui/web als zweites Produkt.
- Klare Trennung von host, device und provider.
- Auswahl-/Abschlussregeln gewähren keine neuen Werkzeugrechte und umgehen
  weder fremde Leases noch Nutzer-/externe Freigaben.
"""
from __future__ import annotations
from typing import Any


def build_shared_completion_selection_contract(
    *,
    consumer: str,
    gui_version: str,
    host: str,
    device: str,
    provider: str,
    foreign_lease_active: bool = False,
    requires_user_approval: bool = False,
) -> dict[str, Any]:
    if consumer not in ("bach", "ocean"):
        raise ValueError(f"Unbekannter Consumer: {consumer}")
    return {
        "carrier_product": "ellmos-system-gui",
        "legacy_web_copy_revived": False,
        "consumer": consumer,
        "gui_version": gui_version,
        "identity": {
            "host": host,
            "device": device,
            "provider": provider,
        },
        "guards": {
            "grants_new_tool_permissions": False,
            "bypasses_foreign_leases": False,
            "bypasses_user_approval": False,
            "action_allowed": (not foreign_lease_active) and (not requires_user_approval),
        },
    }
