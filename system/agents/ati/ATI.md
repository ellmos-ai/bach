---
name: ati-agent
metadata:
  version: 1.2.0
  last_updated: 2026-01-22
  type: agent
  status: draft
  origin: _BATCH + _CHIAH (BATCHI)
description: >
  ATI - Advanced Tool Integration Agent
  Software-Entwickler-Agent fuer BACH.
  ATI = BATCHI - BACH (das Delta, was BACH noch fehlt)
  BACH + ATI = BATCHI (vollstaendiger Software-Entwickler-Agent)
  
  WICHTIG: ATI verwaltet EIGENE Tasks - nicht BACH System-Tasks!
  Scanner fuer AUFGABEN.txt = ATI Feature (nicht BACH-Core)
---

============================================================
ATI - ADVANCED TOOL INTEGRATION AGENT
============================================================

Software-Entwickler-Agent fuer BACH Oekosystem

> ATI = (_BATCH ∪ _CHIAH) - BACH
> Das Delta, das BACH zum vollstaendigen Entwickler-Agenten macht

============================================================
ARCHITEKTUR
============================================================

┌─────────────────────────────────────────────────────────────┐
│                      BACH (OS/Framework)                    │
│  ┌────────────────────────────────────────────────────────┐ │
│  │                                                        │ │
│  │  ┌─────────────────────────────────────────────────┐   │ │
│  │  │              ATI Agent (Plugin)                 │   │ │
│  │  │                                                 │   │ │
│  │  │  [X] Headless Sessions                          │   │ │
│  │  │  [X] Prompt-Templates                           │   │ │
│  │  │  [X] Onboarding-System                          │   │ │
│  │  │  [X] Between-Task-Checks                        │   │ │
│  │  │  [X] Action Hub (JSON)                          │   │ │
│  │  │  [X] Context Sources                            │   │ │
│  │  │  [X] Problems First                             │   │ │
│  │  │                                                 │   │ │
│  │  └─────────────────────────────────────────────────┘   │ │
│  │                         │                              │ │
│  │                         ▼                              │ │
│  │  ┌─────────────────────────────────────────────────┐   │ │
│  │  │            BACH Basis (vorhanden)               │   │ │
│  │  │                                                 │   │ │
│  │  │  [✓] Task-DB (bach.db, user.db)                 │   │ │
│  │  │  [✓] Scanner (AUFGABEN.txt)                     │   │ │
│  │  │  [✓] Memory-System                              │   │ │
│  │  │  [✓] GUI/Dashboard                              │   │ │
│  │  │  [✓] Daemon (Basis)                             │   │ │
│  │  │  [✓] Injektoren                                 │   │ │
│  │  │  [✓] Directory Truth                            │   │ │
│  │  │  [✓] Coding Tools (c_*.py)                      │   │ │
│  │  │                                                 │   │ │
│  │  └─────────────────────────────────────────────────┘   │ │
│  │                                                        │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                             │
│  Andere Agenten: Steuer, Research, Production, ...          │
└─────────────────────────────────────────────────────────────┘

============================================================
ATI DELTA-FEATURES (was BACH fehlt)
============================================================

Diese Features bringt ATI mit (aus _BATCH + _CHIAH):

