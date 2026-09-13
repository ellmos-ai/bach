# Auftrag — Atomarer Task-Claim gegen Doppelausführung (T-20260913-709822598, KRITISCH)

Du arbeitest im Worktree `C:/_Local_DEV/wt/bach-709822598-claim` (Branch
`fix/T-20260913-709822598-atomic-claim`, Basis `origin/main`, aktuell
`9dc363c`). Committe auf DIESEM Branch. **NICHT pushen.**

Dies ist ein **Sicherheits-/Integritätsfix** (Doppelausführung mit
Schreibrechten). Gründlichkeit vor Kürze. Die Konzeption unten ist bewusst
detailliert vorgegeben — weiche NICHT ohne triftigen, im Bericht genannten
Grund davon ab.

## Der Befund (bereits vermessen, nicht neu recherchieren)

Zwei Prozesse lesen unabhängig aus derselben `tasks`-Tabelle (`data/bach.db`)
die "erste offene Aufgabe" und beginnen daran zu arbeiten, OHNE sie vorher
exklusiv zu beanspruchen:

1. **`system/hub/_services/chat/task_runner.py::offene_tasks()`** (Zeile
   ~40-75): liest per **read-only** SQLite-Verbindung
   (`sqlite3.connect(f"file:{db}?mode=ro", uri=True)`) alle Tasks mit
   `status NOT IN ('done','cancelled','completed','in_progress','blocked')`.
   Aufgerufen von **`system/hub/_services/chat/worker.py::main()`**
   (Zeile ~163 `offen = offene_tasks(db, args.category)`) in einer
   Endlosschleife. Erst NACH getaner Arbeit ruft `worker.py` (über
   `markiere_erledigt()`, Zeile ~84) `python bach.py task done <id>` als
   Subprozess auf — zwischen Lesen und Fertig-Markieren gibt es KEINE
   Statusänderung, die den Task für andere Leser sperrt.

2. **`system/hub/_services/chat/chat_tray.py::_process_idle_task()`**
   (Zeile ~564-660): liest per **HTTP GET** `/api/tasks?status=pending`
   bzw. `?status=open` (über `self._api(...)`, Basis `self.gui_url`, also
   Port 8000). Wählt den ersten passenden Task, baut daraus einen Prompt
   und ruft ERST DANN (Zeile ~628)
   `self._api("PUT", f"/api/tasks/{task_id}", {"status": "in_progress", ...})`
   auf — **ohne den Rückgabewert zu prüfen**. Der Aufruf ist reines
   Fire-and-Forget.

3. **`system/gui/server.py::update_task()`** (Route `PUT /api/tasks/{task_id}`,
   Zeile ~1656): liest den bestehenden Task (`SELECT * FROM tasks WHERE
   id = ?`), baut daraus `existing_row`, und wendet dann UNBEDINGT
   `hub.task_audit.apply_task_field_changes(conn, task_id, existing_row,
   field_values, ...)` an — das ist ein klassisches Read-Then-Write
   (TOCTOU), keine bedingte Aktualisierung. Dieser Endpunkt wird laut
   eigenem Docstring sowohl von der GUI als auch vom Tray-Idle-Worker
   benutzt.

**Ergebnis:** Läuft `worker.py` (Standalone-Prozess, eigener OS-Prozess)
gleichzeitig mit dem Tray (`com.bach.chat-tray`, eigener OS-Prozess), können
beide denselben Task gleichzeitig mit vollen Schreibrechten bearbeiten.

**Geprüft und NICHT Teil dieses Bugs:** `system/hub/scheduler.py` liest die
`tasks`-Tabelle nirgends (nur `scheduler_jobs`, eine separate Tabelle, über
manuelle Einzelaufrufe `_run_job()`, keine automatische Polling-Konkurrenz).
Es gibt daher aktuell KEINEN dritten Taktgeber auf `tasks`. Wenn du beim
Umsetzen etwas findest, das dem widerspricht, halte inne und vermerke es im
Bericht statt es stillschweigend zu ignorieren oder zu "reparieren".

