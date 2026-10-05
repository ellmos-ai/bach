# Memory Routing Mapping (Task #1447)

Mapping zwischen der GUI `/memory`-Oberfläche (`gui/server.py`) und dem CLI-Backend
`hub/memory.py` (`MemoryHandler`).

## GUI-Endpunkte und ihre `hub/memory.py`-Pendants

| # | Route | Methode | Implementierung in `gui/server.py` | `hub/memory.py`-Pendant | Rückgabe-Refaktor-Status | Paritätslücken |
|---|-------|---------|-----------------------------------|------------------------|--------------------------|----------------|
| 1 | `/memory` | GET | Statisches Template `memory.html` ausliefern | kein Pendant (reine UI) | nicht betroffen | Kein Datenbezug; Template zeigt Panel für Daten, die von anderen Endpunkten kommen |
| 2 | `/api/memory/overview` | GET | Direkt-SQL über `memory_working`, `memory_facts`, `memory_lessons`, `memory_sessions`, `memory_consolidation`, `context_triggers`, `automation_injectors`; plus Workflows aus `skills/workflows` | `--memory status` liefert nur Counts für working/facts/lessons/sessions | Offen: Zusammenführen in ein Memory-Service-Objekt | Trigger/Injectoren/Workflows/Best-Practices/Consolidation haben kein Pendant; GUI-Memory-Modell ≠ Handler-Modell |
| 3 | `/api/memory/working` | GET | Direkt-SQL SELECT `memory_working` (`is_active=1`, LIMIT) | `--memory read [n]` | Offen: Antwort-Envelope `{"entries":..., "count":...}` vom Handler ableiten | `read` filtert/aktiv-Flag unklar; kein Limit-Parameter |
| 4 | `/api/memory/lessons` | GET | Direkt-SQL SELECT `memory_lessons` (optional Kategorie) | kein Pendant (Lessons eigener Handler, nicht `hub/memory.py`) | Offen | Kategorie-Filter nicht in `MemoryHandler` |
| 5 | `/api/memory/sessions` | GET | Direkt-SQL SELECT `memory_sessions` | `--memory sessions` | Offen: Listen-Envelope angleichen | Handler nutzt gleiche Tabelle, aber unklares Spalten-/Format-Mapping |
| 6 | `/api/memory/working` | POST | Direkt-SQL INSERT `memory_working` | `--memory write "Notiz"` | Offen: JSON-Body → Handler-Args | `write` erwartet String, nicht JSON; keine Kategorie/Source |
| 7 | `/api/memory/lessons` | POST | Direkt-SQL INSERT `memory_lessons` | kein Pendant | Offen | Lessons-Handler separat einbinden oder `MemoryHandler` erweitern |
| 8 | `/api/memory/facts` | GET | Direkt-SQL SELECT `memory_facts` | `--memory facts [category] [--min-conf=...]` | Offen: Filter/Envelope | GUI ignoriert `min_conf`; Kategorie optional |
| 9 | `/api/memory/facts` | POST | Direkt-SQL INSERT `memory_facts` | `--memory fact "key:value"` | Offen: JSON key/value → Handler-Parser | Konfidenz/Source hardcoded (`1.0`, `gui`) |
| 10 | `/api/memory/facts/{fact_id}` | DELETE | Direkt-SQL DELETE `memory_facts` | kein Pendant | Offen | `MemoryHandler` hat keine Löschoperation |
| 11 | `/api/memory/working/{entry_id}` | DELETE | Direkt-SQL UPDATE `memory_working SET is_active=0` | `--memory clear` (löscht alle aktiven) | Offen | Kein einzelnes Deaktivieren/Archivieren |
| 12 | `/api/memory/lessons/{lesson_id}` | DELETE | Direkt-SQL UPDATE `memory_lessons SET is_active=0` | kein Pendant | Offen | Kein Löschen/Deaktivieren in `hub/memory.py` |
| 13 | `/api/memory/stats/db` | GET | Direkt-SQL über alle Tabellen in `bach.db` | `--memory status` (nur Memory-Counts) | Offen | `status` liefert keine `last_update` und nicht alle Tabellen |
| 14 | `/api/memory/maintenance/cleanup` | POST | Direkt-SQL (alte Einträge löschen/VACUUM) | kein Pendant | Offen | Kein Maintenance-Operation im Handler |
| 15 | `/api/memory/sessions/{session_id}` | GET | Direkt-SQL SELECT `session_memories` in `user.db` | `--memory sessions` | Offen | GUI nutzt andere DB/Tabelle (`user.db::session_memories`) als Handler (`bach.db::memory_sessions`) |
| 16 | `/api/memory/sessions` | POST | Direkt-SQL INSERT `session_memories` in `user.db` | `--memory session` (Shutdown-Report in `bach.db::memory_sessions`) | Offen | Unterschiedliches Session-Memory-Modell |

## Legende Rückgabe-Refaktor-Status

- **nicht betroffen**: Template-Route ohne Datenbezug.
- **Offen**: GUI-Route und Handler verwenden unterschiedliche Response-Formate
  bzw. unterschiedliche DB-Tabellen; bedarf Adapter/Refaktor.

## Entscheidung: Rewrite vs. Minimal-Routing-Stub

**Entscheidung für Task #1447:** Minimaler Routing-Stub/Adapter als
Sofortmaßnahme; struktureller **Rewrite** über einen OCEAN-Memory-Vertrag bleibt
erforderlich und wird in einen Folgetask verlagert.

**Begründung:**

- 13 von 16 Endpunkten greifen derzeit direkt auf SQLite zu. `hub/memory.py`
  deckt weder DELETE, Maintenance, die `memory_lessons` (eigener Handler), die
  `/api/memory/overview`-Injektoren/Workflows, noch die `user.db::session_memories`
  ab.
- Ein vollständiger Rewrite auf einen Memory-Vertrag (OCEAN/S6/S7) blockiert am
  fehlenden Gardener/Routing- und GUI-Modulschnitt; er kann nicht innerhalb von
  #1447 abgeschlossen werden.
- Ein Minimal-Stub schließt die akute Lücke: er führt eine `MemoryGUIBridge`
  ein, die die bestehenden GUI-Routen hinter sich hält und dort, wo möglich,
  `MemoryHandler`-Operationen aufruft (z. B. `read`, `write`, `facts`, `sessions`).
  Für nicht abbildbare Operationen (DELETE, Maintenance, `session_memories`)
  werden Adapter-Methoden mit direktem SQL vorgesehen und explizit als
  technische Schuld markiert.
- Langfristig (nach S6/S7) sollen alle GUI-Calls über den OCEAN-Vertrag laufen
  und die direkten SQL-Pfade entfernt werden.

**Empfohlene nächste Schritte:**

1. `MemoryGUIBridge` in `gui/memory_bridge.py` anlegen.
2. Bestehende 16 Routen auf die Bridge umstellen; Antworten in einheitliche
   Envelope überführen.
3. Tests in `tests/test_gui_memory.py` bzw. `tests/test_memory_routes.py`
   ergänzen.
4. Separate Task für den OCEAN/Rewrite anlegen, sobald S6/S7-Verträge vorliegen.
