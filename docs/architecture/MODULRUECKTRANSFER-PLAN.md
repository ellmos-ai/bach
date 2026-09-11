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
| **3** | `accounts-core` | `system/gui/server.py`<br>`system/hub/steuer.py` | `accounts_core.AccountStore`<br>(Bankkonten, CAMT-Import, Salden) | Welle 2 aktiv mit AST-Wächter (`test_accounts_via_accounts_core.py`). Welle 3 steht an. |
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

### Stufe 2: `ellmos-tests` Adapter scharfschalten (Task 1218 & Task 1181)
- Scharfschaltung des Adapters in `system/hub/test.py`.
- Verifikation gegen bestehende 140+ Testdateien in `system/tests/`.
- Sicherstellung von `--dry-run` und unterbrechungsfreiem Fallback auf native Pytest-Ausführung.

### Stufe 3: `ellmos-scheduler` Provider-Seam verdrahten (Task 1219)
- Verdrahtung von `system/hub/scheduler_provider.py` mit installiertem `ellmos-scheduler`.
- Testen des Daemon-Laufs unter Windows und macOS (Mac Studio).
- Erhalt des lokalen SQLite-Job-Stores als Fail-Closed-Fallback.

### Stufe 4: `accounts-core` Welle 3 abschließen (Task 1220)
- Entflechtung der verbleibenden Ausgaben-, Fixkosten- und Saldenlogik in `hub/steuer.py`.
- Ausbau des Regressionswächters `tests/test_accounts_via_accounts_core.py`.

### Stufe 5: `system-explorer` Topology- & Health-Checks (Task 1221)
- Anbindung an `bach setup preflight` und `bach upgrade check`.
- Unabhängiges Scannen von Port 8000, 8081 und Zombie-Prozessen.

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
