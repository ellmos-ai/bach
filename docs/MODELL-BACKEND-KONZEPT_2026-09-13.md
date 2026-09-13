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
3. [Der Befund in sieben Sätzen](#3-der-befund-in-sieben-sätzen)
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
| CLI-Register | `hub/_services/llm/model_backend.py::CLIBackend.KNOWN_CLIS` Z. 708 | **doppelt**, fünfte Liste | trägt Start-, Bereitschafts- und Sessionargumente je CLI — Verhalten, das `BACKEND_PRESETS` gar nicht kennt |
| Backend-Fabrik | `hub/_services/llm/model_backend.py::create_backend` Z. 952 | aktiv | baut aus einer Konfiguration das tatsächliche Backend-Objekt — die eigentliche technische Wahrheit hinter den Presets |
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
| **Kein atomarer Claim** | `chat_tray.py` Z. 567-575 (lesen, dann `in_progress` setzen) gegen `worker.py` Z. 167-193 (`offen[0]` nehmen und starten) | **aktiv und riskant** | zwei Taktgeber können dieselbe Aufgabe gleichzeitig mit Schreibrechten ausführen |

Die Kette ist geschlossen, aber schmal: Ein Task entsteht mit `assigned_to = "OLLAMA"`, und
**ausschließlich** der Tray-Prozess pollt alle fünf Sekunden die GUI, findet ihn, setzt ihn auf
`in_progress` und schickt einen generierten Prompt an die Control API. Weder `scheduler.py` noch
`bach_api.py` kennen diesen Sentinel.

**Der Tray ist dabei breiter zuständig, als der Sentinel vermuten lässt** (`chat_tray.py`
Z. 567-575): Er fragt nacheinander `OLLAMA`, `BUDDHA` und `BACH` ab und greift danach auf
nahezu alle nicht-menschlichen Zuweisungen zurück. `"OLLAMA"` ist damit nicht sein Auftrag,
sondern nur sein erster Versuch.

**Das gefährlichere Fehlen ist der Claim.** Der Tray liest eine Aufgabe und setzt sie *danach*
auf `in_progress`; `worker.py` nimmt schlicht `offen[0]` und startet, ohne vorher überhaupt zu
beanspruchen. Zwischen Lesen und Markieren liegt ein Fenster, in dem ein zweiter Taktgeber
dieselbe Aufgabe aufgreift — mit Schreibrechten. Das ist kein Schönheitsfehler der Zuteilung,
sondern ein Korrektheitsproblem, und es wiegt schwerer als die doppelten Register.

### 2.5 Slots, Fackeln, Ressourcen

| Komponente | Datei::Symbol | Zustand | Lücke |
|---|---|---|---|
| Fackel-Rechnung | `hub/_services/fackel.py`, Konzept `system/docs/TORCH-KONZEPT.md` | aktiv, 16 Tests | Grundsatz „gemessen, nicht gebucht" — bewusst kein Register, wer wie viele hält |
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
| Rechte am Executor | — | **fehlt** | `mode` (`safe`/`full`) wird vom Slot, von der API und vom Prompt gesetzt; kein zentraler Werkzeug- oder Prozessstarter prüft ein Rollenrecht |
| Zugangsschutz Control API | `telegram_chat.py::_is_allowed_origin` Z. 2955, Prüfung Z. 3007/3048 | **aktiv, aber kein Authentifizierungsnachweis** | geprüft werden Herkunft und Inhaltstyp; kein `Authorization`-Header im ganzen Modul. Über diese Schnittstelle lassen sich Slots ändern, Worker im Vollmodus starten und die Fackel umschalten |

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

## 3. Der Befund in sieben Sätzen

1. **Kein atomarer Claim.** Zwei Taktgeber können dieselbe Aufgabe gleichzeitig mit
   Schreibrechten ausführen, weil zwischen Lesen und Beanspruchen ein Fenster liegt und
   `worker.py` gar nicht erst beansprucht. Das ist der gefährlichste Befund.
2. **Rechte werden nirgends erzwungen.** `safe` und `full` setzen Slot, API und Prompt; kein
   zentraler Starter prüft ein Rollenrecht. Ein Rechtefeld an der Rolle wäre ohne diesen
   Prüfpunkt bloße Dokumentation.
3. **Fünf unabgeglichene Modell- und Backend-Listen.** Ein gutes Register existiert bereits,
   liegt aber im Telegram-Modul; eine harte Whitelist schneidet alles außer Claude ab, und
   `model_backend.py` trägt zusätzlich das Startverhalten je CLI, das keines der Register kennt.
4. **Rollen tragen kein Modell.** Die Frage des Nutzers, wer wann welche Rolle spielt, ist
   heute nicht falsch beantwortet, sondern gar nicht als Datum vorhanden.
5. **Es gibt mehr als zwei Rollenwelten**: die Datenbank ohne Modell, `slots_config.json` mit
   Modell als Prompt-Text, dazu `DEFAULT_ROLE_PROMPTS`, `PERSONA_MAP` im Tray,
   `AGENT_DELEGATIONS` im Launcher, die Tabelle `agent_instances` und das Persona-Frontmatter.
6. **Das Protokoll kennt den Akteur nicht.** Deshalb war schon bei der Fackel nicht
   feststellbar, wer umgeschaltet hatte; dieselbe Blindheit gilt für jede Besetzung.
7. **Die Control API prüft Herkunft, nicht Berechtigung.** Über sie lassen sich Slots ändern,
   Worker im Vollmodus starten und die Fackel umschalten.

Die vier Ressourcen- und Schutzmechanismen dagegen — Fackel-Rechnung, Compute-Lock,
Delegationstiefe, Domänen-Gate — sind gebaut, getestet und wirken. **Was fehlt, ist nicht die
Mechanik, sondern eine verbindliche Stelle, an der zugeteilt, beansprucht, geprüft und
protokolliert wird.**

---

## 4. Architekturskizze: lebendiges BACH

### 4.1 Die Grundunterscheidung: vier Begriffe

Ein erster Entwurf dieses Konzepts kannte nur zwei Begriffe, Rolle und Agent. Die
Zweitmeinung hat das zurückgewiesen, und zwar zu Recht: „Agent" ist in BACH bereits belegt —
`core/agent_runtime.py::AgentRegistry` führt eine Tabelle `agent_instances` mit genau diesem
Wort für etwas anderes. Wer den Begriff umdeutet, baut eine Mehrdeutigkeit ein, die jeder
Leser danach erneut auflösen muss. Es braucht vier Begriffe:

| Begriff | Was er festhält | Lebensdauer |
|---|---|---|
| **Rolle** | Vertrag: Fähigkeiten, Rechte, Werkzeuggrenzen, Budgetrahmen. Versioniert. | dauerhaft |
| **Agentenprofil** | ausführbare Kombination aus Backend-Adapter, Modellklasse, Host-Anforderung, technischen Fähigkeiten | dauerhaft |
| **Besetzung** | zeitlich begrenzte Bindung von Rolle, Agentenprofil, Auftrag und Platz | Minuten bis Stunden |
| **Lauf** | die konkrete Ausführung einer Besetzung, mit eigener Kennung und dem *tatsächlich* verwendeten Modell | ein Vorgang |

Der **Platz** kommt als fünfter, aber bereits vorhandener Begriff hinzu: ein vorgehaltener
Ausführungskontext mit Chat-Identität. `buddha_chat`, `buddha_always_on` und
`buddha_connector` sind Plätze, keine Rollen — `buddha_connector` ist genau genommen ein
Eingangskanal. Ein Platz kann nacheinander verschieden besetzt werden; eine Rolle kann
gleichzeitig auf mehreren Plätzen besetzt sein.

Die Unterscheidung zwischen Besetzung und Lauf ist kein Formalismus: Das gewünschte Modell und
das tatsächlich verwendete können auseinanderfallen, etwa wenn ein Gate greift oder ein
Backend ausfällt. Genau diese Differenz ist es, die man später wissen will.

**Was an die Rolle gehört und was nicht.** Rechte und Budgetgrenzen sind Vertragsbestandteil.
Bevorzugtes Backend und bevorzugtes Modell sind es **nicht** — sie sind weiche
Besetzungspolitik und gehören an die Zuteilung, nicht an den Vertrag. Der Fackelbedarf gehört
überhaupt nicht an die Rolle: Er hängt von Modell, Kontextfenster und Host ab und ist damit
eine Eigenschaft des Laufs, keine der Rolle.

### 4.2 Die Zuteilung: wer spielt wann

Eine Besetzung entsteht in sechs Schritten:

1. **Auslöser** — woher kommt die Arbeit: Scheduler-Job, zugewiesener Task, eingehende
   Nachricht, interaktive Anfrage, Leerlauf.
2. **Claim** — die Aufgabe wird atomar beansprucht, bevor irgendetwas anderes geschieht. Ohne
   diesen Schritt ist alles Weitere wertlos, weil zwei Taktgeber dieselbe Arbeit tun können.
3. **Rolle** — welcher Vertrag passt, und erlaubt er das, was hier verlangt wird.
4. **Kandidatenmenge** — BACH bildet aus Rechten, Host, Compute-Lock, Fackeln,
   Delegationstiefe und harten Budgetgrenzen die Menge der überhaupt zulässigen Agentenprofile.
5. **Auswahl** — clutch bewertet und exploriert **innerhalb dieser Menge** und wählt aus.
6. **Start** — BACH prüft unmittelbar davor noch einmal die flüchtigen Ressourcen, startet und
   protokolliert.

**Der entscheidende Punkt ist die Reihenfolge von 4 und 5.** Der naheliegende Entwurf lautet
„clutch schlägt vor, BACH legt ein Veto ein" — und genau der ist falsch. Ein nachträgliches
Veto erzeugt das Zwei-Hirn-Problem: clutch wählt frei, BACH lehnt ab, clutch lernt aus der
Ablehnung und hält das Modell für schlecht, obwohl nur die Maschine voll war. Wirken die Gates
dagegen **vorher**, sieht clutch nur zulässige Kandidaten und trifft innerhalb dieser Menge
eine Entscheidung, die auch umgesetzt wird.

Daraus folgt die Rückmeldungsregel: **Ein Gate-Ausschluss ist kein Modellergebnis.** In die
Lernschleife fließt nur, was tatsächlich lief. Und die Ergebnisarten müssen unterschieden
werden — ein Infrastrukturfehler, eine Richtlinien-Ablehnung und ein fachlicher Misserfolg
sind drei verschiedene Dinge; wer sie zusammenwirft, lernt Rauschen.

Die Verantwortungsgrenze verläuft damit entlang des Wissens: **clutch weiß über Modelle
Bescheid, BACH über diese Maschine.** Nur BACH kennt die Fackeln, den laufenden
33-Stunden-Rechenjob und den Vorrangschalter; nur clutch kennt Modellpreise, Eignung und
Verlauf.

### 4.3 Fackeln und Budget sind zwei Achsen, kein gemeinsames Konto

Das Fackel-Dokument sagt „gemessen, nicht gebucht", clutch dagegen bucht — Tankuhr,
Budgetzonen, Verbrauchsgrenzen. Das ist kein Widerspruch, solange man nicht versucht, beides
in eine Zahl zu ziehen:

- **Fackeln** regeln die *momentane physische Zulässigkeit* auf einem Host: Passt dieses
  Modell jetzt in den Speicher?
- **Budget** regelt den *kumulativen Verbrauch* an Geld, Tokens oder Kontingent: Ist diese
  Ausführung im Rahmen?

Eine Besetzung muss beide Bedingungen erfüllen. Sie dürfen aber kein gemeinsames Guthaben
bilden, und es darf kein Register „Agentenprofil X hält fünf Fackeln" entstehen — das wäre
genau die Buchhaltung, die auseinanderläuft, sobald ein Prozess ohne Abmeldung stirbt.

Zulässig sind drei Dinge: eine **Bedarfsschätzung** aus Modell, Kontext und Host, die
**unmittelbar gemessene Belegung** samt Messquelle, und eine **kurzlebige Startsperre**, die
verhindert, dass zwischen Prüfung und Start ein zweiter Ladevorgang dazwischenkommt. Die
Startsperre behauptet keinen Besitz; nach dem Start bleibt die Messung maßgeblich.

### 4.4 Beobachtbarkeit: Ereignisstrom und Zustand getrennt

Heute schreibt `record_activity` einen Freitext mit einer Quell-ID. Für „wer spielte um 10:34
welche Rolle" reicht das nicht.

**Das Protokoll kann nicht zugleich Ereignisstrom und Zustand sein.** Ein erster Entwurf
dieses Konzepts wollte es zur „einzigen Wahrheit" machen; die Zweitmeinung hat widersprochen,
und der Widerspruch überzeugt. Gebraucht werden zwei Dinge:

- ein **append-only Ereignisstrom** für Entscheidungen und Lebenszyklusänderungen,
- eine **abfragbare Besetzungstabelle** für den aktuellen Zustand — entweder eigenständig oder
  als deterministische Projektion aus dem Strom.

Heute liegen beide zusammen in `slots_config.json`, gedeckelt auf hundert Einträge, gemeinsam
mit der Konfiguration. Ein Ringpuffer in der Konfigurationsdatei kann keine Frage über gestern
beantworten.

Eine Besetzung muss mindestens tragen:

| Feld | Zweck |
|---|---|
| `assignment_id` | die Besetzung selbst |
| `started_at`, `ended_at` | oder zwei korrelierte Ereignisse |
| `role_id` + Rollenrevision | welcher Vertrag, in welcher Fassung |
| `agent_instance_id` | die ausführende Instanz |
| `backend_id`, `model_id`, `host` | **tatsächlich** verwendet, nicht gewünscht |
| `slot_id`, `session_id`, `task_id` | Platz, Sitzung, Auftrag |
| `initiated_by` | der Auslöser: Mensch oder Technik |
| Status, Ergebnis, Umschaltgrund | was daraus wurde |

**„Akteur" ist dabei zwei Dinge, nicht eines:** der *Auslöser* (wer hat es angestoßen) und die
*ausführende Instanz* (wer hat es getan). Beim Fackel-Schalter war genau der Auslöser die
offene Frage — dort werden alter und neuer Wert, der Auslöser und ein Mess-Schnappschuss
protokolliert. Ein Feld `haelt_fackeln` wäre dagegen mit „gemessen, nicht gebucht"
unvereinbar und darf nicht entstehen.

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

### 4.5 Das Cockpit — bewusst außerhalb des Bauumfangs

`:8081/activity` ist heute die Oberfläche des Modell-Backends. Sie wird parallel (Ticket
`T-20260913-660268706`) ins GUI-Design überführt und unter „Agenten" eingehängt.

**Dieses Programm baut am Cockpit nichts.** Die Zweitmeinung hat angemerkt, das Cockpit sei
ein nachgelagerter Abnehmer und schaffe keine korrekte Zuteilung — das trifft zu, und es ist
der Grund, warum es hier aus dem Bauumfang herausfällt statt als fünfte Festlegung
mitgeschleppt zu werden. Es erscheint erst wieder, wenn es etwas anzuzeigen gibt.

Anzuzeigen wären dann drei Dinge: die **Plätze** mit ihrer aktuellen Besetzung (heute
vorhanden), die **Ressourcenlage** aus freien Fackeln, Vorrangschalter und laufenden
Rechenjobs (teilweise vorhanden) und der **Besetzungsverlauf** (fehlt).

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

**Ein Katalog, aber zwei Adapterverträge.** Ein erster Entwurf wollte `BACKEND_PRESETS` zur
alleinigen Wahrheit erheben. Das greift zu kurz: `hub/_services/llm/model_backend.py` trägt in
`CLIBackend.KNOWN_CLIS` (Z. 708) die Start-, Bereitschafts- und Sessionargumente je
Kommandozeilenwerkzeug, und `create_backend` (Z. 952) baut daraus das tatsächliche Objekt —
Verhalten, das die Presets gar nicht kennen. Ein flaches Register würde verdecken, dass ein
Chat-Backend über eine Programmierschnittstelle und ein Prozess-Runner über eine Kommandozeile
grundverschiedene Start-, Werkzeug- und Sitzungssemantik haben. Richtig ist daher: **ein
gemeinsamer Katalog, welche Backends es gibt — und getrennte Adapterverträge, wie man sie
startet.**

Vier Dinge folgen daraus unmittelbar:

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
- **Der Legacy-Fork darf kein zweiter Lernkern bleiben.** Als ausdrücklich eingeschalteter
  Notfallmodus ist er vertretbar; als stiller Ersatz ist er ein zweites, unbemerktes
  Routing- und Lernsystem neben dem eigentlichen.

---

## 6. Zweitmeinung

Eine unabhängige Architektur-Zweitmeinung wurde eingeholt: **Codex, Modell `gpt-5.6-sol`,
Reasoning-Stufe `high`**, read-only im selben Worktree. Auftrag und Antwort liegen als
`_codex/ARCHITEKTUR-FRAGEN.md` und `_codex/ARCHITEKTUR-ANTWORT.md` im Repo.

**Attributionsbeleg.** Rollout `rollout-2026-09-13T12-04-37-01a09a39-…jsonl`, Feld
`"model":"gpt-5.6-sol"`, 42 ausgeführte Befehle. `codex_run_proof.py --contains
"import agent_router|scheduler_provider"` meldet `BELEGT` — Codex hat die Behauptungen dieses
Dokuments selbst am Quellcode nachgemessen, statt sie zu übernehmen. Für Textinhalte ist das
Skript nicht zuständig: Es durchsucht ausgeführte Befehle, nicht Antworttexte, und meldet für
einen Satz aus der Antwort folgerichtig `KEIN BELEG`. Der Textbeleg ist das Rollout selbst.

Die Zweitmeinung hat den Entwurf an fünf Stellen korrigiert. **Alle fünf wurden übernommen**,
nachdem die zugrunde liegenden Gegenbehauptungen am Quellcode nachgemessen wurden:

| Einwand | Übernommen als | Nachgemessen |
|---|---|---|
| „Agent = Besetzung" kollidiert mit `agent_instances`; es braucht vier Begriffe | Abschnitt 4.1 (Rolle, Agentenprofil, Besetzung, Lauf; Platz als fünfter) | `core/agent_runtime.py::AgentRegistry` führt tatsächlich eine Tabelle dieses Namens |
| Gates gehören **vor** die Auswahl, nicht als Veto danach | Abschnitt 4.2, Schritte 4 und 5 | — (Argument, keine Tatsachenbehauptung) |
| Fackeln und Budget dürfen kein gemeinsames Konto bilden; es braucht eine kurzlebige Startsperre | neuer Abschnitt 4.3 | — |
| Das Protokoll kann nicht zugleich Strom und Zustand sein | Abschnitt 4.4, mit Feldliste | — |
| `BACKEND_PRESETS` ist **nicht** die alleinige Wahrheit — `model_backend.py` trägt das Startverhalten | Abschnitt 2.1 (zwei neue Zeilen) und Abschnitt 5 | `CLIBackend.KNOWN_CLIS` Z. 708, `create_backend` Z. 952 — **bestätigt, war im Entwurf übersehen** |

Zusätzlich hat die Zweitmeinung **drei Lücken gefunden, die der Entwurf nicht kannte**. Alle
drei wurden nachgemessen und bestätigt:

1. **Kein atomarer Claim** (`chat_tray.py` Z. 567-575 gegen `worker.py` Z. 167-193). Bestätigt:
   `worker.py` nimmt `offen[0]` und startet, ohne zu beanspruchen. Das ist gefährlicher als
   alle Registerdoppelungen zusammen und steht jetzt an erster Stelle des Befunds.
2. **Rechte werden am Executor nicht erzwungen.** Bestätigt: kein zentraler Prüfpunkt. Ein
   Rechtefeld an der Rolle wäre ohne ihn bloße Dokumentation — das ändert die Reihenfolge.
3. **Die Control API kennt keinen Authentifizierungsnachweis.** Bestätigt: `_is_allowed_origin`
   (Z. 2955) prüft Herkunft, kein `Authorization`-Header im Modul. Über diese Schnittstelle
   lassen sich Slots ändern, Vollmodus-Worker starten und die Fackel umschalten.

**Eine Korrektur betraf den Ist-Befund selbst:** Der Entwurf stellte den Tray so dar, als läse
er nur `assigned_to = "OLLAMA"`. Tatsächlich fragt er `OLLAMA`, `BUDDHA` und `BACH` ab und
greift danach auf nahezu alle nicht-menschlichen Zuweisungen zurück. Abschnitt 2.4 ist
entsprechend richtiggestellt.

**Nicht übernommen wurde nichts.** Der einzige Punkt, an dem die Zweitmeinung und dieses
Dokument auseinanderliefen — ob das Cockpit eine der Festlegungen bleibt — ist zugunsten der
Zweitmeinung entschieden: Es fällt aus dem Bauumfang heraus (Abschnitt 4.5).

---

## 7. Offene Entscheidungen

Vier Festlegungen sind echte Architekturentscheidungen und werden dem Nutzer als
`decision-shot` vorgelegt, nicht hier einseitig getroffen:

1. **Wo lebt das Rollen-Register** — Datenbank oder Konfigurationsdatei?
2. **Wie wird zugeteilt** — bildet BACH die zulässige Kandidatenmenge und clutch wählt darin,
   oder entscheidet BACH allein?
3. **Welche Form hat der Backend-Katalog** — ein gehobenes Python-Modul oder eine Datendatei?
4. **Wann kommt das Cockpit** — jetzt mitbauen oder erst, wenn es etwas anzuzeigen gibt?

Die Vorlage steht im Ticket `T-20260913-896336887` unter der Kennung `BH-2026-09-13-A`.

---

## 8. Reihenfolge und Folgetickets

Die Reihenfolge ist so gewählt, dass das System zu keinem Zeitpunkt unbrauchbar ist. Jeder
Schritt ist für sich nützlich, auch wenn der nächste nie kommt.

| # | Schritt | Warum hier |
|---|---|---|
| 1 | **Eine Zuteilungsgrenze für genau einen Pfad** (Vorschlag: der Hintergrundplatz). Sie reicht die bisherige Modellwahl unverändert durch, beansprucht die Aufgabe aber atomar, prüft das Rollenrecht, erzeugt eine `assignment_id` und protokolliert Start und Ende. | Beseitigt die Doppelausführung, schafft den Protokollschreiber und legt einen Seam, an dem alles Weitere andockt — ohne das Routing anzufassen |
| 2 | **Protokoll vervollständigen**: Ereignis von Zustand trennen, Fackel-Umschaltung einbeziehen | Braucht 1 als Schreiber; danach ist jede Verbesserung belegbar |
| 3 | **Backend-Katalog vereinheitlichen**, Whitelist und `BUILTIN` darauf zurückführen, Adapterverträge getrennt halten | Hebt die Sperre auf, die heute alles außer Claude abschneidet |
| 4 | **Seams ehrlich machen**: clutch-Fallback laut, Scheduler-Seam entscheiden, Zugangsschutz der Control API | Beseitigt Stellen, an denen Ausfall wie Funktion aussieht |
| 5 | **Rolle bekommt Vertragsfelder** — Rechte und Budget (nach Entscheidung 1) | Erst sinnvoll, wenn Schritt 1 einen Prüfpunkt geschaffen hat |
| 6 | **Zuteilung verdrahten** (nach Entscheidung 2), toten Router entscheiden | Braucht 3 und 5 |
| 7 | **Cockpit** (nach Entscheidung 4, Ergebnis von `T-20260913-660268706` übernehmen) | Zeigt, was die Schritte davor erzeugt haben |

**Anfangen mit Schritt 1.** Ein erster Entwurf wollte mit dem Protokoll beginnen, weil es
ohne Nutzerentscheidung auskommt und nichts brechen kann. Die Zweitmeinung hat auf etwas
Besseres hingewiesen: Eine Zuteilungsgrenze für einen einzigen Pfad kostet kaum mehr, löst
aber zusätzlich das Korrektheitsproblem der Doppelausführung — und sie bringt den
Protokollschreiber gleich mit. Sie ist ein Strangler-Seam: Das bestehende Routing bleibt
zunächst unangetastet und wandert später Pfad für Pfad dahinter.

Die Begründung des ersten Entwurfs bleibt trotzdem gültig und gilt nun für Schritt 2: Die
Fackel-Analyse hat gezeigt, wohin es führt, wenn man Mechanik baut, bevor man sie beobachten
kann — die naheliegendste Frage des Nutzers war mit den vorhandenen Daten grundsätzlich nicht
beantwortbar.

---

*Erstellt von bachheart@ASUS-GEI im Auftrag des ticket-master, 13.09.2026.
Phase 1 — Bestandsaufnahme und Konzept, kein Umbau.*
