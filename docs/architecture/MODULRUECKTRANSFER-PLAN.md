# Modulrücktransfer in BACH — Feingranularer Umsetzungsplan & Schnittstellenmatrix

> **Dokument-ID:** `MODULRUECKTRANSFER-PLAN-2026-09-11`  
> **Status:** Genehmigt & Aktiv (`Wettbewerb beendet`, Task 1184 abgeschlossen)  
> **Geltungsbereich:** `C:/_Local_DEV/repos/bach` (Plan D), Partnersysteme via `.SYNC`  
> **Kanonische Tasks:** `bach task list all --filter "TRANSFER"` (Tasks 1217–1224)

---

## 1. Ausgangslage & Governance

Nach erfolgreichem Abschluss des judging-hold Staus, dem Release von **BACH v3.14.0** und der weltweiten Veröffentlichung von **Open Ocean** startet die schrittweise, gegatete Rückführung der modularisierten Komponenten in BACH.

Gemäß den Grundsätzen aus der BACH-Roadmap und den Nutzerentscheidungen (`D-20260906-005`, `D-20260906-006`):
1. **Funktionale Parität an Usecases:** Rücktransport ist keine Veröffentlichungsblockade für Module, sondern ein kontinuierlicher Integrationsprozess.
2. **Gatung vor Ablösung:** Ein externes Modul ersetzt interne Teile erst bei belegter Gleichwertigkeit, grünem Parallelbetrieb und nachgewiesenem Rollback-Pfad.
3. **Fail-Closed & Archivierung:** Altteile werden niemals blind gelöscht, sondern nach einer Haltefrist in `system/hub/_archive/` strukturiert archiviert.
4. **AST- & Contract-Wächter:** Jede Modulintegration wird durch statische AST-Tests gegen Code-Drift und Re-Monolithisierung abgesichert.

---

## 2. Schnittstellenmatrix der 8 Modulkandidaten

| Nr | Modul / Repo | BACH-Zielbereich | Schnittstelle / Adapter | Status / Vorarbeit |
|:---|:---|:---|:---|:---|
| **1** | `ellmos-tests` | `system/hub/test.py`<br>`tools/testing/` | `TestAdapter` / `RunnerSeam`<br>CLI: `bach test` | Vorbereitet in Task 1181 (`2bf77f9`). Rollback & Testsuite-Isolation intakt. |
| **2** | `ellmos-scheduler` | `system/hub/scheduler.py`<br>`system/hub/scheduler_provider.py` | `SchedulerProvider` Interface<br>(Jobs, Chains, Intervalle) | Provider-Seam in `system/hub/scheduler_provider.py` integriert (`ec3ab1f`). Fallback aktiv. |
| **3** | `accounts-core` | `system/gui/server.py`<br>`system/hub/steuer.py` | `accounts_core.AccountStore`<br>(Bankkonten, CAMT-Import, Salden) | Welle 3 abgeschlossen (2026-09-12): keine rohe bank_accounts-SQL, tote Salden-Kette (`parse_balances`) scharfgeschaltet, Wächter ausgebaut (`test_accounts_via_accounts_core.py`, 23 Tests). |
| **4** | `assistant-core` | `system/hub/notify.py`<br>`system/hub/_services/chat/` | `assistant_core.NotificationService`<br>`NotifyStorage`, Order-Broker | Welle 1 (Nachrichten) & Welle 2 (Notify-Fachkern) auf v0.2.0 in `main` gemergt. |
| **5** | `system-explorer` | `system/hub/setup.py`<br>`system/hub/upgrade.py` | `SystemTopologyScanner`<br>Prozess-, Lock- & Port-Audits | Modul eigenständig verifiziert; Adapter für Preflight- und System-Health-Checks. |
| **6** | `memoryhooker` | `system/hub/memory.py`<br>`system/hub/_services/chat/` | `MemoryHookProvider`<br>Session-Lifecycle & Context Hooks | Stufe 6 abgeschlossen (2026-09-12): In-process-Seam `hub/memory_hook_provider.py`; `BachMemoryBackend` read-only gegen BACH_DB; `ChatRuntime.process`-Injektion mit Cap/Cooldown + JSONL-Audit-Trail. Rollback `BACH_USE_EXTERNAL_MEMORYHOOKS=0`. |
| **7** | `workflowhooker`| `system/core/hooks.py`<br>`system/hub/scheduler.py` | `WorkflowInterceptor`<br>Ereignisbasierte Step-Trigger | Stufe 6 abgeschlossen (2026-09-12): generischer Interceptor-Slot in `HookRegistry.emit` (core bleibt hub-frei); `hub/workflow_hook_provider.py`, Installation via `hub/__init__.py`; Budget/Cooldown/Idle im Modul. Rollback `BACH_USE_EXTERNAL_WORKFLOWHOOKS=0`. |
| **8** | `sqlite-transit-sync` | `system/hub/prosync.py`<br>`system/core/safe_db.py` | `TransitSyncProvider`<br>Multi-Host Delta-Replikation | Ersetzt volatile ProSync-Skripte durch zustandsorientierte, konfliktfreie Delta-Syncs. |

