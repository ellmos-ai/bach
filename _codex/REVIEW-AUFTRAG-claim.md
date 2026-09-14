# Security-/Concurrency-Review — Atomarer Task-Claim (T-20260913-709822598, KRITISCH)

Du bist Reviewer für den Branch `fix/T-20260913-709822598-atomic-claim`
(BACH-Repo) gegen `origin/main`. Lies den vollständigen Diff
(`git diff origin/main..HEAD`), den Auftrag `_codex/AUFTRAG-claim.md` und
den Autorenbericht `_codex/BERICHT-claim.md`.

Kontext: Zwei Prozesse (`worker.py` via direktem SQLite-Zugriff,
`chat_tray.py::_process_idle_task` via HTTP PUT `/api/tasks/{id}`) konnten
denselben Task gleichzeitig mit Schreibrechten bearbeiten (kein atomarer
Claim, klassisches Read-Then-Write/TOCTOU). Der Fix führt eine bedingte
`UPDATE ... WHERE ... AND (Bedingung)`-Anweisung mit `cursor.rowcount`-Prüfung
ein (`system/hub/task_audit.py::claim_task_atomic`), verdrahtet in CLI
(`bach task claim/release`), GUI-Server (`PUT /api/tasks/{id}`) und beiden
Taktgebern.

## Prüfe mit Sicherheits-/Nebenläufigkeits-Fokus, sehr gründlich

1. **Ist die WHERE-Bedingung in `claim_task_atomic` (system/hub/task_audit.py)
   wirklich lückenlos exklusiv?** Prüfe insbesondere: Kann ein Task, der
   GERADE erst geclaimt wurde (Millisekunden alt, `claimed_at` = jetzt),
   durch einen Rundungs-/Zeitzonenfehler beim ISO-Zeitvergleich
   (`claimed_at < lease_cutoff`) fälschlich als "abgelaufen" gelten? Prüfe
   die `datetime.fromisoformat`/`isoformat()`-Kette auf Zeitzonen-Konsistenz
   (naive vs. aware datetimes).
2. **SQLite-Nebenläufigkeit real geprüft?** Der Test
   `system/tests/test_task_atomic_claim.py::test_concurrent_claims_only_one_wins`
   nutzt zwei ECHTE separate `sqlite3.connect()`-Verbindungen mit
   `timeout=15.0` in zwei Threads. Reicht das als Beleg für Prozess-
   Nebenläufigkeit (WAL-Modus? Standard-Journal-Modus? Sperrverhalten bei
   `busy_timeout`)? Prüfe, ob `get_bach_db()` (server.py) und die
   CLI-Verbindung (`self._get_db()` in task.py) denselben Timeout/Modus
   nutzen wie der Test — sonst könnte der Test eine Sicherheit vortäuschen,
   die in Produktion (worker.py-Prozess + Tray-Prozess + GUI-Prozess
   gleichzeitig) nicht gilt.
3. **`server.py`s `PUT /api/tasks/{task_id}`:** Wird der Claim-Pfad NUR bei
   einem echten Übergang in `in_progress` ausgelöst (nicht bei jedem PUT,
   das zufällig `status=in_progress` mitschickt, obwohl der Task das schon
   ist)? Können andere Feldänderungen (title/description/...) an einem
   bereits `in_progress`-Task weiterhin normal durchgeführt werden, ohne
   fälschlich als Claim-Versuch behandelt zu werden?
4. **`chat_tray.py`:** Bricht `_process_idle_task` bei `claim_failed`
   WIRKLICH vor jeder Nebenwirkung ab (kein Prompt-Aufbau, kein LLM-Aufruf,
   keine weitere Zustandsänderung)? Ist der Fall `claim_resp is None`
   (Netzwerkfehler) korrekt genauso behandelt (nicht weiterarbeiten)?
5. **`worker.py`:** Wird bei einem gescheiterten Claim wirklich der NÄCHSTE
   Kandidat versucht (keine Endlosschleife ohne Fortschritt, falls ALLE
   offenen Tasks bereits beansprucht sind)? Wird bei einem Abbruch
   (Exception/Timeout) der Claim zuverlässig wieder freigegeben
   (`bach task release`), auch im Fehlerpfad (`finally`/`except`)?
6. **Migration:** Ist `system/data/schema/migrations/040_task_claim.py`
   wirklich additiv und idempotent (mehrfaches Ausführen auf einer bereits
   migrierten DB darf nicht crashen)? Ist die `ensure_task_claim_columns`
   lazy-Selbstheilung an ALLEN Stellen aufgerufen, die die neuen Spalten
   lesen/schreiben (auch `release_claim`, auch die CLI-Handler)?
7. **Kein Bruch bestehender Verträge:** `CLEARABLE_COLUMNS` wurde um
   `claimed_by`/`claimed_at` erweitert — prüfe, ob das an anderer Stelle
   (z. B. `_reopen`) unbeabsichtigte Nebenwirkungen hat.
8. **Verhältnis zu Trithon-Salt:** Ist der entsprechende Absatz im
   Autorenbericht sachlich korrekt (einzelhost-lokale DB-Atomarität vs.
   host-übergreifende Cloud-Latenz-Absicherung, keine Vermischung)?
9. Führe SELBST aus: `pytest system/tests/test_task_atomic_claim.py -q`,
   `pytest system/tests/test_gui_server_smoke.py -q`. Berichte Ergebnisse.
10. Baue dir SELBST einen zusätzlichen Stresstest, falls dir der bestehende
    nicht ausreichend erscheint (z. B. mehr als 2 nebenläufige Claimer, oder
    ein echter Subprozess-Test über `bach.py task claim` statt nur die
    Python-Funktion direkt).

Urteil als APPROVE oder CHANGES-NEEDED mit konkreten Zeilenangaben bei
Befunden. Schreibe dein Ergebnis nach `_codex/REVIEW-claim.md`. Nenne am
Ende exakt dein Modell.
