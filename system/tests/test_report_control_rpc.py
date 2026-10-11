"""Control report transport and lifecycle regressions; no model/network calls."""
import asyncio
import io
import threading

import pytest

from hub._services.document.report_control_rpc import (
    MAX_REPORT_BODY_BYTES,
    ControlReportOwner,
    ReportControlRequestError,
    is_report_control_path,
    parse_report_control_request,
    read_report_json,
)


def unavailable(operation, payload):
    return {"status": "unavailable", "operation": operation}


@pytest.mark.parametrize("method,path,payload,operation,expected", [
    ("GET", "/api/reports/capabilities", None, "capabilities", {}),
    ("GET", "/api/reports/sources?subject_ref=sub_abc", None,
     "sources", {"subject_ref": "sub_abc"}),
    ("GET", "/api/reports/status?run_id=run_123", None,
     "status", {"run_id": "run_123"}),
    ("GET", "/api/reports/watcher/status", None, "watcher_status", {}),
    ("POST", "/api/reports/prepare", {"schema": "example"}, "prepare",
     {"schema": "example"}),
    ("POST", "/api/reports/finish", {"run_id": "r", "approval": {}},
     "finish", {"run_id": "r", "approval": {}}),
    ("POST", "/api/reports/cleanup", {"run_id": "r", "approval": {}},
     "cleanup", {"run_id": "r", "approval": {}}),
    ("POST", "/api/reports/watcher/configure", {"enabled": False},
     "watcher_configure", {"enabled": False}),
    ("POST", "/api/reports/watcher/tick", {}, "watcher_tick", {}),
])
def test_fixed_operation_transport(method, path, payload, operation, expected):
    assert parse_report_control_request(method, path, payload) == (operation, expected)


@pytest.mark.parametrize("method,path,payload,status", [
    ("GET", "/api/reports/sources", None, 422),
    ("GET", "/api/reports/sources?subject_ref=a&subject_ref=b", None, 422),
    ("GET", "/api/reports/sources?subject_ref=", None, 422),
    ("GET", "/api/reports/status?run_id=a&path=private", None, 422),
    ("GET", "/api/reports/capabilities?model=x", None, 422),
    ("GET", "/api/reports/watcher/status?all=true", None, 422),
    ("GET", "/api/reports/prepare", None, 404),
    ("POST", "/api/reports/finish?provider=x", {}, 422),
    ("POST", "/api/reports/finish", [], 422),
    ("POST", "/api/reports/finish", {1: "a"}, 422),
    ("POST", "/api/reports/execute-arbitrary", {}, 404),
    ("DELETE", "/api/reports/status", None, 405),
    ("GET", "https://other.example/api/reports/capabilities", None, 422),
])
def test_transport_rejects_unknown_and_ambiguous_inputs(method, path, payload, status):
    with pytest.raises(ReportControlRequestError) as exc:
        parse_report_control_request(method, path, payload)
    assert exc.value.status_code == status
    assert "private" not in str(exc.value)


@pytest.mark.parametrize("body", [
    b"[]", b"null", b'{"run_id":"a","run_id":"b"}',
    b'{"approval":{"x":1,"x":2}}', b'{"x":NaN}', b'{"x":Infinity}',
    b"{", b"\xff",
])
def test_json_reader_rejects_malformed_duplicate_and_nonfinite(body):
    with pytest.raises(ReportControlRequestError):
        read_report_json({"Content-Length": str(len(body))}, io.BytesIO(body))


def test_json_reader_is_bounded_before_read():
    class Unread:
        def read(self, _count):
            pytest.fail("invalid framing must be rejected before reading")
    for headers, status in [
        ({}, 411),
        ({"Content-Length": "-1"}, 411),
        ({"Content-Length": str(MAX_REPORT_BODY_BYTES + 1)}, 413),
        ({"Content-Length": "2", "Transfer-Encoding": "chunked"}, 400),
        ({"Content-Length": "0"}, 422),
    ]:
        with pytest.raises(ReportControlRequestError) as exc:
            read_report_json(headers, Unread())
        assert exc.value.status_code == status


