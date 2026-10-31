"""BACH #2231: creator priority is off by default and set as a system setting."""
import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hub._services import task_lease_settings as settings
from hub._services.task_lease import LeaseConfig
from hub._services.worker_policy_settings import PolicyConflict
from system.tests.test_task_lease_service import T0, _acq, _insert, conn, db_path  # noqa: F401

CREATED = (T0 - timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S")
FOREIGN = "codex@WORKSTATION-LG"


@pytest.fixture
def config_db(conn):
    conn.execute("""CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT NOT NULL,
        type TEXT DEFAULT 'string', category TEXT, description TEXT, updated_at TEXT,
        dist_type INTEGER DEFAULT 2)""")
    conn.commit()
    return conn


def _enable(db_path, window=120):
    current = settings.read_setting(db_path)
    return settings.write_setting({"configuration_version": current["configuration_version"],
                                   "enabled": True, "window_seconds": window},
                                  actor="device:test", db_path=db_path)


def test_new_task_is_leasable_by_others_at_once_by_default(config_db, monkeypatch):
    monkeypatch.delenv("BACH_TASK_LEASE_CREATOR_WINDOW", raising=False)
    assert LeaseConfig.from_env().creator_window_seconds is None
    tid = _insert(config_db, created_by="claude", created_at=CREATED)
    assert _acq(config_db, tid, worker=FOREIGN, config=LeaseConfig()).granted


def test_enabled_setting_reserves_the_task_for_its_creator(config_db, db_path):
    assert _enable(db_path)["window_seconds"] == 120
    tid = _insert(config_db, created_by="claude", created_at=CREATED)
    denied = _acq(config_db, tid, worker=FOREIGN, config=LeaseConfig())
    assert denied.payload["reason"] == "creator_priority"
    assert _acq(config_db, tid, worker=FOREIGN, config=LeaseConfig(),
                now=T0 + timedelta(seconds=91)).granted


@pytest.mark.parametrize("consumed_at, revoked_at", [
    (None, None), ("2026-10-05T01:59:59Z", None), (None, "2026-10-05T01:59:59Z"),
], ids=["open", "redeemed", "revoked"])
def test_sequence_step_keeps_the_previous_ten_minute_gate(config_db, consumed_at, revoked_at):
    config_db.execute("""CREATE TABLE native_sequence_creator_delegations (
        task_id INTEGER NOT NULL UNIQUE, consumed_at TEXT, revoked_at TEXT)""")
    step = _insert(config_db, created_by="user", created_at=CREATED)
    config_db.execute("INSERT INTO native_sequence_creator_delegations VALUES (?,?,?)",
                      (step, consumed_at, revoked_at))
    config_db.commit()
    denied = _acq(config_db, step, worker=FOREIGN, config=LeaseConfig(), now=T0 + timedelta(minutes=8))
    assert denied.payload["reason"] == "creator_priority"
    assert _acq(config_db, step, worker=FOREIGN, config=LeaseConfig(),
                now=T0 + timedelta(minutes=10)).granted


def test_operator_environment_value_overrides_the_setting(config_db, db_path, monkeypatch):
    _enable(db_path, window=3600)
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    tid = _insert(config_db, created_by="claude", created_at=CREATED)
    assert _acq(config_db, tid, worker=FOREIGN, config=LeaseConfig.from_env()).granted


def test_setting_write_is_versioned_and_validated(config_db, db_path):
    first = settings.read_setting(db_path)
    assert (first["enabled"], first["window_seconds"], first["source"]) == (False, 120, "system_default")
    _enable(db_path, window=300)
    with pytest.raises(PolicyConflict):
        settings.write_setting({"configuration_version": first["configuration_version"],
                                "enabled": False, "window_seconds": 120}, actor="device:test", db_path=db_path)
    current = settings.read_setting(db_path)
    assert (current["enabled"], current["window_seconds"], current["source"]) == (True, 300, "user_override")
    for bad in ({"enabled": "yes", "window_seconds": 120}, {"enabled": True, "window_seconds": 0},
                {"enabled": True, "window_seconds": True}, {"enabled": True}):
        with pytest.raises(ValueError):
            settings.write_setting({"configuration_version": current["configuration_version"], **bad},
                                   actor="device:test", db_path=db_path)


def test_unreadable_or_missing_setting_means_off(config_db):
    import sqlite3
    assert settings.stored_window(sqlite3.connect(":memory:")) == 0  # no system_config table
    assert settings.stored_window(config_db) == 0  # no key
    config_db.execute("INSERT INTO system_config(key,value) VALUES (?,?)", (settings.KEY, "{broken"))
    assert settings.stored_window(config_db) == 0
    config_db.execute("UPDATE system_config SET value=? WHERE key=?",
                      (json.dumps({"revision": 1, "values": {"enabled": True, "window_seconds": 60}}), settings.KEY))
    assert settings.stored_window(config_db) == 60


def test_window_upper_bound_is_rejected_and_max_window_is_writable(config_db, db_path):
    current = settings.read_setting(db_path)
    with pytest.raises(ValueError):
        settings.write_setting({"configuration_version": current["configuration_version"],
                                "enabled": True, "window_seconds": settings.MAX_WINDOW_SECONDS + 1},
                               actor="device:test", db_path=db_path)
    written = settings.write_setting({"configuration_version": current["configuration_version"],
                                     "enabled": True, "window_seconds": settings.MAX_WINDOW_SECONDS},
                                    actor="device:test", db_path=db_path)
    assert written["window_seconds"] == settings.MAX_WINDOW_SECONDS
    assert settings.read_setting(db_path)["window_seconds"] == settings.MAX_WINDOW_SECONDS
    assert settings.stored_window(config_db) == settings.MAX_WINDOW_SECONDS


def test_unknown_field_and_missing_version_are_rejected(config_db, db_path):
    current = settings.read_setting(db_path)
    with pytest.raises(ValueError):
        settings.write_setting({"configuration_version": current["configuration_version"],
                                "enabled": True, "window_seconds": 120, "foo": 1},
                               actor="device:test", db_path=db_path)
    with pytest.raises(ValueError):
        settings.write_setting({"enabled": True, "window_seconds": 120},
                               actor="device:test", db_path=db_path)


def test_environment_value_activates_the_gate_despite_a_disabled_setting(config_db, monkeypatch):
    assert settings.stored_window(config_db) == 0  # the stored setting stays off
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "600")
    assert LeaseConfig.from_env().creator_window_seconds == 600
    tid = _insert(config_db, created_by="claude", created_at=CREATED)
    denied = _acq(config_db, tid, worker=FOREIGN, config=LeaseConfig.from_env())
    assert denied.payload["reason"] == "creator_priority"
    assert _acq(config_db, tid, worker=FOREIGN, config=LeaseConfig.from_env(),
                now=T0 + timedelta(seconds=601)).granted
