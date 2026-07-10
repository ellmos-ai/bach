---
name: bach
version: 3.9.1
type: skill
author: BACH Team
created: 2025-12-01
updated: 2026-03-12
anthropic_compatible: true

description: >
  Zentrales Verwaltungssystem für BACH. Dies ist der EINZIGE Skill
  der bei Claude hochgeladen werden muss. Er kennt alle lokalen Skills,
  führt Versions-Checks durch und lädt bei Bedarf aktuellere lokale
  Versionen. Aktiviert sich automatisch bei jeder Skill-Nutzung.
---

# VERSIONS-HINWEIS

# Prüfe ob eine neuere Version dieses Skills existiert (lokal oder zentral)

# Verwende IMMER die Version mit der höchsten Versionsnummer

# Versions-Check: bach skills version bach

# Willkommen in Bach

---

## REGELN - GUIDELINES - STANDARDS

---

### IMMER (vor allem anderen)

**(1) VERSIONS-CHECK:** Wenn verschiedene Versionen dieses SKILL.md zur Verfuegung stehen (lokal, zentral), Versionsnummern vergleichen und bei Bedarf zur neuesten Version wechseln und dort weiterlesen.
```bash
bach skills version bach   # Prueft ob aktuellere Version existiert
```

**(2) BETRIEBSSYSTEM-CHECK:** Erkenne ob du auf Windows, Mac oder Linux arbeitest.
- Windows: Keine `/dev/null` UND kein `NUL:`. Stattdessen Ausgabe weglassen oder `2>&1` nutzen. Vermeide `&&`, Befehle einzeln ausfuehren
- Bei nul-Dateien: `python tools/c_nul_cleaner.py --dir <pfad> --delete`

---

### DANACH: Zugriffsart / Session-Modus klaeren

Waehle den Modus der zu deiner Situation passt:

| Modus | Wann | Startup | Zugang |
|-------|------|---------|--------|
| **A) Bibliothek** | Gast, lesend, einzelne Abfragen, BACH als Werkzeug | Kein Startup | `from bach_api import task; task.list()` |
| **B) Gemischt** | Vom User zu BACH-Start aufgefordert, aktive Mitarbeit | API Startup | `session.startup()` + API + `session.shutdown()` |
| **C) Session** | Klassisch, automatischer Start, ausfuehrliches Protokoll | CLI Startup | `python bach.py --startup --partner=claude` |

- Modus C kann jederzeit zu B wechseln (API statt CLI nutzen)
- Modus B und C koennen jederzeit zu A wechseln (einzelne Abfrage ohne Session)
- Im Zweifel: **Modus B** (empfohlen fuer LLM-Sessions)

---

### IM MODUS B und C: Regeln fuer aktive Nutzung

**(1) Lesen und Schreiben -- BACH-Nutzung ist Mitentwicklung:**

Wer BACH nutzt, entwickelt BACH mit. Jeder Zugriff ist eine Gelegenheit das System zu verbessern.

- **(a) Handler First:** Jede Funktion gehoert als Handler in `hub/`. Ein Handler ist automatisch ueber CLI **und** API erreichbar. Kein separater Code fuer verschiedene Zugangswege.
- **(b) Luecken fuellen:** Fehlen Handler, API-Module, Skills, Tools, Workflows oder andere Komponenten -- erstelle sie. Fehlende Handler haben hoechste Prioritaet, sie sind die Grundlage fuer alle Zugangswege.
- **(c) Eigenes erwuenscht:** Das Erstellen eigener Skills, Workflows, Tools, MCPs ist ausdruecklich erwuenscht. Bei der Bearbeitung bestehender Absprache mit dem User.
- **(d) Fix-or-Task:** Probleme fuehren entweder zur sofortigen Korrektur (klein) oder zu einem Task in der Queue (gross). Entscheidend: Aufwand vs. Nutzen. Danach zurueck zur eigentlichen Aufgabe.
- **(e) Self-Healing:** Findest du Fehler in BACH (Pfade, Befehle, veraltete Referenzen, kaputte Imports), korrigiere sie sofort und informiere den User. BACH repariert sich selbst durch seine Nutzer.
- **(f) Self-Extension:** Fehlt dir eine Faehigkeit, gib sie dir selbst! Nutze `bach skills create` um neue Tools, Handler, Agents, Experts oder Services zu scaffolden. Nach `bach skills reload` sind sie sofort verfuegbar. Siehe: `bach help self-extension`

**(2) Fuehre die Startprozedur durch** (siehe unten). Lies Pflichtpakete und bei Bedarf (`-->`) freiwillige Verweise. Pakete sind mit Modus-Kennzeichnung versehen:
- `[C]` → Nur im Session-Modus lesen
- `[B]` → Nur im Gemischten Modus lesen, im Session-Modus ueberspringen
- `[B/C]` → In beiden Modi lesen
- Ohne Kennzeichnung → Immer bei Bedarf lesen

**(3) Lese Zusatzpakete bei Bedarf** (Themenpakete weiter unten).

---

### IM MODUS A: Regeln fuer Gast-/Werkzeug-Nutzung

