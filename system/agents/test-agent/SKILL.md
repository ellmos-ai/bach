---
name: test-agent
version: 1.1.0
type: agent
author: Gemini
created: 2026-01-17
updated: 2026-09-18
anthropic_compatible: true
status: active

orchestrates:
  experts: []
  services: []

dependencies:
  tools: [test_runner]
  services: []
  workflows: []

description: >
  Systematisches Testen von BACH und anderen LLM-OS-Systemen. Orchestrator
  fuer Test- und Vergleichs-Workflows.
---
# Test-Agent (QA-Agent)

**Zweck:** Systematisches Testen von BACH und anderen LLM-OS-Systemen
**Typ:** Orchestrator fuer Test- und Vergleichs-Workflows
**Version:** 1.1.0

---

## FAEHIGKEITEN

| Nr | Faehigkeit | Beschreibung |
|:--:|------------|--------------|
| 1 | Selbsttest | BACH auf Funktionalitaet pruefen |
| 2 | Systemvergleich | Andere Systeme mit BACH vergleichen |
| 3 | Qualitaetsmetriken | Abdeckungskoeffizienten berechnen |
| 4 | Regressionstests | Nach Aenderungen Integritaet pruefen |
| 5 | Synopse erstellen | Vergleichende Analyse dokumentieren |

---

## DREI TESTPERSPEKTIVEN

```
┌─────────────────┬─────────────────┬─────────────────┐
│ B-Tests         │ O-Tests         │ E-Tests         │
│ BEOBACHTUNG     │ AUSGABE         │ ERFAHRUNG       │
├─────────────────┼─────────────────┼─────────────────┤
│ Extern          │ Funktional      │ Intern          │
│ Automatisiert   │ Input->Output   │ Subjektiv       │
│ Python-Scripts  │ Python-Scripts  │ Claude-gefuehrt │
│ "Was existiert?"│ "Funktioniert?" │ "Wie fuehlt es?"│
└─────────────────┴─────────────────┴─────────────────┘
```

---

## VERFUEGBARE TESTS

### B-Tests (Beobachtung) - Automatisiert

| ID | Name | Misst |
|----|------|-------|
| B001 | file_inventory | Anzahl, Typen, Groessen |
| B002 | format_consistency | Einheitlichkeit |
| B003 | directory_depth | Max/Avg Tiefe |
| B004 | naming_analysis | Namens-Konsistenz |
| B005 | documentation_check | Doku-Vollstaendigkeit |
| B006 | code_metrics | LOC, Komplexitaet |
| B007 | dependencies | Abhaengigkeiten |
| B008 | age_analysis | Letzte Aenderungen |

### O-Tests (Ausgabe) - Funktional

| ID | Name | Prueft |
|----|------|--------|
| O001 | task_roundtrip | Task CRUD |
| O002 | memory_persistence | Memory Write/Read |
| O003 | tool_registry | Tool finden/nutzen |
| O004 | backup_restore | Backup/Restore |
| O005 | config_validation | Configs parsbar |
| O006 | export_import | Daten ex-/import |

### E-Tests (Erfahrung) - Subjektiv

| ID | Name | Erfasst |
|----|------|---------|
| E001 | skill_readability | SKILL.md Lesbarkeit |
| E002 | navigation | Dateisystem-Erkundung |
| E003 | task_create | Aufgabe erstellen |
| E004 | task_find | Aufgabe finden |
| E005 | memory_write | Memory schreiben |
| E006 | memory_read | Memory lesen |
| E007 | tool_use | Tool nutzen |
| E008 | error_recovery | Fehler-Recovery |
| E009 | session_start | Session starten |
| E010 | overall_impression | Gesamteindruck |

---

## TESTPROFILE

| Profil | Dauer | B-Tests | O-Tests | E-Tests |
|--------|:-----:|:-------:|:-------:|:-------:|
| QUICK | 5 Min | B001 | O001 | E001,E010 |
| STANDARD | 20 Min | B001-B005 | O001-O003 | E001-E007,E010 |
| FULL | 40 Min | B001-B008 | O001-O006 | Alle |
| OBSERVATION | 15 Min | B001-B008 | - | - |
| OUTPUT | 20 Min | - | O001-O006 | - |
| MEMORY_FOCUS | 10 Min | - | O002 | E005,E006 |
| TASK_FOCUS | 10 Min | - | O001 | E003,E004 |

