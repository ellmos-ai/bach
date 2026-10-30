# Task 2074 – Worker-Taskkontext bei neuer Lease isolieren (Teilstand)
## Umgesetzt (Worktree task-2074, Branch bach-task/2074, PR-587)
- telegram_chat.py:5188–5264: Guard RuntimeError bei session_store=None (:5194); clear_session(worker_id, archive_reason='Worker Taskwechsel') nur bei newly_acquired_binding is control.task_binding (:5198); Fehlerchecks :5201–5205, :5212–5216; Rebind _snapshot_chat_backend (:5209); _prepare_bound_task_scope mit RuntimeError-Fallback (:5218–5248); newly_acquired_binding=None (:5250); Session-Rebind :5255–5264.
- docs/architecture/WORKER-TASK-CONTEXT-ISOLATION.md (neu, 18 Zeilen).
- system/tests/test_worker_task_binding.py (479 Zeilen, 6 Tests, pytest-monkeypatch auf control.runtime).
## Prüf-/Beleglage (final)
- execute_command bestätigt Prüfläufe nicht: 24 Versuche über 3 Worker-Läufe, 23× „Werkzeugausführung nicht bestätigt; Wirkung unbekannt", 1× BLOCKIERT (py_compile mit 2 Dateipfaden).
- Ersatzbeleg negativ: kein __pycache__ in system/hub/_services/chat und system/tests (Ordnerlistungen), kein .pytest_cache → kein belegter Testlauf.
- Statische Code-/Testinventur bestätigt; Implementierung konsistent mit Test-Assertions.
## Git-Stand
- WIP-Commits auf bach-task/2074 gepusht, PR-587 existiert (https://github.com/ellmos-ai/bach/pull/587).
## Restarbeit (Subtask #2935; blocked-Status nicht setzbar, nur eigene Task änderbar)
- Bestätigter pytest-Lauf von system/tests/test_worker_task_binding.py im Worktree (funktionierende execute_command-Umgebung).
- Danach finish_task(is_wip=false) mit PR-587-Bezug und Abgabe complete=true.