Lese Zusatzpakete bei Bedarf. Kein Startup noetig, kein Shutdown erwartet.

```python
from bach_api import task, memory, tools, steuer
task.list()         # Sofort nutzbar
tools.search("ocr") # Werkzeug finden
```

---

### Dokument-Struktur (Navigations-Karte)

```
IMMER (vor allem anderen)
├── (1) VERSIONS-CHECK
└── (2) BETRIEBSSYSTEM-CHECK

ZUGRIFFSART klaeren
├── A) Bibliothek    → Gast, lesend, Werkzeug
├── B) Gemischt      → User-gefuehrt, API + Startup (empfohlen)
└── C) Session       → Klassisch, CLI + volles Protokoll

IM MODUS B und C
├── (1) Lesen = Mitentwicklung
│   ├── (a) Handler First
│   ├── (b) Luecken fuellen
│   ├── (c) Eigenes erwuenscht
│   ├── (d) Fix-or-Task
│   └── (e) Self-Healing
├── (2) Startprozedur durchfuehren
│   ├── (1) Start              [B/C]
│   ├── (2) Systemwissen       [B/C]
│   ├── (3) Memory             [B/C]
│   ├── (4) Faehigkeiten       [B/C]
│   ├── (5) Aufgabenplanung    [B/C]
│   └── (6) Protokolle          [C]
└── (3) Zusatzpakete bei Bedarf

IM MODUS A
└── Zusatzpakete bei Bedarf

THEMEN-PAKETE (alle Modi, bei Bedarf)
├── Teamarbeit
├── Problemloesung
├── Coding
├── Wartung
├── Dateiverwaltung
├── Self-Extension              [B/C]
└── Shutdown                    [B/C]

REFERENZ
├── Skill-Architektur
├── Drei Zugriffsmodi (API-Module, Wann-was-nutzen)
├── Gesamtarchitektur-Diagramm
├── Hooks & Injektoren
└── Changelog
```

---

### Skill-Architektur v2.0 (NEU)

#### Versions-Check-Prinzip

**IMMER die neueste Version verwenden** - egal ob lokal oder zentral gespeichert:

```bash
bach skills version <name>    # Prüfe Versionen
bach tools version <name>     # Prüfe Tool-Versionen
```

#### Skill-Struktur: Ein Skill = Ein Ordner

Jeder Skill, Agent, Expert ist **vollständig autark** in einem eigenen Ordner:

```
agents/entwickler/
├── SKILL.md              # Definition mit Standard-Header
├── tool_xyz.py           # Spezifische Tools (flat)
├── protocol_abc.md       # Spezifische Protokolle (flat)
└── config.json           # Optional
```

**Regeln:**

- < 5 Dateien: Flat (alles im Root)
- >= 5 Dateien: Unterordner `tools/`, `protocols/` erlaubt
- **Im Zweifel Tools doppelt halten** (allgemein + skill-spezifisch)
- nach Export muss es ohne BACH funktionieren

#### Standard-Header (Pflicht für alle Komponenten)

```yaml
---
name: [name]
version: X.Y.Z
type: skill | agent | expert | service | protocol
author: [author]
created: YYYY-MM-DD
updated: YYYY-MM-DD
anthropic_compatible: true
dependencies:
  tools: []
  services: []
  protocols: []
description: >
  [Beschreibung]
---
```

**Templates:** `system/skills/_templates/TEMPLATE_*.md`

#### Ausbaustufen

