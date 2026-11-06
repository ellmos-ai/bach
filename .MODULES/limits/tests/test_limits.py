# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Smoke test for limits module."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import limits


def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    assert manifest_p.exists()
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "limits"
    assert data["selfcontained"] is True


def test_limit_defaults():
    assert limits.limit("BACH_CMD_TIMEOUT") == 30
    assert limits.limit("NON_EXISTING", 42) == 42


def test_get_all_limits():
    all_l = limits.get_all_limits()
    assert "BACH_LLM_TIMEOUT" in all_l
    assert all_l["BACH_MAX_TOOL_ROUNDS"] == 25
