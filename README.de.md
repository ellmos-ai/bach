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
- **Strukturierte `bach_api`-Kernmodule** - `task` und `memory` bieten jetzt über `dir(...)` auffindbare Methoden, liefern bei häufigen Reads/Writes Python-Objekte zurück und behalten `raw(...)` für Legacy-Handler-Aufrufe
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

Stand 2026-05-09: OpenClaw bleibt für BACH vor allem als Vergleichssystem für breite Messaging-Anbindung, Plugin-Ökosystem und Security-Patterns relevant. Die aktuelle stabile GitHub-Release bleibt laut GitHub Releases `2026.5.7` vom 7. Mai 2026. Für BACH sind aus der jüngsten Linie `2026.4.x` bis `2026.5.7` vor allem die Control-Plane-Impulse relevant: workspace-scoped Plugin-Metadaten-Snapshots auf Hot Paths, Install-Hinweise für fehlende offizielle Erweiterungen, kollisionssichere Session-Memory-Captures bei wiederholtem Reset/New, Cache-Invalidierung nach Skill-Änderungen sowie strengere fail-closed Config-/Setup-Prüfungen und Auth-Gates. BACH deckt davon bereits manifest-first Plugin-Metadaten, fail-closed Setup-Guards für Shell/Desktop/MCP-Flächen, Scans mit Quarantäne vor der Installation bzw. Aktivierung von Skills, MCP-Servern und Plugins, heuristische Memory-/Wiki-Provenance-Ansichten für Quelle, Evidenzart, Personenbezug und Privacy-Hinweise sowie neue maschinenlesbare Agent-/Scheduler-Statusflächen ab.

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
