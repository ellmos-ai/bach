# SPDX-License-Identifier: MIT
"""Operator API against temporary canonical DB fixtures, never the live host."""
import base64
import io
import sqlite3
import urllib.error
import urllib.parse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gui.device_auth import revoke_device
from hub._services import worker_result_review as review
from hub._services.worker_external_client import WorkerExternalResultClient
from hub._services.worker_external_evidence import MAX_ARTIFACT_BYTES

from system.tests.test_task_lease_client import mem_db as mem_db  # noqa: PLC0414
from system.tests.test_worker_execution_evidence import (
    worker_context as worker_context,  # noqa: PLC0414
)
from system.tests.test_worker_external_attestation import (
    external_world as external_world,  # noqa: PLC0414
)
from system.tests.test_worker_external_result_integration import (
    integrated as integrated,  # noqa: PLC0414
)
from system.tests.test_worker_external_result_integration import (
    target,
)


@pytest.fixture
def api(integrated, monkeypatch):
    from gui.api import unified_api, worker_policy
    from hub import bach_paths
    world = integrated
    monkeypatch.setattr(bach_paths, "BACH_DB", world["path"])
    monkeypatch.setattr(unified_api, "BACH_DB", world["path"])
    app = FastAPI()
    app.include_router(worker_policy.router)
    with TestClient(app) as client:
        yield client, world


def headers(world, *, ordinary=False):
    token = world["ordinary"] if ordinary else world["operator"]
    return {"Authorization": "Bearer " + token, "X-BACH-Result-Operator": token}


@pytest.mark.parametrize("method,path", [
    ("get", "/api/system/worker-model-principal-catalog"),
    ("get", "/api/system/worker-external-principals"),
    ("put", "/api/system/worker-external-principals"),
    ("post", "/api/system/worker-external-artifacts"),
    ("get", "/api/system/worker-external-artifacts/" + "0" * 32),
    ("post", "/api/tasks/1/result/external-attestation"),
    ("post", "/api/tasks/1/result/external-review"),
])
def test_private_endpoints_require_device_and_separate_operator(api, method, path):
    client, world = api
    assert client.request(method, path).status_code == 401
    denied = client.request(method, path, headers=headers(world, ordinary=True), content=b"not-json")
    assert denied.status_code == 403
    assert denied.headers["cache-control"] == "no-store"


def test_catalog_and_sources_are_private_and_cas_bound(api):
    client, world = api
    auth = headers(world)
    path = "/api/system/worker-external-principals"
    snapshot = client.get(path, headers=auth)
    assert snapshot.status_code == 200
    assert snapshot.headers["cache-control"] == "no-store"
    body = snapshot.json()
    payload = {key: body[key] for key in ("configuration_version", "principals")}
    assert client.put(path, headers=auth, json=payload).status_code == 200
    assert client.put(path, headers=auth, json=payload).status_code == 409
    catalog = client.get("/api/system/worker-model-principal-catalog", headers=auth).json()
    assert catalog["schema"] == "bach.worker-model-principal-catalog.v1"
    update = {"configuration_version": catalog["configuration_version"],
              "principal_ids": catalog["explicit_principal_ids"]}
    assert client.put("/api/system/worker-model-principal-catalog", headers=auth, json=update).status_code == 200


@pytest.mark.parametrize("raw,status", [
    (b'{"media_type":"text/plain","content_base64":"YQ==","extra":1}', 400),
    (b'{"media_type":"text/plain","content_base64":"YQ==","media_type":"text/plain"}', 400),
    (b'{"media_type":"text/plain","content_base64":"YR=="}', 400),
    (b'{"media_type":"text/plain","content_base64":NaN}', 400),
    (b'{"media_type":"text/plain","content_base64":"?"}', 400),
    (b'[1]', 400),
])
def test_invalid_private_payload_is_rejected_without_echo(api, raw, status):
    client, world = api
    response = client.post("/api/system/worker-external-artifacts", headers={
        **headers(world), "Content-Type": "application/json"}, content=raw)
    assert response.status_code == status
    assert b"content_base64" not in response.content


def test_artifact_real_bytes_roundtrip_and_cap(api):
    client, world = api
    auth = headers(world)
    path = "/api/system/worker-external-artifacts"
    content = b"private real bytes\x00\xff"
    payload = {"media_type": "text/plain", "content_base64": base64.b64encode(content).decode()}
    stored = client.post(path, headers=auth, json=payload)
    assert stored.status_code == 200
    metadata = stored.json()
    assert "content_base64" not in metadata
    private = client.get(path + "/" + metadata["artifact_id"], headers=auth)
    assert private.headers["cache-control"] == "no-store"
    assert base64.b64decode(private.json()["content_base64"]) == content
    payload["content_base64"] = base64.b64encode(b"x" * (MAX_ARTIFACT_BYTES + 1)).decode()
    assert client.post(path, headers=auth, json=payload).status_code == 400
    assert client.post(path, headers={**auth, "Content-Length": "3145729",
        "Content-Type": "application/json"}, content=b"{}").status_code == 413
    assert client.post(path, headers=auth, content=b"{}").status_code == 415


