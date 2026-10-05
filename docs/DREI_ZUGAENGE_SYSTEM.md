# Die drei Zugänge zum BACH-System

> Version: v2.0 • Stand: 2026-09-29 • Zuständig: BACH Core Team

Dieses Dokument beschreibt die drei offiziellen Zugänge, mit denen Nutzer, Agenten und externe Werkzeuge auf BACH zugreifen können. Jeder Zugang ist für einen anderen Kontext optimiert, nutzt aber dieselbe zentrale Handler-Registry und dieselbe SQLite-Datenbank.

---

## 1. Überblick: Die drei Zugänge

| Zugang | Einstieg | Zielgruppe | Besonderheit |
|--------|----------|------------|--------------|
| **A. Legacy CLI** | `python system/bach.py <befehl> [operation] [args]` | Menschlicher Nutzer, Scripts, Cron | Registry-basiert, Auto-Discovery, `--startup` |
| **B. `bach_api` Library** | `from bach_api import session, task, memory, tools` | Python-Code, Agenten, Tests | Drei Modi: Bibliothek, Gemischt, Session |
| **C. Claude Code / MCP** | `bach mcp serve` oder `~/.claude/claude_code_config.json` | Claude Code, andere MCP-Clients | 23 Tools, 8 Resources, 3 Prompts |

---

## 2. Gemeinsame Architektur

Alle drei Zugänge landen letztendlich bei denselben Komponenten:

- **Handler-Registry**: Dynamische Auflösung von Befehlen (keine statische Map mehr).
- **Core-App** (`core/app.py`): Verwaltet den Lebenszyklus und führt `app.execute(handler, operation, args)` aus.
- **Kanonische Datenbank**: `hub.bach_paths.BACH_DB` (nicht die alte Kopie in `system/data/bach.db`).
- **Skills/Tools**: Erweiterungen unter `system/skills/` und `system/tools/`.

```mermaid
flowchart TB
    subgraph Zugänge
        A1[Legacy CLI<br/>python bach.py ...]
        A2[bach_api Library<br/>from bach_api import task]
        A3[MCP Server<br/>bach mcp serve]
    end

    subgraph Kern
        B[Handler Registry]
        C[core/app.py<br/>App.execute]
        D[(kanonische BACH_DB)]
        E[Skills & Tools]
    end

    A1 -->|parse args| B
    A2 -->|_HandlerProxy / raw()| C
    A3 -->|bach_api Handler-Logik| C
    B --> C
    C --> D
    C --> E
```

---

## 3. Zugang A: Legacy CLI (`system/bach.py`)

### Start

```bash
python system/bach.py <befehl> [operation] [args]
python system/bach.py --<handler> [operation] [args]
python system/bach.py --startup
```

### Hauptmerkmale

- **Registry-basiert**: Befehle werden über Auto-Discovery aufgelöst, nicht über eine hartcodierte Map.
- **Legacy-Backup**: `system/bach_legacy.py` dient als Rückfall-Ebene.
- **Direct Execute**: Bekannte Befehle werden direkt an die Core-App weitergegeben.
- **Tool-Fallback**: Unbekannte Befehle können als Skill/Tool-Name aufgelöst werden.
- **Startup-Modus**: `python bach.py --startup` startet eine interaktive Session.
- **MCP-Subkommando**: `bach mcp serve` (bzw. `python bach.py mcp serve`) startet den MCP-Server.

### Beispiele

```bash
python bach.py task list
python bach.py task add "Neue Aufgabe" --priority P2
python bach.py memory write "Wichtige Erkenntnis"
python bach.py --startup
python bach.py mcp serve
```

---

## 4. Zugang B: `bach_api` Library (`system/bach_api.py`)

`bach_api` ist die programmatische Schnittstelle, die Python-Code, Agenten und Tests einen Zugriff ermöglicht, ohne die CLI zu durchlaufen.

### Drei Betriebsmodi

| Modus | Beschreibung | Beispiel |
|-------|--------------|----------|
| **1. Bibliothek-Modus** | Reine API-Aufrufe, kein Session-Management | `from bach_api import task; task.list()` |
| **2. Gemischter Modus** | API-Aufrufe innerhalb einer expliziten Session | `session.startup()` … `session.shutdown("Zusammenfassung")` |
| **3. Session-Modus** | Klassische CLI-Session | `python bach.py --startup` |

