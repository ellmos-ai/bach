# BACH ROADMAP - Strategische Vision

**Stand:** 2026-07-11 | **Version:** 4.3.57

Copyright (c) 2026 BACH Contributors. Alle Rechte vorbehalten.

> Die ROADMAP definiert Vision und Phasen. Konkrete Tasks siehe: `bach task list`
> Post-Release-Details (SQ-Nummern): ehemals `BACH_Dev/ROADMAP.md` — jetzt hier konsolidiert.


<!-- ellmos-sovereign Langzeit-Vision -->
## Langzeit-Vision: BACH Core + Module (Projekt ellmos Sovereign)

Parallel entsteht in `.OS/sovereign-private` ein **modulares, besser wartbares BACH**, das
BACHs gute Bestandteile als eigenstaendige Module (`.MODULES`) erntet. BACH bleibt dabei
unangetastete Quelle der Wahrheit und **entscheidet selbst, wann** es Schritte uebernimmt.

**Langfristige Richtung fuer BACH (Langzeitprojekt, kein Zwang):**

1. Module schrittweise **auf BACH-Niveau** bringen.
2. Wo ein Modul **gleichwertig oder besser** ist als BACHs eigener Teil: BACHs
   Eigenimplementierung durch das Modul **ersetzen** (eine Quelle der Wahrheit, kein Feature-Sync).
3. Was zwingend bleiben muss, damit **BACH BACH bleibt** (Integration/Verdrahtung), wandert in
   einen schlanken **BACH Core** — das ist dann das eigentliche BACH: Core + eingebundene Module.

Methodik/Analyse: `.OS/sovereign-private/_dev/CLUSTER_ANALYSE_PLAN.md`.
Vorbild bereits in dieser ROADMAP: *"clutch als Routing-Engine uebernehmen"* (Modul ersetzt Fork).

---

## Strategiemodell: Core, Membran, Endozytose, MasterBach [P 2026-06-19]

BACH muss **nicht** vollständig synchron mit allen externen Modulen, Skills, Repos oder
LLM-Umgebungen sein. Wichtiger ist, dass BACH auf dem jeweiligen System **kohärent**,
anschlussfähig und lernfähig bleibt. Für die Weiterentwicklung werden drei Wege gesehen:

### A) BACH bleibt wie es ist

Vorteil: lokal stark, sofort nutzbar, besonders gut für integrierte lokale LLM-Nutzung.
Nachteil: externe LLMs, capability-spezifische Usecases und auswärtige Innovationen bleiben
schwer andockbar oder müssen als Ganzes mitgeschleppt werden.

### B) BACH modularisiert sich schrittweise

Verstreute Tool-/Skill-/Handler-/Service-/Script-/Workflow-Bereiche werden in **echte
Einheiten** überführt, die auch außerhalb von BACH sinnvoll bestehen können. BACH bindet diese
Einheiten wieder an und entfernt danach die verstreuten Altteile.

Leitlinie:

1. Ein Bereich wird nur dann Modul, wenn er **allein sinnvoll** ist.
2. Sobald er Modul ist, wird dieses Modul die **eine Quelle der Wahrheit**.
3. BACH konsumiert das Modul über Adapter, statt Fork + Modul parallel zu pflegen.
4. Nach grünem Parallelbetrieb werden die alten verstreuten Teile archiviert oder entfernt.

### C) BACH lernt von seiner Umgebung (Endozytose)

BACH erhält die Fähigkeit, seine Umgebung aktiv zu scannen und zu bewerten:

1. Neue Inputs im System entdecken: Skills, Tools, Handler, Repos, Sidecars, Module,
   Connectoren, Workflows, Skripte.
2. Auf Anschlussfähigkeit prüfen: Überschneidung mit BACH-Domänen, Namensähnlichkeit,
   ähnliche Fähigkeiten, fehlende eigene Bausteine, erkennbare Qualitätsmerkmale.
3. Als **Nahrung oder Fremdkörper** klassifizieren:
   Nahrung = passt zu BACH, erweitert BACH sinnvoll oder deckt eine eigene Schwäche ab.
4. Daraus strukturierte Tasks erzeugen, die LLMs prüfen:
   vergleichen, testen, Adapter vorschlagen, Import vorbereiten, Risiken bewerten.
5. Nur gegatete Übernahmen akzeptieren:
   Parallelbetrieb, Tests, Rollback, dann erst Integration oder Extraktion als Modul.

Wichtig: Endozytose ersetzt keine Struktur. Ohne klare Grenzen würde BACH sonst nur neuen
Wildwuchs aufnehmen. Deshalb ist C ein **Lernmechanismus**, aber kein Ersatz für B.

### ✅ ENTSCHIEDEN [U 2026-07-03]: B + C — Rückspiegelung der Module

Der User hat sich der Empfehlung angeschlossen (Session 2026-07-03, nach Selbsterfahrungstests
ellmos-tests B/O/E 3.1/4.29/4.2 und Wartungslauf): **BACH bleibt nicht wie es ist (A), sondern
spiegelt zunehmend die modularisierten Komponenten in sich zurück** — B als Strukturstrategie,
C als Evolutionsstrategie. Begründung (empirisch belegt am 2026-07-03):

1. Monolith-Drift real: 5 gefixte Bugs waren interne Umstrukturierung ohne Referenz-Nachzug
   (maintain.py-Pfade, consolidate-Alias, Doku-Drift, Registry-Duplikate).
2. Rückspiegelung funktioniert: ellmos-tests (geerntet aus tools/testing) testete BACH heute
   als eigenständiges Modul erfolgreich.
3. Gatung bleibt Pflicht: Modul ersetzt Eigenteil erst bei Gleichwertigkeit, nach
   Parallelbetrieb mit grünen Tests; Altteil archivieren, nicht löschen. Core bleibt BACH.

