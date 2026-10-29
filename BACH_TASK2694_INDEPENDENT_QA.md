# BACH Task #2694 – Unabhängige QA-Dokumentation (final – Testlauf blockiert)

**Status: KORREKTURRUNDE 1 – Testergebnisse: BLOCKIERT.** Kein einzelner
Testlauf wurde bestätigt ausgeführt. `execute_command` wurde in 30 Versuchen
nicht bestätigt ausgeführt (23× „Prüfargumente oder Prüfpfade sind nicht
zugelassen“, inkl. `python -c`; 7× „Werkzeugausführung nicht bestätigt;
Wirkung unbekannt“, davon 4 im Vorlauf und 3 in Korrekturrunde 1:
`python -m pytest tests/test_task2694_provider_cancel.py -v` im `system`-cwd,
`python -m unittest tests.test_task2694_provider_cancel -v` im `system`-cwd,
`python -m pytest system/tests/test_task2694_provider_cancel.py -v` vom
Worktree-Root).
Diese Datei dokumentiert Implementierungsstand und Abdeckung **per
Quellcode-Lektüre**, keine verifizierte End-to-End-Ausführung.

---

## (a) Auftrag und Umfang

Task #2694:
1. Deterministischer No-Chunk-Test: Ein Stream-Provider liefert **nie** eine
   Zeile (kein Chunk, kein `data:`-Frame). Der Abbruch muss allein über
   `worker_stop` (workerseitiger Abbruch) erfolgen; **kein** Liveness-Ping
   darf ausgelöst werden (`ping_calls == 0`).
2. Unit-Isolation-/Race-Tests für `_WorkerControl`
   (`system/hub/_services/chat/telegram_chat.py`):
   - `register_provider_request`: Guards (stop gesetzt, falsches Binding,
     Doppel-Registrierung, success, finish/Re-Register)
   - `cancel_active_model_request`: autorisierter Abbruch aktiv laufender
     Provider-Requests
   - Zurückweisung nicht autorisierter States (ohne stop, Generations-Mismatch,
     Binding-Mismatch)
3. Danach: Regressionstests, QA-Doku, `finish_task` und Abgabe.

## (b) Implementierungsstand (per Quellcode-Lektüre)

Die Implementierung ist **vorhanden**, es fehlt kein Code (bestätigt durch
Lektüre von `model_backend.py`, `telegram_chat.py`, `chat_runtime.py`):

- `system/hub/_services/llm/model_backend.py`
  - Z. 43/45/46: `cancel_event`-Verarbeitung im Ollama-Chat-Stream.
  - Stream-Mechanik: `async with httpx.AsyncClient(...)` →
    `client.stream(...)` → `async with` → `async for line in
    response.aiter_lines()`; Liveness-Ping über `client.get(...)`;
    Abbruch-Erkennung am Zeilenanfang jeder Iteration → Rückgabe von
    `provider_request_aborted: "worker_stop"`, `tool_calls=None`,
    `content in (None, "")`.
  - Env-Grenzen: `BACH_LLM_TOTAL_CAP`, `BACH_LLM_IDLE_TIMEOUT`,
    `BACH_LLM_IDLE_GRACE`, `BACH_LLM_PING_TIMEOUT`.
  - Korrekturlauf 2: toter Import `_request_worker_revocation` (Z. 35)
    entfernt; `search_text` über `system/hub/_services/llm` bestätigt 0
    Treffer – Importfix im Task-Worktree enthalten.
- `system/hub/_services/chat/telegram_chat.py` (~Z. 225–345)
  - `worker_id` Pflicht, `generation=uuid4().hex`.
  - `active_model_request` (Z. 288/306/315), `register_provider_request`
    (Z. 300), `cancel_active_model_request` (Z. 318), Aufrufstelle Z. 2069.
  - `register_provider_request` → `None` bei: stop_event gesetzt,
    fremdem Control, task_binding-Mismatch, belegtem
    `active_model_request`.
  - `cancel_active_model_request` → `False` bei: stop nicht gesetzt,
    Request `None`, Generations-Mismatch, Binding-Mismatch; sonst
    `cancel_requested=True` + `call_soon_threadsafe(_signal_provider_request_cancel)`.
  - `_WORKER_CONTROLS`: modulglobales Dict (Z. 352).
