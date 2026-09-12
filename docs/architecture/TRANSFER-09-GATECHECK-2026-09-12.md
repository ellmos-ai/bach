# TRANSFER-09 — Fork-Archivierung: Gate-Check 2026-09-12

> Dokument-ID: `TRANSFER-09-GATECHECK-2026-09-12`
> Host: `mac-studio` · Operator: Lukas Geiger
> Referenz: `MODULRUECKTRANSFER-ZERTIFIKAT-2026-09-12.md §5`, Plan-Regeln 4.1/4.3
> Ergebnis: **ALLE 5 GATES UNMET — Archivierung KONTRAINDIZIERT, kein Artefakt verschieben.**

## Gate-Matrix (Live-Prüfung 2026-09-12)

| # | Gate | Zustand | Evidenz |
|:--|:--|:--:|:--|
| 1 | assistant-core auf allen Hosts pin-konform (`444a1fff`), `test_notify_via_assistant_core.py` grün | ❌ UNMET | `git -C ~/services/assistant-core rev-parse HEAD` → `ccadcf9` (v0.1.0); requirements.txt pinnt `444a1fffd56236078988d088f6237f706c3e15a9` (v0.2.0). `pytest test_notify_via_assistant_core.py` → `ImportError: cannot import name 'NotificationService'` (Collection-Error, Befund B1). Pin-Commit lokal nicht vorhanden; `git fetch` in Nicht-Interaktiv-Shell scheitert (privates Repo, Operator-Aufgabe). |
| 2 | Windows-Gegenprobe `WORKSTATION-LG` Stufen 2/3/5/7 (Plan 4.3) | ❌ UNMET | Zertifikat-Matrix: alle ⬜ offen. |
| 3 | Echter 3-Host-Lauf `sqlite-transit-sync` über OneDrive-Transit | ❌ UNMET | Zertifikat §5: „Offener Betriebs-Nachlauf". |
| 4 | Scheduler-Legacy-Jobs argv-konvertiert + `--apply`-Prämigration verifiziert | ❌ UNMET | Zertifikat §5: deklarierte Host-Aufgabe vor `--apply`. |
| 5 | Haltefrist abgelaufen (Vorschlag ≥ 2026-10-12, Dauer = Operator-Entscheidung) | ❌ UNMET | Heute 2026-09-12 = Tag der letzten Stufenschließung; Haltefrist startet erst am 2026-10-12. |

## Schutzregel 4.1 (Reversibilität) — aktiv, NICHT archivable
Folgende Pfade sind die **Rollback-Ziele** der Env-Schalter und dürfen solange die Schalter existieren **NICHT** archiviert werden (Live-Prüfung):
- Env-Schalter vorhanden in 11 hub-Dateien: `db_sync.py`, `workflow_hook_provider.py`, `transit_sync_provider.py`, `__init__.py`, `upgrade.py`, `setup.py`, `_services/chat/chat_runtime.py`, `memory_hook_provider.py`, `scheduler.py`, `explorer_provider.py`, `scheduler_provider.py`.
- Legacy-Rollback-Pfade vorhanden: `db_sync.py` (ProSync-Merge, Fail-Closed-Fallback), `scheduler_provider.py`/`scheduler.py` (nativer Scheduler-Store), `system_audit.py` (nativer Audit), `_get_bach_context` in `_services/chat/chat_runtime.py` + `memory_hook_provider.py`, `--native`-Testlauf in `hub/test.py`.
- Zertifikat §3: „Es gibt keinen toten Modul-Altcode, der heute archiviert werden könnte, ohne aktive Pfade zu treffen."

## Entscheidung
Archivierung nach `system/hub/_archive/` wird **nicht ausgeführt**. Task #1235 bleibt blockiert bis alle 5 Gates grün sind.
- Gates 1–4: Operator-/Host-Aufgaben (siehe angelegte Folgetasks).
- Gate 5: Haltefrist-Countdown auf 2026-10-12 gesetzt (Operator kann Dauer verkürzen/verlängern).

