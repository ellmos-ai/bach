"""Tests für die Provider-Request-Phasen-Zählung im Chat-Worker.

Der Telemetrie-Counter „provider_request_phases“ (Labels: phase, agent)
macht die Phasen eines Provider-Requests im Worker beobachtbar. Die Tests
prüfen ausschließlich die Zeilen der SQLite-Tabelle „telemetry_counters“;
request_id, fence und generation dürfen nie als Label-Wert auftauchen.
"""

import asyncio
import json
import sqlite3

import pytest

from hub._services.chat import telegram_chat as tc

import core.telemetry as telemetry


class _Ack:
    """Attrappe für das Acknowledgement eines Task-Bindings."""

    def __init__(self, fence):
        self.fence = fence


class _Binding:
    """Attrappe für ein aktives Task-Binding."""

    def __init__(self, task_id, generation, fence):
        self.task_id = task_id
        self.generation = generation
        self._ack = _Ack(fence)

    def assert_active(self):
        return None


def _make_control(monkeypatch, worker_id="w-test-1"):
    """Erzeugt ein im Control-Register gemeldetes Worker-Control."""
    control = tc._WorkerControl(worker_id)
    control.stop_event = asyncio.Event()
    binding = _Binding(4242, control.generation, 77)
    control.task_binding = binding
    monkeypatch.setitem(tc._WORKER_CONTROLS, worker_id, control)
    return control, binding


def _patch_db(monkeypatch, tmp_path):
    """Leitet die Telemetrie in eine frische SQLite-Datei um."""
    monkeypatch.delenv("BACH_TELEMETRY_DISABLED", raising=False)
    db = tmp_path / "telemetry.db"
    monkeypatch.setattr(telemetry, "_get_db_path", lambda: db)
    return db


def _rows(db):
    """Liest alle Zeilen des Counters „provider_request_phases“."""
    conn = sqlite3.connect(str(db))
    try:
        cur = conn.execute(
            "SELECT counter, labels, value FROM telemetry_counters "
            "WHERE counter = 'provider_request_phases'"
        )
        return cur.fetchall()
    finally:
        conn.close()


def _parsed(labels):
    """Wandelt das Label-JSON in ein Dictionary um."""
    return json.loads(labels)


def _assert_row(all_rows, phase, outcome, agent):
    """Prüft, dass eine Zeile mit Phase, Outcome und Agent existiert."""
    for _counter, labels, value in all_rows:
        data = _parsed(labels)
        if (
            data.get("phase") == phase
            and data.get("outcome") == outcome
            and data.get("agent") == agent
            and value >= 1
        ):
            return
    raise AssertionError(
        "Keine Zeile für phase=%r outcome=%r agent=%r; vorhanden: %r"
        % (phase, outcome, agent, all_rows)
    )


def _register_ok(control, binding):
    """Registriert einen Provider-Request und gibt ihn zurück."""
    req = control.register_provider_request(
        binding, None, None, transport="ollama_httpx"
    )
    assert req is not None
    return req


def _durchlaufe_erfolgs_kette(control, req):
    """Läuft die Phasen einer erfolgreichen Provider-Antwort durch."""
    for phase in (
        "transport_open",
        "response_headers_received",
        "first_stream_chunk_received",
        "response_completed",
    ):
        assert control.observe_provider_request(req, phase) is True


def test_register_zaehlt_registered(tmp_path, monkeypatch):
    """register zählt die Phase „registered“ mit Outcome „ok“."""
    control, binding = _make_control(monkeypatch)
    db = _patch_db(monkeypatch, tmp_path)
    _register_ok(control, binding)
    _assert_row(_rows(db), "registered", "ok", "w-test-1")


