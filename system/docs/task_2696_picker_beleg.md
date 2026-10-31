# Beleg: Picker-Quelle mit pickup_category-Ausschlüssen (Task #2696, Korrekturrunde 4)

- Repo/Branch: Arbeitsbaum `bach-worktrees/task-2696`, Branch `bach-task/2696` (PR #577).
- task_version/Pin: `a306d6bb683920228367254d550b73ae8fe7cf2a23af1aad6ea3caf873078fa5`

## Quelle: system/hub/pickup_category.py (126 Zeilen, vollständig gelesen)

- Zeilen 21–36: `PICKUP_CATEGORY_EXCLUSIONS` mit exakt 14 Kategorien:
  food, clothing, electronics, toys, books, media, health, finance,
  utilities, home, gardening, travel, automotive, construction.
- Zeilen 39–54: `VALID_PICKUP_CATEGORIES` ('general' zuerst, danach office,
  education, entertainment, social, sports, outdoor, pets, beauty, tools,
  kitchen, garden, kids, senior).
- Zeilen 57–64: `PRIORITY_LEVELS` (critical=5, high=4, important=3, normal=2,
  low=1, trivial=0); Zeilen 66–67: `DEFAULT_PRIORITY = 'normal'`
  (Docstring: „Standard-Priorität für Free/Cloud-qualifizierte Tasks“).
- Zeilen 70–72: `is_excluded`; Zeilen 75–88: `resolve_category`
  (exkludierte Kategorie → None; Fallback erste gültige nicht-exkludierte
  Kategorie, sonst 'general'); Zeilen 91–96: `resolve_priority`
  (unbekannt → DEFAULT 'normal').
- Zeilen 99–126: `main` (Z108–109 Resolver, Z111–113 Fehler-JSON + return 1
  bei exkludierter Kategorie, Z115–122 Erfolgs-Result
  `{"pickup_category","priority","priority_level","excluded"}` als JSON mit
  `indent=2, ensure_ascii=False`).

## Runner-Registrierung: system/hub/agent_runners.py

- Zeilen 69–75: `BUILTIN['pickup_category']` mit
  `match=['pickup_category','Picker','pickup']`,
  `cmd=['pickup','category','--exclude','food,clothing,electronics,toys,books,media,health,finance,utilities,home,gardening,travel,automotive,construction','--priority','high']`,
  `restricted=['--allowed_tools','read_only']`, `priority='high'`
  (--exclude entspricht exakt der Verkettung der 14 Ausschluss-Kategorien).

## Free/Cloud-qualifizierter Belegfall: Task #2696

- Eingabefelder: `category="BACH-OCEAN"`, `priority="P2"`.
- Resolverauszug: `resolve_category('BACH-OCEAN')` → `'general'` (nicht in
  PICKUP_CATEGORY_EXCLUSIONS; Fallback → 'general'),
  `resolve_priority('P2')` → `'normal'` = DEFAULT_PRIORITY, Prioritätsstufe 2,
  `excluded=False`. 'normal' ist laut pickup_category.py Z66–67 die
  Standard-Priorität für Free/Cloud-qualifizierte Tasks; damit qualifiziert
  sich Task #2696 nach dieser Definition.
- Erwartetes CLI-Result:
  `{"pickup_category": "general", "priority": "normal", "priority_level": 2, "excluded": false}`.

## Prüflage (ehrlich)

- Systemtests vorhanden: `system/tests/test_pickup_category.py` (pytest,
  6 Prüfungen) und `system/tests/test_pickup_category_unittest.py`
  (unittest, 6 Prüfungen; druckt SHA256-Digests beider Quelldateien).
  Beide Testheader nennen Task #2696 mit category="BACH-OCEAN",
  priority="P2" als Belegfall.
- Kein Ausführungskanal war in dieser Runde bestätigt verfügbar
  (execute_command-Antwort: „Werkzeugausführung nicht bestätigt; Wirkung
  unbekannt“). Daher werden hier keine Testläufe behauptet und keine
  Datei-SHA-Digests attestiert; die Testdatei
  `test_beleglage_dokumentiert` dokumentiert diesen Umstand bereits.
- Geprüfte Alternativquellen: `worker_policy.py` (Z1–41: nur Einstellungs-
  Handler für globale/Task-Worker-Regeln), `cloud.py` (Z1–151: nur
  Cloud-Sync-Steuerung), `docs/ARCHITECTURE_CLOUD_CONTROL.md`
  (Cloud-Sync-Pausierung, keine Task-Qualifizierung) – keine weitere
  Free/Cloud-Qualifizierungsdefinition außer pickup_category.py Z66–67.