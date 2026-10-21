# SPDX-License-Identifier: MIT
"""Remote SDK/CLI protocol checks; no provider or live BACH calls."""
import base64
import hashlib
import io
import json
import os
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from hub._services.worker_external_client import (
    ExternalResultError,
    WorkerExternalResultClient,
)
from tools import worker_external_results as cli


def client():
    return WorkerExternalResultClient(lead_url="http://127.0.0.1:8081", device_token="device-fixture",
                                      operator_token="operator-fixture")


class Opener:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def open(self, request, **kwargs):
        self.calls.append(request)
        return io.BytesIO(json.dumps(self.response).encode())


@pytest.mark.parametrize("url", ["file:///tmp/db", "https://user:pass@example.org", "http://host/path",
                                 "http://host?token=secret", "http://host#x", "http://host:0", "",
                                 "http://93.184.216.34", "http://192.168.1.1", "http://100.119.69.90"])
def test_fixed_remote_lead_only(url):
    with pytest.raises(ValueError):
        WorkerExternalResultClient(lead_url=url, device_token="x", operator_token="y")


@pytest.mark.parametrize("url", ["https://example.org", "http://100.119.69.90:8000", "http://localhost:8000",
                                 "http://[fd7a:115c:a1e0::1]:8000"])
def test_https_and_local_or_tailnet_addresses_are_explicitly_supported(url):
    assert WorkerExternalResultClient(lead_url=url, device_token="x", operator_token="y",
                                      trusted_tailnet_http=True)


