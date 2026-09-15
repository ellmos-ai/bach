# TODO - ellmos BACH

## Offene Aufgaben

### [BACH-CHAT-ERR-01] Gemeldete Backend-Abbrüche in allen Chat-Pfaden als Fehler verbuchen
- **Ziel:** Auch Backends mit `manages_own_tools=True` dürfen ein Ergebnisdict mit `error` nicht als erfolgreiche Teilantwort oder History `ok=true` melden.
- **Quelle:** `[Ticket: T-20260915-960653188]` `[PR: #67 und #69]` `[USMC-Lesson: 99]`
- **Status:** Providerlose Regression am #67-Alt-Head rot; `FailedAnswer`-Fix 9db1133 und Integration 15b10e8 gepusht, 202 fokussierte Tests grün. Neue Heads und echter Host-/HTTP-Pfad sind noch nicht abgenommen.
- **Akzeptanzkriterien (DoD):** Unabhängiger Re-Review der neuen Heads; Antwort und persistierte History bleiben bei gemeldetem Abbruch fehlgeschlagen, Teilinhalt nur Abbruchkontext; zulässiger Mac-/HTTP-Receipt ohne Produktiv-Opt-in; danach Main-Merge.
- **Priorität:** high

### [BACH-TEST-BOOT-01] Private Slot-Konfiguration vor strikten API-Integrationstests initialisieren
- **Ziel:** Der sichere pytest-Pfad aus Testisolations-PR #63 muss die private `slots_config.json` vor Control-API-Tests auch auf Disk bootstrappen. BACH-Module dürfen nicht vor conftest/Env-Isolation importiert werden.
- **Quelle:** `[Ticket: T-20260915-107799375]` `[PR: #63]` `[USMC-Lesson: 98]`
- **Nachweis:** Synthetischer Audit-Checkout #69 + #63: ohne Bootstrap 304 bestanden und 8 strikte API-Tests rot; ausschließlich im Audit-Worktree ergänzter Temp-Bootstrap ergab 312 bestandene Tests und grünen Home-/Checkout-Wächter. Keine Änderung am gesperrten #63-Worktree.
- **Akzeptanzkriterien (DoD):** Lock-Eigner ergänzt Temp-Bootstrap, Regression und README im #63-Branch; kanonischer Repo-Root-Testpfad ist grün und schreibt weder in `~/.bach` noch in Checkout-Runtime; PR-Review, Merge und erneuter Integrationslauf folgen.
- **Priorität:** high

### [BACH-HERZ-01] Zuteilungsgrenze für einen Pfad: atomarer Claim, Rechteprüfung, Besetzungsprotokoll
- **Ziel:** Eine zentrale Stelle, durch die genau ein produktiver Pfad läuft (Vorschlag: der Hintergrundplatz `buddha_always_on`). Sie reicht die bisherige Modellwahl **unverändert** durch, beansprucht die Aufgabe atomar, prüft das Rollenrecht, erzeugt eine `assignment_id` und protokolliert Start und Ende.
- **Quelle:** `[Quelle: docs/MODELL-BACKEND-KONZEPT_2026-09-13.md, Abschnitte 4.2 und 8]` `[Programmkopf: ROADMAP.md "PROGRAMM: Modell-Backend = das Herz von BACH"]` `[Ticket: T-20260913-896336887]` `[Claim-Ticket: T-20260913-709822598, PR #59]` `[Zweitmeinung: _codex/ARCHITEKTUR-ANTWORT.md, F6 und F7]`
- **Nachzertifizierter Teilstand:** PR #59/2cfda653 ist gemergt; `worker.py` nutzt `bach task claim` vor dem Start, `chat_tray.py` nutzt den claim-aware API-Pfad. Im isolierten Audit bestanden 14 Tests einschließlich zweier konkurrierender Claimants. Dies belegt den Code-Seam, nicht einen produktiven Doppelstarter-Receipt; Rollenrecht, `assignment_id`, Besetzungsprotokoll und Host-Abnahme fehlen weiter.
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
- **Hinweis:** Der erste Claim-Seam ist umgesetzt. Die Schritte 5 bis 7 (Vertragsfelder an der Rolle, Zuteilung verdrahten, Cockpit) bleiben an die dokumentierte Nutzerentscheidung `BH-2026-09-13-A` und deren konkrete Freigabegrenzen gebunden.

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
