# BACH — Features, Skills & Usecases

> Übersicht erstellt aus dem BACH-Boot (Session-Startup) und allen 280 deutschen Help-Dateien in `docs/help/` (186 Top-Level + 94 Tools). Stand: 2026-06-22.

**BACH** = portables, lokales **„Agentic Operating System"** für LLM-Partner (Claude, Gemini, GPT, Kimi, Ollama). Aufgebaut auf einem Schichten-Modell: **Core → Orchestration → Memory → Domain-Agenten → UI**, registry-basierte CLI-Auto-Discovery, SQLite-First (`bach.db`) statt JSON.

---

## 1. Kognitives Gedächtnis (Memory-System)

| Bereich | Funktion |
|---|---|
| **memory** | 5-Ebenen-Modell: Working, Episodisch, Semantisch, Prozedural, Assoziativ — mit Konfidenz-System |
| **mem** | Working-Memory-Cleanup, Memory-Decay für Facts/Lessons, Expires-Verwaltung |
| **shared_memory** | Multi-Agenten-Speicher mit Visibility-Levels und Decay-Tracking |
| **consolidation** | Verdichtung von Sessions/Rohdaten zu strukturiertem Kontext (Decay, Boost, Trigger) |
| **context** | Suche über Memory-Archive, Chat-Historien, System-Dateien |
| **snapshot** | Session-„State-of-Mind" sichern und wiederherstellen |
| **sources** | Registry für Wissensquellen mit dynamischen Triggern + Auto-Injektion |
| **lessons / lesson** | Lessons-Learned-Management (900+ Trigger, Kategorien, Severity) |
| **lernen** | Lern-Theorie: Speichern → Konsolidierung → Verhaltens-Rückfluss |

## 2. Multi-Partner-Delegation & LLM-Koordination

| Bereich | Funktion |
|---|---|
| **partner / partners** | Federated-Intelligence-System; Koordination KIs↔Mensch nach Token-Ökonomie |
| **delegate** | Aufgabenverteilung im Netzwerk nach Expertise + Token-Budget |
| **multi_llm / multi_llm_protocol** | Protokoll V3: Presence, Locking, Handshake, Backup, DB-Stempelkarten für parallele Agenten |
| **schwarm** | 5 Koordinationsmuster (Parallel-Chunks, Hierarchy, Stigmergy, Consensus, Specialist) |
| **token_monitor** | Zone-basiertes Delegations-Routing (Zone 1–4) zu Cloud-Partnern |
| **communicate / messages** | DB-basiertes Nachrichtensystem (Inbox/Outbox, Multi-Partner, REST-API) |
| **integration / partner_config_manager** | LLM-Partner-Eintragung via CLAUDE.md/GEMINI.md-Blöcke |
| **llm-kommunikation** | Katalog aller 21 LLM-Kommunikationsmethoden + Vergleichsmatrix |

## 3. Agenten-Framework

| Bereich | Funktion |
|---|---|
| **agents / agent** | Hierarchie aus Boss-Agenten + Experten (Persona-Schicht + Skills als Substanz) |
| **agent_launcher / agent_cli** | Lifecycle: Start/Stop, Modell-/Modus-Parametrisierung, PID-Tracking |
| **agent_framework / agent_service_integration** | Framework + Service-Anbindung externer Tools |
| **daily_agent** | Persistenter Claude-Agent mit täglicher Task-Queue + Briefings |
| **entwickler_agent** | Software-Dev-Agent (Code-Analyse, -Generierung, Debugging, Phase 1–6) |
| **production_agent** | Content-Produktion (Musik, Podcast, Video, Text) |
| **research_agent / research** | Wissenschaftliche Recherche (PubMed, Perplexity, Consensus, NotebookLM, Elicit) |
| **ollama_worker / watcher** | Hintergrund-Worker (Ollama-Jobs) + Mistral-Always-On-Daemon mit Eskalation zu Claude |
| **success_tracker** | Erfolgsmetriken für 6 Akteur-Kategorien |

## 4. Skills, Tools & Self-Extension

