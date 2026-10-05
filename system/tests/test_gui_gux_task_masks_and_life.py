"""GUX Task-Masken und Life-Aufgabenerstellung (GUX-044..047, Task #1701).

Prüft:
- GUX-044: /api/tasks?status=open expandiert auf alle offenen Aliase
  ('open', 'todo', 'in_progress', 'pending', 'progress').
- GUX-045: /api/tasks?assigned_to=user filtert persönliche Aufgaben für Detailansicht & Bearbeitung.
- GUX-046: Task-Erstellung und -Bearbeitung unterstützen volle Maske und Feldvielfalt
  (title, description, priority, status, category/project, assigned_to, created_by,
   due_date, depends_on, required_model, assigned_slot).
  Fälligkeitsdatum-Vertrag:
    - YYYY-MM-DD und ISO-Format werden akzeptiert und gespeichert
    - null oder leerer String löscht das Fälligkeitsdatum
    - Ungültige Werte werden fail-closed mit HTTP 400 abgewiesen
    - Änderungen werden in task_history auditiert
- GUX-047: /life liefert Tab-Oberfläche mit Meine Aufgaben (tab=aufgaben),
  POST /api/tasks erlaubt direkte persönliche Aufgabenerstellung mit GET-Readback.
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

TASKS_SCHEMA = """
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    category TEXT,
    priority TEXT DEFAULT 'P3',
    status TEXT DEFAULT 'pending',
    created_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT,
    created_by TEXT DEFAULT 'user',
    assigned_to TEXT DEFAULT 'user',
    project TEXT,
    source TEXT,
    image_data TEXT,
    due_date TEXT,
    depends_on TEXT,
    required_model TEXT,
    assigned_slot TEXT,
    modified_by TEXT,
    claimed_by TEXT,
    claimed_at TEXT
);

CREATE TABLE IF NOT EXISTS task_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    field_changed TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    changed_by TEXT DEFAULT 'api',
    changed_at TEXT,
    action TEXT DEFAULT 'field_change'
);
"""


@pytest.fixture(scope="module")
def app_client():
    """Baut eine temporäre BACH-DB auf und stellt den FastAPI TestClient bereit."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    original_db = os.environ.get("BACH_DB")
    os.environ["BACH_DB"] = db_path

    # Cache leeren
    for name in list(sys.modules.keys()):
        if "gui.server" in name or "hub.bach_paths" in name or "hub.task_audit" in name:
            sys.modules.pop(name, None)

    conn = sqlite3.connect(db_path)
    conn.executescript(TASKS_SCHEMA)

    initial_tasks = [
        # (title, status, priority, category, assigned_to, due_date)
        ("Task Open", "open", "P1", "gui", "user", "2026-10-15"),
        ("Task Todo", "todo", "P2", "gui", "user", None),
        ("Task InProgress", "in_progress", "P3", "backend", "claude", "2026-10-20"),
        ("Task Progress", "progress", "P2", "dev", "gemini", None),
        ("Task Pending", "pending", "P4", "ops", "user", None),
        ("Task Done", "done", "P3", "general", "user", None),
        ("Task Completed", "completed", "P3", "general", "user", None),
        ("Task Cancelled", "cancelled", "P4", "general", "user", None),
    ]
    for title, status, priority, cat, assigned_to, due in initial_tasks:
        conn.execute(
            """INSERT INTO tasks (title, status, priority, category, assigned_to, due_date, created_at, created_by)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'), 'user')""",
            (title, status, priority, cat, assigned_to, due),
        )
    conn.commit()
    conn.close()

    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from system.gui import server

    def _get_db():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    with patch.object(server, "get_bach_db", side_effect=_get_db), patch.object(
        server,
        "validate_token",
        side_effect=lambda token: {"id": 1, "device_id": "test-device"}
        if token == "gux-test-token"
        else None,
    ):
        client = TestClient(
            server.app,
            headers={"Authorization": "Bearer gux-test-token"},
        )
        yield client, db_path

    if original_db:
        os.environ["BACH_DB"] = original_db
    else:
        os.environ.pop("BACH_DB", None)

    try:
        os.remove(db_path)
    except OSError:
        pass


def test_gux_044_open_status_alias_expansion(app_client):
    """GUX-044: /api/tasks?status=open liefert alle offenen Aliase (open, todo, in_progress, pending, progress)."""
    client, _ = app_client
    res = client.get("/api/tasks?status=open")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True

    statuses = {t["status"] for t in data["tasks"]}
    # Alle offenen Aliase müssen vertreten sein
    assert "open" in statuses
    assert "todo" in statuses
    assert "in_progress" in statuses
    assert "progress" in statuses
    assert "pending" in statuses
    # Geschlossene dürfen nicht auftauchen
    assert "done" not in statuses
    assert "completed" not in statuses
    assert "cancelled" not in statuses


