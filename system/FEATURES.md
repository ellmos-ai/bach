# Feature-Analyse: BACH v3.12.3-coffee

## Projektuebersicht

**Projektname:** BACH
**Version:** 3.12.3-coffee
**Status:** Production-Ready
**Typ:** Textbasiertes Betriebssystem fuer LLMs

BACH ist ein textbasiertes Betriebssystem, das Large Language Models (LLMs) befaehigt, eigenstaendig zu arbeiten, zu lernen und sich zu organisieren. Es fungiert als Middleware zwischen Mensch und KI und bietet eine vollstaendige Infrastruktur fuer Task-Management, Wissensmanagement, Automatisierung und Multi-Agent-Orchestrierung -- lokal, portabel und datenbankseitig auf SQLite basierend.

---

## Kernfeatures

### 1. Kognitives Memory-Modell (5 Typen)

- **Working Memory:** Kurzzeit/Session-Notizen (`bach mem write`)
- **Episodic Memory:** Abgeschlossene Sessions, Tagebuch (`bach --memory session`)
- **Semantic Memory:** Fakten, Wiki, Help-Inhalte (`bach --memory fact`)
- **Procedural Memory:** Tools, Skills, Workflows (`bach help tools`)
- **Associative Memory:** Konsolidierung, Trigger (`bach consolidate`)

### 2. Multi-Agent Orchestrierung

- Netzwerk von Partner-Modellen (Claude, Gemini, Ollama)
- Chat-System fuer Multi-LLM-Kommunikation
- Lock-System fuer Datei-Koordination (Datei- und Ordner-Locks)
- Partner-Awareness mit Stempelkarten-System (Clock-In/Clock-Out)
- SharedMemory-Bus mit Konflikt-Erkennung und Relevanz-Decay
- USMC Bridge fuer Cross-Instanz-Kommunikation (local/tcp/file)
- Schwarm-LLM mit parallelen Workern (ThreadPoolExecutor)

### 3. Drei Zugriffsmodi (CLI + API + MCP)

- **CLI/Terminal:** `python bach.py` -- Hauptschnittstelle fuer Menschen
- **Library-API:** `from bach_api import task, memory` -- Programmatischer Zugriff fuer LLMs
- **MCP-Server:** 23 MCP-Tools fuer IDE-Integration (Claude Code, Cursor)
- **GUI/Browser:** FastAPI-basiertes Web-Dashboard (`server.py`)

### 4. Self-Extension und Self-Healing

- Self-Extension: `bach skills create <name> --type <typ>` (6 Typen)
- Hot-Reload: `bach skills reload` ohne Neustart
- Plugin-API: Dynamische Erweiterung zur Laufzeit
- Automatische Pfad-Korrektur und Verzeichnis-Heilung
- Identity Seal und Integritaetspruefung

### 5. Execution Stack (3-Schichten-Modell)

- **Schicht 1 -- Zeitsteuerung:** SchedulerService mit Cron-basierter Job-Ausfuehrung
- **Schicht 2 -- Orchestrierung:** ChainHandler + llmauto-Ketten mit `bach://` URL-Resolution
- **Schicht 3 -- Ausfuehrung:** AgentLauncherHandler startet Claude/Gemini/Ollama-Sessions

### 6. Portable Agent Framework

- PortableAgent-Basisklasse: Agenten funktionieren standalone ohne BACH
- Arbeitsmodi: focused, assistant, autonomous
- 24h-Agent mit Session-Kontext-Persistenz und Tageswechsel-Logik

### 7. Wiki-in-Database mit FTS5

- 263 Wiki-Artikel als BLOBs in bach.db
- FTS5-Volltextsuche mit Snippets
- Aenderungsverfolgung via `bach_blob_history`
- Dateisystem als Fallback

---

## Architektur

### Schichtenmodell