## Bereits vorhandene Bausteine, die du wiederverwendest (nicht neu bauen)

- **Migrations-Muster:** `system/hub/_services/task_schema.py` (Funktionen
  `task_has_due_date`/`ensure_task_due_date`) + zugehörige Datei
  `system/data/schema/migrations/038_task_due_date.py`. Additive
  `ALTER TABLE tasks ADD COLUMN ...` mit try/except auf
  `"duplicate column name"`, aufgerufen LAZY/selbstheilend direkt in
  `system/hub/task.py` vor jeder Nutzung (Zeilen ~262, 280, 303, 321 —
  `grep -n "ensure_task_due_date" system/hub/task.py`), zusätzlich EINE
  formale Migrationsdatei unter `system/data/schema/migrations/` (nächste
  freie Nummer ermitteln: `ls system/data/schema/migrations/ | sort | tail -5`
  — Stand jetzt ist die höchste Nummer 039, deine neue Datei heißt also
  `040_task_claim.py`, exakt nach dem Muster von `038_task_due_date.py`
  aufgebaut, inkl. `run_migration(conn=None)`-Funktion).
- **Audit-/Status-Logik:** `system/hub/task_audit.py`
  (`apply_task_field_changes`, `COMPLETED_STATUSES`, `IN_PROGRESS_STATUSES`,
  `ALLOWED_COLUMNS`). Deine neue Claim-Funktion lebt in DERSELBEN Datei,
  daneben, NICHT als Ersatz.
- **CLI-Handler-Muster:** `system/hub/task.py`, Methode `_done()` (Zeile
  ~620) als Vorbild für Aufbau/Fehlerbehandlung/Multi-ID-Parsing
  (`self._parse_ids(args)`).

## Umsetzung

### 1) Schema: zwei neue Spalten (additiv, selbstheilend)

In `system/hub/_services/task_schema.py`, analog zu
`task_has_due_date`/`ensure_task_due_date`:

```python
def task_has_claim_columns(conn: sqlite3.Connection) -> bool:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
    return "claimed_by" in cols and "claimed_at" in cols


def ensure_task_claim_columns(conn: sqlite3.Connection) -> None:
    table = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = 'tasks'"
    ).fetchone()
    if not table or table[0] != "table":
        raise RuntimeError("Task-Migration abgebrochen: tasks-Tabelle fehlt.")
    for col in ("claimed_by TEXT", "claimed_at TEXT"):
        name = col.split()[0]
        if not any(row[1] == name for row in conn.execute("PRAGMA table_info(tasks)")):
            try:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {col}")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_claimed_at ON tasks(claimed_at)"
    )
```

(Passe Stil/Fehlermeldungen an das Bestehende an, die obige Fassung ist ein
Gerüst, kein wörtlich zu kopierender Endstand.)

Neue Migrationsdatei `system/data/schema/migrations/040_task_claim.py`
1:1 nach dem Muster von `038_task_due_date.py`, ruft
`ensure_task_claim_columns` auf.

### 2) Atomarer Claim in `system/hub/task_audit.py`

Zwei neue Funktionen, neben `apply_task_field_changes`:

```python
def claim_task_atomic(
    conn: sqlite3.Connection,
    task_id: int,
    claimed_by: str,
    *,
    now: Optional[str] = None,
    lease_seconds: int = 1800,
) -> bool:
    """Beansprucht einen Task exklusiv. True nur, wenn DIESER Aufruf gewonnen hat.

    Bedingtes UPDATE mit rowcount-Pruefung -- das ist der eigentliche Fix:
    kein Read-Then-Write, sondern ein einziges atomares Statement, das nur
    dann etwas aendert, wenn der Task noch offen ODER sein Lease abgelaufen
    ist. `conn` muss eine SCHREIBENDE Verbindung sein (kein `mode=ro`).
    """
```

- `now` Default: `datetime.now().isoformat()` (wie im Rest der Datei).
- Lease-Grenze als ISO-String berechnen (`datetime.fromisoformat(now) -
  timedelta(seconds=lease_seconds)`, dann wieder `.isoformat()` — ISO-8601
  gleicher Länge ist lexikografisch vergleichbar, das nutzt dieser Code
  bereits an anderer Stelle implizit über String-Zeitstempel).
