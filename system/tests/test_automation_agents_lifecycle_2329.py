from hub._services.automation_agents_lifecycle import AutomationLifecycleRegistry


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