## Erst dann (wenn alle Gates grün)
Verschieben **nur reiner Altartefakte** nach `system/hub/_archive/` (nicht der Rollback-Pfade!),
AST-Wächter-Anpassung + Volltest beider Plattformen (mac-studio + WORKSTATION-LG).
Aktuell in `_archive/`: `DEPRECATED_hub.py`, `_archive_handlers/`, `delegation_legacy/` (Prä-Transfer-Altla, unverändert).

---
## Re-Verifizierung Gate 1 (Task #1242) — 2026-09-12 11:13 — BACH qwen3.8:27b-mlx
Automatischer Live-Check vor dem Operator-Handoff. Ergebnis: **weiterhin UNMET**, Blocker unverändert.

- HEAD /Users/lukas/services/assistant-core = `ccadcf9` (v0.1.0) — pin-konform wäre `444a1ff` (v0.2.0).
- Pin bestätigt: requirements.txt:62 → `...@444a1fffd56236078988d088f6237f706c3e15a9`.
- Commit `444a1ff` in den lokalen Klonen (assistant-core, accounts-core, ellmos-scheduler, ellmos-tests): **nicht vorhanden**.
- Kein pip-Wheel/Tarball, kein Bundle lokal. Kein nicht-interaktives Credential:
  - credential.helper=osxkeychain, aber kein github.com-Eintrag im Keychain
  - SSH-Key ``~/.ssh/id_ed25519`` bei GitHub nicht registriert
  - kein ``~/.netrc`\', kein ``gh`\'/Token
- pytest ``system/tests/test_notify_via_assistant_core.py`` → ImportError: cannot import name 'NotificationService' (Collection-Error, Befund B1) — reproduziert, unverändert.

**Blocker**: privates Repo, Credentials nur interaktiv (Runbook OPERATOR-RUNBOOK-ASSISTANT-CORE-444a1fff.md, Option A=SSH-Key/Option B=PAT). Kein automatisierter Abschluss möglich. Keine Fälschung der NotificationService (würde den Commit-Pin 444a1ff und damit das Gate brechen).
**Hosts**: MacStudio (dieser, geprüft), WORKSTATION-LG, ASUS-GEI (remote — lokal nicht erreichbar, Operator-Aufgabe).
**Status Task #1242**: open (blocked on operator credential step).

---
## Re-Verifizierung Gate 2 (Task #1243) — 2026-09-12 11:55 — BACH qwen3.8:27b-mlx
Windows-Gegenprobe `WORKSTATION-LG` Stufen 2/3/5/7. Ergebnis: **weiterhin UNMET (Operator-Host), aber macOS-Ersatznachweis grün.**

- **macOS-Baseline (mac-studio, `HEAD=809ccdc`, venv `.venvs/bach`, 4 Provider-Module importierbar):**
   | Testmodul | Stufe | macOS |
   |:--|:--:|:--:|
   | `test_scheduler_provider.py` | 2/3 | 2 ✅ |
   | `test_scheduler_provider_wiring.py` | 2/3 | 28 ✅ |
   | `test_accounts_via_accounts_core.py` | 3 | 23 ✅ |
   | `test_explorer_provider_wiring.py` | 5 | 31 ✅ |
   | `test_transit_sync_provider_wiring.py` | 7 | 26 ✅ |
   | **Summe** | | **110 passed in ~2.6 s** |
- **Plattformagnostik:** die 4 Gruppen enthalten keine Windows-spezifischen Abzweigungen
   (kein `sys.platform`/`os.name`/`winreg`/`WinError`/Windows-Separator); `transit_sync_provider`
   nutzt laut Docstring §5 bereits eine lokale 3-Wege-Simulation `WORKSTATION-LG/ASUS-GEI/mac-studio`
   als Ersatznachweis. → Der macOS-Grünlauf ist die **notwendige Voraussetzung** für Parität.
