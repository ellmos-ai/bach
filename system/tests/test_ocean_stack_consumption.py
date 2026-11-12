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

    status = ocean_stack_status()
    assert status["capability_extensions_bound_count"] >= 5  # + universal-gui / llm-note when their checkouts exist
    for ext_name in (
        "ellmos-voice-io",
        "ellmos-talk",
        "ellmos-sensation",
        "ellmos-homecontrol",
        "ellmos-robotics",
    ):
        assert status["capability_extensions"][ext_name]["bound"] is True

    from hub._services.ocean_stack_bridge import check_capability_permission
    from hub._services.voice.voice_stt import VoiceSTT, VoiceTTS
    from hub.smarthome import SmartHomeHandler

    assert check_capability_permission("camera")["allowed"] is False
    assert check_capability_permission("camera", {"camera": True})["allowed"] is True
    assert getattr(VoiceSTT, "__ocean_deprecated__", False) is True
    assert getattr(VoiceTTS, "__ocean_deprecated__", False) is True
    assert getattr(SmartHomeHandler, "__ocean_deprecated__", False) is True


def test_bach_multimodal_and_embodied_gui_endpoints(tmp_path, monkeypatch):
    import asyncio
    import json
    from gui import server

    # Homecontrol/robotics routes are gated by the capability matrix (PB-13, #3996);
    # isolate the grant and the persisted E-Stop from the real ~/.bach.
    grants = tmp_path / "capability_permissions.json"
    grants.write_text(json.dumps({"smarthome_robotics": True}), encoding="utf-8")
    monkeypatch.setattr(server, "_CAPABILITY_PERMISSIONS_FILE", grants)
    monkeypatch.setattr(server, "_ROBOTICS_ESTOP_FILE", tmp_path / "robotics_estop.json")

    perms = asyncio.run(server.api_get_capability_permissions())
    assert perms["schema"] == "ellmos.capability-permissions.v1"
    assert perms["permissions"]["camera"] is False

    v_status = asyncio.run(server.api_voice_status())
    assert v_status["schema"] == "ellmos.voice-io.status.v1"

    t_status = asyncio.run(server.api_talk_status())
    assert t_status["persona"] == "buddha"

    t_turn = asyncio.run(server.api_talk_turn({"user_utterance": "Hallo Buddha", "persona": "buddha", "language": "de"}))
    assert "emotion" in t_turn["visual_state"]
    assert len(t_turn["sentences"]) >= 1

    s_status = asyncio.run(server.api_sensation_status())
    assert s_status["schema"] == "ellmos.sensation.status.v1"
    assert s_status["open_compute_gate"]["should_pause_open_compute"] is False

    hc_devs = asyncio.run(server.api_homecontrol_devices())
    assert hc_devs["total_devices"] >= 4
    hc_energy = asyncio.run(server.api_homecontrol_energy())
    assert hc_energy["total_power_watts"] > 0

    rob_caps = asyncio.run(server.api_robotics_capabilities())
    assert rob_caps["schema"] == "ellmos.robotics.mcp.v1"
    rob_tel = asyncio.run(server.api_robotics_telemetry())
    assert rob_tel["battery_pct"] > 0
    rob_stop = asyncio.run(server.api_robotics_estop({"reason": "unit_test"}))
    assert rob_stop["status"] == "emergency_stopped"

    talk_html = asyncio.run(server.talk_visualizer_companion_page())
    assert b"ELLMOS Talk" in talk_html.body


def test_bach_consumes_agents_heart_assignment():
    from hub._services.ocean_stack_bridge import (
        evaluate_agents_heart_assignment,
        load_agents_heart_module,
    )
    mod = load_agents_heart_module()
    assert mod is not None
    assert "task_worker" in mod.ROLE_CONTRACTS

    res = evaluate_agents_heart_assignment(
        role_id="task_worker",
        backend_id="ollama",
        model_id="qwen3.8:27b-mlx",
        slot_id="slot-worker-1",
        task_id=1234,
        session_id="test-session",
        initiated_by="test",
    )
    assert res["allowed"] is True
    assert res["role_id"] == "task_worker"
    assert "assignment_id" in res