### Wichtige Konstrukte

- `get_app()`: Lazy-initialisierte `App`-Singleton-Instanz aus `core.app`.
- `_HandlerProxy(handler_name)`: Ermöglicht komfortable Aufrufe wie `task.add(...)`.
- `raw(operation, *args)`: Legacy-kompatibler Aufruf eines beliebigen Handlers.
- `app().execute(handler, operation, args)`: Direkter Zugriff auf alle 109+ Handler.

### Verfügbare Module (Auswahl)

```python
from bach_api import (
    session, task, memory, backup, steuer, lesson, status,
    agent, agents, prompt, partner, logs, msg, tools, help,
    update, theme, injector, db, app, tool_registry
)
```

### Beispiele

```python
from bach_api import session, task, memory, tools, injector, app

# Modus 2: Gemischte Session
session.startup(partner="claude", mode="silent")

ok, result = task.add("Dokumentation erweitern", "--priority", "P2")
ok, result = task.list()
ok, result = memory.write("Neue Erkenntnis aus #976")
ok, result = tools.search("ocr")

# Kognitive Injektoren
injector.process("ich bin blockiert")
injector.check_between("task done 42")
injector.set_mode("api")  # CLI-Hinweise filtern

# Raw-Zugriff auf beliebigen Handler
ok, result = app().execute("gesundheit", "termine", ["--upcoming"])

session.shutdown("Zusammenfassung der Arbeitssession")
```

---

## 5. Zugang C: Claude Code / MCP (`system/tools/mcp_server.py`)

Der MCP-Server (Model Context Protocol) macht BACH für Claude Code und andere MCP-Clients als externes Werkzeug verfügbar.

### Start

```bash
bach mcp serve
# oder
python system/bach.py mcp serve
```

### Konfiguration in Claude Code

```json
{
  "mcpServers": {
    "bach": {
      "command": "python",
      "args": ["C:/path/to/system/tools/mcp_server.py"]
    }
  }
}
```

### Exponierte Primitive

- **23 Tools**: Task-, Memory-, Lesson-, Backup-, Steuer-, Kontakt-, Kommunikations-, Session-, Partner- und System-Operationen.
- **8 Resources**: Schreibgeschützte Endpunkte für Tasks, Status, Memory, Skills, Kontakte und Version.
- **3 Prompts**: `daily_briefing`, `task_review`, `session_summary`.

### Tool-Gruppen

| Gruppe | Tools |
|--------|-------|
| Task | `task_create`, `task_done`, `task_search`, `task_list` |
| Memory | `memory_write`, `memory_search`, `memory_facts`, `memory_status`, `memory_note` |
| Lesson | `lesson_search` |
| Backup | `backup_create`, `backup_list` |
| Steuer | `steuer_status` |
| Kontakt | `contact_search` |
| Kommunikation | `msg_send`, `msg_unread`, `notify_send` |
| Session | `session_startup`, `session_shutdown` |
| Partner | `partner_list`, `partner_status` |
| System | `healthcheck`, `db_query` |

### Resources

```text
bach:/tasks/active      → Aktive Tasks
bach:/tasks/stats       → Task-Statistiken
bach:/status            → System-Status
bach:/memory/lessons    → Gelernte Lessons
bach:/memory/status     → Memory-Übersicht
bach:/skills/list       → Registrierte Skills
bach:/contacts          → Kontakte
bach:/version           → Server-Version und Capabilities
```

### Prompts

```text
daily_briefing    → Tägliches Briefing (Tasks, Nachrichten, Status)
task_review       → Task-Analyse und Priorisierung
session_summary   → Session-Zusammenfassung erstellen
```

---

## 6. Verbindungstabelle: Wer nutzt was?

| Anwendungsfall | Empfohlener Zugang | Begründung |
|----------------|--------------------|------------|
| Tägliche manuelle Bedienung | A – Legacy CLI | Schnell, terminalbasiert, `--startup` |
| Python-Script oder Test | B – `bach_api` | Typsicher, komponierbar, direkter App-Zugriff |
| Agenten-Integration (Claude Code) | C – MCP | Standardprotokoll, 23 Tools, Ressourcen, Prompts |
| Cronjob / Automatisierung | A oder B | CLI für Shell, API für Python |
| Datenanalyse / Power-User | C – `db_query` Tool | Whitelist-geschützte SELECT-Abfragen |
| Session mit Zusammenfassung | B – `session.startup/shutdown` | Expliziter Lebenszyklus, Memory-Eintrag |

