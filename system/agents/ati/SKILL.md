---
name: ati-agent
version: 1.2.0
type: agent
author: BACH Team
created: 2026-01-22
updated: 2026-02-04
anthropic_compatible: true
status: active

dependencies:
  tools: [project_bootstrapper.py, task_scanner.py, tool_discovery.py]
  services: []
  workflows: []

description: >
  ATI - Advanced Tool Integration Agent. Software-Entwickler-Agent fuer BACH.
  ATI = BATCHI - BACH (das Delta, was BACH noch fehlt). Verwaltet eigene
  Software-Entwicklungs-Tasks, nicht BACH System-Tasks.
---
# ATI - ADVANCED TOOL INTEGRATION AGENT

> Software-Entwickler-Agent fuer BACH Oekosystem

## AKTIVIERUNG

```bash
# ATI Task-Liste
bach ati task list

# Projekt onboarden
bach ati onboard "Projektname" --path "/pfad/zum/projekt"

# Aufgaben-Dateien scannen
bach ati scan

# Projekt bootstrappen
python agents/ati/tools/project_bootstrapper.py --template python-cli
```

## FEATURES

- **Headless AI-Sessions:** Automatische Claude-Sessions ohne User-Interaktion
- **Prompt-Templates:** Standardisierte Prompts fuer Code-Tasks
- **Onboarding-System:** Neue Projekte in ATI registrieren
- **Task-Scanner:** AUFGABEN.txt, AUFGABEN.md, TODO.md, ROADMAP.md und DONE.md in Projekten erkennen
- **Project Bootstrapper:** Neue Projekte aus Templates erstellen

## ABGRENZUNG

| System | Zustaendigkeit |
|--------|----------------|
| BACH Tasks | System-Tasks (Wartung, Features, Bugs) |
| ATI Tasks | Software-Entwicklung (Projekte, Code, Tests) |

## STRUKTUR

```
ati/
  ATI.md                    # Detaillierte Dokumentation
  SKILL.md                  # Diese Datei
  manifest.json             # Metadaten
  data/config.json          # Konfiguration
  onboarding/               # Projekt-Onboarding
  scanner/                  # Aufgaben-/Roadmap-Scanner
  tools/                    # ATI-spezifische Tools
  templates/                # Projekt-Templates
  prompt_templates/         # AI-Prompt-Vorlagen
```

## CLI-BEFEHLE

```bash
bach ati status             # ATI-Status
bach ati task list          # Software-Tasks
bach ati task add "..."     # Task hinzufuegen
bach ati onboard            # Projekt registrieren
bach ati scan               # Aufgaben-Dateien scannen
```

## SIEHE AUCH

- ATI.md - Vollstaendige Dokumentation
- ATI_PROJECT_BOOTSTRAPPING.md - Template-System

---
Status: AKTIV
Domain: Software-Entwicklung
