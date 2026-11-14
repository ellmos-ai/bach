"""PB-3 (#3987): Loopback-Auto-Anmeldung darf `browser_sessions` nicht fluten."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SYSTEM = Path(__file__).resolve().parent.parent
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

from gui.device_auth import init_devices_db  # noqa: E402
from gui.server import app  # noqa: E402

LOOP = {"Host": "127.0.0.1:8000"}
NAV = {**LOOP, "Sec-Fetch-Dest": "document"}


@pytest.fixture
def env(monkeypatch, tmp_path):
    db = tmp_path / "bach.db"
    conn = sqlite3.connect(str(db))
    init_devices_db(conn)
    conn.close()
    import gui.device_auth as da
    monkeypatch.setattr(da, "GET_CONNECTION", lambda: sqlite3.connect(str(db)))

    def rows():
        with sqlite3.connect(str(db)) as c:
            return c.execute("SELECT COUNT(*) FROM browser_sessions").fetchone()[0]

    return TestClient(app), rows


def test_cookieloser_nichtbrowser_seitenabruf_legt_keine_sitzung_an(env):
    client, rows = env
    for _ in range(5):
        client.get("/talk", headers=LOOP)
        client.cookies.clear()
    assert rows() == 0


def test_subresource_device_fetch_js_legt_keine_sitzung_an(env):
    client, rows = env
    client.get("/device-fetch.js", headers={**LOOP, "Sec-Fetch-Dest": "script"})
    client.get("/static/js/device-fetch.js", headers={**LOOP, "Sec-Fetch-Dest": "script"})
    assert rows() == 0


def test_navigation_legt_genau_eine_sitzung_an_und_wiederverwendet_sie(env):
    client, rows = env
    first = client.get("/talk", headers=NAV)
    assert "bach_device_token=" in first.headers.get("set-cookie", "")
    assert rows() == 1
    for _ in range(5):
        client.get("/talk", headers=NAV)
    assert rows() == 1


def test_auto_session_endpoint_mit_gueltigem_cookie_legt_keine_neue_sitzung_an(env):
    client, rows = env
    hdr = {**LOOP, "Origin": "http://127.0.0.1:8000"}
    assert client.post("/api/devices/auto-session", json={"device_id": "ASUS-GEI"}, headers=hdr).status_code == 200
    assert rows() == 1
    again = client.post("/api/devices/auto-session", json={"device_id": "ASUS-GEI"}, headers=hdr)
    assert again.status_code == 200 and again.json()["valid"] is True
    assert rows() == 1
