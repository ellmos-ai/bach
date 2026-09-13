# Abschlussbericht — Atomarer Task-Claim gegen Doppelausführung (T-20260913-709822598)

## Zusammenfassung

Zur Behebung der Doppelausführung von Hintergrund-Tasks durch konkurrierende Prozesse (`worker.py` und `chat_tray.py`) wurde eine atomare, datenbanknative Claim-Mechanik für die `tasks`-Tabelle implementiert. Statt eines ungeschützten Read-Then-Write (TOCTOU) beansprucht nun ein bedingtes SQL-`UPDATE ... WHERE ...` mit `rowcount`-Prüfung den Task exklusiv für den gewinnenden Prozess.

## Geänderte und neue Dateien

1. **`system/hub/_services/task_schema.py`**
   - Ergänzt um `task_has_claim_columns(conn)` und `ensure_task_claim_columns(conn)`.
   - Fügt additiv und selbstheilend `claimed_by TEXT` und `claimed_at TEXT` sowie den Index `idx_tasks_claimed_at` zur `tasks`-Tabelle hinzu.

2. **`system/data/schema/migrations/040_task_claim.py`** (neu)
   - Formale additive Migrationsdatei nach dem Vorbild von `038_task_due_date.py`, ruft `ensure_task_claim_columns(conn)` auf.

3. **`system/hub/task_audit.py`**
   - Ergänzt um `claim_task_atomic(conn, task_id, claimed_by, *, now=None, lease_seconds=1800) -> bool`:
     Führt ein atomares bedingtes `UPDATE` aus, das nur Tasks erfasst, die nicht terminal/blockiert sind (`status NOT IN ('done', 'completed', 'cancelled', 'blocked')`) und entweder noch nicht `in_progress` sind oder deren Claim/Lease abgelaufen ist (`claimed_at < lease_cutoff`). Setzt bei Erfolg einmalig `started_at` und schreibt den Audit-Eintrag in `task_history`.
   - Ergänzt um `release_claim(conn, task_id) -> bool`:
     Gibt einen Claim vorzeitig frei (setzt Status von `in_progress` zurück auf `open`, leert `claimed_by` und `claimed_at`, dokumentiert den Rückfall in `task_history`).
   - `CLEARABLE_COLUMNS` um `claimed_by` und `claimed_at` erweitert.

4. **`system/hub/task.py`**
   - CLI-Handler um Operationen `claim` und `release` erweitert (`_claim` und `_release`).
   - `bach task claim <id> --by <name> [--lease SECONDS]`: beansprucht Task atomar, gibt bei Erfolg `[OK]`, bei Wettlaufverlust `[CONFLICT]` (Exit Code 1) zurück.
   - `bach task release <id>`: gibt Claim frei.
   - Hilfe und Operationsverzeichnis (`get_operations`, `_help`) entsprechend aktualisiert.

5. **`system/hub/_services/chat/worker.py`**
   - Prüft Kandidaten aus `offene_tasks` vor der Arbeitsaufnahme via Subprozess `bach task claim <id> --by worker:<category>`.
   - Falls ein Kandidat bereits beansprucht ist (`returncode != 0`), wird geloggt und der nächste Kandidat geprüft.
   - Bei Abbruch (`KeyboardInterrupt`), Ausnahme oder Nichterledigung wird `bach task release <id>` aufgerufen.

6. **`system/gui/server.py`**
   - In `PUT /api/tasks/{task_id}` (`update_task`):
     Erkennt Neu-Beanspruchungen nach `in_progress` bzw. Claim-Versuche fremder Taktgeber und delegiert diese an `claim_task_atomic(conn, task_id, changed_by)`.
     Bei Claim-Konflikt liefert der Endpunkt `{"status": "claim_failed", "success": false}` mit **HTTP 200** zurück (damit Clients wie `chat_tray.py` dies sauber von Netzwerkfehlern unterscheiden können). Eigene Aktualisierungen laufender Tasks durch denselben Owner bleiben erhalten.

7. **`system/hub/_services/chat/chat_tray.py`**
   - In `_process_idle_task()`: wertet die Antwort des `PUT /api/tasks/{task_id}`-Aufrufs aus. Bei `claim_failed` oder Netzwerkfehler (`None`) bricht der Tray die Bearbeitung sofort ab, bevor der Prompt gebaut oder Inferenz gestartet wird.

8. **`system/tests/test_task_atomic_claim.py`** (neu)
   - Umfassende Regressionstest-Suite mit 12 Tests für Core-Atomarität, Multithreading-Konkurrenz, Lease-Timeout, Terminal-/Blocked-Ausschluss, Release-Rückfall, CLI-Handler und FastAPI TestClient `PUT /api/tasks/{id}`.

## Verhältnis zu Trithon-Salt

Diese Lösung ist eine **einzelhost-lokale, DB-native Atomarität** (SQLite `UPDATE ... WHERE ...` mit `rowcount`-Prüfung, ein einziger Datenbankprozess auf einem Rechner). Der Trithon-Salt-Architekturentwurf (`.SYNC/ARCHITEKTURENTWURF_OCEAN_LEAD_HOST_TRITHON.md`, NICHT abgenommen) adressiert eine ANDERE Schicht: Wettläufe ZWISCHEN mehreren Hosts über cloud-synchronisierte Dateien mit Latenz. Die hier gewählten Feldnamen (`claimed_by` als freier Text, `claimed_at` als ISO-Zeitstempel) sind bewusst generisch gehalten und schließen eine spätere Erweiterung um eine Salt-Validierung (z. B. `claimed_by` könnte später `"<host>:<salt>"` tragen) nicht aus, nehmen sie aber auch nicht vorweg.