┌─────────────────────────────────────────────────────────────┐
│ 1. HEADLESS AI-SESSIONS (aus _BATCH)                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ Was: Automatische Claude-Sessions ohne User-Interaktion     │
│                                                             │
│ Komponenten:                                                │
│   ati_session_daemon.py    Zeitgesteuerte Session-Starts    │
│   ati_prompt_templates/    Prompt-Vorlagen fuer Aufgaben    │
│   ati_response_handler.py  Antwort-Verarbeitung             │
│                                                             │
│ Workflow:                                                   │
│   Daemon -> Prompt generieren -> Claude -> Antwort -> DB    │
│                                                             │
│ Quelle: _BATCH/session_daemon.py                            │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ 2. ONBOARDING-SYSTEM (aus _BATCH)                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ Was: Automatische Tasks fuer neue Software-Projekte         │
│                                                             │
│ Komponenten:                                                │
│   ati_check_new_tools()         Neue Projekte erkennen      │
│   ati_create_onboarding_tasks() Standard-Tasks erstellen    │
│                                                             │
│ Onboarding-Tasks (pro neuem Projekt):                       │
│   1. Feature-Analyse erstellen                              │
│   2. Code-Qualitaetspruefung                                │
│   3. AUFGABEN.txt erstellen                                 │
│                                                             │
│ Quelle: _BATCH/scanner.py (_check_new_tools)                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ 3. BETWEEN-TASK-CHECKS (aus _BATCH)                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ Was: Checkliste zwischen Aufgaben                           │
│                                                             │
│ Checks:                                                     │
│   [ ] Memory aktualisiert?                                  │
│   [ ] Aenderungen dokumentiert?                             │
│   [ ] Tests ausgefuehrt?                                    │
│   [ ] Naechster Task klar?                                  │
│                                                             │
│ Quelle: _BATCH/SYSTEM/BETWEEN-TASK-CHECKS.md                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ 4. CONTEXT SOURCES (aus _CHIAH)                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ Was: Automatische Kontext-Hinweise bei Keywords             │
│                                                             │
│ Trigger:                                                    │
│   "fehler" -> lessons_learned.md laden                      │
│   "blockiert" -> strategies.md laden                        │
│   "startup" -> best_practices laden                         │
│                                                             │
│ Quelle: _CHIAH/HUB/context_sources.py                       │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ 5. PROBLEMS FIRST (aus _CHIAH)                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ Was: Fehler melden sich automatisch                         │
│                                                             │
│ Workflow:                                                   │
│   Auto-Log pruefen -> ERROR gefunden -> Anzeigen            │
│                                                             │
│ Quelle: _CHIAH/HUB/context_sources.py (problems)            │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ 6. ACTION HUB (aus _BATCH)                                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ Was: Encoding-sichere JSON-Bearbeitung                      │
│                                                             │
│ Features:                                                   │
│   - UTF-8 mit BOM-Toleranz                                  │
│   - Schema-validierte Handler                               │
│   - Strukturierte Operationen                               │
│                                                             │
│ Quelle: _BATCH/claude_action_hub.py                         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ 7. RECURRING TASKS (aus _BATCH)                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ Was: Wiederkehrende System-Aufgaben                         │
│                                                             │
│ Beispiele:                                                  │
│   - SELF-CHECK alle 30 Tage                                 │
│   - External Audit alle 30 Tage                             │
│   - Backup-Pruefung taeglich                                │
│                                                             │
│ Quelle: _BATCH/DATA/system-tasks.json (category: recurring) │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ 8. TASK-ABHAENGIGKEITEN (aus _BATCH/_CHIAH)                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ Was: depends_on Feld fuer Task-Sequenzen                    │
│                                                             │
│ Beispiel:                                                   │
│   Task 2 depends_on: [Task 1]                               │
│   -> Task 2 erst verfuegbar wenn Task 1 done                │
│                                                             │
│ Quelle: _BATCH/DATA/system-tasks.json, CONNI task_schema    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ 9. PROJEKT-BOOTSTRAPPING (NEU v1.2.0)                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ Was: Neue Projekte mit BACH-Policies und Modulen erstellen  │
│                                                             │
│ Komponenten:                                                │
│   project_bootstrapper.py      Kernlogik (682 Zeilen)       │
│   policy_applier.py            Policy-Anwendung             │
│   _templates/                  Git-Strukturvorlagen         │
│   _modules/                    Wiederverwendbare Module     │
│   _policies/                   BACH-Qualitaetspolicies      │
│                                                             │
│ Templates verfuegbar:                                       │
│   python-cli, python-gui, python-library, llm-skill,        │
│   llm-agent, web-api, generic                               │
│                                                             │
│ Module verfuegbar:                                          │
│   path_healer, distribution, encoding, readme_generator     │
│                                                             │
│ Referenz: ATI_PROJECT_BOOTSTRAPPING.md                      │
└─────────────────────────────────────────────────────────────┘

============================================================
ATI ORDNER-STRUKTUR
============================================================

BACH/
├── skills/
│   └── _agents/
│       └── ati/                     <- ATI Agent-Ordner
│           ├── ATI.md               <- Dieses Dokument
│           ├── session_daemon.py    <- Headless Sessions
│           ├── prompt_templates/    <- Prompt-Vorlagen
│           │   ├── task_prompt.txt
│           │   ├── review_prompt.txt
│           │   └── analysis_prompt.txt
│           ├── response_handler.py  <- Antwort-Verarbeitung
│           ├── onboarding.py        <- Neue Projekte
│           ├── context_sources.py   <- Auto-Trigger
│           ├── action_hub.py        <- JSON-Bearbeitung
│           └── between_checks.py    <- Task-Checks
│
├── hub/handlers/
│   └── ati.py                       <- CLI Handler
│       # bach ati start             Headless-Mode starten
│       # bach ati status            ATI-Status
│       # bach ati onboard PATH      Projekt onboarden
│
└── data/
    └── ati/                         <- ATI-Daten
        ├── sessions/                <- Session-Logs
        ├── responses/               <- Claude-Antworten
        └── context_cache/           <- Kontext-Cache

============================================================
ATI CLI-BEFEHLE
============================================================

# Session-Steuerung
bach ati start                   # Headless-Daemon starten
bach ati stop                    # Daemon stoppen
bach ati status                  # Status anzeigen
bach ati session --manual        # Einzelne Session manuell

# Onboarding
bach ati onboard PATH            # Neues Projekt registrieren
bach ati onboard --scan          # Alle neuen Projekte finden

# Context
bach ati context "keyword"       # Kontext-Trigger testen
bach ati problems                # Problems First anzeigen

# Between-Tasks
bach ati check                   # Between-Task-Checkliste

