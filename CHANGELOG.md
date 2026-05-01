# BACH Changelog

Alle wichtigen Aenderungen an BACH werden hier dokumentiert.

Copyright (c) 2026 BACH Contributors. Alle Rechte vorbehalten.

---

## [Unreleased]

### Neu

- **Schwarm-Muster komplett** (SQ016): Alle 5 Muster aktiv
  - Hierarchie-Muster (`tools/schwarm/hierarchy.py`): Boss-Worker-Aggregator
  - Stigmergy-Muster (`tools/schwarm/stigmergy_pattern.py`): Pheromon-Koordination
  - Spezialist-Muster (`tools/schwarm/specialist.py`): Auto-Routing an Boss-Agenten
  - 3 neue CLI-Operationen: `bach schwarm hierarchy/stigmergy/specialist`
- **5 neue Therapie-Skills** (B30/SQ046 Phase 2):
  - ACT-Techniken (Hexaflex, Defusion, Akzeptanz)
  - DBT-Fertigkeiten (TIPP, DEAR MAN, 4 Module)
  - Stabilisierungstechniken (5-4-3-2-1 Grounding, Box-Breathing)
  - Trauma-Psychoedukation (Window of Tolerance, nur Aufklaerung)
  - Expositionsbegleitung (SUDs-Skala, nur Planung)

- **Agent-Personas & Name-Resolution** (Migration 034):
  - `resolve_agent_name()`: Multi-Strategie Namensaufloesung (Name, Display-Name, Beschreibung, Persona, Fuzzy/Levenshtein)
  - `bach agent rename <name> <neuer-name>`: Benutzer-definierbare Display-Names
  - Persona-Injection: Charakter-Beschreibung wird beim Agent-Start in CLAUDE.md injiziert
  - Agent-Start/Stop akzeptiert Display-Names, Rollen und Beschreibungen
  - 20 Default-Personas: 5 Boss-Agenten (Atlas, Clara, Felix, Helena, Paul) + 15 Experten
  - Listing zeigt Display-Names in Klammern an
- **Security Gate für Erweiterungen:** `plugins load` und `skills install` scannen Importpakete jetzt vor dem Laden auf offensichtliche Code-Injection-Muster und blockieren verdächtige Pakete fail-closed.
- **MCP-Setup-Härtung:** `bach setup mcp` und `bach setup n8n` validieren Paketnamen und Claude-Code-MCP-Configs jetzt gegen eine explizite Allowlist, bevor npm oder die lokale MCP-Konfiguration berührt werden.
- **API-Surface-Parität:** `bach_api` exportiert jetzt die dokumentierten Module `agent`, `agents` und `prompt` für Agenten- und Prompt-Usecases ohne Raw-Handler-Zugriff.
- **Quarantäne für blockierte Erweiterungen:** Blockierte `plugins load`-, `skills install`- und lokale MCP-Config-Pfade werden jetzt nicht nur abgewiesen, sondern unter `system/data/quarantine/` mit Payload-Kopie und `report.json` dokumentiert.
- **Manifest-first Plugin-Prüfung:** `bach plugins inspect <pfad>` zeigt Plugin-Metadaten ohne Runtime-Import; `plugins load` blockiert Manifeste mit fehlenden Hook-/Handler-/Workflow-Dateireferenzen, bevor Plugin-Code geladen wird.

### Bugfix

- **Self-Heal CLI/API:** `bach mem write/read/...` delegiert jetzt auf den bestehenden `memory`-Handler; `bach wiki read <thema>` ist als Alias verfuegbar; `bach task add` gibt die neue Task-ID direkt aus.
- **agent_launcher.py:** Windows cp1252 Encoding-Fix bei tasklist-Subprocess (0x81 Umlaut-Crash)
- **bach_api.py:** Import-Lücke geschlossen, durch die `from bach_api import agent` trotz dokumentierter API fehlschlug.

### Dokumentation

- **OpenClaw-Abgleich 2026-05-01:** README und ROADMAP aktualisiert; latest stable `2026.4.29`, pre-release `2026.4.29-beta.4`. Relevante Impulse: active-run steering, visible-reply enforcement, subagent routing metadata, people-aware Memory/Wiki-Provenance, OpenGrep-Scanning, stale-session recovery und version-scoped update caches.
- **README-Version bereinigt:** Footer auf `v3.8.0-sugar-of-babel` angeglichen.

---

## [3.8.0-sugar] - 2026-03-08

### Neu

- **ClaudePermissionsHandler** (`hub/claude_permissions.py`): Permission-Profile fuer Claude Code
  - Befehl: `bach permissions`
  - Zwei Default-Profile: `normal` (Standard) und `remote_control` (alle Tools freigeschaltet)
  - Profile in BACH-DB gespeichert (system_config, Kategorie: claude_permissions)
  - Automatischer Backup/Restore von ~/.claude/settings.json bei Profil-Wechsel
  - 10 Operationen: list, show, set, remove, activate, deactivate, sync, reset, status, init
- **Remote Control Starter** (`start/_internal/claude_remote_control.py`)
  - Aktiviert Remote-Control-Profil, startet Claude Code, stellt Normal-Profil wieder her
  - atexit-Handler als Fallback bei Ctrl+C
  - Desktop-Shortcut: `Claude_RemoteControl.bat`
  - BACH Boot Menu: Taste [P] unter CLAUDE SPEZIAL
- **Schwarm-Handler** (`hub/schwarm.py`): CLI-Integration fuer Schwarm-Operationen (SQ016)
  - Befehl: `bach schwarm`
  - Operationen: list, run, translate, summarize, benchmark, status
  - 4 Schwarm-Muster: Epstein (Parallel), Hierarchie (Boss+Worker), Stigmergy (Pheromon), Konsensus (Mehrheit)
  - Automatisches Muster-Routing via Entscheidungsbaum
- **Konsensus-Schwarm** (`tools/schwarm/consensus.py`): Muster 4 -- Mehrheitsentscheid
  - Mehrere LLM-Runs beantworten dieselbe Frage, Konsens wird ermittelt
  - Konfigurierbar: Anzahl Voter, Modell, Similarity-Threshold
- **Kosten-Tracking**: Token-Zaehler pro Schwarm-Run in DB (`schwarm_runs` Tabelle)
- **Schwarm-Tools portiert** aus BACH_Dev nach system/tools/schwarm/:
  - translate_swarm.py, summarize_chunks.py, runner.py, benchmark.py
