# BACH - Textbasiertes Betriebssystem für LLMs

**Version:** v3.8.0-sugar-of-babel
**Status:** Production-Ready
**Lizenz:** MIT

## Überblick

BACH ist ein textbasiertes Betriebssystem, das Large Language Models (LLMs) befähigt, eigenständig zu arbeiten, zu lernen und sich zu organisieren. Es bietet eine umfassende Infrastruktur für Task-Management, Wissensmanagement, Automatisierung und LLM-Orchestrierung.

### Kernfunktionen

- **109+ Handler** - CLI- und API-Abdeckung für Systemfunktionen
- **373+ Tools** - Umfangreiche Tool-Bibliothek für Dateiverarbeitung, Analyse und Automation
- **932+ Skills** - Wiederverwendbare Workflows und Templates
- **54 Protocol Workflows** - Vorgefertigte Prozess-Protokolle
- **Install Security Gate** - Statische Scans für `skills install`, `plugins load` und MCP-Setup/Config-Aktivierung; Plugin-Setups mit Shell/Desktop/MCP-Zugriff brauchen jetzt explizite fail-closed Guards, blockierte lokale Importe werden quarantänisiert
- **Manifest-first Plugins** - `bach plugins inspect` zeigt Aktivierung, Provider-/Model-, Setup- und Capability-Metadaten ohne Runtime-Import
- **Wissensspeicher** - Lessons, Facts und mehrstufiges Memory-System

## Installation

```bash
# Repository klonen
git clone https://github.com/ellmos-ai/bach.git
cd bach

# Abhängigkeiten installieren
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
Boss-Agenten orchestrieren Experten für komplexe Aufgaben (Büro, Gesundheit, Produktion, etc.).

### 4. Bridge-System
Connector-Framework für externe Services (Telegram, Email, WhatsApp, etc.).

### 5. Automatisierung
Scheduler fuer wiederkehrende Tasks und Event-basierte Workflows.

## OpenClaw-Abgleich

Stand 2026-05-06: OpenClaw bleibt für BACH vor allem als Vergleichssystem für breite Messaging-Anbindung, Plugin-Ökosystem und Security-Patterns relevant. Die aktuelle stabile GitHub-Release ist `2026.5.4` vom 5. Mai 2026; auf derselben Release-Seite ist `2026.5.4-beta.3` als Pre-Release sichtbar. Für BACH passen aktuell besonders manifest-first Plugin-Metadaten, fail-closed Tool-Setup-Checks, aktive Laufsteuerung an sicheren Checkpoints, Memory-/Wiki-Provenance und Scans mit Quarantäne vor der Installation bzw. Aktivierung von Skills, MCP-Servern und Plugins. BACH deckt davon jetzt zusätzlich explizite Setup-Guards für Shell/Desktop/MCP-Flächen in Plugin-Manifests ab.

## Dokumentation

- **[Erste Schritte](docs/getting-started.md)** - Erste Schritte mit BACH
- **[API-Referenz](docs/reference/)** - Vollständige API-Dokumentation
- **[Skills-Katalog](SKILLS.md)** - Alle verfügbaren Skills
- **[Agenten-Katalog](AGENTS.md)** - Alle verfuegbaren Agenten

## Lizenz

MIT License - siehe [LICENSE](LICENSE) für Details.

## Support

- **Issues:** [GitHub Issues](https://github.com/ellmos-ai/bach/issues)
- **Discussions:** [GitHub Discussions](https://github.com/ellmos-ai/bach/discussions)

---

English version: [README.md](README.md)

*Generiert mit `bach docs generate readme --lang de`*
