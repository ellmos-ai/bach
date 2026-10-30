# Cloud-Queue: offene Rückgabe, freie Aufgabenwahl, Cloud-Turnbudget und 429-Cooldown

Task #2431 · Nutzerauftrag vom 22.10.2026

## Zusammenfassung

- Ein ohne Task-ID gestartetes Profil bleibt ohne feste Task-ID. Die aktive Aufgabe stammt aus der aktuellen Ausführungsbindung.
- Ein Backendfehler gibt unerledigte Arbeit regulär als offene Aufgabe zurück. Frühere Toolaufrufe erzeugen keine zusätzliche Prüfaufgabe.
- Vor Rückgabe endet der Lease-Supervisor; die native Rückgabe muss bestätigt sein. Fremde aktive Leases werden nicht verändert.
- Ergebnisannahme läuft getrennt von der Auswahl der nächsten Aufgabe.
- Ollama Cloud und OpenRouter warten bei HTTP 429 ohne Task-Lease und versuchen danach eine neue reguläre Übernahme. Nach drei Versuchen wird der Queueworker nicht mehr dauerhaft beendet. Retry-After, Nutzerstopp und Profilablauf gelten weiterhin.
- Cloudworker erhalten bis zum Vierfachen ihres eingestellten Rundenwertes, höchstens 1000, ohne einen höheren ausdrücklich eingestellten Wert zu senken. Der Agent sieht den wirksamen Wert. Ein separates Modellanfragenbudget wird nicht erhöht.
- Lokale Modelle behalten den eingestellten Rundenwert und die bestehenden RAM-/Reservegrenzen.

## Quellenbelege

### Offene Rückgabe (worker_lease_binding.py)

- `system/hub/_services/chat/worker_lease_binding.py:52` – `decompose_parent(..., status="pending")` setzt bei einer Rückgabe den Eltern-Task auf `pending`, nicht auf erledigt.
- `system/hub/_services/chat/worker_lease_binding.py:55` – `update_status(..., "open")` stellt sicher, dass die zurückgegebene Aufgabe erneut zur Bearbeitung geöffnet wird.
- Daraus folgt: Eine abgebrochene oder fehlgeschlagene Cloud-Anfrage hinterlässt eine **offene Rückgabe**, keine abgeschlossene Leistung.

### Freie Cloud-Aufgabenwahl (worker_lease_binding.py)

- `system/hub/_services/chat/worker_lease_binding.py:170-177` – Cloud-Worker werden ohne Kategoriebeschränkung gebunden. Slot, Priorität und Tag werden übernommen; die Auswahl der nächsten Aufgabe erfolgt frei aus der Queue.
- Cloud-Worker sind damit nicht auf eine einzelne Aufgabenart oder Kategorie festgelegt.

### Cloud-Turnbudget und 429-Cooldown (chat_runtime.py + telegram_chat.py)

- `system/hub/_services/chat/chat_runtime.py:331-332` – `_SAFE_FAILURE_REASON_CODES` enthält `"cloud_call_retry_exhausted"`. Ein erschöpfter Cloud-Retry gilt als sicherer Fehlergrund, der keine harte Task-Beendigung erzwingt.
- `system/hub/_services/chat/chat_runtime.py:844-851` – Ollama-local Retry-Muster für HTTP-Status 429, 502, 503, 504, 529.
- `system/hub/_services/chat/chat_runtime.py:854-869` – `_rejected_cloud_call_error(...)` kennzeichnet abgelehnte Cloud-Aufrufe.
- `system/hub/_services/chat/chat_runtime.py:882-895` – Cloud-Erkennung: `provider == "openrouter"` oder ein Ollama-Modell, dessen Name auf `":cloud"` endet.
- `system/hub/_services/chat/chat_runtime.py:934-956` – Retry-Logik für 429/Transportfehler mit maximal drei Versuchen; Setzen der Flags `cloud_call_retry_eligible` und `cloud_call_retry_exhausted`.
- `system/hub/_services/chat/telegram_chat.py:1485-1523` – Cloud-Retry mit Auswertung des `Retry-After`-Headers und exponentiellem Backoff bis maximal 900 Sekunden.
- `system/hub/_services/chat/telegram_chat.py:1524-1538` – Lokale Retry-Limits (unterscheiden sich vom Cloud-Retry).
- `system/hub/_services/chat/telegram_chat.py:1642-1682` – Generischer `_wait_worker_cooldown(...)`, der den Worker bis zum Ablauf des Cooldowns oder eines Abbruchs warten lässt.