BACH existiert in drei Stufen: **USMC** (Memory-Kern), **Rinnsal** (+ LLM-Orchestrierung), **BACH** (vollstaendiges System). Details: [README.md](README.md#ausbaustufen)

#### Drei Zugriffsmodi

BACH bietet **zwei parallele Zugangswege** (CLI + Library-API), die in **drei Modi** kombiniert werden koennen. Beide Wege nutzen dieselben Handler und dieselbe DB.

##### Modus 1: Session-Modus (CLI -- klassisch)

Volles Startup/Shutdown-Protokoll ueber die Kommandozeile. Fuer interaktive Terminal-Sessions.

```bash
cd system
python bach.py --startup --partner=claude --mode=silent --watch
# ... arbeiten ...
python bach.py --shutdown "Zusammenfassung"
```

##### Modus 2: Bibliothek-Modus (API -- leichtgewichtig)

Direkter Zugriff auf Handler ohne Session-Overhead. Fuer Scripts, schnelle Abfragen, oder LLMs die nur einzelne Operationen brauchen.

```python
from bach_api import task, memory, steuer, partner, tools, injector

task.list()                              # Tasks abfragen
memory.write("Wichtige Notiz")           # Memory schreiben
steuer.status()                          # Steuer-Status
partner.list()                           # Partner auflisten
injector.process("ich bin blockiert")    # Kognitive Hilfe
```

##### Modus 3: Gemischter Modus (API mit Session-Lifecycle)

Volles Startup/Shutdown ueber die API. **Empfohlen fuer LLM-Sessions** -- kombiniert Session-Management mit ergonomischem API-Zugriff.

```python
from bach_api import session, task, memory, injector

# Session starten (= python bach.py --startup --partner=claude --mode=silent)
session.startup(partner="claude", mode="silent")

# Arbeiten mit API
task.list()
memory.write("Notiz")
injector.process("komplexe aufgabe")

# Session beenden (= python bach.py --shutdown "Zusammenfassung")
session.shutdown("Was gemacht wurde. Naechste: Was kommt.")
```

##### Verfuegbare API-Module

```python
from bach_api import (
    # Session-Lifecycle
    session,     # startup(), shutdown(), shutdown_quick(), shutdown_emergency()

    # Kern-Handler
    task,        # add(), list(), done(), assign(), ...
    memory,      # write(), read(), status(), fact(), search(), ...
    backup,      # create(), list(), info()
    status,      # run()

    # Domain-Handler
    steuer,      # status(), beleg(), posten(), export()
    lesson,      # add(), last(), list(), search()
    partner,     # list(), status(), delegate(), info()
    logs,        # status(), tail(), show()
    msg,         # send(), unread(), read()
    email,       # send(), draft(), drafts(), confirm(), setup()

    # Kognitive Injektoren
    injector,    # process(), check_between(), tool_reminder(), status(), toggle()

    # Hook-Framework
    hooks,       # on(), off(), emit(), status(), list_events()

    # Plugin-API (Dynamische Erweiterung)
    plugins,     # register_tool(), register_hook(), register_handler(), load_plugin()

    # Raw-Zugriff (beliebiger Handler)
    app,         # app().execute("handler", "operation", ["args"])
)
```

##### Wann was nutzen

| Situation | Empfehlung |
|-----------|------------|
| LLM-Session (empfohlen) | Gemischter Modus: `session.startup()` + API |
| Schnelle Einzelabfrage | Bibliothek-Modus: direkt `task.list()` |
| Mensch am Terminal | Session-Modus: `python bach.py --startup` |
| Dateien lesen, Code suchen | Direkt (Glob/Grep/Read) |
| Handler nicht in bach_api | `app().execute("handler", "op", ["args"])` |

**Architektur:** `core/registry.py` erkennt 113+ Handler automatisch (Auto-Discovery). Neue Handler brauchen nur eine `.py`-Datei in `hub/` -- kein manuelles Mapping. Hot-Reload: `app().reload_registry()`

#### Komponenten-Typen

| Typ | Ordner | Charakteristik |
|-----|--------|----------------|
| **Agent** | `agents/<name>/` | Orchestriert Experten, eigener Ordner |
| **Expert** | `agents/_experts/<name>/` | Tiefes Domänenwissen, eigener Ordner |
| **Service** | `hub/_services/<name>/` | Allgemein, Handler-nah, eigener Ordner |
| **Protocol** | `skills/workflows/` | 1 Datei = 1 Protokoll (ehem. Workflow), Kategorie-Unterordner erlaubt |
| **Connector** | `connectors/` | Externe Anbindungen (MCP, APIs) |
| **Tool (allg.)** | `tools/` | Wiederverwendbar |
| **Tool (spez.)** | Im Skill-Ordner | Nur für diesen Skill |

#### Skill-Quellen & Sicherheit

| Klasse | Quellen | Vorgehen |
|--------|---------|----------|
| **Goldstandard** | Selbst geschrieben | Beste Integration |
| **Seriös** | anthropics/skills, anthropics/claude-cookbooks | Nach Prüfung 1:1 übernehmbar |
| **Unsicher** | Andere GitHub-Repos | NUR neu schreiben |
| **Blacklist** | `data/skill_blacklist.json` | VERBOTEN |

---

## STARTPROZEDUR [B/C]: (1) → (2) → (3) → (4) → (5) → (6)

*Nur in Modus B (Gemischt) und C (Session). Modus A ueberspringt diese Sektion.*

---

### (1) STARTe jetzt Bach [B/C]

**Modus C (Session/CLI):**

```bash
cd system
python bach.py --startup --partner=claude --mode=silent --watch
```

**Modus B (Gemischt/API -- empfohlen):**

```python
from bach_api import session
session.startup(partner="claude", mode="silent")
```

**Fuer Gemini:**

```python
# Modus B (API)
session.startup(partner="gemini", mode="silent")
# Modus C (CLI)
# python bach.py --startup --partner=gemini --mode=silent --watch
```

---

### (2) SYSTEM: Lade dein Systemwissen [B/C]

```bash
bach help cli
bach help bach_info
bach help features
bach help naming
bach help guidelines
bach help architecture
# --> bach help injectors
```

Oder per API: `help.run("cli")`, `help.run("features")`, etc.

#### Handler-Discovery & Suche

BACH hat 113+ Handler in `hub/`. **Jeder Handler ist ein CLI-Befehl.** Um Handler, Tools, Skills oder Help-Themen zu finden:

```bash
# Fuzzy-Suche in Help-Themen (187+ Themen, Fuzzy-Match!)
bach help <suchbegriff>           # z.B. bach help web → schlaegt web_scrape, web_parse vor

# Handler auflisten
bach help list                    # Alle 187+ Help-Themen
bach help cli                     # CLI-Befehlsuebersicht

# Tools durchsuchen
bach tools list                   # Alle Python-Tools
bach tools search <keyword>       # Volltextsuche in Tool-Namen und -Inhalten

# Skills & Agents durchsuchen
bach skills list                  # Alle Skills in der DB
bach skills search <keyword>      # Skills nach Keyword filtern
bach agent list                   # Alle Agenten

# Beliebigen Handler direkt aufrufen
bach <handler-name> <operation>   # z.B. bach web-scrape get <url>
```

**Wichtig:** Wenn du nicht weisst welcher Handler existiert, nutze `bach help <suchbegriff>` -- die Fuzzy-Suche schlaegt passende Themen vor, auch bei ungenauen Begriffen.

#### Dateien zur Einsicht

- `system/CHANGELOG.md` - Versionshistorie
- `system/ROADMAP.md` - Geplante Features & Architektur-Uebersicht

#### Root-Dokumente (generiert aus DB, bei `bach --shutdown` aktualisiert)

- `AGENTS.md` - Alle Boss-Agenten und Experten mit Status und Pfaden
- `PARTNERS.md` - LLM-Partner und Delegation
- `SKILLS.md` - Skill-Index
- `WORKFLOWS.md` - Protokoll-Index
- `CHAINS.md` - Toolchains
- `USECASES.md` - Anwendungsfaelle
- `USER.md` - User-Profil
- `MEMORY.md` - Memory-Snapshot
- `BACH_HELP_REFERENCE.md` - Gesamte Help-Referenz

#### Kernprinzipien

- **BACH als Organismus**: Connectors/Bridge sind die **Sinne & Stimme** (Wahrnehmung + Kommunikation mit der Aussenwelt). LLMs sind der **Verstand** (Denken, Verstehen, Entscheiden). Die Datenbank und Textdateien sind das **Gedaechtnis**. Die GUI ist das **Gesicht**. API, CLI, Tools, Agenten, Skills und Workflows sind die **Haende** (Handlungspotential).
- **Handler First**: Jede Funktion als Handler in `hub/` -- automatisch ueber CLI **und** API erreichbar
- **API bevorzugt**: LLMs nutzen `bach_api` statt CLI. Menschen nutzen CLI oder GUI.
- **Systemisch**: Wiederverwendbar fuer jeden User
- **dist_type**: 0=USER (persoenlich), 1=TEMPLATE (anpassbar), 2=CORE (System)
- **Idempotent**: Importe wiederholbar ohne Duplikate
- **Versions-Check**: Immer neueste Version verwenden

> **KERNPRINZIP:** BACH wird NICHT primaer fuer einen einzelnen User entwickelt, sondern als wiederverwendbares System.

#### Arbeitsprinzipien

Sechs Grundregeln fuer alle BACH-Partner (LLMs, Agenten, Experten):

1. **Eigene Ressourcen zuerst** — Pruefe Memory, Wiki, Tools und DB bevor du den User fragst
2. **Ergebnisse vor Prozess** — Was zaehlt ist das Resultat, nicht die Methode
3. **Handeln statt ankuendigen** — Erklaere nicht was du tun wirst, tu es einfach
4. **Meinung haben** — Du darfst widersprechen und eigene Vorschlaege machen
5. **Kompakt bleiben** — System-Prompts unter 1000 Token, Injektionen schlank halten
6. **Wissen sichern** — Erkenntnisse ins Gedaechtnis schreiben bevor der Kontext verloren geht

**Partner-spezifische Anweisungen:**
- **Claude**: Lies `CLAUDE.md` im Root-Verzeichnis (Knowledge Capture Regel, Integration)
- **Gemini**: Lies `GEMINI.md` im Root-Verzeichnis (Knowledge Capture Regel, Integration)
- **Ollama**: Lies `OLLAMA.md` im Root-Verzeichnis (Knowledge Capture Regel, Integration)

Diese Dateien enthalten detaillierte Knowledge-Capture-Regeln und Partner-spezifische Einstellungen.

#### Datenbank-Schema (138 Tabellen in bach.db)

| # | Bereich | Wichtigste Tabellen |
|---|---------|---------------------|
| 1 | System | `system_identity`, `system_config`, `instance_identity` |
| 2 | Tasks | `tasks` |
| 3 | Memory | `memory_working`, `memory_facts`, `memory_lessons`, `memory_sessions` |
| 4 | Tools | `tools` (550+ Eintraege) |
| 5 | Skills | `skills` (1870+ Eintraege) |
| 6 | Agents | `bach_agents`, `bach_experts`, `agent_synergies` |
| 7 | Files | `files_truth`, `files_trash`, `dist_files` |
| 8 | Automation | `automation_triggers`, `automation_routines`, `automation_injectors` |
| 9 | Monitoring | `monitor_tokens`, `monitor_success`, `monitor_processes`, `monitor_pricing` |
| 10 | Connections | `connections`, `connector_messages`, `partner_presence` |
| 11 | Languages | `languages_config`, `languages_translations` |
| 12 | Distribution | `distribution_manifest`, `dist_type_defaults`, `releases`, `snapshots` |
| 13 | Wiki | `wiki` (87 Artikel) |
| 14 | Usecases | `usecases`, `toolchains` |

Vollstaendiges Schema: `system/data/schema/schema.sql` (138 Tabellen + Views + FTS)

---

### BACH v2.6 GESAMTARCHITEKTUR

```text
  +=====================================================================+
  |                             USER-INTERFACES                         |
  |  +-----------+  +-----------+  +-----------+  +-------------------+ |
  |  |    CLI    |  | Lib-API   |  |    GUI    |  |  MCP v2.2 (IDE)   | |
  |  |  bach.py  |  | bach_api  |  | server.py |  |  mcp_server.py   | |
  |  +-----+-----+  +-----+-----+  +-----+-----+  +--------+--------+ |
  +========|==============|==============|==================|===========+
           |              |              |                  |
  +========v==============v==============v==================v===========+
  |                    CORE LAYER (core/*.py)                           |
  |  app.py → registry.py → Auto-Discovery von 75+ Handlern            |
  |  base.py (BaseHandler) | db.py (Schema-First) | hooks.py (Events)  |
  +=========|==============|=======================================+====+
            |              |                                       |
  +==========v==============v=======================================v===+
  |                          HUB LAYER (hub/*.py)                       |
  |  System: startup, shutdown, status, backup, tokens, inject, hooks   |
  |  Domain: steuer, abo, haushalt, gesundheit, contact, calendar, email|
  |  Data: task, memory, db, session, logs, wiki, docs, inbox           |
  |  Multi-AI: agents, partner, daemon, ollama, ati                     |
  |  Extension: skills (create/reload), hooks (status/events/log/test)  |
  +====|======================|======================|=================+
       |                      |                      |
  +----v------------------+   |   +------------------v-----------------+
  |   AGENTS LAYER        |   |   |   CONNECTORS & PARTNERS           |
  |                       |   |   |                                    |
  | agents/ (Ordner)      |   |   | connectors/ (MCP, APIs)           |
  | agents/_experts/      |   |   | partners/ (Multi-LLM-Konfig)      |
  +-----------------------+   |   +------------------------------------+
                              |
  +---------------------------v----------------------------------------+
  |   SKILLS & TOOLS LAYER                     |    DATA LAYER         |
  |                                            |                       |
  | skills/workflows/ (ehem. _workflows)      | bach.db (Unified)     |
  | skills/_templates/ (Standard-Templates)    | Dateisystem            |
  | hub/_services/ (Ordner)                    | inbox/outbox/          |
  | tools/*.py | c_*.py | injectors.py         |                       |
  +--------------------------------------------+-----------------------+
              |
  +-----------v-----------+
  | SELF-EXTENSION LAYER  |
  |                       |
  | skills create (6 Typ) |
  | skills reload (Hot)   |
  | hooks.on/emit (14 Ev) |
  | Plugin-API (geplant)  |
  +-----------------------+
```

---

### (3) MEMORY: Lade deinen Episodischen Kontext [B/C]

```bash
bach help memory
bach help lessons
bach help consolidation
```

#### Das kognitive Memory-Modell (5 Typen)

| Typ | Entsprechung | Funktion | Befehl |
|-----|--------------|----------|--------|
| **Working** | Kurzzeit | Aktuelle Session | `bach mem write` |
| **Episodic** | Tagebuch | Abgeschlossene Sessions | `bach --memory session` |
| **Semantic** | Weltwissen | Fakten, Wiki, Help | `bach --memory fact "key:value"` |
| **Procedural** | Können | Tools, Skills, Workflows | `bach help tools` |
| **Associative** | Verknüpfung | Konsolidierung, Trigger | `bach consolidate` |

---

### (4) FÄHIGKEITEN: Lade Wissen über deine Fähigkeiten [B/C]

```bash
bach help skills
bach help tools
```

**Hierarchie:**

- **Agenten**: Orchestrieren mehrere Bereiche, eigener Ordner
- **Experten**: Tiefes Domänenwissen, eigener Ordner
- **Services**: Allgemeine Dienste, Handler-nah

**Wichtige Verzeichnisse:**

- `system/agents/` - Agenten (je eigener Ordner)
- `system/agents/_experts/` - Experten (je eigener Ordner)
- `system/hub/_services/` - Services (je eigener Ordner)
- `system/skills/workflows/` - Protokolle (Einzeldateien, ehem. _workflows)
- `system/skills/_templates/` - Standard-Templates
- `system/connectors/` - Externe Anbindungen (MCP, APIs)
- `system/partners/` - Multi-LLM-Konfigurationen

---

### (5) AUFGABENPLANUNG [B/C]

#### (5.1) User-Wuensche erkennen

- Erkenne konkrete im Prompt genannte Userwuensche als Aufgaben
- Lege Aufgaben fest und plane dein Vorgehen
- Wenn keine konkreten Wuensche vorliegen, gehe weiter zu 5.2

#### (5.2) Aufgabenkontext laden

```python
# API (bevorzugt)
from bach_api import task
task.list()
```

```bash
# CLI
bach help tasks
bach task list
```

- Suche dir selbststaendig Aufgaben aus und weise sie dir zu

---

### (6) PROZEDURALES WISSEN & PROTOKOLLE [C]

*Im Modus B optional -- Protokolle sind Dokumentation, kein Code.*

```bash
bach help protocol
bach help between-tasks
bach help practices
```

**Pfad:** `system/skills/workflows/`

---

## THEMEN-PAKETE (bei Bedarf lesen -- alle Modi)

### THEMA: Zusammenarbeit (PAKET: TEAMARBEIT)

*Wann lesen:* Du arbeitest mit Partnern im System.

```bash
bach help partners
bach help multi_llm
bach help delegate
```

**Chat-System:**

```python
# API
from bach_api import msg, partner
msg.send("gemini", "Bitte recherchiere...")
msg.unread()
partner.delegate("Recherche", "--to=gemini")
```

```bash
# CLI
bach msg send claude "Text"
bach msg unread
```

**Lock-System:**

```bash
bach llm lock <datei>           # Lock VOR Schreiben
bach llm unlock [datei]         # Lock freigeben
bach llm status                 # Wer hat welche Locks?
```

---

### THEMA: Problemlösung (PAKET: PROBLEMLÖSUNG)

*Wann lesen:* Du triffst auf Probleme oder Blockaden.

```bash
bach help operatoren
bach help planning
bach help problemloesung
bach help strategien
```

---

### THEMA: Coding-Aufgaben (PAKET: CODING)

*Wann lesen:* Du bearbeitest Code oder fixt Bugs.

```bash
bach help ati
bach help coding
bach help bugfix
```

---

### THEMA: Wartung (PAKET: WARTUNG)

*Wann lesen:* Du bearbeitest Wartungs-Aufgaben.

```bash
bach help maintain
bach help wartung
bach help recurring
bach daemon status
```

---

### THEMA: Dateiverwaltung (PAKET: DATEIVERWALTUNG)

*Wann lesen:* Du führst Dateioperationen durch.

```bash
bach help trash
bach help migrate
bach help distribution
```

---

### THEMA: Webseiten lesen (PAKET: WEB)

*Wann lesen:* Du musst Webseiten abrufen, Inhalte extrahieren oder Web-Analyse durchfuehren.

```bash
bach help web_parse
bach help web_scrape
```

**Zwei Handler fuer unterschiedliche Zwecke:**

| Handler | Befehl | Zweck | Technik |
|---------|--------|-------|---------|
| `web_parse` | `bach web-parse url/clean <url>` | **Content-Extraktion** (Hauptinhalt als Markdown) | trafilatura/html2text |
| `web_scrape` | `bach web-scrape get/links/forms/headers <url>` | **Struktur-Analyse** (Links, Formulare, Headers) | requests + Regex |

**Empfehlung:** Fuer Textinhalte `web-parse clean <url>` (entfernt Nav/Header/Footer). Fuer Rohdaten oder Link-Listen `web-scrape`. Beide nutzen HTTP-Requests -- JS-gerenderte Seiten liefern nur den Server-seitigen HTML-Anteil.

**Skill:** `skills/workflows/webseiten-lesen.md` -- Ausfuehrliches Verfahren mit Entscheidungsbaum.

---

### THEMA: Selbsterweiterung (PAKET: SELF-EXTENSION) [B/C]

*Wann lesen:* Dir fehlt eine Faehigkeit oder du willst BACH erweitern.

```bash
bach help self-extension
bach help hooks
bach help skills
```

**Neue Faehigkeiten erstellen (5 Typen):**

```bash
bach skills create voice-processor --type tool       # Neues Tool scaffolden
bach skills create email-agent --type agent           # Neuen Agent scaffolden
bach skills create tax-expert --type expert            # Neuen Experten scaffolden
bach skills create api-gateway --type handler          # Neuen CLI-Befehl scaffolden
bach skills create data-sync --type service            # Neuen Service scaffolden
```

**Nach Erstellung: Hot-Reload (kein Neustart!)**

```bash
bach skills reload
```

**Hook-Framework (14 Events):**

```python
from core.hooks import hooks

# Eigene Logik an System-Events haengen
hooks.on('after_task_create', meine_funktion, name='mein_plugin')
hooks.on('after_startup', startup_check, name='mein_plugin')

# Events anzeigen
# bach hooks events
```

**Plugin-API (Dynamische Erweiterung zur Laufzeit):**

```python
from bach_api import plugins

# Tool registrieren (sofort nutzbar)
plugins.register_tool("mein_tool", meine_funktion, "Beschreibung")

# Hook registrieren (Event abonnieren)
plugins.register_hook("after_task_done", callback, plugin="mein-plugin")

# Handler registrieren (neuer CLI-Befehl!)
plugins.register_handler("mein_cmd", MeinHandler)

# Plugin aus Manifest laden
plugins.load_plugin("plugins/mein-plugin/plugin.json")
```

```bash
# CLI: Plugin-Verwaltung
bach plugins list          # Geladene Plugins
bach plugins create name   # Plugin scaffolden
bach plugins load pfad     # Plugin laden
bach plugins unload name   # Plugin entladen
```

**Self-Extension Loop:**
1. ERKENNEN → Fehlende Faehigkeit identifizieren
2. ERSTELLEN → `bach skills create <name> --type <typ>` oder `plugins.register_tool()`
3. IMPLEMENTIEREN → Code schreiben
4. REGISTRIEREN → `bach skills reload` oder `plugins.load_plugin()`
5. NUTZEN → Sofort verfuegbar
6. REFLEKTIEREN → `bach lesson add "Was gelernt"`

---

### THEMA: Shutdown (PAKET: SHUTDOWN) [B/C]

*Wann lesen:* Die Sitzung wird beendet. Nur in Modus B und C relevant.

**Modus B (API -- empfohlen):**
```python
from bach_api import session, memory
memory.session("THEMA: Was gemacht. NAECHSTE: Was kommt.")
session.shutdown("Zusammenfassung", partner="claude")
# Oder schnell:
session.shutdown_quick("Kurze Notiz")
```

**Modus C (CLI):**
```bash
bach help shutdown
bach --memory session "THEMA: Was gemacht. NAECHSTE: Was kommt."
bach --shutdown
```

---

## HOOKS & INJEKTOREN

### Hook-Framework (Technisches Event-System)

Hooks erlauben es, eigene Logik an 14 Lifecycle-Events zu haengen -- ohne bestehenden Code zu aendern.

```python
from core.hooks import hooks

# Listener registrieren
hooks.on('after_task_done', auto_backup, name='backup_plugin')
hooks.on('after_startup', health_check, priority=10, name='health')

# CLI
# bach hooks status    → Zeigt alle Hooks
# bach hooks events    → Listet alle 14 Events
# bach hooks log       → Letzte Ausfuehrungen
```

**Events:** `before_startup`, `after_startup`, `before_shutdown`, `after_shutdown`, `before_command`, `after_command`, `after_task_create`, `after_task_done`, `after_task_delete`, `after_memory_write`, `after_lesson_add`, `after_skill_create`, `after_skill_reload`, `after_email_send`

> Hooks sind das **technische Framework**. Injektoren sind das **kognitive Subsystem**. Sie arbeiten unabhaengig voneinander.

---

### Injektoren (Kognitive Orchestrierung)

Die 6 Injektoren simulieren **Denken und Assoziationen** als **Zentrale Exekutive**. Verfuegbar ueber CLI und API.

| Injektor | Teilfunktionen | API-tauglich |
|----------|----------------|:---:|
| **strategy_injector** | Metakognition, Entscheidungshilfe, Fehleranalyse | Ja |
| **context_injector** | Tool-Empfehlung, Memory-Abruf, Anforderungsanalyse | Teilweise* |
| **between_injector** | Qualitaetskontrolle, Task-Uebergang, Ergebnis-Validierung | Ja |
| **time_injector** | Zeitgefuehl (Timebeat), Nachrichten-Check | Ja |
| **tool_injector** | Tool-Erinnerung, Duplikat-Warnung | Ja |
| **task_assigner** | Auto-Zuweisung, Task-Zerlegung | Ja |

*\*context_injector enthaelt CLI-Befehle als Hinweise. Im API-Modus filterbar.*

**CLI:**
```bash
bach --inject status            # Status aller Injektoren
bach --inject toggle <name>     # An/Aus schalten
```

**API:**
```python
from bach_api import injector

injector.process("text")              # Alle Injektoren auf Text anwenden
injector.check_between("task done")   # Quality-Check nach Task-Abschluss
injector.tool_reminder()              # Verfuegbare Tools (einmalig)
injector.assign_task()                # Naechste Aufgabe automatisch zuweisen
injector.time_check()                 # Uhrzeit + Nachrichten
injector.status()                     # Status aller Injektoren
injector.toggle("strategy_injector")  # Einzeln an/aus
injector.set_mode("api")              # CLI-Hinweise aus Kontext filtern
```

---

## CHANGELOG

### v3.8.0 (2026-03-12)

- **Handler-Discovery**: Neuer Abschnitt in Sektion (2) -- `bach help <suchbegriff>` als primaerer Discovery-Mechanismus fuer 109+ Handler dokumentiert
- **Such-Referenz**: `bach help list`, `bach tools search`, `bach skills search` als Sucheinstiege
- **Themenpaket WEB**: Neues Paket mit Verweis auf `web_parse` und `web_scrape` Handler
- **Skill `webseiten-lesen`**: Neuer Workflow-Skill mit Entscheidungsbaum fuer Web-Content-Extraktion
- **Dokumentation**: Handler sind jetzt im SKILL.md auffindbar statt nur ueber CLI

### v3.2.0-butternut (2026-02-28)

- **Agent-CLI**: `AgentLauncherHandler` -- `bach agent start/stop/list` fuer direkte Agent-Steuerung
- **Prompt-System**: `PromptHandler` -- `bach prompt list/add/edit/show/board-create` fuer zentrale Prompt-Verwaltung
- **SharedMemory-Erweiterungen**: `current-task`, `generate-context`, `conflict-resolution`, `decay`, `changes-since`
- **USMC Bridge**: United Shared Memory Client (`hub/_services/usmc_bridge.py`)
- **llmauto-Ketten**: Claude-Prompts als Chain-Steps + `bach://`-URL-Resolution
- **Scheduler**: `job_type='chain'` + Umbenennung `daemon_jobs` → `scheduler_jobs`
- **Neue API-Module**: `agent`, `prompt` in `bach_api`
- **Portierungen**: SharedMemoryHandler, ApiProberHandler, N8nManagerHandler, UserSyncHandler, Stigmergy-Service
- **Tabellen**: 4 neue DB-Tabellen: `prompt_templates`, `prompt_versions`, `prompt_boards`, `prompt_board_items`
- **109+ Handler** (bisher: 75+)

### v2.6.0 (2026-02-13)

- **Verzeichnis-Restrukturierung**: Klare Trennung von Agents, Skills, Connectors und Partners
  - `skills/_agents/` → `agents/` (Top-Level unter system/)
  - `skills/_experts/` → `agents/_experts/` (Experten gehoeren zu Agents)
  - `skills/_workflows/` → `skills/workflows/` (Workflows heissen jetzt Protocols)
  - `skills/_connectors/` → `connectors/` (Top-Level unter system/)
  - `skills/_partners/` → `partners/` (Top-Level unter system/)
- **PathHealer**: Automatische Pfad-Korrektur in allen betroffenen Dateien
- **Komponenten-Typ `protocol`**: Ersetzt `workflow` in der Typ-Hierarchie
- **Komponenten-Typ `connector`**: Neu fuer externe Anbindungen (MCP, APIs)
- **Architektur-Diagramm**: AGENTS LAYER und CONNECTORS & PARTNERS als eigene Sektionen
- **SKILL.md v2.6**: Alle Referenzen, Tabellen und Diagramme an neue Struktur angepasst

### v2.5.0 (2026-02-13)

- **Self-Extension System**: AI-Partner koennen sich neue Faehigkeiten geben
  - `bach skills create <name> --type <typ>` (5 Typen: tool, agent, expert, handler, service)
  - `bach skills reload` (Hot-Reload: Registry + Tools + Skills-DB)
  - Self-Extension Loop: ERKENNEN → ERSTELLEN → REGISTRIEREN → NUTZEN → REFLEKTIEREN
- **Hook-Framework**: Erweiterbares Event-System mit 14 Lifecycle-Events
  - `core/hooks.py` - HookRegistry-Singleton, Prioritaeten, Event-Log
  - `hub/hooks.py` - CLI: `bach hooks status/events/log/test`
  - Integration in: Startup, Shutdown, Task, Memory, Lesson, Skills, App
  - Hooks != Injektoren: Technisches Framework vs. kognitives Subsystem
- **Email-Handler**: Gmail API mit Draft-Safety (send, draft, confirm, cancel)
- **Registry Hot-Reload**: `app().reload_registry()` ohne Neustart
- **Regel (f) Self-Extension**: "Fehlt dir eine Faehigkeit, gib sie dir selbst!"
- **Dokumentation**: hooks.txt, self-extension.txt, cli.txt, skills.txt, ROADMAP.md

### v2.4.0 (2026-02-08)

- **MCP Server v2.2**: 23 Tools, 8 Resources, 3 Prompts - alle drei MCP-Primitives
- **Email-Adapter**: SMTP_SSL in notify.py (portiert aus BachForelle)
- **BachFliege + BachForelle**: Analysiert und archiviert (`docs/_archive/con5_BACHFLIEGE_BACHFORELLE_ARCHIV.md`)

### v2.3.0 (2026-02-06)

- **Regelwerk komplett ueberarbeitet**: IMMER → Zugriffsart → Modus-spezifisch
- **Drei Modi**: A (Bibliothek), B (Gemischt), C (Session) mit [B], [C], [B/C] Tags
- **Mitentwicklungs-Prinzip**: "BACH-Nutzung ist Mitentwicklung" als Kernregel
- **bach_api.py erweitert**: session, partner, logs, msg, tools, help, injector
- **14 API-Module**: Kompletter programmatischer Zugriff auf alle Handler
- **Injektoren ueber API**: Alle 6 Injektoren per Library nutzbar + CLI-Filter
- **Session-Lifecycle per API**: `session.startup()` / `session.shutdown()`
- Architektur-Diagramm aktualisiert (Core Layer + bach_api)
- Alle Sektionen mit Modus-Kennzeichnung versehen

### v2.2.0 (2026-02-06)

- Zwei Zugriffswege (CLI + Library-API) dokumentiert
- bach_api.py Basismodule: task, memory, backup, steuer, lesson, status

### v2.1.0 (2026-02-04)

- Skill-Architektur v2.0 integriert
- Versions-Check-Prinzip eingefuehrt
- Standard-Header dokumentiert
- Skill-Quellen-Klassifizierung hinzugefuegt
- Injektor-Teilfunktionen dokumentiert

### v2.0.2 (2026-01-01)

- Initiale Version

---

**BACH Skill-Architektur v2.0**
