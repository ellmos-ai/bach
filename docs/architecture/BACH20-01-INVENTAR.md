# BACH20-01 — Core-/Modul-Inventar und Datenflusskarte

> **Dokument-ID:** BACH20-01-INVENTAR-2026-09-27
> **Quellen:** MODULRUECKTRANSFER-PLAN-2026-09-11, MODULRUECKTRANSFER-ZERTIFIKAT-2026-09-12 (Primärquelle, Stufe-1-Wiederverwendung gemäß Plan)
> **Task:** #1349 (BACH20-Kette #1349–#1359, alle P2)
> **Verbindlicher Input für:** #1350 (Systemmanifest)

---

## 1. Klassifikation der Flächen

| Klasse | Fläche | Befund |
|---|---|---|
| **Core** | `system/core/` | Bleibt hub-frei (`hooks.py` mit Interceptor-Slot, `safe_db.py`); keine externen Repo-Abhängigkeiten. |
| **Modul** | 8 externe Repos | Zertifizierte TRANSFER-Module, siehe §2. Alle über Provider-Seams mit Env-Schalter angebunden. |
| **Adapter** | `hub/*_provider.py`, `hub/test.py`, `hub/notify.py`, Seams in `hub/steuer.py`, `gui/server.py` | Dünne Übergabeschicht zwischen hub-Handlern und externen Modulen; halten die Env-Schalter und den Legacy-Fallback. |
| **Daten** | `BACH_DB` (kanonisches Runtime-DB-Verzeichnis) | **Nicht** `system/data/` im Checkout. memoryhooker liest read-only gegen BACH_DB; accounts-core führt keine rohe `bank_accounts`-SQL mehr. |
| **Legacy** | `_archive/` | Nur Prä-Transfer-Altlasten (Stand 2026-09-01). `hub/prosync.py` existiert nicht mehr. `hub/daemon.py` ist dokumentierter Dauer-Kompat-Wrapper. **Archivierung der internen Fallback-Pfade ist KONTRAINDIZIERT** bis #1340/#1341 abgeschlossen: sie sind Rollback-Ziele der 6 Env-Schalter. |

---

## 2. Modul-Inventar (8 TRANSFER-Module, Zertifikats-Matrix)

| # | Modul | Pin (Soll) | Ist-Stand | Adapter/Seam | Rollback (Env-Schalter) | Status |
|---|---|---|---|---|---|---|
| 1 | ellmos-tests | checkout-basiert (kein pip-Pin) | = Soll | `hub/test.py` | `--native`-Flag | ✅ |
| 2 | ellmos-scheduler | `296b6f5` | = Soll | `hub/scheduler_provider.py` | `BACH_USE_EXTERNAL_SCHEDULER=0` | ✅ |
| 3 | accounts-core | `v0.1.1` / `9e0d0e9` | `0166805` = exakt Tag-Commit | `gui/server.py` + `hub/steuer.py` (Welle 2+3); Fachkern ersetzt, Wächter scharf | — | ✅ |
| 4 | assistant-core | `444a1fff` (`v0.2.0`) | `444a1fff` = Soll (auf mac-studio seit 2026-09-17) | `hub/notify.py` + `_services/chat/` (Welle 1+2) | — | ✅ **B1 GELÖST (2026-09-17 hostabhängig)** |
| 5 | system-explorer | `bd250b1a` | = Soll | `hub/explorer_provider.py` + `system_audit.py` nativ | `BACH_USE_EXTERNAL_EXPLORER=0` | ✅ |
| 6 | memoryhooker | `94611c25` | = Soll | `hub/memory_hook_provider.py` → `ChatRuntime.process` | `BACH_USE_EXTERNAL_MEMORYHOOKS=0` | ✅ |
| 7 | workflowhooker | `6d2b1908` | = Soll | `hub/workflow_hook_provider.py` → `core/hooks.py` Interceptor-Slot | `BACH_USE_EXTERNAL_WORKFLOWHOOKS=0` | ✅ |
| 8 | sqlite-transit-sync | `40e99262` | = Soll | `hub/transit_sync_provider.py` → DBSyncManager | `BACH_USE_EXTERNAL_TRANSITSYNC=0` | ✅ |

