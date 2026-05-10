# BACH ROADMAP - Strategische Vision

**Stand:** 2026-05-10 | **Version:** 4.3.9

Copyright (c) 2026 BACH Contributors. Alle Rechte vorbehalten.

> Die ROADMAP definiert Vision und Phasen. Konkrete Tasks siehe: `bach task list`
> Post-Release-Details (SQ-Nummern): ehemals `BACH_Dev/ROADMAP.md` — jetzt hier konsolidiert.

---

## Vision

BACH definiert sich als **Personal Agentic Operating System**. Es entwickelt sich zu einem autonomen, lernfaehigen System mit:

- **Kognitives Memory-System** (menschliches Gedaechtnis als Vorbild)
- **Selbststaendige Sessions** (Headless AI ohne User-Interaktion)
- **Aktive Konsolidierung** (Lernen, Vergessen, Zusammenfassen)
- **Multi-Partner Delegation** (Claude, Gemini, Ollama, lokale Modelle)

---

## Entwicklungsprinzip: Systemisch First

> **BACH wird als wiederverwendbares System entwickelt, nicht fuer einen einzelnen User.**

Jede Funktion muss fuer ALLE zukuenftigen User funktionieren. Die Entwicklung
folgt der Reihenfolge:

1. **Systemisch** - Wiederverwendbare Services, Agents, Workflows
2. **CLI First** - Alles ueber CLI steuerbar
3. **User-Daten** - Import/Test mit echten Daten (z.B. Lukas' Daten)

Der aktuelle Entwickler (Lukas) nutzt BACH aktiv und testet mit seinen
eigenen Daten. Aber alle Workflows (Versicherungs-Import, Arztbericht-Scan,
Steuer-Export) muessen generisch sein und fuer jeden neuen User funktionieren.

**dist_type System** trennt System- von User-Daten:

- `0` = User-Daten (nicht mitgeliefert bei Installation)
- `1` = Template (zuruecksetzbar, Basis-Konfiguration)
- `2` = Core (System-intern, immer dabei)

Siehe: `../docs/WICHTIG_SYSTEMISCH_FIRST.md`

---

## GitHub-Veroeffentlichung (KOMPLETT)

Repo ist PUBLIC auf GitHub mit 14 Topics, Tags `v3.1.6`, `v3.3.0-peanut` und `v3.4.0-pizza`.

| Schritt | Status |
|---------|--------|
| Privates Repo erstellen & Push | KOMPLETT |
| Repo auf Public stellen | KOMPLETT |
| Tags setzen (v3.1.6, v3.3.0-peanut) | KOMPLETT |
| GitHub Topics (14 Stueck) | KOMPLETT |
| Release-Announcement | Ausstehend (Marketing) |

---

## Aktuelle Fokus-Bereiche

### Priorität 1 - Security, Plugin-Härtung, Self-Heal (ab 2026-04-30)

Der OpenClaw-Abgleich vom 2026-05-10 bestätigt den nächsten BACH-Fokus
klar in Richtung sichere Erweiterbarkeit, robuste Agenten-Laufzeit und
saubere Steuer-/Statusoberflächen. Relevant sind nicht die breite
Messenger-Abdeckung, sondern manifest-first Plugin- und Provider-Metadaten,
fail-closed Tool-Setups, Scans vor der Installation von
Skills/MCP-Servern/Plugins, API-Parität für Agentenflächen und
low-cardinality Telemetrie. Als Referenzstand gilt dabei: auf GitHub
Releases ist aktuell `openclaw 2026.5.6` vom 2026-05-06 sichtbar, während
die GHCR-Containerlinie bereits `2026.5.7-slim` ausrollt. Daraus erneut
bestätigt sind workspace-scoped Plugin-Metadaten-Snapshots auf Hot Paths,
Install-Hinweise für fehlende offizielle Erweiterungen, kollisionssichere
Session-Memory-Captures bei wiederholtem `/new` oder `/reset`,
Autorisierungs-Hooks für Inline-Tool-Dispatch, SecretRef-sichere
Runtime-Config-Snapshots, maschinenlesbare Cron-/Run-Status und restriktivere
Scopes für globale Memory-Toggles als prüfenswerte Impulse. Die erste
Stufe der Cache-Invalidierung ist jetzt in BACHs Agent-Runtime umgesetzt;
für Skill-/Plugin-Reset-Hooks bleibt weitere Verdrahtung offen. Neu
beobachtet, aber noch nicht priorisiert, sind aus `openclaw 2026.5.9-beta.1`
vor allem modellidentitätsbasierte Prompt-Injektion, gezielte
Workspace-Pfad-Helfer (`openclaw path`) sowie deutlichere Recovery-Hinweise
bei CLI-/Startup-/Config-Fehlern.

| ID | Thema | Status | Notiz |
|----|-------|--------|-------|
| SH-001 | CLI/API Self-Heal: `mem write`, `wiki read`, Task-ID bei `task add` | DONE | Implementiert und mit Unit-Tests abgesichert (2026-04-30) |
| SEC-PLUGIN-001 | Skill-/Plugin-/MCP-Install-Scanner | DONE (Stufe 1) | `skills install`, `plugins load` und lokale MCP-Config-Pfade scannen statisch, blockieren Code-Injection-Muster fail-closed und legen Quarantäne-Kopien mit `report.json` an |
| SEC-PLUGIN-002 | Manifest-first Plugin-Metadaten | TEILWEISE | `bach plugins inspect` liest Aktivierung, Capabilities, Provider-/Model-Catalogs und Setup-Metadaten ohne Runtime-Import; `plugins load` speichert diese Metadaten und blockiert fehlende Manifest-Dateireferenzen fail-closed |
| SEC-PLUGIN-003 | Fail-closed Tool-Setup-Checks | DONE | Plugin-Manifeste mit `shell`-/`desktop`-/`mcp`-Setupflächen brauchen jetzt `setup.fail_closed=true` plus passende `setup.checks`; `plugins inspect/load` blockieren unsichere Verträge vor Runtime-Code, und bestehende Claude Hook-/MCP-Config-JSONs werden vor Setup-Schreibzugriffen fail-closed validiert |
| SANDBOX-002 | Subprocess-Isolation | OFFEN | Timeout, Ressourcenlimit, erlaubte Capabilities; ergaenzt bestehende Stufe 1 |
| API-SURFACE-001 | Agent-/Prompt-API-Parität | DONE | `bach_api` exportiert jetzt die dokumentierten Module `agent`, `agents` und `prompt`; Agenten-Usecase per Regressionstest abgesichert |
| OPS-TELEM-001 | Low-cardinality Telemetrie | OFFEN | OpenTelemetry-inspiriert, aber lokal/privacy-first: Model-Calls, Tool-Loops, Agentenstarts und Fehler ohne sensible Payloads messen |
| OPS-CACHE-001 | Workspace-scoped Runtime-Cache-Invalidierung | DONE | `core.agent_runtime` trennt Registries jetzt pro `base_path`, lädt Agent-Module isoliert und invalidiert gecachte Instanzen automatisch bei Code-/Config-Änderungen |
| OPS-RUN-001 | Aktive Laufsteuerung langer Agenten-/Scheduler-Runs | TEILWEISE | `bach agent list/status --json` sowie `bach scheduler status/jobs/session status --json` liefern jetzt maschinenlesbare Run-Status-Flächen ohne Idle-/EOD-Chatter; echtes Operator-Steering an Modell-/Tool-Grenzen bleibt offen |
| MEM-PROV-001 | Memory-/Wiki-Provenance Views | DONE | `bach memory provenance` und `bach wiki provenance` zeigen Quellen, Evidenzart, Personenbezug und Privacy-Hinweise; gemeinsame Heuristiken plus Smoke-/Self-Heal-Tests sichern das Verhalten ab |

---

### Prioritaet 1-3 — Alle erledigt (2026-03-02)

Alle Prio 1-3 Items wurden implementiert und in die "Abgeschlossene Bloecke" verschoben.

---

### Prioritaet 4 — Visionen & Experimente (nach Release)

| SQ | Thema | Status | Notiz |
|----|-------|--------|-------|
| SQ016 | Schwarm-LLM-Haiku-Experimente | DONE | Chain-Configs + Konzeptpapier (PIZZA v3.4.0) |
| SQ018 | Plan-Agent & Planungsprotokoll | DONE | JSON-Schema + CLI (PIZZA v3.4.0) |
| SQ028 | Multi-BACH (benannte Instanzen) | DONE | BACH_ROOT ENV, Pfade bereinigt (PIZZA v3.4.0) |
| SQ040 | Reminder-Injektor | DONE | DB + JSON-Fallback (PIZZA v3.4.0) |
| SQ042 | Meta-Feedback-Injektor | DONE | Pattern-DB Auto-Korrektur (PIZZA v3.4.0) |
| SQ044 | BACH-in-a-Database (Vision) | DONE | Konzeptpapier + Inventar (PIZZA v3.4.0) |
| SQ048 | Arbeitsmodi & 24h-Agent | DONE | 3 Modi + Session-Kontext (PIZZA v3.4.0) |
| SQ052 | Bridge Antwort-Modus & Server-Betrieb | DONE | FastAPI REST-API (PIZZA v3.4.0) |
| SQ054 | ResearchAgent BACH-Re-Integration | DONE | PubMed-API + Perplexity (PIZZA v3.4.0) |
| SQ055 | devSoftAgent fertigstellen | DONE | 6-Phasen, standalone (PIZZA v3.4.0) |
| SQ056 | llmauto Standalone finalisieren | DONE | pyproject.toml, BACH_AVAILABLE (PIZZA v3.4.0) |
| ENT-25 | _CHIAH + recludOS als Legacy veroeffentlichen | DONE | READMEs, RECLUDOS_ROOT eliminiert (PIZZA v3.4.0) |

---

## Softwareprojekt-Integrationen (KOMPLETT - 2026-03-01)

6 Integrations-Aufgaben aus der Analyse aller 11 Tools vs. BACH (73 Handler, 23 Experten, 25+ Services).

| Integration | Beschreibung | Status |
|-------------|-------------|--------|
| INT01 | LitZentrum -> `literatur.py` + Expert `literaturverwalter` | KOMPLETT |
| INT02 | HausLagerist V4 -> `haushalt.py` erweitern + Expert | KOMPLETT |
| INT03 | MediaBrain -> `media.py` + Expert `mediaverwalter` | KOMPLETT |
| INT04 | MasterRoutine -> Routine-Export-Skill | KOMPLETT |
| INT05 | UpToday -> Dashboard-Aggregator `bach today` | KOMPLETT |
| INT06 | ProFiler -> Dedup + Datenschutz-Ampel | KOMPLETT |

---

## Weitere abgeschlossene Bloecke (ehemals Prio 1-3)

| Block | SQ | Aufgabe | Status |
|-------|-----|---------|--------|
| — | SQ073 | Scheduler-Migration (Tables, ChainHandler, llmauto, GUI-Tabs) | KOMPLETT (95%) |
| — | SQ074 | marble_run -> llmauto portiert (7 Strategien, 13 Chain-Configs) | KOMPLETT |
| B27 | SQ014 | UC46 MediaBrain auf 100% gehoben | KOMPLETT |
| B28 | SQ017 | GUI: Scheduler-Tab + Chain-Tab im Dashboard | KOMPLETT |
| B29 | SQ038 | Inter-Instanz-Messaging (Registry + Messaging + Hook-Extension) | KOMPLETT |
| B31 | SQ047/SQ059 | Wissensindexierung / KnowledgeDigest | KOMPLETT |
| B33 | SQ051 | Stigmergy-API vollstaendig implementiert | KOMPLETT |
| B34 | SQ075 | USER.md Installer-Integration + bidirektionaler Sync | KOMPLETT |
| B35 | SQ076 | Secrets-Management Installer-Integration | KOMPLETT |
| B36 | SQ080 | ApiProber Timeout-Bug + Tests | KOMPLETT |
| B37 | SQ081 | n8n MCP-Server als optionale Installation | KOMPLETT |
| B38 | SQ010 | Foerderplaner-Extraktion (pdf_processor, ocr_service) | KOMPLETT |
| B40 | SQ027 | Alt-Tests in pytest portieren | KOMPLETT |
| — | SQ033 | BACH Mini (USMC-basiert) | KOMPLETT |
| — | SQ036 | Vernunftstests (12/12 bestanden) | KOMPLETT |
| — | SQ043 | Memory-Migration Stufe D (2046 Sessions + 1120 Triggers migriert, db.py Python-Support) | KOMPLETT |
| — | HQ8 | Installer: full-install Orchestrator + Pre-Flight-Checks | KOMPLETT |
| — | SQ014 | UC26/27: Overpass API + OSRM Routing-Integration (Score 50→75) | KOMPLETT |
| — | SQ011 | Pipeline-Framework: DB-Tabellen + Decision-Briefing Scanner + 2 Pipeline-Definitionen | KOMPLETT |
| — | — | ROADMAP-Konsolidierung (4 Dateien → 1) | KOMPLETT |
| B30 | SQ046 | Therapie-Skills: Trauma + Systemisch | DONE (Recherche, PIZZA v3.4.0) |
| B32 | SQ049 | Agenten autonomer machen | DONE (PortableAgent, PIZZA v3.4.0) |

---

## Abgeschlossene Phasen (BACH-internes Entwicklungsprotokoll)

### 0b.2 Release v3.2.0-butternut (KOMPLETT - 2026-02-28)

Grosse BUTTERNUT-Release mit Scheduler-Refactoring, Prompt-System, neuen Handlern und Portierungen.

**DB-Schema:**
- `daemon_jobs` -> `scheduler_jobs`, `daemon_runs` -> `scheduler_runs`
- 4 neue Tabellen: `prompt_templates`, `prompt_versions`, `prompt_boards`, `prompt_board_items`
- 8 Migrationen (012-020) nachgezogen

**Neue Handler:**
- `AgentLauncherHandler` (`bach agent`) - Agent-Ausfuehrung via CLI
- `PromptHandler` (`bach prompt`) - Prompt-CRUD mit Board-System

**SharedMemory-Erweiterungen:**
- `current-task`, `generate-context`, `conflict-resolution`, `decay`, `changes-since`

**Neue Infrastruktur:**
- `hub/_services/usmc_bridge.py` - USMC Bridge fuer Cross-Agent-Kommunikation
- bach:// URL-Resolution in llmauto-Prompts (`hub/url_resolver.py`)
- `tools/migrate_prompts.py` - 3-Quellen-Migration in DB

**Portierungen aus vanilla:**
- SharedMemoryHandler, ApiProberHandler, N8nManagerHandler, UserSyncHandler
- Stigmergy-Service

**Archivierungen:**
- marble_run -> `_archive/marble_run/`
- ATI SessionDaemon -> Ersetzt durch SchedulerService

### 0. Adaptionsfaehigkeit & Self-Extension (Phase 1-3 KOMPLETT, Phase 4 Stufe 2+3 GEPLANT)

**Phase 1: Quick Wins (KOMPLETT)**
- Registry Hot-Reload (`core/registry.py` reload-Methode)
- `bach skills create <name> --type <typ>` (5 Typen: tool, agent, expert, handler, service)
- `bach skills reload` (Hot-Reload ohne Neustart)

**Phase 2: Hook-Framework (KOMPLETT)**
- `core/hooks.py` - HookRegistry mit 14 Events
- `hub/hooks.py` - CLI-Handler (`bach hooks status/events/log/test`)

**Phase 3: Plugin-API (KOMPLETT)**
- `core/plugin_api.py` - PluginRegistry-Singleton
- `hub/plugins.py` - CLI-Handler (`bach plugins list/load/unload/tools/info/create`)

**Phase 4: Sandbox & Security - Stufe 1 Capability System (KOMPLETT)**
- `core/capabilities.py` - CapabilityManager mit 11 definierten Capabilities
- Trust-Level Enforcement: goldstandard/trusted/untrusted/blacklist

**Phase 4: Sandbox - Stufe 2+3 (OFFEN)**
- Stufe 2: Subprocess-Isolation (timeout, memory-limit) — nicht begonnen
- Stufe 3: Container-Isolation (Docker/chroot) — nicht begonnen
- Rollback bei fehlerhaften Erweiterungen

### Weitere abgeschlossene Phasen

| # | Phase | Bereich | Status |
|---|-------|---------|--------|
| 19 | Directory Restructuring v2.5 | agents/, connectors/, partners/ top-level | KOMPLETT |
| 1 | Zeit-System v1.1.83 | clock, timer, countdown, between, beat | KOMPLETT |
| 2 | Workflow-TUeV v1.1.83 | tuev status/check, usecase list/run | KOMPLETT |
| 3 | Memory-Konsolidierung | CONSOL_001-007, Code komplett, Tasks in DB | In Progress |
| 4 | GUI-Erweiterungen Phase 4 | 32 Templates, 16k+ LOC, Scheduler+Chain-Tabs | KOMPLETT |
| 5 | Steuer-Banking Integration | CAMT.053 Parser existiert, Matching offen | PARTIAL |
| 6 | Data-Import-Framework | CSV/JSON Import, Schema-Erkennung | KOMPLETT |
| 7 | CLI-Handler Erweiterungen | contact, gesundheit, haushalt, steuer | KOMPLETT |
| 8 | Connector & Message-System v2.1 | Queue, Retry, Circuit Breaker, 3 Adapter | KOMPLETT |
| 9 | bach.py v2.0 Registry-Architecture | 1636->563 Zeilen, Auto-Discovery | KOMPLETT |
| 10 | MCP-Server v2.2.0 | 23 Tools, 8 Resources, 3 Prompts | KOMPLETT |

### Langfristige Ziele (P4)

**Headless AI-Sessions** — Tasks AI_001-AI_004 (KOMPLETT)
**Filesystem-Schutz** — Tasks FS_001-FS_004, Konzept: `../docs/CONCEPT_filesystem_protection.md`
**DB-Content-Sync** — Task SYNC_004 (in Progress), Konzept: `../docs/CONCEPT_db_content_sync.md`

---

## Abgeschlossene Meilensteine

| Phase | Bereich | Abschluss |
|-------|---------|-----------|
| 1-3 | Autonomie, Funktionalitaet, Dashboard | 2026-01 |
| 4 | Session, Token, GUI, Prompt-Generator | 2026-01 |
| 5 | Integration Services | 2026-01 |
| 6.1-6.2 | Steuer Phase 1-2, Workflows | 2026-01 |
| 8 | Mail-Profil-System | 2026-01 |
| 10 | Dokumenten-Scanner/Inbox | 2026-01 |
| 11 | JSON-zu-DB Migration | 2026-01 |
| 12 | bach.py v2.0 Registry-Architecture | 2026-02 |
| 13 | Connector Runtime + Voice Service | 2026-02 |
| 14 | Message-System Upgrade (Queue, Retry, API) | 2026-02 |
| 15 | MCP-Server v2.2 (23 Tools, 8 Resources, 3 Prompts) | 2026-02 |
| 16 | BachFliege/BachForelle Analyse + Archivierung | 2026-02 |
| 17 | Email-Handler (Gmail API, Draft-Safety) | 2026-02 |
| 18.1 | Self-Extension Quick Wins | 2026-02 |
| 18.2 | Hook-Framework (14->16 Events) | 2026-02 |
| 18.3 | Plugin-API | 2026-02 |
| 18.4 | Capability System Stufe 1 | 2026-02 |
| 19 | Directory Restructuring v2.5 | 2026-02 |
| 20 | BUTTERNUT v3.2.0 | 2026-02 |
| INT01-06 | Softwareprojekt-Integrationen (6 Tools) | 2026-03 |
| B31 | KnowledgeDigest / Wissensindexierung | 2026-03 |
| B35 | Secrets-Management | 2026-03 |
| B38 | Foerderplaner-Extraktion | 2026-03 |
| B40 | Alt-Tests pytest-Portierung | 2026-03 |
| — | BACH Mini (USMC-basiert) | 2026-03 |
| SQ073 | Scheduler-Migration + ChainHandler | 2026-03 |
| SQ074 | marble_run -> llmauto (7 Strategien, 13 Configs) | 2026-03 |
| B27 | UC46 MediaBrain 100% | 2026-03 |
| B28 | GUI: Scheduler-Tab + Chain-Tab | 2026-03 |
| B29 | Inter-Instanz-Messaging | 2026-03 |
| B33 | Stigmergy-API | 2026-03 |
| B34 | USER.md Installer-Integration | 2026-03 |
| B36 | ApiProber Timeout-Fix + Tests | 2026-03 |
| B37 | n8n optionale Installation | 2026-03 |
| SQ036 | Vernunftstests (12/12) | 2026-03 |
| — | ROADMAP-Konsolidierung | 2026-03 |
| — | GitHub PUBLIC + Tags | 2026-03 |
| — | GUI Phase 4 (32 Templates) | 2026-03 |
| SQ043 | Memory-Migration Stufe D | 2026-03 |
| HQ8 | Installer Non-interaktiv | 2026-03 |
| SQ014 | UC26/27 Overpass + OSRM | 2026-03 |
| SQ011 | Pipeline-Framework + Decision-Briefing | 2026-03 |

~165+ Tasks abgeschlossen in Phase 1-20 + Post-Release-Bloecke.

### Abgeschlossene Release-Meilensteine (Strawberry v3.1.6)

| Meilenstein | Version | Status |
|-------------|---------|--------|
| HQ0 DB-Konsolidierung | — | 142 Tabellen |
| HQ1 Dateizuordnung (dist_type) | — | CORE/TEMPLATE/USER |
| HQ2 Distribution-System | — | distribution.py v1.0.0 |
| HQ3 Strawberry Build | v3.1.6 | 669 Dateien, 99.0% pytest |
| HQ4 Integritaet & PII | — | 0 PII-Leaks |
| HQ5 Nutzertest | — | 83.3% EXCELLENT |
| HQ6 Reset/Restore | — | 3 Varianten, 15/15 Tests |
| HQ7 Neuinstallation | — | 3 Varianten definiert & getestet |
| HQ8 Installer-Workflow | — | ENT-45 3D-Modell (Phase 1-2+4) |
| HQ9 GitHub-Vorbereitung | — | 7/7 Go-Kriterien erfuellt |
| SQ027 Testabdeckung | — | 390/391 (99.7%) |
| SQ014 Usecase-Coverage | — | 50/50 (100%), Score 80.0% |

> Vollstaendige Erledigungsliste: `.dev/archive/masterplan/MASTERPLAN_DONE.txt`

---

## Architektur-Uebersicht

```
                        BACH v2.5 GESAMTARCHITEKTUR
  ========================================================================

  USER-INTERFACES
    CLI (bach.py)  |  GUI (gui/server.py)  |  API (headless:8001)  |  MCP
  ========================================================================
                                |
  HUB LAYER (hub/*.py)
    System:    startup, shutdown, status, backup, tokens, inject, scan
    Domain:    steuer, abo, haushalt, gesundheit, contact, calendar, routine
    Data:      task, memory, db, session, logs, wiki, docs, inbox
    AI:        agent (launcher), partner, scheduler, ollama, ati
    Comm:      connector, messages (Queue, Retry, Circuit Breaker)
    Prompts:   prompt (templates, versions, boards) [NEU v3.2]
    Memory:    shared_memory + USMC Bridge [NEU v3.2]
  ========================================================================
              |                     |                      |
  AGENTS LAYER            TOOLS LAYER              DATA LAYER
    agents/ (ATI, 4+)      c_ocr_engine.py          bach.db (Unified DB)
    agents/_experts/ (14)  data_importer.py          prompt_templates [NEU]
    skills/_services/      folder_diff_scanner.py    scheduler_jobs [NEU]
     (daemon, connector,   doc_search.py             Dateisystem
     document, voice,      mcp_server.py             (../user/, memory/,
     mail, market,         migrate_prompts.py [NEU]   logs/, help/)
     stigmergy [NEU])      url_resolver.py [NEU]     Externe Ordner/Inbox
    skills/workflows/
     (.md)
  ========================================================================
              |                                        |
  PARTNER LAYER                             CONNECTOR LAYER
    partners/claude/                          connectors/ (3+)
    partners/gemini/                          Telegram, Discord
    partners/ollama/                          HomeAssistant
    USMC Bridge [NEU]                         (Signal, WhatsApp geplant)
  ========================================================================

  DATENFLUSS:  CLI/GUI/API --> Hub --> Agents/Skills/Tools --> DB/Files/Partners
  PRINZIPIEN:  CLI First | Systemisch | dist_type | Idempotent
```

> Detaillierte Architektur-Diagramme: `../docs/ARCHITECTURE_DIAGRAMS.md`

---

## Konzept-Index

| Bereich | Konzept-Datei |
|---------|---------------|
| Memory-Konsolidierung | `skills/docs/docs/docs/help/consolidation.txt` |
| Strategische Dokumente | `skills/docs/docs/docs/help/strategic.txt` |
| Drei Handler-Systeme | `../docs/CONCEPT_three_handlers.md` |
| DB-Content-Sync | `../docs/CONCEPT_db_content_sync.md` |
| Filesystem-Schutz | `../docs/CONCEPT_filesystem_protection.md` |
| Inbox-Scanner | `../docs/CONCEPT_inbox_folders_format.md` |
| Message-System Upgrade | `../docs/PLAN_MESSAGE_SYSTEM_UPGRADE.md` |
| Systemisch-First | `../docs/WICHTIG_SYSTEMISCH_FIRST.md` |
| Distribution-System | `data/schema_distribution.sql` |
| Architektur-Diagramme | `../docs/ARCHITECTURE_DIAGRAMS.md` |
| Policy-Entscheidungen | `.dev/POLICY.md` (alle 44 ENTs) |

---

## Changelog (komprimiert)

| Version | Datum | Aenderung |
|---------|-------|----------|
| 1.0-1.5 | 2026-01 | Phase 1-3 (Autonomie, Funktionalitaet) |
| 2.0 | 2026-01-24 | Phase 4-11 konsolidiert |
| 2.1 | 2026-01-25 | Erledigte Phasen zusammengefasst |
| 3.0 | 2026-01-25 | Transformation zu strategischem Dokument |
| 3.1 | 2026-01-28 | Systemisch-First Prinzip, Import-Framework, CLI-Handler |
| **3.2** | 2026-01-30 | **Zeit-System (Clock/Timer/Countdown/Between/Beat), Workflow-TUeV** |
| **3.3** | 2026-02-08 | **bach.py v2.0 Registry, Connector Runtime, Message-System v2.0** |
| **3.4** | 2026-02-08 | **MCP v2.2 (23 Tools), Email-Adapter, BachFliege/BachForelle archiviert** |
| **3.5** | 2026-02-13 | **Self-Extension: Skills Create/Reload, Hook-Framework (14 Events), Email-Handler** |
| **3.6** | 2026-02-13 | **Capability System Stufe 1: 11 Caps, Trust-Enforcement, Audit-Log** |
| **3.7** | 2026-02-13 | **Directory Restructuring v2.5** |
| **3.8** | 2026-02-28 | **BUTTERNUT v3.2.0: Scheduler, Prompt-System, USMC Bridge** |
| **4.0** | 2026-03-01 | **Konsolidierung: BACH_Dev/ROADMAP.md + Post-Release-Prios integriert, INT01-06 + B31/B35/B38/B40/BACH Mini als KOMPLETT markiert** |
| **4.1** | 2026-03-01 | **Verifizierung: Alle Items gegen Code geprueft. SQ073/074/036/051/075/080/081 + B27-29/33-34/36-37 als KOMPLETT. GitHub PUBLIC. GUI Phase 4 KOMPLETT.** |
| **4.2** | 2026-03-02 | **Prio 1-3 erledigt: SQ043 Memory-Migration (2046+1120 Datensaetze), HQ8 Installer (full-install+preflight), SQ014 UC26/27 (Overpass+OSRM), SQ011 Pipeline-Framework (DB+Scanner+Definitionen). Nur noch Prio 4 offen.** |
| **4.3** | 2026-04-30 | **Security-/Plugin-Härtung aus OpenClaw-Abgleich: Scanner, MCP-Allowlist, API-Parität als neuer Fokusblock.** |
| **4.3.1** | 2026-05-01 | **OpenClaw `2026.4.29` abgeglichen; SEC-PLUGIN-001 Stufe 1 mit Quarantäne-Reports abgeschlossen; OPS-RUN-001 und MEM-PROV-001 ergänzt.** |
| **4.3.2** | 2026-05-06 | **OpenClaw `2026.5.4` gegengeprüft; SEC-PLUGIN-003 mit fail-closed Setup-Guards für Shell/Desktop/MCP in Plugin-Manifests plus bestehende Claude-Config-Validierung abgeschlossen; `bach_api` für Editable-Install/Root-Import nachgezogen.** |
| **4.3.3** | 2026-05-07 | **Usecase-Runner gegen Kategorie-/Pfad-Luecken gehaertet (`bach usecase run` faellt bei fehlender Workflow-Datei nicht mehr hart aus); Release-Planungsreferenzen auf `.dev/` korrigiert; OpenClaw-Abgleich auf `2026.5.5` aktualisiert.** |
| **4.3.4** | 2026-05-07 | **Registry-Watcher auf aktuelles Skills-/Tools-Layout und Startup-Selbstcheck ausgerichtet: rekursive Layout-Scans, Trennung von actionable vs. stale/historical Eintraegen und keine False-Positive-Warnung mehr bei sauberem Core-Bestand.** |
| **4.3.5** | 2026-05-07 | **Agent-Start loest Experten-Display-Names jetzt auch dann korrekt ueber `skill_path` auf, wenn DB-Name und Skill-Verzeichnis abweichen (`Theodor` -> `steuer`); Release-/QA-Notizen an den verifizierten Stand angepasst.** |
| **4.3.6** | 2026-05-08 | **`bach --maintain docs report` wieder funktionsfähig gemacht (Subcommand-Passthrough statt hartem `check`-Prefix), Regressionstest ergänzt und OpenClaw-Abgleich auf `2026.5.7` nachgezogen.** |
| **4.3.7** | 2026-05-08 | **MEM-PROV-001 abgeschlossen: `bach memory provenance` und `bach wiki provenance` liefern heuristische Quellen-/Privacy-Sichten; Task `#1119` geschlossen sowie CLI-Hilfe und Regressionstests ergänzt.** |
| **4.3.8** | 2026-05-09 | **Daily-Care-Verifikation und Control-Plane-Nachzug: strukturierte `bach_api`-/Provenance-Smokes gegen die Live-Instanz bestätigt, generischer CLI-Dispatch reicht `--dry-run` wieder korrekt an Handler weiter (`bach agent ... --dry-run`) und Agent-/Scheduler-Statusflächen liefern jetzt sauberes JSON (`bach agent ... --json`, `bach scheduler ... --json`).** |
| **4.3.9** | 2026-05-10 | **ATI-Scanner erweitert; Agent-Runtime-Caches jetzt pro `base_path` gescoped und bei Code-/Config-Änderungen invalidiert; `--json`-Ausgaben bleiben trotz ProSync sauber; `bach_api` nutzt für strukturierte Memory-Schreibpfade denselben kanonischen DB-Pfad wie die Reader; `bach seal status` funktioniert wieder; OpenClaw-Referenzstand auf GitHub Releases `2026.5.6` plus GHCR `2026.5.7-slim` präzisiert.** |

Detaillierte Historie: `CHANGELOG.md`
Archivierte Versionen: `../docs/_archive/ROADMAP_*.md`

---

## Verwandte Dokumente

- **MASTERPLAN (Release-Pipeline):** `.dev/archive/masterplan/MASTERPLAN.txt`
  Beschreibt den Weg von Vanilla -> Strawberry -> GitHub-Veroeffentlichung.
  Enthaelt: 11 Hauptquests, 29 Sidequests, 7 Cluster, Abhaengigkeitskarte.
  Die ROADMAP beschreibt WAS BACH kann, der MASTERPLAN beschreibt WIE wir releasen.

- **NEXT_RELEASE (naechste Tasks):** `.dev/NEXT_RELEASE.md`
  Konkrete Aufgaben fuer das naechste Release.

- **THE_RELEASE_AFTER (verschoben):** `.dev/THE_RELEASE_AFTER.md`
  Items die nicht release-kritisch sind (B30/SQ046, B32/SQ049).

- **POLICY (Entscheidungen):** `.dev/POLICY.md`
  Alle 44 ENT-Entscheidungen.

- **SKILL.md (Einstiegspunkt):** `../../SKILL.md`

---

*Konsolidiert am 2026-03-01 — BACH_Dev/ROADMAP.md und BACH/ROADMAP.md zu einem Dokument zusammengefuehrt*

---

## Persona-System & Skill-Architektur (2026-03-12)

### Phase 1: DB-Personas — KOMPLETT (SUGAR v3.8.0, Migration 034)

Das Persona-System ist seit SUGAR v3.8.0 in der Datenbank implementiert:

**DB-Schema:**
- `bach_agents.display_name` — Persona-Vorname (z.B. "Atlas", "Clara")
- `bach_agents.persona` — Charakter-Beschreibung (z.B. "Pragmatischer Handwerker...")
- `bach_experts.display_name` — Persona-Vorname (z.B. "Theodor", "Sophie")
- `bach_experts.persona` — Charakter-Beschreibung

**20 Default-Personas:**

| Typ | System-Name | Persona | Charakter |
|-----|-------------|---------|-----------|
| Agent | ati | Atlas | Pragmatischer Handwerker |
| Agent | bueroassistent | Clara | Strukturierte Organisatorin |
| Agent | finanz-assistent | Felix | Aufmerksamer Sparfuchs |
| Agent | gesundheitsassistent | Helena | Fuersorgliche Begleiterin |
| Agent | persoenlicher-assistent | Paul | Vielseitiger Allrounder |
| Expert | steuer-agent | Theodor | Peniler Steuerberater |
| Expert | financial_mail | Frieda | Mail-Detektivin |
| Expert | aboservice | Anton | Kuendigungskoenig |
| Expert | gesundheitsverwalter | Gustav | Archivar der Befunde |
| Expert | psycho-berater | Sophie | Einfuehlsame Zuhoererin |
| Expert | health_import | Hugo | Gewissenhafter Datenpfleger |
| Expert | haushaltsmanagement | Martha | Sparsame Hauswirtschafterin |
| Expert | foerderplaner | Florian | Foerdermittel-Experte |
| Expert | bewerbungsexperte | Benjamin | Karriere-Coach |
| Expert | data-analysis | Diana | Zahlenfluesterin |
| Expert | decision-briefing | Dietrich | Kuehler Stratege |
| Expert | report_generator | Rita | Effiziente Berichtsmaschine |
| Expert | mr_tiktak | Mr. TikTak | Strategischer Taktiker |
| Expert | transkriptions-service | Tristan | Geduldiger Zuhoerer |
| Expert | wikiquizzer | Wilhelm | Quizmaster |

**Implementierte Features:**
- `bach agent rename <name> <neuer-display-name>` — Display-Name aendern
- Multi-Strategie Namensaufloesung in `resolve_agent_name()`:
  Exakter Name → Display-Name → Substring → Fuzzy/Levenshtein
- Persona-Injektion in Agent-System-Prompt bei Start (`agent_launcher.py`)
- Display-Name-Anzeige in `bach agent list` (in Klammern)

### Phase 2: Konzeptionelle Weiterentwicklung — OFFEN

#### Kernidee: Drei getrennte Konzepte

```
PERSONA (wer)          SKILL (was)              SESSION (wie)
  Charakter + Stil       Faehigkeiten + Code      Laufzeitumgebung
  display_name + persona SKILL.md + scripts/      Context, Tools, Turns
```

**Persona:** Benannter Charakter mit Persoenlichkeit, Stil, Ethik-Grenzen.
Definiert WER die Arbeit macht und WIE kommuniziert wird.
Aktuell in DB-Spalten (`display_name`, `persona`), kuenftig auch als Dateien.

**Skill:** Faehigkeit mit Instruktionen, Code, Referenzen.
Definiert WAS getan werden kann. Standalone, exportierbar, portierbar (Anthropic-Standard).

**Session/Agent:** Laufzeitumgebung mit Context Window, Tool-Zugriff, Turn-Limit.
Definiert unter WELCHEN BEDINGUNGEN gearbeitet wird.

#### Geplante Dateistruktur (schrittweise Migration)

```
agents/
  personas/              # NEU: Eigenstaendige Persona-Dateien
    THEODOR.md           # Steuerberater-Persona (aus DB extrahiert)
    SOPHIE.md            # Psychologin-Persona
    TIKTAK.md            # Stratege-Persona

skills/
  steuererklaerung/      # Faehigkeit als eigenstaendiger Skill
    SKILL.md             # Anthropic-kompatibel
    scripts/             # beleg_extractor.py, steuer_sync.py...
    references/          # Workflows, Anleitungen
```

#### Interaktionsmodelle

```
# Direkt: Skill ohne Persona (schnell, sachlich)
User: "Mach die Steuererklaerung"
-> Skill STEUERERKLAERUNG wird geladen, LLM fuehrt aus

# Mit Persona: Skill + Charakter (persoenlich, stilsicher)
User: "Frag Theodor wegen der Steuer"
-> Persona Theodor (DB) + Skill wird geladen

# Session: Langfristige Arbeit (eigener Context)
User: "Starte eine Steuersession mit Theodor"
-> Agent-Session + Persona-Injektion + Skill
```

#### Kompatibilitaet mit Anthropic

| BACH-Konzept | Anthropic-Aequivalent | Portierbar? |
|-------------|----------------------|-------------|
| Persona (DB/Datei) | `.claude/agents/<name>.md` | Nein (proprietaer) |
| Skill (SKILL.md) | `.claude/skills/<name>/SKILL.md` | Ja (offener Standard) |
| Session-Config | Agent-Frontmatter (tools, model, maxTurns) | Nein (proprietaer) |

Skills sind das einzige portierbare Element. Personas und Sessions sind
BACH-/Claude-Code-spezifisch -- aber das ist akzeptabel, da sie die
Laufzeitumgebung definieren, nicht das Wissen.

#### Offene Fragen (Phase 2+)

- Persona-Dateien (agents/personas/) vs. DB-only: Braucht es beides?
- Sollen Personas eigenstaendige Skills referenzieren oder nur bestehende Expert-Ordner nutzen?
- Boss-Agent-Rolle: Entfaellt langfristig oder bleibt als interner Router?
- Wie interagieren mehrere Personas in einer Session?
- Migration: Schrittweise (bei Nutzung konvertieren) — User entscheidet Tempo

#### Naechste Schritte

| Prio | Aktion | Status |
|------|--------|--------|
| 1 | DB-Personas fuer alle Agenten/Experten | KOMPLETT (Migration 034) |
| 2 | Persona-Template erstellen (TEMPLATE_PERSONA.md) | KOMPLETT |
| 3 | Standard: Jeder Expert MUSS SKILL.md haben | KOMPLETT (22/22 Experts, 2026-03-12) |
| 4 | Persona-Dateien aus DB generieren (agents/personas/) | KOMPLETT (20 Dateien, 2026-03-12) |
| 5 | Proof-of-Concept: 1 Expert -> Persona + Skill konvertieren | KOMPLETT (Steuer/Theodor, 2026-03-12) |
| 6 | Export-Pipeline: `--format agent` fuer Claude Code Agents | Offen |
| 7 | Boss-Agent-Rolle evaluieren (benoetigt? Router-Ersatz?) | Offen |

### Referenzen

- Migration 034: `data/schema/migrations/034_agent_personas.py`
- Agent-Launcher mit Persona-Injektion: `hub/agent_launcher.py`
- Namensaufloesung: `hub/agents.py` (`resolve_agent_name()`)
- Anthropic Skills Standard: https://agentskills.io
- Persona-Template: `skills/_templates/TEMPLATE_PERSONA.md`
- Help: `bach help skill_standards`, `bach help agents`

---

## Safe DB Access Layer — bach_api.db (2026-03-12)

> Status: KOMPLETT — core/safe_db.py + bach_api.db (2026-03-12)

### Problem

LLMs bevorzugen direkten DB-Zugriff (schnell, flexibel), aber direktes SQL
hat keine Validierung, keine Hooks, kein Audit-Log. Einmal gab es dadurch
Schaeden. Die bestehende bach_api (Handler) ist sicher, aber umstaendlich --
man muss Handler, Operation und Args kennen.

### Loesung: Validierte Schnellspur

Ein neues API-Modul `bach_api.db` das sich wie SQL anfuehlt, aber sicher ist:

```python
from bach_api import db

db.update("bach_experts", {"persona": "Neuer Text"}, where={"name": "mr_tiktak"})
db.insert("tasks", {"title": "Aufgabe", "priority": "high"})
db.delete("tasks", where={"id": 42})
db.select("bach_agents", where={"language": "de"})  # Read bleibt frei
```

### Sicherheitsschichten

1. **Tabellen-Whitelist** — nur bekannte BACH-Tabellen erlaubt
2. **Schema-Validierung** — Spalten gegen `PRAGMA table_info` pruefen
3. **Auto-Backup** — bei kritischen Tabellen (tasks, memory) vorher Snapshot
4. **Hook-Trigger** — `after_memory_write`, `after_task_create` etc. feuern
5. **Audit-Log** — wer (Partner), wann, was geaendert (monitor_* Tabelle)
6. **WHERE-Pflicht** — UPDATE/DELETE ohne WHERE wird geblockt

### Zugriffsebenen (von schnell zu sicher)

| Zugriff | Speed | Sicherheit | Wann |
|---------|-------|------------|------|
| `db.update(...)` | Schnell | Validiert + geloggt | **Standard fuer LLMs** |
| `task.add(...)` | Mittel | Voll (Handler-Logik) | Komplexe Operationen |
| `sqlite3.connect()` | Sofort | Keine | Nur Dev-Mode |
| `bach task add` (CLI) | Langsam | Voll | Menschen am Terminal |

### Implementierung

| Schritt | Beschreibung | Aufwand |
|---------|-------------|---------|
| 1 | `core/safe_db.py` — SafeDB-Klasse mit Whitelist + Schema-Check | KOMPLETT |
| 2 | `bach_api.db` — Modul-Wrapper fuer SafeDB | KOMPLETT |
| 3 | Hook-Integration — Events bei Schreibzugriffen ausloesen | KOMPLETT |
| 4 | Audit-Log — Aenderungen in `monitor_db_changes` loggen | KOMPLETT |
| 5 | Hook-Prompt anpassen — Empfehlung `bach_api.db` statt Block | Offen |

---

## Claude Code Hooks Distribution (2026-03-12)

> Status: PHASE 1 KOMPLETT — `bach setup hooks` implementiert

### Problem

BACH nutzt Claude Code Hooks (z.B. DB-Schutz-Hook in `PreToolUse:Bash`) fuer
Sicherheit und Workflow-Steuerung. Diese Hooks liegen in `~/.claude/settings.json`
und sind damit **lokal pro User** — sie werden NICHT mit dem Repo ausgeliefert.

Claude Code erlaubt keine Hooks in projektspezifischen `.claude/settings.json`
(nur `permissions`, `model` etc.) — das ist eine Sicherheitsentscheidung von Anthropic.

### Frage

Sollen bestimmte Hooks als Teil der BACH-Installation mitgeliefert werden?

### Optionen

| Option | Beschreibung | Pro | Contra |
|--------|-------------|-----|--------|
| A | Installer kopiert Hooks bei `bach install` | Automatisch, einheitlich | Greift in User-Settings ein |
| B | `bach hooks setup` als optionaler Befehl | User entscheidet | Muss aktiv aufgerufen werden |
| C | Hooks nur dokumentieren (Help) | Kein Eingriff | Jeder muss manuell einrichten |
| D | Hooks als Teil von SKILL.md mitliefern | Portabel | Anthropic unterstuetzt das (noch) nicht |

### Kandidaten fuer Distribution

| Hook | Typ | Zweck |
|------|-----|-------|
| bach-db-guard.sh | PreToolUse:Bash | Verhindert direkte DB-Schreibzugriffe ohne API |
| (geplant) | SessionStart | BACH-Startup bei Session-Beginn |
| (geplant) | PreToolUse:Edit | Schutz fuer BACH-Core-Dateien |

### Implementiert: Option B

`bach setup hooks` installiert empfohlene Hooks in die User-Settings:
- Kopiert Hook-Scripts aus `system/hooks/` nach `~/.claude/hooks/`
- Merged Hook-Config in `~/.claude/settings.json` (nicht-destruktiv)
- Ist Teil von `bach setup full-install`
- Erkennt bereits vorhandene Hooks und ueberspringt sie

### Offen

- ~~`bach hooks remove` — Hooks wieder entfernen (reversibel)~~ KOMPLETT (2026-03-12)
- Weitere Hooks (SessionStart, PreToolUse:Edit) bei Bedarf

### Referenzen

- Hook-Quellen im Repo: `system/hooks/bach-db-guard.sh`
- Installer: `hub/setup.py` (`_setup_hooks`, `CLAUDE_HOOKS`, `HOOK_FILES`)
- Claude Code Hooks-Doku: Settings > hooks
- BACH Hook-Framework (intern): `core/hooks.py`, `hub/hooks.py`