| Bereich | Funktion |
|---|---|
| **skills / skill_standards** | Modulares Skill-System v2.0, Anthropic-kompatibel (Progressive Disclosure), DB-Sync |
| **self_extension** | Selbst-erweiterndes System mit Hot-Reload für Skills/Tools/Handler/Workflows |
| **builder / structure_generator** | Skill-/Agent-Erstellung im Spektrum Micro → Standard → Agent_Full |
| **plugins** | Laufzeit-Erweiterung (Tool-, Hook-, Workflow-, Handler-Registrierung) + Capability-Sandbox |
| **tools** | Verwaltung 83+ Python-/CLI-/KI-Tools mit Discovery + Naming-Konvention |
| **tool_discovery / tool_scanner / tool_registry_boot** | Problem→Tool-Empfehlung, System-Tool-Inventar, Boot-Integration |
| **hooks** | Event-System mit 17 Lifecycle-Events (before/after startup, command, task, memory, skill) |
| **injectors / inject** | 5 kognitive Injektoren (Strategy, Context, Time, Between, Tool) mit Cooldown |
| **reminder_injector / meta_feedback_injector** | Trigger-basierte Erinnerungen + Auto-Erkennung von LLM-Ticks mit Korrektur-Feedback |

## 5. Code- & Datei-Werkzeuge (`c_*`-Toolchain)

- **Reparatur:** `c_encoding_fixer`, `c_umlaut_fixer`, `c_json_repair`/`json_fixer`, `c_standard_fixer` (BOM/Encoding/Umlaute), `c_indent_checker`, `path_healer`
- **Analyse:** `c_method_analyzer`, `c_import_diagnose`, `c_german_scanner`, `c_emoji_scanner`, `duplicate_detector`
- **Editieren:** `python_cli_editor`, `c_pycutter` (Klassen-Zerlegung), `c_import_organizer` (PEP8)
- **Konvertieren:** `c_md_to_pdf`/`converters` (Dual-Engine MD→PDF), `c_universal_converter` (JSON/YAML/TOML/XML/TOON), `ocr`/`ocr_engine` (Tesseract)
- **Build/Dist:** `universal_compiler` (PyInstaller→EXE), `installer_exe`, `c_license_generator`, `c_audit_bundler`
- **Policies:** `policies`/`policy_applier`/`policy_control` (Code-Standards-Injection + Compliance)

## 6. Tasks, Workflows & Scheduling

| Bereich | Funktion |
|---|---|
| **task / tasks** | Aufgaben mit Priorität, Status, Abhängigkeiten, Multi-Partner-Zuweisung, LIBRARY-API |
| **workflow / workflow-tuev** | 22 Workflows (welcher Skill in welcher Reihenfolge) + QS mit Benotung |
| **chain / llmauto** | Toolchains + LLM-Agenten-Ketten (MarbleRun-Engine: sequenziell/parallel/konditional) |
| **scheduler / daemon / wartung** | Hintergrund-Jobs (5 Typen), Global-Pause/Resume, automatische Wartung |
| **recurring / routine** | Wiederkehrende Tasks + Haushaltsroutinen (täglich–jährlich) |
| **pipeline** | Datenverarbeitungs-Pipelines via JSON-Definition, zeitgesteuert |
| **planning / dev** | Task-Zerlegung + 8-Phasen-Entwicklungszyklus |
| **time / clock / timer / countdown / between / beat** | Vereintes Zeitsystem + „Zwischen-Tasks"-Erinnerungen mit Profilen |

## 7. Domain-Skills (Lebensbereiche / Alltag)

| Skill | Usecase |
|---|---|
| **gesundheit / mediplaner** | Diagnosen, Medikamente, Laborwerte, Arztkontakte, Vorsorge (+ neutrales Export-Format) |
| **haushalt / routine** | Routinen, Inventar-Ampel, Einkaufslisten, Lieferanten, Kostenplanung |
| **steuer / abo / versicherung** | Werbungskosten + Finanzamt-Export, Abo-Erkennung, Policen mit Fristen/Kündigung |
| **bericht / foerderbericht / foerderplaner_cli** | ICF-basierte Förderberichte mit Anonymisierung + RAG-Quellen |
| **contact** | Kontakte (privat/geschäftlich) mit Suche + Geburtstags-Übersicht |
| **calendar / obsidian** | Termine (Today/Week/Month) + Obsidian-Vault-Sync |
| **media / news / newspaper** | Medienbibliothek + News-Aggregation (RSS/Web/YouTube) + tägliche PDF-Zeitung |
| **cv** | Lebenslauf-Generierung aus DB |
| **literatur** | 5 Zitationsstile, BibTeX-Export |
| **smarthome / clutch** | FritzBox (TR-064) + agentische Fahrassistenz (Fahrtenbuch, Bordcomputer-Health) |
| **press / rhetorik / denkarium / denkstrategien** | Pressemitteilungen (LaTeX→PDF), Rhetorik-/Denk-Operatoren, Logbuch |