---

## 3. Stufenplan & Task-Kette

### Stufe 1: Inventar & Schnittstellenmatrix (Task 1217) — *ABGESCHLOSSEN*
- Bestandsaufnahme der 8 Module, Abhängigkeitsanalyse, Pin-Prüfung in `requirements.txt`.
- Masterplan unter `docs/architecture/MODULRUECKTRANSFER-PLAN.md`.

### Stufe 2: `ellmos-tests` Adapter scharfschalten (Task 1218 & Task 1181) — *ABGESCHLOSSEN (2026-09-12)*
- Scharfschaltung des Adapters in `system/hub/test.py`.
- Verifikation gegen bestehende 140+ Testdateien in `system/tests/`.
- Sicherstellung von `--dry-run` und unterbrechungsfreiem Fallback auf native Pytest-Ausführung.
- **Nachweise (mac-studio):** Syntaxfehler behoben — der Adapter war zuvor nicht importierbar
  (ungueltige String-Konkatenation, 3 Stellen). `ELLMOS_PROFILES` auf den Contract von
  `run_external.py` korrigiert (QUICK/STANDARD/FULL; OBSERVATION/OUTPUT legacy-only via `--native`).
  `--dry-run` in allen Pfaden implementiert (self/run/compare). Adapter aktiv:
  `bach --test profiles` → ellmos-tests; QUICK-Lauf via Adapter: B001 Score 5.0
  (Artefakt `system_diff_tests/output/system/EXTERNAL_TEST_system_2026-09-12.json`).
  Rollback: `bach --test self QUICK --native` → legacy Runner 5.0/5.0
  (`tools/testing/results/system/TEST_system_QUICK_2026-09-12.json`).
  Regressionstests: `tests/test_test_handler_adapter.py` (15 Tests, gruen).
  Praexistente Suite-Fehler (openpyxl/docx fehlen, assistant_core-Import) sind
  Umgebung/Stufe-5-Themen, nicht TRANSFER-02 (via Stash auf HEAD verifiziert).

### Stufe 3: `ellmos-scheduler` Provider-Seam verdrahten (Task 1219) — *ABGESCHLOSSEN (2026-09-12)*
- Verdrahtung von `system/hub/scheduler_provider.py` mit installiertem `ellmos-scheduler`
  (v0.3.3, Pin `296b6f5` in `requirements.txt`; editable im BACH-Venv, Klon unter
  `~/services/ellmos-scheduler`).
- Rollback-Schalter `BACH_USE_EXTERNAL_SCHEDULER=0` (Plan-Regel 4.1) in Probe und Doctor
  verdrahtet; Adapter-Factory `create_external_scheduler_adapter` mit fail-closed
  Vertragspruefung (`create_bach_adapter`-Contract).
- Neue CLI-Gruppe `bach scheduler external status|jobs|verify [--apply]`: read-only Verify
  der Legacy-Jobs (Quelle via `mode=ro`), idempotente Praemigration mit Provenienz
  `bach:<id>` in den isolierten State-Store `system/data/scheduler_external/state.db`.
  Der lokale SQLite-Job-Store bleibt unberuehrt als Fail-Closed-Fallback.
- **Nachweise (mac-studio):** Daemon-Lauf `ellmos-scheduler serve` mit Lease-Claim und
  Run-Receipts (2x succeeded, exit 0, Wiederanlauf nach Kill). `external verify` Dry-Run
  gegen die Produktiv-DB: 4 Jobs, 0 ready, 4 skipped mit dokumentierten Gruenden —
  Bare-Command-Namen (`translation_qa_*`, `db_backup`, `log_rotation`) sind keine
  PATH-Executables; die Shell-Semantik des Legacy-Daemons (`shell=True`) wird bewusst
  nicht emuliert. Vor `--apply` ist eine explizite argv-Konvertierung der 4 Jobs noetig.
  Rollback-Gate live verifiziert (`BACH_USE_EXTERNAL_SCHEDULER=0` → fail-closed,
  Legacy-Lesepfade unberuehrt).
