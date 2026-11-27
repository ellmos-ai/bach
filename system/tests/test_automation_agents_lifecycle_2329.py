# SPDX-License-Identifier: MIT
from __future__ import annotations

import os
import warnings
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gui import server
from hub._services import ocean_stack_bridge
from hub._services.automation_agents_lifecycle import (
    AutomationLifecycleRegistry,
    get_automation_lifecycle_registry,
)
from hub._services.automation_master_adapter import list_module_automations


def test_three_families_deduplication_and_fence_transitions():
    reg = AutomationLifecycleRegistry()
    job = reg.register_entry({"id": "backup-job", "family": "job", "trigger": "routine"})
    mini = reg.register_entry({
        "id": "tagger-mini",
        "family": "mini_agent",
        "trigger": "event",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
    })
    auto = reg.register_entry({"id": "daily-planner", "family": "automation_agent", "trigger": "calendar_once"})
    assert job["state"] == "ready"
    assert mini["state"] == "ready"
    assert auto["state"] == "ready"

    started = reg.trigger_start("tagger-mini", start_trigger="event", dedup_key="evt-100")
    assert started["state"] == "running"
    assert started["deduplicated"] is False
    fence_running = started["fence"]

    dup = reg.trigger_start("tagger-mini", start_trigger="event", dedup_key="evt-100")
    assert dup["deduplicated"] is True
    assert dup["fence"] == fence_running

    stopped = reg.stop_entry("tagger-mini", expected_fence=fence_running)
    assert stopped["state"] == "ready"
    assert stopped["fence"] == fence_running + 1


def test_deprecated_marker_and_ocean_delegation_or_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    assert getattr(AutomationLifecycleRegistry, "__ocean_deprecated__", False) is True
    assert "agent-library" in getattr(AutomationLifecycleRegistry, "__ocean_replacement__", "")

    old_env = os.environ.get("BACH_WARN_DEPRECATED")
    os.environ["BACH_WARN_DEPRECATED"] = "1"
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DeprecationWarning)
            _ = AutomationLifecycleRegistry()
        assert len(caught) >= 1
    finally:
        if old_env is None:
            os.environ.pop("BACH_WARN_DEPRECATED", None)
        else:
            os.environ["BACH_WARN_DEPRECATED"] = old_env

    # Force fallback path when Ocean sibling cannot be resolved
    def _raise_unavailable(*_args, **_kwargs):
        raise FileNotFoundError("test-offline")

    monkeypatch.setattr(ocean_stack_bridge, "get_ocean_automation_lifecycle_registry", _raise_unavailable)
    db_file = tmp_path / "fallback.db"
    fallback_reg, provider = get_automation_lifecycle_registry(db_path=db_file)
    assert provider == "bach.legacy_fallback"
    created = fallback_reg.register_entry({"id": "offline-job", "family": "job", "trigger": "routine"})
    assert created["state"] == "ready"
    assert AutomationLifecycleRegistry(db_path=db_file).get_entry("offline-job")["id"] == "offline-job"

    # Verify Ocean delegation path when sibling provides new persistent registry
    monkeypatch.setattr(
        ocean_stack_bridge,
        "get_ocean_automation_lifecycle_registry",
        lambda db_path=None: AutomationLifecycleRegistry(db_path=db_path),
    )
    ocean_reg, ocean_provider = get_automation_lifecycle_registry(db_path=tmp_path / "ocean_delegated.db")
    assert ocean_provider == "ocean.agent_library"
    assert ocean_reg.register_entry({"id": "ocean-job", "family": "job", "trigger": "routine"})["id"] == "ocean-job"


def test_persistent_lifecycle_calendar_dst_and_adapter_visibility(tmp_path: Path):
    db_file = tmp_path / "bach.db"
    reg = AutomationLifecycleRegistry(db_path=db_file)
    reg.register_entry({
        "id": "mod-cal-job",
        "title": "Kalender-Job",
        "family": "job",
        "trigger": "calendar_once",
        "from_module": True,
        "scheduled": False,
        "timezone": "Europe/Berlin",
    })
    assert reg.get_entry("mod-cal-job")["state"] == "available"

    binding = reg.bind_calendar_event(
        "mod-cal-job",
        calendar_event_id="evt-cal-1",
        scheduled_at="2026-07-10T08:00:00+02:00",
        sync_direction="bidirectional",
    )
    assert binding["tz_offset"] == "+0200"
    assert reg.get_entry("mod-cal-job")["state"] == "ready"

    started = reg.trigger_start(
        "mod-cal-job",
        start_trigger="manual",
        dedup_key="man-77",
        tz_now=datetime(2026, 7, 10, 8, 5, tzinfo=timezone.utc),
    )
    reg.stop_entry("mod-cal-job", expected_fence=started["fence"])

    grouped = AutomationLifecycleRegistry(db_path=db_file).list_runs(group_by_trigger=True)
    assert [r["entry_id"] for r in grouped["manual"]] == ["mod-cal-job"]

    # External cancel marks binding cancelled without deleting the job
    cancelled = reg.cancel_calendar_event("mod-cal-job", calendar_event_id="evt-cal-1", source="calendar")
    assert cancelled["status"] == "cancelled"

    items = list_module_automations(
        db_file,
        include_sync=False,
        include_manifests=False,
        include_package=False,
    )
    lifecycle_items = [it for it in items if it["source"] == "automation-lifecycle"]
    assert len(lifecycle_items) == 1
    assert lifecycle_items[0]["id"] == "automation-lifecycle:mod-cal-job"
    assert lifecycle_items[0]["last_result"] == "manual"
    assert lifecycle_items[0]["enabled"] is True


