# BACH - Textbasiertes Betriebssystem für LLMs

**Version:** v3.12.3-coffee
**Status:** Production-Ready
**Lizenz:** MIT

## Überblick

BACH ist ein textbasiertes Betriebssystem, das Large Language Models (LLMs) befähigt, eigenständig zu arbeiten, zu lernen und sich zu organisieren. Es bietet eine umfassende Infrastruktur für Task-Management, Wissensmanagement, Automatisierung und LLM-Orchestrierung.

### Kernfunktionen

- **113+ Handler** - CLI- und API-Abdeckung für Systemfunktionen
- **550+ Tools** - Umfangreiche Tool-Bibliothek für Dateiverarbeitung, Analyse und Automation
- **1870+ Skills** - Wiederverwendbare Workflows und Templates
- **59 Workflow-Vorlagen** - Vorgefertigte Prozess-Workflows
- **Agent Doctor** - `bach agent doctor [name] [--json]` prüft Claude CLI, Laufzeitverzeichnisse, SKILL.md und veraltete PID-Dateien vor dem Start
- **Scheduler Doctor** - `bach scheduler doctor [--json]` sowie `bach scheduler session doctor [--json]` prüfen Automations-Skripte, PID-Status, DB-/Config-/Profil-Flächen und schlagen Recovery-Schritte vor
- **Session-Steuerung** - `bach scheduler session pause/resume/steer/clear-steer` steuert den nächsten profilbezogenen Auto-Run, ohne die Daemon-Config manuell umzuschreiben
- **Install Security Gate** - Statische Scans für `skills install`, `plugins load` und MCP-Setup/Config-Aktivierung; Plugin-Setups mit Shell/Desktop/MCP-Zugriff brauchen jetzt explizite fail-closed Guards, blockierte lokale Importe werden quarantänisiert
- **Manifest-first Plugins** - `bach plugins inspect` zeigt Aktivierung, Provider-/Model-, Setup- und Capability-Metadaten ohne Runtime-Import
- **Strukturierte `bach_api`-Kernmodule** - `task` und `memory` bieten jetzt über `dir(...)` auffindbare Methoden, liefern bei häufigen Reads/Writes Python-Objekte zurück und behalten `raw(...)` für Legacy-Handler-Aufrufe
- **Wissensspeicher** - Lessons, Facts und mehrstufiges Memory-System

## Installation

```bash
# Repository klonen
git clone https://github.com/ellmos-ai/bach.git
cd bach

# Abhängigkeiten installieren und `bach` CLI verfügbar machen
pip install -e .

# Pre-Flight-Check
bach setup preflight

# Vollständige Installation (MCP-Server, Hooks, Secrets, User-Profil)
bach setup full-install
```

## Quick Start

```bash
# BACH starten
python bach.py --startup

# Task erstellen
python bach.py task add "Analysiere Projektstruktur"

# Wissen abrufen
python bach.py wiki search "Task Management"

# BACH beenden
python bach.py --shutdown
```

## Hauptkomponenten

### 1. Task-Management
Vollständiges GTD-System mit Priorisierung, Deadlines, Tags und Context-Tracking.

### 2. Wissenssystem
Strukturiertes Memory-System mit Facts, Lessons und automatischer Konsolidierung.

### 3. Agenten-Framework
Boss-Agenten orchestrieren Experten für komplexe Aufgaben (Büro, Gesundheit, Produktion, etc.).

### 4. Chat-Service & Bridge-System
Multi-Backend Telegram-Bot mit wechselbaren LLM-Backends (Ollama, Claude CLI, Codex CLI, Claude API, OpenAI API), HTTP Control API mit Web-Dashboard und plattformübergreifendem System Tray. Connector-Framework für weitere Services (Email, WhatsApp, etc.) und USMC-Bridge für Cross-Agent-Kommunikation.

### 5. Automatisierung
SchedulerService für zeitbasierte Jobs (Chains, Tasks, Scripts) und Event-basierte Workflows über das Hook-Framework.