def test_json_reader_and_path_detection():
    assert read_report_json({"Content-Length": "2"}, io.BytesIO(b"{}")) == {}
    assert is_report_control_path("/api/reports")
    assert is_report_control_path("/api/reports/status?run_id=r")
    assert not is_report_control_path("/api/reports-other")


def test_unconfigured_owner_has_no_loop_or_thread():
    owner = ControlReportOwner(None, unavailable)
    assert owner.start() is False
    assert owner.thread_alive is False
    assert owner.call("capabilities")["status"] == "unavailable"
    assert owner.close()


def test_owner_dispatch_and_orderly_close():
    seen = []
    class Host:
        async def dispatch(self, operation, payload):
            seen.append((asyncio.get_running_loop(), threading.current_thread().name))
            return {"status": "ok", "operation": operation}
    loops = []
    def factory(loop):
        assert asyncio.get_running_loop() is loop
        loops.append(loop)
        return Host()
    owner = ControlReportOwner(factory, unavailable)
    try:
        assert owner.start()
        assert owner.start()
        assert owner.call("capabilities") == {"status": "ok", "operation": "capabilities"}
        assert len(loops) == 1 and seen[0][0] is loops[0]
        assert seen[0][1] == "bach-report-control-owner"
    finally:
        assert owner.close()
    assert loops[0].is_closed()
    assert owner.call("capabilities")["status"] == "unavailable"
    assert owner.close()
    assert not owner.start()


def test_timeout_does_not_cancel_effect_and_close_drains_it():
    began = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    class Host:
        async def dispatch(self, _operation, _payload):
            began.set()
            while not release.is_set():
                await asyncio.sleep(0.01)
            completed.set()
            return {"status": "completed"}
        @staticmethod
        def _timeout_response(_operation, _payload, reason):
            return {"status": "unknown", "reason_code": reason}
    owner = ControlReportOwner(lambda _loop: Host(), unavailable)
    try:
        assert owner.start()
        result = owner.call("finish", {"run_id": "r"}, timeout=0.1)
        assert began.is_set()
        assert result == {"status": "unknown", "reason_code": "provider_effect_unknown"}
        assert not completed.is_set()
        assert owner.close(timeout=0.05) is False
        assert owner.call("finish", {})["status"] == "unavailable"
        release.set()
        assert owner.close(timeout=3) is True
        assert completed.is_set()
    finally:
        release.set()
        owner.close()


def test_initialization_failure_does_not_leave_thread():
    def factory(_loop):
        raise RuntimeError("private details must not escape")
    owner = ControlReportOwner(factory, unavailable)
    assert owner.start() is False
    assert owner.close()
    assert not owner.thread_alive
    assert owner.call("capabilities")["status"] == "unavailable"


def test_close_also_drains_children_spawned_after_shutdown_started():
    parent_release = threading.Event()
    child_started = threading.Event()
    child_release = threading.Event()
    child_completed = threading.Event()
    class Host:
        async def dispatch(self, _operation, _payload):
            while not parent_release.is_set():
                await asyncio.sleep(0.01)
            async def child():
                child_started.set()
                while not child_release.is_set():
                    await asyncio.sleep(0.01)
                child_completed.set()
            asyncio.create_task(child())
            return {"status": "completed"}
        @staticmethod
        def _timeout_response(_operation, _payload, reason):
            return {"status": "unknown", "reason_code": reason}
    owner = ControlReportOwner(lambda _loop: Host(), unavailable)
    try:
        assert owner.start()
        assert owner.call("finish", {}, timeout=0.1)["status"] == "unknown"
        assert owner.close(timeout=0.05) is False
        parent_release.set()
        assert child_started.wait(2)
        assert owner.close(timeout=0.1) is False
        assert not child_completed.is_set()
        child_release.set()
        assert owner.close(timeout=3)
        assert child_completed.is_set()
    finally:
        parent_release.set()
        child_release.set()
        owner.close()