def test_fastapi_lifecycle_routes_require_device_token_and_drive_full_flow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    db_file = tmp_path / "bach.db"
    monkeypatch.setattr(server, "BACH_DB", db_file)
    monkeypatch.setattr(server, "validate_token", lambda token: {"name": "test-device"} if token == "good-device" else None)
    monkeypatch.setattr(
        ocean_stack_bridge,
        "get_ocean_automation_lifecycle_registry",
        lambda db_path=None: AutomationLifecycleRegistry(db_path=db_path),
    )

    assert "/api/automations/lifecycle" not in server.DeviceAuthMiddleware.EXEMPT_API_PATHS
    headers = {"Authorization": "Bearer good-device"}

    with TestClient(server.app, base_url="http://testserver") as client:
        unauth = client.get("/api/automations/lifecycle")
        assert unauth.status_code == 401

        create_res = client.post(
            "/api/automations/lifecycle",
            headers=headers,
            json={
                "id": "api-routine-agent",
                "title": "API Routine Agent",
                "family": "automation_agent",
                "trigger": "routine",
                "from_module": True,
                "scheduled": False,
                "timezone": "Europe/Berlin",
            },
        )
        assert create_res.status_code == 200
        created = create_res.json()["entry"]
        assert created["state"] == "available"

        sched_res = client.post(
            "/api/automations/lifecycle/api-routine-agent/schedule",
            headers=headers,
            json={"schedule_spec": "0 9 * * *", "expected_fence": created["fence"]},
        )
        assert sched_res.status_code == 200
        scheduled = sched_res.json()["entry"]
        assert scheduled["state"] == "ready"

        start_res = client.post(
            "/api/automations/lifecycle/api-routine-agent/start",
            headers=headers,
            json={"start_trigger": "manual", "dedup_key": "api-man-1"},
        )
        assert start_res.status_code == 200
        running = start_res.json()["entry"]
        assert running["state"] == "running"

        runs_res = client.get("/api/automations/lifecycle/runs?group_by_trigger=true", headers=headers)
        assert runs_res.status_code == 200
        assert [r["entry_id"] for r in runs_res.json()["runs"]["manual"]] == ["api-routine-agent"]

        stale_stop = client.post(
            "/api/automations/lifecycle/api-routine-agent/stop",
            headers=headers,
            json={"expected_fence": running["fence"] - 1},
        )
        assert stale_stop.status_code == 409

        stop_res = client.post(
            "/api/automations/lifecycle/api-routine-agent/stop",
            headers=headers,
            json={"expected_fence": running["fence"]},
        )
        assert stop_res.status_code == 200
        assert stop_res.json()["entry"]["state"] == "ready"

        cal_res = client.post(
            "/api/automations/lifecycle/api-routine-agent/calendar",
            headers=headers,
            json={
                "calendar_event_id": "cal-api-1",
                "scheduled_at": "2026-12-01T10:00:00+01:00",
                "sync_direction": "bidirectional",
            },
        )
        assert cal_res.status_code == 200
        assert cal_res.json()["binding"]["tz_offset"] == "+0100"

        cancel_res = client.post(
            "/api/automations/lifecycle/api-routine-agent/calendar/cancel",
            headers=headers,
            json={"calendar_event_id": "cal-api-1", "source": "calendar"},
        )
        assert cancel_res.status_code == 200
        assert cancel_res.json()["binding"]["status"] == "cancelled"

        # Verify GET /api/automations surfaces the persisted lifecycle entry
        auto_res = client.get("/api/automations?source=automation-lifecycle")
        assert auto_res.status_code == 200
        assert auto_res.json()["count"] == 1
        assert auto_res.json()["items"][0]["id"] == "automation-lifecycle:api-routine-agent"

        del_res = client.delete(
            f"/api/automations/lifecycle/api-routine-agent?expected_fence={stop_res.json()['entry']['fence']}",
            headers=headers,
        )
        assert del_res.status_code == 200
        assert del_res.json()["deleted"] is True
