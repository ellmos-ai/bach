# BACH - Textbasiertes Betriebssystem für LLMs

**Version:** v3.12.4-earth
**Status:** Production-Ready
**Lizenz:** MIT

## Sprachen

BACH wird mit Dokumentations- und Übersetzungsoberflächen für sechs Sprachen ausgeliefert:

[English](README.md) | [Deutsch](README.de.md) | [Español](README.es.md) | [Русский](README.ru.md) | [日本語](README.ja.md) | [中文](README.zh.md)

Der aktuelle Release-Snapshot aktiviert `de`, `en`, `es`, `ru`, `ja` und `zh` in `system/exports/translations/languages_config.release.json` und exportiert passende Locale-Dateien in `system/exports/translations/locales/`. Für Crawler und direkte Spracheinstiege hat jede Sprache zusätzlich eine eigene `README.md` unter `docs/i18n/<lang>/`.

## Überblick

BACH ist ein textbasiertes Betriebssystem, das Large Language Models (LLMs) befähigt, eigenständig zu arbeiten, zu lernen und sich zu organisieren. Es bietet eine umfassende Infrastruktur für Task-Management, Wissensmanagement, Automatisierung und LLM-Orchestrierung.

### Kernfunktionen

- **113+ Handler** - CLI- und API-Abdeckung für Systemfunktionen
- **550+ Tools** - Umfangreiche Tool-Bibliothek für Dateiverarbeitung, Analyse und Automation
- **1870+ Skills** - Wiederverwendbare Workflows und Templates
- **59 Workflow-Vorlagen** - Vorgefertigte Prozess-Workflows
- **Agent Doctor** - `bach agent doctor [name] [--json]` prüft Claude CLI, Laufzeitverzeichnisse, SKILL.md und veraltete PID-Dateien vor dem Start
- **Agent-Operator-Steuerung** - `bach agent pause/resume/steer/clear-steer [name] [--json]` erlaubt kooperative Pauseanforderungen und Operator-Hinweise vor dem Start oder während des Laufs, spiegelt den Zustand in `OPERATOR_NOTES.md`, erhält vorgemerkte Hinweise über den nächsten `bach agent start` hinweg, injiziert sie in die generierte Session-`CLAUDE.md` und zeigt den Vorstart- und Kontrollzustand maschinenlesbar über `queued_for_next_start` plus verschachteltes `operator_control`
- **Scheduler Doctor** - `bach scheduler doctor [--json]` sowie `bach scheduler session doctor [--json]` prüfen Automations-Skripte, PID-Status, DB-/Config-/Profil-Flächen und schlagen Recovery-Schritte vor
- **Session-Steuerung** - `bach scheduler session pause/resume/steer/clear-steer [--json]` steuert profilspezifische Auto-Sessions und liefert bei Bedarf maschinenlesbare Antworten, ohne die Daemon-Config manuell umzuschreiben
- **Upgrade-Drift-Check** - `bach upgrade list <Pfad> --json` sowie `bach upgrade status/check --json` liefern maschinenlesbare Versions-, Status-, Drift- und Fehlerflächen für Releases, Dashboards und Automationen
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
Boss-Agenten orchestrieren Experten für komplexe Aufgaben (Büro, Gesundheit, Produktion, etc.). `bach agent` unterstützt inzwischen Vorstart-Steering, kooperative Pauseanforderungen und maschinenlesbare `operator_control`-Snapshots für laufende oder vorgemerkte Agentenläufe.

### 4. Chat-Service & Bridge-System
Multi-Backend Telegram-Bot mit wechselbaren LLM-Backends (Ollama, Claude CLI, Codex CLI, Claude API, OpenAI API), HTTP Control API mit Web-Dashboard und plattformübergreifendem System Tray. Connector-Framework für weitere Services (Email, WhatsApp, etc.) und USMC-Bridge für Cross-Agent-Kommunikation.

### 5. Automatisierung
SchedulerService für zeitbasierte Jobs (Chains, Tasks, Scripts) und Event-basierte Workflows über das Hook-Framework.

### 6. SharedMemory
Multi-Agent-Koordination mit Kontextgenerierung, Konflikterkennung, Decay und Delta-Queries.

### 7. llmauto-Integration
Chain-Schritte als LLM-Prompts mit `bach://` URL-Auflösung für dynamische Kontext-Einbettung.

## OpenClaw-Abgleich

