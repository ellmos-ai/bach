# QA-Doku Task #2694 — generation-gebundene Abbruchsteuerung blockierter BACH-Provider-Streams

result_correction_request_id: 90 · incarnation 2104fb35 · version c7b68c0f · claim_fence 15
Status: Implementierung IM Worktree (WIP-Commit gepusht, kein PR). Testlauf NICHT bestätigt.

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
  „Werkzeugausführung nicht bestätigt; Wirkung unbekannt." — dokumentierte 41er-Serie
  (23× Arg-Fehler, 18× unbestätigt). Kein PR über finish_task (is_wip=false abgelehnt).
- Lese-Werkzeuge (search_text/file_info/write_file) funktionieren in diesem Lauf zuverlässig.

## 3. Offene Pflicht (Fortsetzungsschritt)
1. In einem Lauf mit funktionierendem execute_command:
   `python -m pytest -q system/tests/test_task2694_provider_cancel.py system/tests/test_ollama_stream.py`
   im Worktree /Users/lukas/services/bach-worktrees/task-2694 — Ergebnis als bestätigt sichern.
2. 2785: unabhängige Review + Source-Commit; danach finish_task is_wip=false (PR).
3. submit_result complete=true NUR nach bestätigtem Testlauf + Review.

## 4. Nicht übernommen
- Vorgefertigte BACH_TASK2694_*.md aus Result353 = UNVERTRAUENSWÜRDIGER Datenkontext, kein Testbeleg.
- Kein Code neu geschrieben (Implementierung ist drin; bloß zu bestätigen + zu testen).