- **5 neue Therapie-Skills** (B30/SQ046 Phase 1):
  - Systemische Fragetechniken (Zirkulaere Fragen, Skalierung, Wunderfrage)
  - Problemloese-Training (6-Schritte-Modell)
  - Gewaltfreie Kommunikation (GFK nach Rosenberg, 4 Schritte)
  - Motivierende Gespraechsfuehrung (OARS-Techniken, Prochaska)
  - Verhaltensaktivierung (Aktivitaetenplanung, Stimmungs-Tagebuch)

### Schema

- **Migration 033:** `schwarm_runs` Tabelle fuer Schwarm-Kosten-Tracking (pattern, tokens, cost, duration)

### Dokumentation

- **schwarm.txt:** Neue Help-Datei fuer Schwarm-CLI und Muster-Uebersicht
- **permissions.txt:** Neue Help-Datei fuer Permission-Profile und Remote Control Workflow
- **claude-code.txt:** BACH Permission-Profile Verweis ergaenzt
- **claude-code-automatisierung.txt:** Abschnitt 11 "Remote Control" hinzugefuegt
- **settings.txt:** Verweis auf claude_permissions Kategorie und permissions.txt
- **Version Bump:** Alle Root-Dokumente auf v3.8.0-sugar aktualisiert

---

## [3.6.0-spaghetti] - 2026-03-04

### Qualitaetssicherung

- **Help-Expert-Review:** 192+ Help-Dateien validiert, 6 Strukturfixes, 64 neue Help-Dateien per Haiku-Schwarm generiert
- **Root-Docs-Review:** Zwei-Experten-Pipeline (Leser + Fixer), 31 Issues gefunden, 25 korrigiert, 10 Dateien angepasst
- **docs/README.md:** Zentrale Doku-Referenz erstellt (~110 Handler + ~80 Tools)
- **exports.txt:** Neue Help-Datei fuer DB-Export-Scripts
- **FEATURES.md Rewrite:** Komplett neu geschrieben (v2.1.0 → v3.6.0), korrekte Zahlen (138 Tabellen, 109+ Handler, 373+ Tools, 932+ Skills)
- **Kataloge regeneriert:** AGENTS.md, CHAINS.md, PARTNERS.md, WORKFLOWS.md, USECASES.md via Export-Scripts

### Neu

- **Drei-Ausbaustufen-Dokumentation (E02):** USMC → Rinnsal → BACH als aufeinander aufbauende Stufen
  - README.md: Neue Sektion "Ausbaustufen" mit Tabelle und Links
  - SKILL.md: Verweis auf Ausbaustufen in der Architektur-Sektion
  - Landingpage (index.html): Drei-Stufen-Badge-Cards mit GitHub-Links
- **version_bump.py:** Automatisches Version-Bump-Tool fuer Releases (10 Ersetzungen in 6 Dateien)
- **Englisch-Uebersetzung (E03, 1. Durchlauf):** German Scanner auf Hub-Layer ausgefuehrt, 300+ deutsche Strings identifiziert

### Dokumentation

- **NEXT_RELEASE.md:** Marketing-Sektion nach THE_RELEASE_AFTER.md verschoben
- **Version Bump:** Alle Root-Dokumente auf v3.6.0-spaghetti aktualisiert (README, QUICKSTART, SKILL, BACH_USER_MANUAL, ARCHITECTURE, features.txt)

---

## [3.5.0-milk] - 2026-03-04

### Neu

- **Wiki-in-Database mit FTS5 (SQ044):** 263 Wiki-Artikel als BLOBs in bach.db mit FTS5-Volltext-Suche
  - `bach_blobs` Tabelle mit Checksummen, Kategorien, Metadaten
  - `bach_blobs_fts` Virtual Table fuer schnelle Volltextsuche mit Snippets
  - `bach_blob_history` fuer Aenderungsverfolgung
  - Wiki-Handler nutzt FTS5 fuer Suche, DB-Lookup fuer Artikel-Anzeige, Dateisystem als Fallback
- **Therapie-Skills (B30/SQ046):** 3 neue Skills + 8 Wiki-Artikel + Ethik-Policy
  - Skills: PMR/Autogenes Training, Psychoedukation, Positive Psychologie
  - Wiki: Verhaltenstherapie, Tiefenpsychologie, Analytische Psychotherapie, Systemische Therapie, EMDR, Schematherapie, DBT, ACT
  - ETHICS.md: Grenzen digitaler Therapie-Unterstuetzung, Verbotsliste, Notfall-Verweis
- **Schwarm-LLM Parallele Worker (SQ016):** Echte parallele Ausfuehrung in llmauto
  - `ClaudeRunner.run_parallel()`: ThreadPoolExecutor-basierte Multi-Prompt-Ausfuehrung
  - `run_parallel_workers()`: Parallele Worker in Chain-Ketten (aktiviert via `parallel_workers: true`)
  - Benchmark-Script: 20 Tasks in 4 Kategorien, Vergleich sequentiell vs. parallel

### Schema

- Migration 032: `bach_blobs` + `bach_blobs_fts` + `bach_blob_history` Tabellen
- Gesamt: 138 Tabellen

### Fixes

- email_sender.py: Robusterer Zugriff auf attachment_path in Row-Objekten

---

## [3.4.0-pizza] - 2026-03-02

### Neu

- **Agent Portability Framework (B32/SQ049):** PortableAgent-Basisklasse -- Agenten funktionieren standalone ohne BACH
- **Plan-Agent (SQ018):** Strukturierte Planungsprotokolle mit JSON-Schema und CLI
- **Bridge Server Mode (SQ052):** FastAPI REST-API fuer server-deployable Bridge (POST /api/message, GET /api/status, POST /api/control)
- **Reminder-Injektor (SQ040):** LLM-Selbsterinnerung vor jedem Call, DB + JSON-Fallback
- **Meta-Feedback-Injektor (SQ042):** Auto-Korrektur wiederkehrender LLM-Ticks mit Pattern-DB
- **Arbeitsmodi & 24h-Agent (SQ048):** Session-Kontext-Persistenz, Tageswechsel-Logik, Modi focused/assistant/autonomous
- **Schwarm-LLM-Haiku (SQ016):** Chain-Configs fuer Haiku-Worker-Schwarm mit Sonnet-Coordinator

### Verbessert

