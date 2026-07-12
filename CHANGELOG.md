# BACH Changelog

Alle wichtigen Aenderungen an BACH werden hier dokumentiert.

Copyright (c) 2026 BACH Contributors. Alle Rechte vorbehalten.

## [Unreleased]

### Changed

- **clutch-Datenbrücke weiter gespiegelt:** `system/hub/_services/delegation/__init__.py` nutzt für BACHs Fahrtenbuch-/Fahrschule-Oberflächen jetzt externe `clutch.fahrtenbuch`-/`clutch.fahrschule`-APIs, sobald das Modul verfügbar ist. Der Adapter behält die bestehenden BACH-Signaturen und schreibt während des Parallelbetriebs weiter in die kanonische `bach.db` inklusive `clutch_fahrtenbuch`-/`clutch_fitness`-Kompatibilitätsflächen; `bach clutch migration` kann die DB-Brücke dadurch als `OK` ausweisen, ohne den Legacy-Fork zu archivieren.
- **clutch-Runtime-Compat bis zur Streckenlogik erweitert:** `system/hub/_services/delegation/__init__.py` erkennt externe `clutch`-Checkouts jetzt auch unter `.MODULES/.ORCHESTRATION/clutch` und legt `clutch.strecke`, `clutch.gas_bremse` sowie `clutch.bordcomputer` auf BACHs bestehende Signaturen und den kanonischen `bach.db`-Pfad ab. Damit kann `bach clutch migration` jetzt neben der DB-Brücke auch den Compat-Adapter als `OK` melden, sobald die verbleibenden Runtime-Flächen extern gespiegelt sind; die Fork-Archivierung bleibt weiter bewusst blockiert.
- **OpenClaw-Abgleich auf 2026-07-11 gehoben:** README, README.de, ROADMAP und `NEXT_RELEASE` spiegeln jetzt Stable `2026.6.11` sowie das neueste sichtbare Prerelease `2026.7.1-beta.5` vom 2026-07-11 10:36 UTC mit den für BACH relevanten Signalen zu conversational onboarding, approval-geführtem Setup, gebündelter ClawRouter-Modell-/Budgetsicht, Crash-Loop-Recovery und den weiter gültigen GPT-5.6-/Attach-/Telegram-/Capability-Fortschritten.

### Fixed

- **ActivityTracker-Mirror-Export rekursionsfrei gemacht:** Auto-Finalize exportiert `AGENTS.md`, `PARTNERS.md`, `USECASES.md`, `CHAINS.md` und `WORKFLOWS.md` jetzt direkt über die Exporter-Klassen statt über `bach.py export ...`-Subprozesse. Dadurch kann ein stale `system_activity`-Idle-Fall bei kurzen CLI-Befehlen wie `python bach.py skills version bach` keine rekursive Export-/Auto-Finalize-Kette mehr starten.
- **Root-Release-Metadaten synchronisiert:** `README.md`, `README.de.md` und `llms.txt` zeigen jetzt die veröffentlichte `v3.13.0-bluesky` statt des alten `v3.12.4-earth`-Badges; lokale Mac-/Host-Fixtures in Tests wurden durch repo-relative bzw. generische Werte ersetzt.

### Verified

- **ActivityTracker-Regressionspfad verifiziert:** `python -m pytest system\tests\test_activity_tracker.py system\tests\test_core.py -q` lief mit `50 passed`; der Live-Smoke `python bach.py skills version bach` finalisierte eine stale Session und meldete danach `MIRRORS 5/5` sowie `Version aktuell: v3.9.1`, ohne `bach.py export ...`-Kindprozesse zu hinterlassen.

## [3.13.0-bluesky] - 2026-07-11

### Added

- **Prompt-Bibliothek in der Web-GUI:** Neue Seite `/prompt-library` (Nav: Wissen → Prompts) auf BACHs eigenem DB-Prompt-System (`prompt_templates`/`prompt_versions`, identisch zu `bach prompt`): Suche, Kategorien, Editor mit echter Versionierung (Speichern archiviert den Altstand), REST-API `/api/prompt-library` (CRUD + Versionen) sowie idempotenter **Import aus PromptBoard** (`library.json` über dieselbe Kandidaten-Kaskade wie der System-Tray). Der deprecatete `/prompt-generator` leitet dorthin um.

### Fixed

