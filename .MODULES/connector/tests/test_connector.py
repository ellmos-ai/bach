# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit tests for standalone connector module."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from connector import ConnectorRegistry, compute_backoff_seconds


def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "connector"
    assert data["selfcontained"] is True


def test_backoff_and_registry_dispatch():
    assert compute_backoff_seconds(0, base_seconds=5.0, cap_seconds=60.0) == 5.0
    assert compute_backoff_seconds(3, base_seconds=5.0, cap_seconds=60.0) == 40.0
    assert compute_backoff_seconds(10, base_seconds=5.0, cap_seconds=60.0) == 60.0

    reg = ConnectorRegistry()
    reg.register("tg-main", "telegram", "https://api.telegram.org")
    reg.register_transport(
        "telegram",
        lambda spec, env: {"ok": True, "sent_to": env.recipient, "via": spec.name},
    )
    res = reg.dispatch("tg-main", "user-42", "Hallo BACH")
    assert res["ok"] is True
    assert res["sent_to"] == "user-42"
    assert len(reg.list_enabled()) == 1