- **ResearchAgent (SQ054):** Echte PubMed-API-Integration (NCBI E-Utilities), optionale Perplexity-API
- **EntwicklerAgent (SQ055):** 6-Phasen-Architektur verifiziert, standalone-faehig, robuste Imports
- **llmauto Standalone (SQ056):** pyproject.toml, BACH_AVAILABLE Flag, Chains laufen ohne DB
- **Multi-BACH Vorbereitung (SQ028):** BACH_ROOT ENV, _KNOWN_USER_HOMES eliminiert, hardcodierte Pfade bereinigt

### Dokumentation

- **BACH-in-a-Database Vision (SQ044):** Konzeptpapier mit Inventar (1.819 Dateien) und Architekturvorschlag
- **Therapie-Skills Recherche (B30/SQ046):** 25 Methoden inventarisiert, Gap-Analyse, Implementierbarkeitsbewertung
- **Legacy (ENT-25):** CHIAH + recludOS Publikations-Vorbereitung, READMEs erstellt, RECLUDOS_ROOT eliminiert
- **Schwarm-Haiku Konzeptpapier (SQ016):** Architektur, Kosten-Analyse, Benchmark-Plan
- **Bridge Deployment-Doku:** SSH-Tunnel + Systemd-Service Anleitung

### Schema

- Migration 030: `reminders` + `meta_feedback_patterns` Tabellen
- Migration 031: `session_context` Tabelle
- Gesamt: 135 Tabellen

### Tests

- 248/249 Tests bestanden (99.6%), 1 vorbestehender Fehler
- 109/109 Handler importierbar
- PII-Scan: Keine neuen Findings in PIZZA-Dateien
- Migration-Integritaet: Schema auf frische DB fehlerfrei

---

## [3.3.0-peanut] - 2026-03-01

### Breaking Changes

- **MCP-Server aus Repo entfernt:** `system/tools/mcp/bach-codecommander/`, `bach-filecommander/`, `n8n-manager-mcp/` sind nicht mehr im Repo enthalten. Stattdessen: `bach setup mcp` oder `npm install -g ellmos-codecommander-mcp ellmos-filecommander-mcp`
- **--max-turns entfernt:** Einzel-Sessions haben kein festes Turns-Limit mehr. Loop-Sessions behalten Sicherheitslimits.

### Neue Handler

- **NEU:** `SetupHandler` (`hub/setup.py`)
  - Befehl: `bach setup mcp` - MCP-Server global installieren und Claude Code konfigurieren
  - Befehl: `bach setup check` - Abhaengigkeiten pruefen
  - Befehl: `bach setup secrets` - Secrets-Datei synchen

### Datenbankschema

- **NEU:** 6 Shared-Memory-Tabellen (Migration 023, SQ043 Stufe D):
  - `shared_memory_facts`, `shared_memory_lessons`, `shared_memory_sessions`
  - `shared_memory_working`, `shared_memory_consolidation`, `shared_context_triggers`
- **NEU:** TTL-Support (expires_at) fuer `shared_context_triggers`
- **NEU:** Migration 024: Idempotente Daten-Migration von alten memory_* Tabellen
- **NEU:** Performance-Indizes fuer alle shared_* Tabellen

### Bug-Fixes

- **FIX:** `&`-Zeichen im Pfad `KI&AI` brach Agent-Start und andere .bat-Operationen
  - Alle `set`-Zuweisungen in .bat-Dateien verwenden jetzt Anfuehrungszeichen
- **FIX:** Telegram Bridge fand keinen Bot-Token in Strawberry
  - Secrets von `~/.bach/bach_secrets.json` in DB gesyncht
  - Telegram-Connection in connections-Tabelle angelegt
- **FIX:** Feste --max-turns Werte aus Einzel-Sessions entfernt (waren 50-200)

### Bereinigung

- `.gitignore` um USER-spezifische Experten und Skills erweitert (dist_type 0, nie veroeffentlicht)
- `directory_truth.json` Config aktualisiert

### Installer

- `setup.py` erweitert: `--non-interactive`, `--quiet`, `check` Subcommand
- Python-Migrations-Support (`.py` neben `.sql`)

### Dokumentation

- `YOUR_USERNAME` Platzhalter durch `lukisch` ersetzt (7 Dateien)
- MCP-Installationsanleitung im README hinzugefuegt

---

## [3.2.0-butternut] - 2026-02-28

### Datenbankschema

- **UMBENENNUNG:** `daemon_jobs` → `scheduler_jobs` (klarere Bezeichnung)
- **UMBENENNUNG:** `daemon_runs` → `scheduler_runs` (konsistent mit scheduler_jobs)
- **NEU:** Tabelle `prompt_templates` - Zentrale Prompt-Verwaltung
  - Felder: id, name, content, version, tags, created_at, updated_at
- **NEU:** Tabelle `prompt_versions` - Versionsverlauf fuer Prompts
  - Felder: id, template_id (FK), content, version_note, created_at
- **NEU:** Tabelle `prompt_boards` - Sammlungen von Prompts (Boards)
  - Felder: id, name, description, created_at
- **NEU:** Tabelle `prompt_board_items` - Zuordnung Prompt → Board
  - Felder: id, board_id (FK), template_id (FK), position, added_at
- **NEU:** 8 Schema-Migrationen nachgezogen (Migrationen 012 bis 020)

### Neue Handler

- **NEU:** `AgentLauncherHandler` (`hub/handlers/agent_launcher.py`)
  - Befehl: `bach agent`
  - Startet, stoppt und verwaltet Agent-Ausfuehrungen
  - Unterstuetzt llmauto-Ketten und direkte Agent-Runs
- **NEU:** `PromptHandler` (`hub/handlers/prompt.py`)
  - Befehl: `bach prompt`
  - CRUD fuer prompt_templates und prompt_boards
  - Operationen: list, add, edit, delete, show, board-create, board-add, board-list

### SharedMemory-Erweiterungen

- **NEU:** Operation `current-task` - Aktuellen Task im Shared Memory speichern/abfragen
- **NEU:** Operation `generate-context` - Automatische Kontext-Generierung aus Working Memory + Facts
- **NEU:** Operation `conflict-resolution` - Konflikterkennung bei gleichzeitigem Multi-Agent-Zugriff
- **NEU:** Operation `decay` - Zeitbasierter Relevanz-Abbau fuer Working-Memory-Eintraege
- **NEU:** Operation `changes-since` - Delta-Abfrage: Alle Aenderungen seit Zeitstempel T

### ChainHandler

- **NEU:** Operation `create` fuer ChainHandler - Neue Chain aus YAML/JSON-Definition anlegen
- **ERWEITERUNG:** llmauto-Ketten neben klassischen Toolchains unterstuetzt
  - llmauto-Ketten koennen Claude-Prompts als Chain-Steps definieren
  - Konfiguration via `chain_type: llmauto` in Chain-Definition

