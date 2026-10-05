#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit-Tests für tools.ocean.cap.doc_handler und tools.ocean.cap.compliance."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from tools.ocean.cap import compliance, doc_handler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_invoice():
    return {
        "invoice_number": "RE-2026-001",
        "supplier_name": "Lieferant GmbH",
        "supplier_address": "Lieferstraße 2, 54321 Lieferstadt",
        "customer_name": "Kunde AG",
        "customer_address": "Kundenstraße 3, 12345 Kundenstadt",
        "service_description": "Beratungsleistung im Februar 2026",
        "service_date": "15.02.2026",
        "net_amount": "1000,00",
        "tax_amount": "190,00",
        "tax_rate": "19%",
        "gross_amount": "1190,00",
    }


@pytest.fixture
def dispute_ctx():
    return doc_handler.DisputeContext(
        addressee_name="Lieferant GmbH",
        addressee_address="Lieferstraße 2, 54321 Lieferstadt",
        sender_name="Kunde AG",
        sender_address="Kundenstraße 3, 12345 Kundenstadt",
        reference="Aktenzeichen 123/456",
        invoice_number="RE-2026-001",
        invoice_date="15.02.2026",
        payment_due="01.03.2026",
    )


# ---------------------------------------------------------------------------
# compliance.py
# ---------------------------------------------------------------------------

def test_ustg_14a4_schema_registered():
    schema = compliance.REGISTRY.get("ustg_14a4_invoice", "1.0")
    assert schema is not None
    assert schema.domain == "ustg_14a4_invoice"
    assert schema.jurisdiction == "DE"
    assert len(schema.fields) == 7
    field_ids = [f.id for f in schema.fields]
    assert "A7_special_cases" in field_ids


def test_checklist_registry_rejects_non_schema():
    registry = compliance.ChecklistRegistry()
    with pytest.raises(TypeError):
        registry.register("not-a-schema")


def test_domains_for_law():
    domains = compliance.REGISTRY.domains_for_law("§14 Abs. 4 Nr. 1 UStG")
    assert "ustg_14a4_invoice" in domains
    assert "invoice_de" in domains


def test_field_by_id():
    field = compliance.USTG_14_BASE.field_by_id("supplier_name")
    assert field is not None
    assert field.law_ref == "§14 Abs. 4 Nr. 1 UStG"


# ---------------------------------------------------------------------------
# doc_handler – validate_invoice
# ---------------------------------------------------------------------------

def test_valid_invoice_report(valid_invoice):
    report = doc_handler.validate_invoice(valid_invoice)
    assert report.ok is True
    assert report.invoice_number == "RE-2026-001"
    assert not any(f.severity == "error" for f in report.findings)
    assert len(report.checked_fields) == 7


def test_missing_supplier_identity():
    report = doc_handler.validate_invoice({})
    assert report.ok is False
    codes = {f.code for f in report.findings}
    assert "A1_supplier_identity" in codes


def test_missing_customer_identity(valid_invoice):
    data = {**valid_invoice, "customer_name": "", "customer_address": None}
    report = doc_handler.validate_invoice(data)
    finding = next(f for f in report.findings if f.code == "A2_customer_identity")
    assert finding.severity == "error"
    assert set(finding.field_keys) == {"customer_name", "customer_address"}


def test_missing_service_description(valid_invoice):
    data = {**valid_invoice, "service_description": "   "}
    report = doc_handler.validate_invoice(data)
    codes = {f.code for f in report.findings}
    assert "A3_service_description" in codes


def test_service_date_warning_for_bad_format(valid_invoice):
    data = {**valid_invoice, "service_date": "nächste Woche"}
    report = doc_handler.validate_invoice(data)
    finding = next(f for f in report.findings if f.code == "A4_service_date_format")
    assert finding.severity == "warning"


def test_consideration_tax_requires_numeric_values(valid_invoice):
    data = {**valid_invoice, "net_amount": "unbekannt", "tax_amount": None}
    report = doc_handler.validate_invoice(data)
    finding = next(f for f in report.findings if f.code == "A5_consideration_tax")
    assert finding.severity == "error"
    assert "net_amount" in finding.field_keys
    assert "tax_amount" in finding.field_keys


def test_amount_mismatch_warning(valid_invoice):
    data = {**valid_invoice, "gross_amount": "1200,00"}
    report = doc_handler.validate_invoice(data)
    finding = next(f for f in report.findings if f.code == "A6_amount_mismatch")
    assert finding.severity == "warning"
    assert "1190" in finding.message
    assert "1200" in finding.message


def test_gross_or_exemption_with_exemption(valid_invoice):
    data = {**valid_invoice, "gross_amount": None, "tax_exemption": "§4 UStG"}
    report = doc_handler.validate_invoice(data)
    assert not any(f.code == "A6_gross_or_exemption" for f in report.findings)


