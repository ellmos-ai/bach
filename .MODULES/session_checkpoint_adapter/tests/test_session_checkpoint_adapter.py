# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Smoke test for session_checkpoint_adapter module."""
from pathlib import Path
import json

def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    assert manifest_p.exists()
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "session_checkpoint_adapter"
    assert data["selfcontained"] is True