def test_observe_kette_zaehlt_ok_phasen(tmp_path, monkeypatch):
    """Eine erfolgreiche Kette zählt jede Phase mit Outcome „ok“."""
    control, binding = _make_control(monkeypatch)
    db = _patch_db(monkeypatch, tmp_path)
    req = _register_ok(control, binding)
    _durchlaufe_erfolgs_kette(control, req)
    all_rows = _rows(db)
    assert len(all_rows) == 5
    for phase in (
        "registered",
        "transport_open",
        "response_headers_received",
        "first_stream_chunk_received",
        "response_completed",
    ):
        _assert_row(all_rows, phase, "ok", "w-test-1")


def test_finish_nach_abschluss_zaehlt_runtime_call_complete_ok(tmp_path, monkeypatch):
    """finish nach abgeschlossener Antwort zählt „runtime_call_complete“ mit „ok“."""
    control, binding = _make_control(monkeypatch)
    db = _patch_db(monkeypatch, tmp_path)
    req = _register_ok(control, binding)
    _durchlaufe_erfolgs_kette(control, req)
    assert control.finish_provider_request(req, result={"content": "x"}) is True
    _assert_row(_rows(db), "runtime_call_complete", "ok", "w-test-1")


def test_finish_provider_error_zaehlt_error(tmp_path, monkeypatch):
    """Ein Fehler im Ergebnis zählt „runtime_call_complete“ mit „error“."""
    control, binding = _make_control(monkeypatch)
    db = _patch_db(monkeypatch, tmp_path)
    req = _register_ok(control, binding)
    assert control.finish_provider_request(req, result={"error": "boom"}) is True
    all_rows = _rows(db)
    _assert_row(all_rows, "runtime_call_complete", "error", "w-test-1")
    assert not any(
        _parsed(labels).get("phase") == "request_failed"
        for _counter, labels, _value in all_rows
    )


def test_finish_total_deadline_zaehlt_error(tmp_path, monkeypatch):
    """Abbruch über die Gesamtdeadline zählt „runtime_call_complete“ mit „error“."""
    control, binding = _make_control(monkeypatch)
    db = _patch_db(monkeypatch, tmp_path)
    req = _register_ok(control, binding)
    assert control.finish_provider_request(
        req, result={"provider_request_aborted": "total_deadline"}
    ) is True
    all_rows = _rows(db)
    _assert_row(all_rows, "runtime_call_complete", "error", "w-test-1")
    assert not any(
        _parsed(labels).get("phase") == "request_aborted"
        for _counter, labels, _value in all_rows
    )


def test_finish_cancelled_zaehlt_error(tmp_path, monkeypatch):
    """Abbruch über CancelledError zählt „runtime_call_complete“ mit „error“."""
    control, binding = _make_control(monkeypatch)
    db = _patch_db(monkeypatch, tmp_path)
    req = _register_ok(control, binding)
    assert control.finish_provider_request(req, error=asyncio.CancelledError()) is True
    _assert_row(_rows(db), "runtime_call_complete", "error", "w-test-1")


def test_observe_request_aborted_zaehlt_error(tmp_path, monkeypatch):
    """Ein beobachteter Abbruch zählt „request_aborted“ mit „error“."""
    control, binding = _make_control(monkeypatch)
    db = _patch_db(monkeypatch, tmp_path)
    req = _register_ok(control, binding)
    assert control.observe_provider_request(
        req, "request_aborted", reason="worker_stop"
    ) is True
    _assert_row(_rows(db), "request_aborted", "error", "w-test-1")
    assert control.finish_provider_request(req, result=None) is True


def test_observe_request_failed_zaehlt_error(tmp_path, monkeypatch):
    """Ein beobachteter Fehler zählt „request_failed“ mit „error“."""
    control, binding = _make_control(monkeypatch)
    db = _patch_db(monkeypatch, tmp_path)
    req = _register_ok(control, binding)
    assert control.observe_provider_request(
        req, "request_failed", reason="httpx_read_timeout"
    ) is True
    _assert_row(_rows(db), "request_failed", "error", "w-test-1")


