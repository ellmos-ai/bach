"""Canonical acceptance timestamps remain valid public maintenance evidence."""
from datetime import datetime, timedelta, timezone

import pytest

from hub._services.docs.maintenance_dispatch import DocumentationDispatcher
from hub._services.docs.maintenance_runtime import _safe_scalar
from hub._services.task_lease import _local_naive

NOW = datetime(2026, 10, 18, 17, 13, 45, 134605, tzinfo=timezone.utc)


def project(raw, *, accepted=True, status="done"):
    dispatcher = DocumentationDispatcher.__new__(DocumentationDispatcher)
    dispatcher.result_reader = lambda task_id: {
        "verified": True, "task_id": task_id, "status": status,
        "result": {"accepted": accepted, "result_id": 125, "accepted_at": raw},
    }
    return dispatcher._task_state({"task_id": 2234})


@pytest.mark.parametrize("raw", [
    _local_naive(NOW),
    NOW.astimezone(timezone(timedelta(hours=2))).isoformat(),
    NOW.isoformat().replace("+00:00", "Z"),
    NOW.replace(tzinfo=None).isoformat(sep=" "),
])
def test_canonical_review_times_are_aware_utc(raw):
    state = project(raw)
    assert state["result_accepted"] is True
    assert state["last_review_success"] == NOW.isoformat()
    assert _safe_scalar("last_review_success", state["last_review_success"]) == NOW.isoformat()
    assert state["last_repair_success"] is None


@pytest.mark.parametrize("raw", ["private invalid timestamp", {"private": 1}, "x" * 41])
def test_invalid_review_time_cannot_advance_evidence(raw):
    with pytest.raises(RuntimeError, match="task_review_timestamp_unverified"):
        project(raw)


def test_unaccepted_result_does_not_publish_review_time():
    state = project("invalid", accepted=False, status="review")
    assert state["result_accepted"] is False
    assert state["last_review_success"] is None
    assert state["last_repair_success"] is None
