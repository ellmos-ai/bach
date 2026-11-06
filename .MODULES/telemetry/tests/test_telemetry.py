# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Smoke test for telemetry module."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import telemetry


def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    assert manifest_p.exists()
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "telemetry"
    assert data["selfcontained"] is True


def test_telemetry_increment_and_status():
    assert telemetry.is_enabled() is True
    ok = telemetry.increment("model_calls", outcome="ok", model="gemini-flash")
    assert ok is True
    ok_stat, txt = telemetry.status()
    assert ok_stat is True
    assert "Erlaubte Counter" in txt


def test_telemetry_report():
    ok_rep, txt = telemetry.report(days=3)
    assert ok_rep is True
    assert "[TELEMETRIE REPORT" in txt
