# -*- coding: utf-8 -*-
"""Welche Rolle bearbeitet diese Aufgabe?

Der Chat konnte bisher nur an einen fest verdrahteten Anbieter delegieren
(``delegate`` -> claude oder codex). Was fehlte, war die Frage davor: WER
soll das machen. BACH kennt 27 Rollen mit Domaene und Beschreibung - genug,
um eine Aufgabe der passenden zuzuordnen.

Der Router waehlt nur aus. Gestartet wird ueber den Launcher, ausgefuehrt
von dem Runner, den das Modell der Rolle vorgibt (hub/agent_runners.py).

Bewusst ohne Modellaufruf: Eine Zuordnung, die selbst eine Modellantwort
kostet, ist an dieser Stelle zu teuer - sie soll die Delegation vorbereiten,
nicht verdoppeln.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

_NOISE = frozenset(
    """
    aber alle als am an auf aus bei bin bis das dass dem den der des die ein
    eine einem einen einer eines fuer für hat ich ist kann mit nach nicht
    noch nur oder sich sind soll und von vom was wenn wie wir zum zur über
    machen bitte mal etwas
    """.split()
)
_WORD = re.compile(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9_]{2,}")
_STEM = 5


def _stems(text: str) -> set[str]:
    words = {w.lower() for w in _WORD.findall(text or "")} - _NOISE
    return {w[:_STEM] for w in words}


#: Domaenen sind Einwortbegriffe - ohne Synonyme wuerde "Steuererklaerung"
#: die Domaene "finanzen" nie treffen.
DOMAIN_WORDS: dict[str, str] = {
    "finanzen": "steuer steuern beleg belege rechnung abo abos versicherung "
                "kosten geld konto zahlung finanz buchhaltung",
    "gesundheit": "arzt arztbericht diagnose medikament labor laborwert "
                  "vorsorge symptom krank gesundheit rezept",
    "psychologie": "therapie gespraech beratung sitzung psychisch belastung "
                   "stress angst emotion",
    "paedagogik": "foerderung foerderplan schueler unterricht lernen icf "
                  "schule paedagogisch klasse",
    "haushalt": "einkauf einkaufsliste inventar vorrat haushalt putzen "
                "lieferung bestellung",
    "analytik": "analyse auswertung statistik daten diagramm kennzahl "
                "auswerten messung",
    "dokumentation": "bericht dokumentation protokoll zusammenfassung "
                     "schreiben verfassen report",
    "medien": "audio transkript transkription video aufnahme gespraech "
              "untertitel",
    "karriere": "bewerbung lebenslauf anschreiben linkedin vorstellung job",
    "bildung": "quiz wissen lernkarte abfrage wiki bildung",
    "zeit": "strategie taktik planung zeitplan priorisierung",
}


@dataclass(frozen=True)
class Role:
    name: str
    display_name: str
    description: str
    domain: str
    kind: str          # "boss" | "expert"
    model: str = ""

    @property
    def haystack(self) -> str:
        extra = DOMAIN_WORDS.get(self.domain, "")
        return f"{self.name} {self.display_name} {self.description} {self.domain} {extra}"


def load_roles(db_path: str | Path) -> list[Role]:
    """Aktive Rollen aus der BACH-Datenbank. Nur lesend."""
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    rollen: list[Role] = []
    try:
        for tabelle, kind in (("bach_agents", "boss"), ("bach_experts", "expert")):
            spalte = "category" if tabelle == "bach_agents" else "domain"
            try:
                rows = con.execute(
                    f"SELECT name, display_name, description, {spalte} "
                    f"FROM {tabelle} WHERE is_active = 1"
                ).fetchall()
            except sqlite3.Error:
                continue
            gesehen = set()
            for name, anzeige, beschreibung, bereich in rows:
                # Die Tabellen enthalten dieselbe Rolle mehrfach (Sprachen).
                if name in gesehen:
                    continue
                gesehen.add(name)
                rollen.append(Role(
                    name=name or "",
                    display_name=anzeige or name or "",
                    description=beschreibung or "",
                    domain=(bereich or "").lower(),
                    kind=kind,
                ))
    finally:
        con.close()
    return rollen


def route(aufgabe: str, roles: list[Role], limit: int = 3,
          min_score: int = 1) -> list[tuple[int, Role]]:
    """Passende Rollen, beste zuerst. Leer heisst: keine passt klar genug."""
    frage = _stems(aufgabe)
    if not frage:
        return []
    treffer: list[tuple[int, Role]] = []
    for rolle in roles:
        overlap = frage & _stems(rolle.haystack)
        if not overlap:
            continue
        score = len(overlap)
        # Ein Treffer im Namen oder in der Domaene wiegt schwerer als einer
        # in der Prosa - "steuer" in "steuer-agent" ist kein Zufall.
        if frage & _stems(f"{rolle.name} {rolle.domain}"):
            score += 3
        if score >= min_score:
            treffer.append((score, rolle))
    treffer.sort(key=lambda p: (-p[0], p[1].name))
    return treffer[:limit]


def explain(aufgabe: str, roles: list[Role], limit: int = 3) -> str:
    """Vorschlagstext fuer den Chat - er waehlt, der Router raet nur."""
    hits = route(aufgabe, roles, limit=limit)
    if not hits:
        return ("Keine Rolle passt klar zu dieser Aufgabe - selbst erledigen "
                "oder Rolle ausdruecklich benennen.")
    zeilen = ["Passende Rollen:"]
    for score, r in hits:
        bereich = f"[{r.domain}] " if r.domain else ""
        zeilen.append(f"- {r.name} ({r.display_name}) {bereich}"
                      f"{r.description[:70]}  [Passung {score}]")
    return "\n".join(zeilen)
