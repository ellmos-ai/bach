"""Tests for OCEAN Wave 2 endpoints, PDF export, TerminPilot read-through & Agenda API."""
from __future__ import annotations

import json
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
    monkeypatch.setattr(unified_api, "BACH_DB", db_path)
    monkeypatch.setenv("BACH_DATA_DIR", str(tmp_path / "bach_data"))
    monkeypatch.setenv("BACH_LOCAL_DIR", str(tmp_path / "bach_local"))
    monkeypatch.delenv("BACH_TERMINPILOT_DB", raising=False)
    monkeypatch.delenv("BACH_AGENDA_FILE", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "fake_home"))

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


def test_calendar_export_pdf_winansi_umlauts_and_headers(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)

    r_create = client.post(
        "/api/calendar/events",
        json={
            "title": "Ärztliche Überprüfung & Fußgängerstraße",
            "start_datetime": "2026-12-14 09:30:00",
            "calendar_id": "gesundheit",
            "location": "Münchner Straße 42",
        },
    )
    assert r_create.status_code == 200

    for view in ("month", "list"):
        r_pdf = client.get(f"/api/calendar/export?view={view}&date=2026-12-01&calendars=all&format=pdf")
        assert r_pdf.status_code == 200
        assert r_pdf.headers["content-type"].startswith("application/pdf")
        assert r_pdf.headers.get("content-disposition") == 'attachment; filename="kalender-export.pdf"'
        raw = r_pdf.content
        assert raw.startswith(b"%PDF-1.4")
        assert raw.rstrip().endswith(b"%%EOF")
        assert len(raw) > 800
        assert b"/BaseFont /Helvetica" in raw
        assert b"/Encoding /WinAnsiEncoding" in raw
        assert b"\nxref\n" in raw
        # German umlauts encoded via WinAnsi octal escapes (\304=Ä, \334=Ü, \337=ß, \374=ü)
        assert b"\\304" in raw
        assert b"\\374" in raw
        assert b"\\337" in raw

    r_bad = client.get("/api/calendar/export?format=docx")
    assert r_bad.status_code == 400


def test_terminpilot_readthrough_silo_and_missing_db_fallback(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)

    # Missing terminpilot.db must fail cleanly to []
    monkeypatch.setenv("BACH_TERMINPILOT_DB", str(tmp_path / "does_not_exist.db"))
    r_missing_prof = client.get("/api/calendar/profiles")
    assert r_missing_prof.status_code == 200
    assert {p["id"]: p["count"] for p in r_missing_prof.json()["profiles"]}["terminpilot"] == 0

    r_missing_ev = client.get("/api/calendar/events?view=month&date=2026-12-01&calendars=terminpilot")
    assert r_missing_ev.status_code == 200
    assert r_missing_ev.json()["events"] == []
    assert not (tmp_path / "does_not_exist.db").exists()

    # Create synthetic terminpilot.db with mixed finalized/open polls + deduplicated calendar_entry
    tp_db = tmp_path / "terminpilot.db"
    tp_conn = sqlite3.connect(str(tp_db))
    tp_conn.executescript(
        """
        CREATE TABLE polls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            topic TEXT,
            status TEXT NOT NULL,
            final_slot TEXT,
            chosen_date TEXT,
            chosen_time_start TEXT,
            chosen_time_end TEXT,
            location TEXT
        );
        CREATE TABLE calendar_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            date TEXT NOT NULL,
            time_start TEXT,
            time_end TEXT,
            source TEXT,
            source_poll_id INTEGER
        );
        """
    )
    tp_conn.execute(
        "INSERT INTO polls (id, title, topic, status, final_slot, location) "
        "VALUES (1, 'Quartalsabstimmung Q4', 'Roadmap', 'finalized', '2026-12-11 10:00 - 11:30', 'Raum Nord')"
    )
    tp_conn.execute(
        "INSERT INTO polls (id, title, topic, status, chosen_date, chosen_time_start, chosen_time_end) "
        "VALUES (2, 'Jahresrückblick', 'Team', 'closed', '2026-12-18', '14:00', '15:00')"
    )
    tp_conn.execute(
        "INSERT INTO polls (id, title, status, final_slot) "
        "VALUES (3, 'Offene Umfrage', 'active', '2026-12-20 09:00')"
    )
    tp_conn.execute(
        "INSERT INTO polls (id, title, status, chosen_date) "
        "VALUES (4, 'Abgebrochen ohne Slot', 'closed', NULL)"
    )
    # Duplicate for poll 2 must not emit twice; standalone entry 99 must appear
    tp_conn.execute(
        "INSERT INTO calendar_entries (id, title, date, time_start, source, source_poll_id) "
        "VALUES (10, 'Jahresrückblick', '2026-12-18', '14:00', 'poll', 2)"
    )
    tp_conn.execute(
        "INSERT INTO calendar_entries (id, title, date, time_start, source, source_poll_id) "
        "VALUES (11, 'Bestätigtes Gespräch', '2026-12-22', '16:30', 'booking', NULL)"
    )
    tp_conn.commit()
    tp_conn.close()

    monkeypatch.setenv("BACH_TERMINPILOT_DB", str(tp_db))

    r_prof = client.get("/api/calendar/profiles")
    assert r_prof.status_code == 200
    assert {p["id"]: p["count"] for p in r_prof.json()["profiles"]}["terminpilot"] == 3

    r_tp = client.get("/api/calendar/events?view=month&date=2026-12-01&calendars=terminpilot")
    assert r_tp.status_code == 200
    tp_events = r_tp.json()["events"]
    assert len(tp_events) == 3
    titles = [e["title"] for e in tp_events]
    assert titles == ["Quartalsabstimmung Q4", "Jahresrückblick", "Bestätigtes Gespräch"]
    assert all(e["calendar_id"] == "terminpilot" and e["read_through"] is True for e in tp_events)
    assert tp_events[0]["start_datetime"] == "2026-12-11 10:00:00"
    assert tp_events[0]["end_datetime"] == "2026-12-11 11:30:00"

    # Also verify automatic discovery in <bach_data_dir>/terminpilot.db without env override
    monkeypatch.delenv("BACH_TERMINPILOT_DB", raising=False)
    data_dir = tmp_path / "bach_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "terminpilot.db").write_bytes(tp_db.read_bytes())
    r_tp_auto = client.get("/api/calendar/events?view=month&date=2026-12-01&calendars=terminpilot")
    assert r_tp_auto.status_code == 200
    assert r_tp_auto.json()["count"] == 3


