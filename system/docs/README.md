# BACH Dokumentation

Zentrale Dokumentationsreferenz für User und LLMs.
Alle Hilfe-Artikel sind über CLI abrufbar:

```bash
bach help <thema>              # Handler & Konzepte
bach help tools/<name>         # Tool-Dokumentation
bach help agent/<name>         # Agent-Skill anzeigen
bach help expert/<name>        # Experten-Skill anzeigen
bach help workflow/<name>      # Workflow anzeigen
```

```python
from bach_api import help
help.run("<thema>")            # Programmatischer Zugriff
```

---

## Verzeichnisstruktur

```
docs/
├── README.md                  ← Diese Datei
├── docs/help/                      ← CLI-Referenz (bach help <thema>)
│   ├── *.txt                  ← Handler- & Konzept-Artikel (~110 Stück)
│   └── tools/                 ← Tool-spezifische Artikel (~80 Stück)
│       └── _index.txt         ← Tool-Index
└── *.md                       ← Entwickler-Dokumentation, Konzepte
```

---

## Help-Artikel nach Kategorie

### Einstieg & System

| Thema | CLI-Befehl | Beschreibung |
|-------|-----------|--------------|
| architecture | `bach help architecture` | Gesamtarchitektur, Verzeichnisstruktur |
| bach_info | `bach help bach_info` | Was ist BACH, Überblick |
| cli | `bach help cli` | CLI-Konventionen, alle Subcommands |
| features | `bach help features` | Feature-Matrix |
| guidelines | `bach help guidelines` | Entwicklungsrichtlinien |
| naming | `bach help naming` | Namenskonventionen |
| help | `bach help help` | Das Hilfe-System selbst |

### Session & Lifecycle

| Thema | CLI-Befehl | Beschreibung |
|-------|-----------|--------------|
| startup | `bach help startup` | Startprozedur |
| shutdown | `bach help shutdown` | Shutdown-Protokoll |
| session | `bach help session` | Session-Management |
| modes | `bach help modes` | Betriebsmodi (Silent, Watch, etc.) |
| hooks | `bach help hooks` | Event-Hooks |

### Task-System

| Thema | CLI-Befehl | Beschreibung |
|-------|-----------|--------------|
| tasks | `bach help tasks` | Task-Verwaltung (add, list, done) |
| task | `bach help task` | Task-Handler Referenz |
| planning | `bach help planning` | Aufgabenplanung |
| between-tasks | `bach help between-tasks` | Qualitätschecks zwischen Tasks |
| workflow | `bach help workflow` | Workflow-System |
| workflow-tuev | `bach help workflow-tuev` | Workflow-Validierung |

### Memory & Wissen

| Thema | CLI-Befehl | Beschreibung |
|-------|-----------|--------------|
| memory | `bach help memory` | Memory-System (5 Typen) |
| mem | `bach help mem` | Working Memory Handler |
| lessons | `bach help lessons` | Lessons Learned |
| lesson | `bach help lesson` | Lesson Handler |
| consolidation | `bach help consolidation` | Memory-Konsolidierung |
| sources | `bach help sources` | Quellenmanagement |
| shared_memory | `bach help shared_memory` | Geteiltes Memory |
| denkarium | `bach help denkarium` | Reflexions-Tagebuch |

### Agenten & Multi-LLM

| Thema | CLI-Befehl | Beschreibung |
|-------|-----------|--------------|
| agents | `bach help agents` | Agenten-System |
| agent | `bach help agent` | Agent Handler |
| agent_launcher | `bach help agent_launcher` | Agent-Prozess-Launcher |
| actors | `bach help actors` | Rollen & Akteure |
| partners | `bach help partners` | Partner-Netzwerk |
| partner_config_manager | `bach help partner_config_manager` | Partner-Konfiguration |
| multi_llm | `bach help multi_llm` | Multi-LLM Architektur |
| multi_llm_protocol | `bach help multi_llm_protocol` | LLM-Kommunikationsprotokoll |
| delegate | `bach help delegate` | Task-Delegation |
| communicate | `bach help communicate` | Kommunikationssystem |
| claude_bridge | `bach help claude_bridge` | Claude Code Integration |

### Handler (Domain)

