# Modell-Backend und dessen Verwaltung — das neue Herz von BACH

**Programmkopf, Phase 1: Bestandsaufnahme und Architekturkonzept**
Stand: 13.09.2026 · Gemessen gegen `origin/main`, Commit `1bb8fa4` · Ticket `T-20260913-896336887`

> **Auftrag des Nutzers (Originalwortlaut, maßgeblich, 13.09.2026):**
> „wichtigste Neuerung in Bach ist aktuell Modell backend und dessen verwaltung. Das wird das
> neue Herz von Bach. Sprich bach wird lebendig, wer spielt wann welche der Rollen und Agenten usw."

Dieses Dokument beantwortet Phase 1: Was ist heute da, was fehlt, und wie sähe die Anlage aus,
die „wer spielt wann welche Rolle" beantwortbar macht. **Es wird nichts umgebaut.** Der
Umbau folgt in Folgetickets, die am Programmkopf in `ROADMAP.md` andocken.

---

## Inhalt

1. [Messgrundlage](#1-messgrundlage)
2. [Bestandsaufnahme](#2-bestandsaufnahme)
3. [Der Befund in fünf Sätzen](#3-der-befund-in-fünf-sätzen)
4. [Architekturskizze: lebendiges BACH](#4-architekturskizze-lebendiges-bach)
5. [Einordnung der vorhandenen Bausteine](#5-einordnung-der-vorhandenen-bausteine)
6. [Zweitmeinung](#6-zweitmeinung)
7. [Offene Entscheidungen](#7-offene-entscheidungen)
8. [Reihenfolge und Folgetickets](#8-reihenfolge-und-folgetickets)

---

## 1. Messgrundlage

Alle Zeilenangaben beziehen sich auf einen Worktree von `origin/main` bei Commit `1bb8fa4`.
Der Hauptklon `C:/_Local_DEV/repos/BACH` stand zum Messzeitpunkt auf einem Feature-Branch und
145 Commits hinter `origin/main`; dort wurde bewusst nicht gemessen.

Der Live-Stand auf dem Mac Studio (`~/services/bach`, Control API auf Port 8081) wurde
ausschließlich lesend über `GET /api/slots`, `/api/status` und `/api/backends` abgefragt. Dort
lief zum Messzeitpunkt ein Rechenjob seit 33 Stunden; es wurde kein Dienst angefasst und keine
Einstellung verändert.

Wo eine Angabe aus der Live-Abfrage stammt und nicht aus dem Code, ist sie als **[Mac live]**
gekennzeichnet.

---

## 2. Bestandsaufnahme

### 2.1 Provider und Backends

| Komponente | Datei::Symbol | Zustand | Lücke |
|---|---|---|---|
| Backend-Register (8 Einträge) | `hub/_services/chat/telegram_chat.py::BACKEND_PRESETS` Z. 385-439 | **aktiv, das einzige echte Register** | liegt im Telegram-Modul; kein anderer Teil von BACH liest es |
| Verfügbarkeitsprüfung | `telegram_chat.py::_backend_inventory` Z. 2867 | aktiv, gemessen statt konfiguriert | prüft nur die acht Presets, nicht die Runner aus `agent_runners.py` |
| Runner-Register (4 Einträge) | `hub/agent_runners.py::BUILTIN` Z. 39-69 | **doppelt** zu `BACKEND_PRESETS` | Auswahl per `fnmatch` auf den Modellnamen, keine Verfügbarkeitsprüfung derselben Art |
| Nutzer-Runner | `agent_runners.py::runners()` Z. 79-85, liest `~/.config/bach/agent_runners.json` | aktiv | dritter Konfigurationsort neben Presets und BUILTIN |
| Modell-Whitelist | `hub/agent_launcher.py:1395` | **aktiv und sperrend** | lässt nur `sonnet\|opus\|haiku` durch — die Runner `codex`, `agy`, `local` sind dadurch über den regulären Weg unerreichbar |
| Empfehlungs-Modelliste | `hub/_services/delegation/__init__.py::_ScorerAdapter.get_recommended_model` | **doppelt**, dritte Modelliste | kennt nur `haiku\|sonnet\|opus` |
| Ollama-Handler (CLI) | `hub/ollama.py::OllamaHandler` Z. 30, Config `data/ollama_config.json` | aktiv | zweiter, unabhängiger Weg zu lokalen Modellen neben `BUILTIN["local"]` |
| clutch-Anbindung | `hub/_services/delegation/__init__.py::_load_external_clutch_scorer` Z. 108-129 | **aktiv und extern bedient** | Fallback auf den Fork `hub/_archive/delegation_legacy/` ist **still** — ein Ausfall sähe aus wie normale Funktion |
| clutch-CLI-Fassade | `hub/clutch.py::ClutchHandler` Z. 32-225 | aktiv | reine Statusanzeige, kein Routing-Aufruf aus dem Ausführungspfad |

**Gemessen zu clutch (ASUS-GEI, 13.09.2026):** `delegation.get_component_sources()` meldet
`external_clutch: available` und alle sieben Komponenten (Scorer, PartnerRegistry,
Streckenanalyse, Gas/Bremse, Bordcomputer, Fahrschule, Fahrtenbuch) als `clutch`. Die
ROADMAP-Aussage „alle acht Quellen extern" ist damit bestätigt. Der Auflösungsweg läuft
allerdings **nicht** über die im Code gesuchten `.MODULES`-Pfade — die treffen auf diesem Host
ins Leere —, sondern darüber, dass `clutch` als Paket installiert ist
(`C:\_Local_DEV\repos\clutch\clutch\__init__.py`). Das Suchverfahren aus
`_candidate_clutch_roots` (Z. 81-93) ist hier also wirkungslos und der Erfolg hängt allein an
der Installation. Wer nur den Code liest, kommt zum gegenteiligen Schluss; erst die Messung
klärt es.

**[Mac live]** Von den acht Backends waren erreichbar: `ollama` (aktiv gewählt,
`qwen3.8:27b-mlx`), `ollama-cloud` (`kimi-k3:cloud`) und `claude` (CLI). Nicht verfügbar:
`lmstudio` (nicht erreichbar), `hermes` (Modell fehlt), `claude-api` und `openai` (Key fehlt),
`codex` (Anmeldung nicht bestätigt).

### 2.2 Modellwahl und Routing

| Komponente | Datei::Symbol | Zustand | Lücke |
|---|---|---|---|
| Rollen-Router (generisch) | `hub/agent_router.py::route/explain/load_roles` Z. 35-148 | **tot** | null Importeure, keine Handler-Subklasse, daher auch nicht per Auto-Discovery erreichbar — obwohl der eigene Docstring Z. 9-10 die Verdrahtung behauptet |
| Rollen-Routing (aktiv) | `core/launcher.py::AGENT_DELEGATIONS` Z. 88-94 | aktiv | hartkodiertes Dict mit fünf Fällen gegenüber 27 vorhandenen Rollen |
| Runner-Auflösung | `agent_runners.py::resolve/build_command` Z. 88-160 | aktiv | Kriterium ist allein der Modellname als Zeichenkette — keine Kosten, keine Verfügbarkeit, kein Aufgabentyp |
| Komplexitäts-Routing | `hub/_services/delegation` (clutch bzw. Legacy-Fork) | aktiv, aber entkoppelt | liefert eine Empfehlung, die den Ausführungspfad nicht erreicht |
| Modellwahl zur Laufzeit | `hub/schwarm.py::_specialist` Z. 608-610 (`--model haiku\|sonnet`) | aktiv | Modell als CLI-Parameter am Aufrufort, nicht als Eigenschaft der Rolle |

### 2.3 Rollen, Personas, Agenten

| Komponente | Datei::Symbol | Zustand | Lücke |
|---|---|---|---|
| Rollen-Register (kanonisch) | SQLite `bach_agents` / `bach_experts`, Schema `data/schema/schema.sql:596-635` | aktiv | **kein Feld für Modell, Backend, Rechte oder Budget** |
| Persona-Text | Spalte `persona`, Migration `data/schema/migrations/034_agent_personas.py:20` | aktiv | Freitext ohne Struktur |
| Quelle Boss-Agenten | `agents/<name>/SKILL.md`, gescannt in `hub/agents.py::_scan_filesystem` Z. 194-224 | aktiv | — |
| Quelle Experten | `agents/_experts/<name>/CONCEPT.md`, Z. 226-250 (Status per Textmarker) | aktiv | Status als Fließtextmarker statt als Feld |
| Persona-Export | `agents/personas/*.md`, erzeugt von `tools/agents_export.py` | **abgeleitet, kein Register** | wird nirgends zurückgelesen; alle 20 Dateien tragen `runtime.model: null` |
| Zweite Rollenwelt | `hub/_services/chat/slots_config.py::DEFAULT_CORE_SLOTS` Z. 36-83 | **aktiv, doppelt zur DB** | drei fest codierte Slots, die sehr wohl `backend` und `model` tragen — aber in einer JSON-Datei statt in der DB |
| Rollen als Prompt-Text | `slots_config.py::compose_worker_prompt` Z. 369-430 | aktiv | Rolle wirkt ausschließlich als zusammengesetzter System-Prompt; `role_id`, `multi_role`, `max_experts`, `expert_models` existieren als Felder, aber ohne Wirkung außerhalb des Prompts |
| Rollen-Auflösung Tray | `chat_tray.py::_resolve_role` Z. 440-464 | aktiv | `OLLAMA`/`BUDDHA`/`BACH` werden alle auf dieselbe generische Rolle „Buddha" abgebildet |

**[Mac live]** Die drei Core-Slots liefen alle auf demselben Modell (`qwen3.8:27b-mlx`,
Backend `ollama`) und unterschieden sich nur in `mode`, `max_tool_rounds` und `chat_id`. Ein
dynamischer Worker namens `glm` lief auf `ollama-cloud`/`glm-5.3:cloud` und war abgelaufen.

### 2.4 Zuweisung und Ausführung

| Komponente | Datei::Symbol | Zustand | Lücke |
|---|---|---|---|
| Standard-Zuweisung | `gui/server.py::DEFAULT_TASK_ASSIGNEE = "OLLAMA"` Z. 57, 384, 1602 | aktiv (PR #46) | Sentinel-Zeichenkette, kein Verweis auf eine Rolle oder ein Backend |
| Zweitdefinition | `gui/api/headless.py::DEFAULT_TASK_ASSIGNEE` Z. 211 | doppelt, per Test gekoppelt | `tests/test_gui_server_smoke.py:318` hält beide gleich |
| Manuelle Zuweisung | `hub/task.py::TaskHandler._assign` Z. 866-895 | aktiv | Freitext, keine Validierung gegen das Rollen-Register |
| **Der einzige Leser** | `chat_tray.py::_process_idle_task` Z. 553-694 | aktiv | die gesamte Kette „Task ist OLLAMA zugewiesen" hängt an einem System-Tray-Prozess auf dem Desktop |
| Ausführungsaufruf | `chat_tray.py` Z. 638-642, `POST :8081/api/chat` mit `mode: "full"` | aktiv | — |

Die Kette ist geschlossen, aber schmal: Ein Task entsteht mit `assigned_to = "OLLAMA"`, und
**ausschließlich** der Tray-Prozess pollt alle fünf Sekunden die GUI, findet ihn, setzt ihn auf
`in_progress` und schickt einen generierten Prompt an die Control API. Weder `scheduler.py` noch
`bach_api.py` kennen diesen Sentinel.

### 2.5 Slots, Fackeln, Ressourcen

| Komponente | Datei::Symbol | Zustand | Lücke |
|---|---|---|---|
| Fackel-Rechnung | `hub/_services/fackel.py`, Konzept `docs/TORCH-KONZEPT.md` | aktiv, 16 Tests | Grundsatz „gemessen, nicht gebucht" — bewusst kein Register, wer wie viele hält |
| Fackel-Kapazität | `fackel.py::kapazitaet_bytes` Z. 154, Quellenreihenfolge Env → sysctl → Metal → `/api/ps` | aktiv | — |
| Vorrangschalter | `hub/compute_lock.py::get/set_fackel_preference` Z. 431-498 | aktiv | **schreibt keinen Log-Eintrag** — dadurch ist rückwirkend nicht feststellbar, wer umgeschaltet hat (belegt in `T-20260913-253157668`) |
| Doppelte Persistenz | `~/.memwatchdog/fackel_preference.json` **und** `data/slots_config.json` Z. 487-494 | aktiv | zwei Schreibziele für einen Wert |
| Wirkung | `telegram_chat.py::_compute_lock_blocks` Z. 1045-1065 | aktiv | bei `ollama` wird das Gate komplett übersprungen (Z. 1058) |
| Job-Pausierung | `compute_lock.py::pause_compute_jobs` Z. 147-165 (SIGSTOP) / `resume_compute_jobs` Z. 175-182 | aktiv | — |
| Slot-Persistenz | `data/slots_config.json`, Override `BACH_SLOTS_CONFIG_PATH` | aktiv, selbstheilend (Z. 188-191) | JSON-Datei trägt Konfiguration, Zustand **und** Ereignisprotokoll zugleich |

**[Mac live]** `fackel_preference` stand auf `compute`. Im Verlauf des abgelaufenen Workers
steht als letzter Eintrag: „Fehler: Compute-Lock aktiv — kein Modell-Load, damit laufende
Rechenjobs nicht in den Swap gedrängt werden." Das ist die Zuteilung in Aktion, aber nur als
Fehlertext eines Workers sichtbar, nicht als Zuteilungsentscheidung.

### 2.6 Worker

| Komponente | Datei::Symbol | Zustand | Lücke |
|---|---|---|---|
| Dynamischer Worker (Thread) | `slots_config.py::add_worker` Z. 433-508, Start `telegram_chat.py::_run_worker_job` Z. 3505-3613 | aktiv | **keine Obergrenze** für parallele Worker-Threads gefunden |
| Thread-Register | `telegram_chat.py::_ACTIVE_WORKER_THREADS` Z. 140 | aktiv | nur prozesslokal |
| Abgleich | `slots_config.py::reconcile_workers` Z. 264-297 | aktiv | Zustände `idle/running/paused/completed/expired/error` nur für dynamische Worker, nicht für Core-Slots |
| Standalone-Worker | `hub/_services/chat/worker.py::main` Z. 116-259 | aktiv | eigener OS-Prozess, kennt `_ACTIVE_WORKER_THREADS` nicht |
| Fackel-Beachtung im Worker | `worker.py` Z. 174-190, 214-237 | aktiv | — |

### 2.7 Scheduler und Taktgeber

| Komponente | Datei::Symbol | Zustand | Lücke |
|---|---|---|---|
| Legacy-Scheduler | `hub/scheduler.py::SchedulerHandler`, Jobs in `scheduler_jobs`/`scheduler_runs` | **aktiv** | — |
| Session-Automation | `hub/_services/daemon/session_daemon.py` | deprecated und markiert (`scheduler.py` Z. 1544-1583) | nur mit `--force` startbar |
| Provider-Seam | `hub/scheduler_provider.py::probe_scheduler_provider` Z. 26-40 | **nur Statusprobe** | `_check_scheduler_provider` (`scheduler.py:373-388`) ändert ausdrücklich kein Laufzeitverhalten; `load_external_scheduler()` hat **null Aufrufer** |
| Fail-closed-Mechanik | `hub/canonical_seam.py::require_canonical` Z. 154-217 | vorhanden, für den Scheduler **nicht verdrahtet** | wird nur von `hub/web_scrape.py:257` und `_services/document/pdf_service.py:129` genutzt |
| Dritter Taktgeber | `chat_tray.py::_poll_loop` Z. 1247-1255, `IDLE_THRESHOLD` Z. 115 | aktiv | 5-Sekunden-Poll in einem separaten Prozess ohne Bezug zu den beiden anderen |

Die Regeldatei beschreibt den `ellmos-scheduler`-Seam als fail-closed. **Gemessen ist er das
nicht** — er ist eine Importprobe ohne Weiche. Das ist eine zu korrigierende Abweichung, keine
stillschweigende Ausnahme.

### 2.8 Delegation und Schutzgatter

| Komponente | Datei::Symbol | Zustand | Lücke |
|---|---|---|---|
| Tiefenzähler (Werkzeug) | `chat_runtime.py` Z. 782-810, Prüfung Z. 790-792 | aktiv | liest die Umgebungsvariable |
| Tiefenzähler (HTTP) | `telegram_chat.py::ControlHandler.do_POST` Z. 3360-3405, Antwort 429 bei Z. 3367 | aktiv | liest den Header `X-Delegation-Depth`, **nicht** die Umgebungsvariable — wer ohne Header aufruft, startet immer bei null |
| Vollsperre in Schleifen | `agent_runner.py:80`, `task_runner.py:122`, `plan_runner.py:127`, `worker.py:128` | aktiv | — |
| Schwelle | hart codiert an beiden Prüfstellen | aktiv | `_services/limits.py:29` dokumentiert sie, liest sie aber nicht aus |
| Domänen-Gate | `hub/domain_writer_gate.py` Z. 68-113, GUI-Übersetzung `gui/server.py:68-70` (HTTP 423) | aktiv, **echt fail-closed** | — |

`domain_writer_gate.py` ist das einzige Gatter im System, das den fail-closed-Vertrag
tatsächlich einhält: unbekannte Domäne wirft `ValueError` statt still zu erlauben. Es ist damit
die Vorlage, an der sich die übrigen Seams messen lassen müssen.

### 2.9 Oberflächen und Persistenzen

| Oberfläche | Ort | Zustand | Lücke |
|---|---|---|---|
| Cockpit heute | `:8081/activity`, HTML aus `telegram_chat.py::WEB_ACTIVITY_DASHBOARD` Z. 1514 | aktiv | eigenes Design, außerhalb des GUI-Systems |
| GUI-Navigation | `gui/static/js/nav.js::NAV_ITEMS` Z. 61-101 | aktiv | reines JS-Array ohne gemeinsames Server-Layout; verlinkt zweimal auf den fremden Port 8081 |
| Agenten-Seiten | `/agents` Z. 4374, `/agents-board` Z. 4464 | aktiv mit Bruch | `agents-board.html` existiert nicht im Repo, der Fallback auf `skills-board.html` greift immer |
| Zuweisungs-Liste | `GET /api/assignees` Z. 1699 | aktiv | listet `bach`, `user`, `OLLAMA`, `BUDDHA` plus aktive Rollen — der einzige Ort, an dem Sentinel und Rolle nebeneinander stehen |

| Persistenz | Pfad | Inhalt | Lücke |
|---|---|---|---|
| Kanonische DB | `bach.db` (`hub/bach_paths.py::_resolve_bach_db` Z. 200-238) | Rollen, Tasks, Scheduler-Jobs, Präsenz | trägt **keine** Modell-, Backend- oder Besetzungsdaten |
| Slot-Konfiguration | `data/slots_config.json` | Slots, Worker, Fackel-Präferenz, **Aktivitätsprotokoll** | drei verschiedene Dinge in einer Datei |
| Fackel-Präferenz | `~/.memwatchdog/fackel_preference.json` | ein Wert plus `updated_at` | kein Akteur, kein Verlauf |
| Ollama-Konfiguration | `data/ollama_config.json` | Provider, Modell, URL | vierter Konfigurationsort für Modelle |
| Aktivitätsprotokoll | in `slots_config.json`, `record_activity` Z. 524-558 | 100 Einträge, neueste zuerst | Felder `id`, `timestamp`, `source`, `activity`, `status`, `details` — **kein Modell, kein Backend, kein Akteur** |

---

## 3. Der Befund in fünf Sätzen

1. **Ein Backend-Register existiert bereits und ist gut** — es liegt nur im Telegram-Modul,
   und drei weitere Modell-Listen stehen unabgeglichen daneben, von denen eine als harte
   Whitelist alles außer Claude abschneidet.
2. **Rollen tragen kein Modell.** Die Frage des Nutzers, wer wann welche Rolle spielt, ist
   heute nicht falsch beantwortet, sondern gar nicht als Datum vorhanden.
3. **Es gibt zwei Rollenwelten**: die kanonische in der Datenbank ohne Modell, und die
   wirksame in einer JSON-Datei mit Modell, die aber nur Prompt-Text erzeugt.
4. **Drei Taktgeber teilen unabhängig voneinander zu**, und der schmalste von ihnen — ein
   System-Tray-Prozess — ist der einzige, der die Standard-Zuweisung überhaupt liest.
5. **Das Protokoll kennt den Akteur nicht.** Deshalb war schon bei der Fackel nicht
   feststellbar, wer umgeschaltet hatte; dieselbe Blindheit gilt für jede Besetzung.

Die vier Ressourcen- und Schutzmechanismen dagegen — Fackel-Rechnung, Compute-Lock,
Delegationstiefe, Domänen-Gate — sind gebaut, getestet und wirken. **Was fehlt, ist nicht die
Mechanik, sondern die Zuteilungsentscheidung darüber und ihre Protokollierung.**

---

## 4. Architekturskizze: lebendiges BACH

### 4.1 Die Grundunterscheidung

**Rolle ist ein Vertrag. Agent ist eine Besetzung.**

Eine *Rolle* sagt, was getan werden darf und soll: Fähigkeiten, Werkzeugkreis, Rechte,
Budgetrahmen, Fackelbedarf. Sie ist dauerhaft, wird gepflegt und geändert sich selten.
`steuer-agent`, `research-agent`, „Hintergrundworker" sind Rollen.

Ein *Agent* ist die Besetzung dieses Vertrags zur Laufzeit: ein konkretes Modell auf einem
konkreten Backend, an einem konkreten Ort (lokal, Mac, Cloud), mit einem konkreten Budget und
einer konkreten Fackelzuteilung. `qwen3.8:27b-mlx` auf `ollama` am Mac ist ein Agent.

Dieselbe Rolle ist durch verschiedene Agenten besetzbar, und derselbe Agent kann nacheinander
verschiedene Rollen spielen. **Genau diese Trennung fehlt heute**, und genau ihr Fehlen macht
die Frage „wer spielt wann welche Rolle" unbeantwortbar: Was heute Modell trägt (der Slot),
trägt keine Rolle; was Rolle trägt (die DB-Zeile), trägt kein Modell.

Der Slot ist dabei weder das eine noch das andere, sondern ein **Platz**: ein dauerhaft
vorgehaltener Ausführungskontext mit einer Chat-Identität (`buddha_chat` ist der interaktive
Platz, `buddha_always_on` der Hintergrundplatz, `buddha_connector` der Nachrichtenplatz). Plätze
gibt es wenige und stabile; Rollen viele; Besetzungen wechseln. Diese Dreiteilung ist im Code
bereits angelegt — `sub_mode`, `role_id` und `model` stehen im selben Worker-Datensatz — aber
nicht als Begriffe getrennt.

### 4.2 Die Zuteilung: wer spielt wann

Eine Besetzung entsteht aus fünf Eingaben, in dieser Reihenfolge:

1. **Auslöser** — woher kommt die Arbeit: Scheduler-Job, zugewiesener Task, eingehende
   Nachricht, interaktive Anfrage, Leerlauf.
2. **Rolle** — welcher Vertrag passt. Heute hartkodiert in fünf Fällen; künftig aus dem
   Rollen-Register, mit dem wiederbelebten oder ersetzten Router.
3. **Vorschlag** — welches Modell dieser Aufgabe angemessen ist. Das ist die Frage, die clutch
   bereits beantwortet, samt Kosten und Lernschleife.
4. **Gates** — was BACH allein weiß und was den Vorschlag überstimmen darf: reichen die
   Fackeln, steht der Vorrangschalter auf `compute`, ist ein Compute-Lock aktiv, ist die
   Delegationstiefe erschöpft, erlaubt der Rechtevertrag der Rolle das Werkzeug, ist die
   Domäne fremd.
5. **Besetzung** — das Ergebnis: Rolle, Modell, Backend, Platz, Budget. Und dieses Ergebnis
   wird protokolliert.

Der entscheidende Schnitt liegt zwischen 3 und 4: **clutch schlägt vor, BACH entscheidet.**
Der Vorschlag ist eine Empfehlung über Modelle; die Entscheidung ist eine über Ressourcen
dieser Maschine. Nur BACH kennt die Fackeln, den laufenden 33-Stunden-Rechenjob und den
Vorrangschalter. Ein reiner Modellrouter kann diese Entscheidung nicht treffen, und BACH soll
umgekehrt die Modellbewertung nicht noch einmal selbst bauen.

Damit die Lernschleife von clutch dabei nicht gegen die Gates lernt, gilt: **Ein von einem
Gate abgelehnter Vorschlag wird nicht als schlechtes Modellergebnis zurückgemeldet.** Er ist
kein Fehlurteil über das Modell, sondern eine Aussage über die Maschine. Nur tatsächlich
ausgeführte Besetzungen fließen in die Bewertung zurück.

### 4.3 Beobachtbarkeit: das Protokoll als Wahrheit über Besetzungen

Heute schreibt `record_activity` einen Freitext mit einer Quell-ID. Für „wer spielte um 10:34
welche Rolle" reicht das nicht. Eine Protokollzeile muss mindestens tragen:

| Feld | Zweck |
|---|---|
| `timestamp` | wann |
| `platz` | wo (`buddha_chat`, `worker-xxxx`) |
| `rolle` | welcher Vertrag |
| `modell` + `backend` | wer gespielt hat |
| `ausloeser` | warum (Scheduler-Job, Task-ID, Nachricht, Leerlauf, Nutzerklick) |
| `entscheidung` | angenommener Vorschlag, oder abgelehnt durch welches Gate |
| `ergebnis` | ok, Fehler, abgebrochen |

**Zwei Dinge, die heute vermischt sind, gehören getrennt:** der *Ereignisstrom* (was geschah,
append-only, historisch auswertbar) und der *Zustand* (was ist gerade, abfragbar). Heute liegen
beide zusammen in `slots_config.json`, gedeckelt auf hundert Einträge, gemeinsam mit der
Konfiguration. Ein Ringpuffer in der Konfigurationsdatei kann keine Frage über gestern
beantworten.

**Diese Trennung steht nicht im Widerspruch zum Fackel-Grundsatz „gemessen, nicht gebucht".**
Der Grundsatz betrifft den *Zustand*: Wer wie viele Fackeln hält, wird erfragt und nicht in
einer Tabelle geführt, weil eine Buchhaltung auseinanderläuft, sobald ein Prozess ohne
Abmeldung stirbt. Das *Ereignis* dagegen ist vergangen und damit unveränderlich — es kann gar
nicht auseinanderlaufen. Was das Fackel-Dokument verbietet, ist ein Register des Jetzt; was hier
gebraucht wird, ist ein Protokoll des Gewesenen. Konkret: Die Frage „wie viele Fackeln sind
frei" bleibt eine Messung, und die Frage „wer bekam um 10:34 welche" wird eine Protokollzeile.

**Die Fackel-Umschaltung wird einbezogen.** Sie ist heute der belegte Fall, an dem die Blindheit
konkret wurde: Weil `set_fackel_preference` nichts protokolliert, war der Akteur eines Wechsels
grundsätzlich nicht ermittelbar — weder rückwirkend aus Logs noch prospektiv ohne Root-Rechte.
Das ist keine Verbesserung nebenbei, sondern der Prüfstein: Wenn das neue Protokoll diese Frage
nicht beantwortet, taugt es nicht.

### 4.4 Das Cockpit

`:8081/activity` ist heute die Oberfläche des Modell-Backends und bleibt der Ort. Sie wird
parallel (Ticket `T-20260913-660268706`) ins GUI-Design überführt und unter „Agenten"
eingehängt. Dieses Konzept baut daran nichts, sondern behandelt `/activity` als den Cockpit-Ort
und übernimmt dessen Ergebnis.

Das Cockpit zeigt drei Dinge, die heute nur teilweise vorhanden sind: die **Plätze** mit ihrer
aktuellen Besetzung (vorhanden), die **Ressourcenlage** — freie Fackeln, Vorrangschalter,
laufende Compute-Jobs (teilweise vorhanden) und den **Besetzungsverlauf** (fehlt).

---

## 5. Einordnung der vorhandenen Bausteine

Grundsatz P-009: vorhandene Standards vor Eigenbau. Die Zuordnung:

| Baustein | Übernimmt | Übernimmt **nicht** |
|---|---|---|
| **clutch** (`.MODULES/.ORCHESTRATION/clutch`, v0.6.2) | Modellbewertung, Aufgabenklassifikation, Kostenrechnung, Budget-Tankuhr, Circuit Breaker, Lernschleife, Modell-Katalog über sechs Anbieter | Ressourcenentscheidungen dieser Maschine; Rollenbegriff; Rechte |
| **ellmos-scheduler** | Zeitsteuerung, Claims/Leases, Pause/Resume, Heartbeat, Lauf-Historie | Modellwahl; Besetzung |
| **agent-launcher** / `agent_runners` | Prozessstart je Anbieter (Claude, Codex, agy, lokal) | Auswahl, welcher Anbieter — das kommt von oben |
| **Fackel** (`_services/fackel.py`) | Messung des freien Modellspeichers, Passt-Prüfung | Buchführung; Vorrangentscheidung |
| **compute_lock** | Vorrangschalter, SIGSTOP/SIGCONT für Rechenjobs | — |
| **swarm-ai** / `hub/schwarm.py` | Muster für Mehr-Agenten-Läufe | Einzelbesetzung |
| **domain_writer_gate** | **Vorlage** für den fail-closed-Vertrag | — |
| **BACH-eigen bleibt** | Rollen-Register, Plätze, Gates, Besetzungsprotokoll, Cockpit | — |

Drei Dinge folgen daraus unmittelbar:

- **Der stille clutch-Fallback muss laut werden.** clutch wird derzeit gemessen extern
  bedient, aber allein weil das Paket installiert ist — die im Code gesuchten Pfade greifen auf
  diesem Host nicht. Fiele die Installation weg, würde BACH ohne Vorwarnung auf den
  archivierten Fork zurückfallen: Ein Ausfall sähe aus wie normale Funktion. Der Seam braucht
  denselben Vertrag wie `domain_writer_gate` — Fehler statt stiller Ersatz.
- **Der Scheduler-Seam ist noch keiner.** Er muss entweder fail-closed verdrahtet oder als
  reine Probe gekennzeichnet werden. Beides ist vertretbar; der heutige Zwischenzustand, in dem
  die Regeldatei etwas anderes behauptet als der Code tut, ist es nicht.
- **Der tote Router wird entschieden, nicht behalten.** `agent_router.py` wird an die
  Zuteilung angeschlossen oder gelöscht. Eine Leiche, die vorgibt verdrahtet zu sein, kostet
  bei jedem Lesen erneut Zeit.

---

## 6. Zweitmeinung

Eine unabhängige Architektur-Zweitmeinung wurde eingeholt. Fragen und Antwort liegen als
`_codex/ARCHITEKTUR-FRAGEN.md` und `_codex/ARCHITEKTUR-ANTWORT.md` im Repo; die Einarbeitung ist
im Abschnitt unten dokumentiert.

<!-- ZWEITMEINUNG-EINARBEITUNG -->

---

## 7. Offene Entscheidungen

Vier Festlegungen sind echte Architekturentscheidungen und werden dem Nutzer als
`decision-shot` vorgelegt, nicht hier einseitig getroffen:

1. **Wo lebt das Rollen-Register** — Datenbank oder Konfigurationsdatei?
2. **Wie wird zugeteilt** — clutch schlägt vor und BACH gated, oder BACH entscheidet allein?
3. **Welches Format hat das Backend-Register** — ein gehobenes Python-Dict oder eine Datei?
4. **Wo liegt das Cockpit** — bleibt es auf Port 8081 oder zieht es in die GUI auf 8000?

Die Vorlage steht im Ticket `T-20260913-896336887` unter der Kennung `BH-2026-09-13-A`.

---

## 8. Reihenfolge und Folgetickets

Die Reihenfolge ist so gewählt, dass das System zu keinem Zeitpunkt unbrauchbar ist. Jeder
Schritt ist für sich nützlich, auch wenn der nächste nie kommt.

| # | Schritt | Warum hier |
|---|---|---|
| 1 | **Protokoll erweitern**: Akteursfelder ergänzen, Fackel-Umschaltung einbeziehen, Ereignis von Zustand trennen | Ändert kein Verhalten, macht aber alles Folgende messbar. Ohne diesen Schritt lässt sich keine Verbesserung belegen. |
| 2 | **Backend-Register vereinheitlichen**: `BACKEND_PRESETS` herausheben, Whitelist und `BUILTIN` darauf zurückführen | Hebt die Sperre auf, die heute alles außer Claude abschneidet — sichtbarer Gewinn, kleiner Eingriff |
| 3 | **Seams ehrlich machen**: clutch-Fallback laut, Scheduler-Seam entscheiden | Beseitigt zwei Stellen, an denen Ausfall wie Funktion aussieht |
| 4 | **Rolle bekommt Besetzungsfelder** (nach Entscheidung 1) | Braucht die Entscheidung des Nutzers |
| 5 | **Zuteilung verdrahten** (nach Entscheidung 2), toten Router entscheiden | Braucht 2 und 4 |
| 6 | **Cockpit** (nach Entscheidung 4, Ergebnis von `T-20260913-660268706` abwarten) | Zeigt, was die Schritte davor erzeugt haben |

**Anfangen mit Schritt 1.** Nicht weil er der größte Gewinn wäre, sondern weil er der einzige
ist, der ohne Nutzerentscheidung auskommt, nichts kaputtmachen kann und jeden weiteren Schritt
überprüfbar macht. Die Fackel-Analyse hat gezeigt, wohin es führt, wenn man Mechanik baut,
bevor man sie beobachten kann: Die naheliegendste Frage des Nutzers war mit den vorhandenen
Daten grundsätzlich nicht beantwortbar.

---

*Erstellt von bachheart@ASUS-GEI im Auftrag des ticket-master, 13.09.2026.
Phase 1 — Bestandsaufnahme und Konzept, kein Umbau.*
