"""Tests fuer hub._services.decision_writer_adapter.

Reine Unit-Tests ohne Netzwerk: httpx.get/httpx.post werden per monkeypatch
ersetzt. Es wird ausdruecklich KEIN Freigabe-/Approve-Pfad getestet, weil es
einen solchen nicht geben darf (Vorschlag != Entscheidung).
"""

from __future__ import annotations

import httpx
import pytest

from hub._services import decision_writer_adapter as dwa


# --------------------------------------------------------------------------
# Hilfsklassen
# --------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status_code={self.status_code}",
                request=httpx.Request("GET", dwa.UI_URL),
                response=httpx.Response(self.status_code),
            )


# --------------------------------------------------------------------------
# is_available()
# --------------------------------------------------------------------------
def test_is_available_ok(monkeypatch):
    monkeypatch.setattr(dwa.httpx, "get", lambda *a, **kw: _FakeResponse(200))
    available, reason = dwa.is_available()
    assert available is True
    assert reason == "ok"


def test_is_available_status_code_503(monkeypatch):
    monkeypatch.setattr(dwa.httpx, "get", lambda *a, **kw: _FakeResponse(503))
    available, reason = dwa.is_available()
    assert available is False
    assert reason == "status_code=503"


def test_is_available_exception(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(dwa.httpx, "get", _boom)
    available, reason = dwa.is_available()
    assert available is False
    assert reason == "connection refused"


# --------------------------------------------------------------------------
# get_status()
# --------------------------------------------------------------------------
def test_get_status_available(monkeypatch):
    monkeypatch.setattr(
        dwa.DecisionWriterAdapter,
        "is_available",
        staticmethod(lambda timeout=2.0: (True, "ok")),
    )
    status = dwa.get_status()

    assert set(status) == {"id", "available", "reason", "ui_url", "proposal_url"}
    assert status["id"] == "decision-clicker"
    assert status["available"] is True
    assert status["reason"] == "separate_explicit_adoption_required"
    assert status["ui_url"] == "http://127.0.0.1:8096"
    assert status["proposal_url"].endswith("/api/new")


def test_get_status_unavailable(monkeypatch):
    monkeypatch.setattr(
        dwa.DecisionWriterAdapter,
        "is_available",
        staticmethod(lambda timeout=2.0: (False, "timeout")),
    )
    status = dwa.get_status()

    assert status["available"] is False
    assert status["reason"] == "timeout"


# --------------------------------------------------------------------------
# post_proposal() -- nur Vorschlag, keine Freigabe
# --------------------------------------------------------------------------
def test_post_proposal_request_failed(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(dwa.httpx, "post", _boom)
    result = dwa.post_proposal({"title": "x"})

    assert result["error"] == "request_failed"
    assert "detail" in result


def test_post_proposal_http_status(monkeypatch):
    def _fake_post(*a, **kw):
        return _FakeResponse(500)

    monkeypatch.setattr(dwa.httpx, "post", _fake_post)
    result = dwa.post_proposal({"title": "x"})

    assert result["error"] == "http_status"
    assert "detail" in result


def test_module_has_no_approve_entrypoint():
    """Es darf keinen KI-Approve-Endpunkt auf Modulebene geben."""
    public_names = {name for name in dir(dwa) if not name.startswith("_")}
    for forbidden in ("approve", "approve_decision", "decide"):
        assert forbidden not in public_names
