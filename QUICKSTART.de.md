# BACH Schnellstart

**Version:** v3.9.1-tiramisu

## In 5 Minuten zum ersten BACH-Workflow

### 1. Installation (2 Minuten)

```bash
# Repository klonen
git clone https://github.com/ellmos-ai/bach.git
cd bach

# Pre-Flight-Check ausführen
bach setup preflight

# Vollständige Installation (MCP-Server, Hooks, Secrets, User-Profil)
bach setup full-install
```

> **Hinweis:** `bach` ist der CLI-Einstiegspunkt (`system/bach.py`). Falls `bach`
> nicht im PATH ist, stattdessen `python system/bach.py` verwenden.

### 2. Erste Schritte (3 Minuten)

#### BACH starten

```bash
bach --startup
```

#### Tasks erstellen und verwalten

```bash
# Neue Aufgabe anlegen
bach task add "Erstes BACH-Experiment"

# Aufgaben anzeigen
bach task list

# Aufgabe erledigen
bach task done 1
```

#### Wissen speichern und abrufen

```bash
# Fakt speichern
bach mem fact "API-Endpoint: https://api.example.com/v2"

# Fakten abrufen
bach mem read facts

# Wiki-Notiz schreiben
bach wiki write "bash-tricks" "Nützliche Bash-Befehle"
```

#### Systemstatus prüfen

```bash
bach status
```

#### BACH beenden

```bash
bach --shutdown
```

---

## Wichtigste Kommandos

| Kommando | Beschreibung |
|---|---|
| `bach --startup` | Session mit allen Subsystemen starten |
| `bach --shutdown` | Sauberes Herunterfahren |
| `bach status` | System-Gesundheitscheck |
| `bach task list` | Offene Aufgaben anzeigen |
| `bach mem read facts` | Gespeicherte Fakten durchsuchen |
| `bach help <thema>` | Themenspezifische Hilfe |
| `bach setup check` | Installation validieren |

---

## Deployment-Szenarien

BACH hat **einen Installer**. Die Konfiguration bestimmt den Deployment-Modus:

### Einzelsystem (Standard)
Normales Setup, keine Synchronisation nötig.

```bash
bach setup full-install
```

### Multi-System (OneDrive-Sync)
BACH in OneDrive, lokale Datenbank pro System, synchronisiert über ProSync.

```bash
bach setup full-install
bach setup prosync --multi-system
```

### Server / Headless
BACH auf einem dauerhaft laufenden Host. Verwaltete Dienste werden über die Startspine gestartet,
damit Prozessbesitz, tatsächliche Ports, Readiness und Stop nachvollziehbar bleiben. Die
Standardendpunkte sind ausschließlich lokal gebunden. Remotezugriff benötigt einen separat
konfigurierten authentifizierten Zugang; die Control-API darf nicht direkt auf `0.0.0.0`
veröffentlicht werden.

```bash
bach setup full-install
python start/startspine.py start --chat --gui
python start/startspine.py status --json
```

---

## Nächste Schritte

1. **Dokumentation erkunden:** `bach help list`
2. **Agenten kennenlernen:** `bach agent list`
3. **Skills durchsuchen:** `cat SKILLS.md`
4. **Eigenen Workflow erstellen:** Siehe [skills/workflows/](system/skills/workflows/)

---

## Konfiguration

```bash
# Partner registrieren (Claude, Gemini, Ollama)
bach partner register claude

# Einstellungen anzeigen
bach config list

# Connectors auflisten
bach connector list
```

---

## Weiterführende Dokumentation

- **[README.md](README.md)** - Vollständige Übersicht
- **[Benutzerhandbuch](BACH_USER_MANUAL.md)** - Umfassendes Handbuch
- **[Skills-Katalog](SKILLS.md)** - Alle verfügbaren Skills
- **[Agenten-Katalog](AGENTS.md)** - Alle verfügbaren Agenten
- **[Installationsanleitung](system/docs/help/install.txt)** - Detaillierte Install-Doku

---

## Tipps

1. **Kontextuelles Arbeiten:** BACH merkt sich sessionübergreifend, woran gearbeitet wird
2. **Automatisierung:** Workflows für wiederkehrende Aufgaben nutzen
3. **Integration:** Verbindung mit Claude, Gemini, Ollama oder OpenAI
4. **Backup:** `bach backup create` für manuelle Sicherung (automatisch bei Shutdown)
5. **Hilfe:** `bach help <thema>` für jeden Handler oder jedes Konzept

---

## Hilfe bekommen

```bash
# Allgemeine Hilfe
bach --help

# Handler-spezifische Hilfe
bach help <handler>

# Dokumentation durchsuchen
bach docs search "suchbegriff"
```

---

English version: [QUICKSTART.md](QUICKSTART.md)
