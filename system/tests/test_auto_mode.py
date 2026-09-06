# -*- coding: utf-8 -*-
"""Tests fuer den Loop-Mode (/auto) und die Ziel-Gegenpruefung (/goal).

Der Tool-Loop endet normalerweise, sobald das Modell eine Antwort ohne
Werkzeugaufruf schickt. Im Loop-Mode wird stattdessen nachgeschoben.
Diese Tests decken die Entscheidungslogik ab, ohne ein Modell zu rufen.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hub._services.chat.chat_runtime import (  # noqa: E402
    ChatRuntime, AUTO_NUDGE, HANDOFF_PROMPT,
)
from hub._services.limits import limit  # noqa: E402


def _runtime():
    return ChatRuntime(backend=None, system_prompt="test")


def test_default_ist_aus():
    """Ohne /auto verhaelt sich BACH exakt wie vorher."""
    r = _runtime()
    assert r.auto_continue == 0
    assert r._auto_next("Soll ich weitermachen?", 0, False)[0] is None


def test_nudge_wenn_aktiv():
    r = _runtime()
    r.auto_continue = 3
    assert r._auto_next("Soll ich weitermachen?", 0, False)[0] == AUTO_NUDGE


def test_budget_wird_eingehalten():
    """Nach n Nachschueben ist Schluss - keine Endlosschleife."""
    r = _runtime()
    r.auto_continue = 3
    assert r._auto_next("weiter?", 2, False)[0] == AUTO_NUDGE
    assert r._auto_next("weiter?", 3, False)[0] is None
    assert r._auto_next("weiter?", 99, False)[0] is None


def test_fertig_ohne_ziel_beendet():
    r = _runtime()
    r.auto_continue = 5
    assert r._auto_next("FERTIG", 0, False)[0] is None


def test_fertig_mit_ziel_prueft_genau_einmal():
    """Bei gesetztem Ziel wird einmal gegengeprueft, dann ist Schluss."""
    r = _runtime()
    r.auto_continue = 5
    r.goal = "App muss alle 20 Punkte erfuellen"

    erste, geprueft = r._auto_next("FERTIG", 0, False)
    assert erste is not None
    assert "alle 20 Punkte" in erste, "Ziel muss in der Pruefaufforderung stehen"
    assert geprueft is True

    # Kein zweites Mal - sonst laeuft die Pruefung im Kreis.
    assert r._auto_next("FERTIG", 1, geprueft)[0] is None


def test_fertig_erkennung_ist_case_insensitiv():
    r = _runtime()
    r.auto_continue = 5
    assert r._auto_next("fertig", 0, False)[0] is None
    assert r._auto_next("Fertig!", 0, False)[0] is None


def test_limits_sind_einstellbar():
    """Grenzen kommen aus der Umgebung, kaputte Werte fallen auf Default."""
    assert limit("BACH_MAX_MESSAGES") == 40
    os.environ["BACH_MAX_MESSAGES"] = "99"
    try:
        assert limit("BACH_MAX_MESSAGES") == 99
        os.environ["BACH_MAX_MESSAGES"] = "kaputt"
        assert limit("BACH_MAX_MESSAGES") == 40
    finally:
        del os.environ["BACH_MAX_MESSAGES"]


# --- Kontext-Uebergabe ------------------------------------------------------

import asyncio
from hub._services.chat.chat_runtime import HANDOFF_PROMPT  # noqa: E402


class _FakeBackend:
    """Liefert eine vorgegebene Antwort und merkt sich die Anfrage."""

    def __init__(self, content="AUFTRAG: x\nRESUME: weiter"):
        self.content = content
        self.gesehen = None

    async def chat(self, messages, tools=None, think=True, model=None):
        self.gesehen = list(messages)
        return {"content": self.content, "tool_calls": None, "raw_message": {}}

    def get_default_model(self):
        return "test-model"

    def list_models(self):
        return ["test-model"]


def test_context_voll_ohne_tokenzahl_ist_false():
    """Ohne Token-Zahl vom Backend wird nicht geraten."""
    r = _runtime()
    assert r._context_voll({}) is False
    assert r._context_voll({"prompt_tokens": None}) is False
    assert r._context_voll({"prompt_tokens": "viele"}) is False


def test_context_voll_ab_schwelle():
    r = _runtime()
    r.context_limit = 1000
    r.handoff_percent = 75
    assert r._context_voll({"prompt_tokens": 700}) is False
    assert r._context_voll({"prompt_tokens": 750}) is True
    assert r._context_voll({"prompt_tokens": 900}) is True


def test_handoff_abschaltbar():
    r = _runtime()
    r.context_limit = 1000
    r.handoff_percent = 0
    assert r._context_voll({"prompt_tokens": 999}) is False


def test_handoff_ersetzt_kontext_durch_uebergabe():
    r = _runtime()
    be = _FakeBackend("AUFTRAG: App bauen\nERLEDIGT: main.py\nRESUME: Tests")
    r.backend = be
    session = r.get_session("handoff-test")
    alt = [{"role": "user", "content": "x"}] * 12

    neu = asyncio.run(r._handoff(alt, session))

    assert len(neu) == 1, "der Kontext muss auf die Uebergabe zusammenschrumpfen"
    assert "RESUME: Tests" in neu[0]["content"]
    assert r.last_handoff.startswith("AUFTRAG:")
    assert be.gesehen[-1]["content"] == HANDOFF_PROMPT


def test_handoff_faellt_zurueck_statt_alles_zu_verlieren():
    """Antwortet das Modell nicht, wird gekuerzt - aber nicht geleert."""
    r = _runtime()
    r.backend = _FakeBackend("")
    session = r.get_session("handoff-leer")
    alt = [{"role": "system", "content": "sys"}] + [
        {"role": "user", "content": str(i)} for i in range(10)
    ]
    neu = asyncio.run(r._handoff(alt, session))
    assert neu[0]["content"] == "sys", "Systemnachricht muss bleiben"
    assert len(neu) == 5
    assert neu[-1]["content"] == "9", "die juengsten Schritte bleiben erhalten"


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
    print(f"\n{'ALLE GRUEN' if not fails else str(fails) + ' FEHLGESCHLAGEN'}")
    sys.exit(1 if fails else 0)
