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

## Such- und Abgrenzungskontext

BACH ist am besten als **local-first LLM-Betriebssystem** zu verstehen: eine dauerhafte Python-/SQLite-Arbeitsumgebung für autonome Agenten, strukturiertes Gedächtnis, Scheduler-Automation, Prompt-Ketten, MCP-Server-Integration und mehrsprachige Bedienoberflächen. Es ist kein Chatbot-Wrapper, kein gehostetes Agent-SaaS, kein Bash-Testframework, kein Musikprojekt und keine LangChain-artige Pipeline-Bibliothek.

Sinnvolle Suchphrasen sind `local-first LLM operating system`, `text-based OS for LLM agents`, `SQLite memory for AI agents`, `BACH ellmos agent OS`, `personal agentic OS Python SQLite` und `multi-agent orchestration with MCP servers`.

### Kernfunktionen

- **113+ Handler** - CLI- und API-Abdeckung für Systemfunktionen
- **550+ Tools** - Umfangreiche Tool-Bibliothek für Dateiverarbeitung, Analyse und Automation
- **1870+ Skills** - Wiederverwendbare Workflows und Templates
- **59 Workflow-Vorlagen** - Vorgefertigte Prozess-Workflows
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

Stand 2026-06-06: GitHub Releases zeigt `2026.6.1`, veröffentlicht am 2026-06-03, als aktuelle Stable-Linie von OpenClaw; das neueste sichtbare Prerelease im offiziellen Release-Feed ist `2026.6.5-beta.1`, veröffentlicht am 2026-06-06. Für BACH sind aus Stable und den frischen Juni-Betas vor allem sauberere Recovery nach unterbrochenen Tool-Calls, veralteten Session-Bindings, Prompt-Cache-Ablauf oder Gateway-Neustarts, strengere Timer-/Retry-Grenzen und Doctor-/Upgrade-Wartepfade, mehr SQLite-gestützte Auth-, Plugin-Install- und Inbound-Queue-Zustände, breitere Workboard-/SecretRef-Flächen sowie eine robustere Materialisierung reicher MCP-Toolresultate relevant. Auf BACH-Seite hat der Live-Check vom 2026-06-06 den GUI-Drift-Report um zusätzliche JS-`class`-/`id`-Rauschfilter erweitert, mehrere sichtbare Oberflächen wieder auf echte Umlaute gehoben und 29 zusätzliche GUI-DE-Schlüssel in den bestehenden `gui`-Namespace aufgenommen; die Release-Artefakte stehen damit jetzt bei 17.488 exportierten Übersetzungen. Derselbe Lauf hat außerdem `bach agent doctor test-agent --json`, den vollständigen `test-agent`-Steuerzyklus (`clear-steer`, `steer`, `start`, `status`, `pause`, `checkpoint`, `resume`, `stop`, `clear-steer`), `bach usecase run 12 --dry-run`, `bach usecase run 41 --dry-run`, `bach usecase run-all --dry-run`, `bach upgrade status/check --json` und `bach lang report --surface gui --limit 20 --json` erneut verifiziert; der GUI-Report liegt jetzt bei 94 offenen eindeutigen Einträgen und 111 offenen Fundstellen, während Usecase 41 weiterhin ohne verknüpfte Workflow-Datei im manuellen Fallback landet. Nächste Schritte bleiben tieferes Active-Run-Steering in langlaufenden Scheduler-Innenschleifen, Low-Cardinality-Telemetrie, Installer-End-to-End- sowie GUI-Regressionsabdeckung und die priorisierte Bereinigung der vom `bach lang report` sichtbaren UI-/Hilfe-/Skill-/Tool-Texte.

## Dokumentation

- **Sprachen:** [English](README.md) | [Deutsch](README.de.md) | [Español](README.es.md) | [Русский](README.ru.md) | [日本語](README.ja.md) | [中文](README.zh.md)
- **[Schnellstart](QUICKSTART.md)** - Erste Schritte mit BACH
- **[Benutzerhandbuch](BACH_USER_MANUAL.md)** - Vollständiges Handbuch
- **[Skills-Katalog](SKILLS.de.md)** - Öffentlicher Einstieg in verfügbare Skills
- **[Agenten-Katalog](AGENTS.template.de.md)** - Vorlage und öffentlicher Einstieg für Agenten und Experten
- **[Workflows](WORKFLOWS.template.de.md)** - 59 Workflow-Vorlagen
- **[SKILL-Vorlage](SKILL.template.de.md)** - LLM-Betriebsanweisungen für Claude, Gemini, Ollama und Codex-artige Agenten

## Lizenz

MIT License - siehe [LICENSE](LICENSE) für Details.

## Support

- **Issues:** [GitHub Issues](https://github.com/ellmos-ai/bach/issues)
- **Discussions:** [GitHub Discussions](https://github.com/ellmos-ai/bach/discussions)

---

English version: [README.md](README.md)

*Generiert mit `bach docs generate readme --lang de`*
