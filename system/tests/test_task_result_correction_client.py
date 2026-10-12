"""Remote client validation for result correction and lease-bound context."""
import hashlib
import uuid
from copy import deepcopy

import pytest

from hub._services.task_lease_client import LeaseProtocolError, TaskLeaseClient


def test_correction_post_keeps_operator_in_header_and_never_retries(monkeypatch):
    client = TaskLeaseClient(lead_url="https://lead.example", device_token="fixture-device")
    payload = {
        "result_id": 59,
        "result_sha256": "a" * 64,
        "generation": "generation-1",
        "fence": 7,
        "task_version": "b" * 64,
        "status_revision": 145,
        "request_id": str(uuid.uuid4()),
        "correction_note": "Belege ergänzen.",
    }
    token = "private-operator-fixture"
    calls = []
    response = {
        "schema": "bach.task-result-correction-request.v1",
        "request_id": payload["request_id"],
        "task_id": 42001,
        "correction_id": 8,
        "correction_round": 2,
        "source_result_id": payload["result_id"],
        "source_result_sha256": payload["result_sha256"],
        "status": "pending",
        "next_task_version": "c" * 64,
        "replayed": False,
    }

    def request(method, path, payload=None, headers=None):
        calls.append((method, path, payload, headers))
        return 200, response

    monkeypatch.setattr(client, "_http_request", request)
    assert client.request_result_correction(42001, payload, operator_token=token) == response
    assert len(calls) == 1
    method, path, body, headers = calls[0]
    assert method == "POST" and path == "/api/tasks/42001/result/correction"
    assert body == payload
    assert headers == {"X-BACH-Result-Operator": token}
    assert token not in path


def test_remote_context_uses_lease_header_and_validates_source_hash(monkeypatch):
    client = TaskLeaseClient(lead_url="https://lead.example", device_token="fixture-device")
    text = "Untrusted alter Ergebnis mit Umlaut: nötig."
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    lease_id = "00000000-0000-4000-8000-000000000001"
    response = {
        "schema": "bach.task-result-correction-context.v1",
        "task_id": 42001,
        "fence": 7,
        "generation": "generation-2",
        "task_version": "c" * 64,
        "correction": {
            "correction_id": 8,
            "correction_round": 2,
            "correction_note": "Belege ergänzen.",
            "source_result": {
                "result_id": 59,
                "result_sha256": digest,
                "text": text,
                "generation": "generation-1",
                "fence": 6,
                "task_version": "b" * 64,
            },
        },
    }
    calls = []

    def request(method, path, payload=None, headers=None):
        calls.append((method, path, payload, headers))
        return 200, response

    monkeypatch.setattr(client, "_http_request", request)
    result = client.task_correction_context(
        42001, lease_id=lease_id, fence=7, task_version="c" * 64, generation="generation-2"
    )
    assert result == response
    assert len(calls) == 1
    method, path, payload, headers = calls[0]
    assert method == "GET" and payload is None
    assert path.startswith("/api/tasks/42001/lease/correction-context?")
    assert "lease_id" not in path and lease_id not in path
    assert headers == {"X-Lease-Id": lease_id}

    response["correction"]["source_result"]["result_sha256"] = "0" * 64
    try:
        client.task_correction_context(
            42001, lease_id=lease_id, fence=7, task_version="c" * 64, generation="generation-2"
        )
    except Exception as exc:
        assert exc.__class__.__name__ == "LeaseProtocolError"
    else:
        raise AssertionError("Ungültiger historischer SHA wurde akzeptiert")


def test_task_capability_readback_is_explicit_and_fail_closed(monkeypatch):
    from hub._services.task_lease_client import LeaseProtocolError

    client = TaskLeaseClient(lead_url="https://lead.example", device_token="fixture-device")
    response = {
        "schema": "bach.task-capabilities.v1",
        "result_max_chars": {
            "supported": True,
            "min": 1,
            "max": 3000,
            "nullable": True,
        },
    }
    calls = []

    def request(method, path, payload=None, headers=None):
        calls.append((method, path, payload, headers))
        return 200, response

    monkeypatch.setattr(client, "_http_request", request)
    assert client.task_capabilities() == response
    assert calls == [("GET", "/api/task-capabilities", None, None)]

    response["result_max_chars"]["supported"] = False
    try:
        client.task_capabilities()
    except LeaseProtocolError:
        pass
    else:
        raise AssertionError("Nicht unterstützte Task-Capability wurde als verfügbar akzeptiert")

    def old_backend(method, path, payload=None, headers=None):
        return 404, {"detail": "not found"}

    monkeypatch.setattr(client, "_http_request", old_backend)
    try:
        client.task_capabilities()
    except LeaseProtocolError:
        pass
    else:
        raise AssertionError("Altes Backend wurde still als output-limit-fähig behandelt")


@pytest.mark.parametrize("malformed", [[], "bad-correction", 7])
def test_remote_correction_context_rejects_non_object_payload(monkeypatch, malformed):
    client = TaskLeaseClient(lead_url="https://lead.example", device_token="fixture-device")
    response = {
        "schema": "bach.task-result-correction-context.v1",
        "task_id": 42001,
        "fence": 7,
        "generation": "generation-2",
        "task_version": "c" * 64,
        "correction": malformed,
    }
    monkeypatch.setattr(client, "_http_request", lambda *a, **k: (200, response))
    with pytest.raises(LeaseProtocolError, match="Korrekturquelle"):
        client.task_correction_context(
            42001, lease_id="00000000-0000-4000-8000-000000000001",
            fence=7, task_version="c" * 64, generation="generation-2"
        )


@pytest.mark.parametrize("case", ["underfilled", "wrong-cursor"])
def test_remote_history_rejects_inconsistent_more_page(monkeypatch, case):
    from system.tests.test_task_result_correction_api import RESULT_HISTORY_V1_FIXTURE

    client = TaskLeaseClient(lead_url="https://lead.example", device_token="fixture-device")
    response = deepcopy(RESULT_HISTORY_V1_FIXTURE)
    response["has_more"] = True
    if case == "underfilled":
        limit = 3
        response["next_before_event_id"] = response["events"][-1]["event_id"]
    else:
        limit = 2
        response["next_before_event_id"] = response["events"][-1]["event_id"] + 1
    monkeypatch.setattr(client, "_http_request", lambda *a, **k: (200, response))
    with pytest.raises(LeaseProtocolError, match="cursor"):
        client.task_result_history(42001, limit=limit)
