# Beweisnotiz: Chat-Timeout, Concurrency, Python-PATH und Task-Assignee-Analyse

**Datum:** 2026-09-07  
**Host:** Mac Studio (`mac-studio`, M1 Max 32 GB)  
**Bearbeiter:** Gemini / Antigravity  
**Referenz-Ticket / Vorfall:** GUI-Chat `Backend-Fehler: ReadTimeout` bei Modell `qwen3.8:27b-mlx`

---

## 1. Ausgangslage & Befund

Der Nutzer stellte im Web-Chat der BACH-GUI (`http://localhost:8000/chat`, API-Backend auf Port 8081 `/api/chat`) folgende Probleme fest:
1. Nach Starten von Wartungsaufgaben (`maintain(run)`) und anschließenden Chat-Eingaben erschien mehrfach:
   `Backend-Fehler: ReadTimeout`
2. Buddha meldete, dass `python` fehle und legte um 16:45 Uhr einen Symlink an:
   `/opt/homebrew/bin/python -> python3`
3. Die Frage des Nutzers:
   *„Laufen die Wartungsaufgaben automatisch im Hintergrund? Also werden BACH-Tasks erledigt?“*
   konnte vom Chatbot nicht mehr beantwortet werden, da Folge-Prompts sofort mit `ReadTimeout` abbrachen.

---

## 2. Ursachenanalyse (Logs & Messungen)

### A. Prompt-Evaluation (97 s) vs. 120-Sekunden-Timeout
- **Modell:** `qwen3.8:27b-mlx` (18,2 GB NVFP4 Safetensors).
- **Prompt-Größe:** System-Prompt (~9.700 Chars) + 23 Tools `TOOLS_FULL` (~9.300 Chars) + Session-Historie + Memory-Kontext = **7.770 Tokens**.
- **Ollama-Log-Auszug (`/tmp/ollama-user.log`):**
  ```text
  time=2026-09-07T17:28:23 level=INFO msg="Prompt processing progress" processed=6144 total=7771
  time=2026-09-07T17:28:42 level=INFO msg="ServeHTTP method=POST path=/v1/completions took=1m36.8878295s"
  [GIN] 2026/09/07 - 17:28:42 | 500 | 2m0s | POST "/api/chat"
  ```
- **Mechanismus:**
  Die GPU-Prompt-Evaluierung für 7.770 Tokens benötigt auf dem M1 Max ca. **97 Sekunden**.
  Währenddessen sendet Ollama keine Streaming-Chunks.
  Anschließend generiert das Modell Denk-Token (`think: True`).
  In `hub/_services/limits.py` stand `BACH_LLM_IDLE_TIMEOUT` auf dem Default **120 Sekunden**.
  In `model_backend.py` riss `httpx.Timeout(read=float(idle))` nach exakt 120 Sekunden Inaktivität die Verbindung ab.
  Ollama brach den MLX-Runner ab (`stopping mlx runner subprocess`), lieferte HTTP 500 und die Chat-Runtime gab `Backend-Fehler: ReadTimeout` aus.
  Jede Folgefrage schickte denselben großen Kontext erneut und lief reproduzierbar wieder nach 120s in den Timeout.

### B. Fehlende Serialisierung / Race Condition bei parallelen Chat-Nachrichten
- Die GUI (`chat.html`) und `telegram_chat.py` bedienen Anfragen über den `QuietHTTPServer(ThreadingHTTPServer)` auf Port 8081.
- Wenn eine Anfrage rechnete und eine zweite abgeschickt wurde (oder nach einem Timeout der Sendebutton wieder frei wurde), liefen zwei Threads parallel in `runtime.process()` für dieselbe Session (`gui-web`).
- Beide konkurrierten in Ollamas sequentieller Queue (`OLLAMA_NUM_PARALLEL=1`), was dazu führte, dass die wartende Anfrage in der Queue verhungerte und `ReadTimeout` meldete, während die erste Anfrage zeitversetzt ihr Ergebnis lieferte.

