#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
Complexity Scorer - Bewertet Task-Komplexität für intelligente Delegation
==========================================================================

Analysiert Task-Beschreibungen und gibt einen Komplexitäts-Score zurück:
- 0-20: Einfach (Haiku, lokale AI)
- 21-50: Mittel (Sonnet)
- 51-80: Komplex (Opus)
- 81-100: Sehr komplex (Opus mit Extended Context)

Faktoren:
- Textlänge
- Technische Keywords
- Multi-Step Indikatoren
- Code-Anforderungen
- Recherche-Bedarf
- Kreativität
"""

import re
from typing import Dict, Optional, Tuple

# clutch-bridge Integration (Task [1078])
try:
    from .strecken_analyse import (
        StreckenAnalyse, StreckenProfil, get_analyser, analysiere_task
    )
    _STRECKEN_AVAILABLE = True
except ImportError:
    _STRECKEN_AVAILABLE = False


class ComplexityScorer:
    """Bewertet Task-Komplexität für Modell-Delegation."""

    # Keyword-basierte Komplexitäts-Indikatoren
    SIMPLE_KEYWORDS = {
        "zeige", "liste", "anzeige", "status", "info", "check", "prüfe",
        "lies", "öffne", "schließe", "starte", "stoppe", "restart"
    }

    MEDIUM_KEYWORDS = {
        "analysiere", "vergleiche", "finde", "suche", "filter", "sortiere",
        "berechne", "formatiere", "konvertiere", "update", "aktualisiere"
    }

    COMPLEX_KEYWORDS = {
        "entwickle", "implementiere", "erstelle", "designe", "optimiere",
        "refactore", "migriere", "integriere", "debugge", "behebe"
    }

    VERY_COMPLEX_KEYWORDS = {
        "architektur", "framework", "system", "migration", "multi-agent",
        "distributed", "microservice", "security", "performance-optimierung"
    }

    # Code-Indikatoren
    CODE_INDICATORS = [
        r'\bdef\s+\w+', r'\bclass\s+\w+', r'\bimport\s+\w+',
        r'\{[\s\S]*\}', r'function\s+\w+', r'async\s+\w+',
        r'```[\s\S]*```'  # Code-Blöcke
    ]

    # Multi-Step Indikatoren
    MULTI_STEP_INDICATORS = [
        r'\d+\.\s+', r'schritt\s+\d+', r'dann\s+', r'danach\s+',
        r'zuerst\s+.*\s+dann', r'außerdem', r'zusätzlich',
        r'phase\s+\d+', r'teil\s+\d+'
    ]

    def __init__(self):
        self.compiled_code_patterns = [re.compile(p, re.IGNORECASE) for p in self.CODE_INDICATORS]
        self.compiled_step_patterns = [re.compile(p, re.IGNORECASE) for p in self.MULTI_STEP_INDICATORS]

    def score(self, task_description: str) -> Tuple[int, Dict[str, int]]:
        """
        Bewertet Task-Komplexität.

        Args:
            task_description: Task-Beschreibung

        Returns:
            (score, breakdown): Score 0-100 und Detail-Breakdown
        """
        text_lower = task_description.lower()
        breakdown = {}

        # 1. Längen-Score (max 15 Punkte)
        length = len(task_description)
        if length < 50:
            length_score = 5
        elif length < 150:
            length_score = 10
        elif length < 300:
            length_score = 15
        else:
            length_score = 20
        breakdown["length"] = length_score

        # 2. Keyword-basierter Score (max 30 Punkte)
        keyword_score = 0
        if any(kw in text_lower for kw in self.SIMPLE_KEYWORDS):
            keyword_score = 5
        if any(kw in text_lower for kw in self.MEDIUM_KEYWORDS):
            keyword_score = 15
        if any(kw in text_lower for kw in self.COMPLEX_KEYWORDS):
            keyword_score = 25
        if any(kw in text_lower for kw in self.VERY_COMPLEX_KEYWORDS):
            keyword_score = 30
        breakdown["keywords"] = keyword_score

        # 3. Code-Analyse (max 25 Punkte)
        code_score = 0
        code_matches = sum(1 for pattern in self.compiled_code_patterns
                          if pattern.search(task_description))
        if code_matches > 0:
            code_score = min(25, code_matches * 8)
        breakdown["code"] = code_score

        # 4. Multi-Step Erkennung (max 20 Punkte)
        step_score = 0
        step_matches = sum(1 for pattern in self.compiled_step_patterns
                          if pattern.search(task_description))
        if step_matches > 0:
            step_score = min(20, step_matches * 5)
        breakdown["multi_step"] = step_score

        # 5. Technische Terme (max 10 Punkte)
        tech_terms = [
            "api", "endpoint", "database", "sql", "rest", "graphql",
            "authentication", "authorization", "cache", "redis",
            "docker", "kubernetes", "ci/cd", "deployment"
        ]
        tech_score = min(10, sum(3 for term in tech_terms if term in text_lower))
        breakdown["technical"] = tech_score

        # Gesamt-Score
        total_score = min(100, sum(breakdown.values()))

        return total_score, breakdown

    def score_with_strecke(self, task_description: str) -> Tuple[int, Dict]:
        """
        Erweitertes Scoring mit StreckenAnalyse (clutch-bridge).

        Kombiniert den klassischen Score mit der StreckenAnalyse.
        Falls StreckenAnalyse nicht verfügbar, fällt auf score() zurück.

        Returns:
            (score, extended_breakdown) mit StreckenProfil
        """
        score, breakdown = self.score(task_description)

        if _STRECKEN_AVAILABLE:
            profil = get_analyser().analysiere(task_description)
            breakdown["strecke"] = profil.to_dict()
            breakdown["empfohlener_gang"] = profil.empfohlener_gang
            breakdown["token_budget_faktor"] = profil.token_budget_faktor
        else:
            breakdown["strecke"] = None

        return score, breakdown

    def get_strecken_profil(self, task_description: str) -> Optional["StreckenProfil"]:
        """Gibt StreckenProfil zurück oder None wenn nicht verfügbar."""
        if _STRECKEN_AVAILABLE:
            return get_analyser().analysiere(task_description)
        return None

    def get_recommended_model(self, score: int) -> str:
        """
        Empfiehlt Modell basierend auf Score.

        Args:
            score: Komplexitäts-Score 0-100

        Returns:
            Modell-Name: "haiku", "sonnet", "opus"
        """
        if score < 20:
            return "haiku"
        elif score < 50:
            return "sonnet"
        elif score < 80:
            return "opus"
        else:
            return "opus"  # Extended Context für sehr komplexe Tasks

    def get_partner_recommendation(self, score: int, zone: int) -> Dict:
        """
        Empfiehlt Partner basierend auf Score und Budget-Zone.

        Args:
            score: Komplexitäts-Score
            zone: Budget-Zone 1-4

        Returns:
            Dict mit Partner-Empfehlung
        """
        model = self.get_recommended_model(score)

        # Zone-basierte Einschränkungen
        if zone >= 3:  # Zone 3-4: Budget-Einschränkungen
            if model == "opus" and score < 70:
                model = "sonnet"  # Downgrade bei moderater Komplexität

        return {
            "model": model,
            "score": score,
            "zone": zone,
            "cost_tier": "high" if model == "opus" else "medium" if model == "sonnet" else "low"
        }


# Singleton-Instanz für globale Nutzung
_scorer_instance = None

def get_scorer() -> ComplexityScorer:
    """Gibt Singleton-Instanz zurück."""
    global _scorer_instance
    if _scorer_instance is None:
        _scorer_instance = ComplexityScorer()
    return _scorer_instance


def score_task(task_description: str) -> Tuple[int, Dict[str, int]]:
    """
    Convenience-Funktion zum Bewerten eines Tasks.

    Args:
        task_description: Task-Beschreibung

    Returns:
        (score, breakdown)
    """
    scorer = get_scorer()
    return scorer.score(task_description)


if __name__ == "__main__":
    # Test-Cases
    scorer = ComplexityScorer()

    test_cases = [
        ("Zeige mir den Status", "Einfach"),
        ("Analysiere die Logdateien und finde Fehler", "Mittel"),
        ("Implementiere ein neues Authentication-System mit JWT", "Komplex"),
        ("Entwickle eine Multi-Agent Architektur mit verteiltem State-Management", "Sehr komplex")
    ]

    print("=== Complexity Scorer Test ===\n")
    for task, expected in test_cases:
        score, breakdown = scorer.score(task)
        model = scorer.get_recommended_model(score)
        print(f"Task: {task}")
        print(f"  Erwartet: {expected}")
        print(f"  Score: {score}/100")
        print(f"  Modell: {model}")
        print(f"  Breakdown: {breakdown}")
        print()
