# TODO - ellmos BACH

## Offene Aufgaben

### [BACH-AGENT-PID-01] Agent-Stop gegen PID-Wiederverwendung absichern (OC-B-Gate)
- **Ziel:** `agent stop` darf niemals einen fremden Prozess nur wegen einer wiederverwendeten PID beenden. Die PID-Identität muss beim Start gespeichert und vor Status/Stop konsistent geprüft werden; Altdateien ohne verifizierbare Identität brauchen einen fail-closed oder explizit geprüften Migrationspfad.
- **Quelle:** `[OC-B: T-20260818-903104603; unabhängiger Review von BACH PR #65 am 2026-09-15]` — `system/hub/agent_launcher.py::_stop_agent` liest die PID direkt, während `AgentProcessRegistry.is_running` Identitätsabweichungen erkennt und PID-Dateien entfernen kann. BACHs heutige Startdateien enthalten keinen `process_identity`-Anker.
- **Akzeptanzkriterien (DoD):** Wiederverwendete PID und Identitätsabweichung stoppen keinen Prozess; Status-, JSON- und Stop-Zugänge stimmen überein; Stop-Dry-run meldet denselben Guard; Alt-PID-Verhalten ist ausdrücklich geregelt; Tests prüfen Windows- und Unix-Pfade ohne echten Agentenstart. Erst danach Opt-in-Seam auf einem Host aktivieren und Lifecycle/Parity nachweisen.
- **Prüfweg:** gezielte Agent-Handler-/Provider-Tests, echter Modul-Pin/Host-Smoke und unabhängiger Review; kein lokales Ollama.
- **Stand 2026-09-15:** BACH-seitiger PID-/Erzeugungszeit-Guard und fail-closed Altdatei-Verhalten im OC-B-Arbeitszweig umgesetzt. Unabhängiger Review des ersten Nachtrags fand weitere Lücken (Unix-Kinder, Start ohne Identitätsanker, mutierende Status/Dry-run-Bereinigung, Registry-PID-Substitution); sie wurden mit read-only Modul-Probe und BACH-Nachbesserung adressiert. 144 gezielte BACH-Tests und 70 Modul-Tests bestanden, 1 Modul-Test übersprungen. Re-Review hat weitere Hochrisiko-Reste festgestellt, siehe unten. Kein Aktivierungs- oder Release-Claim.
- **Re-Review 2026-09-15:** Hochrisiko-Rest: Spawn kann bei fehlender Birth-Erfassung einen unkontrollierbaren Prozess hinterlassen; parallele Starts überschreiben Belege mangels exklusivem Claim. Unix-Stop erfasst nur eine Kind-Momentaufnahme und löscht den Beleg ohne Abschlussnachweis; JSON-Status kann Dateiname/Record-Name verwechseln. Diese Punkte sind vor Produktiv-Opt-in/Release zu reparieren und mit Race-/Lifecycle-Tests zu belegen. Der separate Modul-Stop hat zusätzlich einen nackten PID-Signalpfad (agent-launcher TODO OC-B-PID-02).
- **Aufwand:** medium
- **Reichweite:** local
- **Priorität:** high

### [BACH-HERZ-01] Zuteilungsgrenze für einen Pfad: atomarer Claim, Rechteprüfung, Besetzungsprotokoll
- **Ziel:** Eine zentrale Stelle, durch die genau ein produktiver Pfad läuft (Vorschlag: der Hintergrundplatz `buddha_always_on`). Sie reicht die bisherige Modellwahl **unverändert** durch, beansprucht die Aufgabe aber atomar, prüft das Rollenrecht, erzeugt eine `assignment_id` und protokolliert Start und Ende. Heute nimmt `worker.py` schlicht `offen[0]` und startet ohne Anspruch, während `chat_tray.py` erst liest und danach auf `in_progress` setzt — zwei Taktgeber können dieselbe Aufgabe mit Schreibrechten ausführen.
- **Quelle:** `[Quelle: docs/MODELL-BACKEND-KONZEPT_2026-09-13.md, Abschnitte 4.2 und 8]` `[Programmkopf: ROADMAP.md "PROGRAMM: Modell-Backend = das Herz von BACH"]` `[Ticket: T-20260913-896336887]` `[Zweitmeinung: _codex/ARCHITEKTUR-ANTWORT.md, F6 und F7]`
- **Akzeptanzkriterien (DoD):**
  - Der Claim ist atomar: ein Test mit zwei gleichzeitigen Beanspruchern derselben Aufgabe führt zu genau einer Ausführung.
  - `system/hub/_services/chat/worker.py` beansprucht vor dem Start, statt `offen[0]` ungeprüft zu nehmen.
  - Jede Besetzung erzeugt eine `assignment_id` und je einen Start- und Endeintrag mit `role_id`, `agent_instance_id`, tatsächlich verwendetem `backend_id` und `model_id`, `slot_id`, `task_id` und `initiated_by`.
  - Die Modellwahl selbst bleibt in diesem Schritt unverändert — der Seam wird gelegt, nicht das Routing umgebaut.
  - Bestehende `/api/activity`-Leser brechen nicht (Rückwärtskompatibilität der Felder).