def test_agenda_endpoint_json_horizon_filtering_and_fallbacks(tmp_path, monkeypatch):
    client, db_path = _make_client(tmp_path, monkeypatch)

    # 1. Empty fallback when neither agenda.json nor tasks/goals exist
    r_empty = client.get("/api/agenda")
    assert r_empty.status_code == 200
    empty_body = r_empty.json()
    assert empty_body == {
        "available": False,
        "source": "empty",
        "updated_at": None,
        "horizons": ["short", "mid", "long"],
        "items": [],
        "count": 0,
    }

    # 2. DB tasks/goals fallback when agenda.json is absent
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            priority TEXT DEFAULT 'P3',
            status TEXT DEFAULT 'pending',
            category TEXT,
            due_date TEXT,
            updated_at TEXT
        );
        CREATE TABLE selfmgmt_career_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT,
            target_date TEXT,
            status TEXT DEFAULT 'active',
            progress INTEGER DEFAULT 0,
            updated_at TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO tasks (title, priority, status, category, due_date, updated_at) "
        "VALUES ('Dringendes Review', 'P1', 'in_progress', 'dev', '2026-12-02', '2026-11-27T08:00:00Z')"
    )
    conn.execute(
        "INSERT INTO tasks (title, priority, status, category, due_date) "
        "VALUES ('Erledigter Task', 'P1', 'done', 'dev', '2026-12-01')"
    )
    conn.execute(
        "INSERT INTO selfmgmt_career_goals (title, category, target_date, status, progress, updated_at) "
        "VALUES ('Jahresarchitektur abschließen', 'strategie', '2027-09-30', 'active', 40, '2026-11-26T12:00:00Z')"
    )
    conn.commit()
    conn.close()

    r_tasks = client.get("/api/agenda?horizon=all")
    assert r_tasks.status_code == 200
    tb = r_tasks.json()
    assert tb["available"] is True
    assert tb["source"] == "bach_tasks"
    assert tb["horizons"] == ["short", "mid", "long"]
    assert tb["count"] == 2
    assert tb["items"][0]["title"] == "Dringendes Review"
    assert tb["items"][0]["weight"] == 95
    assert tb["items"][0]["progress"] == 50
    expected_keys = {"id", "title", "weight", "priority", "horizon", "status", "progress", "category", "deadline"}
    assert set(tb["items"][0].keys()) == expected_keys

    # 3. agenda.json fixture takes precedence via BACH_AGENDA_FILE
    agenda_file = tmp_path / "agenda.json"
    agenda_file.write_text(
        json.dumps(
            {
                "schema": "agent-agenda.v1",
                "revision": 3,
                "updated_at": "2026-11-27T07:30:00Z",
                "items": [
                    {
                        "id": "A1",
                        "text": "Kurzfristige Steuerabgabe prüfen",
                        "weight": 92,
                        "status": "pending",
                        "horizon": "short",
                        "category": "finanzen",
                        "deadline": "2026-12-05",
                    },
                    {
                        "id": "A2",
                        "title": "Quartals-Meilenstein konsolidieren",
                        "weight": 70,
                        "priority": "P2",
                        "status": "in_progress",
                        "horizon": "mid",
                        "progress": 65,
                        "category": "technik",
                        "deadline": "2027-03-01",
                    },
                    {
                        "id": "A3",
                        "text": "Langfristige Infrastruktur-Strategie",
                        "weight": 45,
                        "status": "pending",
                        "timeframe": "ongoing",
                        "category": "architektur",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BACH_AGENDA_FILE", str(agenda_file))

    r_json = client.get("/api/agenda?horizon=all")
    assert r_json.status_code == 200
    jb = r_json.json()
    assert jb["available"] is True
    assert jb["source"] == "agenda_json"
    assert jb["updated_at"] == "2026-11-27T07:30:00Z"
    assert jb["count"] == 3
    assert [it["id"] for it in jb["items"]] == ["A1", "A2", "A3"]

    r_mid = client.get("/api/agenda?horizon=mid")
    assert r_mid.status_code == 200
    assert r_mid.json()["count"] == 1
    assert r_mid.json()["items"][0]["id"] == "A2"
    assert r_mid.json()["items"][0]["progress"] == 65

    r_bad_hz = client.get("/api/agenda?horizon=decade")
    assert r_bad_hz.status_code == 400


def test_agenda_export_formats_headers_and_xss_guard(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)

    agenda_file = tmp_path / "agenda_xss.json"
    agenda_file.write_text(
        json.dumps(
            {
                "updated_at": "2026-11-27T08:00:00Z",
                "items": [
                    {
                        "id": "A1",
                        "title": "Prüfauftrag <script>alert('xss')</script> & Rückmeldung",
                        "weight": 88,
                        "priority": "P1",
                        "horizon": "short",
                        "status": "pending",
                        "progress": 25,
                        "category": "sicherheit",
                        "deadline": "2026-12-10",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BACH_AGENDA_FILE", str(agenda_file))

    r_pdf = client.get("/api/agenda/export?format=pdf&horizon=all")
    assert r_pdf.status_code == 200
    assert r_pdf.headers["content-type"].startswith("application/pdf")
    assert r_pdf.headers.get("content-disposition") == 'attachment; filename="agenda-export.pdf"'
    assert r_pdf.content.startswith(b"%PDF-1.4")
    assert r_pdf.content.rstrip().endswith(b"%%EOF")
    assert b"/Encoding /WinAnsiEncoding" in r_pdf.content

    r_html = client.get("/api/agenda/export?format=html&horizon=short")
    assert r_html.status_code == 200
    assert "text/html" in r_html.headers["content-type"]
    assert "agenda-export.html" in r_html.headers.get("content-disposition", "")
    assert "<script>" not in r_html.text
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in r_html.text

    r_md = client.get("/api/agenda/export?format=md&horizon=all")
    assert r_md.status_code == 200
    assert "text/markdown" in r_md.headers["content-type"]
    assert "agenda-export.md" in r_md.headers.get("content-disposition", "")
    assert "| `A1` | `short` |" in r_md.text

    r_txt = client.get("/api/agenda/export?format=txt&horizon=all")
    assert r_txt.status_code == 200
    assert "text/plain" in r_txt.headers["content-type"]
    assert "agenda-export.txt" in r_txt.headers.get("content-disposition", "")
    assert "A1 (short, P1/w=88, 25%, sicherheit | Frist: 2026-12-10)" in r_txt.text

    r_bad_fmt = client.get("/api/agenda/export?format=exe")
    assert r_bad_fmt.status_code == 400


def test_agenda_routes_require_device_auth_in_server():
    from gui import server

    srv_client = TestClient(server.app, base_url="http://127.0.0.1:8000", raise_server_exceptions=False)
    try:
        assert srv_client.get("/api/agenda").status_code == 401
        assert srv_client.get("/api/agenda/export?format=pdf").status_code == 401
    finally:
        srv_client.close()