## 8. Externe Anbindungen & Kommunikation

- **connections / connector** — Registry für Connectors, AI-Partner, MCP-Server, APIs (Telegram, Discord, HomeAssistant; Polling, Queue, Circuit Breaker)
- **bach_chat / claude_bridge** — Telegram-Bot + Control-API mit pluggbaren LLM-Backends, System-Tray
- **notify** — Multi-Channel (Discord, Signal, Email, Telegram, Webhook, Slack)
- **email** — Gmail-API mit Draft-Sicherheit
- **apibook / api_prober** — API-Registry + automatisches Endpoint-Abtasten
- **mcp / n8n_manager** — MCP-Server-Bundling (CodeCommander, FileCommander) + n8n-Workflows
- **ollama / gemini_start / antigravity** — Lokale LLM-Integration, Gemini-CLI/Antigravity-Start
- **web_parse / web_scrape / rag / docs_search / search / wiki** — Web→Markdown, Selenium-Scraping, Vektor-RAG, FTS5-Volltextsuche

## 9. System, Integrität & Distribution

- **distribution / dist / backup / backup_manager** — 4-Tier-Modell (KERNEL/CORE/EXTENSION/UserData), Snapshots, NAS-Backups
- **seal / identity / fs** — SHA256-CORE-Integrität, Siegel-Mechanismus, Filesystem-Selbstheilung
- **update / upgrade / downgrade / restore / migrate** — Versionierung mit Rollback, evolutionäre Datei-Migration
- **secrets / secrets_handler** — API-Keys/Tokens im OS-Schlüsselbund; SQLite und JSON enthalten nur Metadaten
- **bach_paths / path / mount / bach_user_mounts** — zentrale Pfad-Registry (Single Source of Truth) + Junctions/Symlinks für NAS/Cloud
- **db / db_sync / sync** — SQLite-Operationen + Multi-System-Sync (ProSync) über OneDrive-Hub
- **claude_permissions / permissions / sandbox / emoji** — Permission-Profile, isolierte Code-Ausführung, Emoji-Policy
- **startup / shutdown / session / status / health / monitoring / selfcheck** — Session-Lifecycle + System-Health
- **modes** — 4 Startup-Modi: GUI, Text, Dual, Silent
- **gui** — Web-Dashboard (FastAPI, Ports 8000/8001) mit REST-APIs
- **tokens / reflection / tuev** — Token-/Kosten-Analyse (EUR), Selbstreflexion, QS mit 90-Tage-Validität

---

## Kern-Usecases (typische End-to-End-Abläufe)

1. **Session führen** — `startup` (Kontext der letzten Session + Snapshot) → arbeiten → `shutdown` (Bericht + Directory-State)
2. **Aufgabe an günstigsten Partner delegieren** — Token-Zone prüfen → `delegate`/`schwarm` → Ergebnis ins `messages`-System
3. **Steuer/Finanzen** — Belege per `ocr` → `steuer`/`abo`/`versicherung` erfassen → `export_txt`/Finanzamt-Export
4. **Förderbericht** — ICF-Struktur (`foerderplaner_cli`) → anonymisieren → `bericht` generieren → de-anonymisieren
5. **Code-Hygiene** — `c_standard_fixer`/`c_import_diagnose` → `bugfix`-Protokoll → `sandbox`-Test → `tuev`
6. **Wissen aufbauen** — `rag`/`doc` indizieren → `search`/`docs_search` → `consolidation` ins Memory
7. **Automatisierung** — `chain`/`llmauto` (MarbleRun) + `scheduler`/`recurring` für autonome Läufe
8. **Tägliche Routine** — `daily_agent` Task-Queue + `newspaper` PDF-Zeitung + `routine`/`haushalt`-Fälligkeiten

---

*Quelle: BACH-Boot + `docs/help/*.txt` (deutsche Sprachvariante), automatisiert ausgewertet über parallele Lese-Agenten.*
