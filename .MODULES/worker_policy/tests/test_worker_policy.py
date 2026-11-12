# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Smoke test for worker_policy module."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import worker_policy


def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    assert manifest_p.exists()
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "worker_policy"
    assert data["selfcontained"] is True


def test_worker_policy_read_and_contract():
    res = worker_policy.read_global_policy()
    assert "schema" in res
    assert res["contract"] == worker_policy.CONTRACT
    assert "policy" in res

    task_res = worker_policy.read_task_policy(42)
    assert task_res["task_id"] == 42
    assert "override" in task_res
