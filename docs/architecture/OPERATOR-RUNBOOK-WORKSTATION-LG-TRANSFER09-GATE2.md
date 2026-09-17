# TRANSFER-09 Gate 2 — OPERATOR-RUNBOOK Windows-Gegenprobe WORKSTATION-LG

> Dokument-ID: `OPERATOR-RUNBOOK-WORKSTATION-LG-TRANSFER09-GATE2`
> Host: `WORKSTATION-LG` (Windows) · Operator: Lukas Geiger
> Referenz: `TRANSFER-09-GATECHECK-2026-09-12.md` Gate 2, `MODULRUECKTRANSFER-ZERTIFIKAT-2026-09-12 §1`, Plan-Regel 4.3
> Erzeugt: 2026-09-12 auf `mac-studio` (Task #1243, BACH qwen3.8:27b-mlx)
> Status: **BEREIT FÜR OPERATOR — lokal (MacStudio) nicht ausführbar**

---

## Warum lokal NICHT ausführbar (Beweis 2026-09-12, mac-studio)
- BACH erreicht **nur** den Host `mac-studio`. `WORKSTATION-LG` & `ASUS-GEI` = separate Hosts.
- SSH: `~/.ssh/config` inkludiert nur `/Users/lukas/.colima/ssh_config` (lokale Lima-VM `colima`); kein Eintrag für `WORKSTATION-LG`.
- `known_hosts` ohne Eintrag für `WORKSTATION-LG`; Suche nach `workstation/lg/windows/remote/connector` im BACH-Index: **0 Treffer**.
- Keine Connector-/Sync-Pipe zu `WORKSTATION-LG`. → **kein Zugriff von BACH aus.**
- Delegation an Claude/Codex bringt keine Host-Erreichbarkeit (gleiche Umgebung) → bringt hier nichts.
- Analogie: Gate 1 (#1242/#1248) wurde ebenfalls als Operator-Handoff gelöst.

---

## Was lokal GELEISTET ist (Ersatznachweis, macOS)
Die 4 Zielgruppen sind auf `mac-studio` **grün** und **plattformagnostisch**
(keine `sys.platform`/`os.name`/`winreg`/`WinError`/Windows-Separator; `transit_sync_provider`
nutzt laut Docstring §5 bereits eine lokale 3-Wege-Simulation `WORKSTATION-LG/ASUS-GEI/mac-studio`
als Ersatznachweis). Dies ist die **notwendige Voraussetzung** für Parität — nicht der Ersatz für die
eigentliche Windows-Gegenprobe.

| Testmodul | Stufe | macOS-Ergebnis |
|:--|:--:|:--:|
| `test_scheduler_provider.py` | 2/3 | 2 ✅ |
| `test_scheduler_provider_wiring.py` | 2/3 | 28 ✅ |
| `test_accounts_via_accounts_core.py` | 3 | 23 ✅ |
| `test_explorer_provider_wiring.py` | 5 | 31 ✅ |
| `test_transit_sync_provider_wiring.py` | 7 | 26 ✅ |
| **Summe** | | **110 Tests grün in ~2.6 s** |

Repo-Basis (grüner Paritäts-Pin): `git rev-parse --short HEAD` = **aktueller main-HEAD `60d9888`** (branch `main`), venv `/Users/lukas/.venvs/bach`
(editable Installs aus `~/services/*`), `ellmos_scheduler`/`accounts_core`/`sqlite_transit_sync`/
`system_explorer` importierbar.
> ⚠️ REGRESSION 2026-09-12 ~14:2X (Task #1253): Der Repo-HEAD ist auf `c59b0da` vorgerückt; dort
> ist die Parität **ROT** (`109 passed, 1 failed, 1 error` — `test_accounts_via_accounts_core`
> `test_create_list_update_delete_roundtrip` liefert `success: False`, Regression in
> **Stand 2026-09-13 11:29 (Gate-Check Re-Verifizierung (5)):** Regression #1280 GEFIXT (Commit
> `b529218`), aktueller main-HEAD `60d9888` = 110 passed (stabil). Der Operator kann den
> **aktuellen main-HEAD** verwenden (pin-konform abgleichen), NICHT `git checkout 5e64e07` mehr.
> Die EIGENTLICHE Windows-Gegenprobe auf `WORKSTATION-LG` bleibt Operator-Evidenz.
> **Drift-robuster Hinweis (Re-Run mac-studio, BACH qwen3.8:27b-mlx):** Der Paritätsnachweis
> (110 passed, ~2.6–3.7 s) gilt NICHT nur für `60d9888`, sondern fortlaufend für den
> **aktuellen main-HEAD** — die Commits seit `60d9888` sind **docs-only** (keine Code-/Teständerung),
> daher bleibt die 5-Datei-Parität grün. Der Operator führt die Gegenprobe am **jeweiligen aktuellen
> main-HEAD** aus und trägt genau diesen `git rev-parse --short HEAD`-Wert in die Evidenz ein
> (kein festes Checkout, kein `5e64e07`/`60d9888`-Pin nötig). Erwartung: **110 passed**.

> **Frisch-Re-Verifizierung 2026-09-17 21:5X (BACH qwen3.8:27b-mlx, mac-studio):** Seit Refresh 10
> (#1251, `ace2568`, 2026-09-15) ist Code-Drift eingetreten (`ace2568` → `8825f73`, v.a. docs-only:
> Translations/Help/Telemetrie), daher war ein Refresh gerechtfertigt. Live-Lauf der 5-Datei-Parität
> am **aktuellen main-HEAD `8825f73`** (venv `/Users/lukas/.venvs/bach`): **110 passed, 1 warning**
> in ~10,8 s. Der frühere „1 error" ist bestätigt transientes `~/.bach`-SHM-Artefakt (conftest-Teardown,
> fremde BACH-Dienste PID 30288/31904/32354/41063/92080) — **nicht** Paritätsfall, jetzt nur Warning.
> => macOS-Ersatznachweis bleibt grün und drift-robust. Die **EIGENTLICHE Windows-Gegenprobe auf
> `WORKSTATION-LG` ist unverändert offen** (Host nicht lokal erreichbar, Delegation bringt nichts —
> gleiche Umgebung). **KEIN Green-Flip, KEINE Fälschung** — ZERTIFIKAT §1 Spalte „Windows-Gegenprobe"
> und Gate-Matrix Zeile 2 bleiben `⬜/❌`, bis der Operator den Live-Lauf liefert.

---

## Operator-Schritte auf WORKSTATION-LG (Windows PowerShell)

> Ziel: dieselbe Suite auf dem echten Windows-Host grün laufen lassen (Paritätsnachweis, Plan 4.3).

### 0) Voraussetzungen
- Python 3.12 aktiv, `bach`-Repo an `~/services/bach` (bzw. `%USERPROFILE%\services\bach`).
- Dependency-Repos vorhanden: `~/services/{ellmos-scheduler, accounts-core, system-explorer, sqlite-transit-sync, ...}`.

### 1) venv + editable Installs (falls noch nicht vorhanden)
```powershell
python -m venv .venvs\bach
.\.venvs\bach\Scripts\python.exe -m pip install -r requirements.txt
# pro Provider-Repo (falls lokal geklont):
.\.venvs\bach\Scripts\python.exe -m pip install -e ..\ellmos-scheduler
.\.venvs\bach\Scripts\python.exe -m pip install -e ..\accounts-core
.\.venvs\bach\Scripts\python.exe -m pip install -e ..\system-explorer
.\.venvs\bach\Scripts\python.exe -m pip install -e ..\sqlite-transit-sync
```

### 2) Die 4 Zielgruppen grün (Stufen 2/3/5/7)
```powershell
cd services\bach
.\.venvs\bach\Scripts\python.exe -m pytest `
  system\tests\test_scheduler_provider.py `
  system\tests\test_scheduler_provider_wiring.py `
  system\tests\test_accounts_via_accounts_core.py `
  system\tests\test_explorer_provider_wiring.py `
  system\tests\test_transit_sync_provider_wiring.py `
  -q
```
Erwartet: **110 passed** (2 + 28 + 23 + 31 + 26).

### 3) (Optional, volle 176er-Suite, falls gewünscht)
```powershell
.\.venvs\bach\Scripts\python.exe -m pytest system\tests -q
```

### 4) Evidenz zurückschreiben (Parität nachweisen)
Screencapture bzw. `pytest -q`-Ausgabe (110 passed) + `git rev-parse --short HEAD`
als Nachweis in den Gate-Check einfügen → Gate-Matrix-Zeile `WORKSTATION-LG` für die 4 Stufen
von `offen` → `✅ grün` setzen (ZERTIFIKAT §1, Spalte „Windows-Gegenprobe").

---

## Abschlusskriterien (Gate 2)
- Auf `WORKSTATION-LG`: `test_scheduler_provider{,_wiring}.py` + `test_accounts_via_accounts_core.py`
  + `test_explorer_provider_wiring.py` + `test_transit_sync_provider_wiring.py` → **110 passed**.
- Evidenz (pytest-Ausgabe + HEAD) im Gate-Check hinterlegt, Matrix-Zeilen auf `✅`.
- Erst dann: Gate 2 = MET → `task done` für den Windows-Anteil von #1243.
- **Solange offen** bleibt: „Erst bei Parität gilt ‚Gatung vor Abloesung'." —
  #1243 darf **nicht** vor dem echten Windows-Lauf geschlossen werden.

---
## Hinweis
Diese Aufgabe ist für den Operator freigegeben. BACH (qwen3.8) liefert den macOS-Ersatznachweis
und dieses Runbook; die eigentliche Windows-Gegenprobe muss auf `WORKSTATION-LG` vom Operator
durchgeführt werden. #1243 verbleibt OPEN, bis der Windows-Lauf grün ist.
