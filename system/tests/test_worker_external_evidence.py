"""External provenance foundations never manufacture native model evidence."""
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

from gui.device_auth import create_device, create_task_result_operator, revoke_device
from hub._services import worker_external_evidence as external
from hub._services import worker_review_identity as identity
from hub._services.worker_policy_settings import PolicyConflict, PolicyUnavailable


@pytest.fixture
def authority(tmp_path):
    path = tmp_path / "external.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE system_config(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    conn.commit()
    operator = create_task_result_operator("external-fixture-operator", connection=conn)
    ordinary = create_device("external-fixture-device", connection=conn)
    conn.close()
    return SimpleNamespace(path=path, operator=operator, ordinary=ordinary)


def source(**changes):
    return {"source_id": "source:luna", "platform_id": "codex", "tenant_id": "tenant:fixture",
            "account_id": "account:fixture", "source_principal_id": "agent:luna",
            "model_key": "served-model-v1", "model_principal_id": "model:shared",
            "model_labels": ["fixture-model"], **changes}


def register_model(authority, ids=None):
    current = identity.read_model_principal_catalog(authority.path)
    return identity.write_model_principal_catalog(
        {"configuration_version": current["configuration_version"],
         "principal_ids": ids or ["model:shared"]},
        operator_token=authority.operator, db_path=authority.path)


def register_sources(authority, entries=None):
    current = external.read_external_principals(authority.path)
    return external.write_external_principals(
        {"configuration_version": current["configuration_version"],
         "principals": entries if entries is not None else [source()]},
        operator_token=authority.operator, db_path=authority.path)


