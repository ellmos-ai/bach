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

## QA-Receipt (TEILSTAND 2 – Prüfungen weiterhin UNBESTÄTIGT)

Lauf 2, Korrektur 73 zu Task #2690 (Bindung: e585bf36bb7ff5f18e47048a8f48aa64503a1085 + Ein-Datei-Commit 5a9bd46fb3269f66e8804e33689ade1f2a9523ea).

1) Fixture-Vollprüfung (statisch, belegt durch Lesen): system/tests/test_worker_scope_snapshot.py vollständig Z.1–431 gelesen; Metadaten 431 Zeilen / 16,2 KB / geändert 2026-10-30 07:01:19 / Rechte 644.
2) Kernstruktur bestätigt: TASK_ID=41, ORIGIN=https://github.com/ellmos-ai/bach (Z.15–16); _new_scope_repo (Z.26–76) mit HOME+BACH_LOCAL_DIR → base/home/.bach und chmod 0o700 (Z.29–35), Registrierung des public source nur bei pinned=True (Z.70); _install_lock_scanner (Z.79–97, BACH_LOCK_SCAN); scope_repo-Fixture (Z.100–104); _snapshot (Z.107–112); _assert_available (Z.122–140).
3) Plattformabhängigkeit bestätigt: Symlink-Test springt per pytest.skip, wenn kein Directory-Symlink verfügbar (Z.233–241) – erklärt Win 28 passed/1 skipped vs. Mac 29 passed.
4) Testinventar bestätigt: 18 Testfunktionen (Z.143–409) und 6 Parametrisierungen – dirty_kind 3 (Z.183), branch_state 2 (Z.196), flag 2 (Z.246), origin_state 2 (Z.253), scanner_failure 4 (Z.273), task_id 4 (Z.292) = 17 Param-Fälle + 12 Einzelitems = 29 Items (arithmetisch konsistent, NICHT als Laufbeleg gewertet).
5) Weitere belegte Pfade: git_changed (Z.307–334); gitlink/submodule_scope_unsupported vor jedem status-Read (Z.337–359); autouse-Fixture hermetic_snapshot_git_environment mit GIT_CONFIG_GLOBAL=/dev/null (Z.362–377); Clean-Filter-Marker-Test (Z.380–406); Sanitizer-Test für GIT_OPTIONAL_LOCKS=0 / GIT_TERMINAL_PROMPT=0 / GIT_NO_REPLACE_OBJECTS=1 und Erhalt der BACH_-Variablen (Z.409–431).
6) Native Scope-/Resultrevision: NICHT bestätigt. git-Status/HEAD-Pfüfung im Worktree sowie .git-Metadatenlesen wurden von den Werkzeugen nicht bestätigt (read_file auf .git: BLOCKIERT, Task-Lesebereich nicht bestätigt).
7) Ist-SHA-256 der Fixture: NICHT bestätigt. Sollwert unverändert b98a1999f3d92715b42b91d4e5158ed638111c67c3e1f9fa1d6a78f10b9d6b18; kein freigegebenes Hash-Werkzeug, python -c blockiert.
8) pytest-Lauf im Worktree: NICHT bestätigt. execute_command (pytest und compileall) liefert in dieser Umgebung durchgängig „Werkzeugausführung nicht bestätigt; Wirkung unbekannt"; keine Laufwiederholung mehr.
9) Suche nach unabhängigem Sol-Code-QA-Receipt zu e585: search_text in docs/ des Worktrees → 0 Treffer für 5a9bd46|e585bf36; Worktree-Root-Suche ohne bestätigte Ausgabe. Ein externes Sol-Code-QA-Receipt ist damit NICHT belegt.
10) Konsequenz: Auftrag 73 gilt als NICHT erledigt. Kein Done, kein vollständiger Beleg; Task #2690 bleibt pending und wird mit complete=false zurückgegeben.
Offen (Reihenfolge): (a) unabhängiges Sol-QA-Receipt zu e585 beibringen, (b) bestätigter git-HEAD/Status-Beleg (HEAD=5a9bd46…, Base e585bf36…, genau eine geänderte Datei), (c) bestätigter Ist-SHA-256 == Soll, (d) bestätigter pytest-Lauf (Mac 29 passed / Win 28p+1s), (e) Receipt-Finalisierung.

TEILSTAND 3 (Fortsetzungslauf; kanonische Worktree-Bindung task-2690 unverändert):
1) Fixture system/tests/test_worker_scope_snapshot.py jetzt lückenlos gelesen (Z.1–431): nachgelesen Z.315–335 (commit-during-observation: Monkeypatch auf guard._scope_git, beim Read „rev-parse --verify HEAD^{tree}" → add+commit concurrent-change.txt; assert git_changed) und Z.422–431 (Sanitizer: safe_git = GIT_OPTIONAL_LOCKS=0/GIT_TERMINAL_PROMPT=0/GIT_NO_REPLACE_OBJECTS=1, BACH_SCOPE_TEST_PRESERVED bleibt erhalten). Die Beschreibungen aus Teilstand 2 (Z.24–25) sind damit bestätigt.
2) pytest-Einzelretry laut Plan (1×, „python -m pytest -p no:cacheprovider -q system/tests/test_worker_scope_snapshot.py", cwd=/Users/lukas/services/bach-worktrees/task-2690): erneut „Werkzeugausführung nicht bestätigt; Wirkung unbekannt". Kein Testbeleg; Wiederholungen eingestellt.
3) search_text „e585bf36" auf system/ (recursive): unbestätigt („Werkzeugausführung nicht bestätigt"); als unbelegt vermerkt. Belegte Null-Treffer bleiben docs/ (dieser Lauf), _codex/ (5a9bd46) und tests_tmp_gardener/ (e585bf36) aus dem Vorlauf.
4) Unabhängiges Sol-Code-QA-Receipt zu e585bf36…+5a9bd46…: weiterhin NICHT belegbar (docs 0 Treffer, system unbestätigt, keine weiteren Quellen bekannt). Gemäß Korrektur 73 gilt daher: complete=false, kein Done, kein unabhängiges QA-Urteil behauptet.
5) Keine Code-Änderungen in diesem Lauf; ausschließlich task_result.md erweitert (kein finish_task). Task #2690 bleibt pending; native Resultrevision (HEAD/Status/Diff) und Ist-SHA-256 bleiben unbelegt.