"""Policy export must preserve native authority, CAS and canonical persistence."""
import importlib.util
import json
import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest
from hub._services import ocean_stack_bridge as bridge
from hub._services import worker_policy_settings as native


@pytest.fixture
def exported():
    path = Path(__file__).resolve().parents[2] / ".MODULES/worker_policy/src/worker_policy.py"
    spec = importlib.util.spec_from_file_location("test_policy_export", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "data/bach.db"
    path.parent.mkdir()
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT, status TEXT,
                                require_user_review INTEGER DEFAULT 0);
            INSERT INTO tasks VALUES (1, 'Synthetic policy task', 'pending', 0);
        """)
    return path


def global_payload(snapshot):
    return {key: deepcopy(snapshot[key]) for key in
            ("configuration_version", "policy", "selection", "worker_selection")}


def task_payload(snapshot):
    return {key: deepcopy(snapshot[key]) for key in
            ("task_id", "task_version", "configuration_version", "override")}


def test_global_native_save_readback_and_stale_cas(exported, database):
    before = exported.read_global_policy(database)
    payload = global_payload(before)
    payload["policy"]["github_external_review"] = not before["policy"]["github_external_review"]
    saved = exported.write_global_policy(payload, db_path=database)
    after = native.read_global_policy(database)
    assert saved["updated"] is True and saved["worker_started"] is False
    assert "saved" not in saved
    assert saved["configuration_version"] == after["configuration_version"]
    assert after["policy"] == payload["policy"]
    assert exported.PolicyConflict is native.PolicyConflict
    with pytest.raises(native.PolicyConflict):
        exported.write_global_policy(payload, db_path=database)
    assert native.read_global_policy(database) == after


def test_task_native_save_readback_and_stale_cas(exported, database):
    payload = task_payload(exported.read_task_policy(1, database))
    payload["override"]["require_user_review"] = True
    saved = exported.write_task_policy(1, payload, db_path=database)
    after = native.read_task_policy(1, database)
    assert saved["updated"] is True and saved["worker_started"] is False
    assert saved["configuration_version"] == after["configuration_version"]
    assert after["override"]["require_user_review"] is True
    with pytest.raises(native.PolicyConflict):
        exported.write_task_policy(1, payload, db_path=database)
    with pytest.raises(KeyError):
        exported.read_task_policy(999, database)


def test_missing_authority_does_not_save_or_ack(exported, database):
    before = native.read_global_policy(database)
    payload = global_payload(before)
    payload["policy"]["reviewers"] = [{"reviewer_id": "synthetic-reviewer", "tier": "standard"}]
    with pytest.raises(PermissionError):
        exported.write_global_policy(payload, db_path=database)
    assert native.read_global_policy(database) == before


def test_native_operator_token_is_forwarded_without_new_authority(exported, monkeypatch):
    observed = {}

    def save(payload, **kwargs):
        observed.update(kwargs)
        raise PermissionError("synthetic denial")

    monkeypatch.setattr(native, "write_global_policy", save)
    with pytest.raises(PermissionError):
        exported.write_global_policy({}, operator_token="synthetic-token")
    assert observed["operator_token"] == "synthetic-token"


@pytest.mark.parametrize("operation", ["read_global", "write_global", "read_task", "write_task"])
def test_missing_native_service_is_unavailable(exported, monkeypatch, operation):
    monkeypatch.setattr(exported, "_service", None)
    calls = {"read_global": lambda: exported.read_global_policy(),
             "write_global": lambda: exported.write_global_policy({}),
             "read_task": lambda: exported.read_task_policy(1),
             "write_task": lambda: exported.write_task_policy(1, {})}
    with pytest.raises(exported.PolicyUnavailable):
        calls[operation]()


def test_missing_schema_or_store_never_fabricates_snapshot(exported, database, tmp_path):
    payload = global_payload(native.read_global_policy(database))
    missing = tmp_path / "missing.db"
    with pytest.raises(native.PolicyUnavailable):
        exported.read_global_policy(missing)
    assert not missing.exists()
    empty = tmp_path / "empty.db"
    empty.write_bytes(b"")
    for operation in (lambda: exported.read_global_policy(empty),
                      lambda: exported.write_global_policy(payload, db_path=empty),
                      lambda: exported.read_task_policy(1, empty)):
        with pytest.raises(native.PolicyUnavailable):
            operation()
    assert empty.read_bytes() == b""


def test_missing_kernel_remains_unavailable(exported, database, monkeypatch):
    def unavailable():
        raise native.PolicyUnavailable("synthetic missing kernel")

    monkeypatch.setattr(native, "_kernel", unavailable)
    with pytest.raises(native.PolicyUnavailable):
        exported.read_global_policy(database)


def test_absent_export_loader_uses_native_service_not_handler(monkeypatch):
    monkeypatch.setattr(bridge, "_MODULE_CACHE", {})
    monkeypatch.setattr(Path, "is_file", lambda path: False)
    assert bridge.load_worker_policy_module() is native
    assert bridge.get_service_or_standalone("worker_policy") is native


def test_explicit_nonselfcontained_export_is_rejected_without_install(tmp_path):
    from hub.skills import SkillsHandler, verify_selfcontained_module

    source = Path(__file__).resolve().parents[2] / ".MODULES/worker_policy"
    valid, errors, _, _ = verify_selfcontained_module(source)
    assert valid is False
    assert any("nicht eigenständig" in message for message in errors)
    installed, message = SkillsHandler(tmp_path)._install(str(source))
    assert installed is False and "ABGELEHNT" in message
    assert not (tmp_path / "skills").exists()
    assert not (tmp_path / ".MODULES").exists()


@pytest.mark.parametrize("flag", [True, None])
def test_existing_manifest_without_false_stays_compatible(tmp_path, flag):
    from hub.skills import verify_selfcontained_module

    manifest = {"name": "synthetic", "version": "1.0.0", "entrypoints": {"library": "module.py"}}
    if flag is not None:
        manifest["selfcontained"] = flag
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    assert verify_selfcontained_module(tmp_path)[0] is True


def test_declared_nonselfcontained_policy_export_uses_native_fallback(monkeypatch):
    monkeypatch.setattr(bridge, "_MODULE_CACHE", {})
    assert bridge.load_worker_policy_module() is native


def test_cli_preserves_injected_userdb_and_reports_failed_save(exported, database, monkeypatch):
    from hub import worker_policy

    monkeypatch.setattr(worker_policy, "service", exported)
    handler = worker_policy.WorkerPolicyHandler(database.parent.parent)
    success, text = handler.handle("status", [])
    assert success
    snapshot = json.loads(text)
    payload = global_payload(snapshot)
    payload["policy"]["reviewers"] = [{"reviewer_id": "synthetic-reviewer", "tier": "standard"}]
    success, _ = handler.handle("set", [json.dumps(payload)])
    assert success is False
    payload = global_payload(snapshot)
    payload["configuration_version"] = "0" * 64
    success, _ = handler.handle("set", [json.dumps(payload)])
    assert success is False
    assert native.read_global_policy(database) == snapshot


def test_invalid_payload_is_not_success(exported, database):
    with pytest.raises(ValueError):
        exported.write_global_policy({"arbitrary": "input"}, db_path=database)
    with pytest.raises(ValueError):
        exported.write_task_policy(1, {}, db_path=database)
