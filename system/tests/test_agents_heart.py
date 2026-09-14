# -*- coding: utf-8 -*-
"""Regressionstests für den engen agents-heart-Besetzungs-Seam."""

import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.agents_heart import (  # noqa: E402
    AssignmentDenied,
    begin_assignment,
    finish_assignment,
)
from hub._services.chat.slots_config import (  # noqa: E402
    get_activity_history,
    initialize_slots_config,
)


def test_assignment_start_and_end_are_correlated_and_flattened(tmp_path):
    cfg_file = tmp_path / "slots.json"
    initialize_slots_config(str(cfg_file))

    assignment = begin_assignment(
        role_id="hintergrund_worker",
        mode="full",
        agent_instance_id="worker-test-instance",
        backend_id="ollama",
        model_id="qwen3.8:27b-mlx",
        slot_id="buddha_always_on",
        task_id=42,
        session_id="worker-all-42",
        initiated_by="worker:all",
        path=str(cfg_file),
    )
    finish_assignment(
        assignment,
        status="completed",
        result="task_done",
        path=str(cfg_file),
    )

    history = get_activity_history(limit=10, path=str(cfg_file))
    assert len(history) == 2
    start, end = history[1], history[0]

    assert start["event"] == "assignment_started"
    assert end["event"] == "assignment_ended"
    assert start["assignment_id"] == end["assignment_id"] == assignment.assignment_id
    for entry in (start, end):
        assert entry["role_id"] == "hintergrund_worker"
        assert entry["agent_instance_id"] == "worker-test-instance"
        assert entry["backend_id"] == "ollama"
        assert entry["model_id"] == "qwen3.8:27b-mlx"
        assert entry["slot_id"] == "buddha_always_on"
        assert entry["task_id"] == 42
        assert entry["initiated_by"] == "worker:all"
        assert entry["started_at"] == assignment.started_at
    assert end["ended_at"]
    assert end["result"] == "task_done"


def test_unknown_role_is_denied_before_assignment_is_created(tmp_path):
    with pytest.raises(AssignmentDenied):
        begin_assignment(
            role_id="not-registered",
            mode="full",
            agent_instance_id="worker-test-instance",
            backend_id="ollama",
            model_id="qwen3.8:27b-mlx",
            slot_id="buddha_always_on",
            task_id=43,
            session_id="worker-all-43",
            initiated_by="worker:all",
            path=str(tmp_path / "slots.json"),
        )
