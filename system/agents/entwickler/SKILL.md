---
name: entwickler-agent
version: 0.2.0
type: agent
author: Gemini
created: 2025-12-29
updated: 2026-09-17
anthropic_compatible: true
status: active

orchestrates:
  experts: []
  services: []

dependencies:
  tools: [coding-tools, desktop-commander]
  services: []
  workflows: []

description: >
  Autonomer Software-Entwicklungs-Agent fuer BACH. Verwaltet Projekte,
  bearbeitet Tasks, analysiert und generiert Code. Integriert
  Entwicklungsschleife Advanced für KI-gestützte Entwicklung.
---
============================================================
ENTWICKLER-AGENT V0.2.0
============================================================

Autonomer Software-Entwicklungs-Agent

> 🤖 Selbstständige Projekt- und Task-Verwaltung mit Code-Entwicklung

---

KERNFUNKTIONEN
--------------

[✅ Phase 1 (IMPLEMENTIERT)]

- Projekt-Management: Projekte erstellen, laden, verwalten
- Task-Management: Tasks hinzufügen, priorisieren, abarbeiten
- Status-Reporting: Übersicht über Projekte und Tasks
- Persistenz: JSON-basierte Datenhaltung

[⏳ Phase 2-6 (GEPLANT)]

- Code-Analyse (via coding-tools)
- Service-Integration (Editor, Compiler)
- Testing
- Deployment

[✅ Entwicklungsschleife Advanced (INTEGRIERT)]

Pfad: `SOFTWARE/prio3/A3 Entwicklungsschleife Advanced/entwicklerschleife_advanced_v3.py`

KI-gestützte Software-Entwicklung mit automatischer Phasen-Transition:

| Phase | Rolle | Funktion |
|-------|-------|----------|
| Planer | Architektur | Analysiert Anforderungen, plant Struktur |
| Coder | Implementierung | Generiert Code nach Plan |
| Checker | Qualität | Prüft, testet, verbessert |

Features:

- Automatische Phasen-Transition (kein manueller Button)
- Professioneller Editor mit Zeilennummern
- Robuste API-Integration mit Retry-Logik
- Dark Mode GUI
- Multi-Language: Python, JavaScript, TypeScript, Java, C++, C#, Go, Rust, Ruby, PHP, Swift, Kotlin

Verwendung:
python entwicklerschleife_advanced_v3.py

---

VERWENDUNG
----------

[Programmatisch (Python)]

from agents.Entwickler.agent import EntwicklerAgent

============================================================
AGENT INITIALISIEREN
============================================================

agent = EntwicklerAgent()

============================================================
PROJEKT ERSTELLEN
============================================================

project_id = agent.create_project(
    name="MeinProjekt",
    template="python_cli",
    description="Ein CLI-Tool"
)

============================================================
TASK HINZUFÜGEN
============================================================

task_id = agent.add_task(
    title="Login-Feature implementieren",
    description="User-Login mit OAuth",
    task_type="feature",
    priority="high",
    project_id=project_id
)

============================================================
NÄCHSTEN TASK BEARBEITEN
============================================================

result = agent.process_next_task()

============================================================
STATUS ABRUFEN
============================================================

print(agent.status_report())

[CLI (Testing)]

python agent.py

Ausgabe:
=== Entwickler-Agent v0.1.0 ===

=== ENTWICKLER-AGENT STATUS ===

Projekte: 1 (Aktiv: 1)
Tasks: 3 gesamt

- Ausstehend: 2
- In Arbeit: 1
- Abgeschlossen: 0

---

API-REFERENZ
------------

[Projekt-Management]

#### `create_project(name, template, description)`

Erstellt neues Projekt

Parameter:

- `name` (str): Projekt-Name
- `template` (str): Template-Typ (python_cli, python_gui, python_library)
- `description` (str): Beschreibung

Returns: `project_id` (str)

Beispiel:
project_id = agent.create_project(
    "WebScraper",
    "python_cli",
    "Tool zum Scrapen von Websites"
)

#### `load_project(project_id)`

Lädt Projekt-Daten

Returns: `Dict` oder `None`

#### `list_projects(status=None)`

Listet Projekte

Parameter:

- `status` (str, optional): Filter nach Status (active, archived)

Returns: `List[Dict]`

---

[Task-Management]

#### `add_task(title, description, task_type, priority, project_id)`

Fügt Task zur Queue hinzu

Parameter:

- `title` (str): Task-Titel
- `description` (str): Beschreibung
- `task_type` (str): bugfix|feature|optimization|refactor|test|documentation
- `priority` (str): low|normal|high|critical
- `project_id` (str, optional): Zugehöriges Projekt

Returns: `task_id` (str)

#### `get_next_task()`

Holt nächsten Task (höchste Priorität)

Returns: `Dict` oder `None`

#### `start_task(task_id)`

Markiert Task als in Bearbeitung

Returns: `bool` (Erfolg)

#### `complete_task(task_id, artifacts=None)`

Markiert Task als abgeschlossen

