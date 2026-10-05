"""Tests for tools.model_armor."""

from tools import model_armor


# ---------------------------------------------------------------------------
# Scan / evasion detection
# ---------------------------------------------------------------------------


def test_scan_clean_text_has_no_findings():
    text = "Hello world, this is a completely normal sentence for testing."
    assert model_armor.scan(text) == []


def test_scan_detects_zero_width_chars():
    text = "pass\u200bword"
    findings = model_armor.scan(text)
    assert any(f.kind == "evasion" and f.subtype == "zero_width_chars" for f in findings)


def test_scan_detects_space_padding():
    text = "p a s s w o r d injection"
    findings = model_armor.scan(text)
    assert any(f.kind == "evasion" and f.subtype == "space_padding" for f in findings)


def test_scan_detects_delimiter_stuffing():
    text = "p-a-s-s-w-o-r-d bypass"
    findings = model_armor.scan(text)
    assert any(
        f.kind == "evasion" and f.subtype == "delimiter_stuffing" for f in findings
    )


# ---------------------------------------------------------------------------
# PII redaction
# ---------------------------------------------------------------------------


def test_redact_iban_valid():
    text = "My IBAN is DE89370400440532013000."
    sanitized, findings = model_armor.redact(text)
    assert "[IBAN]" in sanitized
    assert not any("DE89" in token for token in sanitized.split())
    assert any(f.kind == "pii" and f.subtype == "IBAN" for f in findings)


def test_redact_iban_invalid_not_redacted():
    # Last digit changed so mod-97 check fails.
    text = "My IBAN is DE89370400440532013001."
    sanitized, findings = model_armor.redact(text)
    assert "[IBAN]" not in sanitized
    assert not any(f.subtype == "IBAN" for f in findings)


def test_redact_credit_card_valid():
    text = "Card: 4532015112830366 expires soon."
    sanitized, findings = model_armor.redact(text)
    assert "[CREDIT_CARD]" in sanitized
    assert "4532015112830366" not in sanitized
    assert any(f.kind == "pii" and f.subtype == "CREDIT_CARD" for f in findings)


def test_redact_credit_card_invalid_luhn_not_redacted():
    text = "Card: 4532015112830367 expires soon."
    sanitized, findings = model_armor.redact(text)
    assert "[CREDIT_CARD]" not in sanitized
    assert "4532015112830367" in sanitized


def test_redact_api_key():
    text = "api_key=ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
    sanitized, findings = model_armor.redact(text)
    assert "[API_KEY]" in sanitized
    assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456" not in sanitized
    assert any(f.kind == "pii" and f.subtype == "API_KEY" for f in findings)


def test_redact_email():
    text = "Contact alice@example.com please."
    sanitized, findings = model_armor.redact(text)
    assert "[EMAIL]" in sanitized
    assert "alice@example.com" not in sanitized
    assert any(f.kind == "pii" and f.subtype == "EMAIL" for f in findings)


def test_redact_phone():
    text = "Call +49 170 1234567."
    sanitized, findings = model_armor.redact(text)
    assert "[PHONE]" in sanitized
    assert "+49 170 1234567" not in sanitized
    assert any(f.kind == "pii" and f.subtype == "PHONE" for f in findings)


def test_redact_secret_blob():
    text = "token is Ab1_cD2/eF3+gH4=jK5_lM6nO7pQ8rS9"
    sanitized, findings = model_armor.redact(text)
    assert "[SECRET]" in sanitized
    assert "Ab1_cD2/eF3+gH4=jK5_lM6nO7pQ8rS9" not in sanitized
    assert any(f.kind == "pii" and f.subtype == "SECRET" for f in findings)


def test_redact_custom_mask_replaces_all_placeholders():
    text = "Email: alice@example.com and phone +49 170 1234567"
    sanitized, findings = model_armor.redact(text, mask="[PII]")
    assert "[PII]" in sanitized
    assert "[EMAIL]" not in sanitized
    assert "[PHONE]" not in sanitized
    assert any(f.subtype == "EMAIL" for f in findings)
    assert any(f.subtype == "PHONE" for f in findings)


# ---------------------------------------------------------------------------
# Combined armor API
# ---------------------------------------------------------------------------


def test_armor_combines_scan_and_redact():
    text = "api_key=sk-abcdefghijklmnopqrstuvwxyz123456 and email: user@example.com"
    sanitized, findings = model_armor.armor(text, mask="[REDACTED]")
    assert "[REDACTED]" in sanitized
    kinds = {f.kind for f in findings}
    assert "pii" in kinds


def test_armor_detects_evasion_and_redacts_pii():
    text = "p a s s w o r d leak: secret=sk-1234567890abcdef1234567890abcdef"
    sanitized, findings = model_armor.armor(text)
    evasion_kinds = {f.subtype for f in findings if f.kind == "evasion"}
    assert "space_padding" in evasion_kinds
    assert any(f.subtype == "API_KEY" for f in findings)
    assert "[API_KEY]" in sanitized or "[REDACTED]" in sanitized


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


def test_finding_to_dict():
    finding = model_armor.Finding(
        kind="x", subtype="y", start=0, end=1, snippet="z"
    )
    assert finding.to_dict() == {
        "kind": "x",
        "subtype": "y",
        "start": 0,
        "end": 1,
        "snippet": "z",
    }


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


def test_main_returns_zero():
    assert model_armor.main(["hello", "world"]) == 0
