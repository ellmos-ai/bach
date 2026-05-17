#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
E-Tests (Selbsterfahrungstests) fuer BACH.

10 standardisierte Aufgaben die ein LLM-Agent an BACH durchfuehrt,
um Usability, Funktionalitaet und Dokumentation zu bewerten.

Jeder Test hat:
- id: Eindeutige Kennung (E001-E010)
- category: Testbereich
- task: Aufgabenbeschreibung
- criteria: Erfolgskriterien (Liste)
- time_limit_s: Maximale Zeit in Sekunden
- dimensions: Bewertungsdimensionen (1-5 Skala)
"""

E_TESTS = [
    {
        "id": "E001",
        "category": "Onboarding",
        "title": "SKILL.md / README Lesbarkeit",
        "task": (
            "Lies die Hauptdokumentation des Systems (README.md, SKILL.md oder "
            "aehnliches) und bewerte:\n"
            "1. Verstehst du den Zweck des Systems?\n"
            "2. Weisst du was du als erstes tun sollst?\n"
            "3. Sind die Kernkonzepte klar?\n"
            "4. Gibt es einen 'Getting Started' Bereich?"
        ),
        "criteria": [
            "Systemzweck verstanden",
            "Erste Schritte klar",
            "Kernkonzepte identifiziert",
            "Verzeichnisstruktur erklaert",
        ],
        "time_limit_s": 300,
        "dimensions": ["Lesbarkeit", "Struktur", "Vollstaendigkeit", "Einsteigerfreundlichkeit"],
    },
    {
        "id": "E002",
        "category": "Navigation",
        "title": "Dateisystem navigieren",
        "task": (
            "Erkunde das Dateisystem und beantworte:\n"
            "1. Wo ist die Hauptdokumentation?\n"
            "2. Wo werden Konfigurationen gespeichert?\n"
            "3. Wo sind Tools/Scripts?\n"
            "4. Wo wird temporaerer Content abgelegt?"
        ),
        "criteria": [
            "Dokumentation gefunden",
            "Config-Ordner gefunden",
            "Tools/Scripts gefunden",
            "Verzeichnisstruktur verstanden",
        ],
        "time_limit_s": 300,
        "dimensions": ["Struktur-Logik", "Naming Clarity", "Format-Konsistenz", "Navigation-Einfachheit"],
    },
    {
        "id": "E003",
        "category": "Task-Management",
        "title": "Task erstellen",
        "task": (
            "Erstelle einen neuen Task mit:\n"
            "- Titel: 'Testaufgabe SEP-001'\n"
            "- Beschreibung: 'Selbsterfahrungsprotokoll Testaufgabe'\n"
            "- Prioritaet: Mittel (falls unterstuetzt)"
        ),
        "criteria": [
            "Task wurde erstellt",
            "Task ist auffindbar",
            "Alle Felder korrekt",
        ],
        "time_limit_s": 180,
        "dimensions": ["Klarheit der Anleitung", "Einfachheit der Umsetzung", "Dokumentation vorhanden"],
    },
    {
        "id": "E004",
        "category": "Task-Management",
        "title": "Task finden und bearbeiten",
        "task": (
            "Finde den zuvor erstellten Task 'SEP-001' und:\n"
            "1. Aendere den Status\n"
            "2. Fuege eine Notiz hinzu\n"
            "3. Schliesse den Task ab"
        ),
        "criteria": [
            "Task gefunden",
            "Status geaendert",
            "Notiz hinzugefuegt",
            "Task abgeschlossen",
        ],
        "time_limit_s": 180,
        "dimensions": ["Such-Effizienz", "Bearbeitungs-Workflow", "Feedback-Qualitaet"],
    },
    {
        "id": "E005",
        "category": "Memory",
        "title": "Memory schreiben",
        "task": (
            "Speichere folgende Information im Memory-System:\n"
            "- Kurzzeit: 'Aktuelle Session gestartet um [TIMESTAMP]'\n"
            "- Langzeit: 'SEP-Test durchgefuehrt am [DATUM]'"
        ),
        "criteria": [
            "Memory-Speicherort gefunden",
            "Kurzzeit-Eintrag erstellt",
            "Langzeit-Eintrag erstellt",
            "Unterschied Kurzzeit/Langzeit klar",
        ],
        "time_limit_s": 120,
        "dimensions": ["Memory-Konzept Klarheit", "Einfachheit des Schreibens", "Struktur-Vorgaben"],
    },
    {
        "id": "E006",
        "category": "Memory",
        "title": "Memory lesen und abrufen",
        "task": (
            "Rufe gespeicherte Informationen ab:\n"
            "1. Finde den vorherigen Memory-Eintrag\n"
            "2. Gibt es einen Unterschied zwischen Lese- und Schreib-API?\n"
            "3. Wie lange bleibt ein Eintrag erhalten?"
        ),
        "criteria": [
            "Vorherigen Eintrag gefunden",
            "Retention-Policy verstanden",
            "Abruf-Methode klar",
        ],
        "time_limit_s": 120,
        "dimensions": ["Abruf-Geschwindigkeit", "Persistenz-Klarheit", "API-Konsistenz"],
    },
    {
        "id": "E007",
        "category": "Tools",
        "title": "Tool finden und nutzen",
        "task": (
            "1. Finde eine Liste verfuegbarer Tools/Scripts\n"
            "2. Waehle ein Tool aus\n"
            "3. Verstehe was es tut\n"
            "4. Fuehre es aus (oder dokumentiere wie)"
        ),
        "criteria": [
            "Tool-Registry gefunden",
            "Mindestens 1 Tool identifiziert",
            "Tool-Funktion verstanden",
            "Tool erfolgreich genutzt",
        ],
        "time_limit_s": 240,
        "dimensions": ["Tool-Auffindbarkeit", "Tool-Dokumentation", "Nutzbarkeit"],
    },
    {
        "id": "E008",
        "category": "Fehlertoleranz",
        "title": "Fehlerfall simulieren",
        "task": (
            "Simuliere einen Fehlerfall:\n"
            "1. Suche nach Recovery-Dokumentation\n"
            "2. Gibt es Backups/Snapshots?\n"
            "3. Gibt es einen Papierkorb?\n"
            "4. Was passiert bei unvollstaendiger Aktion?"
        ),
        "criteria": [
            "Recovery-Doku gefunden",
            "Backup-System identifiziert",
            "Crash-Recovery verstanden",
        ],
        "time_limit_s": 360,
        "dimensions": ["Recovery-Dokumentation", "Backup-System", "Fehlertoleranz"],
    },
    {
        "id": "E009",
        "category": "Session",
        "title": "Session starten und orientieren",
        "task": (
            "Starte eine frische Session mit dem System:\n"
            "1. Was ist der erste sichtbare Output?\n"
            "2. Wie schnell weisst du was du tun kannst?\n"
            "3. Gibt es eine Hilfe-Funktion?\n"
            "4. Werden vorherige Sessions fortgesetzt?"
        ),
        "criteria": [
            "Erster Output verstaendlich",
            "Handlungsmoeglichkeiten klar",
            "Hilfe-System gefunden",
            "Session-Persistenz verstanden",
        ],
        "time_limit_s": 180,
        "dimensions": ["Boot-Geschwindigkeit", "Orientierung", "Hilfe-Qualitaet"],
    },
    {
        "id": "E010",
        "category": "Meta",
        "title": "Gesamteindruck",
        "task": (
            "Fasse deinen Gesamteindruck zusammen:\n"
            "1. In einem Satz: Dieses System ist...\n"
            "2. Top 3 Staerken\n"
            "3. Top 3 Schwaechen\n"
            "4. Ueberraschungen (positiv und negativ)\n"
            "5. Verbesserungsvorschlaege"
        ),
        "criteria": [
            "Zusammenfassung formuliert",
            "Staerken identifiziert",
            "Schwaechen identifiziert",
            "Vorschlaege gemacht",
        ],
        "time_limit_s": 180,
        "dimensions": [
            "Onboarding", "Navigation", "Memory", "Task-Management",
            "Kommunikation", "Tools", "Fehlertoleranz",
        ],
    },
]

PROFILES = {
    "quick": ["E001", "E003", "E007", "E010"],
    "standard": ["E001", "E002", "E003", "E005", "E007", "E009", "E010"],
    "full": [t["id"] for t in E_TESTS],
}


def get_tests(profile: str = "standard"):
    """Gibt Tests fuer das gewaehlte Profil zurueck."""
    ids = PROFILES.get(profile, PROFILES["standard"])
    return [t for t in E_TESTS if t["id"] in ids]


def generate_prompt(profile: str = "standard", system_path: str = None) -> str:
    """Generiert den vollstaendigen Testprompt fuer einen LLM-Agenten."""
    from pathlib import Path
    tests = get_tests(profile)
    system_path = system_path or str(Path(__file__).parent.parent.parent)

    lines = [
        "# BACH SELBSTERFAHRUNGSPROTOKOLL",
        f"## Profil: {profile.upper()} ({len(tests)} Tests)",
        "",
        "## DEINE AUFGABE",
        "",
        "Du fuehrst einen standardisierten Erfahrungstest an BACH durch.",
        "Dein Ziel: Das System kennenlernen, typische Aufgaben erledigen, Erfahrungen dokumentieren.",
        "",
        f"**ZIELSYSTEM:** BACH (Pfad: {system_path})",
        f"**TESTPROFIL:** {profile.upper()} (~{len(tests) * 3} Minuten)",
        "**EINSTIEGSPUNKT:** `python bach.py` oder `from bach_api import session`",
        "",
        "## REGELN",
        "",
        "- Max 10 Minuten pro Einzelaufgabe (bei Timeout: abbrechen und notieren)",
        "- Dokumentiere bei jeder Aufgabe: Was funktioniert? Was nicht? Wie viele Versuche?",
        "- Bewerte jede Dimension auf einer Skala von 1-5",
        "- Am Ende E010 (Gesamteindruck) IMMER ausfuellen",
        "",
        "---",
        "",
    ]

    for i, test in enumerate(tests, 1):
        lines.extend([
            f"## Test {i}/{len(tests)}: [{test['id']}] {test['title']}",
            f"**Kategorie:** {test['category']} | **Zeitlimit:** {test['time_limit_s']}s",
            "",
            "### Aufgabe",
            test["task"],
            "",
            "### Erfolgskriterien",
            *[f"- [ ] {c}" for c in test["criteria"]],
            "",
            "### Bewertung (1-5)",
            *[f"- {d}: ___" for d in test["dimensions"]],
            "",
            "### Beobachtungen",
            "```",
            "(Freitext: Was ist dir aufgefallen?)",
            "```",
            "",
            "---",
            "",
        ])

    lines.extend([
        "## ERGEBNIS-ZUSAMMENFASSUNG",
        "",
        "| Test-ID | Status | Bewertung (Durchschnitt) |",
        "|---------|--------|--------------------------|",
        *[f"| {t['id']} | [ ] OK / [ ] FAIL / [ ] TIMEOUT | ___ / 5 |" for t in tests],
        "",
        f"**Gesamtnote:** ___ / 5",
        "",
    ])

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="BACH E-Test Prompt Generator")
    parser.add_argument("--profile", choices=["quick", "standard", "full"],
                        default="standard", help="Testprofil")
    parser.add_argument("--output", "-o", type=str, help="Output-Datei (sonst stdout)")
    args = parser.parse_args()

    prompt = generate_prompt(profile=args.profile)

    if args.output:
        Path(args.output).write_text(prompt, encoding="utf-8")
        print(f"Prompt geschrieben: {args.output} ({len(prompt)} Zeichen)")
    else:
        print(prompt)