- SQL (sinngemäß, an die tatsächliche Spaltenreihenfolge/Quoting dieser
  Datei anpassen):
  ```sql
  UPDATE tasks
  SET status = 'in_progress', claimed_by = ?, claimed_at = ?
  WHERE id = ?
    AND status NOT IN ('done', 'completed', 'cancelled', 'blocked')
    AND (claimed_by IS NULL OR claimed_at IS NULL OR claimed_at < ?)
  ```
  Vorher `ensure_task_claim_columns(conn)` aufrufen (lazy/selbstheilend,
  wie beim due_date-Muster). Vorher `SELECT * FROM tasks WHERE id = ?` NUR
  um `existing_row` für die History-Zeile UND für die
  `started_at`-Einmaligkeit zu haben (dieses SELECT entscheidet NICHTS,
  das UPDATE-WHERE ist die einzige Instanz, die über Erfolg/Misserfolg
  entscheidet — `cursor.rowcount == 1` prüfen, sonst `return False`).
  Bei Erfolg: `started_at` einmalig setzen (falls noch NULL, analog zur
  Logik um `IN_PROGRESS_STATUSES` weiter oben in der Datei), UND eine
  `task_history`-Zeile schreiben, die den Claim protokolliert (schau dir
  an, wie `apply_task_field_changes` `history_entries` aufbaut und in
  `task_history` schreibt, und tue dasselbe für `field_changed="status"`,
  `old_value=<voriger Status>`, `new_value="in_progress"`,
  `action="status_change"`, PLUS eine zusätzliche Zeile/Spalte oder
  Anmerkung, dass es sich um einen Claim von `claimed_by` handelt — nutze
  das vorhandene History-Schema, erfinde keine neue Tabelle).
  `conn.commit()` NICHT selbst aufrufen (Aufrufer-Verantwortung, wie bei
  `apply_task_field_changes`).

```python
def release_claim(conn: sqlite3.Connection, task_id: int) -> bool:
    """Gibt einen Claim vorzeitig frei (Abbruch/Fehler) -- Task faellt auf
    'open' zurueck und ist sofort wieder claimbar. True nur bei echter
    Aenderung (WHERE status='in_progress' verhindert, einen laengst
    abgeschlossenen Task versehentlich wieder zu oeffnen)."""
```
```sql
UPDATE tasks SET status = 'open', claimed_by = NULL, claimed_at = NULL
WHERE id = ? AND status = 'in_progress'
```
`cursor.rowcount == 1` als Rueckgabewert.

### 3) CLI: `bach task claim` / `bach task release`

In `system/hub/task.py`:
- Neue Methoden `_claim(self, args)` und `_release(self, args)`, analog zu
  `_done()` im Aufbau (ID-Parsing über `self._parse_ids(args)`, aber diese
  beiden nehmen typischerweise NUR EINE ID plus `--by <name>` bei `claim`).
  `_claim`: `bach task claim <id> --by <name> [--lease SECONDS]` — Usage-
  Fehler bei fehlendem `--by`. Ruft `claim_task_atomic` auf, committet,
  gibt bei Erfolg `"[OK] Task <id> beansprucht von <name>"` zurück, bei
  Misserfolg `False, "[CONFLICT] Task <id> bereits beansprucht oder nicht
  mehr offen"` (WICHTIG: Misserfolg ist ein NORMALER, erwarteter Fall bei
  einem Wettlauf, keine Ausnahme — der Aufrufer (worker.py) muss das am
  Exit-Code/Rueckgabewert unterscheiden koennen, nicht an einer Exception).
  `_release`: `bach task release <id>` -> `release_claim`.
- In `get_operations()` und `handle()` registrieren (siehe die anderen
  `elif operation == "..."`-Zweige).
- In der `--help`/Operationsliste kurz dokumentieren (wie die anderen
  Operationen dort beschrieben sind).

