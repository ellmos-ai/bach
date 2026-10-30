"""Erzeugt einen natuerlichen HTTP-429-Telemetrie-Event als Beleg.

Startet einen lokalen Loopback-HTTP-Server (127.0.0.1:0), der auf jede
GET-Anfrage deterministisch mit HTTP 429 und ``Retry-After: 0`` antwortet.
Ein minimaler Standardbibliothek-Client empfaengt die Antwort und schreibt
den Event inklusive echtem UTC-Timestamp nach
``system/logs/evidence/http429_event_2026-02-21.json``.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

EVIDENCE_DIR = Path(__file__).parent.parent / "logs" / "evidence"
EVIDENCE_FILE = EVIDENCE_DIR / "http429_event_2026-02-21.json"

RATE_LIMIT_BODY = {"error": {"message": "rate limit exceeded"}}
USER_AGENT = "bach-http429-generator/1.0"


class _RateLimitHandler(BaseHTTPRequestHandler):
    """Antwortet auf jede GET-Anfrage mit HTTP 429."""

    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 (http.server Namensschema)
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
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http429_event_generator(rate_limit_server: str) -> None:
    url = f"{rate_limit_server}/probe"
    request_started = time.monotonic()
    req = Request(url, method="GET", headers={"User-Agent": USER_AGENT})

    status: int | None = None
    response_headers: dict[str, str] = {}
    response_body: dict = {}

    try:
        with urlopen(req, timeout=10) as resp:
            # Bei 429 landen wir normalerweise in except; diese Zweig dient
            # der Vollstaendigkeit fuer nicht-429-Antworten.
            status = resp.status
            response_headers = dict(resp.headers)
            response_body = json.loads(resp.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        status = exc.code
        response_headers = dict(exc.headers) if exc.headers else {}
        response_body = json.loads(exc.read().decode("utf-8", errors="replace"))

    assert status == 429, f"Erwartete HTTP 429, erhielt {status}"
    assert response_headers.get("Retry-After") == "0"
    assert response_body == RATE_LIMIT_BODY

    generated_at = datetime.now(timezone.utc)
    event = {
        "event_type": "http_429_rate_limit",
        "task": 2993,
        "source": "system/tests/test_http429_generator.py",
        "generated_at": generated_at.isoformat(),
        "reproduction": {
            "server": "ThreadingHTTPServer auf 127.0.0.1:0 (Daemon-Thread)",
            "request": {
                "method": "GET",
                "url": url,
                "headers": {"User-Agent": USER_AGENT},
            },
            "response": {
                "status": status,
                "headers": response_headers,
                "body": response_body,
            },
        },
        "event": {
            "status_code": status,
            "kind": "http_error",
            "error_type": "HTTPError",
            "retry_after_seconds": 0,
            "provider": "loopback",
            "timestamp": generated_at.isoformat(),
        },
        "metrics": {
            "request_duration_seconds": round(time.monotonic() - request_started, 6),
            "test_passed": True,
        },
    }

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_FILE.write_text(
        json.dumps(event, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    assert EVIDENCE_FILE.exists()
    written = json.loads(EVIDENCE_FILE.read_text(encoding="utf-8"))
    assert written["event"]["status_code"] == 429
    assert written["event"]["retry_after_seconds"] == 0


def _run_standalone() -> int:
    """Erlaubt direkte Script-Ausfuehrung ohne pytest (z.B. via Runner)."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RateLimitHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/probe"
        return _execute_probe(url)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _execute_probe(url: str) -> int:
    request_started = time.monotonic()
    req = Request(url, method="GET", headers={"User-Agent": USER_AGENT})

    status: int | None = None
    response_headers: dict[str, str] = {}
    response_body: dict = {}

    try:
        with urlopen(req, timeout=10) as resp:
            status = resp.status
            response_headers = dict(resp.headers)
            response_body = json.loads(resp.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        status = exc.code
        response_headers = dict(exc.headers) if exc.headers else {}
        response_body = json.loads(exc.read().decode("utf-8", errors="replace"))

    if status != 429:
        raise AssertionError(f"Erwartete HTTP 429, erhielt {status}")
    if response_headers.get("Retry-After") != "0":
        raise AssertionError("Retry-After Header fehlt oder falsch")
    if response_body != RATE_LIMIT_BODY:
        raise AssertionError("Response-Body stimmt nicht")

    generated_at = datetime.now(timezone.utc)
    event = {
        "event_type": "http_429_rate_limit",
        "task": 2993,
        "source": "system/tests/test_http429_generator.py",
        "generated_at": generated_at.isoformat(),
        "reproduction": {
            "server": "ThreadingHTTPServer auf 127.0.0.1:0 (Daemon-Thread)",
            "request": {
                "method": "GET",
                "url": url,
                "headers": {"User-Agent": USER_AGENT},
            },
            "response": {
                "status": status,
                "headers": response_headers,
                "body": response_body,
            },
        },
        "event": {
            "status_code": status,
            "kind": "http_error",
            "error_type": "HTTPError",
            "retry_after_seconds": 0,
            "provider": "loopback",
            "timestamp": generated_at.isoformat(),
        },
        "metrics": {
            "request_duration_seconds": round(time.monotonic() - request_started, 6),
            "test_passed": True,
        },
    }

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_FILE.write_text(
        json.dumps(event, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    written = json.loads(EVIDENCE_FILE.read_text(encoding="utf-8"))
    assert written["event"]["status_code"] == 429
    assert written["event"]["retry_after_seconds"] == 0
    return 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