- `system/hub/_services/chat/chat_runtime.py`
  - Z. 3065/3072: Mapping „worker_stop“ → `provider_request_aborted`.
  - Z. 2078/2096: `register_provider_request`/`finish_provider_request`;
    `cancel_event` Z. 2077/2079/2093.

## (c) Quellcommit

Quellcommit lt. Übergabe: `ef6a0269`. **Verifikation blockiert** –
lesende Git-Befehle sind in dieser Umgebung nicht durchführbar (blockiert).
Der Commit ist daher nicht unabhängig verifizierbar; als Stand der Lektüre
gilt der Worktree `/Users/lukas/services/bach-worktrees/task-2694`.

## (d) Abdeckungsmapping der 4 Tests auf Codestellen

Testdatei: `system/tests/test_task2694_provider_cancel.py`
(235 Zeilen, per `file_info` bestätigt vorhanden).

| Test | Zeilen | Deckt ab |
|---|---|---|
| `test_no_chunk_stream_obeys_worker_stop_without_ping` | 18–108 | `model_backend.py` Z. 43/45/46 + Stream-Mechanik: No-Chunk-Stream (`aiter_lines` yielded nie, `read_started`/`read_cancelled` gesetzt), Env-Caps per monkeypatch (`limit` → bounded), `httpx.AsyncClient` durch Fake ersetzt, `loop.call_later(0.05, cancel_event.set)`. Asserts: `provider_request_aborted=="worker_stop"`, `tool_calls is None`, `content in (None, "")`, `read_started`/`read_cancelled`/`response_closed`/`client_closed` gesetzt, `ping_calls==0`, `pending==[]` |
| `test_worker_control_register_guards_and_finish` | 111–149 | `telegram_chat.py` `register_provider_request` (Z. 300): Guards (a) kein Map-Eintrag→None, (b) Eintrag in `_WORKER_CONTROLS`, (c) binding None→None, (d) fremdes Binding→None, (e) stop_event gesetzt→None, (f) Erfolg (handle.task_binding/binding, worker_generation==generation, active_model_request is handle), (g) Doppel-Registrierung→None, (h) `finish_provider_request(object())` ändert active_model_request nicht, (i) passendes finish räumt ab, (j) Re-Register nach finish möglich; finally-Pop |
| `test_worker_control_cancel_active_model_request` | 152–176 | `telegram_chat.py` `cancel_active_model_request` (Z. 318): nach `register_provider_request` + `stop_event.set()` → True, `handle.cancel_requested is True`, nach 2× `asyncio.sleep(0)`: `cancel_event.is_set()`; finally-Pop |
| `test_worker_control_cancel_rejects_unauthorized_states` | 179–235 | `cancel_active_model_request` False-Fälle: (A) ohne stop_event, (B) `worker_generation="andere-generation"` (Mismatch), (C) binding nach Registrierung auf `object()` geändert (Mismatch); finally-Pop |

## (e) Testmatrix – Ergebnis: BLOCKIERT – nicht ausgeführt

| Test | Ergebnis |
|---|---|
| `test_no_chunk_stream_obeys_worker_stop_without_ping` | **BLOCKIERT – nicht ausgeführt** |
| `test_worker_control_register_guards_and_finish` | **BLOCKIERT – nicht ausgeführt** |
| `test_worker_control_cancel_active_model_request` | **BLOCKIERT – nicht ausgeführt** |
| `test_worker_control_cancel_rejects_unauthorized_states` | **BLOCKIERT – nicht ausgeführt** |
| Regressionen `test_ollama_stream.py` | **ENTFALLEN – Datei existiert nicht** (Lauf 6 verifiziert: nur Namensreferenz in test_provider_model_provenance.py:350; frühere Zeilenangaben zurückgenommen) |
| Regressionen `test_worker_execution_runtime.py` | **BLOCKIERT – nicht ausgeführt** |

Keine Behauptung über E2E-Verhalten: Alle Ergebnisse stehen aus; ein
JUnit-XML (`pytest_2694.xml`) existiert nicht, `system/tests` enthält kein
`__pycache__` – Befehle liefen nachweislich nicht (Fortsetzungslauf 2:
erneut per list_directory negativ verifiziert).