- **Tool-/Skill-Sprachduplikate entfernt (Task 1149):** tools/skills existieren pro Sprache (`UNIQUE(name, language)`, de+en); Suche, Statistiken, Startup-Zähler und Referenz-Generatoren zeigten alles doppelt („BACH OCR Engine 2x", 579 statt 306 Tools). Queries deduplizieren jetzt sprachbewusst (`COUNT(DISTINCT name)`, `GROUP BY name` mit Sprachpräferenz); `docs`/`help`/`steuer` nutzen die kanonische DB statt des veralteten `data/bach.db`-Spiegels.
- **Inspektions-Sweep (5 NameError + Launcher):** fehlende Imports in `hub/multi_llm_protocol.py` (sqlite3) und `hub/setup.py` (sys); undefiniertes `result` in `chat_runtime._tool_loop`; undefiniertes `bd` im claude_bridge-`reload_config` (500); fehlender `date`-Import in der GUI-Finanzen-Route. `start/bach.bat`: Agent-Menü listete nicht existente `agents/*.json` und ignorierte die Agentenwahl — listet jetzt echte Agent-Ordner und bindet die gewählte SKILL.md in den Prompt ein.
- **GUI-Daemon-Status 500 behoben:** `os.kill(pid, 0)` wirft auf Windows bei veralteter PID generischen `OSError` (WinError 87) — wird jetzt abgefangen.
- **`hub/prompt.py`-Crash behoben:** `sqlite3.Row.get()` existiert nicht (Listenausgabe bei leerem `updated_at`).
- **`hub/mount.py`-Crash behoben:** `resolve(strict=True)` warf bei fehlender Mount-Quelle eine unbehandelte `FileNotFoundError`.
- **`tools/inbox_watcher.py`** ist ohne installiertes watchdog wieder importierbar (Fallback-Basisklasse).
- **Morgen-Briefing im Quick-Start repariert:** Redundante Funktions-Imports in `system/hub/startup.py` überschreiben `sqlite3` und `hashlib` nicht mehr als lokale Variablen. Dadurch kann der Morgen-Zweig auch dann auf SQLite zugreifen, wenn der Kernel-Hash-Check im Quick-Modus übersprungen wird; ein zeitfixierter Regressionstest deckt den Pfad ab.

### Changed

- **MCP-Server-Metadaten und Dokumentation aktualisiert:** `README.md`, `llms.txt` und Hilfedokumente auf CodeCommander `v1.3.14` (21 Tools) sowie FileCommander `v1.9.1` (46 Tools) synchronisiert; `llms.txt` Last-checked auf `2026-07-06` gesetzt.
- **clutch-Migration sichtbar gemacht:** `bach clutch migration` zeigt jetzt, welche Delegationskomponenten bereits externe `clutch`-Quellen nutzen und welche Legacy-/DB-Brücken vor einer Fork-Archivierung noch offen sind.
- **clutch-PartnerRegistry gegen BACH-Regeln gespiegelt:** `system/hub/_services/delegation/__init__.py` baut jetzt eine `clutch`-gestützte PartnerRegistry aus BACH `partner_recognition`, und `system/hub/partner.py` legt darüber zusätzlich `delegation_rules` sowie explizite `delegation_zones`. Dadurch respektieren sowohl Auto-Routing als auch explizite `--to=`-Delegationen die BACH-Allow-Lists und die externe clutch-Zonenökonomie; die aktive Routing-Quelle wird als `clutch-partner-registry` ausgewiesen.
- **OpenClaw-Abgleich auf 2026-07-05 gehoben:** README, README.de, ROADMAP und `NEXT_RELEASE` spiegeln jetzt Stable `2026.6.11`, das neueste sichtbare Prerelease `2026.7.1-beta.2` sowie die daraus relevanten Signale zu ClawRouter-Modell-Discovery, Device-Approval-/Plugin-Install-Recovery und den weiter gültigen GPT-5.6-/Attach-/Telegram-/Capability-Fortschritten.
- **Skill-Source-Registry für `bach skills version bach` ergänzt:** `system/hub/skills.py` liest kanonische Quellen und optionale Codex-/Claude-Kopien jetzt aus `system/data/skill_sources.json`, löst relative Registry-Pfade robust auf und meldet den Repo-Root-Skill wieder als echte kanonische Quelle statt `ZENTRAL: (nicht registriert)`.
- **OpenClaw-Abgleich auf 2026-07-03 erneut bestätigt:** README, README.de, ROADMAP und `NEXT_RELEASE` markieren den unveränderten Stand mit Stable `2026.6.11` und sichtbarem Prerelease `2026.7.1-beta.1` jetzt explizit als am 2026-07-03 erneut verifiziert.
- **OpenClaw-Abgleich auf 2026-07-02 gehoben:** README, README.de, ROADMAP und `NEXT_RELEASE` spiegeln jetzt Stable `2026.6.11`, das neueste sichtbare Prerelease `2026.7.1-beta.1` sowie die daraus relevanten Signale zu GPT-5.6-Coverage, `openclaw attach`, Telegram-Codex-Steering, `on-exit`-Cron und gescopten Capability-Profilen.
- **Daily-Care-Planung auf heutigen Upgrade-Befund nachgezogen:** Release-Doku und Roadmap dokumentieren jetzt ausdrücklich, dass `bach upgrade repair --version v3.12.4-earth --json` den Live-Drift im Release-Katalog am 2026-07-02 erneut von `release_entries=0` auf `release_entries=1` zurückgesetzt hat.
- **Handler-Dispatch reicht `dry_run` jetzt signatursicher weiter:** `system/core/app.py` prüft die `handle(...)`-Signatur vor dem Aufruf, statt interne `TypeError`-Fehler versehentlich als Legacy-Fallback ohne `dry_run` zu verschlucken.
- **Delegations-Compat-Layer meldet die echte Scorer-Quelle:** `system/hub/_services/delegation/__init__.py` und `system/hub/partner.py` exponieren für `bach --partner delegate --score` jetzt korrekt, ob der externe `clutch`-Scorer oder der Legacy-Fallback aktiv ist.
- **ProSync-Fail-soft enger begrenzt:** `system/hub/db_sync.py` deferiert Pull-Kandidaten nur noch bei bekannten transienten OneDrive-/SQLite-Fehlern wie Cloud-Timeout oder `disk I/O error`, nicht mehr bei beliebigen Merge-Exceptions.
- **ProSync-Startup wird fail-soft:** `system/hub/db_sync.py` staged OneDrive-Transit-Backups vor dem Merge lokal und merkt Pull-Kandidaten, die mit Cloud-Timeouts oder `disk I/O` scheitern, für rund 30 Minuten in `sync_state.json` vor. Dadurch blockiert ein einzelnes unlesbares Transit-Backup nicht mehr jede CLI-/`--json`-Abfrage erneut.
- **PromptBoard-Storage-Erkennung harmonisiert:** Der BACH-Tray sucht `library.json` jetzt nach `BACH_PROMPTBOARD_LIBRARY` zuerst im aktuellen PromptBoard-Desktop-Standard `~/.promptboard/` und nutzt `%APPDATA%/PromptBoard/` nur noch als Legacy-Fallback.
- **Quick-/Silent-Startup entschärft:** Der Skill-Health-Monitor wird bei Quick- und Silent-Starts übersprungen, damit Automationen und kurze Smokes nicht durch den breiten Skill-Scan ausgebremst werden; Workstation-spezifische Memory-Mirrors sind zusätzlich ignoriert.
- **Domänen-Workflows vervollständigt:** Zwölf neue Workflow-Dateien (`assistent`, `care-modul`, `datenmodul`, `dokumentenmodul`, `finanzen`, `gesundheit`, `haushalt`, `karriere`, `reflection-status`, `selbstmanagement`, `therapie`, `wissen`) decken jetzt die bisher manuellen Usecase-Kategorien ab.
- **Workflow-Katalog auf 71 Vorlagen erhöht:** README und Workflow-Spiegel referenzieren die neue Gesamtzahl nach dem Ausbau der Usecase-Frontdoor.
- **OpenClaw-Abgleich auf 2026-06-16 gehoben:** README, README.de, ROADMAP und `NEXT_RELEASE` spiegeln jetzt Stable `2026.6.8` sowie das neueste sichtbare Prerelease `2026.6.8-beta.2` mit Fokus auf Kanalzustellung, Recovery, Provider-/Auth-Härtung und explizite Websuch-Defaults.
- **Software-Usecases an echten Workflow gebunden:** Eine neue gemeinsame Datei `system/skills/workflows/software.md` deckt jetzt die Software-Usecases 41 bis 49 ab, sodass `bach usecase run` und `bach usecase run-all` diese Gruppe nicht mehr im manuellen Fallback behandeln müssen.
- **Wiki-Author-Workflow auf aktuelles Layout gehoben:** `system/skills/workflows/wiki-author.md` verweist wieder konsistent auf `wiki/` und `hub/_services/wiki/` statt auf veraltete `skills/wiki`- und `skills/_services/wiki`-Pfade.
- **OpenClaw-Abgleich auf 2026-06-13 gehoben:** README, README.de, ROADMAP und `NEXT_RELEASE` spiegeln jetzt Stable `2026.6.6` vom 12. Juni 2026 sowie das neueste sichtbare Prerelease `2026.6.7-beta.1` vom 13. Juni 2026 mit Fokus auf Recovery, Auth-/Kontextgrenzen, Doctor-/Update-Fortschritt und QA-Evidenz.
- **GUI-Scan auf Report-Filter gehärtet:** `system/hub/lang.py` nutzt für `bach lang scan --namespace gui` jetzt dieselben gefilterten Hardcoded-Copy-Fundstellen wie `bach lang report`, sodass Python-Docstrings, SQL-Schnipsel und ähnliches GUI-Rauschen nicht mehr als DE-Copy in die Release-Artefakte gelangen.
- **GUI-i18n-Stand weiter verdichtet:** Nach dem bereinigten Re-Scan und zusätzlichen sichtbaren Umlaut-Korrekturen in `persoenlich`, `memory`, `steuer` und `workflow_tuev` stehen die Release-Artefakte jetzt bei 17.593 exportierten Übersetzungen.
- **OpenClaw-Abgleich auf 2026-06-12 gehoben:** README, README.de, ROADMAP und `NEXT_RELEASE` spiegeln jetzt Stable `2026.6.6` vom 12. Juni 2026, das neueste sichtbare Prerelease `2026.6.6-beta.2` vom 12. Juni 2026 sowie die daraus relevanten Signale zu abgesicherten Zustandsmigrationen, Recovery und Release-/Test-Helfern.
- **Discoverability-Metadaten nachgezogen:** README nennt jetzt den kanonischen Suchstring `ellmos-ai/bach`, verlinkt `llms.txt` als maschinenlesbaren Crawler-Kontext, korrigiert die prominente Workflow-Zahl auf 59 und synchronisiert die MCP-npm-Versionen auf `ellmos-codecommander-mcp` 1.3.10 sowie `ellmos-filecommander-mcp` 1.8.0.
- **Crawler-Frische markiert:** `llms.txt` enthält jetzt `Last-checked: 2026-06-11`.
- **Discoverability-Kontext nachgezogen:** README, README.de und `llms.txt` benennen BACH jetzt klarer als local-first LLM-Betriebssystem, grenzen das Repo von Bach-Musik, Bash-Testframeworks und gehosteten Agent-SaaS ab und synchronisieren `llms.txt` auf `v3.12.4-earth`.
- **Öffentliche Planungsreferenzen bereinigt:** Roadmap und Installer-Hilfe verweisen nicht mehr auf private, ignorierte Release-Planungsdateien, sondern auf öffentliche Roadmap-/Changelog-Zusammenfassungen.
- **GUI-i18n-Report geschärft und Oberfläche bereinigt:** `bach lang report` filtert in JS-generiertem Markup jetzt zusätzlich technische `class`-/`id`-Tokens aus, damit der GUI-Drift-Report keine CSS-/DOM-Reste mehr als DE-Copy zählt.
- **GUI-Texte auf echte Umlaute gehoben:** Sichtbare Oberflächen in `ATI`, `Daemon`, `Financial`, `Denkarium` und dem `Skills Board` verwenden jetzt wieder echte Umlaute statt `ae/oe/ue` oder HTML-Entity-Resten.
- **GUI-i18n-Exports weiter reduziert:** Neunundzwanzig zusätzliche GUI-DE-Schlüssel wurden im bestehenden `gui`-Namespace ergänzt; die Release-Artefakte (`languages_translations.release.json`, `languages_seed.release.sql`, `locales/*.json`, `manifest.release.json`) stehen dadurch jetzt bei 17.488 exportierten Übersetzungen.
- **Lokale Pfad-Defaults redigiert:** Backup-Ziele, ATI-Scan-Defaults und lokale Variant-/Report-Datenpfade nutzen jetzt `BACH_BACKUPS_DIR`, `BACH_SOFTWARE_ROOT`, `BACH_VARIANT_DB` oder `BACH_REPORT_ARCHIVE` statt getrackter maschinenspezifischer Windows-Pfade.
- **OpenClaw-Abgleich aktualisiert:** README, README.de und ROADMAP spiegeln jetzt Stable `2026.6.1` vom 3. Juni 2026, das neueste sichtbare Prerelease `2026.6.5-beta.1` vom 6. Juni 2026 sowie den QA-Befund vom 2026-06-06.

### Verified

- **Skill-Source-Registry live verifiziert:** `python -m pytest system/tests/test_skills_handler.py -q` lief mit `18 passed`; zusätzlich wurden `python bach.py skills version bach`, `python bach.py agent doctor test-agent --json` und `python bach.py usecase run 50 --dry-run` am 2026-07-03 gegen den neuen Registry-Pfad geprüft.
- **Daily-Care-Smokes auf 2026-07-02 erneuert:** `python bach.py --startup quick --mode=silent --partner=codex`, `python bach.py agent doctor test-agent --json`, `python bach.py agent start test-agent --dry-run --json` und `python bach.py usecase run 50 --dry-run` liefen erneut grün; `python bach.py upgrade check --json` zeigte zuerst `release_entries=0`, und der vorgesehene Self-Heal `python bach.py upgrade repair --version v3.12.4-earth --json` stellte den Release-Katalog anschließend wieder mit `release_entries=1` und `repair_recommended=false` her.
- **Delegations-/Dispatch-Regressionen erweitert:** `python -m pytest system/tests/test_core.py system/tests/test_partner_handler.py system/tests/test_startup_handler.py system/tests/test_db_sync_handler.py -q` lief mit `116 passed`; zusätzlich wurden `python bach.py --partner delegate "Migration pruefen" --score --dry-run`, `python bach.py --startup --mode=text --dry-run` und `python bach.py help partner` gegen den aktuellen Stand verifiziert.
- **ProSync-Deferral-Regressionspfad verifiziert:** `python -m pytest system/tests/test_db_sync_handler.py -q` lief mit `45 passed`, `python -m pytest system/tests/test_prosync_race.py -q` mit `3 passed`. Zusätzlich wurde am 2026-06-21 ein echter OneDrive-Transitfehler (`[WinError 426] Der Cloudvorgang wurde nicht vor Ablauf der Zeitüberschreitungsperiode abgeschlossen`) reproduziert; danach blieben `python bach.py agent doctor test-agent --json`, `python bach.py --startup quick --mode=silent --partner=codex`, `python bach.py usecase run 50 --dry-run`, `python bach.py upgrade check --json`, `python bach.py task list --filter clutch` sowie ein vollständiger `test-agent`-Steuerzyklus wieder schnell und grün.
- **PromptBoard-Tray-Pfadsmoke verifiziert:** `python -m pytest system\tests\test_connectors_and_tray.py -q` lief mit `72 passed`; `python system\hub\_services\chat\chat_tray.py --smoke-promptboard` findet `~/.promptboard/library.json` nun vor dem AppData-Fallback.
- **Startup-Skip-Regressionspfad ergänzt:** `system/tests/test_startup_handler.py` deckt ab, dass Quick-/Silent-Starts den Skill-Health-Monitor nicht aufrufen und volle interaktive Starts ihn weiterhin ausführen.
- **Resolver-Abdeckung für Restkategorien verifiziert:** `python -m pytest system/tests/test_tuev_handler.py -q -k "resolve_uppercase_category_to_lowercase_workflow_file or resolve_snake_case_category_to_kebab_case_workflow_file"` lief mit `2 passed`.
- **Usecase-Workflow-Abdeckung jetzt vollständig:** Ein direkter Resolver-Check sieht 50 workflowgebundene und 0 manuelle Usecases; `bach usecase run 50 --dry-run` löst `skills\workflows\reflection-status.md` sauber auf.
- **Startup- und Agenten-Smokes auf 2026-06-17 erneuert:** `bach --startup quick --mode=silent --partner=codex` lief in rund 58 Sekunden erfolgreich durch, und der vollständige `test-agent`-Steuerzyklus (`clear-steer`, `steer`, `start`, `status`, `pause`, `checkpoint`, `resume`, `stop`, `clear-steer`) blieb erneut grün.
- **SOFTWARE-Workflow-Regressionspfad verifiziert:** `python -m pytest system/tests/test_tuev_handler.py -q -k "resolve_uppercase_category_to_lowercase_workflow_file"` lief mit `1 passed`.
- **Usecase-Workflow-Abdeckung sichtbar verbessert:** `bach usecase run 41 --dry-run` löst jetzt `skills\workflows\SOFTWARE.md` statt eines manuellen Fallbacks auf; `bach usecase run-all --dry-run` steht damit bei 24 workflowgebundenen und 26 manuellen Usecases.
- **GUI-Scan/Report-Regressionspfad verifiziert:** `python -m pytest system/tests/test_lang_handler.py -q -k "report_gui_js_ignores_technical_literals_but_keeps_ui_copy or test_scan_gui_uses_report_filters_for_runtime_copy"` lief mit `2 passed`.
- **Daily-Care-Smokes auf 2026-06-12 erneuert:** `bach agent doctor test-agent --json`, der vollständige `test-agent`-Steuerzyklus (`clear-steer`, `steer`, `start`, `status`, `pause`, `checkpoint`, `resume`, `stop`, `clear-steer`), `bach usecase run 12 --dry-run`, `bach usecase run 41 --dry-run`, `bach usecase run-all --dry-run`, `bach upgrade status/check --json`, `bach lang scan --namespace gui` und `bach lang report --surface gui --limit 20 --json` erneut verifiziert.
- **GUI-i18n-Befund bereinigt:** Der GUI-Report liegt jetzt bei 166 eindeutigen Strings und 253 Fundstellen, jeweils mit 0 offenen GUI-DE-Einträgen; Usecase 41 bleibt weiter im manuellen Fallback, aber ohne Fehler.
- **Daily-Care-Smokes erneuert:** `python -m pytest system/tests/test_lang_handler.py -q -k "report_gui_js_ignores_technical_literals_but_keeps_ui_copy or test_extract_script_strings_skips_dom_ids_and_paths or test_extract_script_strings_skips_markup_class_and_id_tokens"` (`3 passed`), `bach agent doctor test-agent --json`, der vollständige `test-agent`-Steuerzyklus (`clear-steer`, `steer`, `start`, `status`, `pause`, `checkpoint`, `resume`, `stop`, `clear-steer`), `bach usecase run 12 --dry-run`, `bach usecase run 41 --dry-run`, `bach usecase run-all --dry-run`, `bach upgrade status/check --json` und `bach lang report --surface gui --limit 20 --json` erneut verifiziert.
- **GUI-i18n-Befund verbessert:** Der GUI-Report liegt jetzt bei 94 offenen eindeutigen Einträgen und 111 offenen Fundstellen; Usecase 41 bleibt weiter im manuellen Fallback, aber ohne Fehler.

## [3.12.4-earth] - 2026-05-17

### Added

- **Mehrsprachige README-Oberfläche:** Root-READMEs für EN/DE/ES/RU/JA/ZH ergänzt und die englische sowie deutsche README um einen sichtbaren Sprachindex erweitert.
- **Crawler-freundliche Spracheinstiege:** Jede aktivierte Sprache erhält zusätzlich einen eigenen `docs/i18n/<lang>/README.md`-Einstieg.

### Changed

- **Release-Codename:** Version auf `v3.12.4-earth` gehoben, passend zur global sichtbaren Mehrsprachigkeit.

## [3.12.3-coffee] - 2026-05-17

### Privacy

- **Legacy-Pfade bereinigt:** Restliche getrackte Windows-/OneDrive-Pfade in Wiki, Help, Workflow-Dokumenten, historischen Testartefakten und Hilfsskripten durch portable Platzhalter oder Home-/Env-basierte Defaults ersetzt.

### Fixed

- **Legacy-Session-Policy geschärft:** `system/hub/scheduler.py` markiert die veraltete pyautogui-Session-Automation in `bach scheduler session doctor/status` jetzt explizit als deprecated, entfernt irreführende Start-Empfehlungen, blockiert `session start/trigger` ohne bewusstes `--force` und listet empfohlene Ersatzpfade plus bereinigte Profilhilfe für Operatoren.

## [3.12.2-coffee] - 2026-05-17

### Added

- **i18n-Release-Snapshot erweitert:** Sprach-Artefakte auf 14.655 Übersetzungen aktualisiert und weitere Help-Übersetzungen für EN/ES/JA/RU/ZH ergänzt.

### Fixed

- **Übersetzungsbatch robuster:** `translate_skills_batch.py` verarbeitet wieder alle aktiven Skills und fällt bei leerem Google-Translate-Ergebnis auf den Ursprungstext zurück.
- **Release-Version synchronisiert:** Packaging und README-Dateien auf `v3.12.2-coffee` nachgezogen.
- **Windows-Subprocess-Ausgaben stabilisiert:** GUI-, Compiler-, Lizenz- und XLSX-Recalc-Aufrufe dekodieren Prozessausgaben explizit als UTF-8 mit Ersatzzeichen.

### Privacy

- **Release-Manifest neutralisiert:** `manifest.release.json` enthält wieder den neutralen `runtime_db`-Hinweis statt eines lokalen Benutzerpfads.
- **Lokale Pfade bereinigt:** Release-Exports, Skill-Spiegel und Help-Beispiele ersetzen lokale Windows-/OneDrive-Pfade durch portable Platzhalter.
- **Compiler-Pfad portable gemacht:** `universal_compiler.py` nutzt `BACH_SOFTWARE_DIR` oder den Home-basierten Standardpfad statt eines festen lokalen OneDrive-Pfads.
- **User-spezifische Artefakte aus Tracking entfernt:** Bereits ignorierte dist_type-0 Experten-/Steuer-Dateien werden aus dem Git-Index entfernt; lokale Kopien bleiben erhalten.
- **Lokales Finalizer-Skript ignoriert:** `wait_and_finalize.py` ist als temporäres Release-Hilfsskript eingestuft und wird nicht veröffentlicht.

## [3.11.1] - 2026-05-17

### Fixed

- **GUI: implicit window.event in 5 templates:** Functions called via `onclick` used `event` without receiving it as parameter (fails in strict mode). Fixed in `prompt-generator.html`, `inbox.html`, `daemon.html`, `messages.html`, `skills-board.js` by passing event explicitly.
- **Cross-platform Popen detachment in 4 handlers:** `claude_bridge.py`, `ati.py`, `daily_agent.py`, `watcher.py` used Windows-only `CREATE_NO_WINDOW` unconditionally. Now uses platform-conditional kwargs dict with `start_new_session=True` on Unix.
- **extensions.py subprocess:** Console window suppression on Windows for plugin subprocess fallback.

### Added

- **Test: test_claude_bridge_handler.py** (8 tests) — startup, shutdown, status, cross-platform Popen.
- **Test: test_watcher_handler.py** (8 tests) — start, stop, status, cross-platform Popen.
- **Test: test_daily_agent_handler.py** (6 tests) — start, stop, schedule, cross-platform Popen.
- **Test: test_ati_handler.py** (+2 tests) — cross-platform Popen verification.
- **Test: test_plugins_handler.py** (8 tests) — plugin installation, listing, removal.

---

## [3.11.0-coffee] - 2026-05-16

### Added

- **3241 Tests:** Comprehensive test suite with 63 new test files covering handlers, services, GUI, MCP servers.
- **MCP Cross-Platform Tests:** `test_mcp_servers.py` validates FileCommander/CodeCommander discovery, initialization, capabilities on Windows/macOS/Linux.
- **Linux Support Verified:** BACH core installs and runs on Ubuntu 24.04 (321/332 smoke tests pass, only GUI-desktop tools skip on headless).
- **GUI Interactivity Audit:** 8 critical templates audited, 3 runtime bugs fixed, all data endpoints verified populated (32/32).

### Fixed

- **GUI: memory.html addLesson/addFact crash:** Removed references to non-existent `lesson-category`/`fact-category` elements that threw TypeError on click.
- **GUI: memory.html Dev Mode buttons:** Implemented missing `refreshDevData()` and `cleanupOrphanedMemory()` functions that threw ReferenceError.
- **GUI: kontakte.html non-functional:** Fixed `escapeHtml` load order — inline `esc()` function instead of referencing `nav.js` before it loads.
- **GUI: tools.html apostrophe crash:** Escape single quotes in tool names for `onclick` handlers.
- **GUI: scan_config SQL query:** Removed non-existent `category` column from scanner config endpoint.
- **GUI: PromptGenerator import path:** Corrected service path from `skills/_services/` to `hub/_services/`.
- **Encoding: scheduler.py subprocess calls:** Added `encoding="utf-8", errors="replace"` to 3 subprocess.run calls that crashed with cp1252 UnicodeDecodeError on Windows.
- **Connection leaks:** Fixed unclosed DB connections in health, fs, restore, setup, startup, agents, db_sync handlers.
- **Cross-platform:** `subprocess.CREATE_NO_WINDOW` instead of magic constant, Edge PDF detection for macOS, font fallback in chat_tray.
- **Contact handler:** Fixed `r['mobile']` → `r['phone_mobile']` column name mismatch.
- **Linux: hub/test.py:** Fixed invalid escape sequences causing SyntaxWarning on Python 3.12.
- **Help files:** Added missing operations: agent rename, setup hooks/hooks-remove/lang, skills export-agent.
- **Schema:** Marked `schema_user_v2.sql` as deprecated (dead artifact, not used by code).
- **Version sync:** Updated pyproject.toml, setup.py, bach.bat, README.md/de.md to v3.11.0.
- **Gitignore:** Added generated `analysis_results.json` to .gitignore, removed from tracking.

---

## [Unreleased]

### Added

- **Strukturierte Pfadoberfläche:** `system/hub/path.py` liefert jetzt eine moderne `bach path`-CLI mit JSON-Ausgaben, Runtime-Root-Spiegelung, `resolve`-/`validate`-Helfern und DB-Overrides über die kanonische BACH-Datenbank.
- **i18n-Drift-Report:** `system/hub/lang.py` ergänzt `bach lang report` als explizite Prüfung für Release-Manifest, Locale-Dateien, Export-Counts und harte DE-Copy pro Namespace.
- **Maschinenlesbare Upgrade-Flächen:** `system/hub/upgrade.py` liefert für `bach upgrade list/status/check --json` jetzt strukturierte Versions-, Release- und Drift-Payloads für Automationen und Dashboards und zeigt `manifest_entries`, `release_entries`, `repair_recommended`, `current_version` sowie `current_release_registered` jetzt konsistent auch außerhalb des Leerfalls.
- **Upgrade-Metadaten-Reparatur:** `system/hub/upgrade.py` ergänzt `bach upgrade repair [--dry-run] [--version]`, um `distribution_manifest` und `dist_file_versions` aus dem aktuellen Distributionsbaum wieder aufzubauen, bei leerem `distribution_releases` den aktuellen Release-Eintrag aus README-/CHANGELOG-Metadaten zu bootstrapen und die kanonische Upgrade-Basis vollständig wiederherzustellen.
- **MediPlaner-Austausch:** `system/hub/mediplaner.py` ergänzt `bach mediplaner export/import/help` für den JSON-Austausch zwischen BACH-Gesundheitsdaten und MediPlaner; CLI-Hilfe, Gesundheitsdoku und Chat-Runtime kennen den Handler jetzt ebenfalls.
- **Safe-Checkpoint-Steering für Ketten:** `llmauto` und `bach chain` unterstützen jetzt `pause`, `resume` und `steer`, sodass Operator-Hinweise zwischen Modellläufen vorgemerkt, angezeigt und am nächsten sicheren Checkpoint übernommen werden.
- **Agent Doctor:** `system/hub/agent_launcher.py` ergänzt `bach agent doctor [name] [--json]` als Preflight-Diagnose für Claude CLI, Laufzeitverzeichnisse, SKILL.md und stale PID-Dateien inklusive konkreter Recovery-/Start-Hinweise.
- **Agent-Start-Policies:** `bach agent start` akzeptiert jetzt `--permission-mode`, `--allowed-tools` und `--max-turns`, kann dieselben Defaults optional aus `agent_runtime`-Frontmatter in Agent-`SKILL.md` laden und spiegelt aktive Policy plus Runtime-Defaults in den JSON-Statusflächen.
- **Scheduler Doctor:** `system/hub/scheduler.py` ergänzt `bach scheduler doctor [--json]` und `bach scheduler session doctor [--json]` als strukturierte Preflight-Diagnosen für Scheduler-/Session-Skripte, PID-Zustand, DB-/Config-/Profil-Flächen und konkrete Recovery-Schritte.
- **Maschinenlesbare Agent-Kontrollantworten:** `system/hub/agent_launcher.py` liefert jetzt auch bei `bach agent start/stop/steer/clear-steer/status --json` strukturierte Operator-Antworten inklusive Zielauflösung, Status, PID-, Laufzeit- und Queue-Metadaten.
- **Explizite Agent-Steering-Bereinigung:** `bach agent clear-steer [name] [--json]` leert vorgemerkte oder veraltete Operator-Hinweis-Queues jetzt gezielt und spiegelt den bereinigten Queue-Stand maschinenlesbar zurück.
- **Agent-Vorstart-Steering-Queue:** `bach agent steer [name] [--json]` kann Hinweise jetzt auch für gestoppte Agenten vormerken; `list/status --json` spiegeln dafür `queued_for_next_start`, und der nächste `bach agent start` übernimmt die Queue bewusst weiter.
- **Vorstart-Hinweise jetzt im Initialkontext:** `bach agent start` injiziert vorgemerkte Operator-Hinweise direkt in die generierte Session-`CLAUDE.md` und verweist dort explizit auf sichere Checkpoints für spätere `OPERATOR_NOTES.md`-Updates.
- **Kooperative Agenten-Pause:** `system/hub/agent_launcher.py` ergänzt `bach agent pause/resume [name] [Grund] [--json]`; laufende Agenten exponieren dazu einen verschachtelten `operator_control`-Snapshot mit Pause-, Queue- und Dateipfad-Metadaten, und `OPERATOR_NOTES.md` spiegelt aktive Pausewünsche direkt mit.
- **Explizite Agenten-Checkpoint-Quittierung:** `system/hub/agent_launcher.py` ergänzt `bach agent checkpoint [name] [Notiz] [--json]`; laufende Agenten schreiben damit `operator_checkpoint.json`, aktualisieren `OPERATOR_NOTES.md` und exponieren `last_checkpoint_at`, `last_checkpoint_message`, `latest_control_request_at` und `awaiting_checkpoint_ack` in `operator_control`.
- **Explizite Session-Steering-Bereinigung:** `bach scheduler session clear-steer [--profile NAME]` leert vorgemerkte Profil-Hinweise jetzt gezielt, und `session status --json` listet die neue Control-Action maschinenlesbar mit aus.
- **Session-Control-JSON-Parität:** `bach scheduler session pause/resume/steer/clear-steer --json` liefert jetzt strukturierte Kontrollantworten mit aktuellem Profil-Snapshot, `available_actions`, Queue-Länge sowie `latest_steer_message` und `latest_steer_requested_at`.
- **Scheduler-Run-Control-JSON-Parität:** `bach scheduler pause/resume/steer/clear-steer --json` liefert jetzt dieselbe Operator-Steueroberfläche auch für fällige Scheduler-Jobs inklusive globalem `operator_control`-Snapshot.

### Changed

- **Heutige Release-Verifikation nachgezogen:** README, README.de, ROADMAP und Release-Planung spiegeln jetzt die Live-Smokes vom 2026-06-01 (`python -m py_compile`, `test_bach_paths.py`, `beleg_vorfilter.py --dry-run`, `bach agent doctor test-agent --json`, kompletter `test-agent`-Headless-Lauf, `usecase run 12/41`, `usecase run-all --dry-run`, `bach upgrade status/check --json`, `bach lang report --surface gui --limit 5 --json`) sowie den verifizierten OpenClaw-Stand mit Stable `2026.5.28`, sichtbarem Release-Prerelease `2026.5.31-beta.1` und der aktuell hervorgehobenen Containerlinie `2026.6.1-beta.1-browser` plus `2026.6.1-beta.1-slim`.
- **Root-README Upgrade-Syntax präzisiert:** Die Upgrade-Bullets nennen jetzt explizit `bach upgrade list <path> --json` sowie `status/check --json`, damit Dateipflicht und maschinenlesbare Fehlerpfade für Automationen klar bleiben.
- **Scheduler-Hilfe und READMEs nachgezogen:** Session-Control-Befehle dokumentieren die neuen `--json`-Antworten jetzt konsistent in Scheduler-Hilfe, README und Release-Planung.
- **Scheduler-Daemon respektiert Operator-Steuerung:** Globale Pausen blockieren fällige Jobs im echten Loop, und vorgemerkte Hinweise werden an Script-, Shell- und Chain-Läufe via `BACH_SCHEDULER_OPERATOR_STEER` weitergereicht.
- **Agent-Hilfe und Release-Planung nachgezogen:** Hilfe, README, ROADMAP, CHANGELOG und `NEXT_RELEASE` dokumentieren jetzt die Vorstart-Steuerung mit `queued_for_next_start`, `status=queued`, Queue-Persistenz über den nächsten Agentenstart, die direkte `CLAUDE.md`-Injection, kooperative `pause`/`resume`-Anfragen sowie explizite `checkpoint`-Quittierungen mit verschachteltem `operator_control`.
- **Upgrade-Hilfe und Root-READMEs nachgezogen:** Hilfe, README und README.de dokumentieren jetzt `bach upgrade list/status/check --json` plus `bach upgrade repair` als maschinenlesbare Drift-, Repair- und Release-Fläche für Automationen.

### Fixed

- **Kanonische DB-Pfadoberflächen weiter vereinheitlicht:** `system/tools/mcp_server.py` nutzt jetzt dieselbe `BACH_DB`-Quelle wie die Handler, `system/tools/bach_db_viewer.py` bevorzugt `BACH_DB` beziehungsweise `~/.bach/bach.db`, und getrackte Help-Texte sprechen konsistent von `BACH_DB` statt `system/data/bach.db`.
- **Scheduler-Steering erreicht llmauto-Ketten jetzt wirklich:** `system/tools/llmauto/core/state.py` und `system/tools/llmauto/modes/chain.py` importieren globale Scheduler-Hinweise aus `BACH_SCHEDULER_OPERATOR_STEER` jetzt beim echten Chain-Run in die reguläre llmauto-Steering-Queue, erhalten den ursprünglichen Zeitstempel und übergeben die Hinweise am nächsten sicheren Checkpoint an den Modellprompt.
- **Sprach-Scan auf aktuelles Layout gehärtet:** `bach lang scan` folgt jetzt `docs/help`, `gui/templates`, `gui/static/js`, `agents/`, `skills/workflows` und `tools/` statt veralteten Pfaden und erkennt zusätzlich HTML-, JS- und Markdown-Flächen.
- **Pause-Statusflächen konsistent gemacht:** `system/hub/agent_launcher.py` leitet aktive Pauseanforderungen für laufende Agenten jetzt auch im Top-Level-Status und im Textstatus als `pause-requested` bzw. `[PAUSE-REQ]` ab, statt sie nur verschachtelt unter `operator_control` zu zeigen.
- **Legacy-Usecases laufen wieder:** `system/hub/tuev.py` akzeptiert bei `bach usecase run` jetzt neben JSON auch ältere Klartext-Payloads in `test_input` und `expected_output`, sodass bestehende Testfälle wie `#12 Irreguläre Kosten Vorschau` nicht mehr mit `JSON-Fehler` abbrechen.
- **Usecase-Sammeltests aktiviert:** `system/hub/tuev.py` führt `bach usecase run-all [workflow] [--dry-run]` jetzt wirklich für alle oder workflowgefilterte Usecases aus, aktualisiert `last_tested` nur außerhalb von Dry-Runs und bevorzugt echte Markdown-Workflowdateien statt gleichnamiger Verzeichnisse.
- **Docs-Report auf aktuelles Layout gehärtet:** `system/tools/doc_update_checker.py` scannt jetzt `docs/help/*.txt`, `hub/_services/` und Root-Dokumente mit konsistenten Pfaden, erkennt veraltete `hub/handlers/*.py`- sowie `skills/_services/<service>/`-Referenzen am realen Layout und beschädigt dabei keine bereits korrekten `hub/_services/...`-Pfade mehr.
- **Scheduler-Doctor DB-Check repariert:** `system/hub/scheduler.py` importiert `sqlite3` wieder explizit, sodass Stale-PID- und Datenbankdiagnosen im JSON-Doctor gemeinsam sauber funktionieren.
- **Scheduler nutzt jetzt die kanonische BACH-DB:** `system/hub/scheduler.py` und `system/gui/daemon_service.py` greifen für Doctor/Status/Jobliste und den Hintergrunddienst jetzt auf dieselbe kanonische BACH-Datenbank zu, statt auf einem veralteten `system/data/bach.db`-Pfad auseinanderzulaufen.
- **Registry-Reports entdoppelt:** `system/tools/maintenance/registry_watcher.py` dedupliziert `valid`, `stale_db_entries`, `relocated_entries`, `historical_entries`, `external_entries` und `orphan_files` jetzt stabil, sodass mehrfach vorhandene DB-Zeilen die Health-Reports nicht mehr künstlich aufblasen.
- **Upgrade-Kategorien vervollständigt:** `system/hub/upgrade.py` routet jetzt auch `agents`, `connectors`, `partners`, `docs` und `gui` sauber in die kategorie-basierte Restore-/Upgrade-Logik, statt diese Namen fälschlich wie Dateipfade zu behandeln.
- **Restore-Kategorien erweitert:** `system/hub/restore.py` erkennt dieselben zusätzlichen Kategorien jetzt nativ über ihre Manifest-Pfadpräfixe, sodass Dry-Runs und selektive Upgrades konsistent bleiben.
- **Upgrade-Hilfe korrigiert:** `system/docs/help/upgrade.txt` beschreibt wieder die echte CLI-Syntax inklusive `list`, Dry-Run-Form und der unterstützten Kategorien.
- **Upgrade-Metadaten-Self-Heal ergänzt:** `system/hub/upgrade.py` erkennt leere oder unvollständige Upgrade-Metadaten jetzt explizit, empfiehlt `bach upgrade repair --dry-run`, rekonstruiert bei Bedarf `distribution_manifest` und `dist_file_versions` aus dem aktuellen Distributionsbaum und liefert in `status/check --json` zusätzlich `manifest_entries`, `release_entries` und `repair_recommended`.
- **Release-Katalog-Recovery ergänzt:** `bach upgrade repair` bootstrappt jetzt auch den aktuellen `distribution_releases`-Eintrag inklusive Datum/Kanal aus lokaler Versionsmetadatenlage, und `bach upgrade check --json` hält die Release-/Repair-Felder im normalen Drift-Pfad konsistent.
- **GUI-i18n-Report präzisiert:** `system/hub/lang.py` filtert in JavaScript-Fundstellen jetzt technisches Rauschen wie DOM-IDs, API-Pfade und Console-Strings heraus, extrahiert eingebettete HTML-Texte verlässlicher und erkennt `Allgemein` zusätzlich als deutschen UI-Begriff.
- **Daemon-Pfade in Doku nachgezogen:** Restliche Hilfs- und Service-Texte referenzieren für Session-Profile jetzt konsistent `hub/_services/daemon/...` statt des alten `skills/_services/daemon/...`-Pfads.
- **Session-Steering bleibt bei Fehlern erhalten:** fehlgeschlagene manuelle oder Hintergrund-Trigger löschen vorgemerkte Profil-Hinweise nicht mehr vorzeitig; die Queue wird erst nach erfolgreichem Session-Start geleert.
- **Working-Memory-Cleanup wieder startup-kompatibel:** `system/tools/memory_working_cleanup.py` stellt den bisherigen `cleanup()`-Aufruf jetzt rückwärtskompatibel wieder bereit, sodass `startup.py` die automatische Bereinigung nicht still verliert.
- **Financial-Mail-Servicepfade vereinheitlicht:** GUI, Daemon-Profil, llmauto-Chain und Service-SKILL referenzieren den Mail-Service und sein Schema jetzt konsistent unter `hub/_services/mail/...` statt auf dem veralteten `skills/_services/...`-Layout.
- **Startup-Ressourcenblock wieder korrekt:** `system/hub/startup.py` zählt Agenten, Skills und Help-Dateien jetzt wieder über das aktuelle Layout (`agents/`, `docs/help/`) und die kanonische DB statt über veraltete `skills/_agents`-/`help`-Pfade, sodass der Startup-Block im Live-System keine falschen Nullwerte mehr meldet.
- **Windows-Agenten wieder sauber trackbar:** `system/hub/agent_launcher.py` startet interaktive Agenten auf Windows jetzt in einer langlebigen eigenen Konsole statt nur über den kurzlebigen `start`-Launcher, sodass `bach agent status` und `bach agent stop` dieselbe Session-PID sehen.
- **Run-Statusflächen konkretisiert:** `bach agent list/status --json` liefern jetzt auch `runtime_seconds`, `window_title` und `available_actions`; `bach scheduler status --json` sowie `bach scheduler session status --json` exponieren ebenfalls maschinenlesbare `available_actions`.
- **Agent-Steering-JSON konsistent gemacht:** `clear-steer`-Antworten und Statusflächen spiegeln Queue-Länge, `latest_operator_note` und `latest_operator_note_at` jetzt konsistent, auch bei Dry-Runs und bereits geleerten Queues.
- **Agent-Statusflächen um Queue-Metadaten erweitert:** `bach agent list/status/start/stop/steer/clear-steer --json` zeigen jetzt zusätzlich `latest_operator_note` und `latest_operator_note_at`, sodass Operator-Dashboards veraltete Hinweis-Queues gezielt erkennen und bereinigen können.
- **Agent-Queue-Persistenz gehärtet:** Gestoppte Agenten mit vorgemerkten Hinweisen melden jetzt `status=queued`, `available_actions` inklusive `start`/`clear-steer` und einen kanonischen Temp-Pfad auch ohne laufende PID; unbekannte Agenten werden bei `bach agent steer` nicht mehr stillschweigend als Queue-Ziel akzeptiert.
- **OpenClaw-Referenzstand aktualisiert:** Doku und Release-Planung erfassen jetzt den verifizierten Stand vom 2026-05-30 mit GitHub-Stable `2026.5.27`, sichtbarem Release-Prerelease `2026.5.28-beta.4`, hervorgehobener Containerlinie `2026.5.28-beta.4-slim` und den daraus erneut bestätigten Beobachtungspunkten rund um Runtime-Recovery, strengere Browser-/Channel-Grenzen, Workboard-Handoffs, schnellere Startup-Hot-Paths, `cron.maxConcurrentRuns` und härtere Release-Validierung.
- **ATI-Scanner erweitert:** `system/agents/ati/scanner/task_scanner.py` erkennt jetzt neben `AUFGABEN.txt` auch `TODO.md`, `AUFGABEN.md`, `ROADMAP.md` und `DONE.md`, zählt Tools bei Multi-Datei-Projekten korrekt nur einmal, speichert echte Zeilennummern für Rücksyncs und liest offene ROADMAP-Tabellenzeilen direkt als ATI-Tasks ein.
- **Agent-Runtime-Cache gehärtet:** `system/core/agent_runtime.py` scoped Registries jetzt pro `base_path`, lädt Agent-Module isoliert und invalidiert gecachte Instanzen automatisch bei Code- oder Config-Änderungen.
- **JSON-Smokes wieder stabil:** `system/bach.py` unterdrückt ProSync-Start/Exit-Chatter bei `--json`, sodass `bach agent ... --json` und `bach scheduler ... --json` sauber maschinenlesbar bleiben.
- **Kanonischer DB-Pfad vereinheitlicht:** `system/bach_api.py` schreibt strukturierte `memory`-Einträge wieder in dieselbe Datenbank, die Reader und Handler verwenden.
- **Seal-Status repariert:** `system/hub/seal.py` löst `BACH_DB` wieder robust auf; `bach seal status` läuft im CLI-Smoke erneut grün.
- **Path-Handler wieder importierbar:** `system/hub/path.py` platziert `from __future__ import annotations` wieder an einer gültigen Modulposition, sodass `bach path ...` im normalen CLI-Dispatch nicht mehr als Syntaxfehler herausfällt.
- **Upgrade-JSON-Parität ergänzt:** `system/hub/upgrade.py` unterstützt jetzt `--json` für `list`, `status` und `check`; leere `dist_file_versions` degradieren dabei auch maschinenlesbar sauber auf Nullsummen statt auf Text-Parsing.
- **Upgrade-Listenfehler bleiben maschinenlesbar:** `bach upgrade list --json` gibt bei fehlendem Pfad oder unbekannter Datei jetzt strukturierte JSON-Fehler mit `error_code`, `message`, `file_path` und `hint` zurück, statt den JSON-Modus in Klartext zu verlassen.
- **Smoke-Agent entkoppelt:** `system/tests/test_smoke.py` nutzt für Dry-Run- und Vorstart-Steering-Smokes jetzt den dedizierten `test-agent` samt Queue-Cleanup, damit laufende Live-Sitzungen wie `ati` die Regressionen nicht verfälschen.

---

## [3.9.1-tiramisu] - 2026-05-10

### Fixed

- **Secrets-Handler-Rename abgeschlossen:** CLI-/Setup-Imports auf `hub.secrets_handler` umgestellt, damit der alte `hub/secrets.py`-Name nicht mehr die Python-Stdlib `secrets` shadowt.
- **Packaging-Version synchronisiert:** `setup.py`, `pyproject.toml`, Root-Docs und LLM-Skill-Header auf `3.9.1` nachgezogen.
- **ProSync-Kompatibilität:** `BaseHandler._canonical_db` bevorzugt bei explizitem Fremd-`base_path` dessen lokale `data/bach.db` und nutzt sonst die zentrale `BACH_DB`.
- **Gitignore-Screening:** ASUS-GEI-Sync-Artefakte werden jetzt für Python- und Root-Memory-Dateien ignoriert.
- **Privacy-Hygiene:** Personenbezug im generierten User Manual neutralisiert.
- **Lokale Pfade redigiert:** Hardcodierte OneDrive-/Gesundheits-/Wissensdatenbank-Pfade in Schema, Hilfe und Wartungstools durch Platzhalter bzw. Umgebungsvariablen ersetzt.
- **GUI-Routen bereinigt:** Doppelte Legacy-Routen entfernt, bestehende Dashboard-Routen bleiben über die späteren Handler registriert.
- **Handler-Testisolation:** `BaseHandler` nutzt temporäre Testdatenbanken wieder lokal, während echte Systemläufe weiter auf `bach_paths.BACH_DB` gehen.
- **Privacy-Hygiene:** Private DNA-/Arztsachen-Dateipfade aus Analyse-Tools entfernt; lokale Pfade kommen jetzt aus Environment-Variablen.

---

## [3.9.0-tiramisu] - 2026-05-10

### Highlights

Multi-System-Integration: BACH läuft jetzt synchronisiert auf Laptop und Mac Studio.
ProSync hält lokale Datenbanken über OneDrive-Transit konsistent. Buddha (Telegram-Bot)
nutzt 13 Tools inkl. Web-Search, Wartung und Förderbericht-Pipeline. 5 Backends
(Ollama, Claude CLI, Codex, Claude API, OpenAI) sind über /backend switchbar.

### Neu

- **ProSync DB-Sync:** Lokale DB pro System (`~/.bach/bach.db`), OneDrive-Transit-Hub für Cross-System-Sync. 137 syncbare Tabellen, Schema-Drift-sicher, Pull-at-Start + Push-at-Stop + atexit-Hook
- **`_canonical_db` Handler-Migration:** 55 Handler von hardcoded `data/bach.db` auf `self._canonical_db` migriert — DB-Standort ist jetzt location-independent via `bach_paths.BACH_DB`
- **Buddha Chat Services:** Multi-Backend Telegram-Bot mit 5 Backends (Ollama, Claude CLI, Codex, Claude API, OpenAI), Control API (:8081), Web Dashboard, cross-platform System Tray
- **13 Buddha Tools (TOOLS_SAFE):** web_search, task_manage, maintain, delegate, foerderbericht, memory_search, fact_store, lesson_store, wiki_search, system_status, help_search, calendar, notes
- **Förderbericht-Pipeline:** DSGVO-konforme Anonymisierung (Phase 1) als Buddha-Tool, ICF-Prompt-Generierung, synthetische Testdaten
- **Model-Switching & Delegation:** Claude/Codex→Buddha via `/api/chat`, Buddha→Claude/Codex via `delegate`-Tool mit Rekursionsschutz (max Depth 2)
- **Cross-Platform Launcher:** `start/bach.sh` mit 4 Subkommandos (chat, gui, status, stop), Server-Modus via `BACH_HOST` env
- **Installer ProSync-Setup:** `bach setup prosync` mit `--multi-system`/`--single-system` Flags, Config-gesteuert
- **Schwarm-Muster komplett** (SQ016): Alle 5 Muster aktiv (Hierarchie, Stigmergy, Spezialist)
- **5 neue Therapie-Skills** (B30/SQ046 Phase 2): ACT, DBT, Stabilisierung, Trauma-Psychoedukation, Expositionsbegleitung
- **Agent-Personas & Name-Resolution** (Migration 034): Multi-Strategie Namensauflösung, Display-Names, Persona-Injection, 20 Default-Personas
- **Security Gate für Erweiterungen:** Code-Injection-Scan bei `plugins load` und `skills install`, Quarantäne, Manifest-first Plugin-Prüfung, Fail-closed Setup-Guards
- **MCP-Setup-Härtung:** Allowlist-Validierung bei `bach setup mcp` und `bach setup n8n`
- **Editable-Install für `bach_api`:** `pip install -e .` funktioniert jetzt aus dem Repo-Root
- **Strukturierte `bach_api`-Kernmodule:** `task`/`memory` mit echten Methoden, `dir(...)` discoverbar
- **Memory-/Wiki-Provenance Views:** Heuristische Quellen-/Evidenz-/Privacy-Analyse
- **Maschinenlesbare Status-Flächen:** `--json` für Agent-/Scheduler-Status

### Entfernt

- **Legacy Prompt-Manager (PyQt6):** 2283 Zeilen Desktop-App entfernt — Web-basierter Prompt-Generator bleibt verfügbar
- **Deprecated Scanner:** Tote `/scanner`-Route und Template entfernt
- **OneDrive Lock-Artefakte:** 10 `.lock.user`-Dateien aus Tracking entfernt, Pattern in `.gitignore`

### Bugfix

- **`hub/secrets.py` → `secrets_handler.py`:** Stdlib-Shadow aufgelöst — ddgs-Import für Web-Search repariert
- **system_prompt_buddha.txt Pfad:** Von hardcoded `~/services/bach/...` auf `bach_paths.DATA_DIR` umgestellt
- **GUI Server Version:** Auf 1.1.8 synchronisiert (nav.js + server.py)
- **Registry-Watcher:** Trennt Core-Dateien von historischen/stale DB-Einträgen, keine False Positives mehr
- **Usecase-Runner:** Fallback auf manuellen Datenmodus bei fehlender Workflow-Datei
- **Self-Heal CLI/API:** `bach mem write/read`, `bach wiki read`, `bach task add` ID-Ausgabe
- **CLI-Dry-Run:** `--dry-run` wird im generischen Handler-Dispatch durchgereicht
- **JSON-CLI-Ausgaben:** `--json` unterdrückt Idle-/EOD-Chatter
- **Git-Hygiene:** `.gitignore` für SQLite-Sidecars und Doc_Update_Reports
- **agent_launcher.py:** cp1252 Encoding-Fix, Experten-Display-Name-Resolution
- **Fail-closed Setup-Configs:** Ungültige Claude-JSON-Dateien brechen Setup ab statt Überschreibung

### Dokumentation

- **Release-Verweise** und **NEXT_RELEASE** bereinigt
- **OpenClaw-Abgleich:** Zweimal verifiziert (2026-05-08, 2026-05-09)
- **Agent-Hilfe** und **Provenance-Dokumentation** aktualisiert
- **Versionierung:** Bump auf v3.9.0-tiramisu

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