Stand 2026-05-22: GitHub Releases markiert `2026.5.20`, veröffentlicht am 2026-05-21 um 20:44 UTC, als aktuelle Stable-Linie von OpenClaw; als neuestes sichtbares Prerelease im Release-Feed bleibt `2026.5.20-beta.2`, veröffentlicht am 2026-05-21 um 15:57 UTC. Die öffentliche GitHub-Paketseite zeigt inzwischen die stabile `2026.5.20-slim`-Familie inklusive `2026.5.20-slim-amd64` und zusätzlich schon die neuere Alpha-Containerlinie `2026.5.21-alpha.1-slim`, die etwa 14 Stunden vor dieser Prüfung veröffentlicht wurde. Für BACH bleibt OpenClaw vor allem als Vergleichssystem für Plugin-Sicherheit, Laufzeitdiagnostik, Operator-Steuerung, QA-Parität und Release-Härtung relevant. Die aktuellen offiziellen Hinweise schärfen nun besonders runtime-flächenspezifische Codex-Hinweise, getypte Tool-Plugin-`build`/`validate`/`init`-Flows, Browser-Dialog-Snapshots mit `blockedByDialog`, per-Agent-`localModelLean`, xAI-Device-Code-OAuth für headless Setups, providerweite OpenRouter-Routing-Defaults, klarere Entscheidungen zur Pflege veralteter Tasks, Warnungen zu versteckten MCP-Tools und Plaintext-Secrets, Aufgabenwartungs-JSON, QA-Parität plus Tool-Coverage-Reporting für Codex-vs-Pi-Laufzeiten, Config-Reload-Metadaten sowie Timeout-Watchdogs für Codex-/Image-Generate-Flows. BACH deckt bereits manifest-first Plugin-Metadaten, fail-closed Setup-Guards für Shell/Desktop/MCP-Flächen, Scans mit Quarantäne vor der Installation von Skills/MCP-Servern/Plugins, Memory-/Wiki-Provenance-Ansichten, kanonische `bach path`-Oberflächen, maschinenlesbare Agent-/Scheduler-Statusflächen, `bach agent doctor` sowie `bach scheduler doctor` und `bach scheduler session doctor` als operatorseitige Startdiagnosen, scheduler-weite Operator-Steuerung über `bach scheduler pause/resume/steer/clear-steer --json` inklusive globaler Due-Job-Pause und vorgemerkter Hinweise für Job-/Chain-Läufe, workspace-scoped Cache-Invalidierung in der Agent-Runtime, maschinenlesbare Upgrade-Flächen über `bach upgrade list/status/check --json` und jetzt auch kooperative Agenten-Pausen über `bach agent pause/resume --json` mit verschachteltem `operator_control`-Snapshot ab. Neu hinzugekommen ist dabei außerdem die vertiefte Vorstart-Steuerung für Agenten: `bach agent steer` kann Hinweise jetzt vor dem eigentlichen Start vormerken, `bach agent list/status --json` zeigen dafür `queued_for_next_start`, und der nächste `bach agent start` übernimmt diese Hinweise nicht nur, sondern injiziert sie direkt in die generierte Session-`CLAUDE.md`. Zusätzlich spiegelt `OPERATOR_NOTES.md` aktive Pause- und Steering-Wünsche, und `bach lang report` blendet technisches JavaScript-Rauschen wie DOM-IDs, API-Pfade und Console-Strings aus, damit GUI-Aufräumlisten auf echte UI-Texte fokussieren. Der heutige Live-Check hat außerdem `--startup quick`, `agent doctor/start/pause/resume/steer/status`, `scheduler doctor`, `usecase run 12/41 --dry-run`, `lang report --surface gui` und `upgrade check --json` erneut verifiziert. Nächste Schritte: Active-Run-Steering tiefer innerhalb langlaufender Agenten, engere Tool-/Connector-Scopes pro Agent, härtere Ingest-Validierung und Cleanup fehlerhafter Zustände, Low-Cardinality-Telemetrie, Release-Validierung und die priorisierte Bereinigung der vom `bach lang report` sichtbaren UI-/Hilfe-/Skill-/Tool-Texte.

## Dokumentation

- **Sprachen:** [English](README.md) | [Deutsch](README.de.md) | [Español](README.es.md) | [Русский](README.ru.md) | [日本語](README.ja.md) | [中文](README.zh.md)
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
