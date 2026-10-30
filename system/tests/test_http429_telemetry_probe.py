"""Reproduzierbarer HTTP-429-Event als Telemetrie-/Belegquelle.

Startet einen echten Loopback-HTTP-Server (127.0.0.1:0), der deterministisch
mit Status 429 und ``Retry-After: 0`` antwortet, und prueft den vollstaendigen
Fehlervertrag des ``HermesBackend`` sowie die Telemetriezaehlung dazu.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.llm.backend_errors import BackendRequestFailure  # noqa: E402
from hub._services.llm.model_backend import HermesBackend  # noqa: E402

RATE_LIMIT_BODY = {"error": {"message": "rate limit exceeded"}}


class _RateLimitHandler(BaseHTTPRequestHandler):
    """Antwortet auf jeden POST deterministisch mit HTTP 429."""

    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802 (http.server Namensschema)
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        payload = json.dumps(RATE_LIMIT_BODY).encode("utf-8")
        self.send_response(429)
        self.send_header("Content-Type", "application/json")
        self.send_header("Retry-After", "0")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return


@pytest.fixture()
def rate_limit_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RateLimitHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http429_event_contract_and_telemetry(rate_limit_server):
    backend = HermesBackend(
        base_url=rate_limit_server,
        api_key="dummy",
        default_model="probe/429",
    )
    messages = [{"role": "user", "content": "probe"}]

    with pytest.raises(BackendRequestFailure) as excinfo:
        asyncio.run(backend.chat(messages, retry_transient=False))

    exc = excinfo.value
    err = exc.backend_error
    assert isinstance(err, dict)
    assert err["status_code"] == 429
    assert err["kind"] == "http_error"
    assert err["provider"] == "hermes"
    assert err["retry_after_seconds"] == 0

    from core import telemetry

    assert telemetry.increment("model_calls", outcome="error", model="hermes") is True
