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

## Selbstauskunft

**Modell:** Gemini 3.8 Flash (High)