```
USER INTERFACES
  +-- CLI/Terminal (bach.py)
  +-- Lib-API (bach_api.py -- 14+ Module)
  +-- GUI/Browser (server.py)
  +-- MCP/IDE (mcp_server.py -- 23 Tools)
       |
CORE LAYER (core/*.py)
  app.py -> registry.py -> Auto-Discovery von 109+ Handlern
  base.py (BaseHandler) | db.py (Schema-First) | hooks.py (14 Events)
       |
HUB LAYER (hub/*.py -- 109+ Handler-Module)
  System: startup, shutdown, status, backup, tokens, inject, hooks, setup
  Domain: steuer, abo, haushalt, gesundheit, contact, calendar, email
  Data: task, memory, db, session, logs, wiki, docs, inbox, prompt
  Multi-AI: agents, partner, scheduler, ollama, ati, chain, shared-memory
  Extension: skills (create/reload), hooks (status/events/log/test)
       |
  +----+----+                       +----+----+
  |         |                       |         |
  v         v                       v         v
AGENTS    SKILLS & TOOLS          CONNECTORS  DATA LAYER
agents/   skills/workflows/       connectors/ bach.db (138 Tabellen)
  _experts/ skills/_templates/    partners/   Dateisystem
            hub/_services/                    inbox/outbox/
            tools/*.py
       |
SELF-EXTENSION LAYER
  skills create (6 Typen)
  skills reload (Hot-Reload)
  hooks.on/emit (14 Events)
  Plugin-API
```

### Verzeichnisstruktur

```
BACH_ROOT/
+-- system/
|   +-- bach.py           (CLI Entry Point)
|   +-- bach_api.py       (Library-API)
|   +-- core/             (Registry, BaseHandler, Hooks, DB)
|   +-- hub/              (109+ Handler-Module)
|   +-- hub/_services/    (Services -- je eigener Ordner)
|   +-- agents/           (Boss-Agenten -- je eigener Ordner)
|   +-- agents/_experts/  (Domain-Experten -- je eigener Ordner)
|   +-- skills/           (Workflows, Templates, Tools)
|   +-- connectors/       (MCP, APIs, Bridges)
|   +-- partners/         (Multi-LLM-Konfigurationen)
|   +-- gui/              (FastAPI Dashboard)
|   +-- data/             (bach.db, Logs, Configs)
|   +-- tools/            (MCP-Server, Migrations-Tools)
+-- docs/                 (Dokumentation)
+-- user/                 (User-Daten, isoliert)
+-- extensions/           (Third-Party Tools)
```

---

## Datenbank-Schema (138 Tabellen)

**Datenbank:** `bach.db` (SQLite mit FTS5-Erweiterung)

| # | Bereich | Wichtigste Tabellen | Anzahl |
|---|---------|---------------------|--------|
| 1 | System | `system_identity`, `system_config`, `instance_identity` | ~5 |
| 2 | Tasks | `tasks` | 1 |
| 3 | Memory | `memory_working`, `memory_facts`, `memory_lessons`, `memory_sessions` | ~8 |
| 4 | Shared Memory | `shared_memory_facts`, `shared_memory_lessons`, `shared_memory_sessions`, `shared_memory_working`, `shared_memory_consolidation`, `shared_context_triggers` | 6 |
| 5 | Tools | `tools` (373 Eintraege) | 1 |
| 6 | Skills | `skills` (932 Eintraege) | 1 |
| 7 | Agents | `bach_agents`, `bach_experts`, `agent_synergies` | ~4 |
| 8 | Files | `files_truth`, `files_trash`, `dist_files` | ~5 |
| 9 | Automation | `automation_triggers`, `automation_routines`, `automation_injectors`, `scheduler_jobs`, `scheduler_runs` | ~8 |
| 10 | Monitoring | `monitor_tokens`, `monitor_success`, `monitor_processes`, `monitor_pricing` | ~6 |
| 11 | Connections | `connections`, `connector_messages`, `partner_presence` | ~5 |
| 12 | Languages | `languages_config`, `languages_translations` | 2 |
| 13 | Distribution | `distribution_manifest`, `dist_type_defaults`, `releases`, `snapshots` | ~6 |
| 14 | Wiki / Blobs | `wiki`, `bach_blobs`, `bach_blobs_fts`, `bach_blob_history` | ~4 |
| 15 | Usecases | `usecases`, `toolchains` | ~3 |
| 16 | Prompts | `prompt_templates`, `prompt_versions`, `prompt_boards`, `prompt_board_items` | 4 |
| 17 | Session-Kontext | `session_context`, `reminders`, `meta_feedback_patterns` | 3 |

Schema-Quelle: `system/data/schema/schema.sql` + 32 Migrationen (`.sql` und `.py`)

---

## Handler-Module (109+ Handler)

Alle Handler werden per Auto-Discovery ueber `core/registry.py` erkannt. Jeder Handler erbt von `BaseHandler`, definiert einen `profile_name` und implementiert `handle(operation, args)`. Neue Handler brauchen nur eine `.py`-Datei in `hub/` -- kein manuelles Mapping noetig.

### System-Handler

