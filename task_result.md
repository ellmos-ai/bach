# Task #2074 – Worker-Taskkontext bei neuer Lease isolieren und Verlauf archivieren

**Stand: Implementierung fertig; einzig offen ist die pytest-Bestätigung, die im Worker-Umfeld trotz 36+ Versuchen (inkl. Sanity-Check) nicht bestätigbar ist. Tests bitte im Controller-Review zu PR #587 ausführen.**

## Fertiggestellt
- `system/hub/_services/chat/telegram_chat.py`: Guard-Block Zeilen 5186–5264 verifiziert. Vor jeder neuen Task-Lease wird der bestehende Worker-Taskkontext (Session) archiviert und eine frische, leere Session erzeugt; Backend-/Modell-/Tool-/Systemprompt-Profile werden aus dem Worker-Slot projiziert.
- `docs/architecture/WORKER-TASK-CONTEXT-ISOLATION.md`: Architektur-Doku vorhanden.
- `system/tests/test_worker_task_binding.py`: 479 Zeilen, 6 Tests, pytest-only (Fixtures, parametrize, mem_db – keine Live-DB).

## Statische Qualitätssicherung (abgeschlossen)
- Vollständiger Review der Testdatei Zeilen 1–479: kein Fehler gefunden. Aufbau konsistent zur Implementierung:
  - Isolation alter Session vor neuer Lease (Assertion: kein „Vorheriger privater Gesprächsverlauf“/„Task-42-only transcript“ in neuen Sessions, `observed_sessions[0][0] is not observed_sessions[1][0]`).
  - Archivierung über `session_snapshots` mit `:archived:`-Sitzungs-Suffix und `CHAT_SNAPSHOT_TYPE`; Archiv enthält alte Taskverläufe, aktive Session nach Abschluss leer (`store.load(wid) == []`).
  - `worker_task_binding`, `execute_task_manage` (done → task_review), `consume_task_completion_receipts` (foreign/review-text/blocked/returned/review/next-assignment-denied), `clear_session`, Lease-Freigabe (`client.read(42).leased is False`).
  - Error-Pfade: missing-store, broken-store (Chat-DB ohne snapshot-Tabelle), foreign-holder → Status „error“, Lease bleibt frei; Native-Factory-Autoritätsprüfungen (`LeaseError` vor Projection-Öffnung).
  - Parametrisiert: continuous/persistent × http/native × once/review; ACK-Wege (actual-ack → task_review, no-task → not_finished).
  - SynchronousThread-Mock statt echtem Threading; `BACH_TASK_LEASE_CREATOR_WINDOW=0` deterministisch.

## pytest-Ausführung – Werkzeugstörung dokumentiert
- Alle Varianten unternommen (jeweils cwd=Taskarbeitsbaum, auch junitxml zur Artefaktsicherung): `python -m pytest [±-q][±--junitxml=pytest_2074.xml] -- system/tests/test_worker_task_binding.py`, `python3 -m pytest …`, `compileall`, Sanity-Check `python -m pytest --version` – jedes Mal „Werkzeugausführung nicht bestätigt; Wirkung unbekannt“.
- Sanity-Check beweist: Störung ist werkzeug-/ergebniskanalseitig, nicht befehlsspezifisch.
- Artefakt-Checks negativ: `pytest_2074.xml` mehrfach „nicht gefunden“ (file_info), kein `.pytest_cache` im Root (conftest.py setzt `dont_write_bytecode=True`, fehlendes `__pycache__` also normal) → Läufe kommen wirklich nicht zustande.
- `py_compile` als Ausweichprüfung: BLOCKIERT (nur pytest/unittest/compileall erlaubt); unittest-Variante unmöglich (pytest-only-Fixtures, parametrize).

## Restarbeit
1. `python -m pytest -- system/tests/test_worker_task_binding.py` im Controller-Review zu PR #587 ausführen und bestätigen (Worktree/Branch: bach-task/2074).
2. Danach Abnahmekriterien von Task #2074 prüfen und Task abschließen.