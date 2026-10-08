# BACH - Textbasiertes Betriebssystem für LLMs

**Version:** v3.14.0
**Status:** Production-Ready
**Lizenz:** MIT

## Überblick

BACH ist ein textbasiertes Betriebssystem, das Large Language Models (LLMs) befähigt, eigenständig zu arbeiten, zu lernen und sich zu organisieren. Es bietet eine umfassende Infrastruktur für Task-Management, Wissensmanagement, Automatisierung und LLM-Orchestrierung.

### Kernfunktionen

- **Agenten und Blueprints** – Rollen, Experten, lokale Steckplätze und beobachtete Läufe
- **Tools und Skills** – Aktuelle Quellen, Bearbeitung und Versionshistorie
- **Aufgaben** – Zuweisung, atomare Leases und nachvollziehbare Bearbeitung
- **Wissensspeicher** – Facts, Lessons und angebundene kanonische Quellen

Verfügbarkeit hängt von den installierten Providern und der lokalen Konfiguration ab.
Die [GUI-Integrationshilfe](system/docs/help/gui-integration.txt) erläutert den Unterschied zwischen registriertem Adapter und geprüftem Lauf.

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
Vollständiges GTD-System mit Priorisierung, Deadlines, Tags und Context-Tracking.

### 2. Wissenssystem
Strukturiertes Memory-System mit Facts, Lessons und automatischer Konsolidierung.

### 3. Agenten-Framework
Boss-Agenten orchestrieren Experten für komplexe Aufgaben (Büro, Gesundheit, Produktion, etc.).

### 4. Bridge-System
Connector-Framework für externe Services (Telegram, Email, WhatsApp, etc.).

### 5. Automatisierung
Scheduler für wiederkehrende Tasks und Event-basierte Workflows.

## Dokumentation

- **[Gemeinsame GUI und Agenten](system/docs/help/gui-integration.txt)** – Bedienung und tatsächliche Adapterprüfung
- **[Ocean–BACH-Transferplan](OCEAN-TRANSFER-PLAN.md)** – Installer, erster Modultransfer und weitere Aufgaben
- **[Deprecation-Register](DEPRICATED.md)** – Ersatz, offene Abnahmen und Rollback

- **[Erste Schritte](QUICKSTART.de.md)** - Erste Schritte mit BACH
- **[Befehlsreferenz](BACH_HELP_REFERENCE.template.de.md)** - Vollständige API-Dokumentation
- **[Skills-Katalog](SKILLS.template.de.md)** - Alle verfügbaren Skills
- **[Agenten-Katalog](AGENTS.template.de.md)** - Alle verfügbaren Agenten

## Lizenz

MIT License - siehe [LICENSE](LICENSE) für Details.

## Support

- **Issues:** [GitHub Issues](https://github.com/ellmos-ai/bach/issues)
- **Discussions:** [GitHub Discussions](https://github.com/ellmos-ai/bach/discussions)

---

English version: [README.md](README.md)

*Deutschsprachiger Einstieg; die operative Modul- und Transferdokumentation ist oben verlinkt.*