| Handler | Befehl | Funktion |
|---------|--------|----------|
| StartupHandler | `--startup` | Session-Start, Partner-Clock-In, Nachrichten-Injektion |
| ShutdownHandler | `--shutdown` | Session-Ende, Partner-Clock-Out, Memory-Konsolidierung |
| StatusHandler | `--status` | Systemstatus, Health-Check |
| BackupHandler | `bach backup` | Datenbank-Backup und -Restore |
| TokensHandler | `bach tokens` | Token-Verbrauch, Emergency-Shutdown bei 95%+ |
| SetupHandler | `bach setup` | MCP-Installation, Abhaengigkeiten-Check, Secrets-Sync |
| HooksHandler | `bach hooks` | Hook-Events verwalten, testen, loggen |
| InjectHandler | `--inject` | Injektor-Status und -Steuerung |

### Domain-Handler

| Handler | Befehl | Funktion |
|---------|--------|----------|
| SteuerHandler | `bach steuer` | Steuererklarung, OCR-Scanning, ELSTER-Export, DATEV-CSV |
| AboHandler | `bach abo` | Abonnement-Verwaltung |
| HaushaltHandler | `bach haushalt` | Inventar, Einkaufslisten, Budget |
| GesundheitHandler | `bach gesundheit` | Health-Data Import, Medikamenten-Tracking |
| ContactHandler | `bach contact` | Kontaktverwaltung |
| CalendarHandler | `bach calendar` | Kalender-Integration |
| EmailHandler | `bach email` | Gmail API, Draft-Safety (send, draft, confirm) |
| NotifyHandler | `bach notify` | Benachrichtigungen (SMTP, Push) |
| DocHandler | `bach doc` | Dokumenten-Verwaltung |

### Daten-Handler

| Handler | Befehl | Funktion |
|---------|--------|----------|
| TaskHandler | `bach task` | GTD-System mit Prioritaeten, Deadlines, Tags |
| MemoryHandler | `bach mem` | 5-Typen-Memory mit Relevanz-Scoring |
| LessonHandler | `bach lesson` | Lessons Learned, Deaktivierung, Audit |
| SessionHandler | `bach session` | Session-Tracking |
| LogsHandler | `bach logs` | Log-Verwaltung |
| WikiHandler | `bach wiki` | FTS5-Volltextsuche, DB-Lookup, Dateisystem-Fallback |
| HelpHandler | `bach help` | 93+ Help-Dateien, kontextbezogene Hilfe |
| InboxHandler | `bach inbox` | Dokumenten-Scanner mit OCR und Auto-Sortierung |
| PromptHandler | `bach prompt` | Prompt-Templates, Boards, Versionierung |
| DbHandler | `bach db` | Direkte DB-Abfragen (mit Table-Whitelist) |

### Multi-AI Handler

| Handler | Befehl | Funktion |
|---------|--------|----------|
| AgentLauncherHandler | `bach agent` | Agenten starten, stoppen, auflisten |
| PartnerHandler | `bach partner` | Multi-LLM-Koordination, Delegation |
| SchedulerHandler | `bach scheduler` | Cron-basierte Jobs (tool, chain, agent) |
| OllamaHandler | `bach ollama` | Lokale LLM-Integration, Offline-Fallback |
| AtiHandler | `bach ati` | Software-Entwicklung, Project Bootstrapper |
| ChainHandler | `bach chain` | Toolchains + llmauto-Ketten, bach://-URLs |
| SharedMemoryHandler | `bach shared-mem` | Cross-Agent-Koordination, Decay, Konflikte |
| ConnectorHandler | `bach connector` | Externe Bridges (Telegram, Discord, Email) |
| MessagesHandler | `bach msg` | Nachrichtensystem mit Queue, Retry, Dead-Letter |

### Extension-Handler

| Handler | Befehl | Funktion |
|---------|--------|----------|
| SkillsHandler | `bach skills` | Create, Reload, Version-Check |
| SyncHandler | `bach sync` | Skills/Tools DB-Synchronisation |
| SnapshotHandler | `bach snapshot` | System-Snapshots |
| ApiProberHandler | `bach api-probe` | HTTP-Endpoint-Tests |
| N8nManagerHandler | `bach n8n` | n8n-Workflow-Verwaltung via REST |
| UserSyncHandler | `bach user-sync` | User-Profile zwischen Instanzen synchronisieren |
| MaintenanceHandler | `bach --maintain` | Dokumenten-Checker, Registry-Watcher |

---

## Skills & Tools

### Zahlen

