# Lokaler Worker-Harness (Buddha / Ollama)

Stand 25.10.2026. Dieses Dokument beschreibt, wie BACH Aufgaben an ein lokales Modell (Buddha, `qwen3.8:27b-mlx` über Ollama auf dem Mac Studio) gibt, was dabei schiefgehen kann und **warum** die heutigen Einstellungen so gewählt sind. Es ist der Kern des lokalen Harnesses; Änderungen daran bitte hier nachtragen (Ist und Begründung).

Bauort heute: BACH-Kern (`system/hub/_services/chat/…`, `system/hub/_services/task_*`), Ausnahme nach MODUL-ZUORDNUNG. Ziel: Herauslösung als Modul `ellmos-worker` (Task #2493); das Dokument zieht dann mit.

## 1. Bausteine

| Baustein | Datei | Aufgabe |
|---|---|---|
| Task-Datenbank und Leases | `hub/_services/task_lease.py`, `task_lease_client.py` | Task übernehmen (`acquire`, Fence, TTL-Profil M), erneuern (`renew`), abgeben (`submit_result`), zurückgeben (`release outcome=return/blocked/review`) |
| Worker-Controller | `hub/_services/chat/telegram_chat.py` (`_start_worker_execution`, Arbeitsschleife) | Startet und überwacht Worker-Läufe, wählt Tasks, behandelt Fehler, gibt Leases zurück |
| Lease-Bindung | `hub/_services/chat/worker_lease_binding.py` | Bindet einen Lauf an genau eine Task; prüft jede `task_manage`-Aktion des Modells |
| Werkzeugschleife | `hub/_services/chat/chat_runtime.py` (`_tool_loop`) | Modellrunden, Werkzeugaufrufe, Kontextübergabe, Abschlussreserve |
| Werkzeuge | `hub/_services/chat/bach_tools.py` (`TOOLS_FULL`, 28 Werkzeuge) | Schemata und Ausführung; im gebundenen Lauf nur die freigegebenen |
| Schreibwache | `hub/_services/chat/worker_write_guard.py`, `hub/worker_git.py` | Task-Arbeitsbaum unter `~/services/bach-worktrees/task-<id>`, Schreiben nur dort, Sperrprüfung |
| Ergebnis und Review | `hub/_services/task_result_service.py`, `worker_result_review.py` | Ergebnisprüfung (höchstens 3000 Zeichen), Review-Absichten und Review-Tasks |
| Slot-Konfiguration | Standard `system/data/slots_config.json`, überschreibbar mit `BACH_SLOTS_CONFIG_PATH` (auf dem Mac Studio `~/.bach/chat/slots_config.json`) | Modell, Modus, Werkzeuge, Pickup-Filter je Worker |

Achtung, gilt für diese Installation (Mac Studio): Die LaunchAgents `com.bach.telegram-bot`, `com.bach.gui-server` und `com.bach.chat-tray` setzen `BACH_SLOTS_CONFIG_PATH=~/.bach/chat/slots_config.json`. Die Live-Konfiguration steht dort, nicht in `system/data/slots_config.json` des Repos. Ohne die Variable liest BACH den Quell-Standard `system/data/slots_config.json` (`slots_config.DEFAULT_SLOTS_FILE`).

## 2. Ablauf eines Laufs

1. **Auswahl:** höchste Priorität zuerst, innerhalb davon die höchste Task-ID. Explizit zugewiesene Tasks (`assigned_slot`) gehen nur an diesen Slot. `assigned_to` muss ein bekannter Bearbeiter sein (`bach`, `buddha`, `ollama` oder die Slot-ID), sonst wird die Task abgelehnt (`ownership`). Eine Abhängigkeit (`depends_on`) gilt erst bei Status **done** als erfüllt, nicht bei review.
2. **Arbeitsbaum:** `_prepare_bound_task_scope` legt den Task-Arbeitsbaum an. Mit Schreibwerkzeugen braucht er eine öffentliche Quellbindung: lokales `main` muss dem öffentlichen `main` auf GitHub entsprechen. Vorher prüft die Schreibwache alle Sperren (`_fresh_locks`).
3. **Modellrunden:** höchstens `max_tool_rounds` (25). Bei etwa 80 % des Kontextfensters folgt eine **Kontextübergabe**: Das Modell schreibt einen Übergabezettel, der Verlauf wird ersetzt. In den letzten zwei Runden gilt die **Abschlussreserve**: nur noch abschließende Werkzeuge; ist der Kontext dort voll, scheitert der Lauf ohne Werkzeugwirkung.
4. **Abschluss**, eine von drei Formen:
   - `submit_result` (Text, höchstens 3000 Zeichen) → Task review, natives Ergebnis mit `result_id`.
   - `finish_task` (Tests, Commit, Push, PR) → Task review mit PR-Verweis, **ohne** `result_id`.
   - Teilstand: `task_manage` mit `{"action": "submit_result", "task_id": <ID>, "result": "<konkrete Teilergebnisse und Restarbeit>", "complete": false}` (Alias: `update` mit `status="done"` und `complete=false`) → Teilstand wird an die Beschreibung gehängt, Task zurück auf pending. Ein reines `update` mit `complete=false` gibt keinen Teilstand ab: es wird abgewiesen, die Bindung bleibt aktiv.
5. **Rückgabe:** Jede Rückgabe trägt einen festen Grundcode (Abschnitt 4).

## 3. Buddhas Einstellungen und warum

| Einstellung | Wert | Begründung |
|---|---|---|
| Modell | `qwen3.8:27b-mlx`, lokal | Kostenfrei, 24/7; Cloud-Kontingent (Ollama Cloud `glm-5.3:cloud`) ist für Oktober erschöpft, Cloud-Worker ruht bis 1.11. (Task #2503) |
| Kontextfenster | 16 384 Token | Das Modell belegt damit 27 von 32 GB; ein größeres Fenster braucht zusätzlichen Speicher für den KV-Cache und ist ohne Messung nicht ratsam |
| Kontextübergabe | bei etwa 80 % (gemessen 12 300–14 400 Token) | Rechtzeitig vor Abschneiden; Ausreißer bis 16 782 Token entstehen, wenn ein einzelnes Werkzeugergebnis sehr groß ist |
| Modus | `full` | Nutzerentscheidung: Buddha erstellt Dateiergebnisse, darf pushen und PRs anlegen (Review „erstmal jeder“ auf GitHub) |
| Werkzeuge (`allowed_tools`) | Stufentest, Stufe 2: 11 Werkzeuge (Task-Worker-Profil) | Siehe Abschnitt 5 |
| Pickup-Filter | aktiv, schließt Tags `delegated` und `waiting` aus | So lassen sich Tasks gezielt zurückhalten |

## 4. Rückmeldungen an Buddha und Rückgabegründe (warum es sie gibt)

Ausgangsbefund 24./25.10.: 98,7 % aller Rückgaben ohne Ergebnis, 76 % in unter einer Minute; jede Rückgabe hatte `note: ""`. Niemand konnte sehen, warum.

**Rückgabegründe (fester Wortschatz, nie Anbietertext)** — PR #510, #513, live seit 25.10.:

| Grund | Bedeutung |
|---|---|
| `backend_error:<anbieter>:<art>[:<status>]` | Anbieterfehler, z. B. `backend_error:ollama:quota_exceeded:429` |
| `model_failure:<code>` | Fehler im Lauf, z. B. `model_failure:completion_reserve_context_exhausted` |
| `task_scope_unavailable` | Task-Arbeitsbaum nicht bestätigt (oft eine Sperre, Abschnitt 7) |
| `worker_returned_open` / `worker_blocked` | Das Modell gibt selbst zurück (Teilstand) bzw. blockiert |
| `worker_stopped` / `worker_ended` | Worker wurde gestoppt bzw. endete |

**Weiterarbeiten nach Task-Fehler** (PR #510): Ein Fehler, der nur diesen Lauf betrifft (kein Anbieterfehler, z. B. „Kontextfenster in der Abschlussreserve erschöpft“ oder ein unlesbarer Werkzeugaufruf), wird protokolliert; die Task geht mit Grund zurück und wird für diesen Lauf zurückgestellt, Buddha nimmt die nächste. Nach **drei** solchen Fehlern in Folge hält er an. Warum: Vorher beendete ein einzelner Fehler den Worker, er blieb auf `error` und startete nach einem Neustart nicht wieder. Warum die Grenze drei: Ein systematischer Fehler soll nicht die ganze Warteschlange leer zurückgeben.

**Monatskontingent erkennen** (PR #510): Ollama Cloud meldet „you (…) have reached your monthly usage limit“. Erkannt wurde nur „monthly usage limit reached“; deshalb lief das Kontingent als kurzzeitiges Rate-Limit mit Neuversuchen alle 60–900 s. Jetzt `quota_exceeded`.

**Prüfgrund bei abgelehnter Abgabe** (PR #510): Das Modell bekam nur „Taskergebnis ist ungültig.“ und gab auf. Jetzt werden die zwei festen öffentlichen Gründe genannt (Längengrenze, reine Erledigungsmeldung); alles andere bleibt neutral (Vertrag #379).

**Klare Hinweise statt `lease_protocol`** (PR #518): `task_manage detail` auf eine fremde Task wird weiter abgelehnt (der gebundene Lauf sieht nur seine Task), aber mit dem Hinweis `detail_scope`. `decompose` lehnt unbekannte `assigned_to`-Werte ab (`decompose_assignee`); vorher entstanden Kind-Tasks mit `help-inventory`, die niemand übernehmen konnte.

## 5. Werkzeuge und Kontext

Gemessen mit Buddhas Tokenizer (Prompt-Token nur für die Werkzeugbeschreibungen):

| Satz | Werkzeuge | Token |
|---|---|---|
| nur lesen (`read_file`, `search_text`, `task_manage`) | 3 | 1 391 |
| Stufe 1: + `list_directory`, `write_file`, `edit_file`, `create_directory` | 7 | 1 783 |
| Stufe 2: Task-Worker-Profil (+ `start_task_worktree`, `file_info`, `execute_command`, `finish_task`) | 11 | 2 225 |
| alle | 28 | 4 256 |

Verlauf: Bis 20.10. hatte Buddha alle Werkzeuge. Danach stand er auf genau den drei Lesewerkzeugen. Diese Kombination schaltet das seitenweise Lesen (`ellmos.read-evidence.v1`, höchstens 200 Zeilen/4000 Zeichen je Seite) frei, verhinderte aber jedes Dateiergebnis. Nutzerentscheidungen 25.10.: Dateiergebnisse, Push und PR erlaubt, Stufentest 7 → 11 → 28; Toolsets werden eine Einstellung mit Standardsatz und eingeschränkten Sätzen je Nutzer (Task #2510). Kleiner Kernsatz plus Werkzeuggruppen nach Bedarf: Nutzerfreigabe 25.10., umgesetzt (siehe unten), Rollout nach Review.

**Kernsatz plus Werkzeuge nach Bedarf** (PR „feat/tool-groups-on-demand“):

- Ist: Steht das Meta-Werkzeug `request_tools` in den `allowed_tools` eines gebundenen Workers, bekommt er zuerst nur den Kernsatz `task_manage`, `read_file`, `search_text`, `list_directory` und `request_tools(group)`. Dessen Beschreibung nennt je Gruppe eine Zeile mit den Werkzeugen, die der Slot tatsächlich hat. Eine angeforderte Gruppe kommt ab der nächsten Modellrunde dazu (die Laufzeit baut die Werkzeugliste ohnehin je Anfrage neu, `_bound_worker_tools_for_request`); sind alle Gruppen offen, verschwindet `request_tools`. Ohne `request_tools` in `allowed_tools` ändert sich nichts.
- Gruppen (`TOOL_GROUPS` in `bach_tools.py`): `dateien` (write_file, edit_file, create_directory, file_info, move_file, copy_file, recycle), `lieferung` (start_task_worktree, finish_task), `ausfuehren` (execute_command, safe_shell), `web` (web_search, web_fetch), `system` (system_status, ollama_info, get_datetime, bach_command, maintain, weather, foerderbericht), `skills` (skill_create, agent_manage). Werkzeuge ohne Gruppe bleiben immer sichtbar, damit ein neues Werkzeug nicht still verschwindet.
- Obergrenze: Gruppen öffnen nur, was `allowed_tools` und Modus schon freigeben; eine Gruppe ohne freigegebenes Werkzeug wird nicht angeboten und auf Anfrage abgelehnt (`tool_not_authorized`). Die Abschlussreserve, die Review-Einengung, die Task-Lesebindung (hängt an `start_task_worktree` in `allowed_tools`, nicht an der sichtbaren Liste) und die Arbeitsbaum-Vorbereitung bleiben unverändert. Die Gruppenwahl gilt je Lauf und beginnt bei jedem Lauf leer. Ruft das Modell ein freigegebenes, aber noch nicht angebotenes Werkzeug direkt auf, läuft es wie bisher: Die Rechtegrenze ist `allowed_tools`, die sichtbare Liste spart nur Kontext.
- Einschalten: `request_tools` in die `allowed_tools` des Slots aufnehmen (die Slot-Prüfung kennt den Namen jetzt). Warum über die Werkzeugliste statt eines neuen Slot-Felds: kein neues Konfigurationsfeld durch API und Oberfläche, und das Toolset des Nutzers bleibt die eine Stelle für Werkzeugrechte.
- Kosten (geschätzt aus einer linearen Anpassung an die vier gemessenen Werte oben, Abweichung höchstens 4 Token; nicht mit dem Tokenizer gemessen): Kernsatz mit `request_tools` etwa 1 616 Token statt 2 225 für Buddhas 11 Werkzeuge, also etwa 600 weniger je Anfrage; nach `dateien` etwa 1 971, nach `dateien` und `lieferung` etwa 2 191; alle Gruppen offen wie heute 2 225. `request_tools` selbst kostet etwa 130 Token.
- Warum: Ein Lauf, der vor allem liest und mit Text endet, spart den größten Teil; ein Lauf mit Datei und PR braucht eine Werkzeugrunde mehr (oder ruft `request_tools` in einer Runde neben einem Lesezugriff auf). Erfolg messen: Prompt-Token der ersten Runden, Übergaben je Lauf und ob Buddha die Gruppen rechtzeitig anfordert.

Werkzeuge ändern: Für `buddha_always_on` nur über `PUT /api/system/core-agents/buddha_always_on` (Kern-Agent; der allgemeine Worker-Konfigurationsweg erlaubt dort nur `persistent_opt_in`). Achtung: Wer von Lesen auf Schreiben wechselt, muss vorhandene, nur lesend angelegte Task-Arbeitsbäume ohne öffentliche Quellregistrierung entfernen, sonst scheitert ihre Wiederaufnahme (Task #2510 Punkt 4).

**Lesen mit Schreibwerkzeugen: normales `read_file`, kein v1** (Entscheidung 25.10., im Sinn des Nutzerziels „weniger Kontext“):

- Das normale `read_file` liest bereits seitenweise: höchstens 200 physische Zeilen und 4000 Zeichen je Aufruf, mit Kopfzeile (`Physische Zeilen a–b von n`) und Fortsetzung über `offset`. Das versionierte `ellmos.read-evidence.v1` bleibt auf das exakte Leseprofil (`read_file`, `search_text`, `task_manage`) beschränkt; sein tatsächlicher Produktionsstand (gepinnt, installiert, echte Seiten 18.–24.10., keine dokumentierte Abnahme) steht als Korrektur in `worker-read-evidence.md`, Abschnitt „Release boundary“.
- Warum nicht v1 für Schreibprofile (Messung 25.10. auf sechs Repo-Dateien, gleiche Grenzen 200 Zeilen/4000 Zeichen): v1 zeigt 2,4-mal weniger Zeilen je Aufruf bei etwa doppelten Zeichen für dieselbe Datei, z. B. `chat_runtime.py` 139 statt 57 Aufrufe, 445 000 statt 226 000 Zeichen; `bach_tools.py` 109 statt 45; `task_lease.py` 43 statt 17. Ursache ist der JSON-Aufwand von etwa 55 Zeichen je Zeile im selben 4000-Zeichen-Budget. Weil das exakte Profil die normale Ausgabe sperrt (`versioned_format_required`), müsste Buddha sonst nur v1 lesen: mehr Leseaufrufe bei höchstens 25 Runden und schneller voller Kontext. Dazu liefert v1 den Text JSON-escaped (`\"`, `\\`), ein Risiko für den exakten `old_string` von `edit_file`. Messskript auf dem Mac: `~/compute/harness-kontext-measure/measure_pages.py`.
- Stattdessen: größere Standardseite für gebundene Task-Leser (200 statt 50 Zeilen ohne `lines`), eigener PR „feat/task-read-default-200“, Rollout nach Review.
- Ist: Gebundene Task-Leser (Task-Lesebindung aktiv, `_task_code_reader_enabled`) lesen ohne `lines` 200 statt 50 Zeilen; die Ausgabe bleibt bei 4000 Zeichen gedeckelt. Andere Aufrufer behalten 50. Messung (normales `read_file`, ganze Datei): `chat_runtime.py` 55 statt 71 Aufrufe, `bach_tools.py` 45 statt 56, `task_lease.py` 17 statt 23, bei praktisch gleichen Zeichen; kurze Dateien unverändert. Wie oft Buddha `lines` weglässt, ist nicht gemessen (die Sitzungsabzüge enthalten keine Werkzeugargumente). Messskript: `~/compute/harness-kontext-measure/measure_default.py`.

## 6. Was Buddha mit 16k Kontext schafft (Messung 25.10., 05:12–11:28)

16 Läufe, 299 Minuten, 237 Modellrunden, 18 Kontextübergaben.

- Abgeschlossen: Übersetzung eines Hilfethemas (6–12 min, 0–1 Übergabe, PR), Hilfe-Inventar für einen Buchstabenblock (32 min, 2 Übergaben, `result_id` 330).
- Nicht abgeschlossen: große Plan- und Codeaufgaben mit 2–5 Übergaben; Buddha zerlegt dann weiter oder gibt einen Teilstand zurück.
- Nach jeder Übergabe liest er neu: bei #2505 37 von 53 Werkzeugaufrufen `read_file`.

**Übergabezettel mit Lesespur** (Nutzerfreigabe 25.10., PR „feat/handoff-read-trail“, Rollout nach Review):

- Ist: Die Werkzeugschleife führt je Lauf eine Lesespur (`_ReadTrail` in `chat_runtime.py`). Nach jeder Kontextübergabe (alle drei Wege: angefordert, vor der Abschlussreserve, Kontext voll) hängt `_resume_handoff_context` sie als eigene Nachricht hinter den Zettel: je Datei die tatsächlich gezeigten Zeilenbereiche (zusammengeführt, z. B. `Zeilen 1–260`), je Suche Muster, Pfad, Trefferzahl und bis zu drei Fundstellen `datei:zeile`. Nie Dateiinhalt.
- Grenzen: höchstens 40 Einträge mit zusammen höchstens 2400 Zeichen, die ältesten fallen zuerst weg; mit Kopf- und Schlusszeile höchstens etwa 900 Token (geschätzt mit Zeichen/3, nicht gemessen). Die Spur überlebt mehrere Übergaben; die alte Spur wird ersetzt, nicht verdoppelt.
- Was zählt: nur Aufrufe mit Inhalt. Abgelehnte (`ToolErrorText`, z. B. Secrets-Pfad), unbestätigte, fehlerhafte und `read-evidence`-unavailable-Antworten werden nicht als gelesen geführt. Geführt werden nur vollständig gezeigte Zeilen: aus den Zeilennummern der nummerierten Antwort, bei einer Kürzung auf 4000 Zeichen nur bis vor die genannte Fortsetzungszeile (`Weiterlesen mit offset=`); bei einer v1-Seite nur Zeilen mit `char_offset` 0 und `line_complete`. Rohausgabe ohne Zeilennummern (`line_numbers=false`, ungebundene Aufrufe) wird nicht geführt, weil sie bei Dateiende oder Kürzung nicht belegt, welche Zeilen vollständig kamen. Die Identität eines Eintrags ist der volle Pfad bzw. das volle Muster; gekürzt wird erst in der Anzeige, lange Pfade mit Prüfsummenkürzel (`…<Ende> #<sha256-Präfix>`), damit verschiedene Dateien unterscheidbar bleiben (Zweitprüfung 25.10.).
- Fakten: Der Zettel-Prompt (`HANDOFF_PROMPT`) hat eine neue Zeile `FAKTEN:` (Befunde mit Datei:Zeile, die nicht erneut nachzulesen sind) und den Hinweis, dass BACH die gelesenen Bereiche selbst anhängt. Warum: Welche Schlüsse gezogen wurden, weiß nur das Modell; welche Bereiche gelesen wurden, weiß die Laufzeit verlässlicher als das Modell.
- Warum: Nach Übergaben las Buddha neu (#2505: 37 von 53 Aufrufen `read_file`); eine Seite kostet bis zu 4000 Zeichen (etwa 1300 Token), die Spur höchstens etwa 900; eine vermiedene Neulesung zahlt sie also schon. Erfolg messen: Anteil `read_file` nach Übergaben und Übergaben je Abschluss in den nächsten Buddha-Läufen.

**Regel daraus:** Aufgaben für Buddha so schneiden, dass sie mit höchstens zwei Kontextübergaben auskommen, innerhalb des eigenen Task-Arbeitsbaums lösbar sind und mit einem Text (höchstens 3000 Zeichen) oder einer Datei plus PR enden. Gebundene Worker sehen nur ihre eigene Task und ihren Arbeitsbaum; Inventuren über das System oder Statistiken über andere Tasks sind für sie nicht lösbar.

Nächste Verbesserungen (nach Nutzen): Übergabezettel mit gelesenen Pfaden/Zeilen und festgestellten Fakten; größere Standardseite für Task-Leser statt v1 mit Schreibwerkzeugen (Abschnitt 5); schlanker Kernsatz; größeres Fenster nur nach Speichermessung.

## 7. Sperren (Locks) und warum sie Buddha stilllegen können

Der Mac-Scanner (`BACH_LOCK_SCAN`) prüft das Live-Repo samt OneDrive-Zwilling und Vorfahren, wertet aber `scope`/`protected_paths` nicht aus. **Jede** Sperre auf `.TOPICS/.AI/.OS/BACH` oder darüber sperrt damit das ganze Repo: Die Schreibwache verweigert jeden Task-Arbeitsbaum, Buddha gibt alles mit `task_scope_unavailable` zurück, Rollouts brechen ab. Belege 25.10.: eigene Sperre 05:00, fremde `LOCK.templates-health.txt` 11:03. Bis zur Behebung (Task #2537): keine Sperren auf dem BACH-Zwilling setzen, wenn Buddha laufen soll; Arbeit in eigenen Worktrees braucht dort keine.

## 8. Review und Abnahme

- Nutzerentscheidungen 25.10.: Reviews werden verzahnt mit neuer Arbeit geholt (PR #519); Aufgaben mit GitHub-PR werden auf GitHub reviewt, Merge = Abnahme (#2453); Reviewweg für Text-Ergebnisse = Ergebnistext gegen die Ausgabeanforderungen der Task (in Arbeit); reviewen und mergen darf jeder frische Lauf, außer eine Nutzerregel schränkt es ein.
- Befund: Bis 25.10. gab es nur eine Review-Absicht, weil native Reviews Scope-Belege aus dem Git-Arbeitsbaum verlangen, die Text-Ergebnisse nie haben (#2454). Folge: 193 Tasks in review, und Zerlegungsketten bleiben stehen, weil Abhängigkeiten erst mit done erfüllt sind.
- Ergebnislänge 3000 Zeichen: eingeführt am 9.10. (Commit `f284c41b`), ohne dokumentierte Begründung; vermutlich knappe Zusammenfassung für Abnahme und Review-Prompt kleiner Modelle. Längere Ergebnisse als Datei mit Verweis.

## 9. Betrieb

- **Start/Stopp:** `POST /api/system/workers/<id>/start|stop` (GUI-Weg mit Geräte-Token). Pausieren ist für Always-On nicht vorgesehen; nach einem Dienst-Neustart lässt die Startprüfung Always-On nur wieder zu, wenn der Slot nicht auf `error` steht.
- **Rollout auf den Mac:** laufend nach Prüfung durch die zweite Instanz (Nutzerentscheidung 25.10.). Ablauf: Lock-Scan (bei Sperre Abbruch), Drift-Prüfung gegen den erwarteten Ausgangsstand, Sicherung nach `~/.local/state/ocean-task-work/deploy-<zeit>`, Dateien aus dem Commit einsetzen und per Hash prüfen, kompilieren, drei Dienste neu starten, Readback.
- **Nachweis:** Rückgabegründe in `task_history` (`lease_release`, Feld `note`); Ergebnis und Review-Stand über `task_result_snapshot`.

## 10. Offene Aufgaben

#2453 (Abschluss beim PR-Merge), #2454 (Review-Rückstau, Textweg), #2493 (Modul `ellmos-worker`), #2510 (Toolsets), #2518 (Rest: Server-Ablehnung bei decompose beendet die Bindung), #2537 (Lock-Scanner-Scope), #2503 (Cloud-Worker ab 1.11.).