def test_remote_sdk_upload_hashes_and_checks_real_bytes():
    sdk = client()
    data = b"real fixture bytes"
    opener = Opener({"schema": "bach.worker-external-artifact.v1", "artifact_id": "a" * 32,
        "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data), "media_type": "text/plain"})
    sdk._opener = opener
    assert sdk.store_artifact(data, media_type="text/plain")["size_bytes"] == len(data)
    request = opener.calls[0]
    assert request.get_header("X-bach-result-operator") == "operator-fixture"
    assert request.get_header("Authorization") == "Bearer device-fixture"
    assert base64.b64decode(json.loads(request.data)["content_base64"]) == data
    opener.response["sha256"] = "0" * 64
    with pytest.raises(ExternalResultError):
        sdk.store_artifact(data, media_type="text/plain")


def test_remote_sdk_download_checks_digest_and_does_not_expose_wire_encoding():
    sdk = client()
    data = b"private download fixture"
    opener = Opener({"schema": "bach.worker-external-artifact.v1", "artifact_id": "b" * 32,
        "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data),
        "content_base64": base64.b64encode(data).decode()})
    sdk._opener = opener
    result = sdk.read_artifact("b" * 32)
    assert result["content"] == data and "content_base64" not in result
    opener.response["artifact_id"] = "c" * 32
    with pytest.raises(ExternalResultError):
        sdk.read_artifact("b" * 32)


def test_redirect_does_not_forward_operator_credentials():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/must-not-follow")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        sdk = WorkerExternalResultClient(lead_url=f"http://127.0.0.1:{server.server_port}",
                                         device_token="x", operator_token="y")
        with pytest.raises(ExternalResultError) as failure:
            sdk.read_sources()
        assert failure.value.status == 302
        assert calls == ["/api/system/worker-external-principals"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_no_retry_fallback_or_private_server_error_echo():
    sdk = client()
    calls = []

    class Failed:
        def open(self, request, **kwargs):
            calls.append(request)
            raise urllib.error.HTTPError(request.full_url, 503, "private server details", {},
                                          io.BytesIO(b"private input or credentials"))

    sdk._opener = Failed()
    with pytest.raises(ExternalResultError) as failure:
        sdk.write_sources({"configuration_version": "fixture", "principals": []})
    assert len(calls) == 1
    assert "private" not in str(failure.value)
    assert "127.0.0.1" not in str(failure.value)


def _attestation_ack():
    return {"schema": "bach.worker-external-attestation-ack.v1", "task_id": 7,
            "attested_result_id": 9, "created": True, "readback": {
                "schema": "bach.task-result-readback.v1", "task_id": 7, "status": "review", "verified": True,
                "result": {"result_id": 9, "result_sha256": "b" * 64,
                           "source_kind": "external_attested", "accepted": False,
                           "result_revision": "a" * 64,
                           "scope": {"availability": "available", "result_revision": "a" * 64},
                           "external_provenance": {"availability": "available", "result_revision": "a" * 64}}}}


def test_attestation_ack_requires_public_verified_current_result():
    sdk = client()
    sdk._opener = Opener(_attestation_ack())
    assert sdk.attest(7, {"result_id": 9, "result_sha256": "b" * 64})["created"] is True


@pytest.mark.parametrize("change", ["task", "result", "created", "readback", "nested-result",
                                    "nested-sha", "source", "accepted", "verified", "status",
                                    "scope", "provenance", "revision", "scope-revision",
                                    "boolean-task", "boolean-result"])
def test_attestation_ack_must_bind_requested_result(change):
    sdk = client()
    ack = _attestation_ack()
    if change == "task":
        ack["task_id"] = 8
    elif change == "result":
        ack["attested_result_id"] = 10
    elif change == "created":
        ack["created"] = "true"
    elif change == "readback":
        ack["readback"] = {"task_id": 8}
    elif change == "nested-result":
        ack["readback"]["result"]["result_id"] = 8
    elif change == "nested-sha":
        ack["readback"]["result"]["result_sha256"] = "c" * 64
    elif change == "source":
        ack["readback"]["result"]["source_kind"] = "native"
    elif change == "accepted":
        ack["readback"]["result"]["accepted"] = True
    elif change == "verified":
        ack["readback"]["verified"] = False
    elif change == "status":
        ack["readback"]["status"] = "done"
    elif change == "scope":
        ack["readback"]["result"]["scope"]["availability"] = "unavailable"
    elif change == "provenance":
        ack["readback"]["result"]["external_provenance"]["availability"] = "unavailable"
    elif change == "revision":
        ack["readback"]["result"]["result_revision"] = None
    elif change == "scope-revision":
        ack["readback"]["result"]["scope"]["result_revision"] = "c" * 64
    elif change == "boolean-task":
        ack["task_id"] = True
    else:
        ack["readback"]["result"]["result_id"] = True
    sdk._opener = Opener(ack)
    with pytest.raises(ExternalResultError):
        sdk.attest(7, {"result_id": 9, "result_sha256": "b" * 64})


@pytest.mark.parametrize("field", ["task_id", "attested_result_id", "nested-task", "nested-result"])
def test_attestation_ack_rejects_boolean_one_ids(field):
    sdk = client()
    ack = _attestation_ack()
    ack.update(task_id=1, attested_result_id=1)
    ack["readback"]["task_id"] = 1
    ack["readback"]["result"]["result_id"] = 1
    if field == "nested-task":
        ack["readback"]["task_id"] = True
    elif field == "nested-result":
        ack["readback"]["result"]["result_id"] = True
    else:
        ack[field] = True
    sdk._opener = Opener(ack)
    with pytest.raises(ExternalResultError):
        sdk.attest(1, {"result_id": 1, "result_sha256": "b" * 64})


@pytest.mark.parametrize("field", ["target_task_id", "target_result_id"])
def test_review_ack_rejects_boolean_one_ids(field):
    sdk = client()
    ack = {"schema": "bach.worker-external-review-ack.v1", "worker_started": False, "accepted": False,
           "review": {"target_task_id": 1, "target_result_id": 1, "target_revision": "a" * 64}}
    ack["review"][field] = True
    sdk._opener = Opener(ack)
    with pytest.raises(ExternalResultError):
        sdk.prepare_review(1, {"result_id": 1, "result_revision": "a" * 64})


@pytest.mark.parametrize("change", ["started", "accepted", "task", "result", "revision"])
def test_review_ack_cannot_change_target_or_claim_acceptance(change):
    sdk = client()
    ack = {"schema": "bach.worker-external-review-ack.v1", "worker_started": False, "accepted": False,
           "review": {"target_task_id": 7, "target_result_id": 9, "target_revision": "a" * 64}}
    if change == "started":
        ack["worker_started"] = True
    elif change == "accepted":
        ack["accepted"] = True
    else:
        field = {"task": "target_task_id", "result": "target_result_id", "revision": "target_revision"}[change]
        ack["review"][field] = "changed"
    sdk._opener = Opener(ack)
    with pytest.raises(ExternalResultError):
        sdk.prepare_review(7, {"result_id": 9, "result_revision": "a" * 64})


def test_cli_artifact_read_creates_private_new_file_and_never_overwrites(tmp_path, monkeypatch, capsys):
    class FixtureClient:
        def __init__(self, **kwargs):
            pass

        def read_artifact(self, artifact_id):
            return {"schema": "fixture", "content": b"private bytes"}

    monkeypatch.setattr(cli, "WorkerExternalResultClient", FixtureClient)
    output = tmp_path / "private.txt"
    args = ["--lead-url", "http://127.0.0.1", "artifact-read", "a" * 32, "--output", str(output)]
    assert cli.main(args) == 0
    assert output.read_bytes() == b"private bytes"
    assert "private bytes" not in capsys.readouterr().out
    assert cli.main(args) == 1
    assert output.read_bytes() == b"private bytes"


@pytest.mark.skipif(os.name != "nt", reason="NTFS DACL contract")
def test_windows_output_has_protected_owner_system_dacl_from_creation(tmp_path):
    import ctypes
    from ctypes import wintypes
    output = tmp_path / "private-artifact.txt"
    fd = cli._private_output(output)
    with os.fdopen(fd, "wb") as handle:
        handle.write(b"private test artifact")
    assert output.read_bytes() == b"private test artifact"
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    get_security = advapi.GetNamedSecurityInfoW
    get_security.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.LPVOID)]
    get_security.restype = wintypes.DWORD
    convert = advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW
    convert.argtypes = [wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                       ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(wintypes.DWORD)]
    convert.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [wintypes.LPVOID]
    descriptor, dacl = wintypes.LPVOID(), wintypes.LPVOID()
    assert get_security(str(output), 1, 4, None, None, ctypes.byref(dacl), None, ctypes.byref(descriptor)) == 0
    text = wintypes.LPWSTR()
    try:
        assert convert(descriptor, 1, 4, ctypes.byref(text), None)
        assert text.value == "D:P(A;;FA;;;SY)(A;;FA;;;OW)"
    finally:
        if text:
            kernel.LocalFree(text)
        kernel.LocalFree(descriptor)
