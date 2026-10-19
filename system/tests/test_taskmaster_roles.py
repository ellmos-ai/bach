import sqlite3

import pytest

from hub._services import blueprint_service
from hub._services.taskmaster_policy import DEFAULTS, read_policy, validate_policy
from hub._services.taskmaster_roles import (
    SCHEMA,
    backoff_seconds,
    deduplication_key,
    role_catalog,
    role_for_task,
    select_candidates,
)


def test_catalogue_has_five_hashed_stable_roles():
    first = role_catalog()
    second = role_catalog()
    assert first == second
    assert first["schema"] == SCHEMA
    assert [role["stable_id"] for role in first["roles"]] == [
        "taskmaster.coding", "taskmaster.writer", "taskmaster.solver",
        "taskmaster.maintainer", "taskmaster.operator",
    ]
    for role in first["roles"]:
        assert len(role["content_sha256"]) == 64
        assert role["revision"] == "1.0.0"
        assert role["origin"] == "bach-native-taskmaster"
        assert role["persona_prompt"]
        assert role["governance"]["tool_whitelist"]


def test_seeded_roles_keep_stable_identity_separate_from_sqlite_id():
    conn = sqlite3.connect(":memory:")
    blueprint_service.seed_default_blueprints(conn)
    rows = conn.execute(
        "SELECT id, name, stable_id, origin, revision, is_template FROM agent_blueprints "
        "WHERE stable_id IS NOT NULL ORDER BY stable_id"
    ).fetchall()
    assert len(rows) == 5
    assert all(row[0] > 0 and row[3] == "bach-native-taskmaster"
               and row[4] == "1.0.0" and row[5] == 1 for row in rows)
    assert {row[2] for row in rows} == {
        "taskmaster.coding", "taskmaster.writer", "taskmaster.solver",
        "taskmaster.maintainer", "taskmaster.operator",
    }
    conn.close()


def test_role_routing_and_candidate_order_are_deterministic():
    assert role_for_task({"category": "development"}) == "taskmaster.coding"
    assert role_for_task({"category": "documentation"}) == "taskmaster.writer"
    assert role_for_task({"category": "maintenance"}) == "taskmaster.maintainer"
    assert role_for_task({"category": "triage"}) == "taskmaster.operator"
    assert role_for_task({"category": "unknown"}) == "taskmaster.solver"

    tasks = [
        {"id": 4, "status": "pending", "priority": "P2", "category": "code", "created_at": "2026-01-02"},
        {"id": 3, "status": "pending", "priority": "P1", "category": "code", "created_at": "2026-01-03"},
        {"id": 2, "status": "in_progress", "priority": "P1", "category": "code", "created_at": "2026-01-01"},
        {"id": 1, "status": "pending", "priority": "P1", "category": "code", "assigned_slot": "local-model"},
    ]
    result = select_candidates(tasks, "taskmaster.coding")
    assert [item["task_id"] for item in result] == [3, 4]
    assert all(item["deduplication_scope"] == "task_id+task_version+role_id" for item in result)


def test_dedup_and_backoff_are_bounded_and_fail_closed():
    key = deduplication_key(7, "a" * 64, "taskmaster.solver")
    assert key == deduplication_key(7, "a" * 64, "taskmaster.solver")
    assert len(key) == 64
    assert backoff_seconds(0) == 30
    assert backoff_seconds(3) == 240
    assert backoff_seconds(99) == 3600
    with pytest.raises(ValueError):
        deduplication_key(0, "a" * 64, "taskmaster.solver")
    with pytest.raises(ValueError):
        deduplication_key(7, "", "taskmaster.solver")
    with pytest.raises(ValueError):
        backoff_seconds(-1)


def test_policy_defaults_keep_scheduler_and_cloud_start_disabled():
    assert validate_policy(DEFAULTS)["cloud_start_mode"] == "user_only"
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    # read_policy uses a path so exercise its read-only contract with a file.
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "bach.db"
        disk = sqlite3.connect(path)
        disk.execute("CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        disk.commit()
        disk.close()
        result = read_policy(path)
    assert result["policy_source"] == "system_default"
    assert result["scheduler_state"] == "disabled_by_default"
    assert result["task_source"] == "canonical_bach_taskdb"
    db.close()