def test_privacy_ohne_request_id_fence_generation(tmp_path, monkeypatch):
    """Kein Label enthält request_id, fence oder generation."""
    control, binding = _make_control(monkeypatch)
    db = _patch_db(monkeypatch, tmp_path)
    req = _register_ok(control, binding)
    _durchlaufe_erfolgs_kette(control, req)
    all_rows = _rows(db)
    verboten = {req.request_id, "77", str(control.generation)}
    for _counter, labels, _value in all_rows:
        for wert in _parsed(labels).values():
            assert wert not in verboten, (
                "Label-Wert %r verletzt die Privatsphäre (Zeilen: %r)"
                % (wert, all_rows)
            )
    _assert_row(all_rows, "response_completed", "ok", "w-test-1")


def test_label_clamping(tmp_path, monkeypatch):
    """Ungültige Phase- und Outcome-Werte werden auf „other“ begrenzt."""
    db = _patch_db(monkeypatch, tmp_path)
    telemetry.add_provider_request_phase(
        "BAD PHASE!", outcome="bogus", agent="w-test-1"
    )
    _assert_row(_rows(db), "other", "other", "w-test-1")


def test_counter_definition():
    """Der Counter ist mit den Labels „phase“ und „agent“ definiert."""
    assert telemetry.COUNTERS["provider_request_phases"] == {"phase", "agent"}


def test_provider_request_id_header_kein_netz(monkeypatch, tmp_path):
    """Regression (b/c): echter httpx.AsyncClient mit MockTransport, kein Netz.

    Der Header „X-BACH-Provider-Request-Id“ trägt die im Worker registrierte
    request_id; alle Happy-Path-Phasen werden gezählt, Privatsphäre gilt.
    """
    import httpx

    from hub._services.llm.model_backend import OllamaBackend

    db = _patch_db(monkeypatch, tmp_path)
    control, binding = _make_control(monkeypatch)
    req = _register_ok(control, binding)
    assert control.observe_provider_request(req, "request_starting") is True

    gefangener_header = {}

    class _AntwortStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            zeilen = [
                {"message": {"role": "assistant", "content": "hal"}, "done": False},
                {"message": {"role": "assistant", "content": "lo"}, "done": False},
                {"message": {"role": "assistant", "content": ""},
                 "done": True, "prompt_eval_count": 3, "eval_count": 4},
            ]
            for zeile in zeilen:
                yield (json.dumps(zeile) + "\n").encode("utf-8")

    async def handler(request):
        if request.url.path == "/api/chat":
            gefangener_header["X-BACH-Provider-Request-Id"] = (
                request.headers.get("X-BACH-Provider-Request-Id")
            )
            return httpx.Response(200, stream=_AntwortStream())
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": "m"}]})
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: client)
    backend = OllamaBackend(default_model="m")

    def report_lifecycle(phase, *, reason=None):
        control.observe_provider_request(req, phase, reason=reason)

    async def _aufruf():
        return await backend.chat(
            [{"role": "user", "content": "x"}],
            lifecycle_observer=report_lifecycle,
            provider_request_id=req.request_id,
        )

    ergebnis = asyncio.run(_aufruf())
    assert control.finish_provider_request(req, result=ergebnis, error=None) is True

    assert gefangener_header["X-BACH-Provider-Request-Id"] == req.request_id
    all_rows = _rows(db)
    for phase in (
        "request_starting",
        "transport_open",
        "awaiting_response_headers",
        "response_headers_received",
        "first_stream_chunk_received",
        "response_completed",
        "response_cleanup_complete",
        "client_cleanup_complete",
        "runtime_call_complete",
    ):
        _assert_row(all_rows, phase, "ok", "w-test-1")

    verboten = {req.request_id, "77", str(control.generation)}
    for _counter, labels, _value in all_rows:
        for wert in _parsed(labels).values():
            assert str(wert) not in verboten