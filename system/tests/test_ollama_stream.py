# -*- coding: utf-8 -*-
"""Tests fuer den gestreamten Ollama-Aufruf und die Stille-Erkennung.

Die Stille laesst sich nicht gegen ein echtes Ollama testen, ohne es
abzuschiessen - deshalb ein gefaelschter HTTP-Client, der Zeilen liefert
oder eben schweigt. Der Live-Pfad (Antwort, Werkzeugaufruf, Token-Zahl)
wurde am 2026-09-05 gegen qwen3.8:27b-mlx geprueft.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hub._services.llm import model_backend as backend_module  # noqa: E402
from hub._services.llm.model_backend import OllamaBackend  # noqa: E402


class _FakeStream:
    """Antwortet mit vorgegebenen Zeilen."""

    def __init__(self, zeilen):
        self._zeilen = zeilen

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        for z in self._zeilen:
            yield z


class _FakeClient:
    def __init__(self, zeilen, ps_models=None, ps_bricht=False):
        self._zeilen = zeilen
        self._ps_models = ps_models if ps_models is not None else [{"name": "m"}]
        self._ps_bricht = ps_bricht
        self.ps_aufrufe = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, **kw):
        return _FakeStream(self._zeilen)

    async def get(self, url, **kw):
        self.ps_aufrufe += 1
        if self._ps_bricht:
            raise OSError("Verbindung weg")

        class R:
            def __init__(self, models):
                self._m = models

            def json(self):
                return {"models": self._m}

        return R(self._ps_models)


def _zeile(content="", done=False, tool_calls=None, prompt_tokens=None, thinking=None):
    d = {"message": {"role": "assistant", "content": content}, "done": done}
    if thinking is not None:
        d["message"]["thinking"] = thinking
    if tool_calls:
        d["message"]["tool_calls"] = tool_calls
    if prompt_tokens is not None:
        d["prompt_eval_count"] = prompt_tokens
    return json.dumps(d)


def _backend(client):
    """OllamaBackend mit gefaelschtem HTTP-Client.

    chat() importiert httpx erst in der Methode, es gibt also kein
    Modulattribut zum Ersetzen - der Austausch muss an httpx selbst
    passieren, und wird danach wieder zurueckgenommen.
    """
    import httpx
    # Nur beim ersten Mal merken: sonst speichert der zweite Aufruf das
    # Lambda des ersten als "Original" und das Zuruecksetzen zementiert
    # den Fake, statt ihn zu entfernen.
    if not hasattr(_backend, "_orig"):
        _backend._orig = httpx.AsyncClient
    httpx.AsyncClient = lambda *a, **k: client
    return OllamaBackend(default_model="m")


def _zuruecksetzen():
    import httpx
    if hasattr(_backend, "_orig"):
        httpx.AsyncClient = _backend._orig


try:
    import pytest

    @pytest.fixture(autouse=True)
    def _httpx_wiederherstellen():
        """Unter pytest laeuft der Selbstlauf-Block unten nicht.

        Ohne diese Fixture bleibt ``httpx.AsyncClient`` fuer den Rest des
        Prozesses ein Lambda. Jedes spaeter importierte Modul, das den Namen
        in einer Annotation auswertet, faellt dann um -- gemessen an
        ``mcp/client/streamable_http.py`` (``httpx.AsyncClient | None``:
        "unsupported operand type(s) for |: 'function' and 'NoneType'"),
        was ``test_smoke_imports`` reissen liess, sobald diese Datei davor
        lief. Ein Test darf den Prozess nicht fuer die naechsten vergiften.
        """
        yield
        _zuruecksetzen()
except ImportError:      # Selbstlauf ohne pytest: der Block unten raeumt auf
    pass


def test_fragmente_werden_zusammengesetzt():
    """Gestreamter Inhalt kommt in Stuecken - er muss vollstaendig ankommen."""
    client = _FakeClient([
        _zeile("Hal"), _zeile("lo "), _zeile("Welt", done=True, prompt_tokens=42),
    ])
    r = asyncio.run(_backend(client).chat([{"role": "user", "content": "x"}]))
    assert r["content"] == "Hallo Welt"
    assert r["prompt_tokens"] == 42
    assert r.get("error") is None


def test_werkzeugaufruf_ueberlebt_den_stream():
    tc = [{"function": {"name": "get_datetime", "arguments": {}}}]
    client = _FakeClient([_zeile(""), _zeile("", done=True, tool_calls=tc)])
    r = asyncio.run(_backend(client).chat([{"role": "user", "content": "x"}]))
    assert r["tool_calls"] == tc


def test_eof_ohne_abschlussmarker_ist_abbruch_mit_teilantwort():
    client = _FakeClient([_zeile("unfinished", done=False)])

    r = asyncio.run(_backend(client).chat([{"role": "user", "content": "x"}]))

    assert r["content"] == "unfinished"
    assert "error" in r
    assert "Abschlussmarker" in r["error"]


def test_tool_calls_aus_mehreren_chunks_bleiben_geordnet_erhalten():
    first = {"function": {"name": "first", "arguments": {"n": 1}}}
    second = {"function": {"name": "second", "arguments": {"n": 2}}}
    client = _FakeClient([
        _zeile(tool_calls=[first]),
        _zeile(done=True, tool_calls=[second]),
    ])

    r = asyncio.run(_backend(client).chat([{"role": "user", "content": "x"}]))

    assert r["tool_calls"] == [first, second]


def test_glm_cloud_tool_thinking_from_earlier_chunks_is_preserved():
    tc = [{"function": {"name": "get_datetime", "arguments": {}}}]
    client = _FakeClient([
        _zeile(thinking="ERSTER_ÜBERLEGUNGSTEIL"),
        _zeile(thinking="ZWEITER_TEIL"),
        _zeile(done=True, tool_calls=tc, thinking=""),
    ])

    r = asyncio.run(_backend(client).chat(
        [{"role": "user", "content": "CLOUD_OK"}],
        model="glm-5.3:cloud", think=True,
    ))

    assert r["tool_calls"] == tc
    assert r["content"] == ""
    assert r["raw_message"]["thinking"] == (
        "ERSTER_ÜBERLEGUNGSTEILZWEITER_TEIL"
    )
    assert r["raw_message"]["content"] == ""


def test_read_timeout_prueft_liveness_bis_zur_begrenzten_grace():
    import httpx

    class TimeoutStream(_FakeStream):
        def __init__(self):
            super().__init__([])
            self.calls = 0

        def aiter_lines(self):
            return self

        def __aiter__(self):
            return self

        async def __anext__(self):
            self.calls += 1
            if self.calls == 1:
                return _zeile("partial", done=False)
            raise httpx.ReadTimeout("still waiting")

    class TimeoutClient(_FakeClient):
        def stream(self, *args, **kwargs):
            return TimeoutStream()

    original_limit = backend_module.limit
    backend_module.limit = (
        lambda name: 2 if name == "BACH_LLM_IDLE_GRACE" else original_limit(name)
    )
    client = TimeoutClient([], ps_models=[{"name": "m"}])
    try:
        r = asyncio.run(_backend(client).chat([{"role": "user", "content": "x"}]))
    finally:
        backend_module.limit = original_limit

    assert client.ps_aufrufe == 2
    assert r["content"] == "partial"
    assert "ReadTimeout" in r["error"]


def test_real_httpx_timeout_verbraucht_grace_und_behaelt_ursache():
    """HTTPX beendet den Byte-Stream nach ReadTimeout dauerhaft."""
    import httpx

    class TimeoutBytes(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield (_zeile("partial", done=False) + "\n").encode("utf-8")
            raise httpx.ReadTimeout("transport stalled")

    ps_aufrufe = 0

    async def handler(request):
        nonlocal ps_aufrufe
        if request.url.path == "/api/chat":
            return httpx.Response(200, stream=TimeoutBytes())
        if request.url.path == "/api/ps":
            ps_aufrufe += 1
            return httpx.Response(200, json={"models": [{"name": "m"}]})
        return httpx.Response(404)

    original_limit = backend_module.limit
    backend_module.limit = (
        lambda name: 2 if name == "BACH_LLM_IDLE_GRACE" else original_limit(name)
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        r = asyncio.run(_backend(client).chat([{"role": "user", "content": "x"}]))
    finally:
        backend_module.limit = original_limit

    assert ps_aufrufe == 2
    assert r["content"] == "partial"
    assert "ReadTimeout" in r["error"]
    assert "transport stalled" in r["error"]


def test_leere_zeilen_zaehlen_nicht_als_regung():
    """Ollama sendet Leerzeilen; sie duerfen die Stille-Uhr nicht faelschen."""
    client = _FakeClient(["", "", _zeile("ok", done=True)])
    r = asyncio.run(_backend(client).chat([{"role": "user", "content": "x"}]))
    assert r["content"] == "ok"


def test_teilantwort_bleibt_bei_abbruch_erhalten():
    """Was schon da war, geht nicht verloren - sonst ist die Arbeit weg."""
    import httpx

    class Brechend(_FakeStream):
        async def aiter_lines(self):
            yield _zeile("halb fertig")
            raise httpx.ReadError("Leitung weg")

    class C(_FakeClient):
        def stream(self, *a, **k):
            return Brechend([])

    r = asyncio.run(_backend(C([])).chat([{"role": "user", "content": "x"}]))
    assert "halb fertig" in r["content"]
    assert r["error"], "ein Abbruch muss als Fehler erkennbar sein"
    assert "ReadError" in r["error"], "der Typname traegt den Grund - str() ist oft leer"


def test_lebt_toleriert_ladevorgang():
    """Waehrend 18 GB geladen werden, steht das Modell noch nicht in /api/ps -
    ein antwortender Dienst genuegt als Lebenszeichen."""
    be = OllamaBackend(default_model="qwen3.8:27b-mlx")
    client = _FakeClient([], ps_models=[])
    assert asyncio.run(be._lebt(client, "qwen3.8:27b-mlx")) is True


def test_lebt_erkennt_verdraengtes_modell():
    be = OllamaBackend(default_model="qwen3.8:27b-mlx")
    client = _FakeClient([], ps_models=[{"name": "ganz-anderes:7b"}])
    assert asyncio.run(be._lebt(client, "qwen3.8:27b-mlx")) is False


def test_lebt_erkennt_toten_dienst():
    be = OllamaBackend(default_model="m")
    assert asyncio.run(be._lebt(_FakeClient([], ps_bricht=True), "m")) is False


def test_lebt_akzeptiert_tagvariante():
    """qwen3.8:27b-mlx und qwen3.8:latest sind dasselbe Modell."""
    be = OllamaBackend(default_model="qwen3.8:27b-mlx")
    client = _FakeClient([], ps_models=[{"name": "qwen3.8:latest"}])
    assert asyncio.run(be._lebt(client, "qwen3.8:27b-mlx")) is True


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"OK    {name}")
        except AssertionError as e:
            fails += 1
            print(f"FEHL  {name}: {e}")
        except Exception as e:
            fails += 1
            print(f"FEHL  {name}: {type(e).__name__}: {e}")
        finally:
            _zuruecksetzen()
    print(f"\n{'ALLE GRUEN' if not fails else str(fails) + ' FEHLGESCHLAGEN'}")
    sys.exit(1 if fails else 0)
