"""Owned loopback relay for one private task binding and fixed tool policy.

Each result needs a separate acknowledgement. An unacknowledged call blocks
the next call and revokes the local binding on close; mutations are never retried.
"""
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import secrets
import threading
import uuid

from .bach_tools import BachToolProvider


_ID = re.compile(r"[0-9a-f]{32}\Z")
_MAX_BODY = 262_144


class _Rejected(Exception):
    def __init__(self, status):
        self.status = status


class _OwnedServer(ThreadingHTTPServer):
    daemon_threads = False  # server_close waits for actual in-flight tool calls

    def handle_error(self, *_):
        # Neither request headers nor private exception details belong in logs.
        pass


class WorkerToolBridge:
    def __init__(self, binding, *, mode, bach_app=None, default_model=None, guard=None,
                 allowed_tools=None, agent_operations=None):
        if mode not in {"safe", "plan", "full"}:
            raise ValueError("Ungültiger Worker-Werkzeugmodus")
        self.binding = binding
        self._mode = mode
        self._provider = BachToolProvider(bach_app, default_model, worker_task_binding=binding,
                                         require_task_binding=True, guard=guard, allowed_tools=allowed_tools,
                                         agent_operations=agent_operations)
        self._token = secrets.token_urlsafe(32)
        self._closing = threading.Event()
        self._calls = threading.RLock()
        self._close_lock = threading.Lock()
        self._pending = None
        self._previous = None
        self._seen = set()
        self._server = None
        self._thread = None

    def private_environment(self):
        if self._server is None or self._closing.is_set():
            raise RuntimeError("Werkzeugtransport ist nicht aktiv")
        return {"BACH_WORKER_TOOL_URL": f"http://127.0.0.1:{self._server.server_port}",
                "BACH_WORKER_TOOL_TOKEN": self._token,
                "BACH_WORKER_TOOL_GENERATION": self.binding.generation,
                "BACH_WORKER_TOOL_TASK_ID": str(self.binding.task_id)}

    def __enter__(self):
        self.binding.assert_active()
        if self._server is not None or self._closing.is_set():
            raise RuntimeError("Werkzeugtransport kann nicht wiederverwendet werden")
        relay = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def setup(self):
                super().setup()
                self.connection.settimeout(3)

            def _reply(self, status, payload):
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _handle(self, method):
                try:
                    actual = self.headers.get("Authorization", "").encode("utf-8")
                    expected = ("Bearer " + relay._token).encode("utf-8")
                    if not hmac.compare_digest(actual, expected):
                        raise _Rejected(401)
                    if self.headers.get("Origin") is not None:
                        raise _Rejected(403)
                    if method == "GET" and self.path == "/tools":
                        result = relay._tools()
                    elif method == "POST" and self.path in {"/call", "/ack"}:
                        if self.headers.get("Transfer-Encoding") is not None:
                            raise _Rejected(400)
                        try:
                            length = int(self.headers.get("Content-Length", "0"))
                            if not 0 < length <= _MAX_BODY:
                                raise ValueError()
                            body = json.loads(self.rfile.read(length))
                        except Exception:
                            raise _Rejected(400) from None
                        result = relay._call(body) if self.path == "/call" else relay._ack(body)
                    else:
                        raise _Rejected(404)
                    self._reply(200, result)
                except _Rejected as exc:
                    self._reply(exc.status, {"error": "Werkzeugaufruf nicht bestätigt"})

            def do_GET(self): self._handle("GET")
            def do_POST(self): self._handle("POST")
        self._server = _OwnedServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=lambda: self._server.serve_forever(poll_interval=.05),
                                        daemon=True, name="worker-tool-relay")
        self._thread.start()
        return self

    def _check(self):
        if self._closing.is_set():
            raise _Rejected(503)
        try:
            self.binding.assert_active()
        except Exception:
            raise _Rejected(403) from None

    def _tools(self):
        self._check()
        return {"tools": self._provider.get_tools(self._mode)}

    def _call(self, body):
        if (not isinstance(body, dict) or set(body) != {"request_id", "previous_receipt", "name", "arguments"}
                or not isinstance(body["request_id"], str) or not _ID.fullmatch(body["request_id"])
                or not isinstance(body["name"], str) or not isinstance(body["arguments"], dict)):
            raise _Rejected(400)
        with self._calls:
            self._check()
            if (self._pending is not None or body["previous_receipt"] != self._previous
                    or body["request_id"] in self._seen):
                raise _Rejected(409)
            if len(self._seen) >= 10_000:
                raise _Rejected(429)
            offered = self._provider.get_tools(self._mode)
            if body["name"] not in {tool["function"]["name"] for tool in offered}:
                raise _Rejected(403)
            self._seen.add(body["request_id"])
            try:
                result = self._provider.execute(body["name"], body["arguments"], self._mode)
            except BaseException:
                self.binding.invalidate()
                raise _Rejected(503) from None
            receipt = uuid.uuid4().hex
            self._pending = (body["request_id"], receipt)
            return {"request_id": body["request_id"], "receipt_id": receipt,
                    "generation": self.binding.generation, "task_id": self.binding.task_id,
                    "result": str(result).replace(self._token, "[redacted]"),
                    "is_error": str(result).startswith(("BLOCKIERT:", "Taskoperation nicht bestätigt", "Taskbindung fehlt"))}

    def _ack(self, body):
        if not isinstance(body, dict) or set(body) != {"request_id", "receipt_id"}:
            raise _Rejected(400)
        with self._calls:
            if self._closing.is_set():
                raise _Rejected(503)
            if self._pending is None or self._pending != (body["request_id"], body["receipt_id"]):
                raise _Rejected(409)
            self._previous = self._pending[1]
            self._pending = None
            return {"acknowledged": True, "receipt_id": self._previous}

    def close(self):
        with self._close_lock:
            if self._closing.is_set():
                return
            self._closing.set()
            if self._server is not None:
                self._server.shutdown()
                self._thread.join()
                self._server.server_close()
            with self._calls:
                if self._pending is not None:
                    self.binding.invalidate()

    def __exit__(self, *_):
        self.close()
