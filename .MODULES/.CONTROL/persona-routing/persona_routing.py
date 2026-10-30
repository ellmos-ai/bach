# coding: utf-8
"""Ocean Control-Modul: persona-routing (#2446).
Stellt das Rollenrouting bereit und reduziert die standardmäßig aktiven
Systemagenten auf genau zwei (coordinator, expert), während alle bisherigen
BACH-Bosse und Fachexperten als inaktive Vorlagen in der Agenten-Bibliothek liegen.
"""
from __future__ import annotations
from typing import Any

DEFAULT_ACTIVE_SYSTEM_AGENTS: tuple[dict[str, Any], ...] = (
    {
        "id": "coordinator",
        "name": "coordinator",
        "title": "Koordinator (System-Boss)",
        "kind": "agent",
        "origin": "system",
        "is_template": False,
        "active_by_default": True,
        "default_access": "api",
        "domains": ["general", "orchestration", "tasks", "system"],
    },
    {
        "id": "expert",
        "name": "expert",
        "title": "Fachexperte (Domänen-Spezialist)",
        "kind": "agent",
        "origin": "system",
        "is_template": False,
        "active_by_default": True,
        "default_access": "api",
        "domains": ["domain", "analysis", "specialist"],
    },
)

LEGACY_BACH_PERSONA_TEMPLATES: tuple[dict[str, Any], ...] = (
    {"id": "ati", "title": "ATI (Technik- & Entwicklungs-Boss)", "domain": "dev", "keywords": ["code", "bug", "git", "python", "test"]},
    {"id": "steuer", "title": "Steuer- & Finanzexperte", "domain": "finance", "keywords": ["steuer", "elster", "finanzamt", "beleg", "rechnung"]},
    {"id": "paedagogik", "title": "Pädagogik- & Förderplan-Experte", "domain": "pedagogy", "keywords": ["förderplan", "icf", "klient", "schule", "therapie"]},
    {"id": "gesundheit", "title": "Gesundheits- & Medizinexperte", "domain": "health", "keywords": ["medizin", "labor", "symptom", "arzt", "gesundheit"]},
    {"id": "recht", "title": "Rechts- & Vertragsprüfer", "domain": "legal", "keywords": ["vertrag", "frist", "paragraph", "recht", "klausel"]},
    {"id": "forschung", "title": "Forschungs- & Literaturexperte", "domain": "research", "keywords": ["paper", "doi", "arxiv", "studie", "zitat"]},
)


def list_persona_catalog() -> dict[str, Any]:
    """Liefert die 2 aktiven Standard-Systemagenten und die inaktiven Bibliotheksvorlagen."""
    templates = [
        {
            **tpl,
            "kind": "role",
            "origin": "system",
            "is_template": True,
            "active_by_default": False,
            "default_access": "api",
        }
        for tpl in LEGACY_BACH_PERSONA_TEMPLATES
    ]
    return {
        "active_system_agents": [dict(a) for a in DEFAULT_ACTIVE_SYSTEM_AGENTS],
        "library_templates": templates,
    }


def resolve_persona_route(query: str, *, enabled_templates: set[str] | None = None) -> dict[str, Any]:
    """Routet eine Anfrage auf die passende Rolle; ist eine Spezialvorlage nicht
    explizit aktiviert, übernimmt der Standard-Systemagent ('expert' bei Fachbezug,
    sonst 'coordinator') mit Verweis auf die empfohlene Bibliotheksvorlage.
    """
    q_low = (query or "").lower()
    enabled = enabled_templates or set()

    matched_tpl = None
    for tpl in LEGACY_BACH_PERSONA_TEMPLATES:
        if any(kw in q_low for kw in tpl["keywords"]):
            matched_tpl = tpl
            break

    if matched_tpl is not None:
        tid = matched_tpl["id"]
        if tid in enabled:
            return {
                "selected_agent": tid,
                "mode": "activated_template",
                "domain": matched_tpl["domain"],
                "recommended_template": tid,
            }
        return {
            "selected_agent": "expert",
            "mode": "default_system_expert",
            "domain": matched_tpl["domain"],
            "recommended_template": tid,
        }

    return {
        "selected_agent": "coordinator",
        "mode": "default_system_coordinator",
        "domain": "general",
        "recommended_template": None,
    }
