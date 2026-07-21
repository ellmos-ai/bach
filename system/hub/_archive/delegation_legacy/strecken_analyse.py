#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StreckenAnalyse - Regelbasierte Task-Klassifikation für clutch-bridge
=====================================================================

Klassifiziert Tasks in 10 Streckentypen (Auto-Metapher) mit 4 Dimensionen:
- Typ: Welche Art von Strecke (Feldweg bis Langstrecke)
- Tempo: Wie schnell soll bearbeitet werden (1-5)
- Schwierigkeit: Wie anspruchsvoll ist die Strecke (1-5)
- Etappen: Wie viele Teilschritte (1-10)

Einhängepunkt: complexity_scorer.py importiert StreckenAnalyse und
erweitert den bestehenden Score um die Strecken-Klassifikation.

Teil der clutch-bridge (BACH Task [1078]).
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class StreckenProfil:
    """Ergebnis der StreckenAnalyse."""
    typ: str                    # Streckentyp-Name
    typ_code: int               # Streckentyp-Code (1-10)
    tempo: int                  # Geschwindigkeit 1-5
    schwierigkeit: int          # Schwierigkeit 1-5
    etappen: int                # Teilschritte 1-10
    beschreibung: str           # Menschenlesbare Beschreibung
    empfohlener_gang: str       # haiku/sonnet/opus
    token_budget_faktor: float  # Multiplikator für Token-Budget
    details: Dict[str, any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "typ": self.typ,
            "typ_code": self.typ_code,
            "tempo": self.tempo,
            "schwierigkeit": self.schwierigkeit,
            "etappen": self.etappen,
            "beschreibung": self.beschreibung,
            "empfohlener_gang": self.empfohlener_gang,
            "token_budget_faktor": self.token_budget_faktor,
            "details": self.details,
        }


# ─── Streckentyp-Definitionen ──────────────────────────────────────

STRECKENTYPEN = {
    1: {
        "name": "Feldweg",
        "beschreibung": "Triviale Abfrage, Status-Check, einfache Anzeige",
        "tempo": 5, "schwierigkeit": 1, "etappen": 1,
        "gang": "haiku", "budget_faktor": 0.3,
    },
    2: {
        "name": "Ortsstraße",
        "beschreibung": "Einfache Operation, einzelner Befehl, Datei lesen",
        "tempo": 4, "schwierigkeit": 1, "etappen": 1,
        "gang": "haiku", "budget_faktor": 0.5,
    },
    3: {
        "name": "Landstraße",
        "beschreibung": "Moderate Aufgabe, Suche, Filter, Konvertierung",
        "tempo": 3, "schwierigkeit": 2, "etappen": 2,
        "gang": "sonnet", "budget_faktor": 0.7,
    },
    4: {
        "name": "Bundesstraße",
        "beschreibung": "Analyse, Vergleich, mehrstufiger Workflow",
        "tempo": 3, "schwierigkeit": 3, "etappen": 3,
        "gang": "sonnet", "budget_faktor": 1.0,
    },
    5: {
        "name": "Schnellstraße",
        "beschreibung": "Feature-Entwicklung, moderater Code-Umfang",
        "tempo": 2, "schwierigkeit": 3, "etappen": 4,
        "gang": "sonnet", "budget_faktor": 1.2,
    },
    6: {
        "name": "Autobahn",
        "beschreibung": "Komplexe Implementierung, mehrere Dateien, Tests",
        "tempo": 2, "schwierigkeit": 4, "etappen": 5,
        "gang": "opus", "budget_faktor": 1.5,
    },
    7: {
        "name": "Bergpass",
        "beschreibung": "Hohe Schwierigkeit, Debugging, Architektur-Problem",
        "tempo": 1, "schwierigkeit": 5, "etappen": 4,
        "gang": "opus", "budget_faktor": 1.8,
    },
    8: {
        "name": "Rennstrecke",
        "beschreibung": "Performance-kritisch, Optimierung, Benchmarking",
        "tempo": 5, "schwierigkeit": 4, "etappen": 3,
        "gang": "opus", "budget_faktor": 1.5,
    },
    9: {
        "name": "Rallye",
        "beschreibung": "Multi-Domain, System-übergreifend, viele Abhängigkeiten",
        "tempo": 2, "schwierigkeit": 5, "etappen": 7,
        "gang": "opus", "budget_faktor": 2.0,
    },
    10: {
        "name": "Langstrecke",
        "beschreibung": "Großprojekt, Migration, Framework-Entwicklung",
        "tempo": 1, "schwierigkeit": 5, "etappen": 10,
        "gang": "opus", "budget_faktor": 2.5,
    },
}


# ─── Klassifikations-Regeln ────────────────────────────────────────