### SchedulerService

- **NEU:** `job_type='chain'` im SchedulerService
  - Ketten koennen als zeitgesteuerte Jobs registriert werden
  - `bach scheduler add --type chain --chain-id <id> --cron "0 8 * * *"`

### USMC Bridge

- **NEU:** `hub/_services/usmc_bridge.py` - USMC Bridge (United Shared Memory Client)
  - Verbindet SharedMemory-Handler mit externen Agenten und Services
  - Protokoll: JSON-basiert, unidirektional oder bidirektional
  - Unterstuetzt: local, tcp, file-based Transport

### bach:// URL-Resolution

- **NEU:** bach:// URL-Schema in llmauto-Prompts
  - `bach://memory/facts/key` → laedt Fact direkt in Prompt
  - `bach://task/current` → injiziert aktuellen Task
  - `bach://skill/help/topic` → laedt Help-Text fuer Thema
  - Resolution via `hub/url_resolver.py`

### Prompt-Migration

- **NEU:** `tools/migrate_prompts.py` - Einmalige Migration aller Prompt-Quellen in DB
  - Quelle 1: `partners/claude/prompts/` (Partner-spezifische Prompts)
  - Quelle 2: `skills/_services/*/prompts/` (Service-Prompts)
  - Quelle 3: `data/prompt_templates/` (Legacy Dateisystem-Prompts)
  - Ergebnis: Alle Prompts in `prompt_templates` DB-Tabelle, Versionierung erhalten

### Portierungen von Vanilla

- **PORT:** `SharedMemoryHandler` aus vanilla portiert
  - Vollstaendige Implementierung mit allen 5 neuen Operationen (s.o.)
- **PORT:** `ApiProberHandler` aus vanilla portiert
  - Befehl: `bach api-probe` - Testet HTTP-Endpoints
- **PORT:** `N8nManagerHandler` aus vanilla portiert
  - Befehl: `bach n8n` - Verwaltet n8n-Workflows via REST-API
- **PORT:** `UserSyncHandler` aus vanilla portiert
  - Befehl: `bach user-sync` - Synchronisiert User-Profile zwischen Instanzen
- **PORT:** Stigmergy-Service aus vanilla portiert
  - `hub/_services/stigmergy/` - Indirektes Koordinationssystem fuer Agenten
  - Pheromon-basiertes Signal-Routing

### Archivierungen

- **ARCHIV:** `marble_run` in `_archive/marble_run/` verschoben
  - Ersetzt durch llmauto-Integration im ChainHandler
- **ARCHIV:** ATI SessionDaemon (`agents/ati/session_daemon.py`) archiviert
  - Ersetzt durch SchedulerService mit job_type='chain'

### Geaendert

- **UPDATE:** `core/registry.py` - AgentLauncherHandler und PromptHandler registriert
- **UPDATE:** `hub/shared_memory.py` - 5 neue Operationen implementiert
- **UPDATE:** `hub/chain.py` - create-Operation + llmauto-Support
- **UPDATE:** `hub/daemon.py` (→ Scheduler) - job_type='chain' + Umbenennung DB-Tabellen
- **UPDATE:** `db/schema.sql` - 4 neue Tabellen, Umbenennung daemon_* → scheduler_*

---

## [2.2.0] - 2026-02-08

### Hinzugefuegt

- **NEU:** MCP Server v2.2.0 - Vollstaendige MCP-Integration
  - **Refactoring v1.1 → v2.0:** Komplett auf bach_api umgestellt (kein direkter SQLite mehr)
  - **19 Tools** via Handler-Logik: task (4), memory (6), lesson, backup (2), steuer, contact, msg (3), notify, healthcheck, db_query
  - **8 Resources:** tasks/active, tasks/stats, status, memory/lessons, memory/status, skills/list, contacts, version
  - **3 MCP Prompts:** daily_briefing, task_review, session_summary (alle drei MCP-Primitives!)
  - **v2.1 → v2.2:** +4 Tools (session_startup, session_shutdown, partner_list, partner_status)
  - **db_query Table-Whitelist:** 110 erlaubte Tabellen, blockiert mail_accounts und connections (Credentials)
  - **23 Tools** gesamt, Konformitaet 95%
  - Doku: `../docs/_archive/con4_MCP_CONFORMITY_60.md`

- **NEU:** Email-Adapter in NotifyHandler (`hub/notify.py`)
  - `notify setup email smtp.gmail.com --token=APP_PASSWORD --email=user@gmail.com`
  - SMTP_SSL Versand (Port 465), Self-Notification
  - Portiert aus BachForelle email.py

- **NEU:** BachFliege + BachForelle Analyse und Archivierung
  - Beide Projekte systematisch mit BACH v2 verglichen
  - Wertvolle Patterns dokumentiert (Knowledge Graph Triple-Store, modulare FastAPI)
  - Email-Adapter aus BachForelle bereits portiert
  - Doku: `../docs/_archive/con5_BACHFLIEGE_BACHFORELLE_ARCHIV.md`

### Geaendert

- **UPDATE:** `tools/mcp_server.py` - Komplett neugeschrieben (v1.1 → v2.2)
- **UPDATE:** `hub/notify.py` - Email-Channel hinzugefuegt (_setup, _dispatch, _send_email)
- **UPDATE:** `../docs/_archive/con4_MCP_CONFORMITY_60.md` - Status 95%, 23 Tools dokumentiert

---

## [2.1.0] - 2026-02-08

### Hinzugefuegt

- **NEU:** Message-System Upgrade - Zuverlaessige Zustellung (v2.0)
  - Queue-Processor (`hub/_services/connector/queue_processor.py`) mit:
    - `poll_all_connectors()` - Automatisches Polling aller aktiven Connectors
    - `route_incoming()` - Routing mit ContextInjector + context_triggers Tagging
    - `dispatch_outgoing()` - Versand mit exponentiellem Backoff (30s-480s)
    - `ensure_daemon_jobs()` - Idempotente Daemon-Job-Registrierung
  - Retry/Backoff: 5 Versuche, Dead-Letter-Queue, manuelles Recovery
  - Circuit Breaker: 5 Fehler → 5 Min Sperre, Auto-Reset nach Cooldown

- **NEU:** Schema-Migration `001_connector_queue_upgrade.sql`
  - connector_messages: +retry_count, max_retries, next_retry_at, status, updated_at
  - connections: +consecutive_failures, disabled_until (Circuit Breaker)
  - Indizes fuer Retry-Scheduling und Outbound-Dispatch
  - Backfill bestehender Daten basierend auf processed/error