Parameter:

- `task_id` (str): Task-ID
- `artifacts` (List[str], optional): Generierte Dateien

Returns: `bool` (Erfolg)

#### `list_tasks(status=None, project_id=None)`

Listet Tasks

Parameter:

- `status` (str, optional): Filter nach Status
- `project_id` (str, optional): Filter nach Projekt

Returns: `List[Dict]`

---

[Workflow]

#### `process_next_task()`

Bearbeitet nächsten Task automatisch

Returns: `Dict` (Task-Ergebnis) oder `None`

Hinweis: Vollständige Implementierung in Phase 2

#### `status_report()`

Generiert Status-Bericht

Returns: `str` (Formatierter Bericht)

---

DATENSTRUKTUREN
---------------

[Projekt]

{
  "id": "proj_20251228200000",
  "name": "MeinProjekt",
  "template": "python_cli",
  "description": "Ein CLI-Tool",
  "created": "2025-12-28T20:00:00",
  "status": "active",
  "path": "/path/to/projects/MeinProjekt",
  "files": [],
  "tasks": []
}

[Task]

{
  "id": "task_20251228200100",
  "project_id": "proj_20251228200000",
  "title": "Feature X implementieren",
  "description": "Detaillierte Beschreibung",
  "type": "feature",
  "priority": "high",
  "status": "pending",
  "created": "2025-12-28T20:01:00",
  "started": null,
  "completed": null,
  "artifacts": []
}

---

INTEGRATION
-----------

[Mit BACH Skills]

============================================================
CODING-TOOLS NUTZEN (PHASE 2)
============================================================

============================================================
AGENT.ANALYZE_CODE(FILE_PATH)
============================================================

============================================================
DATA-TOOLS NUTZEN
============================================================

============================================================
AGENT.PROCESS_DATA(DATA_FILE)
============================================================

============================================================
DESKTOP COMMANDER NUTZEN
============================================================

============================================================
AGENT.EXECUTE_COMMAND(CMD)
============================================================

[Mit Services]

============================================================
CODE-EDITOR (PHASE 3)
============================================================

============================================================
AGENT.OPEN_IN_EDITOR(FILE_PATH)
============================================================

============================================================
COMPILER (PHASE 3)
============================================================

============================================================
AGENT.COMPILE_PROJECT(PROJECT_ID)
============================================================

---

KONFIGURATION
-------------

Pfad: `config.json`

{
  "capabilities": {
    "project_management": true,
    "code_generation": false,
    "debugging": false
  },
  "limits": {
    "max_concurrent_tasks": 3,
    "timeout_minutes": 30
  }
}

---

ENTWICKLUNGS-ROADMAP
--------------------

[✅ Phase 1: Grundgerüst (COMPLETE)]

- Projekt-Management
- Task-Management
- Basis-Workflow
- Status-Reporting

[⏳ Phase 2: Core-Features (TODO)]

- Code-Analyse Integration
- Basic Code-Generation
- Reporting-System
- Error-Handling

[⏳ Phase 3: Service-Integration (TODO)]

- Editor-Service API
- Compiler-Service API
- Service-Orchestrierung

[⏳ Phase 4: Intelligenz (TODO)]

- Debugging-Logik
- Code-Bewertung
- Pattern-Erkennung
- Optimierungs-Vorschläge

[⏳ Phase 5: Kollaboration (TODO)]

- Editor-Synchronisation
- User-Feedback-Loop
- Interaktive Bearbeitung

[⏳ Phase 6: Testing & Polish (TODO)]

- Integrationstests
- Beispielprojekte
- Vollständige Dokumentation

---

BEISPIEL-WORKFLOW
-----------------

============================================================

1. AGENT INITIALISIEREN
============================================================
agent = EntwicklerAgent()

============================================================
2. PROJEKT ANLEGEN
============================================================

proj = agent.create_project("TodoApp", "python_cli")

============================================================
3. TASKS DEFINIEREN
============================================================

agent.add_task("Datenmodell erstellen", project_id=proj, priority="high")
agent.add_task("CLI-Interface", project_id=proj)
agent.add_task("Tests schreiben", project_id=proj, task_type="test")

============================================================
4. TASKS ABARBEITEN
============================================================

while True:
    result = agent.process_next_task()
    if not result:
        break
    print(f"Task {result['task_id']}: {result['status']}")

============================================================
5. STATUS PRÜFEN
============================================================

print(agent.status_report())

---

LOGGING
-------

Log-Datei: `entwickler_agent.log`

Format:
2025-12-28 20:00:00 [INFO] Entwickler-Agent v0.1.0 initialisiert
2025-12-28 20:00:01 [INFO] Projekt erstellt: TodoApp (proj_20251228200001)
2025-12-28 20:00:02 [INFO] Task hinzugefügt: Datenmodell erstellen (task_20251228200002)

---

Status: ✅ PHASE 1 FUNCTIONAL
Bereit für: Phase 2 (Code-Analyse & Generation)
Dependencies: Python 3.7+, Desktop Commander
