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
from llmauto.modes.chain import show_status  # noqa: E402


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
