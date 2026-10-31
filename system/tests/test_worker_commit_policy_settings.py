# SPDX-License-Identifier: MIT
"""Task 2216: commit policy settings are configured separately from review and task completion."""
import sqlite3

import pytest

from hub._services.worker_policy_settings import (
    COMMIT_DEFAULTS,
    COMMIT_KEYS,
    PolicyConflict,
    read_commit_policy,
    validate_commit_policy,
    write_commit_policy,
)


@pytest.fixture()
def db_path(tmp_path):
    """Isolated sqlite database with the hub schema; no shared state is touched."""
    path = tmp_path / "bach.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.commit()
    connection.close()
    return path


def test_defaults_without_stored_row(db_path):
    policy = read_commit_policy(db_path=db_path)
    assert policy["availability"] == "available"
    assert policy["policy_source"] == "system_default"
    for name in COMMIT_KEYS:
        assert policy[name] is COMMIT_DEFAULTS[name]
    first = policy["configuration_version"]
    assert isinstance(first, str) and first
    # The configuration version is derived deterministically from the stored state.
    assert read_commit_policy(db_path=db_path)["configuration_version"] == first


def test_override_is_read_back(db_path):
    before = read_commit_policy(db_path=db_path)
    result = write_commit_policy(
        {"configuration_version": before["configuration_version"], "allow_local_commit": False},
        actor="tester",
        db_path=db_path,
    )
    assert result["updated"] is True
    assert result["worker_started"] is False

    policy = read_commit_policy(db_path=db_path)
    assert policy["policy_source"] == "user_override"
    assert policy["allow_local_commit"] is False
    assert policy["allow_push"] is COMMIT_DEFAULTS["allow_push"]
    assert policy["configuration_version"] == result["configuration_version"]
    assert policy["configuration_version"] != before["configuration_version"]


def test_stale_configuration_version_conflicts(db_path):
    read_commit_policy(db_path=db_path)
    with pytest.raises(PolicyConflict):
        write_commit_policy(
            {"configuration_version": "stale", "allow_push": False},
            actor="tester",
            db_path=db_path,
        )
    # A rejected write leaves the stored policy untouched.
    assert read_commit_policy(db_path=db_path)["policy_source"] == "system_default"


def test_reset_to_default(db_path):
    current = read_commit_policy(db_path=db_path)
    write_commit_policy(
        {"configuration_version": current["configuration_version"], "allow_push": False},
        actor="tester",
        db_path=db_path,
    )
    override = read_commit_policy(db_path=db_path)
    assert override["allow_push"] is False

    write_commit_policy(
        {"configuration_version": override["configuration_version"], "reset_to_default": True},
        actor="tester",
        db_path=db_path,
    )
    policy = read_commit_policy(db_path=db_path)
    assert policy["policy_source"] == "system_default"
    for name in COMMIT_KEYS:
        assert policy[name] is COMMIT_DEFAULTS[name]


def test_unknown_field_is_rejected(db_path):
    current = read_commit_policy(db_path=db_path)
    with pytest.raises(ValueError) as excinfo:
        write_commit_policy(
            {"configuration_version": current["configuration_version"], "bogus": True},
            actor="tester",
            db_path=db_path,
        )
    assert type(excinfo.value) is ValueError
    assert read_commit_policy(db_path=db_path)["policy_source"] == "system_default"

    with pytest.raises(ValueError) as excinfo:
        write_commit_policy({"allow_push": False}, actor="tester", db_path=db_path)
    assert type(excinfo.value) is ValueError


def test_validate_commit_policy_requires_exact_boolean_fields():
    valid = dict(COMMIT_DEFAULTS)
    assert validate_commit_policy(valid) is None

    missing = {name: value for name, value in valid.items() if name != "allow_push"}
    with pytest.raises(ValueError):
        validate_commit_policy(missing)

    with pytest.raises(ValueError):
        validate_commit_policy({**valid, "allow_push": 1})

    with pytest.raises(ValueError):
        validate_commit_policy({**valid, "extra_field": True})