| Thema | CLI-Befehl | Beschreibung |
|-------|-----------|--------------|
| steuer | `bach help steuer` | Steuer-Experte |
| abo | `bach help abo` | Abo-Service |
| bericht | `bach help bericht` | Bericht-Generator |
| gesundheit | `bach help gesundheit` | Gesundheits-Assistent |
| health | `bach help health` | Health-Checks |
| haushalt | `bach help haushalt` | Haushalts-Management |
| versicherung | `bach help versicherung` | Versicherungs-Management |
| calendar | `bach help calendar` | Kalender |
| calendar_handler | `bach help calendar_handler` | Kalender-Handler Referenz |
| contact | `bach help contact` | Kontaktverwaltung |
| cv | `bach help cv` | Lebenslauf-Generator |
| literatur | `bach help literatur` | Literaturverwaltung |
| news | `bach help news` | Nachrichten-Aggregator |
| newspaper | `bach help newspaper` | Zeitungs-Generator |
| press | `bach help press` | Pressespiegel |

### Handler (System & Infrastruktur)

| Thema | CLI-Befehl | Beschreibung |
|-------|-----------|--------------|
| backup | `bach help backup` | Backup-System |
| db | `bach help db` | Datenbank-Handler |
| db_sync | `bach help db_sync` | DB-Synchronisation |
| dist | `bach help dist` | Distribution-System |
| doc | `bach help doc` | Dokumentations-Handler |
| docs_search | `bach help docs_search` | Dokumentationssuche |
| email | `bach help email` | E-Mail Handler |
| extensions | `bach help extensions` | Extension-System |
| folders | `bach help folders` | Ordner-Handler |
| fs | `bach help fs` | Dateisystem-Handler |
| inject | `bach help inject` | Injektor-Handler |
| integration | `bach help integration` | Integrations-Handler |
| lang | `bach help lang` | Sprach-Handler |
| logs | `bach help logs` | Log-System |
| media | `bach help media` | Medien-Handler |
| mount | `bach help mount` | Mount-System |
| n8n_manager | `bach help n8n_manager` | n8n Workflow-Manager |
| notify | `bach help notify` | Benachrichtigungen |
| obsidian | `bach help obsidian` | Obsidian-Integration |
| path | `bach help path` | Pfad-Handler |
| pipeline | `bach help pipeline` | Pipeline-System |
| profile | `bach help profile` | Profil-Handler |
| profiler | `bach help profiler` | Performance-Profiler |
| reflection | `bach help reflection` | Selbstreflexion |
| sandbox | `bach help sandbox` | Sandbox-Umgebung |
| scan | `bach help scan` | Input-Scanner |
| search | `bach help search` | Such-Handler |
| secrets | `bach help secrets` | Secrets-Management |
| settings | `bach help settings` | Einstellungen |
| setup | `bach help setup` | Setup-Handler |
| smarthome | `bach help smarthome` | Smart-Home Integration |
| status | `bach help status` | System-Status |
| sync | `bach help sync` | Dateisystem-DB Sync |
| tokens | `bach help tokens` | Token-Tracking |
| update | `bach help update` | Update-System |
| user_sync | `bach help user_sync` | User-Synchronisation |
| wiki | `bach help wiki` | Wiki-Handler |

### Handler (Web)

| Thema | CLI-Befehl | Beschreibung |
|-------|-----------|--------------|
| web_parse | `bach help web_parse` | HTML-zu-Markdown Parser |
| web_scrape | `bach help web_scrape` | Web-Scraping & Screenshots |
| api_prober | `bach help api_prober` | API-Dokumentation & Tests |
| apibook | `bach help apibook` | API-Verzeichnis |

### Handler (Zeit)

| Thema | CLI-Befehl | Beschreibung |
|-------|-----------|--------------|
| time | `bach help time` | Zeit-System (Übersicht) |
| clock | `bach help clock` | Uhrzeit-Anzeige |
| timer | `bach help timer` | Timer-Modul |
| countdown | `bach help countdown` | Countdown-Modul |
| between | `bach help between` | Between-Checks |
| beat | `bach help beat` | Alle Zeit-Infos |
| daily_agent | `bach help daily_agent` | Täglicher Agent |

### Skills & Tools