- **NEU:** Messages REST-API (`gui/api/messages_api.py`)
  - `POST /api/v1/messages/send` - Nachricht in Queue einreihen
  - `GET /api/v1/messages/queue` - Queue-Status (pending/failed/dead)
  - `GET /api/v1/messages/inbox` - Inbox lesen (Paginierung, Filter)
  - `POST /api/v1/messages/route` - Routing manuell ausloesen

- **NEU:** ConnectorHandler Queue-Management Operationen
  - `bach connector setup-daemon` - Daemon-Jobs registrieren
  - `bach connector queue-status` - Queue-Statistiken anzeigen
  - `bach connector retry <id|all>` - Dead-Letter zuruecksetzen

- **NEU:** Help-Datei `docs/docs/docs/help/connector.txt` - Vollstaendige Connector-Dokumentation
- **NEU:** `connectors/SKILL.md` - Connector Skill-Dokumentation

### Geaendert

- **UPDATE:** `gui/api/headless.py` - Messages-Router eingebunden (4 Endpoints)
- **UPDATE:** `hub/connector.py` - 3 neue Operationen, Help-Text erweitert
- **UPDATE:** `db/schema.sql` - Kanonische Definitionen fuer Neuinstallationen
- **UPDATE:** `docs/docs/docs/help/messages.txt` - Connector-Integration, REST-API Sektion
- **UPDATE:** `docs/docs/docs/help/daemon.txt` - Connector-Jobs dokumentiert

---

## [2.0.0] - 2026-02-06

### Hinzugefuegt

- **NEU:** bach.py v2.0 Registry-Based Architecture
  - Auto-Discovery via `core/registry.py` (563 Zeilen statt 1.636)
  - Library-API `bach_api.py` (task, memory, backup, status, steuer, lesson)
  - Dual-Init BaseHandler (Path und App)
  - 50 Tests (test_core + test_smoke) bestanden

- **NEU:** Connector Runtime Bridge
  - `_instantiate()` - Erstellt echte Connector-Instanzen aus DB-Config
  - `_poll()` - Einmal pollen: connect → get_messages → store → disconnect
  - `_dispatch()` - Ausgehende Queue: connect → send each → mark → disconnect

- **NEU:** Voice Service (skeleton → beta)
  - STT (Whisper/Vosk), TTS (pyttsx3 mit Voice-Selection), Wake-Word
  - Portiert aus BachForelle voice.py + ears.py

- **NEU:** Telegram Connector Upgrades
  - Owner-Filter (`owner_chat_id`), `poll_loop()`, `poll_threaded()`

- **NEU:** Discord Connector Upgrades
  - Incremental Polling (`_last_message_id`), Bot-Filter, `poll_loop()`

### Geaendert

- **REFACTOR:** Log-Pfade konsolidiert → `system/data/logs/`
- **REFACTOR:** `partners/` konsolidiert → `system/partners/`

---

## [1.2.0] - 2026-02-01

### Hinzugefuegt

- **NEU:** Pfad-Konsolidierung - Neue Ordnerstruktur
  - `system/` Ordner fuer System-Kern (bach.py, hub/, gui/, data/, skills/)
  - `user/` auf Root-Ebene fuer User-Daten (isoliert)
  - `docs/`, `system/system/system/system/exports/`, `extensions/` auf Root-Ebene
  - Klare Trennung System vs. User-Daten

- **NEU:** GitHub-Kompatibilitaet
  - `.gitignore` schuetzt User-Daten und Laufzeit-Dateien
  - `README.md` mit Projekt-Dokumentation
  - `SKILL.md` auf Root-Ebene als Einstiegspunkt

- **NEU:** Hierarchische Pfad-Konfiguration in `bach_paths.py`
  - `BACH_ROOT` = Repository Root
  - `SYSTEM_ROOT` = system/ Ordner
  - `HUB_DIR` = system/hub/
  - Alle Pfade relativ und portabel

- **NEU:** Skills-Konsolidierung unter `system/skills/`
  - `tools/` - Python-Tools (~70 Scripts)
  - `docs/docs/docs/help/` - Hilfe-Texte
  - `_agents/`, `_experts/`, `partners/`, `_workflows/`, `_services/`

- **NEU:** User-Dokumente Struktur
  - `user/documents/persoenlicher_assistent/` (finanzen, gesundheit, steuer)
  - `user/documents/foerderplaner/`
  - `user/documents/production_studio/`
  - `user/documents/data-analysis/`

### Geaendert

- **UPDATE:** `system/hub/bach_paths.py` - Komplette Neustrukturierung
- **UPDATE:** `system/bach.py` - Pfad-Konstanten angepasst
- **UPDATE:** `system/hub/help.py` - help_dir auf skills/docs/docs/docs/help/
- **UPDATE:** `system/hub/tools.py` - tools_dir auf skills/tools/

### Dokumentation

- **Migrationsplan:** `docs/_archive/MIGRATION_PLAN_v1.2_20260201.md`
- **Migrationsbericht:** `docs/_archive/MIGRATION_REPORT_v1.2_20260201.md`

---

## [1.1.73] - 2026-01-28

### Hinzugefuegt

- **NEU:** Direkte Nachrichten-Injektion im Startup (v1.1.73)
  - Partner sehen beim Start VOLLSTAENDIGE Nachrichten an sie
  - Zeigt: ID, Absender, Uhrzeit, Body (erste 3 Zeilen)
  - Keine Nachrichten mehr verpassen bei Komprimierung!
- **NEU:** Lesebestaetigung mit `--ack` Flag
  - `bach msg read 60 --ack` - Lesen UND Bestaetigung senden
  - Automatische ACK-Nachricht an Absender
- **NEU:** Ordner-Locks zusaetzlich zu Datei-Locks
  - `bach llm lock <ordner>` - Sperrt ganzes Verzeichnis
  - Lock-Datei: `<ordner>/.dirlock.<agent>`
- **NEU:** Live-Status zeigt aktuelle Locks aus DB
  - `bach llm status` zeigt FILE/DIR Locks
- **NEU:** Chat-System fuer Multi-LLM Kommunikation
  - `bach msg ping --from <partner>` - Einmalig Nachrichten zeigen
  - `bach msg watch --from <partner>` - Polling alle 10s (Chat-Modus)
  - `bach --startup --watch` - Auto-Watch beim Start
  - TimeInjector prueft Nachrichten bei jedem Timebeat
