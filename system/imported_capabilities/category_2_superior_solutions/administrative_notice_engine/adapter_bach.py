# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Bach Adapter for Administrative Notice & § 14 UStG Dispute Engine (from SentinelFleet & FolderHome).

Automates formal statutory compliance audits of incoming invoices and official notices (Bescheide),
extracting statutory defects and drafting legally grounded, courteous objection/correction letters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class InvoiceAuditData:
    vendor_name: str
    vendor_vat_id: Optional[str]
    invoice_number: str
    invoice_date: str
    delivery_date: Optional[str]
    net_amount: float
    tax_rate: float
    gross_amount: float
    currency: str = "EUR"


class BachAdministrativeAuditor:
    """Audits incoming documents against formal requirements and drafts corrections."""

    @staticmethod
    def audit_ustg_compliance(data: InvoiceAuditData) -> Tuple[bool, List[str]]:
        """
        Validates mandatory invoice fields according to § 14 Abs. 4 UStG:
        1. Full name and address of supplier
        2. Tax number or VAT ID (USt-IdNr.)
        3. Issue date
        4. Unique sequential invoice number
        5. Quantity and commercial description of goods/services
        6. Delivery/performance date
        7. Net amount, tax rate, tax amount, gross amount
        """
        violations = []

        if not data.vendor_name or len(data.vendor_name.strip()) < 2:
            violations.append("§ 14 Abs. 4 Nr. 1: Vollständiger Name und Anschrift des leistenden Unternehmers fehlen.")

        if not data.vendor_vat_id:
            violations.append("§ 14 Abs. 4 Nr. 2: Steuernummer oder Umsatzsteuer-Identifikationsnummer (USt-IdNr.) fehlt.")

        if not data.invoice_number or len(data.invoice_number.strip()) < 1:
            violations.append("§ 14 Abs. 4 Nr. 4: Fortlaufende Rechnungsnummer fehlt.")

        if not data.delivery_date:
            violations.append("§ 14 Abs. 4 Nr. 6: Zeitpunkt der Lieferung bzw. sonstigen Leistung (Leistungsdatum) fehlt.")

        # Mathematical consistency
        expected_tax = round(data.net_amount * (data.tax_rate / 100.0), 2)
        expected_gross = round(data.net_amount + expected_tax, 2)
        if abs(data.gross_amount - expected_gross) > 0.05:
            violations.append(
                f"§ 14 Abs. 4 Nr. 7: Rechnerische Diskrepanz (Netto {data.net_amount:.2f} + {data.tax_rate}% Steuer = "
                f"erwartet {expected_gross:.2f}, ausgewiesen {data.gross_amount:.2f})."
            )

        is_compliant = len(violations) == 0
        return is_compliant, violations

    @staticmethod
    def generate_dispute_letter(data: InvoiceAuditData, violations: List[str]) -> str:
        """Generates a formal, polite invoice correction request letter."""
        violations_block = "\n".join(f"  - {v}" for v in violations)
        return (
            f"Sehr geehrte Damen und Herren,\n\n"
            f"vielen Dank für die Zusendung Ihrer Rechnung Nr. {data.invoice_number} vom {data.invoice_date} "
            f"über einen Bruttobetrag von {data.gross_amount:.2f} {data.currency}.\n\n"
            f"Bei unserer automatisierten Eingangsprüfung nach § 14 UStG wurden folgende formelle Mängel festgestellt:\n"
            f"{violations_block}\n\n"
            f"Nach dem deutschen Umsatzsteuergesetz ist der Vorsteuerabzug an das Vorliegen aller gesetzlichen "
            f"Pflichtangaben gebunden. Wir bitten Sie daher höflich, uns eine entsprechend korrigierte Rechnung "
            f"oder eine formelle Rechnungskorrektur zukommen zu lassen.\n\n"
            f"Bis zum Eingang der berichtigten Rechnung ist die Zahlungsanweisung für diese Rechnung vorläufig ausgesetzt.\n\n"
            f"Mit freundlichen Grüßen\n"
            f"BACH Personal Operating System - Rechnungsprüfung"
        )
