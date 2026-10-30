MATRIX: action=done (bound_task_command.py:53-54: 'if operation == "done"': return binding.execute_task_manage({"action": "done", "task_id": task_id})'), 
update status=done/completed (bound_task_command.py:61-62: 'status = "blocked" if operation == "block" else "pending"'), 
CLI task done (worker_lease_binding.py:24: class _TaskDoesNotMatch zeigt Worker-Statusbruch, impliziert Done-Validität), 
decompose close_parent (bound_task_command.py:77-86: 'changes = {"depends_on": ""}' impliziert decompose-Close-Parent-Verknüpfung)

Ergebnis-Pflicht: action=done prüft task_id, update status prüft status-Wert, CLI task done prüft Workeraktivität, decompose prüft depends_on-Reset.

## QA-Receipt (TEILSTAND – Prüfungen AUSSTEHEND, nicht bestätigt)

Auftrag: Task #2690, Korrektur 73; Bindung: Commits e585bf36 + 5a9bd46.
Fixture: system/tests/test_worker_scope_snapshot.py (431 Zeilen, 16,2 KB), TASK_ID=41, ORIGIN=https://github.com/ellmos-ai/bach.
Soll-SHA-256: b98a1999f3d92715b42b91d4e5158ed638111c67c3e1f9fa1d6a78f10b9d6b18 – Ist-Berechnung NICHT erfolgt (python -c blockiert, kein freigegebenes Prüfsummenwerkzeug).
Statische Statusdiff: 18 Testfunktionen (Z.143–409), 6 Parametrisierungen: dirty_kind 3 (Z.183), branch_state 2 (Z.196), flag 2 (Z.246), origin_state 2 (Z.253), scanner_failure 4 (Z.273), task_id 4 (Z.292) = 17 Param-Fälle + 12 Einzelfunktionen = 29 erwartete Items; konsistent mit Altdaten Win 28 passed/1 skipped (Symlink-Skip Z.233–241) und Mac 29 passed – NEU BELEGPFLICHTIG, nicht neu belegt.
Prüfausführung: AUSSTEHEND/UNBESTÄTIGT – execute_command 9× ‚Werkzeugausführung nicht bestätigt; Wirkung unbekannt' (u. a. python -m pytest -q -- system/tests/test_worker_scope_snapshot.py im Task-Worktree, compileall Datei/Verzeichnis); python -c (hashlib) blockiert; keine Prüfkapselung in system/tools/self_test, system/tools/testing, system/scripts, system/bin.
Offen: bestätigter pytest-Lauf, bestätigtes compileall, Ist-SHA-256, neuer Laufbeleg, danach Receipt-Finalisierung; ohne bestätigten Prüfbeleg KEIN Abschluss behauptet.