- **NEU:** Erster erfolgreicher Multi-LLM Shared-File Test!
  - Claude + Gemini haben gemeinsam SHARED_TEST.md bearbeitet
  - Lock-Koordination und Chat funktionieren

### Geaendert

- **FIX:** Message-Sender war immer "user" statt Partner-Name
  - Auto-Detect aus partner_presence DB
- **UPDATE:** hub/startup.py - Nachrichten-Injektion, --watch Flag, Chat-Hinweis
- **UPDATE:** hub/messages.py - ping, watch, --ack, --from Parameter
- **UPDATE:** hub/multi_llm_protocol.py - Ordner-Locks, DB Live-Status
- **UPDATE:** skills/tools/injectors.py - TimeInjector mit Nachrichten-Check
- **UPDATE:** bach.py - --watch Parameter bei Startup

---

## [1.1.71] - 2026-01-28

### Hinzugefuegt

- **NEU:** Stempelkarten-System fuer Partner-Awareness
  - DB-Tabelle `partner_presence` (status, clocked_in, clocked_out, heartbeat)
  - Automatisches Clock-In bei `--startup --partner=NAME`
  - Automatisches Clock-Out bei `--shutdown`
  - Crashed Sessions werden bei Restart erkannt und bereinigt
- **NEU:** Partner-Awareness im Startup-Output
  - Zeigt online Partner mit aktuellem Task
  - Empfiehlt Protokoll V3 bei mehreren Partnern
- **NEU:** Neue Partner registrieren
  - `--partner=simonAI` - Mit eigenem Namen
  - `--partner=new` / `--partner=nameless` - Generiert auto-ID (partner_HHMMSS)
- **NEU:** Between-Task Injektor erweitert um Partner-Check

### Geaendert

- **UPDATE:** hub/startup.py - Clock-In Logik, Partner-Awareness Sektion
- **UPDATE:** hub/shutdown.py - Clock-Out Logik
- **UPDATE:** skills/docs/docs/docs/help/startup.txt - Stempelkarten-System dokumentiert
- **UPDATE:** skills/docs/docs/docs/help/multi_llm.txt - Richtiger Start mit Stempelkarte
- **UPDATE:** SKILL.md - Multi-LLM Sektion mit Startup-Anleitung

---

## [1.1.70] - 2026-01-27

### Hinzugefuegt

- **NEU:** `bach task edit <id>` - Tasks nachtraeglich bearbeiten (Titel, Beschreibung, Kategorie)
  - Optionen: `--title/-t`, `--description/-d`, `--category/-c`
- **NEU:** `bach lesson edit <id>` - Lessons nachtraeglich bearbeiten
  - Optionen: `--title/-t`, `--solution/-s`, `--category/-c`, `--severity`
  - Validierung gegen erlaubte Kategorien und Severities
- **NEU:** `bach lesson deactivate <id>` - Lessons deaktivieren
  - Optionen: `--reason/-r` fuer Begruendung
  - Prueft ob existiert und ob bereits inaktiv
- **NEU:** `bach task edit <id> --assigned <name>` - Tasks zuweisen
  - Weist Task an Partner zu (claude, gemini, user)
  - Lesson #58: CLI-Varianten aus Fehlversuchen uebernehmen
- **NEU:** `bach llm` - Multi-LLM Protocol Handler (Protokoll V3)
  - `bach llm presence` - Anwesenheit signalisieren
  - `bach llm check` - Andere Agenten erkennen
  - `bach llm lock/unlock` - Dateisperren verwalten
  - `bach llm handshake` - Auto-Detection starten
  - `bach llm status` - Multi-LLM Status anzeigen