**Reihenfolge:** ① clutch (Task 1150, Migration vorbereitet) → ② tools/testing durch
ellmos-tests-Adapter ersetzen (dabei „upstream"-Widerspruch im ellmos-tests-SKILL.md auflösen)
→ ③ llmauto/notespace/market gemäß ease-Liste (`sovereign-private/ROADMAP.md`, Cluster-Report).

### Empfohlene Richtung

Nicht A allein. Nicht B allein. Nicht C allein.

**Empfohlen ist: B als Strukturstrategie, C als Evolutionsstrategie.**

- B definiert den **Körperbau**: BACH Core + angebundene Module.
- C definiert den **Stoffwechsel**: BACH scannt, bewertet, erzeugt Prüf-Tasks und übernimmt
  nur das, was lokal wirklich passt.
- A bleibt als aktueller Betriebszustand legitim, ist aber keine überzeugende Langfristlinie.

### Zielbild

#### 1. BACH Core

Der Core behält alles, was BACH als Operating System ausmacht:
Session-/Startup-/Shutdown-Logik, Scheduler, SharedMemory, DB-Verträge, Handler-Registry,
`bach_api`, CLI/API-Grenzflächen, Upgrade/Restore/Paths/Secrets und die zentrale Verdrahtung.

#### 2. Membran

Die Membran ist die bewusste Grenze zwischen BACH und seiner Umgebung:

- scannt neue oder geänderte externe Bausteine
- erkennt Ähnlichkeiten und Anschlussstellen
- schützt vor blindem Import
- erzeugt stattdessen reviewbare Aufnahme-Tasks

#### 3. Endozytose-Pipeline

Standardfluss:

`scan -> match -> klassifizieren -> Task erzeugen -> LLM-Prüfung -> Adapter/Import/Modulisierung -> Parallelbetrieb -> Altteil entfernen`

#### 4. Exozytose / Export

BACH baut parallel seine Export-Fähigkeiten aus, damit gute interne Fähigkeiten sauber nach
außen gegeben werden können: bessere Skill-, Tool-, Workflow- und Modul-Exporte statt
roher Kopien. So wird BACH nicht nur aufnahmefähig, sondern auch **abgabefähig**.

#### 5. MasterBach (optional, spätere Stufe)

Wenn viele Systeme BACH nutzen, können **akzeptierte** Erkenntnisse, Module, Adapter,
Policies und Lessons in eine Art MasterBach gespiegelt werden. Nicht Rohzustände und nicht
private Nutzerdaten, sondern kuratierte, freigegebene, systemisch brauchbare Verbesserungen.

### Entscheidungsregel

Die Kernfrage lautet künftig nicht mehr: *"Muss BACH synchron bleiben?"*

Sondern:

1. Soll etwas **im Core** bleiben?
2. Soll es als **Modul** die eine Quelle der Wahrheit werden?
3. Oder soll BACH es zunächst nur **erkennen, prüfen und als Lernchance** behandeln?

Damit bleibt BACH lokal stark, muss aber nicht statisch bleiben. Es wird zu einem System,
das sich seiner Umgebung anpasst, ohne seine Identität oder Wartbarkeit zu verlieren.

---

## Vision

BACH definiert sich als **Personal Agentic Operating System**. Es entwickelt sich zu einem autonomen, lernfaehigen System mit:

- **Kognitives Memory-System** (menschliches Gedaechtnis als Vorbild)
- **Selbststaendige Sessions** (Headless AI ohne User-Interaktion)
- **Aktive Konsolidierung** (Lernen, Vergessen, Zusammenfassen)
- **Multi-Partner Delegation** (Claude, Gemini, Ollama, lokale Modelle)

---

## Geplant: clutch als Routing-Engine übernehmen (M8) [C 2026-06-14]

BACH betreibt aktuell einen **eigenen Fork** der clutch-Idee (`hub/_services/delegation/` +
`hub/clutch.py` + `hub/partner.py`). Parallel ist das eigenständige Package **clutch**
(`.TOPICS/.AI/.MODULES/clutch`, `ellmos-ai/clutch`) zur state-of-the-art Routing-Anwendung
ausgebaut worden: Engine + Kimi (CLI/API/Ollama, **API live getestet**), zweck-/bildbewusstes
Routing, Modell-Discovery, CLI, Service-Layer (Sessions/Prompts/Profile/ChatRuntime), Web-UI,
Toolset-Permissions (default-deny), 230 Tests grün.

**Leitlinie:** clutch ist Vorrang/state-of-the-art, **BACH übernimmt** (eine Quelle der Wahrheit,
kein Feature-Sync mehr). BACH soll den Umgang mit dem Modul prüfen und seinen Fork ablösen.

- **Task:** `bach task show 1150` (Kategorie integration, HIGH; alte Referenz 1135 war fremdbelegt/erledigt — korrigiert 2026-07-04).
- **Anleitung + Deckungs-Check (gegatet):** `.TOPICS/.AI/.MODULES/clutch/docs/BACH_MIGRATION.md`
- **Gatung:** erst Compat-Adapter + Parallelbetrieb + grüne BACH-Tests, dann Fork archivieren
  (nicht löschen). DB-Tabellen `clutch_fitness`/`clutch_fahrtenbuch`/`partners` bleiben Persistenz.

---

## Entwicklungsprinzip: Systemisch First

> **BACH wird als wiederverwendbares System entwickelt, nicht fuer einen einzelnen User.**

Jede Funktion muss fuer ALLE zukuenftigen User funktionieren. Die Entwicklung
folgt der Reihenfolge:

1. **Systemisch** - Wiederverwendbare Services, Agents, Workflows
2. **CLI First** - Alles ueber CLI steuerbar
3. **User-Daten** - Import/Test mit lokalen Entwicklerdaten

Der aktuelle Maintainer nutzt BACH aktiv und testet mit lokalen Daten.
Alle Workflows (Versicherungs-Import, Arztbericht-Scan, Steuer-Export)
müssen aber generisch sein und für jeden neuen User funktionieren.

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

Der OpenClaw-Abgleich vom 2026-07-05 bestätigt den nächsten BACH-Fokus
klar in Richtung sichere Erweiterbarkeit, robuste Agenten-Laufzeit und
saubere Steuer-/Statusoberflächen. Relevant sind nicht die breite
Messenger-Abdeckung, sondern manifest-first Plugin- und Provider-Metadaten,
fail-closed Tool-Setups, Scans vor der Installation von
Skills/MCP-Servern/Plugins, API-Parität für Agentenflächen, Checkpoint-
Steuerung und low-cardinality Telemetrie. Als Referenzstand gilt dabei:
GitHub markiert `openclaw 2026.6.11` als aktuelle Stable-Linie; auf der
GitHub-Releases-Seite ist `2026.7.1-beta.2`, veröffentlicht am
2026-07-05 um 09:10 UTC, jetzt das neueste sichtbare Prerelease.
Frisch relevant aus Stable und Beta sind zusätzlich GPT-5.6-
Modellfamilien-Support über Katalog-, Capability- und Runtime-Pfade,
`openclaw attach` für externe Harness-Anbindung an bestehende Sessions,
Telegram-Codex-Pairing samt Mid-Run-Steering und Reply-Recovery,
exit-getriggerte Cron-Läufe mit sauberem Detach sowie gescopte
Conversation-Capability-Profile und deutlichere Doctor-/Install-
Diagnostik. Neu konkretisiert die aktuelle Beta zusätzlich ClawRouter-
gestützte Modell-Discovery sowie robustere Recovery bei Device-
Approvals und Plugin-Installationen. Die zuvor wichtigen Signale bleiben
ebenfalls relevant:
automatische Fast-Mode-Wechsel für kurze Turns, robustere Modell-Routen,
sicherere Session- und Channel-Zustände, erhaltene Trusted Policies bei
Hook-Komposition, reichhaltigere Telegram-/Slack-/Discord-Zustellung,
robustere Recovery in Agenten- und Session-Läufen, stärkere Codex-
Integration, explizite Opt-in-Defaults für Websuche mit Herkunftsspur
sowie härtere Secret-/Privacy-Scrubs.
Aus den aktuellen offiziellen Hinweisen erneut bestätigt sind
workspace-scoped Plugin-Metadaten-Snapshots auf Hot Paths,
Install-Hinweise für fehlende offizielle Erweiterungen, kollisionssichere
Session-Memory-Captures bei wiederholtem `/new` oder `/reset`,
Autorisierungs-Hooks für Inline-Tool-Dispatch, SecretRef-sichere
Runtime-Config-Snapshots, queue-unabhängiges Steering an sicheren
Checkpoints, maschinenlesbare Cron-/Run-Status und restriktivere Scopes für
globale Memory-Toggles. Neu sichtbarer geworden sind außerdem
lokalisierte Onboarding-/Setup-Flows, blockierendes `cron run --wait` für
Automationen, xAI-Grok-OAuth ohne API-Key für berechtigte Abos,
konfigurationsgebundenes Warm-Caching für `resolvedSkills`, Ambient-Turns für Gruppenräume, ACP- und
Subagent-Fallback-Semantik in isolierten Scheduler-/Cron-Läufen, per-Agent
scopte Codex-MCP-Server samt Approval-Defaults, das harte Ablehnen
fehlerhafter Extension-Metadaten, MIME-Sniffing vor agentensichtbarer
Dateiverarbeitung, robuste Config-Persistenz bei fehlerhaften Zuständen,
Windows-Sandbox-Blocklisten für `USERPROFILE`, klarere
Auth-/Onboarding-Flag-Weitergabe, Mid-Run-Steering per Queue, explizite
Gateway-Scopes für Browser-Steuerung, Heartbeat-Metadaten auf Agent-Events,
Session-Erzeugung vor dem ersten Agent-zu-Agent-Send sowie
package-installierte Docker-Validierungslanes. Neu seit dem letzten Abgleich
sind außerdem Exec-Approval-Härtung rund um Skill-Ladepfade, ein
gebündeltes Policy-Plugin für Doctor-Linting und policy-gestützte
Channel-Checks, per-Agent-`localModelLean`, providerweite OpenRouter-
Routing-Defaults, klarere Entscheidungen zur Pflege veralteter Tasks,
Browser-Dialog-Snapshots mit `blockedByDialog`, runtime-neutrale
APT-Build-Args für Container, Startup-Kostenattribution bei
Gateway-Neustarts, ein repo-lokaler Codex-Review-Workflow für Dirty-Work-
und PR-Closeout-Schleifen, ein expliziter i18n-Hardcoded-Copy-Report für
die UI, Grace-Window-Liveness-Dämpfung, erweiterte Bootstrap-Kontexte über
`AGENTS.md`, `TOOLS.md`, `USER.md` und `SOUL.md`, Voice-Run-Control mit
Status/Cancel/Steer/Follow-up während aktiver Consult-Sessions sowie neue
Meeting-Notes-Plugin-Flächen, damit Browser-/Gateway-Healthchecks beim
Kaltstart weniger Fehlalarm produzieren und Runtime-Control konsistenter
wird.
Den i18n-Punkt deckt BACH jetzt mit `bach lang report` ab: der Handler scannt
das aktuelle Layout (`docs/help`, `gui/templates`, `gui/static/js`, `agents/`,
`skills/workflows`, `tools/`), prüft die Release-Artefakte gegen das Manifest,
liefert Fundstellen mit Datei/Zeile/Typ und zeigt offene harte DE-Copy je
Namespace. Seit dem 2026-06-12 nutzt `bach lang scan --namespace gui`
dieselben gefilterten Hardcoded-Copy-Fundstellen wie `bach lang report`,
sodass Python-Docstrings, SQL-Schnipsel und ähnliches GUI-Rauschen nicht
mehr in die Release-Artefakte gelangen. Der aktuelle GUI-Live-Befund vom
2026-06-12 meldet 166 eindeutige GUI-DE-Strings bei 253 Fundstellen; alle
253 Fundstellen sind im Manifest und den Locale-Artefakten abgedeckt,
offene GUI-DE-Einträge gibt es aktuell keine mehr. Parallel wurden
sichtbare Oberflächen in `persoenlich`, `memory`, `steuer` und
`workflow_tuev` auf echte Umlaute gehoben und die Release-Artefakte auf
17.593 Übersetzungen aktualisiert.
Neu geschlossen ist außerdem die bisherige Restlücke bei der Workflow-
Frontdoor der Usecases: Zusätzlich zu `system/skills/workflows/software.md`
decken jetzt auch `assistent.md`, `care-modul.md`, `datenmodul.md`,
`dokumentenmodul.md`, `finanzen.md`, `gesundheit.md`, `haushalt.md`,
`karriere.md`, `reflection-status.md`, `selbstmanagement.md`,
`therapie.md` und `wissen.md` die früher manuellen Domänen ab. Der
Live-Resolver-Check vom 2026-06-17 zeigt damit 50 workflowgebundene und
0 manuelle Usecases statt 24 zu 26; für T01 verschiebt sich der Fokus damit
von fehlenden Workflow-Dateien auf echte Domänen-Retests und
Integrationsabdeckung.
Für BACHs eigene T01-Retest-Schiene ist außerdem jetzt wichtig:
`bach usecase run-all [workflow] [--dry-run]` bereitet Sammeltests
wirklich vor, kann ohne Workflow-Argument alle 50 Usecases abdecken und
markiert `last_tested` nur außerhalb von Dry-Runs.
Die erste Stufe der Cache-Invalidierung ist jetzt in BACHs Agent-Runtime
umgesetzt; für Skill-/Plugin-Reset-Hooks bleibt weitere Verdrahtung offen.
Neu bestätigt bleibt außerdem ein ergonomischer Workspace-/Pfadzugriff;
BACH deckt das mit `bach path` als strukturierter CLI-/API-Oberfläche ab.
Neu ergänzt ist außerdem eine maschinenlesbare Upgrade-Fläche:
`bach upgrade list/status/check --json` liefert strukturierte Versions-,
Release- und Drift-Payloads, sodass Release-Validierung und Dashboarding
nicht mehr auf Text-Scraping angewiesen sind.
Seit dem 2026-05-30 deckt `bach upgrade repair [--dry-run] [--version <tag>]`
nicht nur Manifest- und Datei-Versionen ab, sondern bootstrappt bei
leerem `distribution_releases` auch den aktuellen Release-Eintrag aus
README-/CHANGELOG-Metadaten. `bach upgrade check --json` liefert
`manifest_entries`, `release_entries`, `repair_recommended`,
`current_version` und `current_release_registered` jetzt konsistent auch
im normalen Drift-Pfad. Der Live-Check vom 2026-05-30 zeigt damit
4.720 verfolgte Dateien, 4.722 Manifest-Einträge und 1 registrierten
Stable-Release-Eintrag (`v3.12.4-earth`, 2026-05-17).
Neu nachgezogen ist außerdem, dass Scheduler-Doctor/Status/Jobliste und
der GUI-Daemon dieselbe kanonische BACH-Datenbank verwenden; der
Live-Check vom 2026-05-24 zeigt damit konsistent
`~/.bach/bach.db`.
Neu im Daily-Care-Lauf vom 2026-06-01 ist außerdem, dass weitere
Restpfade auf die kanonische `BACH_DB`-Oberfläche gehoben wurden:
`system/tools/mcp_server.py` nutzt jetzt dieselbe Shared-DB wie die
Handler, der DB-Viewer bevorzugt `BACH_DB` beziehungsweise
`~/.bach/bach.db`, und die verbleibenden Help-Texte benennen konsistent
`BACH_DB` statt `system/data/bach.db`.
Neu im Daily-Care-Lauf vom 2026-06-18 ist außerdem, dass jetzt auch der
Root-CLI-Vorpfad in `system/bach.py` dieselbe kanonische `BACH_DB`
nutzt: ActivityTracker, Session-Ticks, EOD-/Idle-Finalisierung und der
`folders`-Hilfspfad laufen nicht mehr gegen ein veraltetes
`system/data/bach.db`. Der Live-Retest zeigte danach wieder normale
Read-Only-Läufe für `bach task list --filter clutch`, `bach reflection
status`, `bach usecase run 50 --dry-run` und `bach --startup quick
--mode=silent --partner=codex`.
Neu im Daily-Care-Lauf vom 2026-06-19 ist zusätzlich, dass
`bach setup check` globale MCP-Installationen robuster über
`npm root -g` und direkte Paketpfade prüft, statt über langsamere
`npm list -g <paket>`-Aufrufe zu raten. Außerdem toleriert
`bach scheduler start --bg` jetzt deutlich langsamere Windows-/
OneDrive-PID-Erzeugung mit einer monotonic-basierten 12-Sekunden-
Deadline. Der heutige Retest bestätigte `test_setup_handler.py`,
`test_scheduler_handler.py`, `test_bach_paths.py`, den isolierten
Startup-Archivfilter, `bach setup check`, den kompletten
`test-agent`-Steuerzyklus sowie `task list --filter clutch`,
`reflection status` und `usecase run 50 --dry-run`.
Neu im Daily-Care-Lauf vom 2026-06-21 ist zusätzlich, dass
`system/hub/db_sync.py` ProSync-Transit-Backups aus OneDrive vor dem
Merge lokal unter `~/.bach/temp/prosync/` staged und problematische
Kandidaten nach Cloud-Timeouts oder `disk I/O error` für 30 Minuten in
`~/.bach/sync_state.json` deferiert. Dadurch blockieren fehlerhafte
Transit-Dateien Read-Only-CLI- und JSON-Befehle nicht mehr bei jedem
Startup erneut. Verifiziert wurden
`python -m pytest system/tests/test_db_sync_handler.py -q`
(`45 passed`), `python -m pytest system/tests/test_prosync_race.py -q`
(`3 passed`), ein echter `sync_on_start()`-Repro mit OneDrive-Timeout
sowie die anschließenden Smokes `python bach.py --startup quick
--mode=silent --partner=codex`, `python bach.py agent doctor test-agent
--json`, der vollständige `test-agent`-Steuerzyklus,
`python bach.py usecase run 50 --dry-run`, `python bach.py upgrade check
--json` und `python bach.py task list --filter clutch`.
Neu im Daily-Care-Lauf vom 2026-06-23 ist außerdem, dass der generische
Handler-Dispatch `dry_run` jetzt signatursicher statt per blindem
`TypeError`-Fallback weiterreicht, `bach --partner delegate --score`
die echte Scorer-Quelle (`clutch` vs. Legacy) aus dem Compat-Layer
meldet und der ProSync-Fail-soft-Pfad nur noch auf bekannte transiente
OneDrive-/SQLite-Fehler anspringt. Verifiziert wurden
`python -m pytest system/tests/test_core.py system/tests/test_partner_handler.py system/tests/test_startup_handler.py system/tests/test_db_sync_handler.py -q`
(`116 passed`) sowie die Smokes
`python bach.py --partner delegate "Migration pruefen" --score --dry-run`,
`python bach.py --startup --mode=text --dry-run` und
`python bach.py help partner`.
Etwas höher gerückt sind zudem deutlichere Recovery- und Startup-Hinweise
bei CLI-/Config-Fehlern sowie reproduzierbare Release-Validierung. Weiter
beobachtet, aber noch nicht priorisiert, sind vor allem
modellidentitätsbasierte Prompt-Injektion, bounded
`before_agent_finalize`-Retries und die Frage, welche Form von
Backend-Fallback-Semantik zu BACHs Multi-Partner-Architektur passt.

| ID | Thema | Status | Notiz |
|----|-------|--------|-------|
| SH-001 | CLI/API Self-Heal: `mem write`, `wiki read`, Task-ID bei `task add` | DONE | Implementiert und mit Unit-Tests abgesichert (2026-04-30) |
| SEC-PLUGIN-001 | Skill-/Plugin-/MCP-Install-Scanner | DONE (Stufe 1) | `skills install`, `plugins load` und lokale MCP-Config-Pfade scannen statisch, blockieren Code-Injection-Muster fail-closed und legen Quarantäne-Kopien mit `report.json` an |
| SEC-PLUGIN-002 | Manifest-first Plugin-Metadaten | TEILWEISE | `bach plugins inspect` liest Aktivierung, Capabilities, Provider-/Model-Catalogs und Setup-Metadaten ohne Runtime-Import; `plugins load` speichert diese Metadaten und blockiert fehlende Manifest-Dateireferenzen fail-closed |
| SEC-PLUGIN-003 | Fail-closed Tool-Setup-Checks | DONE | Plugin-Manifeste mit `shell`-/`desktop`-/`mcp`-Setupflächen brauchen jetzt `setup.fail_closed=true` plus passende `setup.checks`; `plugins inspect/load` blockieren unsichere Verträge vor Runtime-Code, und bestehende Claude Hook-/MCP-Config-JSONs werden vor Setup-Schreibzugriffen fail-closed validiert |
| SANDBOX-002 | Subprocess-Isolation | TEILWEISE | Capabilities/Allowlist (DONE): fail-closed Shell-Allowlist, DB-Persistenz, policy/allow/deny Ops, 72 Tests. Ressourcenlimit (offen, OS-spezifisch) |
| API-SURFACE-001 | Agent-/Prompt-API-Parität | DONE | `bach_api` exportiert jetzt die dokumentierten Module `agent`, `agents` und `prompt`; Agenten-Usecase per Regressionstest abgesichert |
| OPS-TELEM-001 | Low-cardinality Telemetrie | OFFEN | OpenTelemetry-inspiriert, aber lokal/privacy-first: Model-Calls, Tool-Loops, Agentenstarts und Fehler ohne sensible Payloads messen |
| OPS-I18N-001 | i18n-Drift-Report & Layout-aware Scan | DONE | `bach lang report` prüft Manifest/Locale-Artefakte, liefert Fundstellen mit Datei/Zeile/Typ und scannt das aktuelle Layout inklusive HTML/JS/Markdown auf harte DE-Copy; `bach lang scan --namespace gui` nutzt jetzt dieselben gefilterten GUI-Fundstellen wie der Report, aktueller GUI-Live-Befund: 166 eindeutige Strings bei 253 Fundstellen und 0 offenen Einträgen (2026-06-12) |
| OPS-PATH-001 | Strukturierte Pfadoberfläche | DONE | `bach path` liefert kanonische System-/Workspace-/DB-Pfade, JSON-Ausgaben, Resolve-/Validate-Helfer und DB-Overrides für Operatoren, API und Automationen |
| OPS-CACHE-001 | Workspace-scoped Runtime-Cache-Invalidierung | DONE | `core.agent_runtime` trennt Registries jetzt pro `base_path`, lädt Agent-Module isoliert und invalidiert gecachte Instanzen automatisch bei Code-/Config-Änderungen |
| OPS-RECOVERY-001 | Agent-Preflight & Recovery-Hinweise | DONE | `bach agent doctor [name] [--json]` prüft Claude CLI, Laufzeitverzeichnisse, SKILL.md und stale PID-Dateien und liefert konkrete Start-/Recovery-Schritte |
| OPS-RECOVERY-002 | Scheduler-/Session-Preflight & Recovery-Hinweise | DONE | `bach scheduler doctor [--json]` und `bach scheduler session doctor [--json]` prüfen Skripte, PID-Zustand, DB-/Config-/Profil-Flächen, bereinigen stale PID-Dateien und liefern konkrete Start-/Recovery-Schritte |
| OPS-RUN-001 | Aktive Laufsteuerung langer Agenten-/Scheduler-Runs | TEILWEISE | `bach agent list/start/stop/pause/resume/checkpoint/steer/clear-steer/status --json` sowie `bach scheduler status/jobs/session status --json` liefern maschinenlesbare Operator-/Run-Status-Flächen ohne Idle-/EOD-Chatter; `bach chain pause/resume/steer` steuert llmauto-Ketten an sicheren Checkpoints, `bach agent pause/resume` ergänzt kooperative Pauseanforderungen für laufende Agenten mit verschachteltem `operator_control`-Snapshot (`pause_requested`, `pause_reason`, `pause_requested_at`, `pending_steer_count`, `latest_steer_message`, Dateipfade, `available_actions`) und direkter Spiegelung in `OPERATOR_NOTES.md`, `bach agent checkpoint` bestätigt sichere Agenten-Checkpoints jetzt explizit über `operator_checkpoint.json`, `last_checkpoint_at`, `last_checkpoint_message`, `latest_control_request_at` und `awaiting_checkpoint_ack`, `bach agent steer` kann Hinweise jetzt auch für gestoppte Agenten vormerken und spiegelt sie über `pending_operator_notes`, `latest_operator_note`, `queued_for_next_start` und `status=queued`, der nächste `bach agent start` übernimmt diese Queue bewusst weiter und injiziert vorgemerkte Hinweise direkt in die generierte Session-`CLAUDE.md`, `bach agent clear-steer` räumt veraltete Hinweis-Queues jetzt gezielt auf, `bach scheduler pause/resume/steer/clear-steer --json` ergänzt denselben Kontrollpfad jetzt scheduler-weit mit globaler Due-Job-Pause, Status-Snapshots und vorgemerkten Hinweisen für Job-/Chain-Läufe, llmauto importiert diese scheduler-weiten Hinweise beim echten Chain-Run jetzt aus `BACH_SCHEDULER_OPERATOR_STEER` in die reguläre Chain-Queue, sodass sie den nächsten sicheren Modell-Checkpoint wirklich erreichen, `bach scheduler session pause/resume/steer/clear-steer --json` liefert für profilbezogene Auto-Runs zusätzlich mutierende Kontrollantworten mit Queue-/Zeitstempel-Snapshots (`latest_steer_message`, `latest_steer_requested_at`), Agent-Starts tragen jetzt zusätzlich pro Lauf `permission_mode`, `allowed_tools` und `max_turns` als explizite Guardrails aus CLI oder SKILL-Frontmatter mit, und Doctor-/Status-Flächen markieren die veraltete pyautogui-Session-Automation jetzt sauber als deprecated samt `--force`-Guard; offen bleibt vor allem tieferes Active-Run-Steering innerhalb bereits laufender Scheduler- und Agenten-Innenschleifen sowie feinere per-Agent-Scope-Kontrolle |
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
**BACH als anbietbarer MCP-Server** — Bundle-Split + ControlCenter-Control-Plane (VISION/OFFEN), Detail-Sektion am Dokumentende

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

> Vollständige Erledigungsliste: in dieser Roadmap und im `CHANGELOG.md` öffentlich zusammengefasst.

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
| Policy-Entscheidungen | In ROADMAP-/CHANGELOG-Historie öffentlich konsolidiert; interne ENT-Details bleiben privat |
| BACH als MCP-Server (Machbarkeit) | ROADMAP-Sektion „BACH als anbietbarer MCP-Server" |

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
| **4.3.3** | 2026-05-07 | **Usecase-Runner gegen Kategorie-/Pfad-Lücken gehärtet (`bach usecase run` fällt bei fehlender Workflow-Datei nicht mehr hart aus); öffentliche Release-Planungsreferenzen bereinigt; OpenClaw-Abgleich auf `2026.5.5` aktualisiert.** |
| **4.3.4** | 2026-05-07 | **Registry-Watcher auf aktuelles Skills-/Tools-Layout und Startup-Selbstcheck ausgerichtet: rekursive Layout-Scans, Trennung von actionable vs. stale/historical Eintraegen und keine False-Positive-Warnung mehr bei sauberem Core-Bestand.** |
| **4.3.5** | 2026-05-07 | **Agent-Start loest Experten-Display-Names jetzt auch dann korrekt ueber `skill_path` auf, wenn DB-Name und Skill-Verzeichnis abweichen (`Theodor` -> `steuer`); Release-/QA-Notizen an den verifizierten Stand angepasst.** |
| **4.3.6** | 2026-05-08 | **`bach --maintain docs report` wieder funktionsfähig gemacht (Subcommand-Passthrough statt hartem `check`-Prefix), Regressionstest ergänzt und OpenClaw-Abgleich auf `2026.5.7` nachgezogen.** |
| **4.3.7** | 2026-05-08 | **MEM-PROV-001 abgeschlossen: `bach memory provenance` und `bach wiki provenance` liefern heuristische Quellen-/Privacy-Sichten; Task `#1119` geschlossen sowie CLI-Hilfe und Regressionstests ergänzt.** |
| **4.3.8** | 2026-05-09 | **Daily-Care-Verifikation und Control-Plane-Nachzug: strukturierte `bach_api`-/Provenance-Smokes gegen die Live-Instanz bestätigt, generischer CLI-Dispatch reicht `--dry-run` wieder korrekt an Handler weiter (`bach agent ... --dry-run`) und Agent-/Scheduler-Statusflächen liefern jetzt sauberes JSON (`bach agent ... --json`, `bach scheduler ... --json`).** |
| **4.3.9** | 2026-05-10 | **ATI-Scanner erweitert; Agent-Runtime-Caches jetzt pro `base_path` gescoped und bei Code-/Config-Änderungen invalidiert; `--json`-Ausgaben bleiben trotz ProSync sauber; `bach_api` nutzt für strukturierte Memory-Schreibpfade denselben kanonischen DB-Pfad wie die Reader; `bach seal status` funktioniert wieder; OpenClaw-Referenzstand auf GitHub Releases `2026.5.6` plus GHCR `2026.5.7-slim` präzisiert.** |
| **4.3.10** | 2026-05-11 | **`bach path` modernisiert: strukturierte JSON-/Resolve-/Validate-/Override-Oberfläche auf Basis der zentralen Pfad-Registry, runtime-saubere DB-Nutzung und OpenClaw-Abgleich plus `oc-path`/`openclaw path`-Ergonomie nachgezogen.** |
| **4.3.11** | 2026-05-11 | **Windows-Agentenstart auf langlebige Konsolen-PIDs umgestellt, damit Status/Stop echte Agenten-Sessions tracken; Agent-/Scheduler-JSON-Flächen um `available_actions`, Agenten zusätzlich um `runtime_seconds` erweitert; OpenClaw-Abgleich auf die reale Releases-/GHCR-/Beta-Divergenz nachgeschärft.** |
| **4.3.12** | 2026-05-11 | **OPS-RUN-001 auf llmauto-Ketten vertieft: `bach chain pause/resume/steer` steuert sichere Checkpoints, Status zeigt vorgemerkte Pause-/Steer-Anfragen, `bach path` ist im normalen CLI-Dispatch wieder fehlerfrei importierbar, und der OpenClaw-Abgleich wurde auf Stable `2026.5.7`, Beta `2026.5.10-beta.3` plus GHCR `2026.5.10-beta.2-slim` korrigiert.** |
| **4.3.13** | 2026-05-12 | **Registry-Watcher auf den kanonischen BACH-DB-Pfad gehärtet, damit `bach --maintain registry` im echten `system/`-Root nicht mehr gegen eine veraltete `system/data/bach.db` läuft; OpenClaw-Abgleich auf Stable `2026.5.7`, sichtbares Prerelease `2026.5.10-beta.5` und GHCR `2026.5.12-beta.1-slim` aktualisiert.** |
| **4.3.14** | 2026-05-13 | **Registry-Watcher dedupliziert doppelte `valid`-/`stale`-/`external`-Treffer aus mehrfachen DB-Zeilen, sodass `bach --maintain registry check --json` wieder realistische Stale-Zahlen liefert; Working-Memory-Cleanup bleibt über den historischen `cleanup()`-Pfad startup-kompatibel; `bach agent doctor [name] [--json]` ergänzt konkrete Agent-Preflights und Recovery-Hinweise; OpenClaw-Abgleich auf Stable `2026.5.7`, sichtbares Prerelease `2026.5.12-beta.4` und GHCR `2026.5.12-beta.4-slim` nachgezogen.** |
| **4.3.15** | 2026-05-14 | **Financial-Mail-Servicepfade auf das aktuelle `hub/_services`-Layout vereinheitlicht: GUI liest das Schema wieder vom echten Mail-Service, das Daemon-Profil startet `hub/_services/mail/mail_service.py`, die llmauto-Finanz-Mail-Chain verweist auf die aktuellen Kommandos und das Service-SKILL dokumentiert denselben Pfad konsistent.** |
| **4.3.16** | 2026-05-14 | **OpenClaw-Abgleich auf Stable `2026.5.7` plus paketverifiziertes GHCR `2026.5.12-beta.7-slim` aktualisiert; verbleibende Session-Daemon-/Mail-Service-Doku auf `hub/_services/...` nachgezogen; Startup-, Agent-Doctor-, Dry-Run-, Registry- und Financial-Mail-Regressions-Smokes sowie die gezielte pytest-Suite erneut grün verifiziert.** |
| **4.3.17** | 2026-05-14 | **Startup-Ressourcenübersicht auf das aktuelle Layout gehärtet: `hub/startup.py` zählt Agenten, Skills und Hilfe-Dateien jetzt wieder über `agents/`, `docs/help/` und die kanonische DB statt über veraltete `skills/_agents`-/`help`-Pfade; Live-Verifikation mit `bach --startup quick --mode=silent --partner=codex`, `bach agent doctor ati --json`, echtem `bach agent start ati`, `bach agent status --json`, `bach agent stop ati`, `bach upgrade docs --dry-run` und gezielter Self-Heal-Regression ist grün.** |
| **4.3.18** | 2026-05-15 | **Usecase-Runner verarbeitet Legacy-Klartext in `test_input`/`expected_output` wieder rückwärtskompatibel, sodass ältere Testfälle wie `#12 Irreguläre Kosten Vorschau` nicht mehr mit `JSON-Fehler` abbrechen; OpenClaw-Abgleich auf Stable `2026.5.12`, sichtbares Prerelease `2026.5.14-beta.1` und paketverifiziertes GHCR `2026.5.14-beta.1-slim` aktualisiert.** |
| **4.3.19** | 2026-05-15 | **Operator-Preflights auf Scheduler/Session erweitert: `bach scheduler doctor [--json]` und `bach scheduler session doctor [--json]` prüfen Skripte, PID-Zustand, DB-/Config-/Profil-Flächen, räumen stale PID-Dateien auf und liefern konkrete Recovery-/Start-Hinweise; README, Hilfe und Release-Planung auf den verifizierten OpenClaw-Stand plus die neuen Diagnoseschritte nachgezogen.** |
| **4.3.20** | 2026-05-15 | **`doc_update_checker.py` auf das aktuelle Layout gehärtet: `bach --maintain docs report` scannt jetzt auch `docs/help/*.txt`, `hub/_services/` und Root-Dokumente mit konsistenten Pfaden, erkennt veraltete `hub/handlers/*.py`- sowie `skills/_services/<service>/`-Referenzen ohne bereits korrekte `hub/_services/...`-Pfade zu beschädigen; ergänzend importiert `scheduler.py` `sqlite3` wieder explizit, und die verifizierte OpenClaw-Spitze wurde auf Stable `2026.5.12`, sichtbares Prerelease `2026.5.14-beta.1`, `latest`-Container `2026.5.12-slim` sowie GHCR-Versionsseite `2026.5.14-beta.2-slim` nachgezogen.** |
| **4.3.21** | 2026-05-16 | **Agent- und Session-Kontrollflächen für Automationen vertieft: `bach agent start/stop --json` liefern jetzt strukturierte Operator-Antworten inklusive Zielauflösung, Status und Laufzeit-Metadaten; `bach agent steer` bestätigt sich als Operator-Notiz-Bridge mit `pending_operator_notes`/`OPERATOR_NOTES.md`; neu ergänzt `bach scheduler session clear-steer` eine explizite Queue-Bereinigung für profilbezogene Auto-Runs, und fehlgeschlagene Session-Trigger verlieren vorgemerkte Steering-Hinweise weder im manuellen CLI-Pfad noch im Hintergrund-Daemon mehr. Hilfetexte, Smokes und Regressionstests wurden nachgezogen, und der OpenClaw-Abgleich wurde auf Stable `2026.5.12`, sichtbares Prerelease `2026.5.16-beta.1`, den Release-Feed `2026.5.12-beta.8`, die aktuelle Paket-/GHCR-Tag-Linie `2026.5.16-beta.1-slim` sowie die offizielle `beta -> latest`-Fallback-Regel mit zusätzlichen Signalen zu per-Agent-MCP-Scopes, MIME-Sniffing und Cron-Fallback-Semantik aktualisiert.** |
| **4.3.22** | 2026-05-17 | **Agenten- und Session-Steuerflächen nachgeschärft: `bach agent clear-steer [name] [--json]` bereinigt veraltete oder erledigte Operator-Hinweis-Queues jetzt explizit, Agent-JSON-Flächen exponieren zusätzlich `latest_operator_note` und `latest_operator_note_at`, und `bach scheduler session doctor/status/start/trigger/profiles` markieren die veraltete pyautogui-Session-Automation jetzt konsistent als deprecated samt `--force`-Guard und empfohlenen Ersatzpfaden. Hilfetexte, README, Smokes und Regressionstests wurden nachgezogen, und der OpenClaw-Abgleich wurde auf Stable `2026.5.12`, sichtbares Prerelease `2026.5.16-beta.4` sowie die aktuelle GitHub-Paket-/GHCR-Tag-Linie `2026.5.16-beta.4-slim` aktualisiert.** |
| **4.3.23** | 2026-05-18 | **`bach upgrade --check` ist jetzt produktiv: Der Handler trennt aktuelle Dateien, auf ältere bekannte Versionen zurückfallende Upgrade-Kandidaten, lokale Drift und fehlende versionierte Dateien sauber und degradiert bei leerem `dist_file_versions`-Bestand mit einer expliziten Info statt Platzhaltertext. Testsuite (`test_upgrade_handler.py`) und Agenten-Smokes (`agent doctor/start/status`) wurden erneut verifiziert, und der OpenClaw-Abgleich wurde auf Stable `2026.5.12`, sichtbares Prerelease `2026.5.16-beta.6` sowie die aktuelle GitHub-Paket-/GHCR-Tag-Linie `2026.5.16-beta.6-slim` nachgezogen.** |
| **4.3.24** | 2026-05-18 | **Session-Kontrollflächen für Automationen vervollständigt: `bach scheduler session pause/resume/steer/clear-steer --json` liefern jetzt strukturierte Antworten mit aktuellem Profil-Snapshot, `available_actions`, Queue-Länge sowie `latest_steer_message` und `latest_steer_requested_at`; Hilfetexte und READMEs wurden nachgezogen, gezielte Scheduler-/Self-Heal-Tests erneut grün verifiziert, und der OpenClaw-Abgleich wurde auf Stable `2026.5.12`, sichtbares Prerelease `2026.5.16-beta.7` sowie die aktuelle GitHub-Paket-/GHCR-Tag-Linie `2026.5.16-beta.7-slim` aktualisiert.** |
| **4.3.25** | 2026-05-18 | **Agentenstarts tragen jetzt explizite Laufzeit-Guardrails: `bach agent start` akzeptiert `--permission-mode`, `--allowed-tools` und `--max-turns`, liest dieselben Defaults optional aus `agent_runtime`-Frontmatter in `SKILL.md`, und Agent-JSON-/Statusflächen spiegeln die aktive Policy sowie Runtime-Defaults maschinenlesbar mit. Hilfetexte, README, gezielte Agenten-Usecases (`doctor/start/status/steer/clear-steer/stop`) und die Regressionstests wurden erneut grün verifiziert; der OpenClaw-Abgleich wurde auf Stable `2026.5.12`, sichtbares Prerelease `2026.5.16-beta.7` sowie die weiterhin um eine Beta hinterherlaufende GitHub-Paketlinie `2026.5.16-beta.6-slim` nachgezogen.** |
| **4.3.26** | 2026-05-19 | **`bach lang report` ergänzt eine explizite i18n-Driftfläche für Release-Artefakte und harte UI-Copy; der Report liefert jetzt auch `--surface`/`--limit`, konkrete Fundstellen mit Datei/Zeile/Typ sowie Occurrence-/Tracking-Zähler, und `bach lang scan` folgt dem aktuellen Layout (`docs/help`, `gui/templates`, `gui/static/js`, `agents/`, `skills/workflows`, `tools/`) inklusive HTML-, JS- und Markdown-Flächen. Regressionstests (`test_lang_handler.py` -> 106 grün, `test_smoke.py -k "lang_report or lang_list or agent_doctor_json or scheduler_session_doctor_json"` -> 4 grün) sowie Live-Smokes (`bach lang report --json`, `bach agent doctor ati --json`, echter Agent-Start/Steer/Clear/Stop-Zyklus für `ati`, `bach usecase run 12 --dry-run`) wurden verifiziert; der OpenClaw-Abgleich wurde auf Stable `2026.5.18`, sichtbares Prerelease `2026.5.19-beta.1`, Paketlinie `2026.5.19-beta.1-slim` und stabiles `latest=2026.5.18-slim` aktualisiert.** |
| **4.3.27** | 2026-05-20 | **`bach lang report` filtert im GUI-Surface jetzt technisches JavaScript-Rauschen wie DOM-IDs, API-Pfade und Console-Strings, extrahiert eingebettete HTML-Texte aus JS verlässlicher und erkennt `Allgemein` zusätzlich als deutschen UI-Begriff. Die gezielten Regressionen (`test_lang_handler.py` -> 108 grün, `test_smoke.py -k "lang_report or agent_doctor_json or scheduler_session_doctor_json"` -> 3 grün, `test_scheduler_handler.py -k "session_pause or session_resume or session_steer or session_clear_steer or session_doctor"` -> 20 grün, `test_agent_launcher_handler.py` -> 66 grün) sowie Live-Smokes (`bach lang report --json`, `bach lang report --surface gui --json`, `bach agent doctor ati --json`, echter `bach agent start ati --json` plus `status`/`steer`/`clear-steer`, `bach scheduler session doctor --json`, `bach upgrade check`) wurden erneut verifiziert. Der OpenClaw-Abgleich wurde auf Stable `2026.5.18`, sichtbares Prerelease `2026.5.19-beta.2`, Paketlinie `2026.5.19-beta.2-slim`, zusätzliche `2026.5.19-alpha.1-slim`-Builds und stabiles `latest=2026.5.18-slim` aktualisiert.** |
| **4.3.28** | 2026-05-20 | **Scheduler-weite Operator-Steuerung nachgezogen: `bach scheduler pause/resume/steer/clear-steer --json` liefert jetzt strukturierte Kontrollantworten samt `operator_control`-Snapshot, der GUI-Scheduler-Daemon respektiert globale Pausen für fällige Jobs und reicht vorgemerkte Hinweise über `BACH_SCHEDULER_OPERATOR_STEER` auch an Job-/Chain-Läufe weiter. Hilfe, README und Release-Planung wurden auf den verifizierten OpenClaw-Stand vom 2026-05-20 (Stable `2026.5.18`, sichtbares Prerelease `2026.5.19-beta.2`, zusätzliche Paketlinie `2026.5.19-alpha.1-slim`, `latest=2026.5.18-slim`) nachgezogen; gezielte Regressionen (`test_scheduler_handler.py`, `test_daemon_service.py`, `test_self_heal_handlers.py`, `test_smoke.py`) sowie Live-Smokes für Agent- und Scheduler-Controls, `bach usecase run 12 --dry-run` und `bach usecase run 41 --dry-run` liefen erneut grün.** |
| **4.3.29** | 2026-05-20 | **Agenten-Vorstart-Steering ergänzt: `bach agent steer` kann Hinweise jetzt auch für gestoppte Agenten vormerken, `bach agent list/status --json` spiegeln dafür `queued_for_next_start` und `status=queued`, und der nächste `bach agent start` übernimmt die Queue statt sie still zu löschen. Hilfetexte, README und Release-Planung wurden auf diese Kontrollfläche sowie den verifizierten OpenClaw-Stand mit Stable `2026.5.18`, sichtbarem Prerelease `2026.5.19-beta.2`, Paketlinie `2026.5.19-beta.2-slim` plus `-amd64`/`-arm64`, zusätzlicher `2026.5.19-alpha.1-slim`-Linie und stabilem `latest=2026.5.18-slim` nachgezogen; gezielte Regressionen (`test_agent_launcher_handler.py` -> 66 grün, `test_smoke.py -k "agent_steer_prelaunch_json or agent_start_dry_run_json or agent_doctor_json or agent_list_json"` -> 4 grün) sowie Live-Smokes (`clear-steer` -> `steer` -> echter `start` -> `status` -> `stop`) wurden erneut verifiziert.** |
| **4.3.30** | 2026-05-21 | **Agentenstarts übernehmen Vorstart-Hinweise jetzt nicht nur als Queue, sondern injizieren sie direkt in die generierte Session-`CLAUDE.md`; der Startprompt verweist außerdem explizit auf sichere Checkpoints für spätere `OPERATOR_NOTES.md`-Updates. Hilfe, README, CHANGELOG, ROADMAP und `NEXT_RELEASE` wurden auf diese Vertiefung sowie den verifizierten OpenClaw-Stand vom 2026-05-21 (Stable `2026.5.19`, sichtbares Prerelease `2026.5.20-beta.2`, sichtbare Paketlinie `2026.5.20-beta.1-slim`, stabiles `latest=2026.5.19-slim`) nachgezogen; gezielte Regressionen und Live-Smokes für Agenten-Start/Steer/Usecases wurden erneut gefahren.** |
| **4.3.31** | 2026-05-21 | **Upgrade-Flächen auf JSON-Parität gehoben: `bach upgrade list/status/check --json` liefern jetzt strukturierte Versions-, Release- und Drift-Payloads, inklusive sauberer Nullsummen wenn `dist_file_versions` leer ist. Hilfe, README, ROADMAP und `NEXT_RELEASE` wurden auf diese API-/Dashboard-Fläche sowie den verifizierten OpenClaw-Stand vom 2026-05-21 (Stable `2026.5.19`, sichtbares Release-Prerelease `2026.5.20-beta.2`, Paketlinie `2026.5.20-beta.1-slim`, `latest=2026.5.19-slim`) nachgezogen; Regressionen (`test_upgrade_handler.py` -> 31 grün) und Live-Smokes für `upgrade status/check --json`, `agent doctor/start/steer/stop/clear-steer/status --json` sowie `usecase run 12/41 --dry-run` wurden erneut verifiziert.** |
| **4.3.32** | 2026-05-21 | **Kooperative Agenten-Pause ergänzt: `bach agent pause/resume [name] [Grund] [--json]` schreibt und entfernt Pauseanforderungen für laufende Agenten, `agent list/status --json` exponieren dafür einen verschachtelten `operator_control`-Snapshot samt `pause_requested`, `pause_reason`, `pending_steer_count`, Dateipfaden und verfügbaren Aktionen, und `OPERATOR_NOTES.md` spiegelt aktive Pausewünsche direkt mit. Hilfetexte, README, CHANGELOG, ROADMAP und `NEXT_RELEASE` wurden auf diese Vertiefung sowie den verifizierten OpenClaw-Stand vom 2026-05-21 (Stable `2026.5.19`, sichtbares Release-Prerelease `2026.5.20-beta.2`, öffentliche Paketseite noch `2026.5.20-beta.1-slim`, GHCR-Manifest bereits `2026.5.20-beta.2-slim`, `latest=2026.5.19-slim`) nachgezogen; Regressionen (`test_agent_launcher_handler.py` -> 73 grün) und Live-Smokes für `agent pause/resume/steer/status/stop`, `usecase run 12/41 --dry-run`, `upgrade check` und `lang report --surface gui --json` wurden erneut verifiziert.** |
| **4.3.33** | 2026-05-22 | **Heutige Live-Verifikation nachgezogen: `bach --startup quick --mode=silent --partner=codex`, `bach agent doctor test-agent --json`, Vorstart-`steer`, echter `bach agent start test-agent --headless --json` plus `status`/`pause`/`resume`/`clear-steer`/`stop`, `bach usecase run 12/41 --dry-run`, `bach lang report --surface gui --limit 10 --json` sowie `bach upgrade status/check --json` liefen erneut grün. Zusätzlich bleibt `bach upgrade list --json` bei fehlendem oder unbekanntem Pfad jetzt maschinenlesbar, und die CLI-Smokes nutzen den dedizierten `test-agent`, damit laufende Live-Agenten wie `ati` die Regressionen nicht verfälschen. README, README.de, ROADMAP, CHANGELOG und `NEXT_RELEASE` wurden zugleich auf den verifizierten OpenClaw-Stand vom 2026-05-22 mit Stable `2026.5.20`, sichtbarem Prerelease `2026.5.20-beta.2`, stabiler `2026.5.20-slim`-Containerfamilie und zusätzlicher Alpha-Linie `2026.5.21-alpha.1-slim` nachgezogen.** |
| **4.3.34** | 2026-05-23 | **Agentenläufe können sichere Checkpoints jetzt explizit quittieren, und aktive Pauseanforderungen schlagen im Top-Level-Status konsistent als `pause-requested` bzw. `[PAUSE-REQ]` durch: `bach agent checkpoint [name] [Notiz] [--json]` schreibt `operator_checkpoint.json`, aktualisiert `OPERATOR_NOTES.md`, `agent list/status --json` zeigen dafür `last_checkpoint_at`, `last_checkpoint_message`, `latest_control_request_at`, `awaiting_checkpoint_ack` sowie die neue Kontrollaktion `checkpoint`, und laufende pausierte Agenten melden ihren Zustand jetzt nicht mehr nur verschachtelt unter `operator_control`. Hilfe, README, README.de, ROADMAP, CHANGELOG und `NEXT_RELEASE` wurden auf diese OPS-RUN-Vertiefung und den verifizierten OpenClaw-Stand vom 2026-05-23 (Stable `2026.5.20`, sichtbares Release-Prerelease weiter `2026.5.20-beta.2`, Paketlinie `2026.5.22-beta.1-slim`) nachgezogen; gezielte Regressionen (`test_agent_launcher_handler.py` -> `74 passed`) und Live-Smokes für `agent checkpoint`, `pause/resume/steer/status/stop`, `usecase run 12/41 --dry-run`, `scheduler doctor`, `lang report --surface gui` und `upgrade check --json` wurden erneut verifiziert.** |
| **4.3.35** | 2026-05-23 | **Usecase-Sammeltests sind jetzt produktiv: `bach usecase run-all [workflow] [--dry-run]` bereitet wahlweise alle oder workflowgefilterte Usecases wirklich vor, aktualisiert `last_tested` nur außerhalb von Dry-Runs und bevorzugt echte Markdown-Workflowdateien statt gleichnamiger Verzeichnisse. Hilfe, README, README.de, ROADMAP, CHANGELOG und `NEXT_RELEASE` wurden auf diesen T01-Fortschritt nachgezogen; gezielte Regressionen (`test_tuev_handler.py` + `test_smoke.py` -> `130 passed`) und der Live-Smoke `bach usecase run-all --dry-run` liefen erneut grün.** |
| **4.3.36** | 2026-05-24 | **Scheduler-DB-Pfade vereinheitlicht: `system/hub/scheduler.py` und `system/gui/daemon_service.py` nutzen jetzt dieselbe kanonische BACH-DB wie CLI und GUI-Server, sodass Doctor/Status/Jobs und der Hintergrunddienst nicht mehr gegen ein veraltetes `system/data/bach.db` laufen. README, README.de, ROADMAP, CHANGELOG und `NEXT_RELEASE` wurden auf den heutigen Live-Check (`--startup quick`, vollständiger `test-agent`-Headless-Lauf, `scheduler doctor/status --json`, `usecase run 12/41`, `usecase run-all --dry-run`, `lang report --surface gui --limit 5 --json`, `upgrade status/check --json`) sowie den verifizierten OpenClaw-Stand vom 2026-05-24 (Stable `2026.5.22`, sichtbares Prerelease `2026.5.22-beta.1`, Paketlinie `2026.5.22-slim` plus `2026.5.23-alpha.1`) nachgezogen; gezielte Regressionen (`test_scheduler_handler.py`/`test_daemon_service.py`) liefen erneut grün.** |
| **4.3.57** | 2026-07-11 | **Task-1152-Slice für die clutch-Migration geschlossen: BACHs Compat-Layer nutzt für Fahrtenbuch und Fahrschule jetzt externe `clutch`-APIs mit BACH-Signaturen und kanonischem `bach.db`-Pfad. Der Adapter schreibt parallel in externe `fahrten` sowie BACHs bestehende `clutch_fahrtenbuch`-/`clutch_fitness`-Kompatibilitätsflächen; `bach clutch migration` kann damit die DB-Brücke als `OK` melden. Legacy-Streckenanalyse/Gas/Bordcomputer und Fork-Archivierung bleiben bewusst unangetastet bis der Parallelbetrieb weiter grün ist.** |
| **4.3.56** | 2026-07-05 | **Task-1151-Slice für die clutch-Migration geschlossen: `system/hub/_services/delegation/__init__.py` baut jetzt eine `clutch`-gestützte PartnerRegistry aus BACH `partner_recognition`, und `system/hub/partner.py` legt darüber zusätzlich BACH `delegation_rules`, explizite `delegation_zones` und die sichtbare Routing-Quelle `clutch-partner-registry`. Damit respektieren Auto-Routing und explizite `--to=`-Delegationen sowohl clutch-Zonenökonomie als auch BACH-Allow-Lists, ohne den Legacy-Fork zu archivieren. Verifiziert wurden `python -m pytest system/tests/test_delegation_adapter.py system/tests/test_partner_handler.py -q` (`16 passed`) sowie API-Smokes für `partner delegate/list`, `agent doctor test-agent --json` und `usecase run 50 --dry-run`; der OpenClaw-Stand wurde am 2026-07-05 erneut geprüft und bleibt bei Stable `2026.6.11`, während das neueste sichtbare Prerelease jetzt `2026.7.1-beta.2` vom 2026-07-05 09:10 UTC ist.** |
| **4.3.55** | 2026-07-03 | **Skill-Source-Registry für `bach skills version bach` geschlossen: `system/hub/skills.py` liest kanonische Quellen und optionale Nutzerkopien jetzt aus `system/data/skill_sources.json`, löst relative Registry-Pfade robust auf, meldet den Repo-Root-Skill als echte kanonische Quelle statt `ZENTRAL: (nicht registriert)` und kann vorhandene Codex-/Claude-Kopien gegen diesen Stand vergleichen. Verifiziert wurden `python -m pytest system/tests/test_skills_handler.py -q` (`18 passed`), `python bach.py skills version bach`, `python bach.py agent doctor test-agent --json` und `python bach.py usecase run 50 --dry-run`; der OpenClaw-Stand wurde am 2026-07-03 erneut geprüft und bleibt bei Stable `2026.6.11` sowie sichtbarem Prerelease `2026.7.1-beta.1` vom 2026-07-02 07:25 UTC.** |
| **4.3.54** | 2026-07-02 | **Release-/Roadmap-Pflege auf aktuellen Daily-Care-Stand gehoben: README, README.de, ROADMAP, CHANGELOG und `NEXT_RELEASE` spiegeln jetzt den verifizierten OpenClaw-Stand mit Stable `2026.6.11` und sichtbarem Prerelease `2026.7.1-beta.1` sowie die daraus relevanten Signale zu GPT-5.6-Coverage, `openclaw attach`, Telegram-Codex-Steering, `on-exit`-Cron und gescopten Capability-Profilen. Der heutige Lauf verifizierte `python bach.py --startup quick --mode=silent --partner=codex`, `python bach.py agent doctor test-agent --json`, `python bach.py agent start test-agent --dry-run --json` und `python bach.py usecase run 50 --dry-run`; zusätzlich wurde ein Live-Drift im Upgrade-Katalog per `python bach.py upgrade repair --version v3.12.4-earth --json` wieder von `release_entries=0` auf `release_entries=1` gehoben und anschließend mit `python bach.py upgrade check --json` grün gegengeprüft.** |
| **4.3.53** | 2026-06-23 | **Dispatch-/Delegations-Härtung nachgezogen: `system/core/app.py` reicht `dry_run` jetzt signatursicher weiter, `bach --partner delegate --score` meldet dank Compat-Layer die echte Scorer-Quelle (`clutch` vs. Legacy), und `system/hub/db_sync.py` deferiert Pull-Kandidaten nur noch bei bekannten transienten OneDrive-/SQLite-Fehlern statt bei beliebigen Merge-Exceptions. Verifiziert wurden `python -m pytest system/tests/test_core.py system/tests/test_partner_handler.py system/tests/test_startup_handler.py system/tests/test_db_sync_handler.py -q` (`116 passed`) sowie die Smokes `python bach.py --partner delegate "Migration pruefen" --score --dry-run`, `python bach.py --startup --mode=text --dry-run` und `python bach.py help partner`.** |
| **4.3.52** | 2026-06-23 | **OpenClaw-Referenzstand für den laufenden Release-Service aktualisiert: Stable bleibt `2026.6.9`, während das neueste sichtbare Prerelease jetzt `2026.6.10-beta.2` ist. Für BACH relevant sind zusätzlich automatische Fast-Mode-Wechsel für kurze Turns, robustere Modell-Routen, sicherere Session-/Channel-Zustände und erhaltene Trusted Policies bei Hook-Komposition; die ProSync- und Release-Hygiene-Änderungen aus 4.3.51 bleiben dadurch fachlich unverändert.** |
| **4.3.51** | 2026-06-21 | **ProSync-Startup fail-soft gehärtet: `system/hub/db_sync.py` staged OneDrive-Transit-Backups jetzt lokal vor dem Merge und deferiert fehlerhafte Kandidaten nach Cloud-Timeouts oder `disk I/O error` für 30 Minuten in `~/.bach/sync_state.json`, damit Read-Only-CLI- und JSON-Befehle nicht mehr bei jedem Startup an derselben Transit-Datei hängen bleiben. Verifiziert wurden `python -m pytest system/tests/test_db_sync_handler.py -q` (`45 passed`), `python -m pytest system/tests/test_prosync_race.py -q` (`3 passed`), ein echter `sync_on_start()`-Repro mit OneDrive-Timeout sowie die anschließenden Smokes `python bach.py --startup quick --mode=silent --partner=codex`, `python bach.py agent doctor test-agent --json`, der vollständige `test-agent`-Steuerzyklus, `python bach.py usecase run 50 --dry-run`, `python bach.py upgrade check --json` und `python bach.py task list --filter clutch`. Der OpenClaw-Referenzstand wurde zugleich auf Stable `2026.6.9` und sichtbares Prerelease `2026.6.10-beta.1` aktualisiert; relevant bleiben vor allem Kanalzustellung, Agent-/Session-Recovery, Codex-Approval-Flows, Provider-Plugin-Pakete, Herkunftsspur für Suche/Skills und härtere Secret-/Privacy-Scrubs.** |
| **4.3.50** | 2026-06-19 | **Setup-/Scheduler-Health weiter gehärtet: `system/hub/setup.py` prüft globale MCP-Installationen jetzt über `npm root -g` und direkte Paketpfade statt über langsamere `npm list -g`-Aufrufe, und `system/hub/scheduler.py` wartet beim Hintergrundstart mit einer monotonic-basierten 12-Sekunden-Deadline robuster auf langsam erzeugte Windows-/OneDrive-PID-Dateien. Verifiziert wurden `python -m pytest system/tests/test_setup_handler.py system/tests/test_scheduler_handler.py system/tests/test_bach_paths.py -q` (`232 passed`), der isolierte Startup-Archivfilter (`1 passed`), `python bach.py setup check`, `python bach.py agent doctor test-agent --json`, der vollständige `test-agent`-Steuerzyklus, `python bach.py task list --filter clutch`, `python bach.py reflection status`, `python bach.py usecase run 50 --dry-run` sowie ein erfolgreicher `python bach.py scheduler start --bg` mit anschließend sauberem `scheduler stop`. Der OpenClaw-Referenzstand wurde zugleich auf Stable `2026.6.8` und sichtbares Prerelease `2026.6.9-beta.1` aktualisiert; relevant sind vor allem Telegram-Zustellung, Agent-/Session-Recovery, Codex-Integration, Provider-Plugin-Pakete, Herkunftsspur für Suche/Skills und härtere Secret-/Privacy-Scrubs.** |
| **4.3.49** | 2026-06-18 | **Der Root-CLI-Vorpfad nutzt jetzt dieselbe kanonische BACH-Datenbank wie die Handler: `system/bach.py` löst `DB_PATH` über `hub.bach_paths.BACH_DB` auf, und auch der `folders`-Hilfspfad reicht keine veraltete `system/data/bach.db` mehr weiter. Dadurch laufen Activity-Ticks, EOD-/Idle-Finalisierung und Session-Timestamps wieder gegen denselben Live-Stand wie `task`, `reflection`, `usecase` und `startup`. Verifiziert wurden `python -m pytest system/tests/test_bach_paths.py -q` (`58 passed`) sowie die Live-Smokes `bach task list --filter clutch`, `bach reflection status`, `bach usecase run 50 --dry-run` und `bach --startup quick --mode=silent --partner=codex`. Der OpenClaw-Referenzstand wurde am 2026-06-18 erneut geprüft und bleibt bei Stable `2026.6.8` sowie sichtbarem Prerelease `2026.6.8-beta.2`; relevant bleiben Kanalzustellung, Recovery, normalisierte Provider-/Modellrouten, SecretRef-nahe Auth-Logik und explizite Websuch-Defaults.** |
| **4.3.48** | 2026-06-17 | **Die T01-Workflow-Frontdoor ist jetzt vollständig: zwölf neue Domänen-Workflow-Dateien (`assistent`, `care-modul`, `datenmodul`, `dokumentenmodul`, `finanzen`, `gesundheit`, `haushalt`, `karriere`, `reflection-status`, `selbstmanagement`, `therapie`, `wissen`) schließen die restlichen manuellen Usecase-Kategorien, sodass ein direkter Resolver-Check nun 50 workflowgebundene und 0 manuelle Usecases sieht. Verifiziert wurden `bach usecase run 50 --dry-run`, die gezielte Resolver-Regression `test_tuev_handler.py -k "resolve_uppercase_category_to_lowercase_workflow_file or resolve_snake_case_category_to_kebab_case_workflow_file"` (`2 passed`), der vollständige `test-agent`-Steuerzyklus sowie `bach --startup quick --mode=silent --partner=codex` mit erfolgreichem Durchlauf in rund 58 Sekunden. Der OpenClaw-Referenzstand wurde zugleich auf Stable `2026.6.8` und sichtbares Prerelease `2026.6.8-beta.2` (beide 2026-06-16) aktualisiert; relevant bleiben daraus vor allem Kanalzustellung, Recovery, Provider-/Auth-Härtung und explizite Websuch-Defaults.** |
| **4.3.47** | 2026-06-13 | **Die offene SOFTWARE-Usecase-Lücke ist deutlich kleiner: Eine neue gemeinsame Workflow-Datei `system/skills/workflows/software.md` bindet jetzt die Usecases 41 bis 49 an eine reale Markdown-Workflowfläche statt an manuellen Fallback, und `system/skills/workflows/wiki-author.md` verweist wieder auf das aktuelle `wiki/`-Layout und `hub/_services/wiki/`. Verifiziert wurden `bach usecase run 41 --dry-run`, `bach usecase run-all --dry-run` (jetzt 24 workflowgebundene / 26 manuelle Usecases) sowie die gezielte Regression `test_tuev_handler.py -k "resolve_uppercase_category_to_lowercase_workflow_file"` (`1 passed`). Der OpenClaw-Referenzstand wurde zugleich auf Stable `2026.6.6` (2026-06-12) und sichtbares Prerelease `2026.6.7-beta.1` (2026-06-13) aktualisiert; relevant bleiben daraus vor allem härtere Auth-/Kontextgrenzen, robustere Recovery-Pfade und klarere Doctor-/Update-/QA-Signale.** |
| **4.3.46** | 2026-06-12 | **GUI-Lang-Scan auf Report-Parität gehärtet: `system/hub/lang.py` nutzt für `bach lang scan --namespace gui` jetzt dieselben gefilterten Hardcoded-Copy-Fundstellen wie `bach lang report`, sodass Python-Docstrings, SQL-Schnipsel und ähnliches GUI-Rauschen nicht mehr als DE-Copy in die Release-Artefakte gelangen. Der heutige Lauf bereinigte den versehentlichen Noisy-Scan, seedete anschließend 93 legitime GUI-DE-Schlüssel neu, hob sichtbare Oberflächen in `persoenlich`, `memory`, `steuer` und `workflow_tuev` auf echte Umlaute und aktualisierte die Release-Artefakte auf 17.593 Übersetzungen. `bach lang report --surface gui --limit 20 --json` steht damit bei 166 eindeutigen GUI-DE-Strings, 253 Fundstellen und 0 offenen Einträgen; verifiziert wurden außerdem `test_lang_handler.py -k "report_gui_js_ignores_technical_literals_but_keeps_ui_copy or test_scan_gui_uses_report_filters_for_runtime_copy"` (`2 passed`), `bach agent doctor test-agent --json`, der vollständige `test-agent`-Steuerzyklus, `bach usecase run 12/41 --dry-run`, `bach usecase run-all --dry-run` sowie `bach upgrade status/check --json`. Der OpenClaw-Referenzstand wurde zugleich auf Stable `2026.6.6` (2026-06-12) und sichtbares Prerelease `2026.6.6-beta.2` (2026-06-12) aktualisiert.** |
| **4.3.45** | 2026-06-06 | **GUI-i18n-Drift und sichtbare Umlaute weiter bereinigt: `system/hub/lang.py` filtert in JS-generiertem Markup jetzt zusätzlich technische `class`-/`id`-Tokens aus, sichtbare Oberflächen in ATI, Daemon, Financial, Denkarium und dem Skills Board verwenden wieder echte Umlaute, und 29 zusätzliche GUI-DE-Schlüssel wurden im `gui`-Namespace ergänzt. Die Release-Artefakte stehen damit bei 17.488 Übersetzungen, und `bach lang report --surface gui --limit 20 --json` zeigt nur noch 94 offene eindeutige GUI-DE-Einträge bei 111 offenen Fundstellen. Der Lauf vom 2026-06-06 verifizierte außerdem `bach agent doctor test-agent --json`, den vollständigen `test-agent`-Steuerzyklus, `bach usecase run 12/41 --dry-run`, `bach usecase run-all --dry-run`, `bach upgrade status/check --json` sowie die gezielten `test_lang_handler.py`-Regressionen (`3 passed`); Usecase 41 bleibt funktional, aber weiter im manuellen Fallback ohne verknüpfte Workflow-Datei. Der OpenClaw-Referenzstand wurde zugleich auf Stable `2026.6.1` (2026-06-03) und sichtbares Prerelease `2026.6.5-beta.1` (2026-06-06) aktualisiert.** |
| **4.3.44** | 2026-06-05 | **Daily-Care-Stand weiter verdichtet: zwanzig zusätzliche GUI-Schlüssel wurden im `gui`-Namespace ergänzt, die Release-Artefakte auf 17.459 Übersetzungen neu exportiert, und `bach lang report --surface gui --limit 40 --json` zeigt jetzt nur noch 124 offene eindeutige GUI-DE-Einträge bei 143 offenen Fundstellen. Der Lauf vom 2026-06-05 verifizierte außerdem `bach agent doctor test-agent --json`, den vollständigen `test-agent`-Steuerzyklus (`clear-steer` -> `steer` -> `start` -> `status` -> `pause` -> `checkpoint` -> `resume` -> `stop` -> `clear-steer`), `bach usecase run 12/41 --dry-run`, `bach usecase run-all --dry-run` sowie `bach upgrade status/check --json`; Usecase 41 bleibt funktional, aber weiter im manuellen Fallback ohne verknüpfte Workflow-Datei. Der OpenClaw-Referenzstand wurde zugleich auf Stable `2026.6.1`, sichtbares Prerelease `2026.6.2-beta.1` und die aktuelle Browser-/Slim-Betalinie aktualisiert, während stabile Alias-Tags weiter auf `2026.6.1` zeigen.** |
| **4.3.43** | 2026-06-03 | **GUI-i18n-Index weiter reduziert: fünf noch unindexierte Legacy-Texte aus `system/gui/ki-center.html` wurden dem `gui`-Namespace hinzugefügt, die Release-Artefakte auf 17.419 Übersetzungen neu exportiert, und `bach lang report --surface gui --limit 10 --json` zeigt jetzt nur noch 148 offene eindeutige GUI-DE-Einträge bei 192 offenen Fundstellen statt 153/239. Der heutige Daily-Care-Lauf verifizierte außerdem `bach agent doctor test-agent --json`, `bach usecase run 12 --dry-run`, `bach usecase run 41 --dry-run` und `bach upgrade check --json`; Usecase 41 bleibt dabei funktional, aber weiter im manuellen Fallback ohne verknüpfte Workflow-Datei. Der OpenClaw-Referenzstand wurde zugleich auf Stable `2026.5.28`, sichtbares Prerelease `2026.6.1-beta.3` und die aktuelle Containerlinie `2026.6.1-beta.3-browser` plus `2026.6.1-beta.3-slim` nachgezogen.** |
| **4.3.42** | 2026-06-03 | **Langfristiges Ziel ergänzt: „BACH als anbietbarer MCP-Server" (Bundle-Split + ControlCenter-Control-Plane). Neue Detail-Sektion am Dokumentende, Eintrag unter „Langfristige Ziele (P4)" sowie Konzept-Index-Verweis auf diese ROADMAP-Sektion. Befund: `system/tools/mcp_server.py` v2.2 (8 Resources / 23 Tools / 3 Prompts) ist bereits ein lauffähiger MCP-Server; offen bleiben die Bundle-Aufteilung der ~807 Handler-Operationen, optionaler Streamable-HTTP-Transport/OAuth und Multi-Tenant-Datenisolation (Gesundheit/Steuer → Modell B „self-host" empfohlen). Reine ROADMAP-Ergänzung, kein Code-Change.** |
| **4.3.41** | 2026-06-01 | **Kanonische DB-Pfade weiter vereinheitlicht: `system/tools/mcp_server.py` nutzt jetzt `hub.bach_paths.BACH_DB`, `system/tools/bach_db_viewer.py` bevorzugt die lokale `~/.bach/bach.db`, der Steuer-Shared-Layer und mehrere Hilfsskripte hören auf, alte OneDrive-/Repo-DB-Pfade vorauszusetzen, und Hilfetexte sprechen konsistent von `BACH_DB` statt `system/data/bach.db`. Der heutige Daily-Care-Lauf verifizierte `python -m py_compile` auf den geänderten Laufzeitdateien, `test_bach_paths.py` = 56 grün, `beleg_vorfilter.py --dry-run`, `agent doctor test-agent --json`, den kompletten `test-agent`-Headless-Lauf, `usecase run 12/41`, `usecase run-all --dry-run`, `upgrade status/check --json` und `lang report --surface gui --limit 5 --json`; der OpenClaw-Referenzstand wurde zugleich auf Stable `2026.5.28`, sichtbares Prerelease `2026.5.31-beta.1` und die aktuelle Containerlinie `2026.6.1-beta.1-browser` plus `2026.6.1-beta.1-slim` nachgezogen.** |
| **4.3.40** | 2026-05-30 | **Release-Katalog-Recovery im Upgrade-Pfad geschlossen: `bach upgrade repair [--dry-run] [--version]` bootstrappt jetzt bei leerem `distribution_releases` den aktuellen Release-Eintrag aus README-/CHANGELOG-Metadaten, und `bach upgrade check --json` liefert `manifest_entries`, `release_entries`, `repair_recommended`, `current_version` und `current_release_registered` nun konsistent auch im normalen Drift-Pfad. Der heutige Daily-Care-Lauf verifizierte `--startup quick`, `task list`, `agent doctor test-agent --json`, den kompletten `test-agent`-Headless-Lauf, `usecase run-all --dry-run`, `usecase run 12/41/45 --dry-run`, `lang report --surface gui --limit 5 --json`, `upgrade repair/status/check --json` sowie die gezielten Regressionen (`test_upgrade_handler.py` = 38 grün, `test_smoke.py -k "upgrade_status or upgrade_check"` = 2 grün); die Live-Zahlen liegen jetzt bei 4.720 getrackten Dateien, 4.722 Manifest-Einträgen, 1 registrierten Stable-Release und 12 lokalen Änderungen. Zugleich wurde der OpenClaw-Referenzstand auf 2026-05-30 nachgezogen (Stable `2026.5.27`, sichtbares Prerelease `2026.5.28-beta.4`, hervorgehobene Containerlinie `2026.5.28-beta.4-slim`).** |
| **4.3.39** | 2026-05-28 | **Upgrade-Metadaten self-healen jetzt produktiv: `bach upgrade repair [--dry-run] [--version]` rekonstruiert `distribution_manifest` und `dist_file_versions` aus dem Live-Distributionsbaum, `bach upgrade status/check --json` liefern `manifest_entries`, `release_entries` und `repair_recommended`, und der Daily-Care-Lauf hat die kanonische DB damit von 0 auf 4.687 versionierte Dateien repariert. README, README.de, ROADMAP, CHANGELOG, `NEXT_RELEASE` und `bach help upgrade` wurden zugleich auf den verifizierten OpenClaw-Stand vom 2026-05-28 (Stable `2026.5.26`, sichtbares Prerelease `2026.5.27-beta.1`, hervorgehobene Containerlinie `2026.5.27-beta.1-slim`) sowie die heutigen Regressionen (`test_upgrade_handler.py`, `test_smoke.py -k "upgrade_status or upgrade_check"`) und Live-Smokes (`upgrade repair`, `upgrade status/check --json`, `seal repair/check`, `--startup quick`, kompletter `test-agent`-Headless-Lauf, `usecase run 12/41 --dry-run`) nachgezogen.** |
| **4.3.38** | 2026-05-27 | **Scheduler-weites Steering greift jetzt auch in llmauto-Ketten wirklich durch: `system/tools/llmauto/core/state.py` und `system/tools/llmauto/modes/chain.py` importieren `BACH_SCHEDULER_OPERATOR_STEER` beim echten Chain-Run in die reguläre llmauto-Queue, erhalten dabei den ursprünglichen Zeitstempel und übergeben die Hinweise am nächsten sicheren Checkpoint an den Modellprompt. README, README.de, ROADMAP, CHANGELOG und `NEXT_RELEASE` wurden zugleich auf den verifizierten OpenClaw-Stand vom 2026-05-27 (Stable `2026.5.22`, sichtbares Prerelease `2026.5.26-beta.2`, Paketlinie `2026.5.26-beta.2-slim` mit `amd64`/`arm64`) sowie die heutigen Regressionen (`test_chain_control.py`, `test_daemon_service.py`, `test_scheduler_handler.py`, gezielte Agent-Launcher-Kontrollsuite) und Live-Smokes (`test-agent`, `scheduler doctor/status --json`, `usecase run 12/41`, `usecase run-all --dry-run`, `lang report --surface gui --limit 5 --json`, `upgrade status/check --json`) nachgezogen.** |
| **4.3.37** | 2026-05-26 | **MediPlaner-Austausch integriert: `bach mediplaner export/import/help` ist jetzt nicht nur als Handler vorhanden, sondern auch über `bach help mediplaner`, CLI-/Feature-/Gesundheitsdoku und die Chat-Runtime-Hinweise systemweit auffindbar. README, README.de, ROADMAP, CHANGELOG und `NEXT_RELEASE` wurden zugleich auf den verifizierten OpenClaw-Stand vom 2026-05-26 (Stable `2026.5.22`, sichtbares Prerelease `2026.5.24-beta.1`, Paketlinie `2026.5.25-beta.1-slim` mit `amd64`/`arm64`) sowie den heutigen Live-Check (`help mediplaner`, kompletter `test-agent`-Headless-Lauf, `scheduler doctor/status --json`, `usecase run 12/41`, `usecase run-all --dry-run`, `lang report --surface gui --limit 5 --json`, `upgrade status/check --json`) nachgezogen; gezielte Regressionen (`test_scheduler_handler.py`, `test_daemon_service.py`, `test_mediplaner_handler.py`, `test_chat_runtime.py`) liefen erneut grün.** |

Detaillierte Historie: `CHANGELOG.md`
Archivierte Versionen: `../docs/_archive/ROADMAP_*.md`

---

## Verwandte Dokumente

- **Release-Pipeline:** öffentlich zusammengefasst in `CHANGELOG.md`, den Release-Meilensteinen dieser Roadmap und den Test-/Verifikationsnotizen.
  Beschreibt den Weg von Vanilla -> Strawberry -> GitHub-Veröffentlichung.
  Umfasst Hauptquests, Sidequests, Cluster und Abhängigkeitskarte auf öffentlicher Abstraktionsebene.
  Die ROADMAP beschreibt WAS BACH kann; interne Release-Checklisten beschreiben WIE wir releasen.

- **Nächste Aufgaben:** siehe Abschnitt „Noch offen" und die aktuellen OPS-/T-/ORG-Einträge dieser Roadmap.
  Konkrete Aufgaben für das nächste Release werden nur öffentlich sichtbar gemacht, wenn sie keine internen Planungsdetails enthalten.

- **Spätere Items:** siehe „Langfristige Ziele (P4)" und die offenen ORG-/Marketing-Blöcke.
  Nicht release-kritische Items bleiben hier als öffentliche Zusammenfassung.

- **Policy-Entscheidungen:** öffentlich konsolidiert über Roadmap-, Changelog- und Architekturhistorie.
  Interne ENT-Details bleiben außerhalb des öffentlichen Repos.

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

---

## BACH als anbietbarer MCP-Server: Bundle-Split & Control-Plane (2026-06-03)

> Status: VISION / LANGFRISTIG — OFFEN. Die Analyse ist in dieser ROADMAP-Sektion zusammengefasst.

### Ausgangslage

BACH **ist** bereits ein MCP-Server: `system/tools/mcp_server.py` v2.2.0 (FastMCP/Python, stdio) exponiert 8 Resources, 23 Tools und 3 Prompts über `bach_api.execute(handler, operation, args)`. Die Verwandlung ist damit empirisch belegt — offen ist, wie BACH als vollwertiger, *anbietbarer* MCP-Server skaliert.

### Problem

- **Tool-Bloat:** Die natürliche MCP-Oberfläche umfasst ~807 Handler-Operationen (105 Handler) plus 322 Script-Tools. Alle auf einmal zu exponieren sprengt jeden Host-Kontext (die 23 heutigen Tools = ~3 %).
- **Single-User-DNA:** Die DB enthält Gesundheit/Steuer/Finanzen — multi-tenant öffentlich anzubieten ist ohne strikte Mandanten-Isolation hochriskant (Art. 9 DSGVO).
- **Lokale Redundanz:** Für den lokalen Eigenzugriff (Claude ↔ BACH via Bash) ist MCP überflüssig (`wiki/mcp_toolstack.txt`). MCP zahlt sich nur in den dort genannten Ausnahmen aus — **Remote, Multi-Host, große Tool-Menge** — also genau im „anbieten"-Fall.

### Lösung (Zielbild): zwei „on demand"-Ebenen statt Monolith

```
  Ebene 1 (Host-Config):  ControlCenter  --aktiviert je Aufgabe-->  Capability-Bundle
                          (Control-Plane)                          (bach-core / -health / -tax / -dev)
  Ebene 2 (in-Server):    bach-mcp Bundle --Meta-Tool + Pagination-->  Long-Tail der Operationen
                          (auf core/registry.py)                     (tools/list cursor + listChanged)
```

1. **Bundle-Split:** `mcp_server.py` in thematische Capability-Server zerlegen (bach-core, bach-health, bach-tax, bach-dev …), generiert aus der Registry (`get_operations()`) statt 23 handverdrahteter Tools.
2. **Control-Plane (ControlCenter):** `ellmos-controlcenter-mcp` (lokal `.AI/.MCP/ellmos-controlcenter-mcp`, Alpha) als Orchestrator wiederverwenden — entdeckt lokale Server, gruppiert sie in Capability-Bundles (`capability-bundles.json` kennt bereits das Keyword `bach`), empfiehlt/aktiviert das passende Bundle pro Aufgabenkontext und schreibt die `--mcp-config`. Granularität = Server/Bundle (host-config-basiert), kein Per-Call-Loading; Auth/Gateway/Tool-Level-Rechte sind dort noch **nicht** gebaut → für fremde Nutzer (noch) keine Schutzschicht.
3. **In-Server-Lazy-Loading:** innerhalb eines Bundles den Long-Tail über Meta-Tools (`bach_search_tools` → `bach_run`) + `tools/list`-Pagination + `listChanged` exponieren — aufgesetzt auf BACHs **vorhandene** Auto-Discovery (`core/registry.py`, `core/plugin_api.py`). Das generische Plugin-Muster (vgl. `.AI/.MODULES/plugin_system_example`) ist hier bereits umgesetzt und NICHT erneut einzubauen (Duplikat-Vermeidung).

### Anbieter-Modelle

| Modell | Inhalt | Risiko | Eignung |
|---|---|---|---|
| A — Personal (stdio) | bestehenden Server vervollständigen + `bach mcp serve` | niedrig | Quick Win |
| **B — Open-Source-Paket** | `bach-mcp` (PyPI/uvx), jeder hostet eigene BACH-Instanz (1 Instanz = 1 Nutzer = 1 DB) | niedrig | **empfohlener Anbieter-Pfad** |
| C — Hosted Multi-Tenant | Streamable HTTP + OAuth 2.1 + echte Mandanten-Isolation | hoch (DSGVO) | nur mit Datenschutzkonzept |

### Plan (abhängigkeitsgetrieben, ohne Zeitangaben)

1. Bestehenden `mcp_server.py` als first-class `bach mcp serve` integrieren, in MCP-Profil eintragen, **eigene Tests** (heute keine für den Selbst-Server).
2. Registry-getriebene Tool-Generierung + Meta-Tool/Pagination (Tool-Bloat lösen).
3. Capability-Bundles definieren; ControlCenter als Control-Plane andocken.
4. `bach-mcp` als PyPI/uvx-Paket veröffentlichen (Modell B); ORG08-Distributions-Playbook auf den Python-Server anwenden.
5. Nur bei Bedarf: Modell C mit HTTP/Auth/Mandanten-Isolation und vorgeschaltetem Datenschutzkonzept.

### Referenzen

- Machbarkeitsanalyse: diese ROADMAP-Sektion
- Bestehender Server: `system/tools/mcp_server.py` (v2.2.0)
- Control-Plane: `ellmos-ai/ellmos-controlcenter-mcp` (lokal `.AI/.MCP/ellmos-controlcenter-mcp`)
- Plugin-Muster (bereits in BACH): `core/registry.py`, `core/plugin_api.py` (vgl. `.AI/.MODULES/plugin_system_example`)
- Gegenanalyse „lokal redundant": `wiki/mcp_toolstack.txt`
- Distributionshinweise: `system/skills/workflows/npm-mcp-publish.md` und diese ROADMAP-Sektion


---

## Cross-Source-Wissensindex (Notiz 2026-07-06)

Erkenntnis aus dem ctx-/n8n-manager-Strang (Luca King / ctxrs).

- **Befund:** BACH hat **keine echte Volltext-/FTS-Suche** — die Suche im
  DB-/Command-Layer ist substring-/prefix-/regex-basiert (kein SQLite FTS5,
  empirisch 2026-07-06 per Grep bestätigt).
- **Bedarf:** (a) Volltextsuche über das BACH-Gedächtnis; (b) — wichtiger —
  Anschluss an einen **quellenübergreifenden** Index, der BACH, Gardener,
  Rinnsal und optional Agent-Transkripte gemeinsam durchsuchbar macht.
- **Richtung:** NICHT pro System eigenes FTS nachbauen, sondern ein gemeinsames,
  **pull/passiv** arbeitendes Modul (indexiert, was da ist — Gardener/USMC-Lehre:
  push-Speicher bleiben leer). Konzept:
  `.AI/.MODULES/knowledge-index/KONZEPT.md`. BACH wäre dort **Quelle** (Adapter
  über `bach.db`) und **Nutzer** (Suche via Lib/CLI/MCP).
- **Referenz/Alternative:** `ctx` (ctxrs, Apache-2.0) als Vorbild; deckt aber nur
  Coding-Agent-Transkripte ab, nicht die BACH-DB. Eigenbau bevorzugt.