| Thema | CLI-Befehl | Beschreibung |
|-------|-----------|--------------|
| skills | `bach help skills` | Skill-System |
| tools | `bach help tools` | Tool-Übersicht (Gesamtliste) |
| builder | `bach help builder` | Skill/Agent Erstellung & Export |
| exports | `bach help exports` | DB-zu-Markdown Export-Scripts |
| coding | `bach help coding` | Coding-Konventionen |
| bugfix | `bach help bugfix` | Bugfix-Workflow |

### Wartung & Betrieb

| Thema | CLI-Befehl | Beschreibung |
|-------|-----------|--------------|
| maintain | `bach help maintain` | Wartungs-Handler |
| wartung | `bach help wartung` | Wartungs-Übersicht |
| recurring | `bach help recurring` | Wiederkehrende Aufgaben |
| selfcheck | `bach help selfcheck` | Selbstdiagnose |
| tuev | `bach help tuev` | System-TUEV |
| daemon | `bach help daemon` | Scheduler/Daemon |
| scheduler | `bach help scheduler` | Hintergrund-Jobs |

### Kognitive Systeme

| Thema | CLI-Befehl | Beschreibung |
|-------|-----------|--------------|
| injectors | `bach help injectors` | Injektor-Übersicht (6 Stück) |
| meta_feedback_injector | `bach help meta_feedback_injector` | Meta-Feedback Injektor |
| reminder_injector | `bach help reminder_injector` | Erinnerungs-Injektor |
| context | `bach help context` | Kontext-Injektor |
| strategic | `bach help strategic` | Strategie-System |
| problemloesung | `bach help problemloesung` | Problemloesungs-Strategien |
| strategien | `bach help strategien` | Denkstrategien |
| denkstrategien | `bach help denkstrategien` | Erweiterte Denkstrategien |
| operatoren | `bach help operatoren` | Kognitive Operatoren |
| prompt | `bach help prompt` | Prompt-Techniken |

### Sonstiges

| Thema | CLI-Befehl | Beschreibung |
|-------|-----------|--------------|
| identity | `bach help identity` | System-Identität |
| data | `bach help data` | Datenverzeichnis |
| bach_paths | `bach help bach_paths` | Pfad-Konfiguration |
| formats | `bach help formats` | Datei-Formate |
| emoji | `bach help emoji` | Emoji-Konventionen |
| gui | `bach help gui` | GUI/Dashboard |
| prompt-generator | `bach help prompt-generator` | Prompt-Generator GUI |
| ollama | `bach help ollama` | Ollama-Integration |
| cookbook | `bach help cookbook` | Koch-Referenzen |
| cookbooks | `bach help cookbooks` | LLM-Cookbooks |
| vendor | `bach help vendor` | Drittanbieter |
| trash | `bach help trash` | Papierkorb-System |
| arrow | `bach help arrow` | Arrow-System |

---

## Tool-Dokumentation (docs/help/tools/)

Einzeldokumentation für ~80 Python-Tools. Zugriff:

```bash
bach help tools/<name>         # z.B. bach help tools/c_encoding_fixer
```

### Übersichts-Artikel

| Artikel | Beschreibung |
|---------|-------------|
| `tools/_index` | Alphabetischer Index aller Tools |
| `tools/policies` | Namenskonventionen, Präfixe |
| `tools/analysis` | Analyse-Tools |
| `tools/code_quality` | Code-Qualität |
| `tools/conversion` | Format-Konvertierung |
| `tools/imports` | Import-Management |
| `tools/monitoring` | Monitoring-Tools |
| `tools/ocr` | OCR-Engine |
| `tools/python_editing` | Python-Code-Bearbeitung |
| `tools/research` | Recherche-Tools |
| `tools/skills` | Skill-Management Tools |

### Coding-Tools (c_*)

| Tool | Beschreibung |
|------|-------------|
| `c_audit_bundler` | Audit-Bundle Erstellung |
| `c_emoji_scanner` | Emoji finden/ersetzen |
| `c_encoding_fixer` | Encoding reparieren |
| `c_german_scanner` | Deutsche Wörter finden |
| `c_import_diagnose` | Import-Probleme diagnostizieren |
| `c_import_organizer` | Imports sortieren |
| `c_indent_checker` | Einrückung prüfen |
| `c_json_repair` | JSON reparieren |
| `c_license_generator` | Lizenzdateien erstellen |
| `c_md_to_pdf` | Markdown zu PDF |
| `c_method_analyzer` | Methoden analysieren |
| `c_pycutter` | Python-Dateien aufteilen |
| `c_sqlite_viewer` | SQLite-Datenbanken anzeigen |
| `c_standard_fixer` | Code-Standards anwenden |
| `c_umlaut_fixer` | Umlaute korrigieren |
| `c_universal_converter` | Format-Konvertierung |
| `c_youtube_extractor` | YouTube-Extraktion |

