# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Smoke test for domain_writer_gate module."""
import json
import sys
from pathlib import Path

src_dir = Path(__file__).resolve().parent.parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from domain_writer_gate import blocked_reason, known_domains, legacy_domain_writes_enabled


def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    assert manifest_p.exists()
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "domain_writer_gate"
    assert data["selfcontained"] is True


def test_domain_writer_gate_functionality():
    domains = known_domains()
    assert "medication" in domains
    assert "routine" in domains
    assert legacy_domain_writes_enabled({}) is False
    reason = blocked_reason("medication", "test_op", environ={})
    assert reason is not None
    assert "[GESPERRT]" in reason