def database_state(path):
    with sqlite3.connect(path) as conn:
        return (list(conn.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name")),
                list(conn.execute("SELECT key,value FROM system_config ORDER BY key")))


def test_empty_gets_are_read_only_and_create_no_artifact_or_execution_tables(authority):
    before = database_state(authority.path)
    assert external.read_external_principals(authority.path)["principals"] == []
    assert identity.read_model_principal_catalog(authority.path)["principal_ids"] == []
    with pytest.raises(KeyError):
        external.read_external_artifact("a" * 32, operator_token=authority.operator, db_path=authority.path)
    assert database_state(authority.path) == before


@pytest.mark.parametrize("operation", ["catalog", "sources", "artifact", "read"])
def test_ordinary_device_cannot_grant_identity_or_read_private_bytes(authority, operation):
    register_model(authority)
    stored = external.store_external_artifact(b"private fixture", media_type="text/plain",
        operator_token=authority.operator, db_path=authority.path)
    before = database_state(authority.path)
    with pytest.raises(identity.IdentityPermissionDenied):
        if operation == "catalog":
            state = identity.read_model_principal_catalog(authority.path)
            identity.write_model_principal_catalog(
                {"configuration_version": state["configuration_version"], "principal_ids": ["model:other"]},
                operator_token=authority.ordinary, db_path=authority.path)
        elif operation == "sources":
            state = external.read_external_principals(authority.path)
            external.write_external_principals(
                {"configuration_version": state["configuration_version"], "principals": [source()]},
                operator_token=authority.ordinary, db_path=authority.path)
        elif operation == "artifact":
            external.store_external_artifact(b"new bytes", media_type="text/plain",
                operator_token=authority.ordinary, db_path=authority.path)
        else:
            external.read_external_artifact(stored["artifact_id"], operator_token=authority.ordinary,
                db_path=authority.path)
    assert database_state(authority.path) == before


def test_external_mapping_requires_an_explicit_global_model_principal(authority):
    with pytest.raises(ValueError, match="zuerst"):
        register_sources(authority)
    register_model(authority)
    assert register_sources(authority)["updated"] is True
    snapshot = external.read_external_principals(authority.path)
    bound = external.resolve_external_principal(snapshot, source_id="source:luna",
        model_key="served-model-v1", model_label="fixture-model")
    assert bound["model_principal_id"] == "model:shared"
    assert bound["source_principal_id"] == "agent:luna"
    assert bound["source_principal_id"] != bound["model_principal_id"]


def test_native_alias_and_external_source_share_one_global_model_identity(authority):
    state = identity.read_model_bindings(authority.path)
    binding = {"principal_id": "model:shared", "backend_id": "openai", "route_sha256": "b" * 64,
               "requested_models": ["requested-fixture"], "reported_models": ["served-fixture"]}
    identity.write_model_bindings({"configuration_version": state["configuration_version"],
        "bindings": [binding]}, operator_token=authority.operator, db_path=authority.path)
    assert identity.read_model_principal_catalog(authority.path)["principal_ids"] == ["model:shared"]
    register_sources(authority)
    assert external.read_external_principals(authority.path)["principals"][0]["model_principal_id"] == binding["principal_id"]


def test_source_registry_cas_also_binds_global_model_catalog(authority):
    stale = external.read_external_principals(authority.path)
    register_model(authority)
    with pytest.raises(PolicyConflict):
        external.write_external_principals({"configuration_version": stale["configuration_version"],
            "principals": [source()]}, operator_token=authority.operator, db_path=authority.path)


def test_global_catalog_cas_detects_native_alias_changes(authority):
    stale = identity.read_model_principal_catalog(authority.path)
    aliases = identity.read_model_bindings(authority.path)
    identity.write_model_bindings({"configuration_version": aliases["configuration_version"], "bindings": []},
        operator_token=authority.operator, db_path=authority.path)
    with pytest.raises(PolicyConflict):
        identity.write_model_principal_catalog({"configuration_version": stale["configuration_version"],
            "principal_ids": ["model:shared"]}, operator_token=authority.operator, db_path=authority.path)


def test_no_auto_identity_from_label_or_account(authority):
    register_model(authority)
    register_sources(authority)
    snapshot = external.read_external_principals(authority.path)
    assert external.resolve_external_principal(snapshot, source_id="unregistered",
        model_key="served-model-v1", model_label="fixture-model") is None
    assert external.resolve_external_principal(snapshot, source_id="source:luna",
        model_key="wrong-deployment", model_label="fixture-model") is None
    assert external.resolve_external_principal(snapshot, source_id="source:luna",
        model_key="served-model-v1", model_label="wrong-label") is None


def test_other_account_does_not_create_another_identity_for_same_deployment():
    with pytest.raises(ValueError, match="mehrere globale"):
        external.validate_principals([source(), source(source_id="other", account_id="other",
            source_principal_id="other", model_principal_id="model:different")])


def test_same_account_can_explicitly_bind_two_different_models():
    assert len(external.validate_principals([source(), source(source_id="other", model_key="model-v2",
        model_principal_id="model:different")])) == 2


def test_unrelated_mapping_change_keeps_own_binding_digest(authority):
    register_model(authority, ["model:shared", "model:other"])
    register_sources(authority)
    before = external.read_external_principals(authority.path)
    own = external.resolve_external_principal(before, source_id="source:luna",
        model_key="served-model-v1", model_label="fixture-model")
    register_sources(authority, [source(), source(source_id="other", source_principal_id="other",
        model_key="other-deployment", model_principal_id="model:other")])
    after = external.read_external_principals(authority.path)
    assert before["configuration_version"] != after["configuration_version"]
    assert external.resolve_external_principal(after, source_id="source:luna",
        model_key="served-model-v1", model_label="fixture-model", binding_sha256=own["binding_sha256"])


def test_removed_global_principal_invalidates_external_binding(authority):
    register_model(authority)
    register_sources(authority)
    state = identity.read_model_principal_catalog(authority.path)
    identity.write_model_principal_catalog({"configuration_version": state["configuration_version"],
        "principal_ids": []}, operator_token=authority.operator, db_path=authority.path)
    assert external.resolve_external_principal(external.read_external_principals(authority.path),
        source_id="source:luna", model_key="served-model-v1", model_label="fixture-model") is None


def test_retired_global_principal_cannot_revive_old_external_binding(authority):
    register_model(authority)
    register_sources(authority)
    original = external.resolve_external_principal(external.read_external_principals(authority.path),
        source_id="source:luna", model_key="served-model-v1", model_label="fixture-model")
    state = identity.read_model_principal_catalog(authority.path)
    identity.write_model_principal_catalog({"configuration_version": state["configuration_version"],
        "principal_ids": []}, operator_token=authority.operator, db_path=authority.path)
    state = identity.read_model_principal_catalog(authority.path)
    assert state["retired_principal_ids"] == ["model:shared"]
    before = database_state(authority.path)
    with pytest.raises(ValueError, match="wiederverwendet"):
        register_model(authority)
    assert database_state(authority.path) == before
    assert external.resolve_external_principal(external.read_external_principals(authority.path),
        source_id="source:luna", model_key="served-model-v1", model_label="fixture-model",
        binding_sha256=original["binding_sha256"]) is None


def test_native_alias_cannot_bypass_retired_global_principal(authority):
    register_model(authority)
    state = identity.read_model_principal_catalog(authority.path)
    identity.write_model_principal_catalog({"configuration_version": state["configuration_version"],
        "principal_ids": []}, operator_token=authority.operator, db_path=authority.path)
    aliases = identity.read_model_bindings(authority.path)
    before = database_state(authority.path)
    with pytest.raises(ValueError, match="neu gebunden"):
        identity.write_model_bindings({"configuration_version": aliases["configuration_version"],
            "bindings": [{"principal_id": "model:shared", "backend_id": "openai", "route_sha256": "c" * 64,
                "requested_models": ["requested"], "reported_models": ["served"]}]},
            operator_token=authority.operator, db_path=authority.path)
    assert database_state(authority.path) == before


@pytest.mark.parametrize("explicit_first", [False, True], ids=["native-only", "explicit-and-native"])
def test_last_native_alias_removal_retires_global_principal(authority, explicit_first):
    if explicit_first:
        register_model(authority)
    binding = {"principal_id": "model:shared", "backend_id": "openai", "route_sha256": "c" * 64,
               "requested_models": ["requested"], "reported_models": ["served"]}
    def write_aliases(bindings):
        state = identity.read_model_bindings(authority.path)
        return identity.write_model_bindings({"configuration_version": state["configuration_version"],
            "bindings": bindings}, operator_token=authority.operator, db_path=authority.path)
    write_aliases([binding])
    register_sources(authority)
    if explicit_first:
        state = identity.read_model_principal_catalog(authority.path)
        identity.write_model_principal_catalog({"configuration_version": state["configuration_version"],
            "principal_ids": []}, operator_token=authority.operator, db_path=authority.path)
        assert identity.read_model_principal_catalog(authority.path)["retired_principal_ids"] == []
    write_aliases([])
    assert identity.read_model_principal_catalog(authority.path)["retired_principal_ids"] == ["model:shared"]
    before = database_state(authority.path)
    with pytest.raises(ValueError, match="neu gebunden"):
        write_aliases([binding])
    with pytest.raises(ValueError, match="wiederverwendet"):
        register_model(authority)
    assert database_state(authority.path) == before
    assert external.resolve_external_principal(external.read_external_principals(authority.path),
        source_id="source:luna", model_key="served-model-v1", model_label="fixture-model") is None


@pytest.mark.parametrize("entry", [source(model_labels=[]), source(model_labels=["x", "x"]),
    source(model_labels=[None]), source(platform_id="https://example.test"), source(account_id=True),
    source(model_key="bad\nkey"), source(model_principal_id=""), source(extra="unexpected")])
def test_malformed_registry_entries_rejected(entry):
    with pytest.raises((ValueError, TypeError)):
        external.validate_principals([entry])


@pytest.mark.parametrize("invalid", [False, 0, "", {}])
def test_malformed_persisted_registry_is_not_treated_as_empty(authority, invalid):
    with sqlite3.connect(authority.path) as conn:
        conn.execute("INSERT INTO system_config(key,value) VALUES (?,?)",
            (external.REGISTRY_KEY, json.dumps({"revision": 1, "values": invalid})))
    with pytest.raises(PolicyUnavailable):
        external.read_external_principals(authority.path)


def test_artifact_is_server_hashed_private_immutable_and_idempotent(authority):
    raw = b'{"platform":"fixture","turn":"actual-artifact"}\n'
    first = external.store_external_artifact(raw, media_type="application/x-ndjson",
        operator_token=authority.operator, db_path=authority.path)
    second = external.store_external_artifact(raw, media_type="application/x-ndjson",
        operator_token=authority.operator, db_path=authority.path)
    assert first["created"] and not second["created"]
    assert first["artifact_id"] == second["artifact_id"]
    assert first["sha256"] == hashlib.sha256(raw).hexdigest()
    assert "content" not in first and "path" not in first
    private = external.read_external_artifact(first["artifact_id"],
        operator_token=authority.operator, db_path=authority.path)
    assert private["content"] == raw
    with sqlite3.connect(authority.path) as conn:
        manifest = external.artifact_manifest(conn, [first["artifact_id"]])
        assert manifest[0]["sha256"] == first["sha256"]
        assert "content" not in manifest[0]
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='worker_model_executions'").fetchone() is None


def test_same_bytes_cannot_overwrite_artifact_media_type(authority):
    external.store_external_artifact(b"fixture", media_type="text/plain",
        operator_token=authority.operator, db_path=authority.path)
    with pytest.raises(PolicyConflict):
        external.store_external_artifact(b"fixture", media_type="application/json",
            operator_token=authority.operator, db_path=authority.path)


@pytest.mark.parametrize("content", [b"", "string not bytes", bytearray(b"bytes"), b"x" * (external.MAX_ARTIFACT_BYTES + 1)],
    ids=["empty", "text", "mutable-bytes", "oversize"])
def test_invalid_artifact_data_rejected_before_database_mutation(authority, content):
    before = database_state(authority.path)
    with pytest.raises(ValueError):
        external.store_external_artifact(content, media_type="text/plain",
            operator_token=authority.operator, db_path=authority.path)
    assert database_state(authority.path) == before


def test_corrupted_artifact_never_projects_verified_manifest(authority):
    stored = external.store_external_artifact(b"original", media_type="text/plain",
        operator_token=authority.operator, db_path=authority.path)
    with sqlite3.connect(authority.path) as conn:
        conn.execute("UPDATE worker_external_artifacts SET content=? WHERE artifact_id=?",
            (b"corrupt!", stored["artifact_id"]))
        with pytest.raises(PolicyUnavailable):
            external.artifact_manifest(conn, [stored["artifact_id"]])


def test_revoked_operator_cannot_read_existing_artifact(authority):
    stored = external.store_external_artifact(b"private", media_type="text/plain",
        operator_token=authority.operator, db_path=authority.path)
    with sqlite3.connect(authority.path) as conn:
        revoke_device("external-fixture-operator", connection=conn)
    with pytest.raises(identity.IdentityPermissionDenied):
        external.read_external_artifact(stored["artifact_id"], operator_token=authority.operator,
            db_path=authority.path)


@pytest.mark.parametrize("ids", [[], ["a" * 32] * 2, [True], ["../private"], ["a" * 32] * 9])
def test_artifact_manifest_rejects_invalid_refs(authority, ids):
    with sqlite3.connect(authority.path) as conn:
        with pytest.raises(ValueError):
            external.artifact_manifest(conn, ids)