def test_gux_045_user_assigned_personal_task_list(app_client):
    """GUX-045: /api/tasks?assigned_to=user liefert vorselektierte persönliche Aufgaben."""
    client, _ = app_client
    res = client.get("/api/tasks?assigned_to=user")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert len(data["tasks"]) > 0
    for task in data["tasks"]:
        assert task["assigned_to"].lower() == "user"


def test_gux_046_full_task_creation_and_due_date_contract(app_client):
    """GUX-046: Volle Task-Maske bei Anlage und Fälligkeitsdatum-Vertrag."""
    client, db_path = app_client

    # 1. Erfolgreiches Erstellen mit vollem Maskenumfang
    payload = {
        "title": "GUX-046 Testaufgabe",
        "description": "Ausführliche Aufgabenbeschreibung mit Modell & Slot",
        "priority": "P1",
        "category": "gui-ux",
        "assigned_to": "user",
        "created_by": "user",
        "due_date": "2026-11-01",
        "depends_on": "1, 2",
        "required_model": "gemini-2.5-pro",
        "assigned_slot": "slot-a",
    }
    create_res = client.post("/api/tasks", json=payload)
    assert create_res.status_code == 200
    res_data = create_res.json()
    assert res_data["success"] is True
    new_id = res_data["id"]

    # Readback prüfen
    read_res = client.get(f"/api/tasks/{new_id}")
    assert read_res.status_code == 200
    task = read_res.json()
    assert task["title"] == payload["title"]
    assert task["description"] == payload["description"]
    assert task["priority"] == "P1"
    assert task["category"] == "gui-ux"
    assert task["assigned_to"] == "user"
    assert task["due_date"] == "2026-11-01"
    assert task["depends_on"] == "1, 2"
    assert task["required_model"] == "gemini-2.5-pro"
    assert task["assigned_slot"] == "slot-a"

    # 2. Update mit ISO-Fälligkeitsdatum
    update_res = client.put(f"/api/tasks/{new_id}", json={"due_date": "2026-11-15T12:00:00"})
    assert update_res.status_code == 200
    read_res = client.get(f"/api/tasks/{new_id}")
    assert read_res.json()["due_date"] == "2026-11-15T12:00:00"

    # 3. Fälligkeitsdatum leeren (null / leerer String)
    clear_res = client.put(f"/api/tasks/{new_id}", json={"due_date": None})
    assert clear_res.status_code == 200
    read_res = client.get(f"/api/tasks/{new_id}")
    assert read_res.json()["due_date"] is None

    # 4. Ungültiges Fälligkeitsdatum wird mit 400 abgewiesen
    invalid_res = client.put(f"/api/tasks/{new_id}", json={"due_date": "invalid-datum"})
    assert invalid_res.status_code == 400
    assert "Ungültiges Fälligkeitsdatum" in invalid_res.json()["detail"]

    # 5. Audit-Trail in task_history verifizieren
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT field_changed, old_value, new_value FROM task_history WHERE task_id = ? ORDER BY id ASC",
        (new_id,)
    ).fetchall()
    conn.close()
    # due_date-Änderungen müssen in der History stehen
    history_fields = [r[0] for r in rows]
    assert "due_date" in history_fields


def test_gux_047_life_tasks_integration(app_client):
    """GUX-047: /life liefert Template/Page aus und unterstützt persönliche Aufgabenerstellung."""
    client, _ = app_client

    # 1. GET /life muss 200 liefern
    res = client.get("/life?tab=aufgaben")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    content = res.text
    # Prüfen auf Meine Aufgaben & Tab-Mechanik
    assert "Meine" in content
    assert "aufgaben" in content.lower()

    # 2. Persönliche Task-Erstellung über POST /api/tasks mit assigned_to=user
    life_task_payload = {
        "title": "Persönliche Life-Aufgabe",
        "description": "Erstellt via Life-Zentrale Tab 3",
        "priority": "P2",
        "category": "personal",
        "assigned_to": "user",
        "created_by": "user",
        "due_date": "2026-10-31",
    }
    create_res = client.post("/api/tasks", json=life_task_payload)
    assert create_res.status_code == 200
    res_data = create_res.json()
    assert res_data["success"] is True
    task_id = res_data["id"]

    # 3. Kontrollabruf verifiziert persönliche Zuordnung
    readback = client.get(f"/api/tasks/{task_id}").json()
    assert readback["assigned_to"] == "user"
    assert readback["due_date"] == "2026-10-31"
    assert readback["category"] == "personal"