## (f) Blockade-Dokumentation

- `execute_command`: **41 Versuche ohne bestätigte Ausführung** (inkl.
  Vorlauf; Bilanz: 23× „Prüfargumente oder Prüfpfade sind nicht zugelassen",
  18× „Werkzeugausführung nicht bestätigt; Wirkung unbekannt", davon 3 in
  Korrekturrunde 1, 11 in Korrekturrunde 2). Varianten geprüft: pytest mit/ohne `--`, nach erneutem
  `start_task_worktree`, `compileall` relativ/absolut, `--collect-only`,
  `--version`, `--junitxml` (mehrfach, zuletzt 3× in Folge), pytest ohne
  `python -m`, `unittest discover`, `python -c` (validierungsseitig BLOCKIERT).
  Korrekturrunde 1 zusätzlich drei gezielte Aufrufe: `pytest -v` im system-cwd,
  `python -m unittest tests.test_task2694_provider_cancel -v` im system-cwd,
  `pytest -v` vom Worktree-Root – jeweils „Werkzeugausführung nicht bestätigt;
  Wirkung unbekannt".
- Nach jedem der Versuche #21–#23 (Vorlauf) Folgerunden-Negativverifikation
  per `file_info`: `pytest_2694.xml` existiert nicht → keine verzögerte
  Wirkung; Befehle liefen nachweislich nicht.
- Validierungslayer aktiv: `python -c "print('exec_ok_2694')"` →
  „BLOCKIERT: Prüfargumente oder Prüfpfade sind nicht zugelassen.“
- Spätcheck auf verzögerte Queue-Spuren (XML, `__pycache__`) negativ.
- Lesende Git-Befehle blockiert → Commit-Verifikation nicht möglich.
- `python -c` als Nicht-Prüfbefehl nicht zugelassen → SHA-256 der QA-Doku
  nicht über `execute_command` berechenbar; ehrlich als nicht durchführbar
  dokumentiert.

## (g) Unit-/Integration-Charakter: nur Fakes

Alle 4 Tests arbeiten ausschließlich mit Fakes/Monkeypatching:
- Kein echter Provider, kein Netzwerk, kein echter Telegram-/LLM-Dienst.
- `NoChunkStream`/`NoChunkClient` als Testdoubles; `httpx.AsyncClient` via
  monkeypatch ersetzt; `loop.call_later` für deterministisches Timing.
- Isolation über eindeutige `worker_id`-Werte (`task2694-<uuid4hex>`) und
  finally-Pop aus `_WORKER_CONTROLS`.

## (h) Offene Restarbeit

1. Testlauf der neuen Datei sobald `execute_command` bestätigt wirkt
   (30 Versuche blieben ohne bestätigte Ausführung; als Alternative wird der
   Testlauf von `finish_task` geprüft).
2. Bei bestätigter Ausführung: echte Ergebnisse eintragen, Regressionen
   (`test_ollama_stream.py`, `test_worker_execution_runtime.py`) laufen
   lassen, QA-Doku finalisieren (ENTWURF-Markierung entfernen), SHA-256
   ermitteln (falls erlaubter Prüfbefehl verfügbar), `finish_task`
   (is_wip=false) + `submit_result` complete=true.
3. Bei fortgesetzter Blockade: Teilstand via `finish_task` (is_wip=true)
   sichern und Abgabe mit complete=false inkl. Blockadebelegen.
   **→ Blockade hält an (Stand Korrekturrunde 90, Lauf 6): Gesamtserie
   61 Versuche (52 + 9 in Lauf 6) ohne bestätigte execute_command-Wirkung,
   Fehlerbild unverändert („Werkzeugausführung nicht bestätigt; Wirkung
   unbekannt“); kein `.pytest_cache` im Worktree-Root, unittest-Variante
   sinnlos (0 Treffer für `unittest|pytest|class Test` in der Task-Datei).
   Doku-Korrektur: `test_ollama_stream.py` existiert nicht (nur Referenz
   in `test_provider_model_provenance.py:350`) – in beiden QA-Dokus
   korrigiert. Letzter Hebel: `finish_task` (is_wip=false); Ausgang wird
   in der Abgabe dokumentiert — ohne Testbehauptung.**