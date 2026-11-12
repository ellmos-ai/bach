# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for custom source support and source lookup in taskplan_bridge (#2444, #3664, #3665)."""

from __future__ import annotations

from pathlib import Path

from hub._services.taskplan_bridge import (
    BundledTaskPlanClient,
    find_taskplan_mirror_by_source,
    mirror_bach_task,
)


def test_mirror_bach_task_default_source_and_lookup(tmp_path: Path) -> None:
    db_path = tmp_path / "taskplan_default.db"
    result = mirror_bach_task(
        {
            "id": 2444,
            "title": "Mirror default source task",
            "description": "Default source check",
            "priority": "P2",
            "status": "pending",
            "category": "bridge",
        },
        db_path=db_path,
    )
    assert result["action"] == "created"
    assert result["task"]["source"] == "bach.db:tasks"

    client = BundledTaskPlanClient(db_path=db_path)
    found = find_taskplan_mirror_by_source(client, "bach.db:tasks")
    assert found is not None
    assert found["id"] == result["task"]["id"]
    assert found["source"] == "bach.db:tasks"


def test_mirror_bach_task_custom_source_and_lookup(tmp_path: Path) -> None:
    db_path = tmp_path / "taskplan_custom.db"
    custom_source = "ticket-master:T-20261030-2444"
    result = mirror_bach_task(
        {
            "id": 3664,
            "title": "Mirror custom source task",
            "description": "Custom source check",
            "priority": "P1",
            "status": "in_progress",
            "category": "ticket",
        },
        db_path=db_path,
        source=custom_source,
    )
    assert result["action"] == "created"
    assert result["task"]["source"] == custom_source
    assert result["task"]["status"] == "active"

    client = BundledTaskPlanClient(db_path=db_path)
    found = find_taskplan_mirror_by_source(client, custom_source)
    assert found is not None
    assert found["id"] == result["task"]["id"]
    assert found["title"] == "Mirror custom source task"
    assert found["source"] == custom_source
    assert find_taskplan_mirror_by_source(client, "nonexistent:source") is None
    assert find_taskplan_mirror_by_source(client, "") is None
