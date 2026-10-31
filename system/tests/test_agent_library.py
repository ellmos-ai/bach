"""Contract tests for the neutral agent-library delete/archive workflow."""
import json
from pathlib import Path

import pytest

from hub._services import agent_library as bach_agent_library


def test_module_uses_the_versioned_tasktree_manifest():
    module_path = Path(bach_agent_library._agent_library.__file__).resolve()
    manifest_path = module_path.with_name("ellmos-module.v2.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert module_path.parts[-3:] == (".CONTROL", "agent-library", "agent_library.py")
    assert manifest["schema"] == "ellmos.module.v2"
    assert manifest["id"] == "agent-library"
    assert manifest["status"] == "staging"
    assert manifest["entrypoints"]["library"] == "agent_library"


def test_guard_terminal_receipts_archive_and_removal_are_ordered():
    profile = {"id": "worker-fixture"}
    records = ({"phase": "terminal", "sequence": 1},)
    events = []

    def guard(received):
        assert received is profile
        events.append("guard")

    def terminal_records(received):
        assert received is profile
        events.append("read_records")
        return records

    def archive(profile_id, received_records):
        assert profile_id == "worker-fixture"
        assert received_records == records
        events.append("archive")

    def remove():
        events.append("remove")
        return True

    result = bach_agent_library.archive_then_remove_profile(
        "worker-fixture",
        profile,
        assert_inactive=guard,
        terminal_records=terminal_records,
        archive=archive,
        remove=remove,
    )

    assert result is True
    assert events == ["guard", "read_records", "archive", "remove"]


def test_missing_controller_guard_fails_closed_before_side_effects():
    events = []
    with pytest.raises(RuntimeError, match="worker_delete_execution_unconfirmed"):
        bach_agent_library.archive_then_remove_profile(
            "worker-fixture",
            {"id": "worker-fixture"},
            assert_inactive=None,
            terminal_records=lambda _profile: events.append("records") or (),
            archive=lambda *_args: events.append("archive"),
            remove=lambda: events.append("remove") or True,
        )
    assert events == []


def test_unsettled_receipt_blocks_archival_and_removal():
    events = []
    with pytest.raises(RuntimeError, match="worker_delete_budget_unconfirmed"):
        bach_agent_library.archive_then_remove_profile(
            "worker-fixture",
            {"id": "worker-fixture"},
            assert_inactive=lambda _profile: events.append("guard"),
            terminal_records=lambda _profile: (
                events.append("records") or ({"phase": "running"},)
            ),
            archive=lambda *_args: events.append("archive"),
            remove=lambda: events.append("remove") or True,
        )
    assert events == ["guard", "records"]


def test_archive_failure_prevents_profile_removal():
    events = []

    def fail_archive(*_args):
        events.append("archive")
        raise OSError("archive unavailable")

    with pytest.raises(OSError, match="archive unavailable"):
        bach_agent_library.archive_then_remove_profile(
            "worker-fixture",
            {"id": "worker-fixture"},
            assert_inactive=lambda _profile: events.append("guard"),
            terminal_records=lambda _profile: (),
            archive=fail_archive,
            remove=lambda: events.append("remove") or True,
        )
    assert events == ["guard", "archive"]


def test_profile_identity_mismatch_fails_before_guard_or_storage():
    events = []
    with pytest.raises(RuntimeError, match="worker_delete_execution_unconfirmed"):
        bach_agent_library.archive_then_remove_profile(
            "worker-requested",
            {"id": "worker-other"},
            assert_inactive=lambda _profile: events.append("guard"),
            terminal_records=lambda _profile: (),
            archive=lambda *_args: events.append("archive"),
            remove=lambda: events.append("remove") or True,
        )
    assert events == []