---

## WORKFLOWS

### WORKFLOW 1: SELBSTTEST

```
ZIEL: BACH auf Funktionalitaet pruefen

SCHRITT 1: Automatisierte Tests
  python tools/testing/test_runner.py --profile STANDARD

SCHRITT 2: E-Tests manuell (falls gewuenscht)
  - fc_get_time() -> Start
  - E-Tests aus e_tests/AUFGABEN/ durchfuehren
  - fc_get_time() -> Ende
  - Bewertungen dokumentieren

SCHRITT 3: Ergebnis pruefen
  - Score > 4.0 = GUT
  - Score 3.0-4.0 = AKZEPTABEL
  - Score < 3.0 = AKTION ERFORDERLICH
```

### WORKFLOW 2: SYSTEMVERGLEICH

```
ZIEL: Anderes System mit BACH vergleichen

SCHRITT 1: Zielsystem identifizieren
  - Pfad zum System
  - Hat es SKILL.md?
  - Systemklasse? (SKILL/AGENT/OS)

SCHRITT 2: Tests fuer beide ausfuehren
  python tools/testing/test_runner.py "BACH" -p STANDARD
  python tools/testing/test_runner.py "<anderes>" -p STANDARD
  
  ODER direkt vergleichen:
  python tools/testing/test_runner.py "BACH" --compare "<anderes>"

SCHRITT 3: Feature-Matrix erstellen
  ┌──────────────┬──────┬──────────┐
  │ Feature      │ BACH │ Anderes  │
  ├──────────────┼──────┼──────────┤
  │ CLI          │ ?    │ ?        │
  │ Memory       │ ?    │ ?        │
  │ Tasks        │ ?    │ ?        │
  └──────────────┴──────┴──────────┘

SCHRITT 4: Synopse erstellen (siehe WORKFLOW 3)
```

### WORKFLOW 3: SYNOPSE ERSTELLEN

```
ZIEL: Vergleichende Analyse dokumentieren

SCHRITT 1: Daten sammeln
  - Testergebnisse aus tools/testing/results/
  - Feature-Listen
  - Beobachtungen

SCHRITT 2: Dimensionen bewerten (1-5)
  D1 Onboarding
  D2 Navigation
  D3 Memory
  D4 Tasks
  D5 Kommunikation
  D6 Tools
  D7 Fehlertoleranz

SCHRITT 3: Staerken/Schwaechen
  - Top 3 Staerken pro System
  - Top 3 Schwaechen pro System

SCHRITT 4: Synopse schreiben
  -> docs/_Reports/SYNOPSE_<Thema>_<Datum>.md

FORMAT:
  1. Gesamtergebnis (Ranking)
  2. Dimensionsvergleich
  3. Feature-Matrix
  4. Staerken-Schwaechen
  5. Best-of Extraktion
  6. Empfehlungen
```

### WORKFLOW 4: REGRESSIONSTEST

```
ZIEL: Nach Aenderungen Integritaet pruefen

TRIGGER: 
  - Nach groesserer Aenderung
  - Vor Release/Commit
  - Regelmaessig (woechentlich)

ABLAUF:
  1. python tools/testing/test_runner.py -p QUICK
  2. Score mit letztem Ergebnis vergleichen
  3. Bei Verschlechterung > 0.5: Ursache finden
  4. Ergebnis in docs/_Reports/ dokumentieren
```

---

## CLI NUTZUNG

### Test-Runner

```bash
# BACH selbst testen (Standard-Profil)
python tools/testing/test_runner.py

# Mit spezifischem Profil
python tools/testing/test_runner.py -p QUICK
python tools/testing/test_runner.py -p FULL

# Anderes System testen
python tools/testing/test_runner.py "C:\...\anderes_system"

# Zwei Systeme vergleichen
python tools/testing/test_runner.py "BACH" --compare "C:\...\anderes"

# Profile anzeigen
python tools/testing/test_runner.py --list-profiles
```

### Einzelne Tests

```bash
# B-Tests
python tools/testing/b_tests/B001_file_inventory.py "BACH"
python tools/testing/b_tests/run_b_tests.py "BACH" "results"

# O-Tests
python tools/testing/o_tests/O001_task_roundtrip.py "BACH"
python tools/testing/o_tests/run_o_tests.py "BACH" "results"
```

---

## VERZEICHNISSTRUKTUR

