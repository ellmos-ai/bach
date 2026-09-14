# Modulrücktransfer — Reife-Zertifizierung & Nullreferenznachweis

> **Dokument-ID:** `MODULRUECKTRANSFER-ZERTIFIKAT-2026-09-12`
> **Erstellt:** 2026-09-12 auf `mac-studio` (Task 1224 / Stufe 8, Abschlussprüfung)
> **Plan-Referenz:** `MODULRUECKTRANSFER-PLAN-2026-09-11`
> **Ergebnis:** 7/8 Module pin-konform zertifiziert. **Archivierung von Fallback-Pfaden derzeit KONTRAINDIZIERT** (Begründung §3). Folgetask: TRANSFER-09.

---

## 1. Zertifizierungsmatrix (Stand mac-studio, 2026-09-12)

| # | Modul | BACH-Seam / Integration | Pin (requirements.txt) | Checkout-Ist | Konform | Rollback-Schalter | Windows-Gegenprobe |
|:--|:--|:--|:--|:--|:--:|:--|:--:|
| 1 | `ellmos-tests` | `hub/test.py` Adapter (Checkout-Erkennung) | checkout-basiert (kein pip-Pin, by design) | `~/services/ellmos-tests` | ✅ | `--native` | ⬜ offen |
| 2 | `ellmos-scheduler` | `hub/scheduler_provider.py` | `296b6f5` | `296b6f5` | ✅ | `BACH_USE_EXTERNAL_SCHEDULER=0` | ❌ **offen (Plan 4.3)** |
| 3 | `accounts-core` | `gui/server.py`, `hub/steuer.py` (Welle 2+3) | `v0.1.1` (`9e0d0e9`) | `0166805` = **exakt tag-commit** | ✅ | — (Fachkern ersetzt, Wächter scharf) | ⬜ offen |
| 4 | `assistant-core` | `hub/notify.py`, `_services/chat/` (Welle 1+2) | `444a1fff` (v0.2.0) | **`ccadcf9` (v0.1.0)** | ❌ **ABWEICHUNG** | — | ⬜ offen |
| 5 | `system-explorer` | `hub/explorer_provider.py`, `hub/system_audit.py` (nativ, unabhängig) | `bd250b1a` | `bd250b1` | ✅ | `BACH_USE_EXTERNAL_EXPLORER=0` | ❌ **offen (Plan 4.3)** |
| 6 | `memoryhooker` | `hub/memory_hook_provider.py` → `ChatRuntime.process` | `94611c25` | `94611c2` | ✅ | `BACH_USE_EXTERNAL_MEMORYHOOKS=0` | ⬜ offen |
| 7 | `workflowhooker` | `hub/workflow_hook_provider.py` → `core/hooks.py` Interceptor-Slot | `6d2b1908` | `6d2b190` | ✅ | `BACH_USE_EXTERNAL_WORKFLOWHOOKS=0` | ⬜ offen |
| 8 | `sqlite-transit-sync` | `hub/transit_sync_provider.py` → `DBSyncManager` | `40e99262` | `40e9926` | ✅ | `BACH_USE_EXTERNAL_TRANSITSYNC=0` | ❌ **offen (Plan 4.3, Multi-Host-Lauf)** |

Alle Checkouts sind **arbeits sauber** (0 uncommitted Änderungen). venv: `/Users/lukas/.venvs/bach` (editable Installs aus `~/services/*`).

### Test-Nachweis (2026-09-12, mac-studio)

| Testmodul | Stufe | Ergebnis |
|:--|:--:|:--|
| `test_test_handler_adapter.py` | 2 | 15 ✅ |
| `test_scheduler_provider.py` + `test_scheduler_provider_wiring.py` | 3 | 30 ✅ |
| `test_accounts_via_accounts_core.py` | 4 | 23 ✅ |
| `test_explorer_provider_wiring.py` | 5 | ✅ (im 176er-Lauf) |
| `test_hook_provider_wiring.py` | 6 | 51 ✅ (Rollback-Matrizen, AST-Guards) |
| `test_transit_sync_provider_wiring.py` | 7 | 26 ✅ |
| `test_db_sync_handler.py` (Legacy-Pfad-Pin via autouse-Fixture) | 7 | 46 ✅ |
| `test_messages_via_assistant_core.py` (Welle 1) | 4 | 3 ✅ |
| **Summe** | | **225 Tests grün** |
| `test_notify_via_assistant_core.py` (Welle 2) | 4 | ❌ **Collection-Error** — s. Befund B1 |

---

## 2. Befunde

### B1 (offen, Operator-Aufgabe): assistant-core-Checkout nicht pin-konform
- requirements.txt pinnt `assistant-core@444a1fff…` (v0.2.0, Wellen 1+2 inkl. `NotificationService`).
- Lokaler Checkout `~/services/assistant-core` steht auf `ccadcf9` (**v0.1.0**, nur Welle 1); der Pin-Commit ist lokal **nicht vorhanden**.
- `git fetch` scheitert in nicht-interaktiven Shells: privates Repo, Credentials nicht konfiguriert (`could not read Username for 'https://github.com'`).
- Folge: `test_notify_via_assistant_core.py` schlägt mit `ImportError: cannot import name 'NotificationService'` fehl (Collection). Welle-1-Pfad (messages) ist davon **nicht** betroffen und grün.
- **Behebung (Operator):** Interaktiv im Checkout `git fetch && git checkout 444a1fff…`, danach `test_notify_via_assistant_core.py` erneut laufen lassen.
- ⚠️ **Zusatzrisiko:** Der Assistant-Notify-Pfad degradiert unter v0.1.0 ggf. still. Vor Archivierung (§3) oder Release muss die Pin-Konformität auf **jedem** Produktiv-Host hergestellt sein.

