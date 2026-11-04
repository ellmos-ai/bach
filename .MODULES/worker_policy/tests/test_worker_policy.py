# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Smoke test for worker_policy module."""
import json
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import worker_policy


def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    assert manifest_p.exists()
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "worker_policy"
    assert data["selfcontained"] is False


def test_worker_policy_requires_native_service(monkeypatch):
    monkeypatch.setattr(worker_policy, "_service", None)
    with pytest.raises(worker_policy.PolicyUnavailable):
        worker_policy.read_global_policy()
    with pytest.raises(worker_policy.PolicyUnavailable):
        worker_policy.read_task_policy(42)