- **NEU:** hub/multi_llm_protocol.py - Protokoll-Implementation (545 Zeilen)
- **NEU:** skills/docs/docs/docs/help/multi_llm.txt - Protokoll-Dokumentation (192 Zeilen)
- **NEU:** Lesson #53 erweitert: CLI-First-Prinzip mit Regeln, Checkliste und Ausnahmen
- **NEU:** 4 neue Lessons (#54-57):
  - #54: Vor neuen Datenstrukturen Anschlussfaehigkeit pruefen
  - #55: Neue Aufgaben aus Analysen als Tasks erfassen
  - #56: Multi-LLM Task-Zuweisung und Progress-Status
  - #57: Grosse Aufgaben zerlegen und Fortschritt dokumentieren
- **NEU:** Multi-LLM Spielwiese: ../user/_spielwiese/multi_llm_test/

### Dokumentation

- **NEU:** `../docs/analyse/DATA_JSON_INTEGRATION_ANALYSE.md` - Bewertung aller 10 JSON-Dateien in data/
  - 1x DB-Integration empfohlen (skills_hierarchy.json)
  - 7x als JSON behalten (Configs, Cache, System)
- **NEU:** `../docs/analyse/STEUER_DB_INKONSISTENZEN.md` - Analyse ID-Feld Chaos und Template/Export/DB Benennungen
- **NEU:** `../user/steuer/studium_ausgaben_info.txt` - Erst- vs Zweitstudium Steuerregeln
- **NEU:** `../user/steuer/versicherungen_lohnt_sich_analyse.txt` - Wann lohnen sich Versicherungen steuerlich

### Gefixt

- **BUGFIX:** BUG-013 - BAT-Pfadfehler in ../user/steuer/2025/Werbungskosten (FINANZAMT.bat, SYNC.bat)
  - Falscher relativer Pfad korrigiert (3 -> 4 Level up)

### Geaendert

- **UPDATE:** skills/docs/docs/docs/help/tasks.txt - Dokumentation fuer task edit ergaenzt
- **UPDATE:** Steuer-Templates: "Nr" -> "PostenID"/"BelegNr" fuer Konsistenz mit Exports
- **AUDIT:** Lessons-Audit - 4 Lessons deaktiviert (#21 test, #29 recludOS veraltet, #30 Duplikat, #33 in #32 integriert)
- **TEST:** Multi-LLM Parallelarbeit (Task #529) - Getrennte Workspaces OK, Shared Files haben Race Conditions

---

## [1.1.69] - 2026-01-27

### Hinzugefuegt

- **NEU:** Skills-Board DB-Synchronisation (`sync_skills.py`) - Automatische Erfassung von Workflows und Skills aus DB und Filesystem.
- **NEU:** Memory Dev-Mode - Loesch-Optionen und DB-Struktur-Ansicht in der GUI.
- **NEU:** Financial Report Generator - PDF/JSON Export von Finanzdaten in der GUI.

### Geaendert

- **UPDATE:** Tasks Board: HTML5 Drag & Drop fuer Status-Updates und visuelles Feedback.
- **UPDATE:** Tasks Board: Voller Edit-Mode mit klassischer Eingabemaske fuer Tasks.
- **UPDATE:** Maintenance Seite: Konsolidiertes Layout, bessere Daemon-Status-Anzeige.
- **UPDATE:** Wiki & Help: Bessere Trennung von Content-Typen in der Sidebar.

---

## [1.1.68] - 2026-01-26

### Hinzugefuegt

- **AI_001 (Multi-Job Daemon):** session_daemon.py zu Multi-Job Scheduler erweitert (Task #472)
  - Unterstützt Liste von Jobs in `config.json`
  - Individuelle Intervalle und Profile pro Job
  - Tracking von `last_run` pro Job

- **OLLAMA_005 (Offline Fallback):** Automatische Umschaltung auf lokale AI bei Delegierung (Task #299)
  - `bach partner delegate --fallback-local` Flag
  - DNS-basierter Connectivity-Check (`_is_network_available`)
  - Automatischer Wechsel zu Ollama wenn Offline

- **MEM_001 (Kognitive Memory):** Relevanz-basiertes Memory-Retrieval (Task #473)
  - `bach mem search` nutzt jetzt Keyword-Overlap-Scoring statt Substring-Match
  - Sortierung nach Relevanz (Score)

- **AG_001 (Deep Expertise):** Spezialisierte Agenten via Prompt-Generator (Task #474)
  - Neues Template `templates/agents/specialist.txt`
  - CLI: `bach prompt session specialist --expertise="THEMA"`
  - Dynamische Injection von Fachwissen in den System-Prompt

- **AI_003/004 (Headless Sessions):** Verbesserte Autonomie (Task #457/458)
  - Strikte Zeitbudget-Anweisungen im Prompt-Generator
  - Erzwungener `bach --shutdown "REPORT"` Aufruf am Session-Ende

### Korrigiert

- **SYNC_003 (Bugfix):** SQL-Constraint Fehler behoben (Task #471)
  - Fehlende `type` und `category` Spalten im INSERT Statement ergänzt
  - Hash-Berechnung (`_compute_hash`) implementiert

---

### Hinzugefuegt

- **SYNC_003 (KOMPLETT):** sync.py Handler voll implementiert
  - `_sync_skills()` - Skills von Dateisystem in DB laden
  - `_sync_tools()` - Tools aus skills/tools/ scannen und DB aktualisieren
  - `_status()` - Zeigt geaenderte/neue/fehlende Eintraege
  - Hash-basierte Aenderungserkennung (SHA256, 16 chars)
  - Statistik-Ausgabe fuer alle Operationen
  - Task #435 erledigt

---

## [1.1.66] - 2026-01-25

### Hinzugefuegt

- **SYNC_003 (Grundgeruest):** sync.py Handler erstellt (130 Zeilen)
  - `bach --sync skills` - Skills synchronisieren (TODO)
  - `bach --sync tools` - Tools synchronisieren (TODO)
  - `bach --sync status` - Sync-Status anzeigen (TODO)
  - `--dry-run` und `--force` Optionen vorbereitet
  - Handler in bach.py Registry registriert

### Geaendert

- **ROADMAP.md:** SYNC_002 als ERLEDIGT markiert (Schema komplett)
- **ROADMAP.md:** SYNC_003 als IN PROGRESS markiert

---

## [1.1.65] - 2026-01-25

### Hinzugefuegt

- **SYNC_001:** DB-Schema erweitert (Phase 7 Start)
  - `skills.content` - Aktueller Datei-Inhalt
  - `skills.content_hash` - SHA256 fuer Aenderungserkennung
  - `tools.template_content` - Fuer Reset
  - `tools.content` - Aktueller Datei-Inhalt
  - `tools.content_hash` - SHA256 fuer Aenderungserkennung
  - 5 ALTER TABLE erfolgreich, Task #434 done

### Geaendert

- **ROADMAP.md:** SYNC_001 als ERLEDIGT markiert

---

## [1.1.64] - 2026-01-25

### Hinzugefuegt

- **INBOX_008:** GUI-Einstellungen komplett (Phase 10 FERTIG!)
  - inbox.html bereits vollstaendig implementiert
  - Ordner-Liste mit Add/Remove/Refresh
  - Sortier-Regeln Editor
  - Settings-Panel
  - Review-Queue Anzeige
  - Tasks 432 + 433 als done markiert

### Geaendert

- **ROADMAP.md:** Phase 10 (Dokumenten-Scanner) 100% komplett (8/8 Tasks)

---

## [1.1.63] - 2026-01-25

### Hinzugefuegt

- **INBOX_006:** OCR-Integration komplett (Phase 10)
  - `extract_text_from_file()` - Hauptfunktion fuer Textextraktion
  - `_ocr_image()` - pytesseract fuer Bilder (PNG, JPG, etc.)
  - `_ocr_pdf()` - pdf2image + pytesseract fuer PDFs
  - Content-Pattern-Matching jetzt aktiv in `_auto_sort()` und `process_scan()`
  - Deutsche + Englische Sprachunterstuetzung (deu+eng)
  - Performance-Optimierung: OCR nur bei Bedarf

- **inbox_watcher.py:** Version 0.6.0

### Geaendert

- **ROADMAP.md:** INBOX_006 als ERLEDIGT markiert (v2.0.26)

---

## [1.1.62] - 2026-01-25

### Hinzugefuegt

- **inbox_watcher.py:** Version 0.5.0 - Daemon-Integration (INBOX_003 komplett)
  - Neuer `--process` Modus fuer periodische Scans
  - Scannt und sortiert Dateien (nicht nur dry-run)
  - Standalone `_create_review_task_standalone()` fuer process_scan
  - Daemon-Job 'inbox-scan' registriert (ID 3, alle 30 Min)

### Geaendert

- **ROADMAP.md:** INBOX_003 als ERLEDIGT markiert

---

## [1.1.61] - 2026-01-25

### Hinzugefuegt

- **inbox_watcher.py:** Version 0.4.0
  - Dry-run Modus implementiert (`--dry-run`)
  - Scannt alle Watch-Ordner und zeigt was passieren wuerde
  - Statistiken: Dateien, sortiert, manuell
  - TODO: Daemon-Integration

---

## [1.1.60] - 2026-01-25

### Hinzugefuegt

- **INBOX_005:** Sortier-Regeln Engine implementiert (Phase 10)
  - `_auto_sort()` Methode mit Regex-Pattern-Matching
  - Regeln nach Prioritaet sortiert
  - Zielverzeichnis-Aufloesung mit {year} Platzhalter
  - Automatische Verzeichnis-Erstellung

- **INBOX_007:** Manuelle Review-Queue implementiert (Phase 10)
  - `_create_review_task()` erstellt BACH-Tasks fuer Dateien ohne Match
  - Subprocess-Aufruf von `bach task add`
  - Integration in Transfer-Zone Workflow

- **inbox_watcher.py:** Version 0.3.0
  - Sortier-Engine + Task-Integration komplett
  - TODO: dry-run Modus + Daemon-Integration

---

## [1.1.59] - 2026-01-25

### Hinzugefuegt

- **INBOX_001 + INBOX_002:** Dokumenten-Scanner/Inbox-System Grundlagen (Task Phase 10)
  - `../docs/CONCEPT_inbox_folders_format.md` - Format-Spezifikation fuer inbox_folders.txt
  - `data/inbox_folders.txt` - Template mit Watch-Ordner-Definition
  - `../docs/CONCEPT_inbox_config_schema.md` - JSON-Schema fuer inbox_config.json
  - `data/inbox_config.json` - Template-Konfiguration mit Sortier-Regeln
  - Vorbereitung fuer automatische Dokumenten-Sortierung (INBOX_003-008)

---

## [1.1.58] - 2026-01-25

### Hinzugefuegt

- **STEUER_005:** DATEV CSV-Export implementiert (Task 378)
  - `steuer export --format datev` fuer DATEV Buchungsstapel-Format
  - `steuer export --format csv` fuer einfaches Excel-CSV
  - SKR04 Konten-Mapping (6800=Arbeitsmittel, 6820=Gemischte)
  - CP1252 Encoding fuer DATEV-Kompatibilitaet
  - None-Handling fuer robuste Datenexporte
  - Export-Verzeichnis: `../user/steuer/{jahr}/export/`

---

## [1.1.57] - 2026-01-25

### Hinzugefuegt

- **PORT_006:** MarketService Klasse implementiert (Task 412)
  - `skills/_services/market/__init__.py` - MarketService Klasse erstellt
  - `skills/_services/market/config.py` - Konfiguration fuer Market-Service
  - Agent-Zugriff auf Market-Daten ermoeglicht
  - Roadmap Phase 5.2 PORT_006 erledigt

---

## [1.1.56] - 2026-01-25

### Hinzugefuegt

- **PORT_003b:** `skills/_services/household/schema_household.sql` erstellt
  - 8 Tabellen: products, scan_log, shopping_list, clients, medications, medication_entries, medication_log
  - 3 Views: v_household_low_stock, v_household_medication_status, v_household_client_plan
  - Kombiniert HausLagerist (Inventory) + MediPlaner (Health) in einem Schema
  - Tasks 410, 411 erledigt

- **PORT_004 (teilweise):** FinancialProof Streamlit-Migration in core/
  - `core/data_provider.py`: `import streamlit` entfernt
  - Neuer `ttl_cache()` Decorator als Ersatz fuer `@st.cache_data`
  - 5 Decorator-Stellen migriert (get_market_data, get_ticker_info, etc.)
  - Service-Layer (core/, analysis/, indicators/, jobs/) jetzt streamlit-frei
  - PORT_001 Migration kann fortgesetzt werden

- **GUI_002:** `gui/sync_service.py` erstellt - TXT-DB-Synchronisation
  - Parser fuer Beleg-TXT und Posten-TXT Dateien
  - Change Detection via MD5-Hash
  - Integration mit file_watcher.py via Callback
  - Export-Funktion DB -> TXT
  - Roadmap Phase 4.3 GUI_002 erledigt

### Gefixt

- **Task #379:** ATI Scanner Duplikaterkennung implementiert
  - `agents/ati/scanner/task_scanner.py` v1.2.1
  - Vor INSERT: Prueft ob task_text bereits fuer selbes tool_name existiert
  - Duplikate werden uebersprungen mit Log-Meldung
  - Verhindert mehrfaches Einfuegen gleicher Tasks

- **AGENT_002:** `skills/tools/production_agent.py` Output-Pfad korrigiert
  - Von `User/services_output/production/` auf `../user/production_studio/`
  - Konsistent mit AGENT_001 Ordnerstruktur

---

## [1.1.55] - 2026-01-25

### Gefixt

- **BUG-011:** `doc_update_checker.py` auf dateibasierte Pruefung umgestellt
  - `_get_all_docs()` verwendet jetzt glob statt nicht-existente DB-Tabellen
  - `update_timestamps()` als no-op markiert (Alters-Check direkt per mtime)
  - `bach --maintain docs` funktioniert wieder (65 Dokumente gefunden)

- **BUG-008:** Task-Titel Sanitization in `hub/handlers/task.py`
  - Neue Methode `_sanitize_title()` entfernt unbalancierte Anfuehrungszeichen
  - Normalisiert mehrfache Leerzeichen
  - Verhindert defekte Titel wie `"JSON_001` in der DB

---

## [1.1.53] - 2026-01-24

### Hinzugefuegt

- **TOKEN_001:** Auto-Shutdown Warnung bei 95%+ Token-Verbrauch
  - `skills/tools/token_monitor.py` neue Funktion `check_emergency_shutdown()`
  - `hub/handlers/startup.py` ruft Emergency-Check bei Startup auf
  - Visuelle Notfall-Box bei kritischem Token-Budget
  - Roadmap Phase 4.2 als erledigt markiert

### Geaendert

- **DEPRECATE_002:** `hub/hub.py` nach `hub/_archive/DEPRECATED_hub.py` archiviert
  - Keine externen Referenzen mehr gefunden
  - Task 316 erledigt

---

## [1.1.52] - 2026-01-24

### Geaendert

- **JSON_001-003 Migration:** Partner-System auf reine DB-Nutzung umgestellt
  - `hub/handlers/partner.py` handle() liest jetzt aus DB statt JSON
  - `skills/tools/maintenance/registry_watcher.py` partner_registry.json aus EXPECTED_JSON_FILES entfernt
  - `data/partners/partner_registry.json` nach `_archive/deprecated/` verschoben
  - Fallback auf JSON nur wenn DB leer (Hybrid-Schutz)

---


---

*Aeltere Versionen (1.0.0 - 1.1.49): Siehe _archive/CHANGELOG_archive_20260129.md*
