"""Behavioral tests for operator-owned model principals and route stamps."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from types import SimpleNamespace

import pytest

from gui.device_auth import create_device, create_task_result_operator, revoke_device
from hub._services.llm.controller_route import bind_controller_backend, route_snapshot
from hub._services.llm.model_backend import (
    AnthropicBackend,
    CLIBackend,
    HermesBackend,
    LMStudioBackend,
    OllamaBackend,
    OpenAIBackend,
    OpenRouterBackend,
)
from hub._services.worker_policy_settings import PolicyConflict, PolicyUnavailable
from hub._services.worker_review_identity import (
    IdentityPermissionDenied,
    principal_for_execution,
    principal_for_route,
    read_model_bindings,
    resolve_binding,
    validate_bindings,
    write_model_bindings,
)


@pytest.fixture
def identity_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from gui import device_auth, server
    from gui.api import unified_api
    from hub import bach_paths
    from hub._services.task_lease import ensure_task_lease_schema

    path = tmp_path / "worker-review-api.sqlite"
    conn = _open_db(path)
    conn.executescript("""
        CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, description TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            priority TEXT NOT NULL DEFAULT 'M', category TEXT, assigned_to TEXT,
            created_by TEXT, depends_on TEXT, estimated_minutes INTEGER,
            actual_minutes INTEGER, started_at TEXT, completed_at TEXT,
            updated_at TEXT, due_date TEXT, source TEXT
        );
        CREATE TABLE task_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL,
            action TEXT NOT NULL, field_changed TEXT, old_value TEXT,
            new_value TEXT, changed_by TEXT, changed_at TEXT NOT NULL
        );
    """)
    ensure_task_lease_schema(conn)
    device_name = "worker-review-device-" + uuid.uuid4().hex
    device_token = create_device(device_name, connection=conn)
    operator_name = "worker-review-operator-" + uuid.uuid4().hex
    operator_token = create_task_result_operator(
        operator_name, connection=conn
    )
    conn.close()

    monkeypatch.setattr(bach_paths, "BACH_DB", path)
    monkeypatch.setattr(unified_api, "BACH_DB", path)
    monkeypatch.setattr(device_auth, "GET_CONNECTION", lambda: _open_db(path))
    client = TestClient(server.app)
    yield SimpleNamespace(
        client=client,
        path=path,
        device_name=device_name,
        device_token=device_token,
        operator_name=operator_name,
        operator_token=operator_token,
    )
    client.close()


def _device_headers(api):
    return {"Authorization": f"Bearer {api.device_token}"}


def _global_payload(snapshot):
    return {
        "configuration_version": snapshot["configuration_version"],
        "policy": json.loads(json.dumps(snapshot["policy"])),
        "selection": json.loads(json.dumps(snapshot["selection"])),
    }


def _open_db(path):
    conn = sqlite3.connect(str(path), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _schema_objects(path):
    conn = _open_db(path)
    try:
        return tuple(
            tuple(row)
            for row in conn.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
            )
        )
    finally:
        conn.close()


def _config_rows(path):
    conn = _open_db(path)
    try:
        return tuple(
            tuple(row)
            for row in conn.execute(
                "SELECT key,value FROM system_config ORDER BY key"
            )
        )
    finally:
        conn.close()


def _identity_database(path):
    conn = _open_db(path)
    conn.execute(
        "CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.commit()
    operator_name = "review-operator-" + uuid.uuid4().hex
    operator_token = create_task_result_operator(operator_name, connection=conn)
    device_token = create_device("ordinary-device-" + uuid.uuid4().hex, connection=conn)
    conn.close()
    return path, operator_name, operator_token, device_token


def _binding(
    principal_id="principal:reviewer-a",
    *,
    backend_id="openai",
    route_sha256=None,
    requested_models=None,
    reported_models=None,
):
    return {
        "principal_id": principal_id,
        "backend_id": backend_id,
        "route_sha256": route_sha256 or hashlib.sha256(b"fixture-route").hexdigest(),
        "requested_models": requested_models or ["requested-model"],
        "reported_models": reported_models or ["served-model"],
    }


def _available_snapshot(bindings):
    normalized = validate_bindings(bindings)
    return {
        "availability": "available",
        "configuration_version": _json_digest({"bindings": normalized}),
        "bindings": normalized,
    }


def _json_digest(value):
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _execution_receipt(snapshot, *, backend_id, route_sha256, requested_model, observed_model):
    binding = resolve_binding(
        snapshot,
        backend_id=backend_id,
        route_sha256=route_sha256,
        requested_model=requested_model,
        observed_model=observed_model,
    )
    if binding is None:
        raise AssertionError("fixture must resolve to exactly one current binding")
    return {
        "availability": "available",
        "model_provenance": "provider_reported",
        "backend_id": backend_id,
        "route_sha256": route_sha256,
        "requested_model": requested_model,
        "observed_model": observed_model,
        "model_principal_id": binding["principal_id"],
        "identity_binding_sha256": _json_digest(binding),
        "identity_configuration_version": snapshot["configuration_version"],
    }


def _backend(provider):
    if provider == "ollama":
        return OllamaBackend(
            base_url="http://127.0.0.1:11434", default_model="fixture-model"
        ), None
    if provider == "lmstudio":
        return LMStudioBackend(
            base_url="http://127.0.0.1:1234/v1",
            api_key="fixture-raw-key",
            default_model="fixture-model",
        ), None
    if provider == "openai":
        return OpenAIBackend(
            base_url="https://openai.fixture/v1",
            api_key="fixture-raw-key",
            default_model="fixture-model",
        ), "env:OPENAI_API_KEY"
    if provider == "hermes":
        return HermesBackend(
            base_url="https://hermes.fixture/v1",
            api_key="fixture-raw-key",
            default_model="fixture-model",
        ), "env:OPENROUTER_API_KEY"
    if provider == "openrouter":
        return OpenRouterBackend(
            base_url="https://openrouter.ai/api/v1",
            api_key="fixture-raw-key",
            default_model="openrouter/free",
        ), "env:OPENROUTER_API_KEY"
    if provider == "anthropic":
        return AnthropicBackend(
            api_key="fixture-raw-key", default_model="fixture-model"
        ), "env:ANTHROPIC_API_KEY"
    raise AssertionError(f"unknown fixture provider: {provider}")


@pytest.mark.parametrize(
    ("provider", "factory_id"),
    [
        ("ollama", "ollama"),
        ("lmstudio", "lmstudio"),
        ("openai", "openai"),
        ("hermes", "hermes"),
        ("openrouter", "openrouter"),
        ("anthropic", "claude-api"),
    ],
)
def test_native_backend_instances_produce_private_route_snapshots(provider, factory_id):
    backend, credential_ref = _backend(provider)
    bound = bind_controller_backend(backend, credential_ref=credential_ref)

    snapshot = route_snapshot(bound)

    assert bound is backend
    assert snapshot is not None
    assert snapshot["backend_id"] == factory_id
    assert set(snapshot) == {"backend_id", "route_sha256"}
    assert re.fullmatch(r"[a-f0-9]{64}", snapshot["route_sha256"])
    public_text = repr(snapshot)
    assert "fixture-raw-key" not in public_text
    assert "https://" not in public_text
    if credential_ref is not None:
        assert backend._controller_route.credential == credential_ref
        assert credential_ref not in public_text
    else:
        assert backend._controller_route.credential == f"native-runtime:{factory_id}"

    if provider == "openai":
        same_reference, _ = _backend("openai")
        same_reference.api_key = "different-raw-key"
        bind_controller_backend(
            same_reference, credential_ref="env:OPENAI_API_KEY"
        )
        assert route_snapshot(same_reference) == snapshot


def test_route_snapshot_rejects_unstamped_cli_and_url_credentials():
    unbound, _ = _backend("openai")
    assert route_snapshot(unbound) is None

    cli = CLIBackend(cli_name="claude", cli_path="fixture-cli")
    assert bind_controller_backend(cli) is cli
    assert route_snapshot(cli) is None

    credential_url = OpenAIBackend(
        base_url="https://user:password@provider.fixture/v1",
        api_key="fixture-raw-key",
    )
    assert bind_controller_backend(
        credential_url, credential_ref="env:OPENAI_API_KEY"
    ) is credential_url
    assert route_snapshot(credential_url) is None


def test_route_snapshot_rejects_a_stamp_copied_from_another_backend_instance():
    original, credential_ref = _backend("openai")
    copied_to, _ = _backend("openai")
    bind_controller_backend(original, credential_ref=credential_ref)
    copied_to._controller_route = original._controller_route

    assert route_snapshot(original) is not None
    assert route_snapshot(copied_to) is None


@pytest.mark.parametrize("mutation", ["origin", "key"])
def test_route_snapshot_fails_closed_after_backend_identity_mutation(mutation):
    backend, credential_ref = _backend("openai")
    bind_controller_backend(backend, credential_ref=credential_ref)
    assert route_snapshot(backend) is not None

    if mutation == "origin":
        backend.base_url = "https://changed.fixture/v1"
    else:
        backend.api_key = "changed-raw-key"

    assert route_snapshot(backend) is None


def test_aliases_of_one_principal_resolve_only_for_a_provider_reported_execution():
    backend, credential_ref = _backend("openai")
    bind_controller_backend(backend, credential_ref=credential_ref)
    route = route_snapshot(backend)
    bindings = _available_snapshot([
        _binding(
            "principal:reviewer-a",
            backend_id=route["backend_id"],
            route_sha256=route["route_sha256"],
            requested_models=["requested-v1"],
            reported_models=["served-v1"],
        ),
        _binding(
            "principal:reviewer-a",
            backend_id=route["backend_id"],
            route_sha256=route["route_sha256"],
            requested_models=["requested-v2"],
            reported_models=["served-v2"],
        ),
    ])

    assert principal_for_route(
        bindings,
        backend_id=route["backend_id"],
        route_sha256=route["route_sha256"],
        requested_model="requested-v1",
    ) == "principal:reviewer-a"
    assert principal_for_route(
        bindings,
        backend_id=route["backend_id"],
        route_sha256=route["route_sha256"],
        requested_model="requested-v2",
    ) == "principal:reviewer-a"

    execution = _execution_receipt(
        bindings,
        backend_id=route["backend_id"],
        route_sha256=route["route_sha256"],
        requested_model="requested-v2",
        observed_model="served-v2",
    )
    assert principal_for_execution(bindings, execution) == "principal:reviewer-a"


def test_one_observed_route_model_cannot_be_assigned_to_two_principals():
    route = hashlib.sha256(b"real-bound-route-fixture").hexdigest()
    with pytest.raises(ValueError, match="mehrere Principals"):
        validate_bindings([
            _binding(
                "principal:reviewer-a",
                route_sha256=route,
                requested_models=["requested-a"],
                reported_models=["served-shared"],
            ),
            _binding(
                "principal:reviewer-b",
                route_sha256=route,
                requested_models=["requested-b"],
                reported_models=["served-shared"],
            ),
        ])


def test_free_route_with_more_than_one_planned_principal_has_no_identity():
    backend, credential_ref = _backend("openrouter")
    bind_controller_backend(backend, credential_ref=credential_ref)
    route = route_snapshot(backend)
    bindings = _available_snapshot([
        _binding(
            "principal:reviewer-a",
            backend_id=route["backend_id"],
            route_sha256=route["route_sha256"],
            requested_models=["openrouter/free"],
            reported_models=["provider/model-a"],
        ),
        _binding(
            "principal:reviewer-b",
            backend_id=route["backend_id"],
            route_sha256=route["route_sha256"],
            requested_models=["openrouter/free"],
            reported_models=["provider/model-b"],
        ),
    ])

    assert principal_for_route(
        bindings,
        backend_id=route["backend_id"],
        route_sha256=route["route_sha256"],
        requested_model="openrouter/free",
    ) is None


@pytest.mark.parametrize(
    ("change", "value"),
    [
        ("availability", "unavailable"),
        ("model_provenance", "unknown"),
        ("model_provenance", "legacy_release_only"),
        ("model_provenance", "request_only"),
        ("route_sha256", "f" * 64),
        ("requested_model", "unapproved-request"),
        ("observed_model", "unapproved-response"),
        ("model_principal_id", "principal:other-reviewer"),
        ("identity_binding_sha256", "0" * 64),
        ("identity_configuration_version", "not-a-digest"),
    ],
)
def test_execution_identity_requires_current_route_and_approved_alias(
    change, value
):
    backend, credential_ref = _backend("openai")
    bind_controller_backend(backend, credential_ref=credential_ref)
    route = route_snapshot(backend)
    bindings = _available_snapshot([
        _binding(
            backend_id=route["backend_id"],
            route_sha256=route["route_sha256"],
            requested_models=["requested-model"],
            reported_models=["served-model"],
        )
    ])
    execution = _execution_receipt(
        bindings,
        backend_id=route["backend_id"],
        route_sha256=route["route_sha256"],
        requested_model="requested-model",
        observed_model="served-model",
    )
    execution[change] = value

    assert principal_for_execution(bindings, execution) is None


def test_route_and_display_fields_without_historical_identity_proof_resolve_nothing():
    route = hashlib.sha256(b"late-binding-route").hexdigest()
    binding = _binding(route_sha256=route)
    current = _available_snapshot([binding])
    execution = {
        "availability": "available",
        "model_provenance": "provider_reported",
        "backend_id": binding["backend_id"],
        "route_sha256": route,
        "requested_model": "requested-model",
        "observed_model": "served-model",
    }

    # A present-day alias cannot retrospectively identify an earlier call.
    assert principal_for_execution(current, execution) is None


def test_historical_identity_stops_resolving_after_alias_change_or_revoke():
    route = hashlib.sha256(b"historical-binding-route").hexdigest()
    original = _binding(
        route_sha256=route,
        requested_models=["requested-model"],
        reported_models=["served-model-v1"],
    )
    original_snapshot = _available_snapshot([original])
    historical = _execution_receipt(
        original_snapshot,
        backend_id=original["backend_id"],
        route_sha256=route,
        requested_model="requested-model",
        observed_model="served-model-v1",
    )
    assert principal_for_execution(original_snapshot, historical) == original["principal_id"]

    changed = dict(original)
    changed["reported_models"] = ["served-model-v2"]
    changed_snapshot = _available_snapshot([changed])
    assert principal_for_execution(changed_snapshot, historical) is None

    revoked_snapshot = _available_snapshot([])
    assert principal_for_execution(revoked_snapshot, historical) is None


def test_binding_store_requires_explicit_active_operator_and_cas(tmp_path):
    path, operator_name, operator_token, device_token = _identity_database(
        tmp_path / "worker-review-identity.sqlite"
    )
    initial = read_model_bindings(path)
    first_binding = _binding("principal:reviewer-a")
    payload = {
        "configuration_version": initial["configuration_version"],
        "bindings": [first_binding],
    }

    with pytest.raises(IdentityPermissionDenied):
        write_model_bindings(payload, operator_token=device_token, db_path=path)
    with pytest.raises(IdentityPermissionDenied):
        write_model_bindings(payload, operator_token="unknown-token", db_path=path)

    conn = _open_db(path)
    try:
        assert revoke_device(operator_name, connection=conn) is True
    finally:
        conn.close()
    with pytest.raises(IdentityPermissionDenied):
        write_model_bindings(payload, operator_token=operator_token, db_path=path)

    after_denials = read_model_bindings(path)
    assert after_denials["bindings"] == []
    assert _config_rows(path) == ()

    conn = _open_db(path)
    try:
        replacement = create_task_result_operator(
            "replacement-operator-" + uuid.uuid4().hex,
            connection=conn,
        )
    finally:
        conn.close()
    current = read_model_bindings(path)
    successful = write_model_bindings(
        {
            "configuration_version": current["configuration_version"],
            "bindings": [first_binding],
        },
        operator_token=replacement,
        db_path=path,
    )
    assert successful["updated"] is True
    assert successful["worker_started"] is False

    changed_binding = _binding("principal:reviewer-b")
    stale_payload = {
        "configuration_version": current["configuration_version"],
        "bindings": [changed_binding],
    }
    config_before_stale_write = _config_rows(path)
    with pytest.raises(PolicyConflict):
        write_model_bindings(
            stale_payload, operator_token=replacement, db_path=path
        )

    readback = read_model_bindings(path)
    assert readback["bindings"] == [first_binding]
    assert readback["configuration_version"] == successful["configuration_version"]
    assert _config_rows(path) == config_before_stale_write


def test_binding_reads_are_query_only_and_never_create_schema(tmp_path):
    empty_path = tmp_path / "no-schema.sqlite"
    sqlite3.connect(str(empty_path)).close()
    assert _schema_objects(empty_path) == ()
    with pytest.raises(PolicyUnavailable):
        read_model_bindings(empty_path)
    assert _schema_objects(empty_path) == ()

    path = tmp_path / "configured-read-only.sqlite"
    conn = _open_db(path)
    conn.execute(
        "CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()
    schema_before = _schema_objects(path)
    rows_before = _config_rows(path)

    snapshot = read_model_bindings(path)

    assert snapshot["availability"] == "available"
    assert snapshot["bindings"] == []
    assert _schema_objects(path) == schema_before
    assert _config_rows(path) == rows_before


def test_model_principal_http_routes_require_device_and_operator(identity_api):
    client = identity_api.client
    path = identity_api.path
    endpoint = "/api/system/worker-model-principals"
    schema_before = _schema_objects(path)
    rows_before = _config_rows(path)

    assert client.get(endpoint).status_code == 401
    initial_response = client.get(endpoint, headers=_device_headers(identity_api))
    assert initial_response.status_code == 200
    initial = initial_response.json()
    assert initial["availability"] == "available"
    assert initial["bindings"] == []
    assert _schema_objects(path) == schema_before
    assert _config_rows(path) == rows_before

    payload = {
        "configuration_version": initial["configuration_version"],
        "bindings": [_binding("principal:reviewer-http")],
    }
    ordinary_headers = _device_headers(identity_api)
    denied = client.put(endpoint, json=payload, headers=ordinary_headers)
    assert denied.status_code == 403

    copied_device_right = dict(ordinary_headers)
    copied_device_right["X-BACH-Result-Operator"] = identity_api.device_token
    assert client.put(endpoint, json=payload, headers=copied_device_right).status_code == 403
    assert _config_rows(path) == rows_before
    assert client.get(endpoint, headers=ordinary_headers).json()["configuration_version"] == initial[
        "configuration_version"
    ]

    operator_headers = dict(ordinary_headers)
    operator_headers["X-BACH-Result-Operator"] = identity_api.operator_token
    written = client.put(endpoint, json=payload, headers=operator_headers)
    assert written.status_code == 200
    assert written.json()["updated"] is True
    assert written.json()["worker_started"] is False

    readback = client.get(endpoint, headers=ordinary_headers)
    assert readback.status_code == 200
    current = readback.json()
    assert current["bindings"] == [_binding("principal:reviewer-http")]
    assert current["configuration_version"] == written.json()["configuration_version"]

    stale_rows = _config_rows(path)
    conflict = client.put(endpoint, json=payload, headers=operator_headers)
    assert conflict.status_code == 409
    assert client.get(endpoint, headers=ordinary_headers).json() == current
    assert _config_rows(path) == stale_rows


def test_global_policy_http_keeps_device_settings_but_reserves_reviewer_changes(
    identity_api,
):
    client = identity_api.client
    endpoint = "/api/system/worker-policy"
    device_headers = _device_headers(identity_api)

    initial_response = client.get(endpoint, headers=device_headers)
    assert initial_response.status_code == 200
    initial = initial_response.json()
    rows_before = _config_rows(identity_api.path)
    reviewer_change = _global_payload(initial)
    reviewer_change["policy"]["reviewers"] = [
        {"reviewer_id": "principal:reviewer-a", "tier": "top"}
    ]

    assert client.put(endpoint, json=reviewer_change, headers=device_headers).status_code == 403
    copied_device_right = dict(device_headers)
    copied_device_right["X-BACH-Result-Operator"] = identity_api.device_token
    assert client.put(endpoint, json=reviewer_change, headers=copied_device_right).status_code == 403
    denied_readback = client.get(endpoint, headers=device_headers).json()
    assert denied_readback["configuration_version"] == initial["configuration_version"]
    assert denied_readback["policy"]["reviewers"] == []
    assert _config_rows(identity_api.path) == rows_before

    operator_headers = dict(device_headers)
    operator_headers["X-BACH-Result-Operator"] = identity_api.operator_token
    added = client.put(endpoint, json=reviewer_change, headers=operator_headers)
    assert added.status_code == 200
    assert added.json()["worker_started"] is False

    # A device can still change ordinary global settings while the reviewer
    # grant remains byte-for-byte unchanged.
    after_grant = client.get(endpoint, headers=device_headers).json()
    ordinary_change = _global_payload(after_grant)
    ordinary_change["selection"]["normal_task_order"] = "oldest_first"
    ordinary = client.put(endpoint, json=ordinary_change, headers=device_headers)
    assert ordinary.status_code == 200
    after_ordinary = client.get(endpoint, headers=device_headers).json()
    assert after_ordinary["policy"]["reviewers"] == reviewer_change["policy"]["reviewers"]
    assert after_ordinary["selection"]["normal_task_order"] == "oldest_first"
    rows_before_tier_change = _config_rows(identity_api.path)

    tier_change = _global_payload(after_ordinary)
    tier_change["policy"]["reviewers"] = [
        {"reviewer_id": "principal:reviewer-a", "tier": "standard"},
        {"reviewer_id": "principal:reviewer-b", "tier": "top"},
    ]
    assert client.put(endpoint, json=tier_change, headers=device_headers).status_code == 403
    assert client.put(endpoint, json=tier_change, headers=copied_device_right).status_code == 403
    after_denied_tier_change = client.get(endpoint, headers=device_headers).json()
    assert after_denied_tier_change["configuration_version"] == after_ordinary[
        "configuration_version"
    ]
    assert after_denied_tier_change["policy"]["reviewers"] == reviewer_change[
        "policy"
    ]["reviewers"]
    assert _config_rows(identity_api.path) == rows_before_tier_change

    changed_tier = client.put(endpoint, json=tier_change, headers=operator_headers)
    assert changed_tier.status_code == 200
    assert changed_tier.json()["worker_started"] is False
    final = client.get(endpoint, headers=device_headers).json()
    assert final["policy"]["reviewers"] == tier_change["policy"]["reviewers"]

    conn = _open_db(identity_api.path)
    try:
        assert revoke_device(identity_api.operator_name, connection=conn) is True
    finally:
        conn.close()
    revoked_operator_change = _global_payload(final)
    revoked_operator_change["policy"]["reviewers"].append(
        {"reviewer_id": "principal:reviewer-c", "tier": "standard"}
    )
    assert client.put(
        endpoint, json=revoked_operator_change, headers=operator_headers
    ).status_code == 403
    after_revoked_attempt = client.get(endpoint, headers=device_headers).json()
    assert after_revoked_attempt["configuration_version"] == final[
        "configuration_version"
    ]
    assert after_revoked_attempt["policy"]["reviewers"] == final["policy"]["reviewers"]