- **Blocker (wie Gate 1):** BACH erreicht `WORKSTATION-LG` nicht — `~/.ssh/config` enthält nur `colima`
   (Lima), kein `WORKSTATION-LG`-Eintrag in `known_hosts`, BACH-Index-Suche `workstation/lg/windows/remote/connector`
   = 0 Treffer, keine Connector-Pipe. Delegation an Claude/Codex bringt keine Host-Erreichbarkeit.
   → **Eigentliche Windows-Gegenprobe = Operator-Aufgabe.**
- **Runbook erstellt:** `OPERATOR-RUNBOOK-WORKSTATION-LG-TRANSFER09-GATE2.md`
   (venv/Installs + pytest-Aufruf der 4 Gruppen auf Windows PowerShell, Erwartung **110 passed**,
   Evidenz-Rückschreib-Anleitung + Matrix-Zeilenumsetzung `offen`→`✅`).
- **Status Task #1243:** open — verbleibt OPEN bis der echte `WORKSTATION-LG`-Lauf grün ist.
   „Erst bei Parität gilt ‚Gatung vor Abloesung'": #1243 darf **nicht** vor dem Windows-Lauf geschlossen werden.
   Keine Fälschung (kein `sys.platform`-Short-Circuit / kein simulierter Windows-Pass) — würde die Gate-Integrität brechen.

---
## Re-Verifizierung Gate 2 (2) — 2026-09-12 12:2X — BACH qwen3.8:27b-mlx (Task #1250)
Erneuter lokaler Live-Check auf `mac-studio`, **HEAD `f8554ca`** (branch `main`, seit Runbook neu).
Ergebnis: **Paritätsvoraussetzung grün, echter Windows-Host-Run weiterhin UNMET.**

- macOS-Ersatznachweis (5 Dateien, Stufen 2/3/5/7): **110 passed in 2.57s**
  (`test_scheduler_provider.py` 2, `…_wiring.py` 28, `test_accounts_via_accounts_core.py` 23,
   `test_explorer_provider_wiring.py` 31, `test_transit_sync_provider_wiring.py` 26 = 110).
- Erreichbarkeit `WORKSTATION-LG` erneut verifiziert: nicht vorhanden
  (`~/.ssh/config` = nur `colima`; `known_hosts` = 4 Einträge, kein `WORKSTATION-LG`;
   BACH-Index `workstation/WORKSTATION-LG` = 0 Treffer; Host = `mac-studio`).
- **Gate-Matrix-Zeile 2 `Windows-Gegenprobe` = ⬜ offen → bleibt ⬜ (kein fälschliches ✅).**
  Kein `sys.platform`-Short-Circuit, kein simulierter Windows-Pass (Gate-Integrität).
