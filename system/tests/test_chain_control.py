# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tests fuer llmauto-Laufsteuerung auf Chain-Ebene.
"""

from datetime import datetime
from pathlib import Path
import sys


import pytest


SYSTEM_ROOT = Path(__file__).parent.parent
TOOLS_ROOT = SYSTEM_ROOT / "tools"

if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from llmauto.core.state import ChainState  # noqa: E402
from llmauto.modes.chain import (  # noqa: E402
    _apply_operator_controls,
    _import_scheduler_operator_steer,
    show_status,
)


class TestChainControlState:
    def test_pause_and_steer_roundtrip(self, tmp_path):
        state = ChainState("demo", tmp_path)

        assert state.get_pause_request() is None
        assert state.peek_steer_requests() == []

        payload = state.request_pause("Auf Operator warten")
        assert payload["reason"] == "Auf Operator warten"
        assert state.is_pause_requested() is True
        assert state.get_pause_request()["reason"] == "Auf Operator warten"

        state.clear_pause()
        assert state.is_pause_requested() is False

        state.request_steer("Bitte den nächsten Lauf auf Doku fokussieren.")
        state.request_steer("Logs nicht vergessen.")

        queued = state.peek_steer_requests()
        assert len(queued) == 2
        assert queued[0]["message"].startswith("Bitte den nächsten Lauf")

        consumed = state.consume_steer_requests()
        assert len(consumed) == 2
        assert state.peek_steer_requests() == []

    def test_reset_clears_control_files(self, tmp_path):
        state = ChainState("demo", tmp_path)
        state.request_pause("Pause")
        state.request_steer("Hinweis")

        state.reset()

        assert state.get_pause_request() is None
        assert state.peek_steer_requests() == []
        assert state.get_status() == "READY"

    def test_scheduler_operator_steer_env_is_imported_into_chain_queue(self, tmp_path, monkeypatch):
        state = ChainState("demo", tmp_path)
        monkeypatch.setenv(
            "BACH_SCHEDULER_OPERATOR_STEER",
            (
                '[{"message":"Bitte nur Docs prüfen.","requested_at":"2026-05-27T12:30:00"},'
                '{"message":"Vor Abschluss Status melden.","requested_at":"2026-05-27T12:31:00"}]'
            ),
        )

        imported = _import_scheduler_operator_steer(state, "demo")
        queued = state.peek_steer_requests()

        assert imported == 2
        assert "BACH_SCHEDULER_OPERATOR_STEER" not in __import__("os").environ
        assert [item["message"] for item in queued] == [
            "Bitte nur Docs prüfen.",
            "Vor Abschluss Status melden.",
        ]
        assert queued[0]["created_at"] == "2026-05-27T12:30:00"

        can_continue, operator_steer, control_reason = _apply_operator_controls("demo", state, {})

        assert can_continue is True
        assert control_reason == ""
        assert "Bitte nur Docs prüfen." in operator_steer
        assert "Vor Abschluss Status melden." in operator_steer
        assert state.peek_steer_requests() == []


class TestChainControlStatus:
    def test_show_status_mentions_pause_and_steer(self, tmp_path, capsys):
        base_dir = tmp_path
        state = ChainState("demo", base_dir)
        state.set_status("RUNNING")
        state.round_file.write_text("2", encoding="utf-8")
        state.start_time_file.write_text(datetime.now().isoformat(), encoding="utf-8")
        state.write_handoff(
            "# Handoff - Runde 2\n"
            "## Rolle: WORKER\n"
            "## Task: Demo-Aufgabe\n"
            "## Status: NEEDS_REVIEW\n"
        )
        state.request_pause("Warte auf Review")
        state.request_steer("Beim nächsten Schritt nur Statusflächen anfassen.")

        rc = show_status("demo", base_dir=base_dir)
        captured = capsys.readouterr().out

        assert rc == 0
        assert "PAUSE" in captured
        assert "STEER" in captured
        assert "Demo-Aufgabe" in captured
