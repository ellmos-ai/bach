"""
BACH Zero-Trust Model Armor (K9-BOUNDARY Security Interceptor)

Provides lightweight, dependency-free hardening for text that is sent to
or returned by LLMs / sub-agents:

* Evasion detection (space-padding, delimiter stuffing, zero-width chars)
* Automatic PII redaction (IBAN, API keys, credit cards, e-mail, phone)

The module intentionally uses only the Python standard library so it can be
imported in sandboxed / restricted environments without external packages.

Public API:
    scan(text)   -> list of detected evasions
    redact(text) -> text with PII replaced by placeholders
    armor(text)  -> (sanitized_text, findings)
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Evasion pattern definitions
# ---------------------------------------------------------------------------

# Zero-width / invisible unicode characters that can be used to bypass
# naive keyword filters or tokenizers.
ZERO_WIDTH_CHARS = frozenset(
    "\u200b\u200c\u200d\u2060\ufeff\u180e\u200e\u200f\u202a\u202b"
    "\u202c\u202d\u202e\u2061\u2062\u2063\u2064"
)

# Delimiters frequently used to break up banned tokens / patterns.
DELIMITER_CHARS = frozenset(" -_.:,;/|\\+*#~`!@$%^&(){}[]=<>")

# ---------------------------------------------------------------------------
# PII regular expressions
# ---------------------------------------------------------------------------

# Generic IBAN: 2-letter country code followed by 2 check digits and up to 30
# alphanumeric characters, with optional spaces every 4 chars.
_IBAN_RE = re.compile(
    r"\b[A-Z]{2}\d{2}(?:[ ?]?[A-Z0-9]){11,30}\b",
    re.IGNORECASE,
)

# API keys / secrets: common prefixes and high-entropy tokens.
_API_KEY_RE = re.compile(
    r"\b(?:sk|pk|api|secret|token|key|auth|access)[-_]?"
    r"(?:key|token|secret|id|live|test)?\s*[:=]\s*"
    r"[A-Za-z0-9_\-+/]{16,}\b",
    re.IGNORECASE,
)

# Generic secret-ish blobs (no obvious prefix but high entropy).
_SECRET_BLOB_RE = re.compile(
    r"\b(?:[A-Za-z0-9_\-]{20,}|[A-Za-z0-9+/]{32,}={0,2}|[A-Za-z0-9_\-+/=]{24,})\b",
)

# Credit cards: Visa, Mastercard, Amex, Discover, JCB, Diners.
# Allows common delimiters between digit groups.
_CREDIT_CARD_RE = re.compile(
    r"\b(?:4[0-9]{3}|5[1-5][0-9]{2}|3[47][0-9]{2}|3(?:0[0-5]|[68][0-9])"
    r"[0-9]|6(?:011|5[0-9]{2})|(?:2131|1800|35\d{2}))"
    r"[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}"
    r"(?:[-\s]?[0-9]{4})?\b",
)

# E-mail address.
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
)

# Phone numbers (German / international style with delimiters).
# Requires an international prefix (+/00) or a leading German trunk
# zero followed by a delimiter, so long digit-only strings (e.g.
# credit-card numbers) are not mis-detected as phone numbers.
_PHONE_RE = re.compile(
    r"(?:\+|00)(?:49|43|41)?[-\s./]?(?:\(?0\)?[-\s./]?)?"
    r"[1-9][0-9]{1,4}[-\s./]?[0-9]{3,}[-\s./]?[0-9]{3,}"
    r"|"
    r"\b0[1-9][0-9]{1,4}[-\s./][0-9]{3,}[-\s./]?[0-9]{3,}\b",
)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """Single armor finding (evasion or PII leak)."""

    kind: str          # e.g. "space_padding", "zero_width", "iban", "api_key"
    subtype: str       # more specific classification
    start: int
    end: int
    snippet: str       # short normalized preview, never the full secret

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "subtype": self.subtype,
            "start": self.start,
            "end": self.end,
            "snippet": self.snippet,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _snippet(text: str, start: int, end: int, max_len: int = 32) -> str:
    """Return a short, safe preview (no secret material)."""
    window = text[max(0, start) : min(end, len(text))]
    # Strip invisible / evasion chars before previewing.
    cleaned = "".join(c for c in window if c not in ZERO_WIDTH_CHARS)
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 1] + "…"
    return cleaned


def _strip_evasion_chars(text: str) -> str:
    """Remove zero-width / invisible characters used for evasion."""
    return "".join(ch for ch in text if ch not in ZERO_WIDTH_CHARS)


def _collapse_spaces(text: str) -> str:
    """Normalize whitespace to detect space-padding evasion."""
    return re.sub(r"\s+", " ", text)


def _remove_delimiters(text: str) -> str:
    """Remove common delimiter characters used to break tokens."""
    return "".join(ch for ch in text if ch not in DELIMITER_CHARS)


def _normalize(text: str) -> str:
    """Apply all normalization passes used for evasion-resilient matching."""
    return _remove_delimiters(_collapse_spaces(_strip_evasion_chars(text)))


def _luhn_valid(digits: str) -> bool:
    """Validate a digit string using the Luhn algorithm."""
    total = 0
    reverse = digits[::-1]
    for i, ch in enumerate(reverse):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _is_valid_iban(candidate: str) -> bool:
    """Basic IBAN modulo-97 check (ISO 13616)."""
    # Remove spaces.
    compact = candidate.replace(" ", "").upper()
    if len(compact) < 15 or len(compact) > 34:
        return False
    # Move country code + check digits to the end and convert letters to digits.
    rearranged = compact[4:] + compact[:4]
    numeric = "".join(str(ord(ch) - 55) if ch.isalpha() else ch for ch in rearranged)
    try:
        return int(numeric) % 97 == 1
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Scanning functions
# ---------------------------------------------------------------------------


def _scan_zero_width(text: str, findings: list[Finding]) -> None:
    """Detect zero-width / invisible unicode characters."""
    if any(ch in ZERO_WIDTH_CHARS for ch in text):
        findings.append(
            Finding(
                kind="evasion",
                subtype="zero_width_chars",
                start=0,
                end=len(text),
                snippet="[invisible unicode characters detected]",
            )
        )


def _scan_space_padding(text: str, findings: list[Finding]) -> None:
    """Detect excessive whitespace used to break tokens visually."""
    normalized = _collapse_spaces(_strip_evasion_chars(text))
    # Compare length of normalized text vs. compressed text.  If removing
    # whitespace shortens the text by >= 20 %, flag it as padding evasion.
    compact = normalized.replace(" ", "")
    has_high_ratio = len(normalized) > 0 and (len(normalized) - len(compact)) / len(normalized) > 0.20
    has_spaced_word = bool(re.search(r"\b(?:[A-Za-z0-9]\s+){3,}[A-Za-z0-9]\b", text))
    if has_high_ratio or has_spaced_word:
        findings.append(
            Finding(
                kind="evasion",
                subtype="space_padding",
                start=0,
                end=len(text),
                snippet="[excessive whitespace / space-padding detected]",
            )
        )


def _scan_delimiter_evasion(text: str, findings: list[Finding]) -> None:
    """Detect delimiter stuffing used to break up suspicious tokens."""
    # If removing delimiters shortens the text significantly and creates
    # longer alphanumeric runs, it may be an evasion attempt.
    stripped = _remove_delimiters(text)
    if len(text) > 0 and (len(text) - len(stripped)) / len(text) > 0.25:
        # Look for words split by delimiters (e.g. p-a-s-s-w-o-r-d).
        parts = re.split(r"\s+", stripped)
        long_run = any(len(part) >= 8 and part.isalnum() for part in parts)
        if long_run:
            findings.append(
                Finding(
                    kind="evasion",
                    subtype="delimiter_stuffing",
                    start=0,
                    end=len(text),
                    snippet="[delimiter stuffing detected]",
                )
            )


# ---------------------------------------------------------------------------
# Redaction functions
# ---------------------------------------------------------------------------


def _redact_with(
    text: str,
    pattern: re.Pattern,
    placeholder: str,
    validator: Callable[[str], bool] | None = None,
    mask: str | None = None,
) -> tuple[str, list[Finding]]:
    """Replace regex matches with a placeholder and return findings.

    If *mask* is provided it is used as the literal replacement text, while
    the *placeholder* still determines the reported subtype.
    """
    findings: list[Finding] = []
    effective = mask if mask is not None else placeholder

    def repl(match: re.Match) -> str:
        candidate = match.group(0)
        if validator is not None and not validator(candidate):
            return candidate
        findings.append(
            Finding(
                kind="pii",
                subtype=placeholder.strip("[]"),
                start=match.start(),
                end=match.end(),
                snippet=_snippet(text, match.start(), match.end()),
            )
        )
        return effective

    return pattern.sub(repl, text), findings


def redact(text: str, mask: str | None = None) -> tuple[str, list[Finding]]:
    """
    Remove PII from *text*.

    Returns a tuple ``(sanitized_text, findings)``.  The default *mask* can be
    overridden (e.g. ``[PII]``); however, changing the placeholder does not
    influence the ``subtype`` field of the returned findings.
    """
    all_findings: list[Finding] = []
    # When the default placeholder is requested keep per-type labels; only a
    # custom mask should override the literal replacement text.
    effective_mask = mask

    # IBAN
    text, findings = _redact_with(text, _IBAN_RE, "[IBAN]", _is_valid_iban, mask=effective_mask)
    all_findings.extend(findings)

    # Credit cards (validate with Luhn to reduce false positives).
    def _cc_validator(candidate: str) -> bool:
        digits = re.sub(r"\D", "", candidate)
        return 13 <= len(digits) <= 19 and _luhn_valid(digits)

    text, findings = _redact_with(text, _CREDIT_CARD_RE, "[CREDIT_CARD]", _cc_validator, mask=effective_mask)
    all_findings.extend(findings)

    # API keys / explicit secrets.
    text, findings = _redact_with(text, _API_KEY_RE, "[API_KEY]", mask=effective_mask)
    all_findings.extend(findings)

    # E-mail.
    text, findings = _redact_with(text, _EMAIL_RE, "[EMAIL]", mask=effective_mask)
    all_findings.extend(findings)

    # Phone.
    text, findings = _redact_with(text, _PHONE_RE, "[PHONE]", mask=effective_mask)
    all_findings.extend(findings)

    # Generic high-entropy secret blobs only if no other PII matched nearby.
    # This is intentionally conservative to avoid mangling harmless long ids.
    def _blob_filter(candidate: str) -> bool:
        normalized = _normalize(candidate)
        # Require a mix of character classes and reasonable entropy.
        has_digit = any(c.isdigit() for c in normalized)
        has_upper = any(c.isupper() for c in normalized)
        has_lower = any(c.islower() for c in normalized)
        has_symbol = any(c in "_-/+=" for c in normalized)
        variety = sum([has_digit, has_upper, has_lower, has_symbol])
        return variety >= 3 and len(normalized) >= 24

    text, findings = _redact_with(text, _SECRET_BLOB_RE, "[SECRET]", _blob_filter, mask=effective_mask)
    all_findings.extend(findings)

    return text, all_findings


# ---------------------------------------------------------------------------
# Combined armor API
# ---------------------------------------------------------------------------


def scan(text: str) -> list[Finding]:
    """
    Scan *text* for evasion patterns.

    Returns a list of ``Finding`` objects.  The scan is heuristic: it flags
    structural anomalies (zero-width chars, excessive whitespace, delimiter
    stuffing) rather than maintaining a blocklist of banned words.
    """
    findings: list[Finding] = []
    _scan_zero_width(text, findings)
    _scan_space_padding(text, findings)
    _scan_delimiter_evasion(text, findings)
    return findings


def armor(text: str, mask: str | None = None) -> tuple[str, list[Finding]]:
    """
    Run full Model Armor pipeline on *text*.

    Steps:
        1. Detect evasion patterns via ``scan()``.
        2. Redact PII via ``redact()``.
        3. Return the sanitized text and all findings.

    The original text is never returned; all PII is replaced by *mask*.
    """
    findings = scan(text)
    sanitized, pii_findings = redact(text, mask=mask)
    findings.extend(pii_findings)
    return sanitized, findings


# ---------------------------------------------------------------------------
# CLI convenience
# ---------------------------------------------------------------------------


def main(argv: Iterable[str] | None = None) -> int:
    """Tiny CLI for quick manual testing: ``python -m tools.model_armor 'text'``."""
    import sys

    args = list(argv) if argv is not None else sys.argv[1:]
    text = " ".join(args) if args else sys.stdin.read()
    sanitized, findings = armor(text)
    print("SANITIZED:")
    print(sanitized)
    if findings:
        print("\nFINDINGS:")
        for f in findings:
            print(f"  {f.kind}/{f.subtype}: {f.snippet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
