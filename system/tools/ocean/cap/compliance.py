#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: compliance.py
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version ocean.cap.compliance

Description:
    Ersatz/Rekonstruktion der Referenzvorlage `sentinelfleet/compliance.py`.
    Stellt domain-übergreifende Compliance-Schemata, Checklisten-Registry
    und einen Registry-Adapter bereit, mit dem Modulen wie doc_handler
    ihre Pflichtangaben-Checklisten zentral registrieren können.

Usage:
    from tools.ocean.cap.compliance import ChecklistRegistry, ComplianceSchema
    registry = ChecklistRegistry()
    registry.register(doc_handler.USTG_14A4_CHECKLIST)
"""

from __future__ import annotations

__version__ = "1.0.0"
__author__ = "BACH Team"

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any


@dataclass(frozen=True)
class ComplianceField:
    """Eine einzelne zu prüfende Pflichtangabe / Compliance-Regel."""
    id: str
    name: str
    description: str
    required: bool = True
    law_ref: Optional[str] = None
    validator: Optional[Callable[[Any], bool]] = None


@dataclass(frozen=True)
class ComplianceSchema:
    """Schema für einen Rechtsbereich / eine Dokumentenklasse."""
    domain: str
    version: str
    fields: List[ComplianceField]
    jurisdiction: str = "DE"

    def field_by_id(self, field_id: str) -> Optional[ComplianceField]:
        for f in self.fields:
            if f.id == field_id:
                return f
        return None


class ChecklistRegistry:
    """Zentrale Registry für Compliance-Checklisten."""

    def __init__(self) -> None:
        self._schemas: Dict[str, ComplianceSchema] = {}

    def register(self, schema: ComplianceSchema) -> None:
        if not isinstance(schema, ComplianceSchema):
            raise TypeError("Nur ComplianceSchema-Instanzen registrierbar.")
        key = f"{schema.jurisdiction}:{schema.domain}:{schema.version}"
        self._schemas[key] = schema

    def get(self, domain: str, version: str, jurisdiction: str = "DE") -> Optional[ComplianceSchema]:
        key = f"{jurisdiction}:{domain}:{version}"
        return self._schemas.get(key)

    def list_domains(self) -> List[str]:
        return sorted({s.domain for s in self._schemas.values()})

    def domains_for_law(self, law_ref: str) -> List[str]:
        return sorted({
            s.domain for s in self._schemas.values()
            if any(f.law_ref == law_ref for f in s.fields)
        })


def _always_true(_value: Any) -> bool:
    return True


# Beispiel-Schema: Allgemeines deutsches Rechnungs-Compliance-Schema (Basis §14 UStG)
USTG_14_BASE = ComplianceSchema(
    domain="invoice_de",
    version="1.0",
    jurisdiction="DE",
    fields=[
        ComplianceField(
            id="supplier_name",
            name="Name des leistenden Unternehmers",
            description="Vollständiger Name des Rechnungsstellers.",
            law_ref="§14 Abs. 4 Nr. 1 UStG",
        ),
        ComplianceField(
            id="supplier_address",
            name="Anschrift des leistenden Unternehmers",
            description="Vollständige Adresse des Rechnungsstellers.",
            law_ref="§14 Abs. 4 Nr. 1 UStG",
        ),
        ComplianceField(
            id="customer_name",
            name="Name des Leistungsempfängers",
            description="Name des Kunden.",
            law_ref="§14 Abs. 4 Nr. 2 UStG",
        ),
        ComplianceField(
            id="customer_address",
            name="Anschrift des Leistungsempfängers",
            description="Adresse des Kunden.",
            law_ref="§14 Abs. 4 Nr. 2 UStG",
        ),
        ComplianceField(
            id="service_description",
            name="Menge und Art / Beschreibung",
            description="Bezeichnung der gelieferten Gegenstände oder sonstigen Leistung.",
            law_ref="§14 Abs. 4 Nr. 3 UStG",
        ),
        ComplianceField(
            id="service_date",
            name="Liefer-/Leistungsdatum",
            description="Zeitpunkt der Lieferung/Leistung oder Zahlung.",
            law_ref="§14 Abs. 4 Nr. 4 UStG",
        ),
        ComplianceField(
            id="net_amount",
            name="Entgelt netto",
            description="Zahlungsbetrag ohne Steuer.",
            law_ref="§14 Abs. 4 Nr. 5 UStG",
        ),
        ComplianceField(
            id="tax_rate",
            name="Steuersatz",
            description="Anzuwendender USt-Satz.",
            law_ref="§14 Abs. 4 Nr. 5 UStG",
        ),
        ComplianceField(
            id="tax_amount",
            name="Steuerbetrag",
            description="Ausgewiesener USt-Betrag.",
            law_ref="§14 Abs. 4 Nr. 5 UStG",
        ),
        ComplianceField(
            id="gross_amount",
            name="Zahlungsbetrag brutto",
            description="Zahlungsbetrag einschließlich Steuer.",
            law_ref="§14 Abs. 4 Nr. 6 UStG",
        ),
    ],
)

# Globale Standard-Registry
REGISTRY = ChecklistRegistry()
REGISTRY.register(USTG_14_BASE)

__all__ = [
    "ComplianceField",
    "ComplianceSchema",
    "ChecklistRegistry",
    "USTG_14_BASE",
    "REGISTRY",
]
