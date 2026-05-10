# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Shared heuristics for provenance, people scope, and privacy hints."""

from __future__ import annotations

from datetime import datetime


SENSITIVE_KEYWORDS = (
    "adresse",
    "anschrift",
    "arzt",
    "bank",
    "chat_id",
    "diagnose",
    "email",
    "geburt",
    "gesundheit",
    "iban",
    "insurance",
    "konto",
    "labor",
    "medik",
    "patient",
    "password",
    "secret",
    "steuer",
    "telegram",
    "telefon",
    "therapy",
    "token",
    "versicherung",
)

PARTNER_KEYWORDS = (
    "claude",
    "codex",
    "copilot",
    "gemini",
    "gpt",
    "ollama",
    "partner",
    "perplexity",
    "session_",
    "user",
)

DOMAIN_KEYWORDS = (
    "bug",
    "docs",
    "plugin",
    "registry",
    "roadmap",
    "scheduler",
    "skill",
    "task",
    "usecase",
    "wiki",
    "workflow",
)


def truncate_text(text: str | None, limit: int = 88) -> str:
    """Return a single-line preview."""
    if not text:
        return "-"
    normalized = " ".join(str(text).split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def format_timestamp(value: str | None) -> str:
    """Format common ISO/SQLite timestamps for compact CLI output."""
    if not value:
        return "-"
    raw = str(value).strip()
    if not raw:
        return "-"
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return raw[:16] if len(raw) >= 16 else raw


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


def classify_people_scope(
    *,
    text: str = "",
    category: str = "",
    source: str = "",
    path: str = "",
    partner_id: str = "",
) -> tuple[str, str]:
    """Return a coarse people-scope label plus short rationale."""
    haystack = " ".join(
        part for part in (text, category, source, path, partner_id) if part
    )

    if category == "user" or _contains_any(haystack, SENSITIVE_KEYWORDS):
        return (
            "personenbezogen",
            "Enthält persönliche oder sensible Bezüge.",
        )

    if path.startswith("docs/help"):
        return (
            "systemisch",
            "Interne Help- oder Systemdokumentation ohne primären Personenfokus.",
        )

    if partner_id or _contains_any(haystack, PARTNER_KEYWORDS):
        return (
            "partnerbezogen",
            "Bezieht sich auf eine Session, einen Partner oder Chat-Kontext.",
        )

    if _contains_any(haystack, DOMAIN_KEYWORDS):
        return (
            "fachbezogen",
            "Domänen- oder arbeitsbezogener Inhalt ohne klaren Personenfokus.",
        )

    return (
        "systemisch",
        "Technischer oder allgemeiner Systembezug ohne erkennbaren Personenfokus.",
    )


def classify_privacy(
    *,
    text: str = "",
    category: str = "",
    source: str = "",
    path: str = "",
    partner_id: str = "",
    people_scope: str = "",
) -> tuple[str, str]:
    """Return a coarse privacy label plus handling hint."""
    haystack = " ".join(
        part for part in (text, category, source, path, partner_id, people_scope) if part
    )

    if _contains_any(haystack, ("api_key", "chat_id", "iban", "password", "secret", "token")):
        return (
            "sensibel",
            "Nicht in öffentliche Doku, Logs oder Telemetrie übernehmen.",
        )

    if people_scope == "personenbezogen":
        return (
            "vertraulich",
            "Nur intern und mit Datensparsamkeit weitergeben.",
        )

    if people_scope == "partnerbezogen":
        return (
            "intern",
            "Session- oder Partnerkontext nur intern referenzieren.",
        )

    if path.startswith("docs/help") or category in {"help", "system"}:
        return (
            "intern",
            "Interne Systemreferenz; extern nur nach Review teilen.",
        )

    return (
        "niedrig",
        "Geringes Risiko, dennoch vor externer Weitergabe kurz prüfen.",
    )
