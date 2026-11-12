# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Smoke test for agent_spawn_gate module."""
from pathlib import Path
import json

def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    assert manifest_p.exists()
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "agent_spawn_gate"
    assert data["selfcontained"] is True
