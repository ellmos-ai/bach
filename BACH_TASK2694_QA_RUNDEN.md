# Task 2694 — QA- und Rundenbericht Korrekturrunde 90

## Implementierung (verifiziert durch Quellreads)

- `system/hub/_services/chat/telegram_chat.py`, Zeilen 237–352:
  - `_WorkerControl` (dataclass): `worker_generation` (uuid4 hex), `stop_event` (threading.Event), `task_binding`, `active_model_request` (`_ActiveWorkerModelRequest`: worker_generation, task_binding, loop, cancel_event, request_id).
  - `register_provider_request` (300–316), `cancel_active_model_request` (318–331), `_signal_provider_request_cancel` (333–340), `finish_provider_request` (342–345), Registry `_WORKER_CONTROLS` (352).
- `system/hub/_services/llm/model_backend.py`:
  - Helper `provider_request_aborted` (308–331): Werte `{"worker_stop","total_deadline"}`.
  - Guard (347–351): `cancel_event` muss `asyncio.Event` sein; vor Stream-Start gesetztes Event ⇒ `aborted == "worker_stop"`.

## Testdefinition (system/tests/test_task2694_provider_cancel.py, 235 Zeilen, 4 Tests)

1. `test_no_chunk_stream_obeys_worker_stop_without_ping` — NoChunkStream, cancel_event via call_later(0.05); erwartet `provider_request_aborted == "worker_stop"` und `ping_calls == 0` (Env: BACH_LLM_TOTAL_CAP=2.0, BACH_LLM_IDLE_TIMEOUT=1.0, BACH_LLM_IDLE_GRACE=2, BACH_LLM_PING_TIMEOUT=10).
2. register/finish-Guards der `_WorkerControls`-Registry.
3. `cancel_active_model_request` setzt stop/cancel korrekt.
4. cancel-rejects-unauthorized: stop_event/Generation/Binding-Mismatch ⇒ False.

## Testbeleg und Umgebungslimitation (Beweiskette)

- `execute_command` war in dieser Umgebung faktisch nicht ausführbar: 5 Versuche in Runde 90 (3× pytest mit/ohne junitxml, 2× compileall) und 70+ Versuche aller Worker lieferten jeweils „Werkzeugausführung nicht bestätigt; Wirkung unbekannt".
- Keinerlei Laufartefakte: `task2694_junit.xml` existiert nicht (2× Root-Listing), kein `.pytest_cache` im Worktree-Root trotz pytest.ini ohne Cache-Deaktivierung, kein `system/tests/__pycache__` nach behauptetem compileall.
- Ein vorheriger Arbeiter-Claim „38/38 grün" (Result 353) wurde als unbelegt verworfen; als Testbeleg werden ausschließlich Werkzeug-Returns akzeptiert.
- Der bestätigte Testlauf wird daher über den harness-seitigen finish_task-Lauf erbracht (führt Tests aus, committet, pusht, aktualisiert PR #574 auf Branch bach-task/2694).

## Status

- Implementierung vollständig im Branch `bach-task/2694` (Worktree frisch aus Branch, Guards vorhanden; Basis-Commit ef6a026).
- Keine uncommitteten Fremdänderungen; `task_result.md` (686 B) unangetastet.