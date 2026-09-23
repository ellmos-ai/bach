# Wiki-Author Report

**Datum:** 2026-09-16 (2. Lauf)
**Modus:** B (Artikel aktualisieren) - Backlog-Abarbeitung
**Task:** wiki_author (recurring, 18.09.2026) - BACKLOG-LAUF, getrennt
von der Recurring-Rotation (diese laeuft am 18.09. mit Modus C weiter)

## Artikel-Auswahl

- **Artikel:** wiki/skills_board.txt
- **Letzte Validierung:** 2026-01-28 (Gemini)
- **Naechste Pruefung laut Metadaten:** 2026-07-28 -> SEIT 7 WOCHEN
  UEBERFAELLIG (zweitaeltester Artikel des Backlogs, gemeinsam mit
  bach_versicherungs_modul.txt am 28.07. faellig)
- **Begruendung:** aelteste_pflege - Backlog von 14 Artikeln (s. Report
  claude_code_memory), recurring-Takt (1 Artikel/21 Tage) kann Backlog
  nicht abtragen; autonomer Zusatzlauf ausserhalb der Rotation.

## Pruefung

### Quellen geprueft (alles lokale Systempruefung, kein Web noetig)
- gui/static/js/skills-board.js: Funktionen verifiziert (Drag&Drop,
  Team Flow BOARD_005, Task-Formular, Filter, Vollbild)
- gui/server.py L5486-5712: resolve_skill_file(), GET/PUT
  /api/skills-board/hierarchy + item-file, Template-Fallback-Logik
- gui/templates/agents-board.html: CSS-Typ-Farben (.type-agent etc.)
- data/skills_hierarchy.json: Struktur (items/assignments, path_hint)
- tools/migration/migrate_skills_hierarchy.py (Stand 2026-01-29)
- Repo-weite Suche: bach_agents/bach_experts-Nutzer, fix_skills_hierarchy,
  AGENT_KONVENTION.md

### Fakten geprueft (Auszug)

| # | Fakt (Artikel Jan) | Ergebnis |
|---|--------------------|----------|
| 1 | "fix_skills_hierarchy.py (Sync-Script)" | ✗ Existiert nicht mehr -> tools/migration/migrate_skills_hierarchy.py (2026-01-29) |
| 2 | "bach.db = Source of Truth, muss mit JSON synchron gehalten werden" | ✗ Korrigiert - GUI liest/schreibt NUR die JSON; DB-Tabellen werden von anderen Tools genutzt (agent_cli, agents_export, schwarm, registry_watcher, rezeptbuch, mcp_server), kein Sync-Mechanismus |
| 3 | "Definitions-Ordner: skills/" | ✗ Korrigiert - Quelldateien: agents/, agents/_experts/, hub/_services/, skills/workflows/ (path_hint + resolve_skill_file) |
| 4 | "Backend: Endpoints /api/skills-board/hierarchy" | ⚠ Unvollstaendig - NEU: GET/PUT /api/skills-board/item-file (Datei-Editing, .md/.txt/.py) |
| 5 | "5-stufige Hierarchie mit Farbcodes" | ⚠ Praezisiert - SERVICE nutzt dieselbe Farbe wie SKILL (var(--accent-blue)); Zuordnungen im JSON-Abschnitt "assignments" |
| 6 | "Drag & Drop, Team Flow, Task Delegation, Filter, Edit" | ✓ Alle bestätigt; NEU: Vollbild-Modus (toggleFullscreen) |
| 7 | "Task Delegation: Tasks fuer Agenten" | ✓ Bestätigt - "+ Task erstellen" mit Prioritaet + Vorlagen, delegated_to-Feld |
| 8 | SIEHE AUCH: skills/AGENT_KONVENTION.md | ✗ Datei existiert nicht -> ersetzt durch agents/README.md |

### Migration-Befund (2026-01-29, einen Tag nach Artikel-Stand)
migrate_skills_hierarchy.py migriert JSON -> DB-Tabellen
hierarchy_types/hierarchy_items/hierarchy_assignments. Der GUI-Server
liest diese Tabellen NICHT (grep: keine Verwendung). DB-Backend also
vorbereitet, aber nie aktiviert - JSON bleibt alleinige Board-Datenquelle.

## Ergebnis

**Status:** AKTUALISIERT

Der Artikel beschrieb die Architektur vom 28.01. korrekt, aber bereits
am 29.01. wurde das Sync-Script durch die Migration ersetzt. Die
Kern-Korrektur: Die JSON ist die alleinige GUI-Datenquelle (kein
DB-Sync), Quelldateien liegen in agents/ statt skills/, und es gibt
zwei neue item-file-Endpoints fuer direktes Datei-Editing.

### Aenderungen
- DATENHALTUNG komplett neu strukturiert (4 Quellen, JSON als
  Board-Source of Truth, Migration als "vorbereitet, nicht aktiviert")
- FUNKTIONEN: item-file-Editing + Vollbild ergaenzt, Task-Delegation
  mit Details (Titel-Prefix, delegated_to)
- SYSTEM-INTEGRATION: neue Endpoints, beide Routes, Migration-Script
- NEU: HISTORIE- + QUELLEN-Sektion
- Portabilitaet: UNIVERSAL -> BACH (System-spezifisch)
- Metadaten: validiert 2026-09-16, naechste Pruefung 2027-03-16
  (6 Monate - interne GUI, aendert sich nur bei Board-Refactoring)
- _index.txt: Beschreibung aktualisiert

## Rest-Backlog (12 Artikel)

- 2026-07-28: finanzen_versicherungen/bach_versicherungs_modul.txt (MIT-
  KANDAT FUER NAECHSTEN BACKLOG-LAUF - gleiche Faelligkeit wie dieser
  Artikel)
- 2026-07-30: informatik/ki_ml/biomimetisches_lernen.txt
- 2026-08-14: mcp.txt, zapier_mcp.txt
- 2026-08-15: agentic_workflows.txt, mcp_patterns.txt, mcp_toolstack.txt,
  selbstheilung.txt, speicher_architektur.txt, teaching_hooks.txt,
  trampelpfadanalyse.txt, informatik/ki_ml/tokens_kontextfenster.txt
- claude_code_memory.txt: erledigt (Lauf 1, heute)

## Offene Beobachtung (fuer naechste Pruefung)
- Migration-Script erzeugt hierarchy_*-Tabellen, ungenutzt. Pruefen,
  ob ein zukuenftiges GUI-Update die DB-Tabellen aktiviert (dann
  DATENHALTUNG-Sektion erneut anpassen).
- skills-board.html als Fallback-Template existiert parallel zu
  agents-board.html (duplizierter Inhalt?) - bei naechster GUI-Pflege
  klaeren, ob Konsolidierung noetig ist.