---

## 7. ASCII-Architekturdiagramm

```text
┌─────────────────────────────────────────────────────────────────────┐
│                         BACH ZUGÄNGE                                │
├─────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────────┐  │
│  │  Legacy CLI  │   │  bach_api    │   │    Claude Code / MCP     │  │
│  │  bach.py     │   │  Library     │   │    mcp_server.py         │  │
│  │              │   │              │   │                          │  │
│  │  python      │   │  from        │   │  bach mcp serve          │  │
│  │  bach.py     │   │  bach_api    │   │                          │  │
│  │  <befehl>    │   │  import ...  │   │  23 Tools / 8 Resources  │  │
│  │  [operation] │   │              │   │  / 3 Prompts             │  │
│  │  [args]      │   │  session,    │   │                          │  │
│  │              │   │  task,       │   │  task_create             │  │
│  │  --startup   │   │  memory,     │   │  memory_write            │  │
│  │  mcp serve   │   │  tools,      │   │  healthcheck             │  │
│  │              │   │  injector    │   │  db_query                │  │
│  └──────┬───────┘   └──────┬───────┘   └────────────┬─────────────┘  │
│         │                  │                        │               │
│         │                  │   _HandlerProxy         │               │
│         │                  │   raw()                │               │
│         │                  │   app().execute()       │               │
│         │                  │                        │               │
│         └──────────────────┴────────────────────────┘               │
│                            │                                        │
│                   ┌────────┴────────┐                               │
│                   │  Handler Registry │  (Auto-Discovery)          │
│                   │  + core/app.py   │                               │
│                   │  App.execute()   │                               │
│                   └────────┬────────┘                               │
│                            │                                        │
│              ┌─────────────┴─────────────┐                          │
│              │                           │                          │
│     ┌────────▼────────┐      ┌──────────▼──────────┐              │
│     │  kanonische     │      │   Skills & Tools    │              │
│     │  BACH_DB        │      │   (system/skills,   │              │
│     │  (hub.bach_paths)│     │   system/tools)     │              │
│     └─────────────────┘      └─────────────────────┘              │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 8. FAQ

### Was ist der Unterschied zwischen `bach.py` und `bach_api`?

- `bach.py` ist die **menschenlesbare Kommandozeile**.
- `bach_api` ist die **programmatische Bibliothek** für Python-Agenten und Scripts.

### Kann ich `bach_api` ohne Session verwenden?

Ja. Im reinen Bibliotheksmodus rufst du einfach `task.list()` auf, ohne `session.startup()` zu verwenden.

### Woher weiß MCP, welche Befehle es gibt?

MCP greift nicht direkt auf die Datenbank zu, sondern nutzt die **Handler-Logik über `bach_api`**. Dadurch sind alle drei Zugänge konsistent.

### Ist `db_query` sicher?

Ja. `db_query` arbeitet mit einer Table-Whitelist (116 Tabellen) und ist auf SELECT beschränkt. Es ist ein Power-User-Escape-Hatch, kein alltägliches Werkzeug.

### Welche Datenbank ist die richtige?

**Immer** `hub.bach_paths.BACH_DB`. Die alte Kopie unter `system/data/bach.db` ist veraltet und darf nicht mehr verwendet werden.

### Kann ich mehrere Zugänge gleichzeitig nutzen?

Ja. Da alle Zugänge auf dieselbe Core-App und dieselbe Datenbank zugreifen, können CLI, API und MCP parallel genutzt werden.

---

## 9. Änderungshistorie

| Version | Datum | Änderung |
|---------|-------|----------|
| v1.0.0 | — | Ursprüngliche Dokumentation aus Backups nicht mehr rekonstruierbar |
| v2.0.0 | 2026-09-29 | Neuaufbau aus `bach.py`, `bach_api.py` und `mcp_server.py`; Mermaid- und ASCII-Diagramme hinzugefügt |

---

## 10. Verwandte Dateien

- `system/bach.py`
- `system/bach_api.py`
- `system/bach_legacy.py`
- `system/tools/mcp_server.py`
- `system/core/app.py`
- `system/hub/bach_paths.py`