### Generator-Tools

| Tool | Beschreibung |
|------|-------------|
| `code_generator` | Code-Generierung |
| `os_generator` | LLM-OS Struktur erstellen |
| `structure_generator` | Skill/Agent Struktur erstellen |
| `distribution_system` | Distribution-System |

### Agent- & Skill-Tools

| Tool | Beschreibung |
|------|-------------|
| `agent_cli` | Agent-CLI Steuerung |
| `agent_framework` | Agent-Framework |
| `agent_service_integration` | Service-Integration |
| `agents` | Agent-Verwaltung |
| `entwickler_agent` | Entwickler-Agent |
| `production_agent` | Produktions-Agent |
| `research_agent` | Recherche-Agent |
| `register_skills` | Skill-Registrierung |
| `generate_skills_report` | Skill-Report |
| `exporter` | Skill/Agent/OS Export |

### Wartungs-Tools

| Tool | Beschreibung |
|------|-------------|
| `backup` | Backup-System |
| `backup_manager` | Backup-Verwaltung |
| `doc_update_checker` | Dokumentations-Check |
| `duplicate_detector` | Duplikat-Erkennung |
| `file_cleaner` | Alte Dateien löschen |
| `json_fixer` | JSON reparieren |
| `path_healer` | Pfade reparieren |
| `pattern_tool` | Dateinamen-Patterns |
| `sync_utils` | Sync-Utilities |

### Monitoring & Policies

| Tool | Beschreibung |
|------|-------------|
| `token_monitor` | Token-Verbrauch |
| `success_tracker` | Erfolgs-Tracking |
| `task_statistics` | Task-Statistiken |
| `reports` | Report-Erstellung |
| `policy_applier` | Policies anwenden |
| `policy_control` | Policy-Kontrolle |
| `problems_first` | Problem-Priorisierung |

### System-Tools

| Tool | Beschreibung |
|------|-------------|
| `autolog` | Auto-Logging |
| `batch_file_ops` | Batch-Dateioperationen |
| `create_boot_checks` | Boot-Checks |
| `dirscan` | Verzeichnis-Scan |
| `injectors` | Injektor-System |
| `tool_discovery` | Tool-Erkennung |
| `tool_registry_boot` | Registry-Initialisierung |
| `tool_scanner` | Tool-Scanner |
| `registry_watcher` | Registry-Überwachung |
| `universal_compiler` | Universal Compiler |
| `python_cli_editor` | Python CLI Editor |

### Migrations- & Sonstige

| Tool | Beschreibung |
|------|-------------|
| `migrate_connections` | Connection-Migration |
| `migrate_ati_tasks` | ATI-Task Migration |
| `archive_done_tasks` | Erledigte Tasks archivieren |
| `export_txt` | Steuer-Export |
| `ollama_benchmark` | Ollama Benchmark |
| `ollama_summarize` | Ollama Zusammenfassung |
| `ollama_worker` | Ollama Worker |
| `gemini_start` | Gemini-Session starten |
| `mapping` | Feature-Mapping |
| `partner` | Partner-Tools |
| `foerderplaner_cli` | Förderplan-CLI |

---

## Für LLMs: Schnellzugriff

```python
from bach_api import help

# Hilfe lesen
help.run("cli")                # CLI-Referenz
help.run("tasks")              # Task-System
help.run("tools")              # Tool-Übersicht
help.run("architecture")       # Architektur

# Tool-spezifisch
help.run("tools/c_encoding_fixer")
help.run("tools/exporter")
```

**Empfohlene Lesereihenfolge für neue LLM-Sessions:**
1. `bach_info` -- Was ist BACH
2. `cli` -- Verfügbare Befehle
3. `architecture` -- Systemaufbau
4. `features` -- Feature-Matrix
5. `tasks` -- Task-System
6. `memory` -- Memory-Modell
7. `tools` -- Werkzeuge