def test_special_cases_vat_id_warning():
    data = {
        "_raw_text": "Dies ist eine innergemeinschaftliche Lieferung.",
        "supplier_name": "EU Supplier SARL",
        "supplier_address": "Rue de Paris, Paris",
        "customer_name": "Kunde AG",
        "customer_address": "Berlin",
        "service_description": "Beratung",
        "service_date": "01.02.2026",
        "net_amount": "1000",
        "tax_amount": "0",
        "tax_rate": "0%",
        "gross_amount": "1000",
        "tax_exemption": "innergemeinschaftliche Leistung",
    }
    report = doc_handler.validate_invoice(data)
    finding = next(f for f in report.findings if f.code == "A7_special_cases_vat_id")
    assert finding.severity == "warning"


# ---------------------------------------------------------------------------
# doc_handler – Freitext-Extraktion
# ---------------------------------------------------------------------------

def test_validate_invoice_text_extraction():
    text = (
        "Rechnung Nr.: RE-2026-042\n"
        "Rechnungsdatum: 04.02.2026\n"
        "Lieferant: ACME GmbH\nHauptstraße 1, 12345 Berlin\n"
        "Kunde: Beispiel AG\nBahnhofstraße 2, 54321 München\n"
        "Beratung 10 Stunden à 100 EUR\n"
        "Netto: 1000,00\n"
        "19 % USt: 190,00\n"
        "Brutto: 1190,00\n"
    )
    report = doc_handler.validate_invoice_text(text)
    assert report.ok is True
    assert report.invoice_number == "RE-2026-042"


def test_validate_invoice_text_finds_errors():
    text = (
        "Rechnung Nr.: RE-2026-043\n"
        "Hier fehlen wichtige Angaben.\n"
    )
    report = doc_handler.validate_invoice_text(text)
    assert report.ok is False
    codes = {f.code for f in report.findings}
    assert "A1_supplier_identity" in codes
    assert "A2_customer_identity" in codes


# ---------------------------------------------------------------------------
# doc_handler – generate_dispute_letter
# ---------------------------------------------------------------------------

def test_generate_dispute_letter_contains_details(valid_invoice, dispute_ctx):
    data = {**valid_invoice, "supplier_name": None}
    report = doc_handler.validate_invoice(data)
    letter = doc_handler.generate_dispute_letter(report, dispute_ctx)
    assert "Mängelrüge" in letter
    assert "Lieferant GmbH" in letter
    assert "Kunde AG" in letter
    assert "RE-2026-001" in letter
    assert "§14 Abs. 4 Nr. 1 UStG" in letter
    assert "A1_supplier_identity" not in letter  # code is not used in detail output


def test_generate_dispute_letter_not_detailed(valid_invoice, dispute_ctx):
    data = {**valid_invoice, "supplier_name": None}
    report = doc_handler.validate_invoice(data)
    letter = doc_handler.generate_dispute_letter(report, dispute_ctx, detailed=False)
    assert "Im Einzelnen" not in letter
    assert "gesetzlich vorgeschriebenen Pflichtangaben" in letter


def test_generate_dispute_letter_raises_on_valid_invoice(valid_invoice, dispute_ctx):
    report = doc_handler.validate_invoice(valid_invoice)
    with pytest.raises(ValueError):
        doc_handler.generate_dispute_letter(report, dispute_ctx)


# ---------------------------------------------------------------------------
# doc_handler – CLI
# ---------------------------------------------------------------------------

def test_cli_with_valid_invoice(valid_invoice):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(valid_invoice, fh)
        path = fh.name
    try:
        result = subprocess.run(
            [sys.executable, "-m", "tools.ocean.cap.doc_handler", "--invoice", path],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["ok"] is True
        assert output["invoice_number"] == "RE-2026-001"
    finally:
        Path(path).unlink(missing_ok=True)


def test_cli_with_invalid_invoice_and_dispute():
    bad_invoice = {
        "invoice_number": "RE-2026-999",
        "supplier_name": "X",
        "supplier_address": "",
        "service_description": "Y",
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(bad_invoice, fh)
        path = fh.name
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.ocean.cap.doc_handler",
                "--invoice",
                path,
                "--dispute",
                "--sender-name",
                "Test AG",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 2
        output = json.loads(result.stdout)
        assert output["ok"] is False
        assert "dispute_letter" in output
        assert "Test AG" in output["dispute_letter"]
    finally:
        Path(path).unlink(missing_ok=True)


def test_cli_text_mode():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.ocean.cap.doc_handler",
            "--text",
            "Rechnung Nr.: RE-TEXT-001\nNetto: 500,00\n19% USt: 95,00\nBrutto: 595,00",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2  # missing identities / description
    output = json.loads(result.stdout)
    assert output["invoice_number"] == "RE-TEXT-001"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
