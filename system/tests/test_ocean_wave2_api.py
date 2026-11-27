"""Tests for OCEAN Wave 2 endpoints & 504/429 Carbon-Review fixes."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, Path]:
    from gui.api import unified_api

    db_path = tmp_path / "bach_test.db"
    conn = sqlite3.connect(str(db_path))
    unified_api._ensure_calendar_tables(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS financial_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider_id TEXT NOT NULL UNIQUE,
            provider_name TEXT NOT NULL,
            betrag_monatlich REAL,
            zahlungsintervall TEXT,
            naechste_zahlung TEXT,
            aktiv INTEGER DEFAULT 1
        )
        """
    )
    conn.execute(
        "INSERT INTO financial_subscriptions (provider_id, provider_name, betrag_monatlich, zahlungsintervall, naechste_zahlung, aktiv) "
        "VALUES ('o2', 'O2 Internet', 29.99, 'monatlich', '2026-12-05 09:00:00', 1)"
    )
    conn.execute(
        "INSERT INTO household_routines (name, frequency, category, next_due, is_active) "
        "VALUES ('Pflanzen giessen', 'woechentlich', 'Haushalt', '2026-12-03 08:00:00', 1)"
    )
    conn.commit()
    conn.close()

    def _conn_factory():
        c = sqlite3.connect(str(db_path))
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(unified_api, "_get_conn", _conn_factory)
    help_dir = tmp_path / "help"
    help_dir.mkdir()
    (help_dir / "memory.txt").write_text("# Memory Hilfe\nArbeitsgedaechtnis und Fakten.\n", encoding="utf-8")
    (help_dir / "memory_en.txt").write_text("# Memory Help\nWorking memory and facts.\n", encoding="utf-8")
    monkeypatch.setattr(unified_api, "_help_docs_dir", lambda: help_dir)

    app = FastAPI()
    app.include_router(unified_api.router)
    return TestClient(app), db_path


def test_multi_calendar_silos_readthrough_actions_and_exports(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)

    # Create a ticket-silo event
    r_create = client.post(
        "/api/calendar/events",
        json={
            "title": "Release Review #2972",
            "start_datetime": "2026-12-10 14:00:00",
            "calendar_id": "tickets",
            "location": "Mac Studio",
        },
    )
    assert r_create.status_code == 200
    created = r_create.json()
    assert created["ok"] is True
    assert created["calendar_id"] == "tickets"
    eid = created["id"]

    # Profiles report live counts across direct + read-through silos
    r_prof = client.get("/api/calendar/profiles")
    assert r_prof.status_code == 200
    prof_map = {p["id"]: p["count"] for p in r_prof.json()["profiles"]}
    assert prof_map["tickets"] == 1
    assert prof_map["finanzen"] == 1
    assert prof_map["routinen"] == 1

    # Mirror ticket event into user silo
    r_mirror = client.post(f"/api/calendar/events/{eid}/mirror", json={"target_calendar_id": "user"})
    assert r_mirror.status_code == 200
    assert r_mirror.json()["action"] == "mirror"
    assert r_mirror.json()["calendar_id"] == "user"

    # Filter by user silo only
    r_user = client.get("/api/calendar/events?view=month&date=2026-12-01&calendars=user")
    assert r_user.status_code == 200
    user_events = r_user.json()["events"]
    assert len(user_events) == 1
    assert user_events[0]["calendar_id"] == "user"
    assert user_events[0]["link_mode"] == "mirror"

    # Merged all silos includes ticket, mirrored user, financial read-through, routine read-through
    r_all = client.get("/api/calendar/events?view=month&date=2026-12-01&calendars=all")
    assert r_all.status_code == 200
    assert r_all.json()["count"] == 4

    # Transfer original event to terminpilot
    r_tr = client.post(f"/api/calendar/events/{eid}/transfer", json={"target_calendar_id": "terminpilot"})
    assert r_tr.status_code == 200
    assert r_tr.json()["calendar_id"] == "terminpilot"

    # Exports: html, md, txt, ics
    for fmt, marker in (
        ("html", "<!doctype html>"),
        ("md", "# OCEAN Kalender-Auszug"),
        ("txt", "OCEAN Kalender-Auszug"),
        ("ics", "BEGIN:VCALENDAR"),
    ):
        r_exp = client.get(f"/api/calendar/export?view=month&date=2026-12-01&calendars=all&format={fmt}")
        assert r_exp.status_code == 200
        assert marker in r_exp.text


def test_help_topics_search_detail_and_traversal_guard(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)

    r_list = client.get("/api/help/topics?lang=de&q=memory")
    assert r_list.status_code == 200
    body = r_list.json()
    assert body["schema"] == "bach.help-topics.v1"
    assert body["total_files"] == 2
    assert len(body["topics"]) == 1
    assert body["topics"][0]["topic"] == "memory"

    r_en = client.get("/api/help/topics/memory?lang=en")
    assert r_en.status_code == 200
    assert "Working memory" in r_en.json()["content"]

    # Path traversal must be rejected
    r_bad = client.get("/api/help/topics/..%2F..%2Fetc%2Fpasswd?lang=de")
    assert r_bad.status_code in {400, 404}
