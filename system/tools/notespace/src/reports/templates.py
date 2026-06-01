#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Report Templates - Predefined report structures
================================================

Templates for different report types with customizable sections.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ReportSection:
    """A section in a report template."""
    id: str
    title: str
    prompt_hint: str
    required: bool = True
    order: int = 0


@dataclass
class ReportTemplate:
    """A complete report template."""
    id: str
    name: str
    description: str
    sections: List[ReportSection]
    style_hints: str = ""
    output_formats: List[str] = field(default_factory=lambda: ["md", "pdf"])

    def get_section_prompts(self) -> str:
        """Get formatted section prompts for LLM."""
        lines = []
        for section in sorted(self.sections, key=lambda s: s.order):
            marker = "*" if section.required else ""
            lines.append(f"{section.order}. **{section.title}**{marker} - {section.prompt_hint}")
        return "\n".join(lines)


# Predefined templates
TEMPLATES: Dict[str, ReportTemplate] = {
    "analysis": ReportTemplate(
        id="analysis",
        name="Analysebericht",
        description="Strukturierter Analysebericht mit Erkenntnissen und Empfehlungen",
        sections=[
            ReportSection("summary", "Zusammenfassung", "Kernerkenntnisse in 3-5 Sätzen", True, 1),
            ReportSection("intro", "Einleitung", "Kontext, Hintergrund und Fragestellung", True, 2),
            ReportSection("analysis", "Analyse", "Detaillierte Untersuchung der Kernthemen", True, 3),
            ReportSection("findings", "Erkenntnisse", "Wichtige Befunde und Muster", True, 4),
            ReportSection("conclusions", "Schlussfolgerungen", "Beantwortung der Hauptfrage", True, 5),
            ReportSection("recommendations", "Empfehlungen", "Handlungsvorschläge", False, 6)
        ],
        style_hints="Professionell, sachlich, gut strukturiert"
    ),

    "summary": ReportTemplate(
        id="summary",
        name="Zusammenfassung",
        description="Kurze, prägnante Zusammenfassung der Dokumente",
        sections=[
            ReportSection("overview", "Überblick", "Was behandeln die Dokumente?", True, 1),
            ReportSection("keypoints", "Kernpunkte", "Die wichtigsten Aussagen als Stichpunkte", True, 2),
            ReportSection("conclusion", "Fazit", "Gesamtbild in 2-3 Sätzen", True, 3)
        ],
        style_hints="Kurz, prägnant, auf das Wesentliche fokussiert",
        output_formats=["md"]
    ),

    "research": ReportTemplate(
        id="research",
        name="Forschungsbericht",
        description="Wissenschaftlich strukturierter Bericht mit Quellenverweisen",
        sections=[
            ReportSection("abstract", "Abstract", "Zusammenfassung der Forschung", True, 1),
            ReportSection("intro", "Einleitung", "Hintergrund und Forschungsfrage", True, 2),
            ReportSection("methods", "Methodik", "Analysemethoden und Vorgehen", True, 3),
            ReportSection("results", "Ergebnisse", "Detaillierte Befunde", True, 4),
            ReportSection("discussion", "Diskussion", "Interpretation und Einordnung", True, 5),
            ReportSection("conclusion", "Schlussfolgerungen", "Beantwortung der Forschungsfrage", True, 6),
            ReportSection("references", "Quellenverweise", "Bezüge zu den Dokumenten", False, 7)
        ],
        style_hints="Akademisch, objektiv, mit Quellenverweisen",
        output_formats=["md", "pdf", "docx"]
    ),

    "comparison": ReportTemplate(
        id="comparison",
        name="Vergleichsbericht",
        description="Systematischer Vergleich mehrerer Dokumente",
        sections=[
            ReportSection("overview", "Überblick", "Was wird verglichen?", True, 1),
            ReportSection("similarities", "Gemeinsamkeiten", "Übereinstimmungen zwischen Dokumenten", True, 2),
            ReportSection("differences", "Unterschiede", "Abweichungen und Kontraste", True, 3),
            ReportSection("matrix", "Vergleichsmatrix", "Tabellarische Gegenüberstellung", False, 4),
            ReportSection("evaluation", "Bewertung", "Stärken und Schwächen", True, 5),
            ReportSection("conclusion", "Fazit", "Gesamtbewertung des Vergleichs", True, 6)
        ],
        style_hints="Systematisch, neutral, mit klaren Kriterien",
        output_formats=["md", "pdf"]
    ),

    "executive": ReportTemplate(
        id="executive",
        name="Executive Summary",
        description="Kompakte Zusammenfassung für Entscheidungsträger",
        sections=[
            ReportSection("situation", "Situation", "Aktueller Stand und Kontext", True, 1),
            ReportSection("findings", "Kernbefunde", "Die 3-5 wichtigsten Erkenntnisse", True, 2),
            ReportSection("implications", "Implikationen", "Was bedeutet das?", True, 3),
            ReportSection("actions", "Handlungsoptionen", "Mögliche nächste Schritte", True, 4)
        ],
        style_hints="Prägnant, handlungsorientiert, für schnelle Erfassung",
        output_formats=["md", "pdf"]
    ),

    "technical": ReportTemplate(
        id="technical",
        name="Technischer Bericht",
        description="Detaillierter technischer Analysebericht",
        sections=[
            ReportSection("executive", "Executive Summary", "Kurzfassung für Management", True, 1),
            ReportSection("intro", "Einleitung", "Technischer Kontext und Ziele", True, 2),
            ReportSection("architecture", "Architektur/Struktur", "Technische Struktur", False, 3),
            ReportSection("analysis", "Technische Analyse", "Detaillierte technische Untersuchung", True, 4),
            ReportSection("issues", "Probleme/Risiken", "Identifizierte Issues", True, 5),
            ReportSection("solutions", "Lösungsvorschläge", "Technische Empfehlungen", True, 6),
            ReportSection("appendix", "Anhang", "Zusätzliche technische Details", False, 7)
        ],
        style_hints="Technisch präzise, mit Fachbegriffen, strukturiert",
        output_formats=["md", "pdf", "docx"]
    )
}


def get_template(template_id: str) -> Optional[ReportTemplate]:
    """Get a report template by ID."""
    return TEMPLATES.get(template_id)


def list_templates() -> List[Dict]:
    """List all available templates."""
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "sections": len(t.sections),
            "formats": t.output_formats
        }
        for t in TEMPLATES.values()
    ]


def create_custom_template(
    id: str,
    name: str,
    description: str,
    sections: List[Dict],
    style_hints: str = "",
    output_formats: List[str] = None
) -> ReportTemplate:
    """
    Create a custom report template.

    Args:
        id: Unique template ID
        name: Display name
        description: Template description
        sections: List of section dicts with keys: id, title, prompt_hint, required, order
        style_hints: Style guidance for the LLM
        output_formats: List of output formats

    Returns:
        ReportTemplate instance
    """
    template_sections = [
        ReportSection(
            id=s["id"],
            title=s["title"],
            prompt_hint=s.get("prompt_hint", ""),
            required=s.get("required", True),
            order=s.get("order", i)
        )
        for i, s in enumerate(sections)
    ]

    return ReportTemplate(
        id=id,
        name=name,
        description=description,
        sections=template_sections,
        style_hints=style_hints,
        output_formats=output_formats or ["md", "pdf"]
    )
