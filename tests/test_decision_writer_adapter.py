"""Tests fuer den schmalen DecisionClicker-Writer-Adapter (#2015; kein zweiter Ledger, kein KI-Approve)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

_ADAPTER = (
    Path(__file__).resolve().parents[1]
    / "system"
    / "hub"
    / "_services"
    / "decision_writer_adapter.py"
)
_SPEC = importlib.util.spec_from_file_location("decision_writer_adapter", _ADAPTER)
assert _SPEC is not None and _SPEC.loader is not None
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)
Adapter = mod.DecisionWriterAdapter


class FakeResponse:
    """Minimale Response-Stellvertreter fuer alle Adapter-Pfade."""

    def __init__(self, status_code: int, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload: dict[str, Any] = payload if payload is not None else {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise mod.httpx.HTTPStatusError("boom", request=None, response=None)

    def json(self) -> dict[str, Any]:
        return self._payload


def test_constants() -> None:
    assert mod.ID == "decision-clicker"
    assert mod.VERSION == "1.1.2"
    assert mod.UI_URL == "http://127.0.0.1:8096"
    assert mod.PROPOSAL_URL == "http://127.0.0.1:8096/api/new"
    assert mod.PROPOSAL_URL == mod.UI_URL + "/api/new"


def test_is_available_connect_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: object, **kwargs: object) -> object:
        raise mod.httpx.ConnectError("connection refused")

    monkeypatch.setattr(mod.httpx, "get", _boom)
    available, reason = Adapter.is_available()
    assert available is False
    assert isinstance(reason, str)
    assert bool(reason)


def test_is_available_http_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod.httpx, "get", lambda *a, **k: FakeResponse(503))
    available, reason = Adapter.is_available()
    assert available is False
    assert reason == "status_code=503"
    assert "503" in reason


def test_is_available_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod.httpx, "get", lambda *a, **k: FakeResponse(200))
    assert Adapter.is_available() == (True, "ok")


def test_get_status_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Adapter, "is_available", staticmethod(lambda timeout=2.0: (False, "x")))
    status = Adapter.get_status()
    assert status["available"] is False
    assert status["reason"] == "x"


def test_get_status_available_reason_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Adapter, "is_available", staticmethod(lambda timeout=2.0: (True, "ok")))
    status = Adapter.get_status()
    assert status["available"] is True
    assert status["reason"] == "separate_explicit_adoption_required"
    assert {"id", "available", "reason", "ui_url", "proposal_url"} <= set(status)


def test_post_proposal_success(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"title": "Decision", "context": {"step": 1}}
    calls: list[tuple[str, dict[str, Any]]] = []

    def _fake_post(url: str, **kwargs: Any) -> FakeResponse:
        calls.append((url, kwargs))
        return FakeResponse(200, payload)

    monkeypatch.setattr(mod.httpx, "post", _fake_post)
    result = Adapter.post_proposal(payload)
    assert result == payload
    assert calls[0][0] == mod.PROPOSAL_URL
    assert calls[0][1]["json"] == payload


def test_post_proposal_http_status_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod.httpx, "post", lambda *a, **k: FakeResponse(500, {"nope": True}))
    result = Adapter.post_proposal({"x": 1})
    assert result["error"] == "http_status"
    assert "detail" in result
    assert "boom" in result["detail"]


def test_post_proposal_request_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("kaputt")

    monkeypatch.setattr(mod.httpx, "post", _boom)
    result = Adapter.post_proposal({"x": 1})
    assert result["error"] == "request_failed"
    assert "kaputt" in result["detail"]