def test_json_reader_rejects_excessive_nesting():
    raw = b'{"x":' + b"[" * 2000 + b"]" * 2000 + b"}"
    with pytest.raises(ReportControlRequestError) as exc:
        read_report_json({"Content-Length": str(len(raw))}, io.BytesIO(raw))
    assert exc.value.status_code == 422


@pytest.mark.parametrize("body", [b'{"x":1e999}', b'{"x":-1e999}', b'{"x":[1e999]}'])
def test_json_reader_rejects_numeric_overflow(body):
    with pytest.raises(ReportControlRequestError) as exc:
        read_report_json({"Content-Length": str(len(body))}, io.BytesIO(body))
    assert exc.value.status_code == 422


def test_json_reader_rejects_multiple_content_length_headers_before_read():
    from email.message import Message
    class Unread:
        def read(self, _count):
            pytest.fail("ambiguous framing must be rejected before reading")
    headers = Message()
    headers["Content-Length"] = "2"
    headers["Content-Length"] = "3"
    with pytest.raises(ReportControlRequestError) as exc:
        read_report_json(headers, Unread())
    assert exc.value.status_code == 411


def test_json_reader_rejects_even_empty_transfer_encoding_header():
    from email.message import Message
    headers = Message()
    headers["Content-Length"] = "2"
    headers["Transfer-Encoding"] = ""
    headers["Transfer-Encoding"] = "chunked"
    with pytest.raises(ReportControlRequestError) as exc:
        read_report_json(headers, io.BytesIO(b"{}"))
    assert exc.value.status_code == 400


def _actual_control_handler():
    """Execute the real affected handler methods without booting another runtime."""
    import ast
    import logging
    from pathlib import Path
    from types import SimpleNamespace
    from urllib.parse import urlparse
    source = (Path(__file__).parents[1] / "hub/_services/chat/telegram_chat.py").read_text()
    parsed = ast.parse(source)
    original = next(node for node in parsed.body
                    if isinstance(node, ast.ClassDef) and node.name == "ControlHandler")
    names = {"do_GET", "do_POST", "_report_control_response",
             "_allow_control_request", "_allow_json_post"}
    methods = [node for node in original.body
               if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in methods} == names
    selected = ast.ClassDef(name="ActualControlHandler", bases=[], keywords=[],
                            body=methods, decorator_list=[])
    module = ast.Module(body=[selected], type_ignores=[])
    namespace = {
        "urlparse": urlparse,
        "log": logging.getLogger("test-report-control"),
        "is_control_api_authorized": lambda headers: headers.get("Authorization") == "test-token",
        "_is_allowed_origin": lambda _origin, _host: False,
    }
    exec(compile(ast.fix_missing_locations(module), str(Path(__file__)), "exec"), namespace)
    calls = []
    class Owner:
        def call(self, operation, payload):
            calls.append((operation, payload))
            return {"status": "fixture", "operation": operation}
    handler = namespace["ActualControlHandler"]()
    handler.responses = []
    handler._json = lambda value, status=200: handler.responses.append((status, value))
    handler.server = SimpleNamespace(report_control_owner=Owner())
    return handler, calls


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/reports/sources?subject_ref=bad&path=private"),
    ("POST", "/api/reports/finish?provider=untrusted"),
])
def test_actual_control_auth_guard_precedes_report_validation_or_body(method, path):
    handler, calls = _actual_control_handler()
    class Unread:
        def read(self, _count):
            pytest.fail("unauthenticated input must not be read")
    handler.path = path
    handler.headers = {"Content-Type": "application/json", "Content-Length": "2"}
    handler.rfile = Unread()
    getattr(handler, "do_" + method)()
    assert handler.responses == [(401, {"error": "Control-API-Token erforderlich oder ungültig"})]
    assert calls == []


