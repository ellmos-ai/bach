# Modell-Backend und dessen Verwaltung — das neue Herz von BACH

**Programmkopf, Phase 1: Bestandsaufnahme und Architekturkonzept**
Stand: 13.09.2026 · Gemessen gegen `origin/main`, Commit `1bb8fa4` · Ticket `T-20260913-896336887`

> **Auftrag des Nutzers (Originalwortlaut, maßgeblich, 13.09.2026):**
> „wichtigste Neuerung in Bach ist aktuell Modell backend und dessen verwaltung. Das wird das
> neue Herz von Bach. Sprich bach wird lebendig, wer spielt wann welche der Rollen und Agenten usw."

Dieses Dokument beantwortet Phase 1: Was ist heute da, was fehlt, und wie sähe die Anlage aus,
die „wer spielt wann welche Rolle" beantwortbar macht. **Es wird nichts umgebaut.** Der
Umbau folgt in Folgetickets, die am Programmkopf in `ROADMAP.md` andocken.

Der Nutzer hat den Umfang am selben Tag zweimal erweitert: Das Cockpit sei „ein Knoten", der
**mit den anderen Systemen verbunden** werden müsse (Kapitel 9), und das Herz solle **für BACH
und OCEAN gemeinsam** entwickelt werden — Arbeitsname `ocean-heart` beziehungsweise
`agents-heart`, samt Tray, Rücktransfer aus drei Schwestersystemen sowie den Konzepten Fackel,
Muschelgrund und Trithon (Kapitel 10). Beide Erweiterungen sind eingearbeitet.

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
9. [Der Systemverbund: ein Herz über mehrere Rechner](#9-der-systemverbund-ein-herz-über-mehrere-rechner)
10. [ocean-heart: das gemeinsame Herz von BACH und OCEAN](#10-ocean-heart-das-gemeinsame-herz-von-bach-und-ocean)

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
| Fackel bei unmessbarer Kapazität | `fackel.py::frei` Z. 186-204, Rückgabe `float(FACKELN)` | **fail-open** | meldet volle zehn Fackeln, wenn nichts gemessen werden konnte. Lokal ein weicher Vorfilter; im Verbund bietet ein Host damit Kapazität an, die er nicht kennt |
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

`:8081/activity` ist die Oberfläche des Modell-Backends. Der Menüumbau aus Ticket
`T-20260913-660268706` ist **inzwischen gemergt** (PR #51, Commit `823823b`) und beim
Zusammenführen dieses Branches übernommen worden: `gui/static/js/nav.js` führt den Eintrag
„Models" jetzt unter „Agenten" und zeigt auf `portRel: 8081, path: "/activity"`. Das Cockpit
ist damit aus der GUI erreichbar, ohne dass diese es nachbaut — genau die Form, die Abschnitt
10.5 auch für OCEAN empfiehlt.

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

Zwei Runden unabhängiger Architektur-Zweitmeinung durch **Codex `gpt-5.6-sol`, Stufe `high`**,
read-only im selben Worktree. Auftrag und Antwort je Runde liegen als
`_codex/ARCHITEKTUR-FRAGEN.md` / `-ANTWORT.md` und `-FRAGEN-2.md` / `-ANTWORT-2.md` im Repo;
die vollständige Einarbeitungstabelle steht in `_codex/ZWEITMEINUNG-EINARBEITUNG.md`.

**Alle Einwände beider Runden wurden übernommen**, jeweils erst nachdem die zugrunde liegenden
Gegenbehauptungen am Quellcode nachgemessen waren.

**Vier davon widerlegten eigene Aussagen dieses Dokuments** — sie sind in der
Einarbeitungsdatei einzeln als solche markiert:

| Eigene Aussage | Was die Messung ergab |
|---|---|
| `BACKEND_PRESETS` sei die einzige Modell-Wahrheit | `model_backend.py` trägt zusätzlich das Startverhalten je CLI — eine fünfte Liste |
| clutch wisse nichts über Rollen und Rechte | `fahrer.py`, `getriebe.py`, Prompt-Typen `rolle` und `agent` — zu stark formuliert |
| Das Inventar trage je Host rund 14 KB | 14 bis 143 KB, und der `network`-Block steht nur in einer der vier Dateien |
| OCEANs Lokalitätsschranke stehe dem Verbund entgegen | sie erlaubt Tailscale — kein Hindernis |

Die übrigen Einwände änderten die Architektur, ohne eine Messung zu widerlegen: vier Begriffe
statt zwei, Gate vor Auswahl, Ereignis getrennt vom Zustand, Fackeln und Budget als zwei
Achsen, die Schreibfähigkeit des Boards, das Fail-open der Fackel, der fehlende
Dispatch-Vertrag und die Verengung des Herzens auf C\*.

**Attributionsbeleg Runde 1.** Rollout `rollout-2026-09-13T12-04-37-01a09a39-…jsonl`, Feld
`"model":"gpt-5.6-sol"`, 42 ausgeführte Befehle. `codex_run_proof.py --contains
"import agent_router|scheduler_provider"` meldet `BELEGT`. Für Textinhalte ist das Skript nicht
zuständig — es durchsucht ausgeführte Befehle, nicht Antworttexte.

---

## 7. Offene Entscheidungen

**Vier** Festlegungen sind echte Architekturentscheidungen und werden dem Nutzer als
`decision-shot` vorgelegt:

1. **Wo lebt das Herz** — BACH-intern, als Erweiterung von clutch, oder als enges eigenes
   Modul, das BACH und OCEAN beide konsumieren? Empfehlung C\*, Abschnitt 10.2.
2. **Wo lebt das Rollen-Register** — Datenbank oder Konfigurationsdatei? Abschnitt 4.1.
3. **Welche Form hat der Backend-Katalog** — ein gehobenes Python-Modul oder eine Datendatei?
   Abschnitt 5.
4. **Wie heißt das Herz** — `agents-heart`, `ocean-heart` oder `ocean-control`, und steht es
   neben dem ControlRoom oder darin? Abschnitt 10.2.1.

### 7.1 Vier Fragen, die keine Entscheidung mehr sind

Ein Zwischenstand dieses Dokuments legte acht Fragen vor. Die Zweitmeinung hat vier davon als
Scheinfragen zurückgewiesen, und der Einwand trägt: Eine Frage, die im selben Dokument mit
Begründung beantwortet wird, dem Nutzer aber trotzdem als offen vorgelegt wird, ist keine
Beteiligung, sondern eine Rückdelegation. Sie stehen hier als **Feststellung**, nicht als Wahl:

| Frage | Warum sie entschieden ist |
|---|---|
| Wie wird zugeteilt? | Abschnitt 4.2: Gates bilden die Kandidatenmenge, clutch wählt darin. Ein nachträgliches Veto vergiftet die Lernschleife — das ist ein technisches Argument, keine Vorliebe |
| Wann kommt das Cockpit? | Abschnitt 4.5: erst, wenn es etwas anzuzeigen gibt. Es ist ein Abnehmer, kein Erzeuger |
| Welche GUI-Richtung gilt? | `D-20260830-002` hat sie entschieden, `D-20260903-001` setzt sie bereits um. Der Nutzer hat gefragt, ob seine neue Idee besser ist — die Antwort in Abschnitt 10.5 ist nein, mit Begründung. Eine bestehende Entscheidung erneut zur Wahl zu stellen, wäre eine stille Umkehr |
| Woher kommen Hosts und Modelle? | Falsches Entweder-oder. Alle drei werden gebraucht: das Inventar findet Hosts, die Probe am Ziel klärt die aktuelle Zulässigkeit, clutch bewertet Modelle. Abschnitt 9.4 nennt das Kriterium, das sie trennt |

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

**Zwei weitere Schritte kommen aus Kapitel 10 hinzu** (Herz herauslösen, OCEAN als zweiter
Konsument), beide nach Schritt 4. Sie ändern an dieser Reihenfolge nichts, legen den Schritten
1 bis 4 aber eine Auflage auf: Was dort gebaut wird, muss BACH verlassen können. Siehe
Abschnitt 10.7.

---

## 9. Der Systemverbund: ein Herz über mehrere Rechner

> **Nutzerhinweis (live, Wortlaut, 13.09.2026):** „sehr gut und das muss halt dann noch
> verbunden werden mit den anderen systemen"

Das Cockpit auf dem Mac ist **ein Knoten**, nicht das System. Ein Modell-Backend, das nur eine
Maschine kennt, beantwortet die Frage „wer spielt wann welche Rolle" nur für diese Maschine.
Dieses Kapitel misst, was an Verbund heute wirklich existiert — und was nur Begriff ist.

### 9.1 Vorab-Korrektur: Das Cockpit liegt bereits in `origin/main`

Eine Ticketnotiz hielt fest, die Seite „BACH Aktivitätsanzeige & Worker Dashboard" liege im
Mac-Stand und **nicht** in `origin/main`. **Das ist nachgemessen falsch.** Sie liegt dort:

| Merkmal | Fundstelle in `origin/main` |
|---|---|
| Seitentitel, wörtlich wie beschrieben | `telegram_chat.py:1519` — `<title>BACH Aktivitätsanzeige & Worker Dashboard</title>` |
| Überschrift | `telegram_chat.py:1591` |
| Fackel | 20 Vorkommen im Modul |
| Always-On-Schalter | 6 Vorkommen |
| „Neuer Worker" | 4 Vorkommen |
| Verlauf | 8 Vorkommen |
| Verlinkung aus dem Chat-Dashboard | `telegram_chat.py:1336` |

Der Unterschied zwischen Mac und `origin/main` mag in Einzelheiten bestehen, aber die
Grundlage ist gemeinsamer Stand. **Das Konzept baut darauf auf und ersetzt es nicht.**

### 9.2 Was an Verbund gebaut ist — und was nur ein Wort ist

| Baustein | Zustand | Beleg |
|---|---|---|
| **Systemregister — die Ableitung** | dünn, **absichtlich** | `.SYNC/_inventory/systems-registry.json`, 631 Byte: vier Hosts mit `hostname`, `role`, `slot`, teils `active` |
| **Systemregister — die Quelle** | **reich**, und das war im ersten Anlauf übersehen | `.SYNC/_inventory/systems/<slot>.json`, je Host rund 14 KB: `system` mit Chip, Kernen, RAM, GPU, Speicher; `network` mit LAN-Adresse, **Tailscale-Adresse, SSH-Schlüssel, offenen Ports**; dazu `software`, `mcps`, `skills`, `agents` (14 Einträge), `venvs`, `services_dir` |
| **Ableitungsregel** | aktiv, fail-closed gegen Handpflege | `ticket-master/lib/systems_registry.py::build_snapshot` Z. 69-120, Docstring Z. 11-16: „DERIVED, never authored". Es extrahiert bewusst nur `hostname`, `slot`, `role` und `active` (Z. 101-107) |
| **PingPong** | **real gebaut**, läuft | Skill `pingpong` v1.1.0, Laufzeitskript `scripts/pingpong_runtime.py` mit eigenen Tests, Modi ListenSync/WriteSync, Anbieteradapter für Codex und Claude Code; Betriebsspuren als datierte Übernahme- und Kadenz-Deltas in `.SYNC/` |
| **„Routing v2"** | **existiert — aber für etwas anderes** | Es ist der **Ticket**-Routing-Vertrag des `ticket-master`: `lib/ticket_writer.py:84` („Routing schema v2 needs a system-registry snapshot"), `:862` und `:901` (`--systems-registry` ist für Schema v2 Pflicht), `lib/systems_registry.py`, Vertrag dokumentiert im CHANGELOG ab 22.08.2026. Er entscheidet, **welcher Host ein Ticket bekommt** — kein Nachrichten- oder Modelltransport |
| **clutch hostübergreifend** | **halb** | `clutch/motorblock.py:296-303` (`_ziel_url`) löst den Endpunkt eines Gangs auf, sonst liefe ein Remote-Gang gegen `localhost`; `clutch/discovery.py:68-84` liest die Umgebungsvariable `CLUTCH_REMOTE_OLLAMA` als zusätzliche Basis-URLs |
| **clutch als zentraler Resolver** | **nein** | clutch kennt weder `systems-registry.json` noch die Hostnamen; einzige Fundstelle ist die Modul-Metadatendatei, nicht der Code. Pro Host läuft eine eigene Instanz |
| **agent-launcher** | eigenständiges Modul, real | Repo `ellmos-ai/agent-launcher`, Klon `C:/_Local_DEV/repos/agent-launcher`; `agent_launcher/providers.py:25` — `PROVIDERS = ("claude", "codex", "agy", "kimi")`, `UNVERIFIED_PROVIDERS = {"kimi"}` |
| **Fackeln je Host** | vorgesehen, gemessen | Die Zahl zehn ist überall gleich, die Größe einer Fackel folgt der Maschine — genau die Eigenschaft, die den Verbund trägt (`system/docs/TORCH-KONZEPT.md`) |

**Die wichtigste Einzelfeststellung dieses Kapitels betrifft „Routing v2".** Ein erster Anlauf
fand den Begriff nirgends und erklärte ihn für nicht existent; die Gegenprüfung des
Zwei-Modell-Reviews hat ihn gefunden. Er existiert — **aber er routet Tickets, nicht Modelle.**
Als Transport für eine Besetzungsentscheidung taugt er nicht, und wer ihn dafür einplant, plant
mit dem falschen Ding. Der Transport, der nachweislich läuft, ist **PingPong**.

Was von „Routing v2" trotzdem zu lernen ist: Es ist der einzige gebaute Mechanismus im System,
der **eine Zuteilungsentscheidung über Rechner hinweg trifft und dafür das Systemregister
liest** (`--systems-registry` ist dort Pflicht). Die Besetzungszuteilung steht vor derselben
Aufgabe. Bevor dafür etwas Neues entsteht, gehört dieser Vertrag gelesen.

### 9.3 Wie der Verbund aussieht

Die Begriffe aus Kapitel 4 tragen über Rechnergrenzen, wenn man einen einzigen hinzufügt:

> **Der Ort ist Teil des Agentenprofils, nicht der Rolle.**

Eine Rolle wie „Rechercheur" ist hostunabhängig. Das Agentenprofil `qwen3.8:27b-mlx auf ollama
am Mac` ist es nicht — es trägt den Host, und damit trägt es auch dessen Fackeln, dessen
Compute-Lock und dessen Erreichbarkeit. Daraus folgt die Verbundlogik fast von selbst:

1. **Das Rollenregister ist gemeinsam.** Ein Vertrag gilt auf allen Rechnern gleich. Wäre er es
   nicht, hieße dieselbe Rolle auf zwei Maschinen Verschiedenes.
2. **Die Kandidatenmenge ist hostabhängig.** Jeder Host prüft seine eigenen Fackeln, seinen
   eigenen Vorrangschalter, seine eigenen Rechenjobs. Was auf dem Mac nicht passt, kann auf der
   Workstation passen.
3. **Die Zuteilung bleibt lokal, die Kandidaten werden entfernt.** Kein zentraler Verteiler, der
   von außen über fremde Maschinen verfügt — das wäre eine Buchhaltung über Zustände, die er
   nicht misst, und damit derselbe Fehler, den das Fackel-Dokument verbietet. Stattdessen fragt
   der zuteilende Host die anderen: *was hättest du frei?* Die Antwort ist eine Messung.
4. **Das Besetzungsprotokoll trägt den Host.** Ohne `host` im Eintrag ist „wer spielte um 10:34"
   auf einem Mehrrechnersystem nicht beantwortbar.
5. **Der Transport ist PingPong**, bis etwas Besseres nachweislich existiert. Es ist gebaut,
   getestet, hat Anbieteradapter und hinterlässt Betriebsspuren.

### 9.4 Zwei Funde, die die Lückenanalyse korrigieren

**Erstens: Das Systemregister ist nicht zu dünn — seine Quelle ist reicher, aber uneinheitlich.**
Ein erster Anlauf sah nur `systems-registry.json` mit vier Feldern und schloss auf eine Lücke.
Unter `.SYNC/_inventory/systems/<slot>.json` liegt tatsächlich mehr: `mac-studio.json` trägt
Chip, Kerne, RAM, GPU, **Tailscale-Adresse, SSH-Schlüssel und offene Ports**. Die schmale
Registry ist eine bewusste Ableitung daraus (`build_snapshot`, „DERIVED, never authored").

**Ein zweiter Anlauf verallgemeinerte das zu früh.** Nachgemessen über alle vier Dateien:

| Datei | Größe |
|---|---|
| `mac-studio.json` | 14 KB |
| `surface.json` | 44 KB |
| `laptop.json` | 81 KB |
| `workstation.json` | 143 KB |

Die Datei, aus der die Feldliste stammt, ist also die **kleinste**, und der `network`-Block mit
der Erreichbarkeit steht nicht überall. `surface.json` ist zudem vom Mai. Wer aus einer Stichprobe
auf den Bestand schließt, misst die Stichprobe.

Damit verschiebt sich die Lücke ein drittes Mal, und erst jetzt stimmt sie: Es fehlt nicht das
Datum und nicht der Filter, sondern **ein Schema**. Die Quelle braucht Versionierung, Herkunft,
Messzeitpunkt und einen Zustand `unknown`, bevor eine Ableitung mehr durchreichen darf. Ohne das
reicht sie Felder durch, die auf einem Host stimmen und auf dem nächsten fehlen.

**Und ein Eintrag im Inventar ist kein Beleg für Erreichbarkeit.** Die Dateien tragen
`_gepflegt_von` und `_gepflegt_hinweis`, sind also handgepflegt. Eine Adresse dort heißt
*dort nachsehen*, nicht *dort läuft der Dienst*.

**Das Kriterium, das die Grenze zieht** (aus der Zweitmeinung übernommen, weil es schärfer ist
als „statisch gegen flüchtig"):

> Handgepflegte Daten dürfen **Absicht, Identität und mögliche Topologie** beschreiben. Alles,
> dessen aktueller Wahrheitswert über **Zulässigkeit, Sicherheit oder Erfolg eines konkreten
> Starts** entscheidet, wird am Zielsystem frisch gemessen.

Die Probe dazu: Könnte eine veraltete Angabe einen unzulässigen Start, einen Datenabfluss,
verdrängte Ressourcen, Doppelarbeit oder eine falsche Quittung verursachen? Dann darf sie nicht
alleinige Grundlage der Zulassung sein. Gelesen werden dürfen Host- und Platzidentität,
Vertrauenszone, Hardwareklasse als Vorauswahl, Adresse und Schlüsselpfad **als Probenziel**,
sowie erlaubte Anbieter. Gemessen werden müssen Erreichbarkeit, Anmeldung, tatsächlich
startbare Modelle, freie Fackeln, Compute-Lock, laufende Jobs und am Ende der tatsächlich
verwendete Anbieter samt Modell.

Ein menschliches Verbot bleibt davon unberührt: Eine Freigabe oder Sperre ist Richtlinie und
wird durch keine Messung überstimmt.

**Zweitens: Ein Besetzungsprotokoll über Rechner hinweg existiert bereits.** Der
Ticket-Routing-Vertrag führt je Zielsystem ein Ledger, und jede Zeile trägt eine Quittung mit
Pflichtfeldern (`routing_contract.py::_RECEIPT_FIELDS` Z. 988-991):

```
signature · status · executed_by · actual_provider · actual_model · occurred_at · evidence
```

**`executed_by`, `actual_provider` und `actual_model` sind genau die Frage „wer hat gespielt" —
und zwar das tatsächliche Modell, nicht das gewünschte.** `record_receipt` (Z. 1041-1053)
verweigert unvollständige Quittungen und nimmt sie nur unter passendem Anspruch an; die
Ledger-Zustände sind `pending`, `claimed`, `done`, `blocked`.

Das ändert die Aufgabe: Es ist **kein neues Protokollvokabular zu erfinden**. Aber — und hier
hat die Zweitmeinung einen Kurzschluss korrigiert — **den Vertrag zu übernehmen heißt nicht,
ihn zu benutzen.**

Es sind zwei zusammenhängende, aber verschiedene Zustandsmaschinen:

1. **Transport:** Welcher Host hat das Ticket angenommen? Dateibasiert, seltene Übergaben,
   Anspruch durch Umbenennen der Vertragsdatei.
2. **Besetzung:** Welche Rolle wurde auf welchem Platz mit welchem Agentenprofil tatsächlich
   gestartet und beendet? Häufig, lokal, für Chats, Plätze, Scheduler-Läufe und Worker.

`claimed` im Transportvertrag **ersetzt den lokalen Claim nicht**: Ein Host kann ein Ticket
korrekt übernommen haben, während die Ausführung dort noch gar nicht zugelassen, noch nicht
gestartet oder bereits abgebrochen ist. Eine dateibasierte Umbenennung ist außerdem die falsche
Granularität für einen Fünf-Sekunden-Takt.

Daraus folgt konkret:

- Bei einem Ticket aus dem Routing-Vertrag **benutzt** BACH den vorhandenen Vertrag und
  beansprucht **vor** der lokalen Ausführung.
- Die lokale Aufgabe braucht **zusätzlich** einen atomaren Vergleichen-und-Setzen-Anspruch in
  ihrem eigenen Aufgabenspeicher.
- `assignment_id`, `run_id` und `ticket_id` verbinden beide Ebenen.
- Am Ende eines Laufs entsteht **eine** versionierte Ausführungsquittung, aus der der
  Ticket-Adapter die vorhandenen Felder befüllt.
- `executed_by` muss dabei präzisiert werden: Im Transportvertrag meint es den Runner; die
  Besetzung braucht zusätzlich Agenteninstanz, Rolle, Rollenrevision, Platz und Host.

Sauberste Form wäre ein kleines **gemeinsames Anspruchs- und Quittungspaket**, das der
ticket-master und das Herz beide konsumieren — statt einer Abhängigkeit des Herzens von
Ticketdateien.

---

## 10. ocean-heart: das gemeinsame Herz von BACH und OCEAN

> **Nutzerauftrag (live, Wortlaut, maßgeblich, 13.09.2026):** „ja zumindest sollte es für beide
> zusammen entwickelt werden weiter also das ocean-heart oder so könnten wir es nennen oder
> ocean-control oder würde es in ocean zum ControlRoom gehören? Entwickle aus dem bereits
> bestehenden Bachelementen wie dem tray und einstellungs/activity board sowie routinen und
> wartungsbereichen aus bach ein gemeinsames Konzept für ocean-heart bzw. agents-heart. In
> diesem Zuge auch FolderHome NemoFold und SentinelFleet Rücktransfer mit einplanen. Außerdem
> Fackelkonzept übernehmen und Muschelgrund und Trithon Konzept einplanen. Ocean soll auch
> einen Tray bekommen wie Bach […] Bei der GUI könnte als Idee unified gui der Unterbau werden
> […] Aber wir hatten bzgl. GUI schon viele Entscheidungen […] deshalb nur diese neue Idee
> verwenden wenn sie besser ist als bisherige Ideen Umsetzungen und Entscheidungsrichtungen."

### 10.1 Warum ein gemeinsames Herz überhaupt möglich ist

Gemessen an OCEAN (`C:/_Local_DEV/repos/open-ocean`, 150 grüne Tests, kein Releaseschema,
`PRIVATE.txt`-Sperre aktiv):

| Fähigkeit | BACH | OCEAN |
|---|---|---|
| Modell-/Backend-Verwaltung | fünf Listen, aber gebaut | **keine** (null Treffer für Ollama, Modell-Register) |
| Rollen-/Agentenmodell | 27 Rollen in der DB, ohne Modell | **keins** |
| Tray | gebaut (`chat_tray.py`) | **keiner** |
| Activity-Cockpit | gebaut (`:8081/activity`) | **keins** |
| Scheduler | Legacy gebaut, Seam vorbereitet | **keiner** — konsumiert `ellmos-scheduler` als externen Anbieter |
| GUI | gebaut (`:8000`) | **keine** — bindet `unified-gui.host` ein |
| Bundle-/Rezeptwesen | — | **gebaut** (Resolve, Verify, Fetch/Place, Activate) |

**Was OCEAN stattdessen hat, und warum es nicht dasselbe ist** (nachgemessen):

| Fundstelle | Was sie tut | Warum sie kein Modell-Backend ist |
|---|---|---|
| `tools/ocean_lifecycle.py::select_runtime_provider` Z. 123-140 | wählt **eine** aufgelöste Komponente, die `runtime.host` bereitstellt | generisch, aber es gibt nur einen Anbieter: `_ellmos_core_runtime_spec` Z. 348-357 wirft bei allem außer `ellmos-core` |
| `validate_model_locality`, definiert in `ellmos-core/src/ellmos_core/config.py:98-114` | erzwingt private statt öffentlicher Inferenz; `_validate_local_endpoint` Z. 117-141 erlaubt Loopback, private und link-lokale Adressen **sowie den Tailscale-Bereich `100.64.0.0/10`** | eine Schranke, keine Auswahl — aber **kein Hindernis für den Verbund**, siehe unten |
| Rollen | nur `admin` und `user` (`ocean.py:169`, `ocean_lifecycle.py:968`, `runtime_user.py:14`) | Zugriffsstufen, keine Aufgabenverträge |
| `tools/host_adapters.py` Z. 55-65 | anbieterneutrale Abstraktion für den Aktivierungsschritt | genau **ein** Adapter registriert: `ClaudeCodeHostAdapter` (Z. 78-162); Codex, agy und Kimi nennt der Docstring als später |

`validate_model_locality` verdient besondere Beachtung: Sie ist die einzige Stelle im
Ökosystem, an der **Modellwahl und Ort bereits verknüpft** sind.

**Ein Entwurf dieses Kapitels las sie als Widerspruch zum Verbund. Das war falsch.** Sie
verlangt nicht „Modell auf demselben Rechner", sondern private statt öffentlicher Inferenz:
`_validate_local_endpoint` lässt neben Loopback auch private, link-lokale und ausdrücklich
Tailscale-Adressen zu (`ellmos-core/src/ellmos_core/config.py:139-141`). **Ein Ollama auf dem
Mac Studio über Tailscale besteht die vorhandene Prüfung bereits.** Verboten bleiben öffentliche
Ziele und, wo nur lokale Modelle erlaubt sind, Cloud-Anbieter.

Für das Herz reicht die Prüfung trotzdem nicht: Eine private Adresse belegt weder Vertrauen
noch Echtheit, und auch über Tailscale verlässt der Prompt den Ursprungsrechner. Der Ort gehört
deshalb dreistufig modelliert — `derselbe Host`, `vertrauter Verbund`, `außerhalb` — und die
Schranke wird nicht entfernt, sondern zum **harten Vorfilter der Kandidatenmenge** erweitert.

**Das bevorzugte Muster ist nicht der Fernaufruf, sondern der Auftrag:** Das Herz schickt eine
beglaubigte, korrelierte Ausführungsanforderung an den Zielhost; dieser misst seine Fackeln und
Ansprüche **selbst**, ruft sein Ollama über Loopback auf und quittiert das tatsächlich
verwendete Modell samt der eigenen Messung. So bleibt „gemessen, nicht gebucht" erhalten, weil
jeder Host das misst, was nur er wissen kann. Ein direkter Fernaufruf bleibt möglich, aber nur
als ausdrücklich erlaubter Verbundpfad mit Verschlüsselung, Dienstanmeldung und Datenfreigabe.

**Das Bild ist eindeutig und macht die Frage leicht:** OCEAN hat für dieses Thema nichts, was
BACH doppeln würde. BACH hat alles, was OCEAN fehlt. Es geht also nicht um eine Zusammenführung
zweier Implementierungen, sondern um **eine Herauslösung aus BACH, die OCEAN mitbenutzen kann.**
Das ist genau das Muster, das der Nutzer für die GUI bereits entschieden hat (siehe 10.5).

### 10.2 Wo lebt das Herz — die eigentliche Frage

Der Nutzer fragt nach dem Namen. Dahinter liegt die schwerere Frage, und sie entscheidet mehr:
**Wird das Herz ein BACH-internes Bauteil, eine Erweiterung von clutch, oder ein eigenes
Modul, das BACH und OCEAN beide konsumieren?**

Zwei gemessene Sätze aus OCEANs eigener README geben die Richtung vor:

> „The governing rule is a conservation law: **extraction changes the bed, never the water.**"
> (`open-ocean/README.md:69`)

> „**BACH stays supplied by consuming the same modules as OCEAN**; any later move to LTS,
> freeze, or archive remains an explicit product decision, never an automatic consequence of
> this plan." (`open-ocean/README.md:76`)

Die zweite ist eine Erhaltungsregel für BACH: Es bleibt versorgt, **indem** es dieselben Module
konsumiert. Ein BACH-internes Herz verstößt dagegen — es wäre Wasser, das im alten Bett bleibt,
während alles andere umzieht.

| Option | Dafür | Dagegen |
|---|---|---|
| **A — BACH-intern** | kürzester Weg, alles liegt schon dort | verstößt gegen die Erhaltungsregel; OCEAN müsste es später doch extrahieren, und dann unter Last |
| **B — clutch erweitern** | clutch ist bereits der Modellrouter, provider-neutral, mit Budget und Lernschleife | es fehlen ihm die kanonischen Rollenverträge, Plätze und hostübergreifenden Ansprüche; es wüchse um eine fremde Achse |
| **C — eigenes Modul**, das BACH und OCEAN konsumieren | folgt der Erhaltungsregel; BACH wird erster Konsument, OCEAN zweiter; clutch bleibt Router und wird konsumiert statt erweitert | **in der breiten Fassung selbst ein Monolith** — siehe die Einschränkung unten |

**Eine Korrektur an der eigenen Darstellung von clutch.** Der erste Entwurf schrieb, clutch
wisse nichts über Rollen und Rechte. Nachgemessen ist das zu stark: clutch hat `fahrer.py` als
Orchestrator, `getriebe.py` als anbieterneutrales Modellregister, Team-, Schwarm- und
Kettenmuster, Profile und in `prompt_library.py:20` die Typen `rolle` und `agent`; die
Standard-Verweigerung bei Werkzeugsätzen ist eine Rechtevorstufe. Was clutch **fehlt**, sind
kanonische Rollenverträge, Plätze und hostübergreifende Ansprüche — nicht der Begriff Rolle.
Option B bleibt trotzdem die schlechtere: Diese drei Achsen sind nicht die eines Routers.

**Und eine Korrektur an Option C.** So wie sie oben steht — Rollenregister, Backend-Katalog,
Zuteilung, Protokoll, Fackel, Wartung, Board und Tray in einem Modul — wäre sie genau der
Monolith, den dieses Dokument anderswo beklagt, und tatsächlich ein drittes Register. Die
Roadmap gibt dafür auch keine Deckung: Sie sagt ausdrücklich, dass Cluster keine
vorentschiedenen Paketnamen sind und ein eigenes Repository nur bei einer klaren Schnittstellen-
und Zustandsgrenze gerechtfertigt ist.

**Die tragfähige Fassung ist eng (C\*):**

| Gehört ins Herz | Bleibt draußen, als Anschluss |
|---|---|
| Zustandsmaschine für Besetzung und Lauf | Modellkatalog, Bewertung, Budget, Lernschleife → **clutch** |
| atomarer Anspruch und Zulassung | Ausführung → **agent-launcher** und die Backend-Adapter |
| Besetzungsprotokoll | Hosts und Ressourcen → **Inventar plus lokale Proben** |
| genau **ein** kanonischer Rollenspeicher | Anzeige und Bedienung → **Board und Tray als Klienten** |

Der **Backend-Katalog gehört ausdrücklich nicht** ins Herz — er bleibt dort, wo er hingehört,
und wird konsumiert. Ein Modul ist nicht automatisch ein Register; zum Register wird es erst,
wenn es fremde Wahrheiten kopiert.

**Die Extraktions-Roadmap von OCEAN stützt C und widerspricht einer Einordnung als
Kernaufgabe:** `architecture/BACH-EXTRACTION-ROADMAP.md` behandelt **Cluster 9** als System-,
Daten- und Betriebskern (Registry, `dbsync`, `snapshot`, Lifecycle) und priorisiert ihn zuerst.
Ein Modell-Backend-Paket steht dort **nicht** — gemessen per Volltextsuche über den Cluster.
LLM- und Mehr-Agenten-Orchestrierung ist ausdrücklich **Cluster 5** (Z. 198). Das Herz gehört
damit nicht in den zuerst gezogenen Kern, sondern in einen eigenen, späteren Cluster. Die
Roadmap kennt dafür auch den Ausnahmeweg: „A valuable BACH-only component may still be
extracted, but that is an exception with its own gate."

**Empfehlung: C\* — ein enges eigenes Modul**, das nur Besetzung, Anspruch, Zulassung und
Protokoll besitzt; BACH wird erster Konsument, clutch bleibt Router und wird konsumiert. Das
Mac-Worker-Dashboard auf `:8081` ist die **BACH-seitige Referenzimplementierung**, die später
extrahiert wird — nicht der künftige Ort des Herzens.

### 10.2.1 Und wie heißt es?

Der Nutzer fragt: `ocean-heart`, `ocean-control`, oder gehört es in OCEANs ControlRoom?

**Gemessen zum ControlRoom** (`.TOPICS/.AI/.MODULES/.CONTROL/controlroom/`, kein Repo, nur
Entwurfsdokumente): Er definiert sich selbst als Governance- und Kompositionsebene mit dem
ausdrücklichen Satz **„Kein Modul-Neubau. Backend = die Module, Frontend = unified-gui."**
Entscheidung `D-20260817-002` hält fest: Oberfläche über dem bestehenden `_control-center`,
**kein Nachfolger**; `D-20260817-006`: keine neue Datenhaltung. Die Umsetzungsschritte M2 bis
M4 sind gesperrt.

Ein Herz aus Backend-Katalog, Rollenregister, Zuteilung und Besetzungsprotokoll ist eine
**Laufzeitfunktion mit eigener Datenhaltung**. Es ist damit genau das, was der ControlRoom
ausdrücklich nicht sein will. **Es gehört nicht in den ControlRoom, sondern ist eines der
Module, die der ControlRoom später referenziert.** Das ist keine Ablehnung der Idee des
Nutzers, sondern ihre Auflösung: Der ControlRoom zeigt es an, er ist es nicht.

Zum Namen: `ocean-control` kollidiert begrifflich mit `_control-center` und ControlRoom — drei
Dinge mit „Control" im Namen, die Verschiedenes sind, ist eine Verwechslung mit Ansage.
`agents-heart` beschreibt, was es tut (es besetzt Rollen mit Agenten), und bindet es nicht an
ein Produkt — was richtig ist, weil BACH, OCEAN und die Hackathon-Systeme es alle benutzen
sollen. **Empfehlung: `agents-heart`.** Die Entscheidung liegt beim Nutzer (`BH-2026-09-13-A`,
E5).

### 10.3 Was aus BACH herausgelöst wird

Der Nutzer nennt vier Bausteine. Gemessen an ihrem heutigen Zustand:

| Baustein aus BACH | Heute | Im Herz |
|---|---|---|
| **Tray** (`chat_tray.py`) | 1278+ Zeilen, hält Single-Instance-Lock, pollt alle 5 s, löst Rollen auf, führt Aufgaben aus, schaltet die Fackel | **Zu viel für einen Tray.** Er ist heute Anzeige *und* Taktgeber *und* Ausführer. Herausgelöst wird der Tray als **Anzeige und Bedienung**; das Zuteilen wandert in die Zuteilungsgrenze aus Schritt 1 |
| **Activity-Board** (`:8081/activity`) | gebaut, gut, siehe 9.1 | wird die Oberfläche des Herzens — unverändert übernommen, nicht neu gebaut |
| **Routinen** (`hub/routine.py`) | **gated**: `domain_writer_gate` sperrt die Domäne `routine`, Kanon ist Routinika | **nicht** mitnehmen. BACH besitzt diese Domäne nicht mehr; sie ins Herz zu ziehen hieße, eine abgegebene Zuständigkeit zurückzuholen |
| **Wartung** (`hub/maintain.py`, `tuev.py`, `health.py`) | gebaut | als **Prüfbereich** des Herzens: Sind die Backends erreichbar, stimmen die Register, laufen Waisen? Das ist dieselbe Frage wie „wer spielt gerade", nur mit anderem Blickwinkel |

**Der OCEAN-Tray.** Der Nutzer will ihn ähnlich, zunächst nahezu gleich, und BACH soll ihn
später gebrandet übernehmen („Bach B"). Das funktioniert nur, wenn der Tray **nicht** zweimal
gebaut wird. Die Reihenfolge ergibt sich aus dem Befund: Weil BACHs Tray heute drei Aufgaben
vermengt, wäre eine Kopie eine Kopie des Problems. Richtig ist: erst die Zuteilung aus dem Tray
herauslösen (Schritt 1 des Programms), dann bleibt ein schlanker Anzeige-Tray übrig — **und
genau der ist der, den OCEAN bekommt und BACH umbrandet.**

### 10.4 Fackel, Muschelgrund, Trithon

**Das Fackel-Konzept** wird übernommen: Die Zahl zehn gilt überall gleich, die Größe einer
Fackel folgt der Maschine. Das ist die verbundfähige Form — ein Maß, das auf einem größeren
Rechner dieselbe Sprache spricht.

**Die Fackel-Implementierung wird es nicht unverändert.** Hier ist zwischen Konzept und Code zu
trennen, sonst entsteht ein Widerspruch zu Abschnitt 10.8: `_services/fackel.py` hängt an
`hub._services.limits`, ist auf Ollama und Apple-Silicon-Proben zugeschnitten und meldet bei
nicht messbarer Kapazität volle zehn Fackeln. Sie wandert als hostlokale **Ressourcenprobe**
hinter einer neutralen Schnittstelle heraus, und `unbekannt` muss dabei fail-closed werden.

**Muschelgrund** und **Trithon** stammen aus dem Architekturentwurf
`.SYNC/ARCHITEKTURENTWURF_OCEAN_LEAD_HOST_TRITHON.md` (08.09.2026). **Beide sind Entwurf, nicht
abgenommen**: Das zugehörige Ticket `T-20260908-362639245` steht auf `USER/freigabe`, und ein
Nachtrag verlangt Autoritätsmatrix, Split-Brain-Negativtests und einen Feld-für-Feld-Abgleich,
bevor irgendetwas gebaut wird. Dieses Konzept plant sie deshalb **als Anschlusspunkte ein, ohne
sie vorauszusetzen**:

- **Trithon** ist die Zweiweg-Engine des Ticket-Ökosystems, dazu ein Lead-Trithon als
  Millisekunden-Atomreferenz für die Salt-Mechanik gegen Wettläufe beim Cloud-Abgleich.
  **Das ist dieselbe Frage wie der fehlende atomare Claim aus Befund 1** — nur eine Ebene
  höher. Wer den Claim baut, sollte die Salt-Mechanik kennen, damit nicht zwei verschiedene
  Antworten auf dasselbe Problem entstehen. **Anschlusspunkt, kein Vorgriff.**
- **Muschelgrund** ist Modus A des Gedächtnisses: eine kanonische Datenbank auf einem
  Leitrechner, gegen die alle Knoten abgleichen; Modus B wäre dezentral mit
  `sqlite-transit-sync`. Für das Herz ist das die Frage, **wo das Rollenregister lebt, wenn es
  mehrere Rechner gibt** — dieselbe Entscheidung E1, nur im Verbund. Sie wird nicht hier
  vorweggenommen.

Der Entwurf hält beide ausdrücklich getrennt („Aufgaben sind nicht Wissen"). Das Herz fügt eine
dritte Achse hinzu — **Besetzung ist weder Aufgabe noch Wissen** — und darf mit keiner der
beiden verschmolzen werden.

### 10.5 Die GUI-Frage: ist die neue Idee besser?

Der Nutzer bittet ausdrücklich darum, seine neue Idee nur zu verwenden, wenn sie besser ist als
die bestehenden Entscheidungen. Also gemessen.

**Bestehende Entscheidungen:**

- `D-20260830-002` (30.08.2026): Der Nutzer verwarf die drei vorgelegten Optionen und wählte
  eine eigene: *„mein favorit wäre das die Bach-Version ein neutrales Modul wird das dann sowohl
  bach als auch unified gui importieren, sodass es keinen drift gibt"*.
- `D-20260903-001`: bereits umgesetzt — PR #15 gemergt, `assistant-core v0.1.0` herausgelöst,
  der GUI-Server darauf umgestellt. Das Muster läuft also schon.
- `D-20260817-007`: Die ControlRoom-Konsole wird eine Web-Oberfläche mit eigenem Port.

**Die neue Idee** lautet: unified-gui als Unterbau, darauf eine OCEAN-GUI, die BACHs Oberfläche
mit OCEAN-Modulen im Rücken nachbaut; BACH könnte später auf diese Ansicht umschalten.

**Die bestehenden Richtungen gegen die neue Idee:**

| Frage | Bestehende Entscheidung | Neue Idee | Besser? |
|---|---|---|---|
| Wer hält die Fachfunktionen? | neutrales Modul, von beiden importiert (`D-20260830-002`, Option D des Nutzers) | OCEAN-Module im Rücken einer nachgebauten Oberfläche | **nein** — dasselbe Ziel, aber die Module werden nicht geteilt, sondern gespiegelt |
| Wie viele Oberflächen? | eine, von beiden konsumiert | zwei, eine davon Nachbau | **nein** — zwei Oberflächen driften |
| Ist es schon im Gang? | ja: `assistant-core v0.1.0` extrahiert, GUI-Server umgestellt (`D-20260903-001`, PR #15) | nein, wäre ein Neuanfang | **nein** |
| Bekommt OCEAN eine eigene Ansicht? | nicht ausgeschlossen, aber nicht adressiert | ja, ausdrücklich | **ja** — das ist der Teil, der fehlt |
| Konsole des ControlRoom | Web-Oberfläche mit eigenem Port (`D-20260817-007`) | nicht berührt | unverändert |

**Urteil: die neue Idee ist nicht besser, sondern derselbe Gedanke mit einem Risiko mehr.**
Beide wollen, dass BACH und OCEAN dieselbe Oberfläche benutzen. Der Unterschied liegt im Wort
*nachbauen*: Eine nachgebaute Oberfläche ist eine zweite Oberfläche, und zwei Oberflächen
driften — genau das, was der Nutzer am 30.08. ausschließen wollte („sodass es keinen drift
gibt"). Die bereits laufende Extraktion erreicht dasselbe Ziel ohne diesen Schritt.

**Was aus der neuen Idee aber zu übernehmen ist:** der Gedanke, dass OCEAN eine eigene Ansicht
bekommt. Nur eben als **Ansicht auf dieselben Module**, nicht als Nachbau. Dann ist „BACH
schaltet auf ocean-view um" kein Umbau, sondern eine Einstellung — und `D-20260830-002` bleibt
unangetastet.

### 10.6 Rücktransfer aus den drei Schwestersystemen

Der Nutzer nennt FolderHome, NemoFold und SentinelFleet. Gemessen, mit einem wichtigen
Vorbehalt: **zwei der drei stehen unter Sperre.**

| System | Zustand | Was zurückkommt |
|---|---|---|
| **FolderHome** | aktiver Team-Lock (`LOCK.team.ASUS-GEI.txt`, Endabnahme), nur lesend | **Das Modellschema.** `contracts/strands_agent.py:130-150` und `application/local_app.py:717-720` unterscheiden bereits `local_ollama_host` von `remote_ollama_host` und verlangen außerhalb der Loopback-Adresse eine ausdrückliche Zustimmung. Das ist exakt die Verbundfrage aus Kapitel 9 — dort gelöst, hier offen |
| **SentinelFleet** | `LOCK.user.agentic-judging-no-push.txt`, **weiterhin aktiv**, nur lesend. **Kein Enddatum:** `LOCK_FALLS_NOT_BEFORE 2026-09-01` (Z. 10) ist eine Untergrenze, keine Zusage; die Bedingung ist die belegte Gewinnerbekanntgabe (Z. 13-18), fail-closed, vorzeitige Entfernung nur durch den Nutzer (Z. 21). Wer ein Ablaufdatum nennt, misst falsch | **Die Aufsichtsebene.** Es hat eine Flottensteuerung mit `TaskMaster State`, `Swarm Conductor` und Dashboard gebaut. Wichtig: Sein Modellrouter ist laut eigenem Docstring nur *„based on clutch"*, kein Import — die eigene Skill-Datei sagt ausdrücklich, ein Routing-Algorithmus existiere dort nicht. Zurückzuholen sind also **Muster**, nicht Code |
| **NemoFold** | kein lokaler Klon, eigenes Repo; Entscheidung `D-20260909-001` offen: *„gebündelter Vertragslücken-Audit in vorhandenen Komponenten, kein Neubau von drei Modulen"* | **Das Belegprinzip:** exakte Fundstellen, umkehrbare Aktionen, begrenztes Schlussfolgern hinter einem lokalen Datenschutz-Gatter. Für das Besetzungsprotokoll ist „exakte Fundstelle" genau die richtige Messlatte |

**Wie Rücktransfer hier funktioniert, ist bereits präzedenzhaft geklärt.** Ticket
`T-20260913-744071825`: Ein Verfahren aus FolderHome — eine hashgebundene Einmal-Freigabe —
wurde **unter aktivem Lock gelesen, nicht kopiert**, als Muster in den Freigabe-Ablauf des
ticket-master übertragen und mit einem Herkunftsvermerk im Code versehen; das
Beitrags-spezifische wurde ausdrücklich verworfen. **Das ist die Form: Verfahren zurückholen,
keine Fachlogik, Herkunft vermerken, Sperren achten.**

### 10.7 Was sich dadurch am Programm ändert

Nichts an der Reihenfolge aus Kapitel 8, und das ist der Punkt. Die Schritte 1 bis 4 —
Zuteilungsgrenze, Protokoll, Backend-Katalog, ehrliche Seams — sind genau die, die ein
herauslösbares Herz ergeben. Sie werden nur mit einer zusätzlichen Auflage versehen:

> **Was in den Schritten 1 bis 4 gebaut wird, wird so gebaut, dass es BACH verlassen kann.**
> Keine Importe aus `hub/` in die neuen Bausteine, keine Annahme, dass es genau eine Datenbank
> gibt, kein fest verdrahteter Hostname.

Das kostet in diesen Schritten fast nichts und erspart später eine zweite Extraktion. Es ist
dieselbe Auflage, unter der `assistant-core` bereits herausgelöst wurde.

Zusätzlich kommen zwei Schritte hinzu, beide **nach** Schritt 4:

| # | Schritt | Abhängig von |
|---|---|---|
| 8 | **Herz herauslösen** als eigenes Modul (Rollenregister, Backend-Katalog, Zuteilung, Besetzungsprotokoll, Fackel), BACH wird sein erster Konsument | Schritte 1–4, Entscheidung E1 und E5 |
| 9 | **OCEAN wird zweiter Konsument**, bekommt den schlanken Anzeige-Tray; BACH brandet denselben Tray um | Schritt 8; OCEANs Publikationssperre beachten |

Der Rücktransfer aus den drei Schwestersystemen ist kein eigener Schritt, sondern eine
**Lesepflicht vor** den Schritten 1 und 8: Wer die Zuteilungsgrenze baut, liest vorher
FolderHomes Modellschema; wer das Herz herauslöst, liest vorher SentinelFleets Aufsichtsebene.
Beide Systeme stehen unter Sperre — lesen ist erlaubt, übernehmen nur als Muster mit
Herkunftsvermerk.

### 10.8 Extraktionspfade: Tray, Board, Fackel

OCEANs Erhaltungsregel gibt die Form vor: *extraction changes the bed, never the water* —
Umbau darf die Funktion nicht verändern, und funktionale Parität ist dort ausdrücklich die
Messlatte für eine Freigabe, keine Zierde. Für die drei Bausteine heißt das je etwas anderes:

| Baustein | Heutiger Zustand | Was vor der Extraktion passieren muss | Was danach umzieht |
|---|---|---|---|
| **Tray** (`chat_tray.py`) | Anzeige **und** Taktgeber **und** Ausführer in einem Prozess; hält den Einzelinstanz-Lock, pollt im Fünf-Sekunden-Takt, löst Rollen auf, führt aus, schaltet die Fackel | **Schritt 1 des Programms.** Solange das Zuteilen im Tray steckt, extrahiert man den Taktgeber mit — und OCEAN bekäme eine Kopie des Doppelausführungsproblems | der schlanke Anzeige- und Bedienteil; BACH brandet denselben um |
| **Board** (`:8081/activity`) | gebaut, vollständig, seit PR #52 in `main`; die GUI verlinkt es seit PR #51 unter „Agenten" | **es liest nicht nur.** Es schaltet die Fackel und legt Worker an, startet, stoppt und löscht sie per POST. Vor der Extraktion braucht es einen beglaubigten Befehlsvertrag und eine Berechtigungsprüfung | die Seite als **Klient** einer Abfrage- und Befehlsschnittstelle |
| **Fackel** (`_services/fackel.py`) | 16 Tests, misst statt zu buchen, Zahl zehn überall gleich, Größe folgt der Maschine | **mehr als gedacht.** Sie importiert `hub._services.limits` (Z. 33), hängt an `BACH_FACKEL_KAPAZITAET_MB`, ist auf Ollama und Apple-Silicon-Proben zugeschnitten — und meldet bei nicht messbarer Kapazität **volle zehn Fackeln** (`frei()`, Rückgabe `float(FACKELN)`) | als hostlokale **Ressourcenprobe** hinter einer neutralen Schnittstelle |

**Die Fackel ist entgegen dem ersten Entwurf nicht unverändert extraktionsreif.** Ihr
Verhalten bei unmessbarer Kapazität ist *fail-open*: Sie meldet alles frei. Lokal ist das als
weicher Vorfilter erklärbar — im Verbund ist es gefährlich, denn dann bietet ein Host einem
fremden Zuteiler Kapazität an, die er nicht gemessen hat. **Für den Verbund muss `unbekannt`
zu *nicht zulässig* führen, nicht zu *alles frei*.**

**Und vor allen dreien fehlt etwas.** Die Reihenfolge Fackel, Board, Tray stimmt relativ, aber
sie setzt einen Vertrag voraus, den es noch nicht gibt: Kennungen und Zustandsmaschine für
Besetzung und Lauf, atomarer Anspruch und Zulassung, Rechteprüfung am Ausführenden, die
Anschlüsse für Rollen, clutch, Hostprobe, Ausführung und Ereignissenke, die Orts- und
Sicherheitsgrenze, **genau ein Eigentümer des Zustands**, dazu Paritäts- und Fehlertests. Das
ist OCEANs eigene Regel „contract before code".

Die belastbare Reihenfolge lautet damit:

1. **Vertrag** plus ein produktiver BACH-Pfad mit atomarem Anspruch (= Schritt 1 des Programms)
2. **Fackel** als hostlokale Ressourcenprobe hinter neutraler Schnittstelle, `unbekannt`
   fail-closed
3. **Ereignisprojektion** und beglaubigte Abfrage- und Befehlsschnittstelle
4. **Board** als Klient dieser Schnittstelle
5. **Tray**, nachdem Takt, Zuteilung und Ausführung daraus entfernt sind

Wer in umgekehrter Reihenfolge anfängt, extrahiert das Problem statt der Funktion.

**Der Ausnahmeweg ist vorgesehen und muss benannt werden.** OCEANs Roadmap sagt: Ein wertvoller
BACH-eigener Baustein darf extrahiert werden, „but that is an exception with its own gate."
Das Herz ist ein solcher Fall — es steht nicht im zuerst gezogenen Cluster 9, sondern gehört
zu Cluster 5. Die Extraktion braucht also ein eigenes Tor, keine stille Mitnahme.

---

---

*Erstellt von bachheart@ASUS-GEI im Auftrag des ticket-master, 13.09.2026.
Phase 1 — Bestandsaufnahme und Konzept, kein Umbau.*