def test_operator_revocation_blocks_private_reads_with_another_active_device(api):
    client, world = api
    assert revoke_device("external-operator-fixture", connection=world["conn"])
    response = client.get("/api/system/worker-external-principals", headers={
        "Authorization": "Bearer " + world["ordinary"], "X-BACH-Result-Operator": world["operator"]})
    assert response.status_code == 403


@pytest.mark.parametrize("external_world", [{"review_models": True}], indirect=True)
def test_attestation_ack_is_public_and_review_requires_exact_selected_revision(api):
    client, world = api
    auth = headers(world)
    path = f"/api/tasks/{world['task_id']}/result/"
    response = client.post(path + "external-attestation", headers=auth, json=world["request"])
    assert response.status_code == 200, response.text
    ack = response.json()
    assert ack["schema"] == "bach.worker-external-attestation-ack.v1"
    assert ack["readback"]["result"]["source_kind"] == "external_attested"
    for private in ("source_artifact_ids", "result_artifact_id", "account_id", "tenant_id", "run_id", "turn_id"):
        assert private not in response.text
    record = target(world)
    payload = {key: record[key] for key in (
        "task_id", "result_id", "result_sha256", "result_revision", "task_version", "status_revision")}
    stale = {**payload, "result_revision": "0" * 64}
    assert client.post(path + "external-review", headers=auth, json=stale).status_code == 409
    assert client.post(path + "external-review", headers=auth, json={}).status_code == 400
    result = client.post(path + "external-review", headers=auth, json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["worker_started"] is False
    assert result.json()["accepted"] is False
    assert result.json()["review"]["target_revision"] == payload["result_revision"]
    replay = client.post(path + "external-review", headers=auth, json=payload)
    assert replay.json()["review"]["review_task_id"] == result.json()["review"]["review_task_id"]


@pytest.mark.parametrize("external_world", [{"review_models": True}], indirect=True)
def test_public_review_adapter_rechecks_db_after_observed_revision(api, monkeypatch):
    client, world = api
    auth = headers(world)
    path = f"/api/tasks/{world['task_id']}/result/"
    assert client.post(path + "external-attestation", headers=auth, json=world["request"]).status_code == 200
    record = target(world)
    payload = {key: record[key] for key in (
        "task_id", "result_id", "result_sha256", "result_revision", "task_version", "status_revision")}
    original = review._prepare_target_review

    def race(conn, target_record, authority, **kwargs):
        conn.execute("UPDATE tasks SET claim_id='foreign-race' WHERE id=?", (world["task_id"],))
        conn.commit()
        return original(conn, target_record, authority, **kwargs)

    monkeypatch.setattr(review, "_prepare_target_review", race)
    assert client.post(path + "external-review", headers=auth, json=payload).status_code == 409


@pytest.mark.parametrize("external_world", [{"review_models": True}], indirect=True)
def test_remote_sdk_ack_validation_matches_real_api_readback(api):
    client, world = api

    class Bridge:
        def open(self, request, **kwargs):
            response = client.request(request.method, urllib.parse.urlsplit(request.full_url).path,
                                      headers=dict(request.header_items()), content=request.data)
            if response.status_code >= 400:
                raise urllib.error.HTTPError(request.full_url, response.status_code, "fixture", {},
                                              io.BytesIO(response.content))
            return io.BytesIO(response.content)

    sdk = WorkerExternalResultClient(lead_url="http://127.0.0.1", device_token=world["operator"],
                                      operator_token=world["operator"])
    sdk._opener = Bridge()
    assert sdk.read_sources()["schema"] == "bach.worker-external-principals.v1"
    ack = sdk.attest(world["task_id"], world["request"])
    assert ack["created"] is True
    record = ack["readback"]["result"]
    payload = {key: record[key] for key in (
        "task_id", "result_id", "result_sha256", "result_revision", "task_version", "status_revision")}
    assert sdk.prepare_review(world["task_id"], payload)["accepted"] is False


def test_private_operator_routes_through_actual_gui_auth_middleware(integrated, monkeypatch):
    from hub import bach_paths
    from gui import device_auth
    world = integrated
    monkeypatch.setattr(bach_paths, "BACH_DB", world["path"])
    from gui import server
    from gui.api import unified_api
    monkeypatch.setattr(server, "BACH_DB", world["path"])
    monkeypatch.setattr(unified_api, "BACH_DB", world["path"])

    def connect():
        conn = sqlite3.connect(world["path"])
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(device_auth, "GET_CONNECTION", connect)
    with TestClient(server.app) as client:
        for path in ["/api/system/worker-model-principal-catalog", "/api/system/worker-external-principals"]:
            assert client.get(path).status_code == 401
            assert client.get(path, headers={"Authorization": "Bearer invalid-device"}).status_code in {401, 403}
            assert client.get(path, headers={"Authorization": "Bearer " + world["ordinary"]}).status_code == 403
            response = client.get(path, headers=headers(world))
            assert response.status_code == 200, response.text
            assert "no-store" in {part.strip() for part in response.headers["cache-control"].split(",")}