### 6. SharedMemory
Multi-Agent-Koordination mit Kontextgenerierung, Konflikterkennung, Decay und Delta-Queries.

### 7. llmauto-Integration
Chain-Schritte als LLM-Prompts mit `bach://` URL-Auflösung für dynamische Kontext-Einbettung.

## OpenClaw-Abgleich

Stand 2026-05-16: GitHub Releases markiert `2026.5.12` weiterhin als aktuelle Stable-Linie von OpenClaw; als neuestes sichtbares Prerelease erscheint jetzt `2026.5.16-beta.1`, und die Paket-Startseite zeigt inzwischen ebenfalls `2026.5.16-beta.1-slim` als neuesten Tag, während in der jüngsten Image-Liste zusätzlich `2026.5.14-beta.3-slim` sichtbar ist. Für BACH bleibt OpenClaw vor allem als Vergleichssystem für Plugin-Sicherheit, Laufzeitdiagnostik, Operator-Steuerung und Release-Härtung relevant. Die neuesten offiziellen Hinweise schärfen insbesondere lokalisierte Onboarding-/Setup-Flows, konfigurationsgebundenes Warm-Caching für `resolvedSkills`, Ambient-Turns für Gruppenräume, Fallback-Semantik für isolierte Cron-/Subagent-Läufe, per-Agent-Codex-MCP-Scopes samt Approval-Defaults, das harte Ablehnen fehlerhafter Extension-Metadaten, MIME-Sniffing vor agentensichtbarer Dateiverarbeitung und robuste Config-Persistenz bei fehlerhaftem gespeicherten Zustand. BACH deckt bereits manifest-first Plugin-Metadaten, fail-closed Setup-Guards für Shell/Desktop/MCP-Flächen, Scans mit Quarantäne vor der Installation von Skills/MCP-Servern/Plugins, Memory-/Wiki-Provenance-Ansichten, kanonische `bach path`-Oberflächen, maschinenlesbare Agent-/Scheduler-Statusflächen, `bach agent doctor` sowie `bach scheduler doctor` und `bach scheduler session doctor` als operatorseitige Startdiagnosen und workspace-scoped Cache-Invalidierung in der Agent-Runtime ab. Neu hinzugekommen sind jetzt zusätzlich maschinenlesbare `bach agent start/stop --json`-Antworten für automatisierungssichere Operator-Steuerung, `bach agent steer` als Operator-Notiz-Brücke sowie profilspezifische Session-Steuerung über `bach scheduler session pause`, `resume`, `steer` und `clear-steer`. Nächste Schritte: Active-Run-Steering über llmauto-Ketten hinaus, engere Tool-/Connector-Scopes pro Agent, härtere Ingest-Validierung und Cleanup fehlerhafter Zustände, Telemetrie und Release-Validierung sowie Fallback-Semantik dort, wo sie zu BACHs Multi-Partner-Architektur passt.

## Dokumentation

- **[Schnellstart](QUICKSTART.md)** - Erste Schritte mit BACH
- **[Benutzerhandbuch](BACH_USER_MANUAL.md)** - Vollständiges Handbuch
- **[Skills-Katalog](SKILLS.md)** - Alle verfügbaren Skills
- **[Agenten-Katalog](AGENTS.md)** - Alle verfügbaren Agenten und Experten
- **[Workflows](WORKFLOWS.md)** - 59 Workflow-Vorlagen
- **[SKILL.md](SKILL.md)** - LLM-Betriebsanweisungen (für Claude, Gemini, Ollama)

## Lizenz

MIT License - siehe [LICENSE](LICENSE) für Details.

## Support

- **Issues:** [GitHub Issues](https://github.com/ellmos-ai/bach/issues)
- **Discussions:** [GitHub Discussions](https://github.com/ellmos-ai/bach/discussions)

---

English version: [README.md](README.md)

*Generiert mit `bach docs generate readme --lang de`*