```
tools/testing/
├── test_runner.py       # Haupt-Runner (NEU)
├── query_tests.py       # DB-Abfragen
├── populate_tests.py    # DB befuellen
├── test_schema.sql      # DB-Schema
│
├── b_tests/             # B-Tests (automatisiert)
│   ├── B001_file_inventory.py
│   ├── B002_format_consistency.py
│   ├── ...
│   └── run_b_tests.py
│
├── o_tests/             # O-Tests (funktional)
│   ├── O001_task_roundtrip.py
│   ├── O002_memory_persistence.py
│   ├── ...
│   └── run_o_tests.py
│
├── e_tests/             # E-Tests (subjektiv)
│   ├── AUFGABEN/
│   │   ├── E001_skill_readability.txt
│   │   └── ...
│   └── PROMPT_TEMPLATE.txt
│
├── profiles/            # Testprofile (JSON)
│   ├── QUICK.json
│   ├── STANDARD.json
│   └── FULL.json
│
└── results/             # Testergebnisse
    └── BACH/
```

---

## BEWERTUNGSSKALA

| Wert | Bedeutung | Aktion |
|:----:|-----------|--------|
| 5 | Exzellent | Beibehalten |
| 4 | Gut | Kleine Verbesserungen |
| 3 | Akzeptabel | Mittelfristig verbessern |
| 2 | Mangelhaft | Zeitnah verbessern |
| 1 | Kritisch | Sofort beheben |

### Erfolgsstatus

| Status | Code | Bedeutung |
|--------|:----:|-----------|
| SUCCESS | 2 | Vollstaendig erledigt |
| PARTIAL | 1 | Teilweise / mit Hilfe |
| FAILED | 0 | Nicht geschafft |
| TIMEOUT | -1 | Zeitlimit ueberschritten |
| BLOCKED | -2 | Feature fehlt |

---

## 7 DIMENSIONEN

| Dim | Name | Kernfrage |
|:---:|------|-----------|
| D1 | Onboarding | Wie schnell orientiert? |
| D2 | Navigation | Wie leicht zu finden? |
| D3 | Memory | Kontext persistent? |
| D4 | Tasks | Aufgaben-Handling? |
| D5 | Kommunikation | User-Interaktion? |
| D6 | Tools | Werkzeuge nutzbar? |
| D7 | Fehlertoleranz | Recovery moeglich? |

---

## ZEITMESSUNG (E-Tests)

**KRITISCH:** Immer fc_get_time() nutzen!

```
Vor Aufgabe:  fc_get_time() -> T_START
Nach Aufgabe: fc_get_time() -> T_END
Differenz:    T_TOTAL = T_END - T_START
```

### Abbruchkriterien

| Kontext | Max Zeit |
|---------|:--------:|
| Einzelaufgabe | 10 Min |
| QUICK Profil | 15 Min |
| STANDARD Profil | 30 Min |
| FULL Profil | 60 Min |

---

## ERGEBNIS-FORMAT

```json
{
  "system": "BACH",
  "profile": "STANDARD",
  "test_date": "2026-01-17T14:00:00",
  "b_tests": {
    "B001": {"status": "success", "score": 4.2}
  },
  "o_tests": {
    "O001": {"status": "PASS", "score": 5.0}
  },
  "dimensions": {
    "d1_onboarding": 4,
    "d2_navigation": 4,
    "d3_memory": 5,
    "d4_tasks": 4,
    "d5_communication": 3,
    "d6_tools": 5,
    "d7_error_tolerance": 4
  },
  "summary": {
    "b_avg": 4.2,
    "o_avg": 4.8,
    "overall": 4.5
  }
}
```

---

## QUICK-START

### Schnelltest (2 Min)

```bash
python tools/testing/test_runner.py -p QUICK
```

### Standard-Test (15 Min)

```bash
python tools/testing/test_runner.py -p STANDARD
```

### Vergleich mit anderem System

```bash
python tools/testing/test_runner.py --compare "C:\...\anderes_system"
```

---

## REFERENZEN

- skills/workflows/skill-abdeckungsanalyse.md
- tools/testing/e_tests/PROMPT_TEMPLATE.txt
- docs/help/selfcheck.txt

---

*Agent Version: 1.1.0*
*Erstellt: 2026-01-17*
*Quelle: BACH_STREAM/PRODUCTION/TESTS + WORKFLOWS*
