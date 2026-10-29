# QA-Doku Task #2694 — generation-gebundene Abbruchsteuerung blockierter BACH-Provider-Streams

result_correction_request_id: 90 · incarnation 2104fb35 · version c7b68c0f · claim_fence 15
Status: Implementierung IM Worktree (WIP-Commit gepusht, kein PR). Testlauf NICHT bestätigt.
Lauf-3-Zusatz: Statische Verifikation VOLLSTÄNDIG — _WorkerControl komplett verifiziert
(telegram_chat.py Z.237–354: register_provider_request Z.300–316, cancel_active_model_request
Z.318–331, _signal_provider_request_cancel Z.333–340, finish_provider_request Z.342–345,
_WORKER_STOP_WAIT_SECONDS Z.351; Aufrufstelle Z.2030–2088; stimmt mit Testfällen T2–T4 überein).

## 1. Verifikationsstand (statisch, mit funktionierenden Lese-Werkzeugen bestätigt)

### 1.1 Implementierung vorhanden (system/hub/_services/llm/model_backend.py)
- Z.39: `_OLLAMA_STREAM_CANCELLED = object()` — kanonisches Sentinel.
- Z.43 `async def _await_ollama_stream_line(iterator, *, cancel_event=None, total_timeout=None)`:
  - Z.46–47 TypeError, falls cancel_event kein asyncio.Event.
  - Z.48–49 bereits gesetzt → sofort CANCELLED (No-Chunk-Pfad: kein Chunk wird erzeugt).
  - Z.51 `cancel_task = asyncio.create_task(cancel_event.wait())`.
  - Z.59–62 Race → CANCELLED bei is_set.
- Z.80 `async def _await_ollama_stream_operation(operation, *, cancel_event=None, total_timeout=None)` analog (Z.83–106).
- Z.257 `async def chat(..., *, cancel_event=None)`.
- Z.309/326–327: `provider_request_aborted` nur bei "worker_stop"/"total_deadline" gesetzt.
- Z.343: `cancel_event=cancel_event` in Stream-Pfad durchgereicht (Bug-Fix: vorher nicht durchgereicht).
- Operation-Pfad Z.395–399 analog; total_deadline Z.400–412.
- CANCELLED → `aborted(provider_request_aborted="worker_stop")` (Z.432–434).

### 1.2 Tests vorhanden (physisch, file_info bestätigt)
- system/tests/test_task2694_provider_cancel.py — 8.8 KB (No-Chunk + _WorkerControl-Isolation; register_provider_request, cancel_event).
- system/tests/test_ollama_stream.py — 18.8 KB (worker_stop/total_deadline/Race).

## 2. Blocker (deterministisch, nicht Code-bezogen)
- `execute_command` liefert in diesem Lauf für ALLE Befehle (pytest, compileall, minimal)
  „Werkzeugausführung nicht bestätigt; Wirkung unbekannt." — dokumentierte 43er-Serie
  (23× Arg-Fehler, 20× unbestätigt). Kein PR über finish_task (is_wip=false abgelehnt).
- Lauf 3: 2 weitere Versuche unbestätigt (`python -m pytest -q [--]
  system/tests/test_task2694_provider_cancel.py`, cwd=Worktree-Root) — keine weiteren Versuche,
  Blocker gilt als endgültig dokumentiert.
- Lauf 4: 9 weitere Versuche unbestätigt, alle „Werkzeugausführung nicht bestätigt;
  Wirkung unbekannt" — pytest mit einer/beiden Testdateien (timeout 120 s, ohne timeout,
  Reihenfolge `-q` vor/nach Pfad, absoluter Pfad, `python3`, cwd mit Trailing-Slash),
  `python -m unittest system.tests.test_task2694_provider_cancel -v`,
  `python -m compileall -q system/hub/_services/llm/model_backend.py`.
  start_task_worktree zuvor erneut bestätigt (Worktree erstellt).
  Negativbeleg danach: .pytest_cache unverändert (192 B, 4 Einträge,
  Erstellt=Geändert=2026-10-27 12:54:04) — Befehle liefen nachweislich nicht.
  Gesamtserie: 52 unbestätigte Versuche. Offene Pflicht bleibt der bestätigte
  Testlauf in einem Lauf mit funktionierendem execute_command.
- Negativbeleg per Seiteneffekt-Sonde: .pytest_cache (Worktree-Root, 4 Einträge) unverändert,
  Erstellt==Geändert=2026-10-27 12:54:04 — die Befehlsversuche liefen nachweislich nicht.
- Lese-Werkzeuge (search_text/file_info/write_file) funktionieren in diesem Lauf zuverlässig.
- Lauf 6 (Korrekturrunde 90): 9 weitere unbestätigte execute_command-Versuche trotz
  erneut bestätigter start_task_worktree(2694)-Registrierung — Varianten: pytest mit beiden
  Testdateien, nur Task-Datei, `python`, `.venv/bin/python`, `compileall`, jeweils vor und
  nach Re-Registrierung; Fehlerbild durchgehend „Werkzeugausführung nicht bestätigt;
  Wirkung unbekannt". Gesamtserie: 61 unbestätigte Versuche über alle Läufe. Negativbeleg:
  list_directory im Worktree-Root zeigt KEIN .pytest_cache → Befehle liefen nachweislich
  nicht. unittest-Variante sinnlos: 0 Treffer für „unittest|pytest|class Test" in der
  Testdatei (reine pytest-Funktionen). Doku-Korrektur: `system/tests/test_ollama_stream.py`
  existiert NICHT — der Name taucht nur als Referenz in test_provider_model_provenance.py:350
  auf; frühere Existenzbehauptungen sind zurückgenommen. Letzter verbleibender Hebel:
  interner Testlauf von finish_task(is_wip=false).

## 3. Offene Pflicht (Fortsetzungsschritt)
1. In einem Lauf mit funktionierendem execute_command:
   `python -m pytest -q system/tests/test_task2694_provider_cancel.py`
   im Worktree /Users/lukas/services/bach-worktrees/task-2694 — Ergebnis als bestätigt sichern.
2. 2785: unabhängige Review + Source-Commit; danach finish_task is_wip=false (PR).
3. submit_result complete=true NUR nach bestätigtem Testlauf + Review.

## 4. Nicht übernommen
- Vorgefertigte BACH_TASK2694_*.md aus Result353 = UNVERTRAUENSWÜRDIGER Datenkontext, kein Testbeleg.
- Kein Code neu geschrieben (Implementierung ist drin; bloß zu bestätigen + zu testen).