- **Operator-Handoff (kopierfertig, auf `WORKSTATION-LG` PowerShell):**
  ```powershell
  cd %USERPROFILE%\services\bach
  .\.venvs\bach\Scripts\python.exe -m pytest `
    system\tests\test_scheduler_provider.py `
    system\tests\test_scheduler_provider_wiring.py `
    system\tests\test_accounts_via_accounts_core.py `
    system\tests\test_explorer_provider_wiring.py `
    system\tests\test_transit_sync_provider_wiring.py -q
  git rev-parse --short HEAD
  ```
- **Evidenz-Vorlage (Operator füllt aus → in Matrix Zeile 2 + ZERTIFIKAT §1 eintragen):**
  - `WORKSTATION-LG` HEAD: `______` (muss `f8554ca` bzw. pin-konform sein)
  - pytest-Ergebnis: `______ passed` (Erwartung **110 passed**)
  - Zeitstempel Windows-Lauf: `______`
  - Matrix-Zeile 2 + ZERTIFIKAT §1 Spalte „Windows-Gegenprobe": `⬜ offen` → `✅ grün`
  - Danach: Task #1243 darf geschlossen werden.

### Re-Verifizierung Gate 2 (3) — 2026-09-12 ~13:00 — BACH qwen3.8:27b-mlx (Task #1253)
HEAD vorgerückt auf `5e64e07` (branch `main`). Paritätsvoraussetzung **lebensbestätigt**:
  venv `/Users/lukas/.venvs/bach` (python3.12), 5 Dateien Stufen 2/3/5/7 → **110 passed in 2.59 s**.
Handoff-Artefakte (Runbook + Abschnitt „(2)") kopierfertig und konsistent bestätigt.
Gate-Matrix-Zeile 2 `Windows-Gegenprobe` = ⬜ offen → bleibt ⬜ (kein fälschliches ✅, kein Windows-Pass simuliert).
**BLOCKED auf Operator:** echter Windows-Lauf auf `WORKSTATION-LG` ist von BACH/mac-studio nicht ausführbar
(keine Erreichbarkeit, Delegation bringt nichts — gleiche Umgebung). #1243 verbleibt OPEN bis grüner Windows-Lauf.

---
## Re-Verifizierung Gate 2 (3) — Matrix-Endkontrolle Task #1251 — 2026-09-12 13:3X — BACH qwen3.8:27b-mlx
Aufgabe #1251 „nach B": ZERTIFIKAT §1 Spalte „Windows-Gegenprobe" (Stufen 2/3/5/7) auf grün,
Gate 2 auf MET, dann #1243 schließbar. **Regel: „Erst bei Parität gilt Gätung vor Ablösung".**
Ergebnis der Endkontrolle: **Prämisse NICHT erfüllt → KEIN Green-Flip, KEIN Gate-MET, #1243 bleibt OPEN.**

- **Prämissenprüfung (nicht erfüllt):**
    - Echte `WORKSTATION-LG`-Evidenz **nicht vorliegen**: Evidenz-Vorlage in Task #1253/#1250
      unbesetzt (`WORKSTATION-LG HEAD: ______`, `pytest: ______ passed`, Zeitstempel leer).
    - `WORKSTATION-LG` erneut nicht erreichbar: `~/.ssh/config` = nur `colima`;
      `known_hosts` ohne `WORKSTATION-LG`-Eintrag; keine Connector-/Sync-Pipe (Host = `mac-studio`).
    - Zertifikat-Matrix `MODULRUECKTRANSFER-ZERTIFIKAT-2026-09-12 §1` Spalte „Windows-Gegenprobe"
      Stufen 2/3/5/7 = **⬜/❌ offen** (unverändert).
    - Gate-Matrix Zeile 2 `Windows-Gegenprobe` = **❌ UNMET** (unverändert).
- **macOS-Paritätsvoraussetzung (nötig, nicht hinreichend):** 110 passed (2+28+23+31+26)
  bestätigt; plattformagnostisch. Dies ist die *Voraussetzung*, nicht der Ersatz für den Windows-Lauf.
- **Entscheidung:** Gate 2 **bleibt UNMET**. Zertifikat-Spalte **bleibt ⬜**. #1243 **bleibt OPEN**
  („Erst bei Parität gilt Gätung vor Ablösung"). **Keine Fälschung** — kein simulierter Windows-Pass,
  kein vorzeitiger Green-Flip. Fälschung würde den Gate-Pin/Integrität brechen (wie bei Gate 1).
- **Nächster Schritt (Operator auf WORKSTATION-LG, vgl. #1250/#1253):** PowerShell-Lauf der 5 Dateien
  (Erwartung 110 passed) + `git rev-parse --short HEAD` → Evidenz in Vorlage eintragen →
  ZERTIFIKAT §1 `Windows-Gegenprobe` ⬜→✅ (Stufen 2/3/5/7) → Gate-Matrix Zeile 2 UNMET→MET →
  dann #1243 (und erst danach #1235) schließbar.
- **Status Task #1251:** open (Prämisse nicht erfüllt, Endkontrolle durchgeführt — Gate korrekt OFFEN).