def test_actual_control_origin_guard_precedes_body():
    handler, calls = _actual_control_handler()
    class Unread:
        def read(self, _count):
            pytest.fail("foreign-origin input must not be read")
    handler.path = "/api/reports/finish"
    handler.headers = {"Authorization": "test-token", "Origin": "https://foreign.example",
                       "Host": "localhost", "Content-Type": "application/json",
                       "Content-Length": "2"}
    handler.rfile = Unread()
    handler.do_POST()
    assert handler.responses == [(403, {"error": "Fremd-Origin nicht erlaubt"})]
    assert calls == []


def test_actual_control_content_type_guard_precedes_body():
    handler, calls = _actual_control_handler()
    class Unread:
        def read(self, _count):
            pytest.fail("non-JSON input must not be read")
    handler.path = "/api/reports/prepare"
    handler.headers = {"Authorization": "test-token", "Content-Type": "text/plain",
                       "Content-Length": "2"}
    handler.rfile = Unread()
    handler.do_POST()
    assert handler.responses == [(415, {"error": "Content-Type application/json erforderlich"})]
    assert calls == []


@pytest.mark.parametrize("method,path,body,operation,payload", [
    ("GET", "/api/reports/capabilities", None, "capabilities", {}),
    ("GET", "/api/reports/status?run_id=r", None, "status", {"run_id": "r"}),
    ("GET", "/api/reports/sources?subject_ref=s", None, "sources", {"subject_ref": "s"}),
    ("GET", "/api/reports/watcher/status", None, "watcher_status", {}),
    ("POST", "/api/reports/prepare", b"{}", "prepare", {}),
    ("POST", "/api/reports/finish", b'{"run_id":"r","approval":{}}',
     "finish", {"run_id": "r", "approval": {}}),
    ("POST", "/api/reports/cleanup", b'{"run_id":"r","approval":{}}',
     "cleanup", {"run_id": "r", "approval": {}}),
    ("POST", "/api/reports/watcher/configure", b'{"enabled":false}',
     "watcher_configure", {"enabled": False}),
    ("POST", "/api/reports/watcher/tick", b"{}", "watcher_tick", {}),
])
def test_actual_control_methods_route_to_owned_service(method, path, body, operation, payload):
    handler, calls = _actual_control_handler()
    handler.path = path
    handler.headers = {"Authorization": "test-token", "Content-Type": "application/json",
                       "Content-Length": str(len(body or b""))}
    handler.rfile = io.BytesIO(body or b"")
    getattr(handler, "do_" + method)()
    assert calls == [(operation, payload)]
    assert handler.responses == [(200, {"status": "fixture", "operation": operation})]


def _network_control_handler():
    """Use actual Control HTTP methods and token/origin checks on an ephemeral server."""
    import ast
    import ipaddress
    import logging
    from http.server import BaseHTTPRequestHandler
    from pathlib import Path
    from typing import Optional
    from urllib.parse import urlparse
    from hub._services.chat.control_auth import is_control_api_authorized

    path = Path(__file__).parents[1] / "hub/_services/chat/telegram_chat.py"
    source = path.read_text()
    parsed = ast.parse(source)
    original = next(node for node in parsed.body
                    if isinstance(node, ast.ClassDef) and node.name == "ControlHandler")
    names = {"do_GET", "do_POST", "_report_control_response", "_json", "_cors",
             "_canonicalize_origin_for_header", "_allow_control_request", "_allow_json_post"}
    methods = [node for node in original.body
               if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in methods} == names
    origin = next(node for node in parsed.body
                  if isinstance(node, ast.FunctionDef) and node.name == "_is_allowed_origin")
    selected = ast.ClassDef(name="NetworkControlHandler",
                            bases=[ast.Name(id="BaseHTTPRequestHandler", ctx=ast.Load())],
                            keywords=[], body=methods, decorator_list=[])
    namespace = {"BaseHTTPRequestHandler": BaseHTTPRequestHandler, "urlparse": urlparse,
                 "json": __import__("json"), "ipaddress": ipaddress, "Optional": Optional,
                 "log": logging.getLogger("test-report-network-control"),
                 "is_control_api_authorized": is_control_api_authorized,
                 # Tested requests either match Host or fail before this hostname seam.
                 "_is_trusted_host": lambda host: host in {"localhost", "127.0.0.1", "::1"}}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[origin, selected], type_ignores=[])),
                 str(path), "exec"), namespace)
    handler = namespace["NetworkControlHandler"]
    handler.log_message = lambda *_args: None
    return handler