| Kategorie | Anzahl | Speicherort |
|-----------|--------|-------------|
| Skills (gesamt) | 932+ | `skills`-Tabelle in bach.db |
| Tools | 373+ | `tools`-Tabelle in bach.db |
| Protokoll-Workflows | 54 | `skills/workflows/` |
| Wiki-Artikel | 263 | `bach_blobs`-Tabelle (FTS5) |
| Help-Dateien | 93+ | `skills/docs/help/` |

### Komponenten-Typen

| Typ | Ordner | Charakteristik |
|-----|--------|----------------|
| Agent | `agents/<name>/` | Orchestriert Experten, eigener Ordner, standalone-faehig |
| Expert | `agents/_experts/<name>/` | Tiefes Domaenenwissen, eigener Ordner |
| Service | `hub/_services/<name>/` | Allgemein, Handler-nah, eigener Ordner |
| Protocol | `skills/workflows/` | 1 Datei = 1 Protokoll, Kategorie-Unterordner erlaubt |
| Connector | `connectors/` | Externe Anbindungen (MCP, APIs) |
| Tool (allg.) | `tools/` | Wiederverwendbare Python-Scripts |
| Tool (spez.) | Im Skill-Ordner | Nur fuer diesen Skill |

### Agenten

| Agent | Fokus |
|-------|-------|
| ATI | Software-Entwicklung, Task Scanner, Project Bootstrapper |
| Persoenlicher-Assistent | Briefings, Kalender, Tagesplanung |
| Buero-Assistent | Dokumente, Mails, Organisation |
| Entwickler-Agent | GitHub, Code-Review, 6-Phasen-Architektur |
| Gesundheits-Assistent | Health-Data Import, Reports |
| Versicherungen | Vertraege, Claims |
| Production | Media/Studio |
| Research-Agent | PubMed-API, Perplexity, Recherche |
| Plan-Agent | Strukturierte Planungsprotokolle mit JSON-Schema |

### Experten (18+)

Steuer, Aboservice, Foerderplaner, Haushaltsmanagement, Gesundheitsverwalter, Psycho-Berater, Report-Generator, PMR/Autogenes Training, Psychoedukation, Positive Psychologie und weitere.

---

## Automation

### 6 Kognitive Injektoren

Die Injektoren simulieren Denken und Assoziationen als Zentrale Exekutive. Alle sind ueber CLI (`bach --inject`) und API (`from bach_api import injector`) steuerbar.

| Injektor | Funktion |
|----------|----------|
| strategy_injector | Metakognition, Entscheidungshilfe, Fehleranalyse |
| context_injector | Tool-Empfehlung, Memory-Abruf, Anforderungsanalyse |
| between_injector | Qualitaetskontrolle, Task-Uebergaenge, Ergebnis-Validierung |
| time_injector | Zeitgefuehl (Timebeat), Nachrichten-Check |
| tool_injector | Tool-Erinnerung, Duplikat-Warnung |
| task_assigner | Auto-Zuweisung, Task-Zerlegung |

Zusaetzlich seit v3.4.0:
- **Reminder-Injektor:** LLM-Selbsterinnerung vor jedem Call (DB + JSON-Fallback)
- **Meta-Feedback-Injektor:** Auto-Korrektur wiederkehrender LLM-Ticks mit Pattern-DB

### 14 Hook-Events

Das Hook-Framework erlaubt es, eigene Logik an Lifecycle-Events zu haengen -- ohne bestehenden Code zu aendern.

Events: `before_startup`, `after_startup`, `before_shutdown`, `after_shutdown`, `before_command`, `after_command`, `after_task_create`, `after_task_done`, `after_task_delete`, `after_memory_write`, `after_lesson_add`, `after_skill_create`, `after_skill_reload`, `after_email_send`

### SchedulerService

- Cron-basierte Job-Ausfuehrung (`0 8 * * *`, `@hourly`, etc.)
- Job-Typen: `tool`, `chain`, `agent`
- Tracking: last_run, next_run, run_count, error_count
- Integration mit ChainHandler und AgentLauncherHandler

### Connector-Queue

- Retry/Backoff: 5 Versuche, exponentieller Backoff (30s-480s)
- Dead-Letter-Queue mit manuellem Recovery
- Circuit Breaker: 5 Fehler -> 5 Min Sperre, Auto-Reset

---

## Externe Integrationen

### MCP-Server (23 Tools)