# Patterns für Typ-Erkennung (Regex, case-insensitive)
TYP_PATTERNS = {
    1: [  # Feldweg
        r"^(zeig|list|status|info)\b",
        r"^(was ist|wie viel|wann)\b",
    ],
    2: [  # Ortsstraße
        r"^(lies|öffne|schließe|starte|stoppe|restart)\b",
        r"(datei\s+lesen|log\s+anzeigen)",
    ],
    3: [  # Landstraße
        r"(such|find|filter|sortier|konvertier|format)",
        r"(csv|json|xml)\s+(import|export|konvert)",
    ],
    4: [  # Bundesstraße
        r"(analysier|vergleich|zusammenfass|bericht|report)",
        r"(workflow|pipeline|ablauf)",
    ],
    5: [  # Schnellstraße
        r"(implementier|erstell|bau|entwickl)\w*.{0,30}(feature|funktion|modul)",
        r"(add|hinzufüg)\w*.{0,30}(button|tab|view|dialog)",
        r"(feature|funktion|modul).{0,30}(implementier|erstell|bau|entwickl)",
    ],
    6: [  # Autobahn
        r"(implementier|erstell|entwickl)\w*.{0,30}(system|service|handler|api)\b",
        r"(test|pytest|unittest).{0,20}(schreib|erstell)",
        r"(mehrere|verschiedene)\s+(dateien|module|klassen)",
    ],
    7: [  # Bergpass
        r"(debug|beheb|fix|reparier|diagnos)",
        r"(architektur|design.?pattern|refactor)",
        r"(fehler|bug|crash|exception).{0,20}(find|beheb|analys)",
    ],
    8: [  # Rennstrecke
        r"(optimier|performance|beschleunig|cache)",
        r"(benchmark|profil|latenz|throughput)",
    ],
    9: [  # Rallye
        r"(integrier|verbind|bridge|connector|sync)",
        r"(multi.?agent|cross.?platform|system.?übergreifend)",
        r"(migration|portier)\w*.{0,20}(framework|plattform)",
    ],
    10: [  # Langstrecke
        r"(framework|architektur|system).{0,20}(entwickl|bau|erstell|design)",
        r"(entwickl|bau|erstell|design)\w*.{0,20}(framework|architektur)",
        r"(komplett|vollständig|ganz)\w*\s+(neu|umschreib|portier)",
        r"(migration|großprojekt|rewrite)",
    ],
}

# Etappen-Indikatoren (erhöhen die Etappen-Zählung)
ETAPPEN_PATTERNS = [
    r"\d+\.\s+",               # Nummerierte Listen
    r"schritt\s+\d+",          # "Schritt 1..."
    r"(dann|danach|anschließend|außerdem|zusätzlich)\b",
    r"(phase|teil|stufe)\s+\d+",
    r"(zuerst|erstens|zweitens|drittens)",
    r"(und\s+dann|als\s+nächstes)",
]

# Schwierigkeits-Multiplikatoren
SCHWIERIGKEITS_BOOST = {
    "security": 1,
    "authentication": 1,
    "encryption": 1,
    "distributed": 2,
    "concurrent": 1,
    "async": 1,
    "race condition": 2,
    "deadlock": 2,
    "memory leak": 1,
    "backwards.?compat": 1,
}