def test_modularized_services_and_hot_wiring():
    from hub._services.ocean_stack_bridge import (
        invalidate_module_cache,
        load_agent_spawn_gate_module,
        load_context_hints_module,
        load_session_checkpoint_adapter_module,
        load_domain_writer_gate_module,
        load_scheduler_provider_module,
        load_db_sync_adapter_module,
        load_agent_process_provider_module,
        load_session_checkpoint_provider_module,
        load_db_sync_readiness_module,
        load_token_budget_module,
        load_rate_limit_policy_module,
        load_audit_logger_module,
        load_telemetry_module,
        load_limits_module,
        load_worker_policy_module,
        load_session_module,
        load_cache_module,
        load_scheduler_module,
        load_plugins_module,
        load_hooks_module,
        load_memory_module,
        detect_legacy_in_tree_services,
        auto_switch_to_standalone_modules,
        get_service_or_standalone,
        ocean_modularized_services_status,
        ocean_stack_status,
    )

    # Invalidate cache to test clean load
    invalidate_module_cache()

    mod_gate = load_agent_spawn_gate_module()
    assert mod_gate is not None
    assert hasattr(mod_gate, "main")

    mod_hints = load_context_hints_module()
    assert mod_hints is not None
    assert hasattr(mod_hints, "neutral_manual_hint")

    mod_cp = load_session_checkpoint_adapter_module()
    assert mod_cp is not None
    assert hasattr(mod_cp, "NAMESPACE")

    mod_dw = load_domain_writer_gate_module()
    assert mod_dw is not None
    assert hasattr(mod_dw, "blocked_reason")

    mod_sp = load_scheduler_provider_module()
    assert mod_sp is not None
    assert hasattr(mod_sp, "probe_scheduler_provider")

    mod_db = load_db_sync_adapter_module()
    assert mod_db is not None
    assert hasattr(mod_db, "SharedDBSyncAdapter")

    mod_app = load_agent_process_provider_module()
    assert mod_app is not None
    assert hasattr(mod_app, "create_agent_registry")

    mod_scp = load_session_checkpoint_provider_module()
    assert mod_scp is not None
    assert hasattr(mod_scp, "get_checkpoint_store")

    mod_dsr = load_db_sync_readiness_module()
    assert mod_dsr is not None
    assert hasattr(mod_dsr, "validate_native_db")

    mod_tb = load_token_budget_module()
    assert mod_tb is not None
    assert hasattr(mod_tb, "evaluate_token_budget")

    mod_rlp = load_rate_limit_policy_module()
    assert mod_rlp is not None
    assert hasattr(mod_rlp, "evaluate_rate_limit")

    mod_al = load_audit_logger_module()
    assert mod_al is not None
    assert hasattr(mod_al, "log_audit_event")

    mod_telem = load_telemetry_module()
    assert mod_telem is not None
    assert hasattr(mod_telem, "increment")

    mod_lim = load_limits_module()
    assert mod_lim is not None
    assert hasattr(mod_lim, "limit")

    mod_wp = load_worker_policy_module()
    assert mod_wp is not None
    assert hasattr(mod_wp, "read_global_policy")

    mod_sess = load_session_module()
    assert mod_sess is not None
    assert hasattr(mod_sess, "SessionManager")

    mod_cache = load_cache_module()
    assert mod_cache is not None
    assert hasattr(mod_cache, "CacheManager")

    mod_sched = load_scheduler_module()
    assert mod_sched is not None
    assert hasattr(mod_sched, "JobScheduler")

    mod_plug = load_plugins_module()
    assert mod_plug is not None
    assert hasattr(mod_plug, "PluginRegistry")

    mod_hook = load_hooks_module()
    assert mod_hook is not None
    assert hasattr(mod_hook, "HookRegistry")

    mod_mem = load_memory_module()
    assert mod_mem is not None
    assert hasattr(mod_mem, "MemoryStore")

    # Dynamic service resolver test
    dyn_dw = get_service_or_standalone("domain_writer_gate")
    assert dyn_dw is not None
    assert hasattr(dyn_dw, "blocked_reason")

    # Legacy in-tree detection
    detection = detect_legacy_in_tree_services()
    assert detection["schema"] == "bach.legacy-in-tree-detection.v1"
    assert detection["total_in_tree_services"] >= 140
    assert detection["standalone_modules_available"] >= 18
    assert detection["switched_or_switchable_count"] >= 18

    # Auto-switch execution
    switch_report = auto_switch_to_standalone_modules()
    assert switch_report["schema"] == "bach.auto-switch-standalone-report.v1"
    assert switch_report["total_switched"] >= 23

    status = ocean_modularized_services_status()
    for s_name in (
        "agent_spawn_gate",
        "context_hints",
        "session_checkpoint_adapter",
        "domain_writer_gate",
        "scheduler_provider",
        "db_sync_adapter",
        "agent_process_provider",
        "session_checkpoint_provider",
        "db_sync_readiness",
        "token_budget",
        "rate_limit_policy",
        "audit_logger",
        "telemetry",
        "limits",
        "worker_policy",
        "prompt",
        "message_delivery",
        "conversation_store",
        "inbox",
        "email_bridge",
        "notify",
        "session",
        "cache",
        "scheduler",
        "plugins",
        "hooks",
        "memory",
        "skills",
        "tools",
        "agents",
    ):
        assert s_name in status
        assert status[s_name]["bound"] is True, f"Service {s_name} not bound: {status[s_name]}"

    full_status = ocean_stack_status()
    assert "modularized_services" in full_status
    assert full_status["modularized_standalone_count"] >= 14
    for s_name in (
        "agent_spawn_gate",
        "context_hints",
        "session_checkpoint_adapter",
        "domain_writer_gate",
        "scheduler_provider",
        "db_sync_adapter",
        "agent_process_provider",
        "session_checkpoint_provider",
        "db_sync_readiness",
        "token_budget",
        "rate_limit_policy",
        "audit_logger",
        "telemetry",
        "limits",
        "worker_policy",
        "prompt",
        "message_delivery",
        "conversation_store",
        "inbox",
        "email_bridge",
        "notify",
        "session",
        "cache",
        "scheduler",
        "plugins",
        "hooks",
        "memory",
        "skills",
        "tools",
        "agents",
    ):
        assert full_status["modularized_services"][s_name]["bound"] is True


def test_llm_note_is_bound_without_shadowing_gui_package():
    """PB-11 (#3994): llm-note joins `ext_modules`; its flat package must not shadow `gui`."""
    import sys

    from hub._services.ocean_stack_bridge import load_llm_note_module, ocean_capability_extensions_status

    entry = ocean_capability_extensions_status()["llm-note"]
    assert entry["module"] == "llm_note.store"
    if not entry["bound"]:
        import pytest

        pytest.skip("llm-note checkout not present")
    assert load_llm_note_module().NoteStore is not None
    assert "gui" not in sys.modules or getattr(sys.modules["gui"], "__file__", "").replace("\\", "/").find("llm_note") < 0