@pytest.fixture
def control_http(monkeypatch):
    from http.server import ThreadingHTTPServer
    from hub._services.chat.control_auth import CONTROL_API_TOKEN_ENV

    monkeypatch.setenv(CONTROL_API_TOKEN_ENV, "ephemeral-report-test-credential")
    calls = []
    class Host:
        async def dispatch(self, operation, payload):
            calls.append((operation, payload, threading.current_thread().name))
            return {"status": "fixture", "operation": operation}
    owner = ControlReportOwner(lambda _loop: Host(), unavailable)
    assert owner.start()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _network_control_handler())
    server.report_control_owner = owner
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01},
                              name="ephemeral-report-test-http", daemon=True)
    thread.start()
    try:
        yield server, calls
    finally:
        server.shutdown()
        thread.join(3)
        server.server_close()
        assert owner.close(timeout=3)
        assert not thread.is_alive()


def _http_report(server, method, path, body=None, headers=None):
    import http.client
    import json
    connection = http.client.HTTPConnection(*server.server_address, timeout=3)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


@pytest.mark.parametrize("method,path,body,operation", [
    ("GET", "/api/reports/capabilities", None, "capabilities"),
    ("GET", "/api/reports/sources?subject_ref=s", None, "sources"),
    ("GET", "/api/reports/status?run_id=r", None, "status"),
    ("GET", "/api/reports/watcher/status", None, "watcher_status"),
    ("POST", "/api/reports/prepare", b"{}", "prepare"),
    ("POST", "/api/reports/finish", b'{"run_id":"r","approval":{}}', "finish"),
    ("POST", "/api/reports/cleanup", b'{"run_id":"r","approval":{}}', "cleanup"),
    ("POST", "/api/reports/watcher/configure", b'{"enabled":false}', "watcher_configure"),
    ("POST", "/api/reports/watcher/tick", b"{}", "watcher_tick"),
])
def test_http_control_routes_execute_in_owned_loop(control_http, method, path, body, operation):
    server, calls = control_http
    status, payload = _http_report(server, method, path, body,
                                  {"Authorization": "Bearer ephemeral-report-test-credential",
                                   "Content-Type": "application/json"})
    assert (status, payload) == (200, {"status": "fixture", "operation": operation})
    assert len(calls) == 1 and calls[0][0] == operation
    assert calls[0][2] == "bach-report-control-owner"


@pytest.mark.parametrize("headers,body,status", [
    ({"Authorization": "Basic irrelevant", "Content-Type": "application/json",
      "Content-Length": "1000000000"}, None, 401),
    ({"Authorization": "Bearer ephemeral-report-test-credential",
      "Origin": "ftp://foreign.example", "Content-Type": "application/json",
      "Content-Length": "1000000000"}, None, 403),
    ({"Authorization": "Bearer ephemeral-report-test-credential",
      "Content-Type": "text/plain", "Content-Length": "1000000000"}, None, 415),
    ({"Authorization": "Bearer ephemeral-report-test-credential",
      "Content-Type": "application/json", "Content-Length": str(MAX_REPORT_BODY_BYTES + 1)},
     None, 413),
    ({"Authorization": "Bearer ephemeral-report-test-credential",
      "Content-Type": "application/json"}, b'{"n":1e999}', 422),
])
def test_http_control_rejections_never_dispatch(control_http, headers, body, status):
    server, calls = control_http
    observed, payload = _http_report(server, "POST", "/api/reports/finish", body, headers)
    assert observed == status and isinstance(payload.get("error"), str)
    assert calls == []


