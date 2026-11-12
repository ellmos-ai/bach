# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Smoke test for scheduler_provider module."""
import json
import sys
from pathlib import Path

src_dir = Path(__file__).resolve().parent.parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from scheduler_provider import SchedulerProvider, probe_scheduler_provider


def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    assert manifest_p.exists()
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "scheduler_provider"
    assert data["selfcontained"] is True


def test_scheduler_provider_probe():
    prov = probe_scheduler_provider()
    assert isinstance(prov, SchedulerProvider)
    assert prov.name in ("ellmos-scheduler", "builtin")