- Windows-Gegenprobe (WORKSTATION-LG) bleibt als Host-Aufgabe offen (Plan-Regel 4.3).
- Regressionstests: `tests/test_scheduler_provider_wiring.py` (28 Tests; Rollback,
  Factory-Contract, Dispatch, Idempotenz, Tick-Ausfuehrung, AST-Waechter gegen
  Direktimporte ausserhalb des Seams) — 30/30 gruen mit `test_scheduler_provider.py`.

### Stufe 4: `accounts-core` Welle 3 abschließen (Task 1220) — *ABGESCHLOSSEN (2026-09-12)*
- Entflechtung der verbleibenden Ausgaben-, Fixkosten- und Saldenlogik in `hub/steuer.py`.
- Ausbau des Regressionswächters `tests/test_accounts_via_accounts_core.py`.
- **Befund:** Keine rohe bank_accounts-SQL mehr in BACH (Welle 2 vollständig),
  ABER die Salden-Kette war tot: Der D-013-Fix (`9ff3df2`) mit
  `CamtParser.parse_balances()` existierte nur in der gitignorierten
  Betriebsinstallation; der öffentliche Baum hatte die Methode nie, und
  `_import_camt` degradierte via `hasattr`-Fallback lautlos zu „keine Salden".
  Zusätzlich fehlte die deklarierte Abhängigkeit `defusedxml` im BACH-Venv
  (Importfehler). Der accounts-core-README-Contract („die Form, die BACHs
  CamtParser.parse_balances() liefert") hatte einen nicht existenten Produzenten.
- **Nachweise (mac-studio):** `parse_balances()` im öffentlichen
  `tools/steuer/camt_parser.py` implementiert (nur CLBD, OPBD bewusst nicht;
  DBIT negiert; DtTm → Datumsteil; ohne IBAN → `UNKNOWN`-Sentinel, das
  accounts_core mit Warnung überspringt). `hub/steuer.py` ruft direkt auf,
  hasattr-Fallback entfernt. `defusedxml>=0.7.1` ins Venv installiert
  (requirements.txt-Zeile 22 bereits deklariert). End-to-End verifiziert:
  UPDATE-Pfad (vorhandenes Konto, IBAN-normalisiert, Name bleibt) und
  INSERT-Pfad (`CAMT-Import ****3000`), Dry-Run zeigt Salden und schreibt
  nichts, „ohne CLBD" → `[WARN] Keine Salden ... unverändert.`
  CLI-Nachweis: `python3 bach.py steuer import camt <auszug.xml> --dry-run`
  → Saldenzeile (vorher: „keine Salden gefunden"). Beide Produktiv-DBs
  (`system/data/bach.db`, `~/.bach/bach.db`) haben 0 Konten — keine
  Produktivdaten betroffen. Regressionswächter ausgebaut:
  `tests/test_accounts_via_accounts_core.py` 9 → 23 Tests (Contract-Shape,
  OPBD-Ignore, DBIT/DtTm, UNKNOWN, Namespace-Autodetektion, End-to-End
  UPDATE/INSERT, Dry-Run, Warn-Weiterleitung, tote-Kette-Wächter:
  `parse_balances` muss existieren + steuer.py muss direkt aufrufen +
  camt_parser.py bleibt reiner XML-Produzent ohne sqlite/bank_accounts +
  in GUARDED_FILES aufgenommen). 114 Tests grün im betroffenen Umfeld
  (accounts/steuer/financial_summary).

### Stufe 5: `system-explorer` Topology- & Health-Checks (Task 1221) — *ABGESCHLOSSEN (2026-09-12)*
- Anbindung an `bach setup preflight` und `bach upgrade check`.
- Unabhängiges Scannen von Port 8000, 8081 und Zombie-Prozessen.
- **Umsetzung:** Native Audits in `system/hub/system_audit.py` (UNABHÄNGIG vom
  Modul): Port-8000/8081-Prüfung mit Prozess-Zuordnung (psutil, macOS-lsof-
  Fallback ohne Root), Zombie-Scan (defunct, BACH-Zombies markiert),
  Lock-/PID-Audit im DATA_DIR (live/stale/foreign/unklar). Externer
  Topologie-Scan über Provider-Seam `system/hub/explorer_provider.py`
  (find_spec-Probe, fail-closed Contract-Factory, Rollback
  `BACH_USE_EXTERNAL_EXPLORER=0`, Budget `BACH_EXPLORER_SCAN_BUDGET`):
  begrenzter Scan (10s Default, include md/json/toml/yaml, data/logs/
  explorer_state exkludiert) in Temp-Store, Knotenzählung je Typ.
- **Nachweise (mac-studio):** Preflight zeigt Port 8000/8081 korrekt als
  „belegt durch BACH" (GUI-Server PID + Control-Port PID via lsof-Fallback,
  da psutil.net_connections auf macOS AccessDenied wirft) und
  Topologie-Evidenz „280→251 Dateien, 12→9 registries, 0.6s";
  `upgrade --check` (Text + `--json`) hängt Topologie-Audit an und erkennt
  Drift gegen `data/explorer_state/last_topology.json` (Persistenz nur im
  Upgrade-Check als Drift-Monitor; Nachweis: 280→281 durch das eigene
  State-File, danach exkludiert → 0 Drift). Rollback-Matrix
  (0/false/no/off) → „Topologie-Scan: deaktiviert"; native Audits laufen
  weiter. Wächter: `system/tests/test_explorer_provider_wiring.py`
  (Probe/Rollback, Port frei/belegt, Zombie-Fakes, Lock-Zustände,
  Factory fail-closed, Fixture-Scan, Drift 3-Phasen, Preflight/Upgrade-
  Verdrahtung, AST-Guards: setup/upgrade importieren den Seam,
  system_audit bleibt modulunabhängig, kein Direktimport im hub). Pin:
  `system-explorer@bd250b1` in requirements.txt.

### Stufe 6: `memoryhooker` & `workflowhooker` Verdrahtung (Task 1222) — *ABGESCHLOSSEN (2026-09-12)*
- Dynamisches Einhängen in `ChatRuntime.process` und `HookRegistry.emit`
  (der Registry-Singleton entspricht dem HookManager) + Audit-Trail.
- **Umsetzung:**
  - `system/hub/memory_hook_provider.py`: In-process-Seam (Probe via find_spec,
    Rollback `BACH_USE_EXTERNAL_MEMORYHOOKS=0`, fail-closed Contract gegen die
    modes/state/config/protocol-Symbole). `BachMemoryBackend` implementiert das
    MemoryBackend-Protocol read-only (`mode=ro`) gegen BACH_DB — die
    „documented read-only API", auf die memoryhookers reservierter `bach`-
    Backend-Slot wartet; Ranking nach BACH-Termmatch-Semantik x Curation
    (Fakt-Konfidenz, Lesson-Severity, Working-Basis 0.4), normalisiert auf
    (0,1]. Verdrahtung: `ChatRuntime.process` haengt `hook_ctx` hinter
    `bach_ctx` an den System-Prompt (`--- MEMORY-HOOK ---`, fail-soft);
    `session_start_message` (einmalig je chat_id) + `evaluate_prompt`
    (remember+search; Session-Cap + Cooldown werden im Modul erzwungen).
    Der Injektor-Pfad (`_get_bach_context`) bleibt unberuehrt: Hooks !=
    Injektoren.
  - Audit-Trail: jede Kontextinjektion → JSONL neben BACH_DB
    (`~/.bach/memoryhooker_audit.jsonl`: ts, chat_id, mode, chars, message).
  - `system/hub/workflow_hook_provider.py`: `ExternalWorkflowInterceptor`
    (Event-Filter after_command/after_task_done — before_command bleibt
    optional zuschaltbar, BACH hat dafuer keine Ausgabestelle: eine
    Before-Meldung wuerde das Session-Budget unsichtbar verbrauchen,
    im Nachweislauf empirisch gefangen und korrigiert; Checks ueber
    `cli._run_active_checks` — Budget/Cooldown/Idle-Selbstabschaltung bleiben
    im Modul, State persistiert). `core/hooks.py` erhaelt einen generischen
    Interceptor-Slot (`register_interceptor`, emit ruft Interceptors VOR den
    Listenern fail-soft; Meldungen landen zusaetzlich in
    `last_interceptor_results`), Installation idempotent ueber
    `hub/__init__.py` beim Paketimport — core importiert dabei nie hub.
    Sichtbarkeit: `core/app.py` (after_command) und `hub/task.py`
    (after_task_done) haengen Interceptor-Meldungen an die Ausgabe;
    Listener-Rueckgaben bleiben still (Sichtbarkeitsregel). Rollback
    `BACH_USE_EXTERNAL_WORKFLOWHOOKS=0` wird live pro Aufruf gelesen.
- **Nachweise (mac-studio):** Backend real gegen BACH_DB (3 Hits, rank 0.73,
  read-only); process-Injektion mit Session-Start + Treffern; Cap/Cooldown
  greift (2. Injektion unterdrueckt, neue chat_id startet frisch); Audit
  2 Zeilen. Interceptor real: `before_command` → „[WorkflowHooker]
  Abschluss-Gate: 17 uncommittete Aenderung(en)"; Folgemeldung (after_task_done
  im gleichen Lauf) vom Cooldown unterdrueckt — Budget-Verhalten korrekt;
  State-Persistenz ueber Interceptor-Instanzen hinaus. E2E sichtbar:
  `app.execute('memory','status')` haengt „[WorkflowHooker] Abschluss-Gate:
  23 uncommittete Aenderung(en)" an die Message; CLI `bach task done 1229`
  zeigt die Meldung direkt unter „[OK] Task 1229 erledigt!" (after_task_done-
  Pfad). Waechter:
  `system/tests/test_hook_provider_wiring.py` (51 Tests: Rollback-Matrizen,
  Backend read-only/Ranking/Inactive-Ignore, Cap/Cooldown/Audit,
  Interceptor-Event-Filter/Budget/Persistenz, Registry-Slot,
  Duplikat-Guard, AST-Import-Richtung, Sichtbarkeits-Verdrahtung,
  Injektor- und Subprozess-Transport unberuehrt). 164 Tests gruen im
  Stufen-Umfeld (2/3/5/6 + accounts + Test-Adapter zusammen).