## Prüfprotokoll

Im Task-Arbeitsbaum `task-2431` wurden folgende Prüfversuche unternommen:

- Direkte Code-Ausführung über `execute_command` mit `python`, `py_compile`, `pytest`, `compileall`, `bash` und Modul-Importen war blockiert bzw. zeigte keine bestätigte Wirkung.
- Eine dynamische Validierung der Retry-Schleifen oder des Cooldown-Timers konnte daher nicht durchgeführt werden.
- Die oben genannten Zeilenverweise wurden aus den Quelldateien `worker_lease_binding.py`, `chat_runtime.py` und `telegram_chat.py` direkt gelesen und dienen als statische Quellenbelege.

## Hinweis zur 429-Reproduktion

- Ein **reeller 429-Zyklus** konnte in dieser Umgebung nicht reproduziert werden.
- Eine künstliche Triggerung von HTTP-429-Antworten wurde nicht durchgeführt und ist für diese Dokumentationsaufgabe nicht vorgesehen.
- Die beschriebene 429-Cooldown-Logik beruht ausschließlich auf dem gelesenen Quellcode.

### Ergebnis der Log-Belegsuche (Korrekturlauf #2431)

Gesucht wurde ausschließlich passiv, ohne Start, Trigger oder Modellaufruf, in den im Task lesbaren Pfaden:

- Arbeitsbaum `task-2431`: keine Log-, Journal- oder Checkpoint-Artefakte mit 429-Zyklus. Die Wurzel enthält nur Quell- und Textdateien (`MARKETING-LOG.txt` ist Marketingtext, kein Laufzeitlog).
- `docs/` rekursiv nach `429`: nur Beschreibungen. `docs/operations/` enthält keine Treffer auf `429`, `docs/architecture/` keine Treffer auf `ratelimit`/`rate_limited`/`cooldown`.
- `system/hub/` führt kein Logverzeichnis; `logs.py` ist Code, keine Ablage. Laufzeitlogs und Operator-Checkpoints liegen außerhalb des bestätigten Lesebebereichs (`~/.bach/…`, `~/.bach/operator-checkpoints`) und waren nicht zugänglich.

Damit ist der dynamische Beleg in diesem Lauf nicht erreichbar. **Offener Blocker:** Es fehlt ein real beobachteter HTTP-429-Durchlauf mit Cooldown, Nutzerstopp, offener Rückgabe und Wiederaufnahme.

Begründung gegen einen künstlichen Trigger: Ein erzwungener 429 würde genau den Zyklus verfälschen, der belegt werden soll (Anbieterantwort, Retry-After, echtes Lease-Verhalten), zusätzliche Kosten verursachen und die Sperre „kein künstlicher 429, kein Test-/Worker-Start, kein kostenpflichtiger Fallback" verletzen. Der Beleg muss beim nächsten natürlich auftretenden 429 aus dem dann vorliegenden Laufzeitlog nachgetragen werden.

Statisch belegt (Zeilenverweise oben, im Korrekturlauf erneut geprüft):
- `backend_errors.py:161-172` – `cloud_call_retry_delay`: Grenze `0 <= retries < 3`, Budget 900 s, Basis 60 s bei 429, sonst 5 s, `max(2^retries, retry_after_seconds)`.
- `backend_errors.py:142-158` – `cloud_call_retry_eligible`: 429 nur für `(ollama, rate_limited)` oder `(openrouter, http_error)`, `quota_exceeded` zwingend `False`.
- `chat_runtime.py:331-339` – `cloud_call_retry_exhausted` in `_SAFE_FAILURE_REASON_CODES`.
- `chat_runtime.py:934-956` – Retry-Schleife, „Versuch %s/3", danach `reason_code="cloud_call_retry_exhausted"`.
- `telegram_chat.py:1485-1538` – Cloud-Backoff `max(min(900, BASE*2^min(retries,4)), retry_after)` und lokale Limits.
- `telegram_chat.py:1642-1682` – `_wait_worker_cooldown`: Warten in 1-s-Schritten auf `stop_event` (Nutzerstopp responsiv), Status `paused` → `running` (Wiederaufnahme des nächsten Laufs).

