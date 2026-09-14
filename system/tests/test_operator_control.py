# SPDX-License-Identifier: MIT
"""Tests fuer OPS-RUN-001: Operator-Steuerung langer Agenten-Laeufe.

Deckt den Konsumenten (hub/_services/chat/operator_control.py) und seine
Integration in den Tool-Loop der Chat-Runtime ab.
"""
import asyncio
import json
import threading
import time
from pathlib import Path

import pytest

from hub._services.chat.operator_control import (
    OperatorControl, NOTES_FILE, PAUSE_FILE, CHECKPOINT_FILE,
)


def _write(path: Path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


# --------------------------------------------------------------------------
# OperatorControl: Steer-Notizen
# --------------------------------------------------------------------------

class TestDrainNotes:
    def test_liefert_nur_neue_hinweise(self, tmp_path):
        ctrl = OperatorControl(tmp_path)
        _write(tmp_path / NOTES_FILE, [{"message": "eins", "requested_at": "t1"}])
        assert [n["message"] for n in ctrl.drain_notes()] == ["eins"]
        assert ctrl.drain_notes() == []  # nichts Neues
        _write(tmp_path / NOTES_FILE, [
            {"message": "eins", "requested_at": "t1"},
            {"message": "zwei", "requested_at": "t2"},
        ])
        assert [n["message"] for n in ctrl.drain_notes()] == ["zwei"]

    def test_clear_steer_setzt_zaehler_zurueck(self, tmp_path):
        ctrl = OperatorControl(tmp_path)
        _write(tmp_path / NOTES_FILE, [{"message": "alt", "requested_at": "t1"}])
        ctrl.drain_notes()
        (tmp_path / NOTES_FILE).unlink()  # bach agent clear-steer
        _write(tmp_path / NOTES_FILE, [{"message": "neu", "requested_at": "t2"}])
        assert [n["message"] for n in ctrl.drain_notes()] == ["neu"]

    def test_eintraege_ohne_message_werden_ignoriert(self, tmp_path):
        ctrl = OperatorControl(tmp_path)
        _write(tmp_path / NOTES_FILE, [{"requested_at": "t0"},
                                       {"message": "ok", "requested_at": "t1"}])
        assert [n["message"] for n in ctrl.drain_notes()] == ["ok"]

    def test_fehlende_und_kaputte_datei_sind_fail_soft(self, tmp_path):
        ctrl = OperatorControl(tmp_path)
        assert ctrl.drain_notes() == []
        (tmp_path / NOTES_FILE).write_text("{kein json", encoding="utf-8")
        assert ctrl.drain_notes() == []


# --------------------------------------------------------------------------
# OperatorControl: Kooperative Pause
# --------------------------------------------------------------------------

class TestPause:
    def test_pending_pause_und_fail_soft(self, tmp_path):
        ctrl = OperatorControl(tmp_path)
        assert ctrl.pending_pause() is None
        _write(tmp_path / PAUSE_FILE, {"reason": "Kaffee", "requested_at": "t"})
        assert ctrl.pending_pause()["reason"] == "Kaffee"
        _write(tmp_path / PAUSE_FILE, {"requested_at": "t"})  # ohne reason
        assert ctrl.pending_pause() is None

    def test_wait_if_paused_kehrt_ohne_pause_sofort_zurueck(self, tmp_path):
        ctrl = OperatorControl(tmp_path)
        info = asyncio.run(ctrl.wait_if_paused())
        assert info == {"paused": False, "waited_sec": 0.0, "timed_out": False}

    def test_wait_if_paused_wartet_bis_resume_loescht(self, tmp_path):
        pause = tmp_path / PAUSE_FILE
        _write(pause, {"reason": "Stopp", "requested_at": "t"})
        ctrl = OperatorControl(tmp_path, poll_interval=0.02, max_pause_wait=5.0)

        def resume():
            time.sleep(0.15)
            pause.unlink()

        threading.Thread(target=resume).start()
        info = asyncio.run(ctrl.wait_if_paused())
        assert info["paused"] and not info["timed_out"]
        assert info["waited_sec"] >= 0.1

    def test_wait_if_paused_gibt_nach_max_wait_auf(self, tmp_path):
        _write(tmp_path / PAUSE_FILE, {"reason": "vergessen", "requested_at": "t"})
        ctrl = OperatorControl(tmp_path, poll_interval=0.02, max_pause_wait=0.1)
        info = asyncio.run(ctrl.wait_if_paused())
        assert info["paused"] and info["timed_out"]


# --------------------------------------------------------------------------
# OperatorControl: Checkpoint
# --------------------------------------------------------------------------

class TestCheckpoint:
    def test_neuer_checkpoint_wird_genau_einmal_geliefert(self, tmp_path):
        ctrl = OperatorControl(tmp_path)
        _write(tmp_path / CHECKPOINT_FILE,
               {"acknowledged_at": "2026-09-12T08:00:00", "message": "Sicher"})
        cp = ctrl.consume_new_checkpoint()
        assert cp and cp["message"] == "Sicher"
        assert ctrl.consume_new_checkpoint() is None
        # Neuer Zeitstempel = neue Bestaetigung
        _write(tmp_path / CHECKPOINT_FILE,
               {"acknowledged_at": "2026-09-12T09:00:00", "message": "Noch sicherer"})
        assert ctrl.consume_new_checkpoint()["message"] == "Noch sicherer"

    def test_default_message_und_fail_soft(self, tmp_path):
        ctrl = OperatorControl(tmp_path)
        assert ctrl.consume_new_checkpoint() is None
        _write(tmp_path / CHECKPOINT_FILE, {"acknowledged_at": "t1"})
        assert ctrl.consume_new_checkpoint()["message"] == "Sicherer Checkpoint erreicht."


# --------------------------------------------------------------------------
# Integration: Tool-Loop konsumiert Steuerung an der Modell-Grenze
# --------------------------------------------------------------------------

class _RecordingBackend:
    """Antwortet sofort final und protokolliert jede gesehene Nachricht."""

    def __init__(self):
        self.seen: list[list[str]] = []

    def get_default_model(self):
        return "test-model"

    async def chat(self, messages, **kwargs):
        self.seen.append([m.get("content", "") for m in messages])
        return {"content": "Fertig."}


def _runtime():
    from hub._services.chat.chat_runtime import ChatRuntime
    backend = _RecordingBackend()
    rt = ChatRuntime(backend)
    rt.auto_continue = 0  # kein automatisches Nachlegen nach der Antwort
    return rt, backend


class TestToolLoopIntegration:
    def _run(self, session, msgs, tmp_path):
        rt, backend = _runtime()
        asyncio.run(rt._tool_loop(msgs, session, tools=[]))
        return backend

    def test_steer_hinweis_wird_vor_erstem_modellcall_injiziert(self, tmp_path):
        rt, backend = _runtime()
        session = rt.get_session("agent-test")
        session.operator_control = OperatorControl(tmp_path)
        _write(tmp_path / NOTES_FILE,
               [{"message": "Bitte zuerst die Tests lesen.", "requested_at": "t1"}])
        asyncio.run(rt._tool_loop([{"role": "user", "content": "Aufgabe"}],
                                  session, tools=[]))
        first_call = backend.seen[0]
        assert any("[OPERATOR-HINWEIS" in c and "Tests lesen" in c
                   for c in first_call)

    def test_checkpoint_wird_injiziert(self, tmp_path):
        rt, backend = _runtime()
        session = rt.get_session("agent-test")
        session.operator_control = OperatorControl(tmp_path)
        _write(tmp_path / CHECKPOINT_FILE,
               {"acknowledged_at": "t1", "message": "Baseline ok"})
        asyncio.run(rt._tool_loop([{"role": "user", "content": "Aufgabe"}],
                                  session, tools=[]))
        assert any("[OPERATOR-CHECKPOINT" in c and "Baseline ok" in c
                   for c in backend.seen[0])

    def test_ohne_control_bleibt_verhalten_unveraendert(self):
        rt, backend = _runtime()
        session = rt.get_session("telegram-123")
        # operator_control bleibt None (Default)
        answer = asyncio.run(rt._tool_loop([{"role": "user", "content": "Hallo"}],
                                           session, tools=[]))
        assert answer == "Fertig."
        assert backend.seen[0] == ["Hallo"]

    def test_pause_verzoegert_den_modellcall_bis_resume(self, tmp_path):
        rt, backend = _runtime()
        session = rt.get_session("agent-test")
        session.operator_control = OperatorControl(
            tmp_path, poll_interval=0.02, max_pause_wait=5.0)
        pause = tmp_path / PAUSE_FILE
        _write(pause, {"reason": "Operator prueft", "requested_at": "t"})

        threading.Thread(target=lambda: (time.sleep(0.15), pause.unlink())).start()
        t0 = time.monotonic()
        answer = asyncio.run(rt._tool_loop([{"role": "user", "content": "Aufgabe"}],
                                           session, tools=[]))
        assert answer == "Fertig."
        assert time.monotonic() - t0 >= 0.1

    def test_kaputte_steuerdateien_aendern_nichts(self, tmp_path):
        rt, backend = _runtime()
        session = rt.get_session("agent-test")
        session.operator_control = OperatorControl(tmp_path)
        for fname in (NOTES_FILE, PAUSE_FILE, CHECKPOINT_FILE):
            (tmp_path / fname).write_text("{kaputt", encoding="utf-8")
        answer = asyncio.run(rt._tool_loop([{"role": "user", "content": "Aufgabe"}],
                                           session, tools=[]))
        assert answer == "Fertig."