- **Grenzen/Betriebshinweise:** bach.py-CLI feuert historisch keine
  before/after_command-Events — Command-Sichtbarkeit wirkt im
  app.execute-Pfad (MCP-Server tools/mcp_server.py, Library-API bach_api)
  und im Task-Pfad (task done); ein CLI-Command-Hook-Ausbau waere eine
  Betriebsentscheidung. Der Subprozess-Transport
  (`hub/_services/chat/hooks.py`, `~/.config/bach/chat_hooks.json`,
  PostToolUse, Claude-Code-stdin-JSON-Format) bleibt eigenstaendig
  unberuehrt; dort ist „Stop" konfiguriert, wird aber von keinem
  Transportpunkt gefeuert (Betriebs-Hinweis fuer die Snippet-Seite).
  `core/agent_runtime.py` und `core/app.py` (2 lazy Imports) tragen
  historische hub-Imports pra-Stufe-6 (dokumentiert; AST-Waechter
  fokussiert auf die Stufe-6-Dateien).
- Pins: `memoryhooker@94611c2`, `workflowhooker@6d2b190` in requirements.txt.

### Stufe 7: `sqlite-transit-sync` Replikation (Task 1223) — *ABGESCHLOSSEN (2026-09-12)*
- Kopplung von ProSync an `sqlite-transit-sync` für sauberen 3-Wege-Zustand (`WORKSTATION-LG`, `ASUS-GEI`, `mac-studio`).
- **Umsetzung:**
  - `system/hub/transit_sync_provider.py`: Provider-Seam nach dem
    Explorer-Muster (find_spec-Probe ohne Import, fail-closed Contract gegen
    `SyncConfig`/`TransitSync`/`MergeReport`/`Snapshot`, Rollback
    `BACH_USE_EXTERNAL_TRANSITSYNC=0`). `ExternalTransitSyncEngine` mappt den
    ProSync-Lebenszyklus auf verifizierte Snapshots (push/pull/pending/
    sync/cleanup); Namespace `bach`, Merge-State-Datei liegt nach
    `SyncConfig`-Hardinvariante ausserhalb des Transit-Verzeichnisses
    (`~/.bach/transit_sync_state/state.json`).
  - `system/hub/db_sync.py`: `DBSyncManager` routet `sync_on_start` (Pull),
    `sync_on_exit` (Push) und `sync()` (Pull+Push) lazy über die Engine, wenn
    das Modul importierbar ist; Vertragsbruch/Importfehler degradieren nicht
    still, sondern bleiben über `get_status()` sichtbar (fail-closed, Legacy
    bleibt aktiv). Der Legacy-Pfad (.bachdb/mtime/Heartbeat-Prompt) ist unter
    dem Rollback-Schalter unveraendert; `test_db_sync_handler.py` pinnt ihn
    via `BACH_USE_EXTERNAL_TRANSITSYNC=0` autouse-Fixture.
  - Merge-Semantik-Paritaet: Timestamp-LWW ueber (updated_at, modified_at,
    created_at), `secrets` standardmaessig exkludiert, keine
    Deletions-Propagation (gleiche Grenze wie der Legacy-Merge).
