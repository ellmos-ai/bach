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

from hub._services.llm.model_backend import OllamaBackend  # noqa: E402


class _FakeStream:
    """Antwortet mit vorgegebenen Zeilen."""

    def __init__(self, zeilen):
        self._zeilen = zeilen

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

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


def _zeile(content="", done=False, tool_calls=None, prompt_tokens=None):
    d = {"message": {"role": "assistant", "content": content}, "done": done}
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
    _backend._orig = httpx.AsyncClient
    httpx.AsyncClient = lambda *a, **k: client
    return OllamaBackend(default_model="m")


def _zuruecksetzen():
    import httpx
    if hasattr(_backend, "_orig"):
        httpx.AsyncClient = _backend._orig


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
