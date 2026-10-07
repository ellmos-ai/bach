# TODO - ellmos BACH

## Offene Aufgaben

### [BACH-SEC-DEPS-01] GUI-Abhängigkeitslücken vor dem nächsten Release schließen
- **Ziel:** Die 14 offenen GitHub-Dependabot-Alerts vom 2026-10-03 abarbeiten, ohne den vorhandenen Update-PR zu duplizieren.
- **Quelle:** [PR #188](https://github.com/ellmos-ai/bach/pull/188), Alerts #29–#42 für `system/gui/web/package-lock.json`; [GHSA-ch52-4w7c-c8xp](https://github.com/advisories/GHSA-ch52-4w7c-c8xp).
- **Historischer Stand 2026-10-03:** PR #188 enthält Astro 7.3.5, sharp 0.35.5 und esbuild 0.28.2 außerhalb der betroffenen Bereiche von 13 Alerts. `http-cache-semantics` bleibt dort bei 4.2.0; für Alert #42 nennt GitHub aktuell keine gepatchte Version. Die vorhandene CI prüft keinen Astro-Build.
- **Akzeptanzkriterien:** PR #188 nach unabhängigem Review und erfolgreichem GUI-Build integrieren; verbleibenden Cache-Alert durch einen verifizierten Upstream-Fix oder eine überprüfte Entfernung des betroffenen Abhängigkeitspfads schließen. Anschließend Lockfile und GitHub-Alertstatus erneut prüfen.
- **Historisch offen 2026-10-03:** Kein Abhängigkeitsupdate integriert, keine Ausnutzbarkeit im produktiven Deployment bewiesen. Der fehlende Patch ist ein Release-Blocker und keine Risikofreigabe.
- **Nachtrag 2026-10-07:** PR #188 wurde am 2026-10-04 integriert; der aktuelle GUI-Workflow prüft Installation, Tests und Build. Auf `origin/main` `9815de1b` war nur Alert #42 offen. Das am 2026-10-06 zurückgesetzte Astro-5-Manifest widersprach weiterhin dem Astro-7-Lockfile; Neuauflösung auf Astro 5 führte wieder zu kritischen Advisories. Dieser Korrekturkandidat gleicht das Manifest auf Astro 7.3.5 ab und aktualisiert `http-cache-semantics` auf das am 2026-10-04 veröffentlichte 4.3.0. `npm ci`, acht GUI-Tests, Build mit 17 Seiten und `npm audit --package-lock-only` (0 Befunde) sind lokal grün. Ein unvollständiges Funktionsduplikat in Fabrika wurde entfernt. Integration nach Review und anschließender GitHub-Alert-Readback bleiben offen; das Audit ist kein produktiver Ausnutzbarkeitsnachweis.
- **Aufwand:** medium
- **Reichweite:** local
- **Priorität:** high

### [BACH-SEC-ROTATE-01] Widerruf des früher offengelegten GUI-Gerätetokens belegen
- **Ziel:** Die im GUI-Deploymentbericht genannte frühere Token-Offenlegung operativ abschließen. Das Entfernen aus Quelltexten und Builds widerruft ein Credential nicht.
- **Quelle:** `system/gui/GUI_DEPLOYMENT_RECEIPT_2026-10-03.md`, Abschnitt „Verbleibende Grenzen“; Release-Privacy-Audit vom 2026-10-03.
- **Akzeptanzkriterien:** Verbraucher und zuständige Geräteidentität lokal zuordnen, Ersatz sicher hinterlegen, den Alt-Token widerrufen und dessen Ablehnung sowie den gültigen Ersatz prüfen. Nur redigierte Ergebnisbelege speichern, keine Tokens oder Token-Hashes.
- **Offen:** Aktueller Widerruf- und Verbraucherstand ist nicht verifiziert. Dieser Quellcode-Audit hat keine produktiven Geräte oder Zugangsdaten geändert.
- **Nachtrag 2026-10-07:** Weiterhin kein redigierter Widerrufbeleg im aktuellen Quellstand gefunden. Release-Gate bleibt offen; Identität und Verbraucher müssen vor einem gezielten Widerruf zugeordnet werden.
- **Aufwand:** medium
- **Reichweite:** local
- **Priorität:** high


### ✅ [BACH-HERZ-01] Zuteilungsgrenze für einen Pfad: atomarer Claim, Rechteprüfung, Besetzungsprotokoll
- **Ziel:** Eine zentrale Stelle, durch die genau ein produktiver Pfad läuft (Vorschlag: der Hintergrundplatz `buddha_always_on`). Sie reicht die bisherige Modellwahl **unverändert** durch, beansprucht die Aufgabe atomar, prüft das Rollenrecht, erzeugt eine `assignment_id` und protokolliert Start und Ende.
- **Quelle:** `[Quelle: docs/MODELL-BACKEND-KONZEPT_2026-09-13.md, Abschnitte 4.2 und 8]` `[Programmkopf: ROADMAP.md "PROGRAMM: Modell-Backend = das Herz von BACH"]` `[Ticket: T-20260913-896336887]` `[Claim-Ticket: T-20260913-709822598, PR #59]` `[Zweitmeinung: _codex/ARCHITEKTUR-ANTWORT.md, F6 und F7]`
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
- **Erledigt:** 2026-09-14 – `agents_heart.py` legt den versionierten Rechtevertrag und Assignment-Seam; `worker.py` claimt vor dem Start und schreibt korrelierte Start-/Endereignisse; bestehende Aktivitätsfelder bleiben flach verfügbar. Verifiziert mit 58 fokussierten Tests, `py_compile`, Ruff und `git diff --check`.


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

### ✅ [BACH-MOD-01] Modularisierung: `tools/testing` durch `ellmos-tests`-Adapter ersetzen
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
- **Erledigt:** 2026-09-14 auf WORKSTATION-LG gegengeprüft — Adapter-Vertrag
  `15 passed`, externer QUICK-Lauf `8/8` B-Tests erfolgreich, nativer
  Rollbackpfad `B001 + O001` jeweils 5,0/5; BACH-Task 1218 abgeschlossen.
