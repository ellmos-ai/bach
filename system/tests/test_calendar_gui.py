#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests fuer das Kalender-Dashboard (GUI + API).

Deckt ab:
- GET  /api/calendar/events (Pflicht-Query start/end, leere DB)
- POST /api/calendar/events (anlegen, RRULE)
- PUT  /api/calendar/events/{id} (partielles Update)
- DELETE /api/calendar/events/{id}
- PATCH /api/calendar/events/{id}/done
- GET  /kalender (HTML-Seite)

Isolation: USER_DB wird auf eine tmp-DB umgebogen (get_user_db liest
srv.USER_DB bei Call-Zeit), Schema minimal nachgebaut.
ACHTUNG: status hat CHECK-Constraint ('geplant','bestaetigt','abgesagt',
'erledigt') — nie 'done'/'pending' verwenden.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

BACH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACH_ROOT / "system"))

pytest.importorskip("fastapi")  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from gui.server import app  # noqa: E402
import gui.server as srv  # noqa: E402
from gui import device_auth  # noqa: E402

def _resolve_schema_sql() -> str:
    candidates = [
        BACH_ROOT / "data" / "schema" / "schema.sql",
        BACH_ROOT / "system" / "data" / "schema" / "schema.sql",
        BACH_ROOT / ".." / "data" / "schema" / "schema.sql",
        Path(__file__).resolve().parents[2] / "data" / "schema" / "schema.sql",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise FileNotFoundError(
        f"schema.sql nicht gefunden; gesucht in: "
        f"{', '.join(str(c.resolve()) for c in candidates)}"
    )


SCHEMA_SQL = _resolve_schema_sql()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / "bach.db"
    monkeypatch.setattr(srv, "USER_DB", db)
    monkeypatch.setattr(srv, "BACH_DB", db, raising=False)
    monkeypatch.setenv("BACH_CONTROL_API_TOKEN", "test-control-token")

    # Device-Auth auf dieselbe Temp-DB lenken, damit /api/*-Routen gültiges
    # Bearer-Token akzeptieren.
    monkeypatch.setattr(device_auth, "GET_CONNECTION", lambda: sqlite3.connect(str(db)))

    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA_SQL)
    conn.execute("""CREATE TABLE IF NOT EXISTS assistant_calendar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        event_type TEXT,
        start_datetime TEXT NOT NULL,
        end_datetime TEXT,
        location TEXT,
        description TEXT,
        attendees TEXT,
        status TEXT DEFAULT 'geplant' CHECK(status IN ('geplant','bestaetigt','abgesagt','erledigt')),
        reminder_minutes INTEGER,
        is_recurring INTEGER DEFAULT 0,
        recurrence_rule TEXT,
        external_id TEXT,
        created_at TEXT,
        updated_at TEXT,
        dist_type TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS routines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        description TEXT,
        category TEXT,
        interval_type TEXT,
        interval_value INTEGER,
        specific_day TEXT,
        last_completed_at TEXT,
        next_due_at TEXT,
        is_active INTEGER DEFAULT 1,
        priority TEXT,
        duration_minutes INTEGER,
        dist_type TEXT)""")
    conn.commit()
    conn.close()

    _, token = device_auth.create_device("test-device")
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def _create(client, **overrides):
    payload = {"title": "Test", "date": "2025-06-15", "time": "10:00"}
    payload.update(overrides)
    resp = client.post("/api/calendar/events", json=payload)
    data = resp.json()
    assert resp.status_code == 200
    assert data["success"] is True, data
    return data


def test_get_events_empty(client):
    resp = client.get("/api/calendar/events", params={"start": "2025-06-01", "end": "2025-06-30"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["events"] == []
    assert data["routines"] == []


def test_create_event(client):
    data = _create(client)
    assert data["event"]["start_datetime"] == "2025-06-15 10:00:00"
    assert data["event"]["status"] == "geplant"
    assert data["id"]


def test_update_event_partial(client):
    event_id = _create(client)["id"]
    resp = client.put(f"/api/calendar/events/{event_id}", json={"title": "Neu"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["event"]["title"] == "Neu"
    # Ohne "date"-Key bleiben start/end unveraendert
    assert data["event"]["start_datetime"] == "2025-06-15 10:00:00"


def test_delete_event(client):
    event_id = _create(client)["id"]
    resp = client.delete(f"/api/calendar/events/{event_id}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    # Event ist weg
    resp = client.get("/api/calendar/events", params={"start": "2025-06-01", "end": "2025-06-30"})
    assert resp.json()["events"] == []


def test_create_event_with_recurrence(client):
    data = _create(client, title="R", recurrence="daily")
    assert data["event"]["recurrence_rule"] == "FREQ=DAILY"
    assert data["event"]["is_recurring"] == 1


def test_patch_done(client):
    event_id = _create(client)["id"]
    resp = client.patch(f"/api/calendar/events/{event_id}/done")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    # Status in DB pruefen
    conn = sqlite3.connect(srv.USER_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT status FROM assistant_calendar WHERE id = ?", (event_id,)).fetchone()
    conn.close()
    assert row["status"] == "erledigt"


def test_get_events_requires_range(client):
    resp = client.get("/api/calendar/events")
    assert resp.status_code == 422


def test_kalender_page(client):
    resp = client.get("/kalender")
    assert resp.status_code == 200