# Projekt-Bootstrapping (NEU v1.2.0)
bach ati bootstrap NAME --template TYPE   # Neues Projekt mit BACH-Policies
bach ati migrate PROJECT --analyze        # Bestehendes Projekt analysieren
bach ati migrate PROJECT --execute        # Migration ausfuehren
bach ati modules list                     # Verfuegbare Module anzeigen
bach ati modules inject MODULE PROJECT    # Modul in Projekt einfuegen

# ATI Export/Install
bach ati export [--to PATH]       # ATI-Agent exportieren
bach ati install PATH             # ATI aus Export installieren

============================================================
ATI KONFIGURATION
============================================================

In BACH config.json oder data/ati/config.json:

{
  "ati": {
    "enabled": true,
    "session": {
      "interval_minutes": 30,
      "quiet_start": "22:00",
      "quiet_end": "08:00",
      "timeout_minutes": 15,
      "max_tasks_per_session": 3
    },
    "onboarding": {
      "enabled": true,
      "auto_scan": true,
      "tasks": [
        "Feature-Analyse erstellen",
        "Code-Qualitaetspruefung",
        "AUFGABEN.txt erstellen"
      ]
    },
    "context_sources": {
      "enabled": true,
      "triggers": {
        "fehler": "lessons_learned",
        "blockiert": "strategies",
        "startup": "best_practices"
      }
    },
    "between_checks": {
      "enabled": true,
      "items": [
        "Memory aktualisiert?",
        "Aenderungen dokumentiert?",
        "Tests ausgefuehrt?",
        "Naechster Task klar?"
      ]
    }
  }
}

============================================================
IMPLEMENTIERUNGS-ROADMAP
============================================================

Phase 1: Grundstruktur (2h) ✓ ERLEDIGT
---------------------------
[x] agents/ati/ Ordner erstellen
[x] ATI.md (dieses Dokument) finalisieren
[x] hub/ati.py Handler erstellen
[x] data/ati/ Datenstruktur anlegen

Phase 2: Onboarding-System (2h)
-------------------------------
[ ] onboarding.py von _BATCH portieren
[ ] _check_new_tools() adaptieren
[ ] _create_onboarding_tasks() adaptieren
[ ] In Scanner integrieren

Phase 3: Headless Sessions (4h) <- KERN-FEATURE
-----------------------------------------------
[ ] session_daemon.py von _BATCH portieren
[ ] Prompt-Template-System erstellen
[ ] Response-Handler implementieren
[ ] Integration mit BACH Daemon

Phase 4: Context & Checks (2h)
------------------------------
[ ] context_sources.py von _CHIAH portieren
[ ] Between-Task-Checks implementieren
[ ] Problems First integrieren

Phase 5: Action Hub (optional, 2h)
----------------------------------
[ ] action_hub.py von _BATCH portieren
[ ] An BACH Struktur anpassen

Phase 6: Projekt-Bootstrapping (NEU) ✓ ERLEDIGT (2026-01-22)
------------------------------------------------------------
[x] project_bootstrapper.py erstellen (682 Zeilen)
[x] TemplateEngine implementieren
[x] Git-Struktur-Templates (7 Typen)
[x] Wiederverwendbare Module extrahieren
[x] BACH-Policies als Templates
[x] CLI: bach ati bootstrap/migrate
[x] StructureMigrator fuer bestehende Projekte
[x] ATI.md dokumentieren (diese Aenderung)

============================================================
INTEGRATION MIT BACH
============================================================

ATI nutzt BACH-Basis-Features:
------------------------------
- bach.db/tasks          -> Task-Management
- user.db/scanned_tasks  -> Scanner-Tasks
- bach.db/memory_*       -> Memory-System
- hub/handlers/*         -> CLI-System
- gui/daemon_service.py  -> Daemon-Basis
- skills/tools/c_*.py           -> Coding-Tools

ATI erweitert BACH um:
----------------------
- Headless AI-Sessions (autonom)
- Automatisches Projekt-Onboarding
- Intelligente Kontext-Trigger
- Qualitaets-Checks zwischen Tasks

============================================================
VERGLEICH: BACH vs BATCHI (BACH + ATI)
============================================================

Feature                     | BACH    | BATCHI (BACH+ATI)
----------------------------|---------|------------------
Task-Management             | 60%     | 90%
Autonomer Modus             | 20%     | 100%
Projekt-Erkennung           | 30%     | 90%
Memory & Kontext            | 70%     | 95%
Tool-Integration            | 65%     | 85%
Workflow-Steuerung          | 70%     | 90%
----------------------------|---------|------------------
GESAMT                      | 56%     | 92%

============================================================
FAZIT
============================================================

ATI ist das "Entwickler-Plugin" fuer BACH:

  BACH allein = Framework/OS (56% Agent)
  BACH + ATI  = BATCHI = Vollstaendiger Software-Entwickler-Agent (92%)

ATI bringt nur das Delta mit - keine Redundanz zu BACH.
ATI nutzt BACH-Infrastruktur - kein eigenes Task-System.
ATI ist ein Agent unter vielen - BACH kann weitere Agenten haben.

============================================================