def test_full_gui_mount_and_real_control_transport(monkeypatch):
    """Actual BACH GUI mount -> report client -> real HTTP -> one owner loop."""
    from fastapi.testclient import TestClient
    from http.server import ThreadingHTTPServer
    from gui import server as gui_server
    from gui.api import unified_api, worker_status_adapter
    from hub._services.chat.control_auth import CONTROL_API_TOKEN_ENV
    from hub._services.document.report_provider_contract import SCHEMA

    monkeypatch.setenv(CONTROL_API_TOKEN_ENV, "ephemeral-report-test-credential")
    expected_paths = {
        ("/api/reports/capabilities", "GET"), ("/api/reports/sources", "GET"),
        ("/api/reports/status", "GET"), ("/api/reports/watcher/status", "GET"),
        ("/api/reports/prepare", "POST"), ("/api/reports/finish", "POST"),
        ("/api/reports/cleanup", "POST"), ("/api/reports/watcher/configure", "POST"),
        ("/api/reports/watcher/tick", "POST"),
    }
    routes = {(route.path, method) for route in gui_server.app.routes
              if hasattr(route, "path") for method in getattr(route, "methods", [])}
    assert expected_paths <= routes
    calls = []
    class Host:
        async def dispatch(self, operation, payload):
            calls.append((operation, payload, threading.current_thread().name))
            assert operation == "capabilities"
            return {"schema": SCHEMA, "available": False, "modes": [],
                    "watcher_available": False, "reason_code": "provider_unavailable",
                    "mode_statuses": {
                        mode: {"available": False, "reason_code": "provider_unavailable"}
                        for mode in ("local", "cloud", "hybrid")}}
    base_handler = _network_control_handler()
    class WithIdentity(base_handler):
        def do_GET(self):
            if self.path == "/api/status":
                self._json({"service": "bach-chat-control", "telegram_verified": False})
            elif self.path == "/api/auth/check":
                if self._allow_control_request():
                    self._json({"service": "bach-chat-control", "authenticated": True})
            else:
                super().do_GET()
    owner = ControlReportOwner(lambda _loop: Host(), unavailable)
    assert owner.start()
    http_server = ThreadingHTTPServer(("127.0.0.1", 0), WithIdentity)
    http_server.report_control_owner = owner
    thread = threading.Thread(target=http_server.serve_forever,
                              kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    token = "ephemeral-report-test-credential"
    base = "http://127.0.0.1:" + str(http_server.server_address[1]) + "/api"
    # Exercise the actual perimeter middleware with an isolated registered-device
    # verifier fixture; never provision or read the operator's live device store.
    monkeypatch.setattr(gui_server, "validate_token",
                        lambda candidate: {"id": 9001} if candidate == token else None)
    monkeypatch.setattr(unified_api, "_require_memory_device_token", lambda _request: token)
    monkeypatch.setattr(worker_status_adapter, "_control_context",
                        lambda received: (base, {"Authorization": "Bearer " + received},
                                          gui_server._chat_control_payload_ready))
    try:
        client = TestClient(gui_server.app, base_url="http://localhost")
        response = client.get("/api/reports/capabilities",
                              headers={"Authorization": "Bearer " + token})
        assert response.status_code == 200
        assert response.json()["schema"] == SCHEMA
        assert response.json()["available"] is False
        assert calls == [("capabilities", {}, "bach-report-control-owner")]
        calls.clear()
        response = client.get("/api/reports/capabilities")
        assert response.status_code == 401
        assert calls == []
        response = client.get("/api/reports/capabilities",
                              headers={"Authorization": "Bearer revoked-fixture"})
        assert response.status_code == 401
        assert calls == []
        from fastapi import HTTPException
        def reject(_request):
            raise HTTPException(status_code=401, detail="fixture unauthorized")
        monkeypatch.setattr(unified_api, "_require_memory_device_token", reject)
        response = client.post("/api/reports/finish?extra=private", content=b"malformed")
        assert response.status_code == 401
        assert calls == []
    finally:
        http_server.shutdown()
        thread.join(3)
        http_server.server_close()
        assert owner.close(timeout=3)
        assert not thread.is_alive()