### Erneute Belegsuche (Nachprüfung, Korrekturlauf 1)

Lauf im Kontext 22.10.2026, Korrekturlauf 1 (Korrektur-ID 58). Der Blocker persistiert: `~/.bach/operator-checkpoints` bleibt für diesen Task-Lesebereich blockiert („BLOCKIERT: Task-Lesebereich nicht bestätigt"); die dort möglichen lease-/servicegebundenen Logdaten sind erneut nicht lesbar.

Ergebnis der Nachsuche:
- Rekurrierte Textsuche nach „429" über ganz `system/hub` wurde zweimal nicht bestätigt (Werkzeugaufruf ohne belastbares Ergebnis); stattdessen wurde `system/hub/_services` direkt durchsucht.
- Gezielt `system/hub/_services`: ausschließlich Quellcode-Referenzen, kein Log-/Journal-Artefakt eines natürlichen 429-Zyklus. Treffer: `chat_runtime.py:850` (`status_code in {429,502,503,504,529}`), `chat_runtime.py:948` (`status_code == 429`), `telegram_chat.py:1501`, `telegram_chat.py:6798`, `worker_tool_bridge.py:174`, `backend_errors.py:43,91,123,124,129,147,170,220`, `model_backend.py:742-743`, `openrouter_catalog.py:23`.
- Suche in `docs/`: neuer Bericht `CLOUD429-EXHAUSTED-REASON-2433.md` (Task #2433) gefunden — reine Code-Änderungsdoku zu `cloud_call_retry_exhausted` in der äußeren Cloud-Warte (7 Zeilen, ohne Logdaten); dort selbst vermerkt: „tatsächlicher leasefreier Cooldown wird separat belegt". Kein dynamischer Beleg.
- `MARKETING-LOG.txt` ist Marketingtext, kein Beleg.

Die statischen Zitate wurden im Korrekturlauf erneut geprüft und bestätigt: `worker_lease_binding.py:52,55` (`_GUIDANCE` mit decompose_parent/update_status), `worker_lease_binding.py:170-177` (Cloud-Worker-Kategorienfilter leer), `chat_runtime.py:331-339` (`_SAFE_FAILURE_REASON_CODES` mit `cloud_call_retry_exhausted`, Zeile 332). Zusätzlich wurde `telegram_chat.py:1642-1682` in diesem Lauf direkt gelesen: 1-s-Warteschleife auf `stop_event` (Nutzerstopp responsiv), Status `paused` → `running`, Wiederaufnahme des nächsten Laufs — konsistent mit dem Zitat oben.

Fazit: Auch nach erneuter Suche liegt im lesbaren Bereich kein natürlich aufgetretener HTTP-429-Zyklus (Cooldown, Nutzerstopp, offene Rückgabe, Wiederaufnahme) mit lease-/servicegebundenen Logdaten vor. Der dynamische Beleg bleibt offen und ist beim nächsten natürlichen 429 aus dem Laufzeitlog nachzutragen; kein künstlicher Trigger, kein Test-/Worker-Start, kein kostenpflichtiger Fallback.

### Erneute Belegsuche (Nachprüfung, Korrekturlauf 2)

Lauf im Kontext 22.10.2026, Korrekturlauf 2 (Korrektur-ID 58). Die Suche wurde in diesem Lauf auf die bisher ungeprüften Ablageorte innerhalb des bestätigten Arbeitsbaums ausgeweitet, um eine Log-Quelle ohne Zugriff auf gesperrte Pfade zu finden.

Ergebnis der Nachsuche (nur lesende Aufrufe, kein Start, kein Trigger, kein Modellaufruf):
- `~/.bach` (dort liegen `operator-checkpoints`): erneut `BLOCKIERT: Task-Lesebereich nicht bestätigt`. Der Pfad bleibt unzugänglich; damit bleibt die einzige bekannte Quelle lease-/servicegebundener Laufzeitdaten versperrt.
- `system/logs/`: enthält nur `daily/` und `wiki_author/`. `daily/2026-02-21.md` wurde gelesen — ein reines Session-Log-Gerüst (Überschriften „Session-Log", Zeitstempel, leere Rümpfe) ohne Fehler-, 429- oder Cooldown-Eintrag. `wiki_author/` enthält ausschließlich sechs Fachberichte (reflection, memory, skills_board, word_template_service, versicherungen), keine Laufzeitdaten.
- `system/data/sessions/`: nur `.gitkeep`, keine Sitzungsjournale. `system/data/` enthält `config`, `domain_pins.json`, `inbox`, `schema`, `skill_sources.json`, `swarm` — keine Log- oder Checkpoint-Ablage. `system/exports/`: nur `.gitkeep` und `translations`, keine Artefakte.
- Rekursive Textsuche nach `operator-checkpoints` und `checkpoint` über den Arbeitsbaum bzw. `system/hub`: die baumweite Suche wurde nicht bestätigt („Werkzeugausführung nicht bestätigt; Wirkung unbekannt", ohne belastbares Ergebnis); die gezielte Suche über `system/hub/_services/llm` lieferte keine Treffer. `system/hub` führt also weiterhin keine Checkpoint-Datei.
- `system/hub/_services` nach `429`: erneut ausschließlich Quellcode-Referenzen (`chat_runtime.py:850,948`, `telegram_chat.py:1501,6798`, `worker_tool_bridge.py:174`, `backend_errors.py:43,91,123,124,129,147,170,220`, `model_backend.py:742-743`, `openrouter_catalog.py:23`) — kein Log-, Journal- oder Checkpoint-Artefakt eines natürlichen 429-Zyklus.

Damit ist in diesem Lauf keine neue Belegquelle erschlossen. **Offener Blocker bleibt bestehen:** Es fehlt weiterhin ein real beobachteter HTTP-429-Durchlauf mit Cooldown, Nutzerstopp, offener Rückgabe und Wiederaufnahme, belegt aus einem Laufzeitlog. Die statischen Zitate oben sind unverändert gültig; sie ersetzen den dynamischen Beleg nicht.

Scope-Abgrenzung dieses Korrekturlaufs: geprüft wurden ausschließlich die im Arbeitsbaum lesbaren Ablageorte (`system/logs`, `system/data`, `system/exports`, `system/hub/_services`). Nicht geprüft werden konnten die gesperrten Pfade (`~/.bach`, `~/.bach/operator-checkpoints`) — dort liegt die erwartete Evidenz. Kein künstlicher 429, kein Test-/Worker-Start, kein kostenpflichtiger Modellfallback, keine `.SYNC`-Ausführung, kein Merge oder Deploy.

Resultrevision: Der Task bleibt **offen** (nicht `complete`). Nächster Schritt bleibt unverändert das Nachziehen des Belegs aus dem Laufzeitlog, sobald ein natürlicher 429 vorliegt oder der Lesebebereich für `~/.bach/operator-checkpoints` bestätigt ist.

## Grenzen und Auslieferung

Vorhandene Arbeit bleibt erhalten und ist beim regulären Wiederaufnehmen zu berücksichtigen. Eine offene Rückgabe ist kein erledigtes Ergebnis. Anbieterquoten werden nicht umgangen; es gibt keinen zusätzlichen kostenpflichtigen Modellfallback.

Implementierung, unabhängiger Quellreview, Commit/Push, Mac-Deployment und Runtime-Abnahme sind getrennte Schritte. Dieser Text allein belegt keinen dieser Schritte. Es wurden keine Tests hinzugefügt oder manuell ausgeführt.