- **Nachweise (mac-studio):** Probe/Factory/Rollback-Tests;
  2-Knoten-Push/Pull mit LWW-Konfliktloesung und State-Gate
  (Re-Pull = No-op, kein Replay); Secrets-Ausschluss; **lokale
  3-Wege-Simulation** (WORKSTATION-LG/ASUS-GEI/mac-studio als getrennte
  DBs ueber einem gemeinsamen Transit-Verzeichnis): konfliktfreie
  Konvergenz aller drei Knoten, keine Eigen-Imports, stabile Zweitpulls.
- **Wächter:** `system/tests/test_transit_sync_provider_wiring.py`
  (26 Tests inkl. AST-Guards: db_sync verdrahtet den Seam, hub importiert
  das Modul nicht direkt, core bleibt unabhaengig, Rollback-Env im Plan,
  requirements-Pin). Pin: `sqlite-transit-sync@40e9926` in requirements.txt.
- **Offener Betriebs-Nachlauf (Plan-Regel 4.3):** echter Multi-Host-Lauf
  (Push/Pull ueber den OneDrive-Transit zwischen WORKSTATION-LG, ASUS-GEI,
  mac-studio) inkl. Windows-Gegenprobe; bis dahin gilt das Legacy-Verhalten
  auf Hosts ohne installiertes Modul unveraendert fort.