### 4) `worker.py` nutzt den Claim vor der Arbeit

In `system/hub/_services/chat/worker.py::main()`: nach der Auswahl eines
konkreten Tasks aus `offen` (dort, wo aktuell der erste/naechste Task aus
der Liste genommen und bearbeitet wird — lies den Codeblock nach Zeile 163
vollstaendig, bevor du aenderst, um die bestehende Priorisierungs-/
Blockierungslogik nicht zu zerstoeren), VOR dem eigentlichen Start der
Arbeit einen Subprozess-Aufruf einbauen (analog zu `markiere_erledigt`,
Zeile ~84, das ebenfalls `subprocess.run([sys.executable, bach_cli, "task",
...])` nutzt):
```python
claim_ok = subprocess.run(
    [sys.executable, bach_cli, "task", "claim", str(task_id), "--by", f"worker:{args.category}"],
    capture_output=True, text=True, timeout=30,
).returncode == 0
```
Ist `claim_ok` False: NICHT an diesem Task arbeiten, Log-Zeile schreiben
("Task <id> bereits beansprucht, ueberspringe"), zum naechsten Kandidaten
in `offen` weitergehen bzw. in der naechsten Schleifenrunde neu lesen (dein
Ermessen, folge der bestehenden Schleifenstruktur -- keine Endlosschleife
ohne Fortschritt bauen, falls ALLE Kandidaten schon beansprucht sind: dann
wie bisher "keine bereiten Tasks" behandeln oder kurz warten, siehe
bestehendes `args.takt`-Sleep-Verhalten).
Bricht die Arbeit an einem beanspruchten Task fehlerhaft ab (Exception/
Timeout), rufe `bach.py task release <id>` auf, bevor die Schleife
weiterlaeuft (Best-Effort, Fehler dabei nur loggen, nicht crashen).

### 5) `server.py`: `PUT /api/tasks/{task_id}` claim-bewusst machen

In `update_task()` (Zeile ~1656): wenn `update.status == "in_progress"`
UND `existing_row["status"] != "in_progress"` (also eine ECHTE Neu-
Beanspruchung, keine Bearbeitung eines bereits laufenden eigenen Tasks),
verwende `claim_task_atomic(conn, task_id, update.changed_by or "api")`
STATT den Status-Teil ueber `apply_task_field_changes` zu setzen. Die
UEBRIGEN Felder (`title`, `description`, `priority`, `category`,
`assigned_to`, `created_by`, `depends_on`) laufen weiterhin unveraendert
ueber `apply_task_field_changes` (auch wenn `status` gleichzeitig
mitgegeben wurde -- trenne die beiden Pfade sauber: Status-Wechsel-nach-
in_progress separat behandeln, alle anderen Felder wie bisher in EINEM
`apply_task_field_changes`-Aufruf ohne `status` im `field_values`-dict).
Bei Claim-Misserfolg (`claim_task_atomic` liefert False): Antwort
`{"status": "claim_failed", "success": false}` mit **HTTP 200** (NICHT 4xx
werfen -- `chat_tray.py`s eigener `_api()`-Wrapper interpretiert jeden
Nicht-2xx-Statuscode als Netzwerkfehler und liefert `None` zurueck, das
waere hier nicht unterscheidbar von einem echten Verbindungsfehler).
Alle anderen Statuswechsel (z. B. nach `done`, `blocked`, `cancelled`, oder
ein PUT, das den Task lediglich in seinem AKTUELLEN `in_progress`-Zustand
belaesst) bleiben unveraendert ueber `apply_task_field_changes`.

### 6) `chat_tray.py::_process_idle_task` prueft den Claim