### Abweichung B1 (assistant-core, Modul 4) — GELÖST

- **Befund:** Ist-Commit `ccadcf9` (`v0.1.0`) weicht vom Pin `444a1fff` (`v0.2.0`) ab. — **Überholt, siehe unten.**
- **Hostabhängig:** WORKSTATION-LG 4/4 grün; mac-studio Collection-Error.
- **Klärungs-Task:** #1341 (Pin-Klärung), MRP-Auflösung #1382.
- **Auflösung (2026-09-27, MRP Stufe 8 / #1382):** Auf **mac-studio** wurde der Lokal-Checkout bereits am **2026-09-17** per Reflog-Checkout von `ccadcf9` auf `444a1fff` gezogen (HEAD = Pin, .git/HEAD geprüft). **Testnachweis 2026-09-27:** `pytest system/tests/test_notify_via_assistant_core.py -q` → **4/4 grün** (Nachweis lt. OPERATOR-1240 Z.79). Damit ist B1 auf mac-studio vollständig gelöst. Rest offen in #1341: hostübergreifender Abschluss/Abschlussvermerk (Windows-Gegenprobe 2026-09-21 bereits 4/4 grün).

---

## 3. Datenflusskarte

```
User
 └─► GUI / CLI
      └─► hub-Handler
           └─► Provider-Seam (Env-Schalter: BACH_USE_EXTERNAL_*)
                ├─► externes Modul (8er-Matrix, §2)
                └─► Legacy-Fallback (interne Pfade — Rollback-Ziele, nicht archivieren!)
                     └─► BACH_DB  bzw.  DBSyncManager / transit-sync
```

**Nebenflüsse:**

- **Audit:** via JSONL durch memoryhooker (read-only gegen BACH_DB).
- **Claims / PID-Binding:** agent-launcher ist ein separater **OC-B**-Strang, opt-in über `BACH_USE_EXTERNAL_AGENT_REGISTRY=1` und **nicht** Teil der 8er-Zertifizierung.

---

## 4. Offene Gates / Folgeverweise

| Gate | Stand | Task |
|---|---|---|
| Windows-Gegenproben Stufen 2, 3, 5, 7 | offen | laut Zertifikat |
| Multi-Host-Lauf Stufe 7 | offen | laut Zertifikat |
| Abweichung B1 (assistant-core Pin) | gelöst 2026-09-17 (mac-studio), Test 2026-09-27 grün; Abschluss offen | **#1341** |
| Archivierung interner Fallback-Pfade | kontraindiziert bis #1340/#1341 | **#1340** |
| Systemmanifest | Input dieses Dokuments | **#1350** |

---

## 5. Abweichungen zur Primärquelle

- Der MODULRUECKTRANSFER-PLAN Stufe 1 wurde als Primärquelle wiederverwendet; die Matrix in §2 spiegelt die Zertifikats-Matrix 1:1.
- **Ehemalige einzige inhaltliche Abweichung:** B1 (assistant-core) war im Zertifikat befundet; seit 2026-09-17 gelöst (2026-09-27 verifiziert), Rest = Abschluss-Vermerk in #1341.
- Keine weiteren Abweichungen; Legacy-Fläche `_archive/` bewusst unverändert (Rollback-Integrität).

---

*Erstellt: 2026-09-27 · Quellenstand: PLAN-2026-09-11, ZERTIFIKAT-2026-09-12 · Abschlussgrenze: vollständige Klassifikation aller Flächen (Core / Modul / Adapter / Daten / Legacy) inkl. Datenflusskarte — erreicht.*