class StreckenAnalyse:
    """Regelbasierte Task-Klassifikation mit Auto-Metapher."""

    def __init__(self):
        self._compiled_typ_patterns = {}
        for typ_code, patterns in TYP_PATTERNS.items():
            self._compiled_typ_patterns[typ_code] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]
        self._compiled_etappen = [
            re.compile(p, re.IGNORECASE) for p in ETAPPEN_PATTERNS
        ]
        self._compiled_schwierigkeit = {
            k: re.compile(k, re.IGNORECASE) for k in SCHWIERIGKEITS_BOOST
        }

    def analysiere(self, task_beschreibung: str) -> StreckenProfil:
        """
        Klassifiziert einen Task anhand seiner Beschreibung.

        Args:
            task_beschreibung: Task-Text

        Returns:
            StreckenProfil mit allen 4 Dimensionen
        """
        text = task_beschreibung.strip()
        if not text:
            return self._default_profil()

        # 1. Typ bestimmen (Pattern-Matching, höchster Match gewinnt)
        #    Bei Gleichstand: höherer Typ-Code bevorzugt (spezifischer)
        typ_scores = self._score_typen(text)
        best_typ = max(typ_scores, key=lambda k: (typ_scores[k], k)) if typ_scores else 4

        # Fallback: Längenbasierte Heuristik wenn kein Pattern matcht
        if not typ_scores or typ_scores[best_typ] == 0:
            best_typ = self._typ_from_length(text)

        strecke = STRECKENTYPEN[best_typ]

        # 2. Etappen zählen (Basis + erkannte Schritte)
        etappen = self._count_etappen(text, strecke["etappen"])

        # 3. Schwierigkeit adjustieren
        schwierigkeit = self._adjust_schwierigkeit(text, strecke["schwierigkeit"])

        # 4. Tempo aus Streckentyp (fest)
        tempo = strecke["tempo"]

        # 5. Gang und Budget-Faktor (können durch Schwierigkeit steigen)
        gang = strecke["gang"]
        budget_faktor = strecke["budget_faktor"]

        if schwierigkeit > strecke["schwierigkeit"]:
            # Schwierigkeit erhöht → ggf. Gang hochschalten
            if gang == "haiku" and schwierigkeit >= 3:
                gang = "sonnet"
                budget_faktor *= 1.3
            elif gang == "sonnet" and schwierigkeit >= 5:
                gang = "opus"
                budget_faktor *= 1.3

        return StreckenProfil(
            typ=strecke["name"],
            typ_code=best_typ,
            tempo=tempo,
            schwierigkeit=schwierigkeit,
            etappen=etappen,
            beschreibung=strecke["beschreibung"],
            empfohlener_gang=gang,
            token_budget_faktor=round(budget_faktor, 2),
            details={
                "typ_scores": typ_scores,
                "schwierigkeit_basis": strecke["schwierigkeit"],
                "schwierigkeit_boost": schwierigkeit - strecke["schwierigkeit"],
            },
        )

    def _score_typen(self, text: str) -> Dict[int, int]:
        """Bewertet alle Streckentypen per Pattern-Matching."""
        scores = {}
        for typ_code, patterns in self._compiled_typ_patterns.items():
            score = sum(1 for p in patterns if p.search(text))
            if score > 0:
                scores[typ_code] = score
        return scores

    def _typ_from_length(self, text: str) -> int:
        """Fallback: Typ aus Textlänge ableiten."""
        length = len(text)
        if length < 30:
            return 1
        elif length < 80:
            return 2
        elif length < 150:
            return 3
        elif length < 300:
            return 5
        elif length < 600:
            return 6
        else:
            return 9

    def _count_etappen(self, text: str, basis: int) -> int:
        """Zählt erkannte Etappen-Indikatoren."""
        extra = sum(
            len(p.findall(text)) for p in self._compiled_etappen
        )
        return min(10, max(basis, basis + extra))

    def _adjust_schwierigkeit(self, text: str, basis: int) -> int:
        """Erhöht Schwierigkeit durch erkannte Boost-Keywords."""
        boost = 0
        for keyword, points in SCHWIERIGKEITS_BOOST.items():
            pattern = self._compiled_schwierigkeit[keyword]
            if pattern.search(text):
                boost += points
        return min(5, basis + boost)

    def _default_profil(self) -> StreckenProfil:
        """Gibt ein Default-Profil für leere Eingaben zurück."""
        s = STRECKENTYPEN[1]
        return StreckenProfil(
            typ=s["name"], typ_code=1,
            tempo=s["tempo"], schwierigkeit=s["schwierigkeit"],
            etappen=s["etappen"], beschreibung=s["beschreibung"],
            empfohlener_gang=s["gang"],
            token_budget_faktor=s["budget_faktor"],
        )


# ─── Singleton ──────────────────────────────────────────────────────

_analyser_instance: Optional[StreckenAnalyse] = None


def get_analyser() -> StreckenAnalyse:
    """Gibt Singleton-Instanz zurück."""
    global _analyser_instance
    if _analyser_instance is None:
        _analyser_instance = StreckenAnalyse()
    return _analyser_instance


def analysiere_task(task_beschreibung: str) -> StreckenProfil:
    """Convenience-Funktion für Task-Analyse."""
    return get_analyser().analysiere(task_beschreibung)


# ─── Test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    analyser = StreckenAnalyse()

    tests = [
        "Zeige mir den Status",
        "Lies die Datei config.json",
        "Suche alle Python-Dateien mit TODO",
        "Analysiere die Logdateien und erstelle einen Bericht",
        "Implementiere ein neues Feature für den Tab-Wechsel",
        "Erstelle ein komplettes API-System mit Tests und Dokumentation",
        "Debugge den Race-Condition-Bug im Authentication-Handler",
        "Optimiere die Performance der Datenbankabfragen mit Cache",
        "Integriere den Multi-Agent-Bridge-Connector systemübergreifend",
        "Entwickle das komplette Framework für die neue Architektur und portiere alles",
    ]

    print("=== StreckenAnalyse Test ===\n")
    for t in tests:
        p = analyser.analysiere(t)
        print(f"Task: {t}")
        print(f"  Strecke: {p.typ} (Code {p.typ_code})")
        print(f"  Tempo: {p.tempo} | Schwierigkeit: {p.schwierigkeit} | Etappen: {p.etappen}")
        print(f"  Gang: {p.empfohlener_gang} | Budget-Faktor: {p.token_budget_faktor}")
        print()
