# -*- coding: utf-8 -*-
"""Tests fuer den Pickup-Category-Picker (system/hub/pickup_category.py).

Task #2696 (category="BACH-OCEAN", priority="P2"): Beleg, dass
resolve_category auf "general" faellt und resolve_priority auf
DEFAULT_PRIORITY "normal" (kein explizites P2-Mapping).
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from hub import agent_runners
from hub import pickup_category

EXCL = ["food", "clothing", "electronics", "toys", "books", "media",
        "health", "finance", "utilities", "home", "gardening", "travel",
        "automotive", "construction"]


def test_exakt_14_ausschluesse():
    assert pickup_category.PICKUP_CATEGORY_EXCLUSIONS == EXCL
    assert len(EXCL) == 14


def test_resolve_category_bach_ocean_general():
    assert pickup_category.resolve_category("BACH-OCEAN") == "general"


def test_resolve_priority_p2_default_normal():
    assert "p2" not in pickup_category.PRIORITY_LEVELS
    assert pickup_category.resolve_priority("P2") == "normal"
    assert pickup_category.DEFAULT_PRIORITY == "normal"


def test_main_bach_ocean_p2(capsys):
    rc = pickup_category.main(["pickup_category.py", "BACH-OCEAN", "P2"])
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out) == {"pickup_category": "general", "priority": "normal",
                               "priority_level": 2, "excluded": False}


def test_runner_registrierung_und_echter_aufruf():
    spec = agent_runners.BUILTIN["pickup_category"]
    assert spec["match"] == ["pickup_category", "Picker", "pickup"]
    assert spec["cmd"][0] == sys.executable
    assert Path(spec["cmd"][1]).name == "pickup_category.py"
    assert Path(spec["cmd"][1]).is_file()
    i = spec["cmd"].index("--exclude")
    assert spec["cmd"][i + 1] == ",".join(EXCL)
    assert spec["priority"] == "high"
    proc = subprocess.run(
        [*spec["cmd"], "BACH-OCEAN", "P2"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    assert json.loads(proc.stdout) == {
        "pickup_category": "general",
        "priority": "normal",
        "priority_level": 2,
        "excluded": False,
    }


def test_beleglage_dokumentiert():
    base = Path(__file__).resolve().parent.parent / "hub"
    for name in ("pickup_category.py", "agent_runners.py"):
        raw = (base / name).read_bytes()
        assert raw, "%s ist leer" % name
        assert len(hashlib.sha256(raw).hexdigest()) == 64
