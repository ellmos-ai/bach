"""Remote client validation for result correction and lease-bound context."""
import hashlib
import json
import threading
import uuid
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from hub._services.task_lease_client import (
    LeaseConnectionError, LeaseProtocolError, TaskLeaseClient, TaskResultOperationError,
    TaskResultServiceClient,
)


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


class _ServiceErrorHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.seen.append((self.path, {key.casefold(): value for key, value in self.headers.items()}))
        status, payload = self.server.responses.get(self.path, (503, {"detail": {"code": "other", "message": "unavailable"}}))
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.do_GET()

    def log_message(self, *_args):
        return


def test_result_service_uses_real_http_error_parser_and_exact_503_allowlist(monkeypatch):
    monkeypatch.setenv("BACH_DEVICE_TOKEN", "ambient-device-fixture")
    service_token = "S" * 43
    server = HTTPServer(("127.0.0.1", 0), _ServiceErrorHandler)
    server.seen = []
    server.responses = {
        "/api/tasks/77/result": (503, {"detail": {"code": "result_service_unavailable", "message": "Schema fehlt"}}),
        "/api/tasks/77/result/correction": (503, {"detail": {"code": "result_service_unavailable", "message": "Schema fehlt"}}),
        "/api/tasks/77/lease": (503, {"detail": {"code": "result_service_unavailable", "message": "Schema fehlt"}}),
        "/api/tasks/77/result/history": (503, {"detail": {"code": "wrong_code", "message": "Schema fehlt"}}),
    }
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = TaskResultServiceClient(
            service_token=service_token,
            lead_url=f"http://127.0.0.1:{server.server_port}",
        )
        assert client._device_token is None
        with pytest.raises(TaskResultOperationError) as read_error:
            client.task_result_snapshot(77)
        assert read_error.value.code == "result_service_unavailable"

        with pytest.raises(TaskResultOperationError) as write_error:
            client._service_http(
                "POST", "/api/tasks/77/result/correction", payload={"request_id": "fixture"}, revision=4
            )
        assert write_error.value.code == "result_service_unavailable"

        with pytest.raises(LeaseConnectionError):
            client._http_service_request("GET", "/api/tasks/77/lease", headers=client._service_headers())
        with pytest.raises(LeaseConnectionError):
            client.task_result_history(77)
        assert len(server.seen) == 4
        for path, headers in server.seen:
            assert headers.get("x-bach-result-service") == service_token
            assert "authorization" not in headers and "cookie" not in headers
        assert server.seen[1][1].get("x-bach-result-service-revision") == "4"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_service_client_blocks_inherited_general_task_api_and_device_identity(monkeypatch):
    from hub._services import task_lease_client as client_module

    monkeypatch.setenv("BACH_DEVICE_TOKEN", "ambient-device-fixture")
    client = TaskResultServiceClient(
        service_token="S" * 43,
        lead_url="https://lead.example",
    )
    assert client._device_token is None
    transport_calls = []
    monkeypatch.setattr(
        client_module.urllib.request,
        "urlopen",
        lambda *args, **kwargs: transport_calls.append((args, kwargs)),
    )

    calls = [
        lambda: client.task_snapshot(77),
        lambda: client.task_capabilities(),
        lambda: client.task_candidates(),
        lambda: client.task_correction_context(
            77, lease_id="00000000-0000-4000-8000-000000000001",
            fence=1, task_version="a" * 64, generation="generation-1",
        ),
        lambda: client.renew(
            77, lease_id="00000000-0000-4000-8000-000000000001",
            fence=1, task_version="a" * 64,
        ),
        lambda: client.update(
            77, lease_id="00000000-0000-4000-8000-000000000001",
            fence=1, task_version="a" * 64, changes={"title": "blocked"},
        ),
        lambda: client.tool_trace_events(77),
    ]
    for call in calls:
        with pytest.raises(LeaseProtocolError, match="allgemeine Task-API"):
            call()
    assert transport_calls == []

    # The private native creator path bypasses _call in TaskLeaseClient. A
    # service client must deny it before opening a local TaskDB connection.
    local_db_calls = []
    local_client = TaskResultServiceClient(service_token="S" * 43, conn=object())
    local_client._mode = "local"
    monkeypatch.setattr(
        local_client, "_get_local_connection",
        lambda: local_db_calls.append("connection"),
    )
    monkeypatch.setattr(
        client_module, "_acquire_native_creator_lease",
        lambda *args, **kwargs: local_db_calls.append("creator"),
    )
    with pytest.raises(LeaseProtocolError, match="allgemeine Task-API"):
        local_client._acquire_native_creator(
            77, delegation=object(), worker_id="fixture-worker@HOST",
            host="HOST", task_version="a" * 64,
        )
    assert local_db_calls == []

    with pytest.raises(LeaseProtocolError, match="keine Geräteanmeldung"):
        TaskResultServiceClient(
            service_token="S" * 43,
            device_token="explicit-device-fixture",
            lead_url="https://lead.example",
        )
