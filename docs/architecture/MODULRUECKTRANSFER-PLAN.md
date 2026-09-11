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
| **6** | `memoryhooker` | `system/hub/memory.py`<br>`system/hub/_services/chat/` | `MemoryHookProvider`<br>Session-Lifecycle & Context Hooks | Ergänzt Task 1174 (Session-Provenienz) um dynamische Kontext- und Decay-Hooks. |
| **7** | `workflowhooker`| `system/core/hooks.py`<br>`system/hub/scheduler.py` | `WorkflowInterceptor`<br>Ereignisbasierte Step-Trigger | Entflechtung der HookManager-Callbacks in standardisierte Life-Cycle-Events. |
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

### Stufe 6: `memoryhooker` & `workflowhooker` Verdrahtung (Task 1222)
- Dynamisches Einhängen von Hookern in `ChatRuntime.process` und `HookManager.emit`.
- Audit-Trail für jede Kontextinjektion.

### Stufe 7: `sqlite-transit-sync` Replikation (Task 1223)
- Kopplung von ProSync an `sqlite-transit-sync` für sauberen 3-Wege-Zustand (`WORKSTATION-LG`, `ASUS-GEI`, `mac-studio`).

### Stufe 8: Single-Source-of-Truth Zertifizierung (Task 1224)
- Reife-Zertifizierung aller 8 Module, Nullreferenznachweis auf Altschrott, Verschiebung des Altcodes nach `system/hub/_archive/`.

---

## 4. Rollback- & Sicherheitsregeln

1. **Jeder Schritt reversibel:** Jede Änderung muss sich durch das Umlegen eines Env-Schalters (z. B. `BACH_USE_EXTERNAL_SCHEDULER=0`) sofort auf den internen Codepfad zurückstellen lassen.
2. **Kein Datenverlust:** Migrationen von Tabellen berühren niemals Produktivbestände ohne automatischen Snapshot nach `~/.bach/backups/`.
3. **Plattformparität:** Alle Änderungen werden vor dem Release auf Windows (`WORKSTATION-LG`) und macOS (`mac-studio`) gegengeprüft.
