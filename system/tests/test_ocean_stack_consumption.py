# SPDX-License-Identifier: MIT
"""Integration tests verifying BACH's consumption of the new Ocean modules and deprecation of legacy paths."""
from __future__ import annotations

import json
import os
import sqlite3
import warnings
from pathlib import Path

from core.agent_runtime import (
    check_agent_escalation,
    check_agent_worktree_policy,
    validate_agent_persona_manifest,
)
from hub._services.ocean_resources_adapter import (
    OceanRamDistributor,
    RAMDistributor,
    WatchdogHysteresisPolicy,
    evaluate_ocean_ram_admission,
)
from hub._services.ocean_stack_bridge import (
    ocean_governance_audit,
    ocean_software_inventory,
    ocean_stack_status,
    ocean_task_assignees,
    ocean_task_result,
    project_agent_library,
    validate_skill_learning_candidate,
)
from hub._services.task_result_service import evaluate_configurable_result_review
from hub._services.taskplan_bridge import (
    BundledTaskPlanClient,
    execute_taskplan_lease,
)


def test_ocean_stack_status_all_modules_bound():
    status = ocean_stack_status()
    assert status["schema"] == "bach.ocean-stack-bindings.v1"
    assert status["stack_role"] == "branded-partial-os-stack-of-ocean"
    assert status["legacy_mode"] == "deprecated-fallback-only"
    for mod_name, info in status["modules"].items():
        assert info["bound"] is True, f"Module {mod_name} not bound: {info}"


def test_legacy_classes_marked_deprecated(tmp_path: Path):
    assert getattr(OceanRamDistributor, "__ocean_deprecated__", False) is True
    assert "ocean_resources.ram_distributor.RAMDistributor" in getattr(
        OceanRamDistributor, "__ocean_replacement__", ""
    )
    assert getattr(BundledTaskPlanClient, "__ocean_deprecated__", False) is True
    assert "taskplan.lease.TaskLeaseManager" in getattr(
        BundledTaskPlanClient, "__ocean_replacement__", ""
    )

    old_env = os.environ.get("BACH_WARN_DEPRECATED")
    os.environ["BACH_WARN_DEPRECATED"] = "1"
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DeprecationWarning)
            _ = OceanRamDistributor(total_ram_gb=32.0, protected_reserve_gb=8.0)
            _ = BundledTaskPlanClient(db_path=tmp_path / "legacy.db")
        assert len(caught) >= 2
    finally:
        if old_env is None:
            os.environ.pop("BACH_WARN_DEPRECATED", None)
        else:
            os.environ["BACH_WARN_DEPRECATED"] = old_env


def test_bach_consumes_ocean_ram_distributor_and_watchdog():
    assert RAMDistributor is not None
    assert WatchdogHysteresisPolicy is not None
    res = evaluate_ocean_ram_admission(
        available_ram_bytes=28 * 1024**3,
        pressure="normal",
        consumer_id="qwen3.8:27b-mlx",
        weights_ram_bytes=16 * 1024**3,
    )
    assert res["schema"] == "bach.ocean-ram-admission.v1"
    assert res["admission"]["admitted"] is True
    assert res["watchdog"]["evict"] is False


def test_bach_consumes_taskplan_lease_kernel(tmp_path: Path):
    db_path = tmp_path / "taskplan_leases.db"
    taken = execute_taskplan_lease(
        "take",
        db_path=db_path,
        holder_id="buddha-worker",
        create_new=True,
        title="Cutover task lease test",
        task_kind="discovered",
    )
    assert taken["status"] == "active"
    assert taken["holder"] == "buddha-worker"
    assert taken["task_kind"] == "discovered"

    renewed = execute_taskplan_lease(
        "renew",
        db_path=db_path,
        task_id=taken["task_id"],
        lease_id=taken["lease_id"],
        fence=taken["fence"],
    )
    assert renewed["fence"] == taken["fence"] + 1

    submitted = execute_taskplan_lease(
        "submit",
        db_path=db_path,
        task_id=taken["task_id"],
        lease_id=taken["lease_id"],
        fence=renewed["fence"],
        result_summary="Completed via BACH->taskplan seam",
    )
    assert submitted["status"] == "submitted"


def test_bach_consumes_configurable_review_worktree_and_escalation(tmp_path: Path):
    rev = evaluate_configurable_result_review(
        policy_mode="any_fresh_run",
        producer_model="qwen3.8:27b-mlx",
        producer_provider="ollama",
        producer_generation="run-1",
        reviewer_model="qwen3.8:27b-mlx",
        reviewer_provider="ollama",
        reviewer_generation="run-2",
        has_code_scope=False,
        result_text_present=True,
    )
    assert rev["allowed"] is True
    assert rev["scope_mode"] == "scope_not_recorded"

    wt = check_agent_worktree_policy(
        worker_id="buddha",
        repo_name="open-ocean",
        branch="worker/buddha/2577",
        write_scope="ocean",
    )
    assert wt["allowed"] is True

    esc = check_agent_escalation("worker", "store_submission", has_user_gate=False)
    assert esc["allowed"] is False
    assert esc["escalate_to"] == "user_gate"

    pr = validate_agent_persona_manifest({
        "roles": [{"id": "boss-1", "kind": "boss", "capabilities": ["dispatch"]}],
        "maintenance": [{"id": "m-1", "interval_ref": "routine:daily", "entrypoint": "tools/m.py"}],
    })
    assert pr["valid"] is True

    lc = validate_skill_learning_candidate({
        "candidate_id": "c-1",
        "target_skill_id": "dev/test",
        "origin_session_id": "s-1",
        "evidence_refs": ["commit:123"],
        "proposed_diff_sha256": "a" * 64,
        "review_state": "accepted",
        "reviewer_principal": "rev-1",
    })
    assert lc["promotable"] is True

    lib = project_agent_library(
        templates=[{"id": "t1"}],
        prompt_agents=[{"id": "p1"}],
        chains=[{"id": "c1", "kind": "marblerun"}],
    )
    assert lib["tabs"] == ["templates", "prompt_agents", "chains"]

    releases_path = tmp_path / "releases.json"
    releases_path.write_text(
        json.dumps({"projects": [{"name": "DemoApp", "path": "apps/demo", "version": "1.0.0", "targets": []}]}),
        encoding="utf-8",
    )
    inv = ocean_software_inventory(releases_path)
    assert inv["schema"] == "bach.capability-inventory.v1"
    assert inv["kind"] == "software"

    dummy_db = tmp_path / "empty_bach.db"
    with sqlite3.connect(dummy_db) as conn:
        conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT, status TEXT, completed_at TEXT, updated_at TEXT)")
        conn.execute("CREATE TABLE task_history (task_id INTEGER, action TEXT, field_changed TEXT, changed_at TEXT)")
        conn.commit()

    aud = ocean_governance_audit(bach_db_path=dummy_db)
    assert aud["availability"] == "available"

    slots_cfg = tmp_path / "slots.json"
    slots_cfg.write_text(json.dumps({"agents": [{"id": "buddha", "enabled": True}]}), encoding="utf-8")
    ass = ocean_task_assignees(slots_cfg)
    assert ass["schema"] == "bach.task-assignees.v1"

    tres = ocean_task_result(999999, bach_db_path=dummy_db)
    assert tres["available"] is True
    assert tres["found"] is False