## Testergebnisse

1. **Gezielte neue Regressionstest-Suite:**
   ```powershell
   pytest system/tests/test_task_atomic_claim.py -q
   ```
   **Ergebnis:** `12 passed, 1 warning in 4.20s` (100% Erfolgsquote)

2. **GUI Server Smoke-Suite (Regression):**
   ```powershell
   pytest system/tests/test_gui_server_smoke.py -q
   ```
   **Ergebnis:** `42 passed, 1 warning in 10.61s` (100% Erfolgsquote, keine Regressionen)

## `git diff --stat`

```text
 system/gui/server.py                   |  33 ++++++++--
 system/hub/_services/chat/chat_tray.py |   9 ++-
 system/hub/_services/chat/worker.py    |  46 +++++++++++++-
 system/hub/_services/task_schema.py    |  29 +++++++++
 system/hub/task.py                     |  78 ++++++++++++++++++++++-
 system/hub/task_audit.py               | 113 ++++++++++++++++++++++++++++++++-
 6 files changed, 293 insertions(+), 15 deletions(-)
```

## Nachbesserung — Behebung der vier Codex-Review-Befunde

Im Review (`_codex/REVIEW-claim.md`) wurden vier Sicherheits- und Nebenläufigkeitsbefunde identifiziert. Alle vier wurden behoben und durch neue bzw. erweiterte Tests abgesichert:

### Befund 1 & 3: Zeitstempel-Format, Mikrosekunden-Inkonsistenz und Claim-Race
- **Ursache:** `datetime.now().isoformat()` serialisiert in Python ohne Mikrosekunden, wenn `microsecond == 0` ist (`2026-09-13T20:50:00`), aber mit Mikrosekunden, wenn `microsecond != 0` (`2026-09-13T20:50:00.123456`). Im lexikografischen SQLite-String-Vergleich (`claimed_at < lease_cutoff`) führt die fehlende Mikrosekunden-Komponente zu Fehlvergleichen (`'...:00'` wird anders sortiert als `'...:00.123456'`), wodurch frische Claims fälschlich als abgelaufen gelten konnten oder abgelaufene Claims blockiert wurden. Zudem führte die Mischung aus naiven und zeitzonenbehafteten Datetimes zu fehlerhaften String-Vergleichen.
- **Reproduktion:** Zwei Zeitstempel zur exakt selben Sekunde, einer mit `microsecond == 0` und einer mit `microsecond > 0`, gegeneinander in SQLite verglichen; gezielter Testfall `test_claim_zero_microsecond_consistency_and_lease_cutoff` gebaut.
- **Behebung:** Zentrale Hilfsfunktion `_iso_now(dt=None)` in `system/hub/task_audit.py` eingeführt. Sie erzwingt strikt das 26-Zeichen-Format `%Y-%m-%dT%H:%M:%S.%f`, normalisiert eingehende Zeitstempel/Zeitzonen auf lokale naive Datetimes und wird überall einheitlich für `now`, `claimed_at` und `lease_cutoff` verwendet.

### Befund 2: Stale Release gegen neuen Owner
- **Ursache:** `release_claim()` prüfte bisher nur `WHERE status = 'in_progress'` ohne den `claimed_by`-Owner zu verifizieren. Lief der Lease von Worker A ab und übernahm Worker B legitim den Task, konnte ein verspäteter Aufruf von Worker A (z. B. im Fehlerpfad / `except`-Block) fälschlicherweise den aktiven Claim von Worker B auf `open` zurücksetzen.
- **Reproduktion:** Task mit `worker-B` als Claimer angelegt; Aufruf `release_claim(conn, task_id, "worker-A")` ausgeführt und verifiziert, dass der Release abgelehnt wird. Testfall `test_stale_release_rejected_for_wrong_owner` implementiert.
- **Behebung:**
  - `release_claim(conn, task_id, claimed_by: str) -> bool` besitzt nun `claimed_by` als Pflichtparameter; die WHERE-Klausel wurde um `AND claimed_by = ?` ergänzt.
  - CLI `bach task release <id> --by <name>` erfordert `--by` analog zu `bach task claim`.
  - `worker.py` übergibt bei allen drei Release-Aufrufen (`KeyboardInterrupt`, `Exception`, unfertiger Task) denselben Bezeichner `worker:{args.category}` via `--by`.

### Befund 4: Abweichender Worker-Datenbankpfad
- **Ursache:** `worker.py` ermittelte die Datenbank über `db = args.db or str(bach / 'data' / 'bach.db')`. Die kanonische Ermittlung in `server.py` und `task.py` läuft jedoch über `hub.bach_paths::BACH_DB` (welches standardmäßig `~/.bach/bach.db` priorisiert). Dadurch griffen `offene_tasks()` in `worker.py` und der Claim via `bach.py` auf unterschiedliche SQLite-Dateien zu.
- **Reproduktion:** Absoluter Pfadvergleich von `BACH_DB` (`C:\Users\User\.bach\bach.db`) gegenüber `bach / 'data' / 'bach.db'` (`...\system\data\bach.db`) belegte zwei verschiedene Dateien.
- **Behebung:** `worker.py` importiert nun `from hub.bach_paths import BACH_DB` und setzt `db = args.db or str(BACH_DB)`.

### Nachtest-Ergebnisse
- `pytest system/tests/test_task_atomic_claim.py -q --basetemp=.pytest-tmp2`: **14 passed, 1 warning**
- `pytest system/tests/test_gui_server_smoke.py -q --basetemp=.pytest-tmp2`: **42 passed, 1 warning**

## Selbstauskunft

**Modell:** Gemini 3.8 Flash (High)