- 23 Tools via Handler-Logik (task, memory, lesson, backup, steuer, contact, msg, etc.)
- 8 Resources (tasks/active, status, memory/lessons, skills/list, etc.)
- 3 MCP-Prompts (daily_briefing, task_review, session_summary)
- db_query mit Table-Whitelist (110 erlaubte Tabellen)

### Connectors & Bridges

| Connector | Status | Funktion |
|-----------|--------|----------|
| Telegram | Aktiv | Bot mit Owner-Filter, Polling, Threaded |
| Discord | Aktiv | Incremental Polling, Bot-Filter |
| Email (SMTP) | Aktiv | Gmail App-Password, Self-Notification |
| USMC Bridge | Aktiv | Cross-Instanz-Kommunikation (local/tcp/file) |
| Bridge Server | Aktiv | FastAPI REST-API (POST /api/message, GET /api/status) |
| Stigmergy | Aktiv | Pheromon-basiertes Signal-Routing fuer Agenten |
| n8n | Aktiv | Workflow-Verwaltung via REST-API |

### Externe APIs

- Claude API (Anthropic) -- Haupt-LLM
- Gemini API (Google) -- Partner-LLM
- Ollama -- Lokale Modelle, Offline-Fallback
- PubMed API (NCBI E-Utilities) -- Research-Agent
- Perplexity API (optional) -- Research-Agent
- Tesseract OCR -- Dokumenten-Scanning
- ELSTER -- Deutsche Steuerverwaltung

---

## Technologie-Stack

| Komponente | Technologie |
|------------|-------------|
| Programmiersprache | Python 3.10+ (100%) |
| Datenbank | SQLite3 mit FTS5-Erweiterung |
| Web-Framework | FastAPI + Uvicorn (ASGI) |
| GUI-Framework | PySide6 (geplant) |
| Datenvalidierung | Pydantic |
| LLM-SDK | Anthropic SDK (Claude), Google GenAI (Gemini) |
| MCP | ellmos-codecommander-mcp, ellmos-filecommander-mcp (npm) |
| Pfad-Verwaltung | Pathlib (Cross-Platform), bach_paths.py (Self-Healing) |
| Parallelisierung | ThreadPoolExecutor (Schwarm-LLM) |
| OCR | pytesseract + pdf2image |

---

## Zusammenfassung

BACH v3.12.3-coffee ist ein vollstaendiges textbasiertes Betriebssystem fuer KI-Agenten mit folgenden Kennzahlen:

| Metrik | Wert |
|--------|------|
| Tabellen in bach.db | 145+ |
| Handler-Module | 109+ |
| Tools | 373+ |
| Skills | 932+ |
| Tests | 3241 |
| Protokoll-Workflows | 54 |
| Kognitive Injektoren | 8 |
| Hook-Events | 14 |
| MCP-Tools | 23 |
| Wiki-Artikel | 263 |
| Help-Dateien | 93+ |
| Uebersetzungen (i18n) | 14.655 |
| Schema-Migrationen | 35+ |
| Zugriffsmodi | 4 (CLI, API, GUI, MCP) |
| Partner-LLMs | 5 (Claude, Gemini, Ollama, Codex, OpenAI) |

**Kernprinzipien:** Database-First, Handler-First, Self-Healing, Self-Extension, Portable, Multi-Agent-faehig, 100% lokal.

### Seit v3.6 hinzugekommen

- **ProSync** (v3.9): Cross-System DB-Sync ueber OneDrive-Transit, 137 syncbare Tabellen
- **Buddha Chat Services** (v3.9): Multi-Backend Telegram-Bot mit 13 BACH-Tools, Control API, System Tray
- **Schwarm-System** (v3.8): 4 Muster (Parallel, Hierarchie, Stigmergy, Konsensus), CLI-Integration
- **Permission-Profile** (v3.8): Claude Code Remote Control mit Profil-Switching
- **Foerderbericht-Pipeline** (v3.9): DSGVO-konforme Anonymisierung, ICF-Prompt-Generierung
- **Agent-Personas** (v3.9): Multi-Strategie Namensaufloesung, Display-Names, 20 Default-Personas
- **Security Gate** (v3.9): Code-Injection-Scan bei Plugin/Skill-Installation, Quarantaene
- **Cross-Platform** (v3.11): Linux-Support verifiziert, bash.sh Launcher, plattformbedingte Subprozesse
- **Encoding-Haertung** (v3.12): UTF-8 Safety fuer alle subprocess-Aufrufe auf Windows

---

*Erstellt: 2026-02-05*
*Aktualisiert: 2026-05-17*
*System: BACH Feature-Analyse v3.12.3-coffee*
