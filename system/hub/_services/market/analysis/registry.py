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
FinancialProof - Analyse-Registry
Zentrales Register für alle verfügbaren Analyse-Algorithmen
"""
from typing import Dict, List, Type, Optional, Any
try:
    from .base import BaseAnalyzer, AnalysisCategory
except ImportError:
    from analysis.base import BaseAnalyzer, AnalysisCategory


class AnalysisRegistry:
    """
    Zentrales Register für alle Analyse-Algorithmen.

    Ermöglicht dynamische Registrierung und Abfrage von Analyzern.
    """

    _analyzers: Dict[str, Type[BaseAnalyzer]] = {}
    _instances: Dict[str, BaseAnalyzer] = {}

    @classmethod
    def register(cls, analyzer_class: Type[BaseAnalyzer]) -> Type[BaseAnalyzer]:
        """
        Registriert einen Analyzer.

        Kann als Decorator verwendet werden:

            @AnalysisRegistry.register
            class MyAnalyzer(BaseAnalyzer):
                ...

        Args:
            analyzer_class: Die Analyzer-Klasse

        Returns:
            Die gleiche Klasse (für Decorator-Verwendung)
        """
        name = analyzer_class.name
        if name in cls._analyzers:
            raise ValueError(f"Analyzer '{name}' ist bereits registriert")

        cls._analyzers[name] = analyzer_class
        return analyzer_class

    @classmethod
    def unregister(cls, name: str):
        """Entfernt einen Analyzer aus dem Register"""
        if name in cls._analyzers:
            del cls._analyzers[name]
        if name in cls._instances:
            del cls._instances[name]

    @classmethod
    def get(cls, name: str) -> Optional[BaseAnalyzer]:
        """
        Gibt eine Analyzer-Instanz zurück.

        Erstellt eine neue Instanz wenn nötig (Singleton-Pattern).

        Args:
            name: Name des Analyzers

        Returns:
            Analyzer-Instanz oder None
        """
        if name not in cls._analyzers:
            return None

        if name not in cls._instances:
            cls._instances[name] = cls._analyzers[name]()

        # Reset vor Verwendung
        cls._instances[name].reset()
        return cls._instances[name]

    @classmethod
    def get_class(cls, name: str) -> Optional[Type[BaseAnalyzer]]:
        """Gibt die Analyzer-Klasse zurück"""
        return cls._analyzers.get(name)

    @classmethod
    def list_all(cls) -> List[Dict[str, Any]]:
        """
        Gibt Informationen über alle registrierten Analyzer zurück.

        Returns:
            Liste von Info-Dicts für jeden Analyzer
        """
        return [
            analyzer_class.get_info()
            for analyzer_class in cls._analyzers.values()
        ]

    @classmethod
    def list_by_category(cls, category: AnalysisCategory) -> List[Dict[str, Any]]:
        """
        Gibt Analyzer einer bestimmten Kategorie zurück.

        Args:
            category: Die gewünschte Kategorie

        Returns:
            Liste von Info-Dicts
        """
        return [
            analyzer_class.get_info()
            for analyzer_class in cls._analyzers.values()
            if analyzer_class.category == category
        ]

    @classmethod
    def list_names(cls) -> List[str]:
        """Gibt alle registrierten Analyzer-Namen zurück"""
        return list(cls._analyzers.keys())

    @classmethod
    def exists(cls, name: str) -> bool:
        """Prüft ob ein Analyzer existiert"""
        return name in cls._analyzers

    @classmethod
    def get_categories(cls) -> Dict[str, List[str]]:
        """
        Gruppiert Analyzer nach Kategorie.

        Returns:
            Dict {category_name: [analyzer_names]}
        """
        categories: Dict[str, List[str]] = {}

        for name, analyzer_class in cls._analyzers.items():
            cat = analyzer_class.category.value
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(name)

        return categories

    @classmethod
    def clear(cls):
        """Löscht alle Registrierungen (für Tests)"""
        cls._analyzers.clear()
        cls._instances.clear()


# ===== INITIALISIERUNG =====
# Importiere und registriere alle Analyzer beim Laden des Moduls

def _register_all_analyzers():
    """
    Importiert und registriert alle verfügbaren Analyzer.

    Wird beim Laden des Moduls aufgerufen.
    """
    # Die Imports müssen hier sein um zirkuläre Imports zu vermeiden
    try:
        from .statistical.arima import ARIMAAnalyzer
    except ImportError:
        try:
            from analysis.statistical.arima import ARIMAAnalyzer
        except ImportError:
            pass

    try:
        from .statistical.monte_carlo import MonteCarloAnalyzer
    except ImportError:
        try:
            from analysis.statistical.monte_carlo import MonteCarloAnalyzer
        except ImportError:
            pass

    try:
        from .statistical.mean_reversion import MeanReversionAnalyzer
    except ImportError:
        try:
            from analysis.statistical.mean_reversion import MeanReversionAnalyzer
        except ImportError:
            pass

    try:
        from .correlation.cointegration import CorrelationAnalyzer
    except ImportError:
        try:
            from analysis.correlation.cointegration import CorrelationAnalyzer
        except ImportError:
            pass

    try:
        from .ml.random_forest import RandomForestAnalyzer
    except ImportError:
        try:
            from analysis.ml.random_forest import RandomForestAnalyzer
        except ImportError:
            pass

    try:
        from .ml.neural_net import NeuralNetAnalyzer
    except ImportError:
        try:
            from analysis.ml.neural_net import NeuralNetAnalyzer
        except ImportError:
            pass

    try:
        from .nlp.sentiment import SentimentAnalyzer
    except ImportError:
        try:
            from analysis.nlp.sentiment import SentimentAnalyzer
        except ImportError:
            pass

    try:
        from .nlp.research_agent import ResearchAgent
    except ImportError:
        try:
            from analysis.nlp.research_agent import ResearchAgent
        except ImportError:
            pass


# Registrierung wird verzögert, damit die Analyzer-Module Zeit haben zu laden
# Dies geschieht beim ersten Zugriff auf das Registry

_initialized = False


def ensure_initialized():
    """Stellt sicher, dass alle Analyzer registriert sind"""
    global _initialized
    if not _initialized:
        _register_all_analyzers()
        _initialized = True


# ===== HILFSFUNKTIONEN =====

def get_analyzer(name: str) -> Optional[BaseAnalyzer]:
    """
    Komfort-Funktion um einen Analyzer zu holen.

    Args:
        name: Name des Analyzers

    Returns:
        Analyzer-Instanz oder None
    """
    ensure_initialized()
    return AnalysisRegistry.get(name)


def list_analyzers() -> List[Dict[str, Any]]:
    """
    Komfort-Funktion um alle Analyzer aufzulisten.

    Returns:
        Liste von Analyzer-Informationen
    """
    ensure_initialized()
    return AnalysisRegistry.list_all()


def get_analyzer_for_ui() -> Dict[str, List[Dict]]:
    """
    Gibt Analyzer gruppiert nach Kategorie für die UI zurück.

    Returns:
        Dict mit Kategorien und ihren Analyzern
    """
    ensure_initialized()

    categories = {
        AnalysisCategory.STATISTICAL.value: {
            "name": "Statistische Analysen",
            "icon": "📊",
            "analyzers": []
        },
        AnalysisCategory.CORRELATION.value: {
            "name": "Korrelation & Kointegration",
            "icon": "🔗",
            "analyzers": []
        },
        AnalysisCategory.ML.value: {
            "name": "Machine Learning",
            "icon": "🤖",
            "analyzers": []
        },
        AnalysisCategory.NLP.value: {
            "name": "Sentiment & NLP",
            "icon": "📰",
            "analyzers": []
        },
        AnalysisCategory.RESEARCH.value: {
            "name": "Web-Recherche",
            "icon": "🔍",
            "analyzers": []
        }
    }

    for info in AnalysisRegistry.list_all():
        cat = info.get("category", "statistical")
        if cat in categories:
            categories[cat]["analyzers"].append(info)

    # Nur Kategorien mit Analyzern zurückgeben
    return {k: v for k, v in categories.items() if v["analyzers"]}
