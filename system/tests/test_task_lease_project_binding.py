# SPDX-License-Identifier: MIT
"""Project bindings stay local even when the lease client uses HTTP."""
import urllib.error

import pytest

from hub._services import task_lease_client as module
from system.tests.test_task_lease_client import _insert_task, mem_db


OPERATIONS = ("renew", "release", "update", "decompose", "submit_result")


def invoke(client, operation, binding):
    kwargs = dict(
        lease_id="00000000-0000-4000-8000-000000000001",
        fence=1, task_version="a" * 64, _project_binding=binding,
    )
    if operation == "update":
        kwargs["changes"] = {"title": "Updated task"}
    elif operation == "decompose":
        kwargs["subtasks"] = [{"title": "Child task"}]
    elif operation == "submit_result":
        kwargs.update(generation="test-generation", result="Concrete test result")
    return getattr(client, operation)(1, **kwargs)


@pytest.fixture(autouse=True)
def isolated_role(monkeypatch):
    monkeypatch.setattr(module, "get_lead_config", lambda: {"mode": "isolated"})


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("binding", ["private-project-binding-canary", object()], ids=["text", "opaque"])
def test_remote_project_binding_is_rejected_before_serialization_or_transport(monkeypatch, operation, binding):
    requests = []

    def transport(request, **kwargs):
        requests.append(request.data)
        raise urllib.error.URLError("Synthetic transport; no network access")

    monkeypatch.setattr(module.urllib.request, "urlopen", transport)
    client = module.TaskLeaseClient(lead_url="https://lead.invalid", device_token="test-token")
    with pytest.raises(module.LeaseProtocolError):
        invoke(client, operation, binding)
    assert requests == []


@pytest.mark.parametrize("operation", OPERATIONS)
def test_none_project_binding_keeps_existing_wire_payload(monkeypatch, operation):
    payloads = []

    class TransportReached(Exception):
        pass

    def transport(method, path, payload, headers=None):
        payloads.append(payload)
        raise TransportReached

    client = module.TaskLeaseClient(lead_url="https://lead.invalid", device_token="test-token")
    monkeypatch.setattr(client, "_http_request", transport)
    with pytest.raises(TransportReached):
        invoke(client, operation, None)
    assert len(payloads) == 1 and "_project_binding" not in payloads[0]


def test_local_project_binding_remains_accepted(mem_db):
    task_id = _insert_task(mem_db)
    client = module.TaskLeaseClient(conn=mem_db)
    ack = client.acquire(task_id, worker_id="worker@HOST", host="HOST")
    renewed = client.renew(
        task_id, lease_id=ack.lease_id, fence=ack.fence,
        task_version=ack.task_version, _project_binding=object(),
    )
    assert renewed.lease_id == ack.lease_id and renewed.fence == ack.fence