### B2 (Feststellung, kein Fehler): `_archive/` enthält nur Prä-Transfer-Altlasten
`system/hub/_archive/` (Stand 2026-09-01: `DEPRECATED_hub.py`, `_archive_handlers/`, `delegation_legacy/`) ist **nicht** Gegenstand von Stufe 8 — kein Bezug zu den 8 Modulrücktransfers.

---

## 3. Nullreferenznachweis (statisch, 2026-09-12)

Geprüft auf Referenzen gegen entfernte/gegabelte Altartefakte der 8 Transfers:

| Prüfung | Ergebnis |
|:--|:--|
| `hub/prosync.py` als Datei | ✅ **existiert nicht** — keine toten Imports. Alle `ProSync`-Strings in `db_sync.py`/`transit_sync_provider.py`/`bach_paths.py`/`setup.py`/`path.py` bezeichnen das **aktive Legacy-Verfahren** (bewusster Fail-Closed-Fallback, Plan-Regel 4.1), keinen Altcode. |
| Volatile ProSync-EinzelSkripte (tools/, scripts/) | ✅ keine vorhanden; verbliebene `*sync*`-Dateien sind andere aktive Komponenten (memory/gui/mail/maintenance). |
| Geforkte Alt-Test-Runner (`tools/testing/`) | ✅ keine vorhanden; `hub/test.py` routet sauber (extern ↔ `--native`). |
| `hub/daemon.py` (DEPRECATED-markiert) | ✅ **kein Archivierungskandidat**: dünner Re-Export-Wrapper auf `hub.scheduler`, Header dokumentiert ausdrücklich „bleibt dauerhaft für Rueckwaertskompatibilitaet erhalten". Wird von `tests/test_daemon.py` abgesichert. |
| Bare-Command-Legacy-Jobs (`translation_qa_*`, `db_backup`, `log_rotation`) | ✅ Datenbestand in der Scheduler-DB, kein Code-Altschrott; argv-Konvertierung ist deklarierte Host-Aufgabe vor `--apply` (Stufe 3). |

**Fazit:** Es gibt **keinen toten Modul-Altcode**, der heute archiviert werden könnte, ohne aktive Pfade zu treffen.

## 4. Warum die Archivierung (Stufe-8-Teil 3) jetzt kontraindiziert ist

1. **Plan §1, Grundsatz 3 (Haltefrist):** „Altteile werden niemals blind gelöscht, sondern **nach einer Haltefrist** in `system/hub/_archive/` strukturiert archiviert." — Alle Stufen wurden **am selben Tag** (2026-09-12) abgeschlossen; jede Haltefrist > 0 ist per Definition noch nicht abgelaufen.
2. **Plan §4, Regel 1 (Reversibilität):** Die internen Pfade (ProSync-Merge in `db_sync.py`, nativer Scheduler-Store, `--native`-Testlauf, `system_audit.py`, Injektor `_get_bach_context`) **sind** die Rollback-Ziele der sechs Env-Schalter. Sie ins Archiv zu verschieben würde dieRollback-Fähigkeit zerstören — direkter Regelverstoß.
3. **Plan §4, Regel 3 (Plattformparität):** Windows-Gegenproben (WORKSTATION-LG) für Stufen 2, 3, 5, 7 und der echte 3-Host-OneDrive-Lauf (Stufe 7, „Offener Betriebs-Nachlauf") sind noch offen. Vor hergestellter Parität keine Ablösung (Grundsatz 2: „Gatung vor Ablösung").
4. **Befund B1:** Modul 4 ist auf diesem Host nicht pin-konform — Single-Source-of-Truth ist damit aktuell **nicht** herstellbar.

**Konsequenz:** Stufe 8 wird als *Abschlussprüfung mit Feststellungen* geschlossen; die Archivierung wandert in den Folgetask **TRANSFER-09** mit harten Gates (Pin-Konformität aller Hosts, Windows-Gegenproben, Multi-Host-Lauf, Haltefrist).

## 5. Verbleibende Gates für TRANSFER-09 (Fork-Archivierung)

- [ ] assistant-core auf allen Hosts pin-konform (`444a1fff…`); `test_notify_via_assistant_core.py` grün
- [ ] Windows-Gegenprobe WORKSTATION-LG: Stufen 2, 3, 5, 7 (Plan-Regel 4.3)
- [ ] Echter 3-Host-Lauf sqlite-transit-sync über OneDrive-Transit (Stufe-7-Nachlauf)
- [ ] Scheduler-Legacy-Jobs argv-konvertiert + `--apply`-Praemigration verifiziert (Stufe-3-Nachlauf)
- [ ] Haltefrist abgelaufen (Vorschlag: ≥ 30 Tage nach letzter Stufe, d. h. frühestens **2026-10-12**; Dauer ist Operator-Entscheidung)
- [ ] Erst dann: Verschiebung *reiner* Altartefakte (nicht der Rollback-Pfade!) nach `system/hub/_archive/` + AST-Wächter-Anpassung + Volltest beider Plattformen
