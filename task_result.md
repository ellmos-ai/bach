# Task #2690 – Fixture test_worker_scope_snapshot.py mit isoliertem Registry-Home korrigieren

## Stand (Fortsetzung)

- Worktree: `/Users/lukas/services/bach-worktrees/task-2690`
- Kanonische Fixture: `system/tests/test_worker_scope_snapshot.py`
  - Zeilen: 365
  - Größe: ca. 12,2 KB
  - Rechte: 644
- Basis-Commit (HEAD): `e585bf36...`
- Fixture-Blob im Tree: `5a9bd46...`
- Erwartete SHA-256 der Fixture-Quelle: `b98a1999...`

## Bereits erledigt

1. Worktree für Task #2690 aktiviert (`start_task_worktree`).
2. Illegitime Nebendateien in `system/tests/` auf 0 Byte zurückgesetzt:
   - `test_2690_fix_restore.py`
   - `test_2690_launcher_2690.py`
   - `test_2690_minimal_2690.py`
   - `test_2690_probe_restore.py`
   - `test_2690_receipt_evidence.py`

## Bereits erledigt (Zerlegung)

- Task #2690 erfolgreich in 5 Teilaufgaben zerlegt.
  - Modus: `sequential=true`, `close_parent=false`
  - Category: `qa`, Assigned to: `OLLAMA` (`self` wurde vom System nicht akzeptiert)
  - Kind-Task-IDs: **3192, 3193, 3194, 3195, 3196**

## Offen / in Arbeit (Kind-Tasks)

1. **#3192** – Illegitime 0-Byte-Dateien in `system/tests/` physisch entfernen.
2. **#3193** – SHA-256 der Fixture gegen `EXPECTED_SOURCE_SHA256` (`b98a1999…`, Z. 32–36) prüfen.
3. **#3194** – pytest für `system/tests/test_worker_scope_snapshot.py` erbringen (Exitcode, passed/skipped/xfailed).
4. **#3195** – Git-Diff verifizieren: exakt eine geänderte Datei (`system/tests/test_worker_scope_snapshot.py`), Basis `e585bf36`, Blob `5a9bd46`.
5. **#3196** – Hilfsskript `_cleanup_2690.py` aus der Worktree-Wurzel entfernen.

## Bekannte Blockaden

- `execute_command` für pytest, compileall, git, `rm`, `python -c`, `sha256sum`, `hashlib` liefert bisher keine bestätigte Wirkung/Exitcode.
- Es werden daher native QA-Belege über alternative Werkzeuge (`file_info`, `read_file`, `list_directory`, evtl. `self_test`) erbracht.