### Stufe 8: Single-Source-of-Truth Zertifizierung (Task 1224) — *ABGESCHLOSSEN ALS PRÜFUNG MIT FESTSTELLUNGEN (2026-09-12)*
- Reife-Zertifizierung aller 8 Module, Nullreferenznachweis auf Altschrott, Verschiebung des Altcodes nach `system/hub/_archive/`.
- **Ergebnis (Zertifikat `MODULRUECKTRANSFER-ZERTIFIKAT-2026-09-12.md`):**
  7/8 Module pin-konform, 225 Wächter-Tests grün (mac-studio).
  **Abweichung B1:** assistant-core-Checkout auf diesem Host v0.1.0 statt Pin
  `444a1fff` (v0.2.0); fetch erfordert interaktive Credentials (privates Repo);
  `test_notify_via_assistant_core.py` dadurch Collection-Error — Operator-Aufgabe.
- **Nullreferenznachweis: bestanden.** Kein toter Modul-Altcode vorhanden:
  `hub/prosync.py` existiert nicht (ProSync-Strings = aktives Legacy-Verfahren),
  keine Einzel-Sync-Skripte, keine Alt-Test-Runner; `hub/daemon.py` ist
  dokumentierter Dauer-Kompat-Wrapper (kein Kandidat). `_archive/` traegt nur
  Prae-Transfer-Altlasten vom 2026-09-01.
- **Archivierung KONTRAINDIZIERT zum Prüfzeitpunkt:** Haltefrist (§1.3) am
  Abschlusstag nicht abgelaufen; die internen Pfade sind zugleich die
  Rollback-Ziele der sechs Env-Schalter (§4.1) — Verschiebung zerstoerte die
  Reversibilitaet; Windows-Gegenproben (§4.3, Stufen 2/3/5/7) und der echte
  3-Host-Lauf (Stufe 7 Nachlauf) fehlen; B1 offen.
- **Auslagerung:** ARCHIVIERUNG + Gates → **Task TRANSFER-09** (s. Zertifikat §5).

---

## 4. Rollback- & Sicherheitsregeln

1. **Jeder Schritt reversibel:** Jede Änderung muss sich durch das Umlegen eines Env-Schalters (z. B. `BACH_USE_EXTERNAL_SCHEDULER=0`) sofort auf den internen Codepfad zurückstellen lassen.
2. **Kein Datenverlust:** Migrationen von Tabellen berühren niemals Produktivbestände ohne automatischen Snapshot nach `~/.bach/backups/`.
3. **Plattformparität:** Alle Änderungen werden vor dem Release auf Windows (`WORKSTATION-LG`) und macOS (`mac-studio`) gegengeprüft.
