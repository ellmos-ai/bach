# BACH - Textbasiertes Betriebssystem fuer LLMs

**Version:** v3.8.0-sugar-of-babel
**Status:** Production-Ready
**Lizenz:** MIT

## Ueberblick

BACH ist ein textbasiertes Betriebssystem, das Large Language Models (LLMs) befaehigt, eigenstaendig zu arbeiten, zu lernen und sich zu organisieren. Es bietet eine umfassende Infrastruktur fuer Task-Management, Wissensmanagement, Automatisierung und LLM-Orchestrierung.

### Kernfunktionen

- **10 KI-Agenten** - Spezialisierte Agenten fuer verschiedene Aufgabenbereiche
- **273 Tools** - Umfangreiche Tool-Bibliothek fuer Dateiverarbeitung, Analyse, Automation
- **927 Skills** - Wiederverwendbare Workflows und Templates
- **0 Workflows** - Vorgefertigte Prozess-Protokolle
- **Wissensspeicher** - 147 Lessons + 249 Facts

## Installation

```bash
# Repository klonen
git clone https://github.com/ellmos-ai/bach.git
cd bach

# Abhaengigkeiten installieren
pip install -r requirements.txt

# BACH initialisieren
python system/setup.py
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
Vollstaendiges GTD-System mit Priorisierung, Deadlines, Tags und Context-Tracking.

### 2. Wissenssystem
Strukturiertes Memory-System mit Facts, Lessons und automatischer Konsolidierung.

### 3. Agenten-Framework
Boss-Agenten orchestrieren Experten fuer komplexe Aufgaben (Buero, Gesundheit, Produktion, etc.).

### 4. Bridge-System
Connector-Framework fuer externe Services (Telegram, Email, WhatsApp, etc.).

### 5. Automatisierung
Scheduler fuer wiederkehrende Tasks und Event-basierte Workflows.

## OpenClaw-Abgleich

Stand 2026-04-30: OpenClaw bleibt fuer BACH vor allem als Vergleichssystem fuer breite Messaging-Anbindung, Plugin-Oekosystem und Security-Patterns relevant. Fuer BACH passen aktuell besonders manifest-first Plugin-Metadaten, fail-closed Tool-Setup-Checks und Scans vor der Installation von Skills, MCP-Servern und Plugins.

## Dokumentation

- **[Erste Schritte](docs/getting-started.md)** - Erste Schritte mit BACH
- **[API-Referenz](docs/reference/)** - Vollstaendige API-Dokumentation
- **[Skills-Katalog](SKILLS.md)** - Alle verfuegbaren Skills
- **[Agenten-Katalog](AGENTS.md)** - Alle verfuegbaren Agenten

## Lizenz

MIT License - siehe [LICENSE](LICENSE) fuer Details.

## Support

- **Issues:** [GitHub Issues](https://github.com/ellmos-ai/bach/issues)
- **Discussions:** [GitHub Discussions](https://github.com/ellmos-ai/bach/discussions)

---

English version: [README.md](README.md)

*Generiert mit `bach docs generate readme --lang de`*