- **Prüfweg:** `python -m pytest system/tests/test_slots_and_workers.py system/tests/test_runner_safety_gates.py -v`; zusätzlich ein Nebenläufigkeitstest für den Claim.
- **Aufwand:** medium
- **Reichweite:** local
- **Priorität:** high
- **Hinweis:** Erster Schritt des Programms. Die Schritte 5 bis 7 (Vertragsfelder an der Rolle, Zuteilung verdrahten, Cockpit) bleiben bis zur Nutzerentscheidung `BH-2026-09-13-A` gesperrt.

### ✅ [BACH-HOOK-01] Hook-Prompt anpassen: Empfehlung für `bach_api.db` statt hartem Block
- **Ziel:** Den Hook-Prompt / DB-Guard-Prompt so anpassen, dass Agenten aktiv `bach_api.db` empfohlen wird, anstatt nur blockiert zu werden.
- **Quelle:** `[Quelle: ROADMAP.md:1017]` `[Ableitung: Soll/Ist-Lücke]`
- **Akzeptanzkriterien (DoD):**
  - DB-Guard Hook (`system/hooks/bach-db-guard.sh` bzw. Hook-Prompt) enthält klare Handlungsanweisung zur Nutzung von `bach_api.db`.
  - Regressionstest für Hook-Meldungen/Prompt vorhanden und grün.
- **Prüfweg:** `python -m pytest system/tests/test_db_guard_hook.py -v`
- **Aufwand:** easy
- **Reichweite:** local
- **Priorität:** medium
- **Erledigt:** 2026-09-13 – Hook-Meldung auf `bach_api` + BACH CLI + Handler-API umgestellt, 11 Regressionstests grün.

### ✅ [BACH-MCP-01] BACH MCP Server: First-class `bach mcp serve` CLI-Integration und Testsuite
- **Ziel:** Bestehenden `mcp_server.py` als vollwertiges CLI-Kommando `bach mcp serve` anbinden und dedizierte Pytest-Suite für den Server bereitstellen.
- **Quelle:** `[Quelle: ROADMAP.md:1077-1115]`
- **Akzeptanzkriterien (DoD):**
  - CLI-Befehl `bach mcp serve` startet FastMCP Server sauber über stdio.
  - Dedizierte Testdatei `system/tests/test_bach_mcp_server.py` testet Tool-Listings, Prompts und Handler-Aufrufe.
- **Prüfweg:** `python -m pytest system/tests/test_bach_mcp_server.py -v` läuft fehlerfrei durch.
- **Aufwand:** medium
- **Reichweite:** local
- **Priorität:** high
- **Erledigt:** 2026-09-13 – `mcp` auf v1.x gepinnt, `pytest-asyncio` ergänzt, alle 9 Tests grün.

### [BACH-MOD-01] Modularisierung: `tools/testing` durch `ellmos-tests`-Adapter ersetzen
- **Ziel:** Eigene Test-Tools aus `tools/testing` durch Adapter auf das externe Modul `ellmos-tests` ablösen und den Upstream-Widerspruch in `ellmos-tests-SKILL.md` auflösen.
- **Quelle:** `[Quelle: ROADMAP.md:88-90]`
- **Akzeptanzkriterien (DoD):**
  - `ellmos-tests`-Adapter in BACH integriert und einsatzbereit.
  - Widerspruch in Doku/SKILL aufgelöst.
  - Vollständige Testsuite läuft ohne Regressionen.
- **Prüfweg:** `pytest system/tests`
- **Aufwand:** large
- **Reichweite:** local
- **Priorität:** medium
