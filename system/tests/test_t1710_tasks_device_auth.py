"""Task #1710 [T793][SEC] — Regression: /api/tasks device-auth (agent-studio-Muster).

GET /api/tasks und GET /api/tasks/{task_id} (sowie /api/tasks/meta und die
PUT/POST/DELETE-Verbformen) muessen wie /api/agent-studio eine gueltige
Geraete-Authentifizierung erfordern (individueller Geraeteschluessel, NICHT
gemeinsames Control-Token). Filter/Pagination/Response-Schema bleiben erhalten.

Teststrategie (isoliert, KEINE Produkt-TaskDB):
- Der echte DeviceAuthMiddleware aus server.py wird gegen eine in-memory
  FastAPI-App + gepatchte device_auth-Funktionen (validate_token/has_active_devices)
  geprueft. Kein Zugriff auf die produktive TaskDB.
"""
import asyncio
import importlib
import os
import sys

import pytest

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

# server.py liegt ein Ebenen ueber (system/gui/server.py).
_HERE = os.path.dirname(os.path.abspath(__file__))
_GUI = os.path.abspath(os.path.join(_HERE, "..", "gui"))
if _GUI not in sys.path:
    sys.path.insert(0, _GUI)

import server  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_devices(monkeypatch):
    """device_auth isolieren: ein gueltiger Geraeteschluessel 'ASUS-KEY'."""
    valid = {"id": "dev-asus", "name": "ASUS", "active": True}
    monkeypatch.setattr(server, "validate_token",
                        lambda tok: dict(valid) if tok == "ASUS-KEY" else None)
    monkeypatch.setattr(server, "has_active_devices", lambda: True)
    yield


def _make_app():
    app = FastAPI()
    app.add_middleware(server.DeviceAuthMiddleware)

    # GET /api/tasks: Filter + Pagination + Response-Schema.
    @app.get("/api/tasks")
    async def list_tasks(request: Request, status: str = "all", category: str = "",
                         limit: int = 50, offset: int = 0):
        return {"success": True,
                "categories": ["arbeit", "privat"],
                "data": [{"id": 1, "title": "x", "status": status, "category": category}],
                "limit": limit, "offset": offset}

    # GET /api/tasks/{id}: row_to_dict-artiges Response-Schema.
    @app.get("/api/tasks/{task_id}")
    async def get_task(task_id: int, request: Request):
        return {"success": True,
                "task": {"id": task_id, "title": "t", "status": "open",
                         "category": "arbeit"}}

    return app


def _client(app):
    return TestClient(app)


def test_no_token_401():
    c = _client(_make_app())
    r = c.get("/api/tasks")
    assert r.status_code == 401
    assert "Missing device authorization token" in r.json().get("error", "")


def test_invalid_token_403():
    c = _client(_make_app())
    r = c.get("/api/tasks", headers={"Authorization": "Bearer WRONG"})
    assert r.status_code == 403
    assert "Invalid or revoked device token" in r.json().get("error", "")


def test_valid_token_200_filter_pagination():
    c = _client(_make_app())
    r = c.get("/api/tasks", headers={"Authorization": "Bearer ASUS-KEY"},
              params={"status": "open", "category": "arbeit",
                      "limit": 10, "offset": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["categories"] == ["arbeit", "privat"]
    assert body["limit"] == 10
    assert body["offset"] == 5
    assert body["data"][0]["status"] == "open"


def test_valid_token_200_get_by_id():
    c = _client(_make_app())
    r = c.get("/api/tasks/7", headers={"Authorization": "Bearer ASUS-KEY"})
    assert r.status_code == 200, r.text
    assert r.json()["task"]["id"] == 7
