# TODO - ellmos BACH

## Offene Aufgaben

### [BACH-HERZ-01] Besetzungsprotokoll: Akteursfelder ergaenzen, Ereignis von Zustand trennen
- **Ziel:** Jede Modell-/Rollen-Besetzung und jede Umschaltung schreibt eine Protokollzeile, die den Akteur benennt. Heute traegt `record_activity` nur `source`, `activity` (Freitext) und `status` — kein Modell, kein Backend, keine Rolle, keinen Ausloeser. Deshalb war beim Fackel-Schalter nicht feststellbar, wer umgeschaltet hatte.
- **Quelle:** `[Quelle: docs/MODELL-BACKEND-KONZEPT_2026-09-13.md, Abschnitt 4.3 + 8]` `[Programmkopf: ROADMAP.md "PROGRAMM: Modell-Backend = das Herz von BACH"]` `[Ticket: T-20260913-896336887]`
- **Akzeptanzkriterien (DoD):**
  - Protokollzeile traegt mindestens `timestamp`, `platz`, `rolle`, `modell`, `backend`, `ausloeser`, `entscheidung`, `ergebnis`.
  - `hub/compute_lock.py::set_fackel_preference` schreibt einen Protokolleintrag mit Akteur (heute: kein einziger Aufruf von `record_activity`).
  - Ereignisstrom (append-only, historisch auswertbar) liegt getrennt vom Zustand; der 100-Eintraege-Ringpuffer in `data/slots_config.json` ist nicht mehr die einzige Historie.
  - Bestehende `/api/activity`-Leser brechen nicht (Rueckwaertskompatibilitaet der Felder).
- **Pruefweg:** `python -m pytest system/tests/test_slots_and_workers.py -v`; anschliessend Fackel einmal umschalten und pruefen, dass der Akteur im Protokoll steht.
- **Aufwand:** medium
- **Reichweite:** local
- **Prioritaet:** high
- **Hinweis:** Erster Schritt des Programms und der einzige, der ohne Nutzerentscheidung auskommt. Schritte 4 bis 6 (Rollenfelder, Zuteilung, Cockpit) bleiben bis zur Entscheidung `BH-2026-09-13-A` gesperrt.

### [BACH-HOOK-01] Hook-Prompt anpassen: Empfehlung für `bach_api.db` statt hartem Block
- **Ziel:** Den Hook-Prompt / DB-Guard-Prompt so anpassen, dass Agenten aktiv `bach_api.db` empfohlen wird, anstatt nur blockiert zu werden.
- **Quelle:** `[Quelle: ROADMAP.md:1017]` `[Ableitung: Soll/Ist-Lücke]`
- **Akzeptanzkriterien (DoD):**
  - DB-Guard Hook (`system/hooks/bach-db-guard.sh` bzw. Hook-Prompt) enthält klare Handlungsanweisung zur Nutzung von `bach_api.db`.
  - Regressionstest für Hook-Meldungen/Prompt vorhanden und grün.
- **Prüfweg:** `python -m pytest system/tests/test_hooks.py` bzw. manuelle Prüfung der Hook-Ausgabe.
- **Aufwand:** easy
- **Reichweite:** local
- **Priorität:** medium

### [BACH-MCP-01] BACH MCP Server: First-class `bach mcp serve` CLI-Integration und Testsuite
- **Ziel:** Bestehenden `mcp_server.py` als vollwertiges CLI-Kommando `bach mcp serve` anbinden und dedizierte Pytest-Suite für den Server bereitstellen.
- **Quelle:** `[Quelle: ROADMAP.md:1077-1115]`
- **Akzeptanzkriterien (DoD):**
  - CLI-Befehl `bach mcp serve` startet FastMCP Server sauber über stdio.
  - Dedizierte Testdatei `system/tests/test_mcp_server.py` testet Tool-Listings, Prompts und Handler-Aufrufe.
- **Prüfweg:** `python -m pytest system/tests/test_mcp_server.py -v` läuft fehlerfrei durch.
- **Aufwand:** medium
- **Reichweite:** local
- **Priorität:** high

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