### C. Automatische Task-Abarbeitung (`assigned_to`)
- Die Wartungs-Tasks (1125, 1134, 1135, 1136, 1137) standen auf `assigned_to = 'user'`.
- Der Scheduler-Daemon war gestoppt (`Status: [STOPPED]`).
- Der Idle-Worker in `chat_tray.py` prüfte ausschließlich:
  `for assignee in ("OLLAMA", "BUDDHA"):`
- **Ergebnis:** Tasks mit `assigned_to = 'bach'` wurden bisher weder vom Scheduler noch vom Idle-Worker abgearbeitet.

### D. Python-Umfeld
- Der von Buddha angelegte Symlink `/opt/homebrew/bin/python -> python3` zeigte auf **Python 3.14.7** (Homebrew global).
- Die BACH-Installation und alle Abhängigkeiten (`httpx` etc.) liegen jedoch in der Virtualenv `/Users/lukas/.venvs/bach/` (**Python 3.12.13**).
- Die LaunchAgents hatten `/Users/lukas/.venvs/bach/bin` nicht im `PATH`, sodass Subprozesse im unvollständigen globalen Python 3.14 landeten.

---

## 3. Durchgeführte Behebungen

1. **Timeout-Verlängerung auf 300 s:**
   - `hub/_services/limits.py`:
     * `BACH_LLM_TIMEOUT`: von 180 auf **300 s** gesetzt.
     * `BACH_LLM_IDLE_TIMEOUT`: von 120 auf **300 s** gesetzt.
   - `~/Library/LaunchAgents/com.bach.telegram-bot.plist`:
     * Environment-Variable `BACH_LLM_IDLE_TIMEOUT` = `300` hinterlegt.
   - `hub/_services/chat/chat_tray.py`:
     * Timeout für `tray-prompt` auf `300` gesetzt.

2. **Per-Chat Request-Locking in `telegram_chat.py`:**
   - `_chat_locks` mit `threading.Lock` je `chat_id` implementiert.
   - Parallele Anfragen an `/api/chat` und `_answer_order` für dieselbe Session warten geordnet (bis zu 300 s) statt simultan in Ollama zu kollidieren.

3. **Task-Assignee `BACH` im Idle-Worker aktiviert:**
   - In `hub/_services/chat/chat_tray.py`:
     ```python
     for assignee in ("OLLAMA", "BUDDHA", "BACH"):
     ```
     Damit erfasst der Idle-Worker nun auch Tasks, die auf `assigned_to = 'bach'` oder `'BACH'` gesetzt sind, sobald das System im Leerlauf ist.

4. **Virtualenv im LaunchAgent-PATH verankert:**
   - In `com.bach.telegram-bot.plist` und `com.bach.chat-tray.plist`:
     `PATH` erweitert auf `/Users/lukas/.venvs/bach/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin`.
   - Dadurch nutzen alle aufgerufenen Skripte garantiert die Python-3.12-Virtualenv mit allen installierten Bibliotheken.

5. **Bereinigung der Chathistorie:**
   - In der SQLite-Datenbank (`~/.bach/bach.db`, Tabelle `session_snapshots`, ID 489) wurden die fehlgeschlagenen `Backend-Fehler: ReadTimeout`-Abschlüsse am Ende entfernt.
   - Der Chatverlauf ist sauber bis zur letzten erfolgreichen Buddha-Antwort (#11).

6. **Dienste neu gestartet:**
   - `com.bach.telegram-bot` und `com.bach.chat-tray` via `launchctl kickstart -k` neu geladen.

---

## 4. Verifikation

- **Automatisierte Tests:**
  `pytest tests/test_chat_runtime.py tests/test_chat_runtime_task_manage.py tests/test_chat_session_store.py`
  -> **124 von 124 Tests bestanden (100% grün)** in 0.15 s.
- **Service-Health:**
  `curl http://localhost:8081/api/status` -> HTTP 200, Backend `OllamaBackend`, Modell `qwen3.8:27b-mlx`, Health OK.
- **History-Readback:**
  `curl http://localhost:8081/api/history?chat_id=gui-web` -> Liefert die saubere Historie ohne fehlerhafte Timeout-Meldungen zurück.
