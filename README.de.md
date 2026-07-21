<img src="assets/banner_v2.png" width="100%" alt="BACH Banner">

# ellmos BACH — Textbasiertes Betriebssystem für LLMs

> Der Strom, der alles verbindet.

[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)](https://python.org)
[![Lizenz: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/Version-v3.13.0--bluesky-orange)](CHANGELOG.md)
[![Status](https://img.shields.io/badge/Status-Production--Ready-brightgreen)](ROADMAP.md)

**Version:** v3.13.0-bluesky

## 🎬 Demo-Video

BACH live in Aktion — Dashboard, Codex-Backend, Operator-Steuerung — in 2:22:

[![BACH-Demo — local-first LLM-Betriebssystem (2:22)](https://img.youtube.com/vi/Gv5nxF8HssU/maxresdefault.jpg)](https://youtu.be/Gv5nxF8HssU)

## Sprachen

BACH wird mit Dokumentations- und Übersetzungsoberflächen für sechs Sprachen ausgeliefert:

[🇬🇧 English](README.md) | **🇩🇪 Deutsch** | [🇪🇸 Español](README.es.md) | [🇷🇺 Русский](README.ru.md) | [🇯🇵 日本語](README.ja.md) | [🇨🇳 中文](README.zh.md)

Der aktuelle Release-Snapshot aktiviert `de`, `en`, `es`, `ru`, `ja` und `zh` in `system/exports/translations/languages_config.release.json` und exportiert passende Locale-Dateien in `system/exports/translations/locales/`. Für Crawler und direkte Spracheinstiege hat jede Sprache zusätzlich eine eigene `README.md` unter `docs/i18n/<lang>/`.

## Überblick

BACH ist ein textbasiertes Betriebssystem, das Large Language Models (LLMs) befähigt, eigenständig zu arbeiten, zu lernen und sich zu organisieren. Es bietet eine umfassende Infrastruktur für Task-Management, Wissensmanagement, Automatisierung und LLM-Orchestrierung.

## Such- und Abgrenzungskontext

BACH ist am besten als **local-first LLM-Betriebssystem** zu verstehen: eine dauerhafte Python-/SQLite-Arbeitsumgebung für autonome Agenten, strukturiertes Gedächtnis, Scheduler-Automation, Prompt-Ketten, MCP-Server-Integration und mehrsprachige Bedienoberflächen. Es ist kein Chatbot-Wrapper, kein gehostetes Agent-SaaS, kein Bash-Testframework, kein Musikprojekt und keine LangChain-artige Pipeline-Bibliothek.

Sinnvolle Suchphrasen sind `local-first LLM operating system`, `text-based OS for LLM agents`, `SQLite memory for AI agents`, `BACH ellmos agent OS`, `personal agentic OS Python SQLite` und `multi-agent orchestration with MCP servers`.

## OpenAI Build Week — Codex und GPT-5.6

BACH nutzt Codex in zwei klar getrennten Rollen:

- **Laufzeit-Backend:** `codex-cli` ist eines von fünf austauschbaren Chat-Backends; BACH-Agenten können Programmieraufgaben über `codex exec` delegieren.
- **Repository-Entwicklung:** Drei aktive Codex-Automationen pflegen das Projekt: `bach-daily-care-and-dev-check`, `bach-start-and-health-checks` und `bach-github-release-service`. Seit dem 21. Juli 2026 sind alle drei für GPT-5.6 (`gpt-5.6-terra`) konfiguriert; die ersten beiden laufen täglich, der Release-Service wöchentlich.
- **Verifiziertes Modell-Routing:** In Codex-Session `019f85c6-4339-7f13-b8e5-bf1823fd8432` prüfte GPT-5.6 Sol mit hohem Reasoning alle 78 Automationsdefinitionen und routete BACHs Entwicklungs- und Release-Aufgaben auf Terra/high sowie die Health-Checks auf Terra/medium.
- **Abschlussprüfung der Einreichung:** GPT-5.6 Sol prüfte und zertifizierte in Codex-Session `019f8674-fe9a-7d91-a80f-7ee799e8ced0` die ausstehenden BACH-Änderungen, korrigierte die Wettbewerbsangaben und schloss die Härtung und Regressionstests des Web-Scrapers ab.

Zur Nachvollziehbarkeit gilt die GPT-5.6-Zuordnung der Automationen erst ab dieser Konfigurationsänderung; frühere Automationsläufe verwendeten frühere Codex-Modelle.

### Kernfunktionen

- **113+ Handler** - CLI- und API-Abdeckung für Systemfunktionen
- **550+ Tools** - Umfangreiche Tool-Bibliothek für Dateiverarbeitung, Analyse und Automation
- **1870+ Skills** - Wiederverwendbare Workflows und Templates
- **Skill-Source-Registry** - `bach skills version bach` löst den kanonischen Repo-Root-Skill jetzt über `system/data/skill_sources.json` auf und kann optionale Codex-/Claude-Nutzerkopien ohne fuzzy Dateinamen-Drift vergleichen
- **71 Workflow-Vorlagen** - Vorgefertigte Prozess-Workflows
- **Agent Doctor** - `bach agent doctor [name] [--json]` prüft Claude CLI, Laufzeitverzeichnisse, SKILL.md und veraltete PID-Dateien vor dem Start
- **Agent-Operator-Steuerung** - `bach agent pause/resume/checkpoint/steer/clear-steer [name] [--json]` erlaubt kooperative Pauseanforderungen und Operator-Hinweise vor dem Start oder während des Laufs, ergänzt explizite Checkpoint-Bestätigungen, spiegelt den Zustand in `OPERATOR_NOTES.md`, erhält vorgemerkte Hinweise über den nächsten `bach agent start` hinweg, injiziert sie in die generierte Session-`CLAUDE.md` und zeigt den Vorstart- und Kontrollzustand maschinenlesbar über `queued_for_next_start` plus verschachteltes `operator_control`
- **Scheduler Doctor** - `bach scheduler doctor [--json]` sowie `bach scheduler session doctor [--json]` prüfen Automations-Skripte, PID-Status, DB-/Config-/Profil-Flächen und schlagen Recovery-Schritte vor
- **Session-Steuerung** - `bach scheduler session pause/resume/steer/clear-steer [--json]` steuert profilspezifische Auto-Sessions und liefert bei Bedarf maschinenlesbare Antworten, ohne die Daemon-Config manuell umzuschreiben
- **Scheduler-Laufsteuerung** - `bach scheduler pause/resume/steer/clear-steer [--json]` pausiert fällige Jobs global, reicht vorgemerkte Hinweise an Job-/Chain-Läufe weiter und hydratisiert schedulerweite Steer-Hinweise jetzt auch in llmauto-Ketten bis zum nächsten sicheren Checkpoint
- **Upgrade-Drift- und Reparaturpfad** - `bach upgrade list <Pfad> --json`, `bach upgrade status/check --json` und `bach upgrade repair [--dry-run] [--version <Tag>]` liefern maschinenlesbare Versions-, Status-, Drift-, Reparatur- und Recovery-Flächen für Releases, Dashboards und Automationen
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
Boss-Agenten orchestrieren Experten für komplexe Aufgaben (Büro, Gesundheit, Produktion, etc.). `bach agent` unterstützt inzwischen Vorstart-Steering, kooperative Pauseanforderungen, explizite Checkpoint-Bestätigungen via `bach agent checkpoint` und maschinenlesbare `operator_control`-Snapshots für laufende oder vorgemerkte Agentenläufe.

### 4. Chat-Service & Bridge-System
Multi-Backend Telegram-Bot mit wechselbaren LLM-Backends (Ollama, Claude CLI, Codex CLI, Claude API, OpenAI API), HTTP Control API mit Web-Dashboard und plattformübergreifendem System Tray. Connector-Framework für weitere Services (Email, WhatsApp, etc.) und USMC-Bridge für Cross-Agent-Kommunikation.

### 5. Automatisierung
SchedulerService für zeitbasierte Jobs (Chains, Tasks, Scripts) und Event-basierte Workflows über das Hook-Framework.

### 6. SharedMemory
Multi-Agent-Koordination mit Kontextgenerierung, Konflikterkennung, Decay und Delta-Queries.

### 7. llmauto-Integration
Chain-Schritte als LLM-Prompts mit `bach://` URL-Auflösung für dynamische Kontext-Einbettung.

## OpenClaw-Abgleich

Stand 2026-07-19: OpenClaw Stable bleibt `2026.7.1`; das neueste sichtbare Prerelease ist `2026.7.2-beta.3`, veröffentlicht am 2026-07-18 um 23:16 UTC. Es erweitert die bereits beobachteten Signale zu session-lokaler MCP-Isolation, task-ledger-basierter Cron-Historie, Remote-Workern und Recovery um Remote-Coding-Sessions auf dem owning host, geführtes Control-UI-/Channel-Setup, robustere Gateway-/Session-Recovery, sicherere Channel-Bedienung und versionierte Restart-Handoffs für externe Supervisoren. Für BACH passen davon vor allem supervised Restart-Handoffs, Terminal-Resume auf dem owning host, gehärtete Setup-Flows und recovery-sichere Channel-/Session-Pfade; breite Mobile-/Channel-Parität bleibt weiter außerhalb des aktuellen Fokus. Quelle: [openclaw/openclaw releases](https://github.com/openclaw/openclaw/releases/tag/v2026.7.2-beta.3).

Auf BACH-Seite hat der Daily-Care-Lauf vom 2026-07-19 den Live-Release-Katalog versiegelt: `bach upgrade repair --version v3.13.0-bluesky --json` registriert den aktuellen Release jetzt real, und `bach upgrade check --json` meldet Stable/Latest `v3.13.0-bluesky`, `release_entries=2`, `current_release_registered=true`, `repair_recommended=false` und `local_modifications=0`. `test-agent`-Doctor/Start-Dry-Run sowie Usecase `50` liefen ebenfalls erfolgreich.

## Dokumentation

- **Sprachen:** [English](README.md) | [Deutsch](README.de.md) | [Español](README.es.md) | [Русский](README.ru.md) | [日本語](README.ja.md) | [中文](README.zh.md)
- **[Schnellstart](QUICKSTART.md)** - Erste Schritte mit BACH
- **[Benutzerhandbuch](BACH_USER_MANUAL.md)** - Vollständiges Handbuch
- **[Skills-Katalog](SKILLS.de.md)** - Öffentlicher Einstieg in verfügbare Skills
- **[Agenten-Katalog](AGENTS.template.de.md)** - Vorlage und öffentlicher Einstieg für Agenten und Experten
- **[Workflows](WORKFLOWS.template.de.md)** - 71 Workflow-Vorlagen
- **[SKILL-Vorlage](SKILL.template.de.md)** - LLM-Betriebsanweisungen für Claude, Gemini, Ollama und Codex-artige Agenten

## Lizenz

MIT License - siehe [LICENSE](LICENSE) für Details.

## Support

- **Issues:** [GitHub Issues](https://github.com/ellmos-ai/bach/issues)
- **Discussions:** [GitHub Discussions](https://github.com/ellmos-ai/bach/discussions)

---

English version: [README.md](README.md)

*Generiert mit `bach docs generate readme --lang de`*