Der bestehende Aufruf (Zeile ~628)
```python
self._api("PUT", f"/api/tasks/{task_id}", {"status": "in_progress", "changed_by": "idle-worker"}, base=self.gui_url)
```
wird zu:
```python
claim_resp = self._api("PUT", f"/api/tasks/{task_id}", {"status": "in_progress", "changed_by": "idle-worker"}, base=self.gui_url)
if not claim_resp or claim_resp.get("status") == "claim_failed":
    print(f"[Idle] Task #{task_id} bereits von anderem Taktgeber beansprucht -- ueberspringe.")
    return
```
(direkt VOR dem Aufbau des `prompt`-Strings einfuegen, also bevor irgendeine
Arbeit am Task beginnt). Fange ab, dass `claim_resp` `None` sein kann
(Netzwerkfehler) -- in dem Fall ebenfalls abbrechen, nicht weiterarbeiten.

## Verhältnis zu Trithon-Salt (für den PR-Text, nicht Teil des Codes)

Schreibe im Abschlussbericht (`_codex/BERICHT-claim.md`) einen kurzen
Absatz: Diese Lösung ist eine **einzelhost-lokale, DB-native Atomarität**
(SQLite `UPDATE ... WHERE ...` mit `rowcount`-Prüfung, ein einziger
Datenbankprozess auf einem Rechner). Der Trithon-Salt-Architekturentwurf
(`.SYNC/ARCHITEKTURENTWURF_OCEAN_LEAD_HOST_TRITHON.md`, NICHT abgenommen)
adressiert eine ANDERE Schicht: Wettläufe ZWISCHEN mehreren Hosts über
cloud-synchronisierte Dateien mit Latenz. Die hier gewählten Feldnamen
(`claimed_by` als freier Text, `claimed_at` als ISO-Zeitstempel) sind
bewusst generisch gehalten und schließen eine spätere Erweiterung um eine
Salt-Validierung (z. B. `claimed_by` könnte später `"<host>:<salt>"`
tragen) nicht aus, nehmen sie aber auch nicht vorweg.

## Verifikation (PFLICHT, keine Abkürzung)

- **Neuer Regressionstest** `system/tests/test_task_atomic_claim.py`:
  - Zwei nebenläufige Claim-Versuche auf DENSELBEN Task (z. B. über
    `concurrent.futures.ThreadPoolExecutor` mit zwei Threads, die beide
    `claim_task_atomic` auf ZWEI SEPARATEN sqlite3-Connections zur selben
    Datei aufrufen, oder über zwei `subprocess.run(["python", "bach.py",
    "task", "claim", ...])`-Aufrufe) — assert: GENAU EINER gewinnt
    (`True`), der andere verliert (`False`), der Task-Status ist danach
    genau einmal `in_progress`.
  - Ein abgelaufener Claim (altes `claimed_at` künstlich in die
    Vergangenheit gesetzt, älter als `lease_seconds`) ist erneut claimbar.
  - Ein bereits `done`/`blocked`/`cancelled` Task ist NICHT claimbar.
  - `release_claim` setzt einen `in_progress`-Task zurück auf `open` und
    löscht `claimed_by`/`claimed_at`.
  - `PUT /api/tasks/{id}` mit `status=in_progress` gegen einen bereits
    beanspruchten Task liefert `{"status": "claim_failed", ...}` bei
    HTTP 200 (FastAPI TestClient, analog zu den bestehenden Tests in
    `system/tests/test_gui_server_smoke.py`).
- `pytest system/tests/test_task_atomic_claim.py -q` ausführen, Ergebnis
  berichten.
- `pytest system/tests/test_gui_server_smoke.py -q` (Regression, ~40 Tests,
  schnell) ausführen, Ergebnis berichten. KEINE volle Suite (haengt/dauert
  zu lange).
- `node`-Check entfaellt (kein JS geaendert).

## Selbstauskunft

Nenne am Ende deines Berichts EXAKT dein Modell.

## Bericht

Schreibe nach `_codex/BERICHT-claim.md`: alle geänderten/neuen Dateien mit
kurzer Beschreibung, den Trithon-Salt-Absatz (siehe oben), Testergebnisse,
`git diff --stat`, dein Modell. Committe alles auf dem aktuellen Branch
(Conventional Commits, z. B. `fix(tasks): atomarer Claim gegen
Doppelausfuehrung -- worker.py + chat_tray + PUT /api/tasks
(T-20260913-709822598)`). NICHT pushen.
