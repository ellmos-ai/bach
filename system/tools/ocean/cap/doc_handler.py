#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: doc_handler.py
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version ocean.cap.doc_handler

Description:
    Ocean CAP-2.4 Modul: §14 Abs. 4 UStG Rechnungsprüfung (7 Pflichtangaben)
    und Bestreitungsbrief-Generator (Dispute Loop).

    Akzeptiert strukturierte Rechnungsdaten (dict) oder Freitext. Liefert
    einen Validierungsreport mit Mängelliste und rechtskonformem Hinweis.
    Bei Fehlern kann ein formaler Bestreitungsbrief generiert werden.

Usage:
    python -m tools.ocean.cap.doc_handler --invoice invoice.json
    python -m tools.ocean.cap.doc_handler --text "Rechnung über 100 EUR..."
"""

from __future__ import annotations

__version__ = "1.0.0"
__author__ = "BACH Team"

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import compliance


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ValidationFinding:
    code: str
    severity: str  # 'error' | 'warning'
    message: str
    law_ref: str
    field_keys: List[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    ok: bool
    invoice_number: Optional[str]
    findings: List[ValidationFinding]
    checked_fields: List[str]


@dataclass
class DisputeContext:
    addressee_name: str
    addressee_address: str
    sender_name: str
    sender_address: str
    reference: str
    invoice_number: str
    invoice_date: Optional[str]
    payment_due: Optional[str]
    language: str = "de"


# ---------------------------------------------------------------------------
# §14 Abs. 4 UStG: Definition der 7 Pflichtangaben
# ---------------------------------------------------------------------------

USTG_14A4_CHECKLIST = compliance.ComplianceSchema(
    domain="ustg_14a4_invoice",
    version="1.0",
    jurisdiction="DE",
    fields=[
        compliance.ComplianceField(
            id="A1_supplier_identity",
            name="Name und Anschrift des leistenden Unternehmers",
            description="Vollständiger Name und Anschrift des Rechnungsstellers.",
            law_ref="§14 Abs. 4 Nr. 1 UStG",
        ),
        compliance.ComplianceField(
            id="A2_customer_identity",
            name="Name und Anschrift des Leistungsempfängers",
            description="Vollständiger Name und Anschrift des Rechnungsempfängers.",
            law_ref="§14 Abs. 4 Nr. 2 UStG",
        ),
        compliance.ComplianceField(
            id="A3_service_description",
            name="Menge und Art der Gegenstände / Art und Umfang der Leistung",
            description="Bezeichnung der gelieferten Gegenstände oder der erbrachten sonstigen Leistung.",
            law_ref="§14 Abs. 4 Nr. 3 UStG",
        ),
        compliance.ComplianceField(
            id="A4_service_date",
            name="Zeitpunkt der Lieferung/Leistung oder Zahlung",
            description="Datum der Lieferung/Leistung oder, falls abweichend, Zahlungsdatum.",
            law_ref="§14 Abs. 4 Nr. 4 UStG",
        ),
        compliance.ComplianceField(
            id="A5_consideration_tax",
            name="Entgelt und Steuerbeträge sowie Steuersatz",
            description="Entgelt für die Lieferung/Leistung und darauf entfallende Steuerbeträge sowie Steuersatz.",
            law_ref="§14 Abs. 4 Nr. 5 UStG",
        ),
        compliance.ComplianceField(
            id="A6_gross_or_exemption",
            name="Zahlungsbetrag und Hinweis auf Steuerbefreiung",
            description="Zahlungsbetrag einschließlich Umsatzsteuer; bei Steuerbefreiung entsprechender Hinweis.",
            law_ref="§14 Abs. 4 Nr. 6 UStG",
        ),
        compliance.ComplianceField(
            id="A7_special_cases",
            name="Sonstige gesetzlich erforderliche Angaben",
            description="Z.B. USt-IdNr. bei innergemeinschaftlichen Sach-/Dienstleistungen (§14 Abs. 4 Nr. 7 UStG).",
            law_ref="§14 Abs. 4 Nr. 7 UStG",
            required=False,
        ),
    ],
)

compliance.REGISTRY.register(USTG_14A4_CHECKLIST)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _is_non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        # Ersetze Komma durch Punkt und entferne Währungszeichen
        if isinstance(value, str):
            value = value.replace("€", "").replace("EUR", "").replace(" ", "").replace(",", ".")
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return None


def _looks_like_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    value = value.strip()
    patterns = [
        r"^\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}$",  # 04.02.2026
        r"^\d{4}-\d{2}-\d{2}$",  # 2026-02-04
    ]
    return any(re.match(p, value) for p in patterns)


def _extract_invoice_number(data: Dict[str, Any]) -> Optional[str]:
    for key in ("invoice_number", "rechnungsnummer", "invoice_no", "number", "nr"):
        val = data.get(key)
        if _is_non_empty(val):
            return str(val).strip()
    return None


# ---------------------------------------------------------------------------
# Validierungslogik
# ---------------------------------------------------------------------------

def _check_supplier_identity(data: Dict[str, Any]) -> Optional[ValidationFinding]:
    name = data.get("supplier_name") or data.get("seller_name") or data.get("rechnungssteller_name")
    address = data.get("supplier_address") or data.get("seller_address") or data.get("rechnungssteller_adresse")
    missing = []
    if not _is_non_empty(name):
        missing.append("supplier_name")
    if not _is_non_empty(address):
        missing.append("supplier_address")
    if missing:
        return ValidationFinding(
            code="A1_supplier_identity",
            severity="error",
            message="Name und/oder Anschrift des leistenden Unternehmers fehlen.",
            law_ref="§14 Abs. 4 Nr. 1 UStG",
            field_keys=missing,
        )
    return None


def _check_customer_identity(data: Dict[str, Any]) -> Optional[ValidationFinding]:
    name = data.get("customer_name") or data.get("buyer_name") or data.get("rechnungsempfänger_name")
    address = data.get("customer_address") or data.get("buyer_address") or data.get("rechnungsempfänger_adresse")
    missing = []
    if not _is_non_empty(name):
        missing.append("customer_name")
    if not _is_non_empty(address):
        missing.append("customer_address")
    if missing:
        return ValidationFinding(
            code="A2_customer_identity",
            severity="error",
            message="Name und/oder Anschrift des Leistungsempfängers fehlen.",
            law_ref="§14 Abs. 4 Nr. 2 UStG",
            field_keys=missing,
        )
    return None


def _check_service_description(data: Dict[str, Any]) -> Optional[ValidationFinding]:
    desc = (
        data.get("service_description")
        or data.get("items")
        or data.get("leistungsbeschreibung")
        or data.get("description")
    )
    if not _is_non_empty(desc):
        return ValidationFinding(
            code="A3_service_description",
            severity="error",
            message="Menge und Art der gelieferten Gegenstände oder Art und Umfang der sonstigen Leistung fehlen.",
            law_ref="§14 Abs. 4 Nr. 3 UStG",
            field_keys=["service_description", "items"],
        )
    return None


def _check_service_date(data: Dict[str, Any]) -> Optional[ValidationFinding]:
    dt = (
        data.get("service_date")
        or data.get("delivery_date")
        or data.get("leistungsdatum")
        or data.get("invoice_date")
        or data.get("zahlungsdatum")
        or data.get("payment_date")
    )
    if not _is_non_empty(dt):
        return ValidationFinding(
            code="A4_service_date",
            severity="error",
            message="Zeitpunkt der Lieferung/Leistung oder Zahlung fehlt.",
            law_ref="§14 Abs. 4 Nr. 4 UStG",
            field_keys=["service_date", "delivery_date", "invoice_date"],
        )
    if isinstance(dt, str) and not _looks_like_date(dt):
        return ValidationFinding(
            code="A4_service_date_format",
            severity="warning",
            message="Das angegebene Liefer-/Leistungsdatum hat kein erkanntes Datumsformat.",
            law_ref="§14 Abs. 4 Nr. 4 UStG",
            field_keys=["service_date", "delivery_date", "invoice_date"],
        )
    return None


def _check_consideration_tax(data: Dict[str, Any]) -> Optional[ValidationFinding]:
    net = _to_decimal(data.get("net_amount") or data.get("netto") or data.get("net"))
    tax = _to_decimal(data.get("tax_amount") or data.get("umsatzsteuer") or data.get("vat"))
    rate = data.get("tax_rate") or data.get("steuersatz") or data.get("vat_rate")
    missing = []
    if net is None:
        missing.append("net_amount")
    if tax is None:
        missing.append("tax_amount")
    if not _is_non_empty(rate):
        missing.append("tax_rate")
    if missing:
        return ValidationFinding(
            code="A5_consideration_tax",
            severity="error",
            message="Entgelt und/oder Steuerbeträge und/oder Steuersatz fehlen oder sind nicht numerisch.",
            law_ref="§14 Abs. 4 Nr. 5 UStG",
            field_keys=missing,
        )
    return None


def _check_gross_or_exemption(data: Dict[str, Any]) -> Optional[ValidationFinding]:
    gross = _to_decimal(data.get("gross_amount") or data.get("brutto") or data.get("total"))
    net = _to_decimal(data.get("net_amount") or data.get("netto") or data.get("net"))
    tax = _to_decimal(data.get("tax_amount") or data.get("umsatzsteuer") or data.get("vat"))
    exemption = data.get("tax_exemption") or data.get("steuerbefreiung") or data.get("reverse_charge")

    if gross is None and not _is_non_empty(exemption):
        return ValidationFinding(
            code="A6_gross_or_exemption",
            severity="error",
            message="Zahlungsbetrag (brutto) fehlt und es liegt kein Hinweis auf Steuerbefreiung vor.",
            law_ref="§14 Abs. 4 Nr. 6 UStG",
            field_keys=["gross_amount", "tax_exemption"],
        )

    if gross is not None and net is not None and tax is not None:
        expected = net + tax
        if gross != expected:
            return ValidationFinding(
                code="A6_amount_mismatch",
                severity="warning",
                message=f"Rechenabweichung: netto ({net}) + Steuer ({tax}) = {expected}, angegeben brutto = {gross}.",
                law_ref="§14 Abs. 4 Nr. 5, 6 UStG",
                field_keys=["net_amount", "tax_amount", "gross_amount"],
            )
    return None


def _check_special_cases(data: Dict[str, Any]) -> Optional[ValidationFinding]:
    """
    Nr. 7 ist nur bei bestimmten Sonderfällen zwingend (z.B. innergemeinschaftliche
    Lieferungen/Leistungen). Wir prüfen hier nur, ob ein relevanter Hinweis im Text
    vorliegt und dann ggf. fehlende Zusatzangaben beanstanden.
    """
    text = str(data.get("_raw_text", ""))
    # Heuristik: innergemeinschaftliche Begriffe ohne USt-IdNr. -> Mangel
    ic_terms = ["innergemeinschaftlich", "ausländisch", "EU-Ausland", "reverse charge", "Art. 196"]
    if any(term.lower() in text.lower() for term in ic_terms):
        vat_id = data.get("supplier_vat_id") or data.get("customer_vat_id") or data.get("umsatzsteuer_id")
        if not _is_non_empty(vat_id):
            return ValidationFinding(
                code="A7_special_cases_vat_id",
                severity="warning",
                message="Hinweis auf innergemeinschaftliche Sonderregelung ohne USt-IdNr. / erforderliche Zusatzangabe.",
                law_ref="§14 Abs. 4 Nr. 7 UStG",
                field_keys=["supplier_vat_id", "customer_vat_id"],
            )
    return None


# ---------------------------------------------------------------------------
# Haupt-API
# ---------------------------------------------------------------------------

def validate_invoice(data: Dict[str, Any]) -> ValidationReport:
    """
    Prüft eine Rechnung auf die Pflichtangaben des §14 Abs. 4 UStG.

    Parameter:
        data: dict mit Rechnungsfeldern. Unterstützte Keys:
            supplier_name, supplier_address, customer_name, customer_address,
            service_description / items, service_date / delivery_date / invoice_date,
            net_amount / netto, tax_amount / umsatzsteuer / vat,
            tax_rate / steuersatz / vat_rate, gross_amount / brutto / total,
            tax_exemption, supplier_vat_id, customer_vat_id,
            invoice_number, _raw_text.

    Rückgabe:
        ValidationReport mit ok=True/False und Liste der Mängel.
    """
    findings: List[ValidationFinding] = []
    for checker in (
        _check_supplier_identity,
        _check_customer_identity,
        _check_service_description,
        _check_service_date,
        _check_consideration_tax,
        _check_gross_or_exemption,
        _check_special_cases,
    ):
        finding = checker(data)
        if finding:
            findings.append(finding)

    errors = [f for f in findings if f.severity == "error"]
    checked = [
        "A1_supplier_identity",
        "A2_customer_identity",
        "A3_service_description",
        "A4_service_date",
        "A5_consideration_tax",
        "A6_gross_or_exemption",
        "A7_special_cases",
    ]
    return ValidationReport(
        ok=len(errors) == 0,
        invoice_number=_extract_invoice_number(data),
        findings=findings,
        checked_fields=checked,
    )


def validate_invoice_text(text: str) -> ValidationReport:
    """
    Heuristische Extraktion von Rechnungsdaten aus Freitext und anschließende Validierung.
    """
    data: Dict[str, Any] = {"_raw_text": text}
    # Einfache Regex-Extraktion
    patterns = {
        "invoice_number": [
            r"Rechnungsnummer[\s:]+([A-Za-z0-9\-/]+)",
            r"Rechnung\s+(?:Nr\.?|Nummer)[\s:]+([A-Za-z0-9\-/]+)",
        ],
        "invoice_date": [
            r"Rechnungsdatum[\s:]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
            r"Datum[\s:]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
        ],
        "net_amount": [
            r"Nettobetrag[\s:]+([\d.,]+)",
            r"Netto[\s:]+([\d.,]+)",
        ],
        "tax_amount": [
            r"USt\.?[\s:]+([\d.,]+)",
            r"MwSt\.?[\s:]+([\d.,]+)",
            r"Steuer[\s:]+([\d.,]+)",
        ],
        "gross_amount": [
            r"Brutto[\s:]+([\d.,]+)",
            r"Gesamtbetrag[\s:]+([\d.,]+)",
            r"Zahlungsbetrag[\s:]+([\d.,]+)",
        ],
        "tax_rate": [
            r"(\d{1,2})\s*%\s*USt",
            r"(\d{1,2})\s*%\s*MwSt",
            r"Steuersatz[\s:]+(\d{1,2})\s*%",
        ],
    }
    for key, regex_list in patterns.items():
        for pattern in regex_list:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                data[key] = match.group(1).strip()
                break

    # Liefer-/Leistungsdatum extrahieren
    service_match = re.search(
        r"(?:Leistungsdatum|Lieferdatum|Leistungszeitraum)[\s:]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
        text,
        re.IGNORECASE,
    )
    if service_match:
        data["service_date"] = service_match.group(1)

    # Supplier / Customer aus Block oberhalb der Positionen heuristisch
    supplier_match = re.search(
        r"(?:Rechnungssteller|Lieferant|von|from)[:\s]+([A-Z][^\n]{5,100})\n?\s*([A-Z][^\n]{5,100})",
        text,
        re.IGNORECASE,
    )
    if supplier_match:
        data["supplier_name"] = supplier_match.group(1).strip()
        data["supplier_address"] = supplier_match.group(2).strip()

    customer_match = re.search(
        r"(?:Kunde|Leistungsempfänger|an|to)[:\s]+([A-Z][^\n]{5,100})\n?\s*([A-Z][^\n]{5,100})",
        text,
        re.IGNORECASE,
    )
    if customer_match:
        data["customer_name"] = customer_match.group(1).strip()
        data["customer_address"] = customer_match.group(2).strip()

    # Leistungsbeschreibung: Zeilen mit €-Beträgen oder Positionsbeschreibungen
    items = []
    for line in text.splitlines():
        if re.search(r"\d+[.,]?\d*\s*(?:EUR|€|Stk\.?|Std\.?)", line):
            items.append(line.strip())
    if items:
        data["items"] = items

    return validate_invoice(data)


def generate_dispute_letter(
    report: ValidationReport,
    ctx: DisputeContext,
    *,
    detailed: bool = True,
    deadline_days: int = 14,
) -> str:
    """
    Erzeugt einen formellen Bestreitungsbrief / Mängelrüge wegen fehlender
    Rechnungspflichtangaben nach §14 Abs. 4 UStG.

    Parameter:
        report: ValidationReport mit Mängelliste.
        ctx: Adressaten- und Absenderdaten sowie Rechnungsreferenz.
        detailed: Wenn True, werden alle Mängel einzeln aufgeführt.
        deadline_days: Frist in Tagen für Nachbesserung.

    Rückgabe:
        Brief als mehrzeiliger String (deutsch).
    """
    if report.ok and not report.findings:
        raise ValueError("Rechnung ist formal korrekt; kein Bestreitungsbrief erforderlich.")

    today = date.today().strftime("%d.%m.%Y")
    deadline = (date.today() + __import__("datetime").timedelta(days=deadline_days)).strftime("%d.%m.%Y")

    lines: List[str] = []
    lines.append(ctx.sender_name)
    lines.append(ctx.sender_address)
    lines.append("")
    lines.append(ctx.addressee_name)
    lines.append(ctx.addressee_address)
    lines.append("")
    lines.append(f"Datum: {today}")
    lines.append("")
    lines.append(f"Betreff: Mängelrüge / Bestreitungsbrief zu Ihrer Rechnung {ctx.invoice_number}")
    lines.append(f"Referenz: {ctx.reference}")
    if ctx.invoice_date:
        lines.append(f"Rechnungsdatum: {ctx.invoice_date}")
    if ctx.payment_due:
        lines.append(f"Zahlungsziel: {ctx.payment_due}")
    lines.append("")
    lines.append("Sehr geehrte Damen und Herren,")
    lines.append("")
    lines.append(
        "wir beziehen uns auf Ihre oben genannte Rechnung und bestreiten deren "
        "formelle Ordnungsmäßigkeit wegen fehlender oder unvollständiger Pflichtangaben "
        "gemäß §14 Abs. 4 Umsatzsteuergesetz (UStG)."
    )
    lines.append("")

    if detailed:
        lines.append("Im Einzelnen weisen wir folgende Mängel zurück:")
        lines.append("")
        for idx, finding in enumerate(report.findings, start=1):
            lines.append(f"{idx}. {finding.message}")
            lines.append(f"   Rechtsgrundlage: {finding.law_ref}")
            lines.append(f"   Schwere: {'Fehler' if finding.severity == 'error' else 'Hinweis'}")
            lines.append("")
    else:
        lines.append(
            "Die Rechnung enthält nicht alle gesetzlich vorgeschriebenen Pflichtangaben "
            "nach §14 Abs. 4 UStG."
        )
        lines.append("")

    lines.append(
        "Wir bitten Sie, die genannten Mängel bis spätestens "
        f"{deadline} zu beheben und uns eine berichtigte Rechnung zukommen zu lassen. "
        "Bis zur vollständigen Behebung aller Mängel ist die Zahlung unstreitig zurückbehalten."
    )
    lines.append("")
    lines.append(
        "Dieses Schreiben dient der Wahrung unserer Rechte und stellt keine Anerkennung "
        "des bestehenden oder eines etwaigen künftigen Forderungsbestands dar."
    )
    lines.append("")
    lines.append("Mit freundlichen Grüßen")
    lines.append("")
    lines.append(ctx.sender_name)
    lines.append("")
    lines.append("--")
    lines.append(
        "Hinweis: Dieser Brief wurde maschinell auf Basis einer §14 Abs. 4 UStG "
        "Rechnungsprüfung erstellt. Bitte vor Versand juristisch prüfen."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ocean CAP doc_handler: §14 Abs. 4 UStG Rechnungsprüfung & Dispute Loop"
    )
    parser.add_argument("--invoice", type=Path, help="Pfad zu einer JSON-Rechnungsdatei")
    parser.add_argument("--text", help="Rechnungstext zur Validierung")
    parser.add_argument("--dispute", action="store_true", help="Bestreitungsbrief generieren")
    parser.add_argument(
        "--output", type=Path, help="Ausgabedatei für Report oder Brief"
    )
    parser.add_argument(
        "--sender-name", default="Max Mustermann", help="Absendername für Bestreitungsbrief"
    )
    parser.add_argument(
        "--sender-address",
        default="Musterstraße 1, 12345 Musterstadt",
        help="Absenderadresse für Bestreitungsbrief",
    )
    parser.add_argument(
        "--addressee-name", default="Lieferant GmbH", help="Empfängername für Bestreitungsbrief"
    )
    parser.add_argument(
        "--addressee-address",
        default="Lieferstraße 2, 54321 Lieferstadt",
        help="Empfängeradresse für Bestreitungsbrief",
    )
    parser.add_argument("--reference", default="Ihr Zeichen / Unser Aktenzeichen", help="Referenzzeile")
    args = parser.parse_args(argv)

    if args.invoice:
        with args.invoice.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        report = validate_invoice(data)
    elif args.text:
        report = validate_invoice_text(args.text)
    else:
        parser.print_help()
        return 1

    output: Dict[str, Any] = {
        "ok": report.ok,
        "invoice_number": report.invoice_number,
        "checked_fields": report.checked_fields,
        "findings": [
            {
                "code": f.code,
                "severity": f.severity,
                "message": f.message,
                "law_ref": f.law_ref,
                "field_keys": f.field_keys,
            }
            for f in report.findings
        ],
    }

    if args.dispute and not report.ok:
        ctx = DisputeContext(
            addressee_name=args.addressee_name,
            addressee_address=args.addressee_address,
            sender_name=args.sender_name,
            sender_address=args.sender_address,
            reference=args.reference,
            invoice_number=report.invoice_number or "unbekannt",
            invoice_date=None,
            payment_due=None,
        )
        letter = generate_dispute_letter(report, ctx)
        output["dispute_letter"] = letter

    text = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)

    return 0 if report.ok else 2  # 0 = ok, 2 = Mängel gefunden


if __name__ == "__main__":
    sys.exit(_main())
