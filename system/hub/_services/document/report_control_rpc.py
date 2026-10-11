"""Control-process adapter for fixed report RPCs and an owned async lifecycle.

The report provider and its DTOs remain separate. This module creates neither
a ChatRuntime nor a model/backend, artifact store, or operator consent issuer.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import threading
from typing import Any, Callable, Mapping
from urllib.parse import parse_qsl, urlsplit

MAX_REPORT_BODY_BYTES = 262144
_REPORT_GET = {
    "/api/reports/capabilities": ("capabilities", frozenset()),
    "/api/reports/sources": ("sources", frozenset({"subject_ref"})),
    "/api/reports/status": ("status", frozenset({"run_id"})),
    "/api/reports/watcher/status": ("watcher_status", frozenset()),
}
_REPORT_POST = {
    "/api/reports/prepare": "prepare",
    "/api/reports/finish": "finish",
    "/api/reports/cleanup": "cleanup",
    "/api/reports/watcher/configure": "watcher_configure",
    "/api/reports/watcher/tick": "watcher_tick",
}


class ReportControlRequestError(ValueError):
    """A neutral rejection which does not include request content."""

    def __init__(self, status_code: int, reason_code: str) -> None:
        self.status_code = status_code
        self.reason_code = reason_code
        super().__init__(reason_code)


def is_report_control_path(raw_path: str) -> bool:
    path = urlsplit(raw_path).path
    return path == "/api/reports" or path.startswith("/api/reports/")


def parse_report_control_request(
    method: str, raw_path: str, body: Any = None,
) -> tuple[str, dict[str, Any]]:
    """Validate transport shape; the host validates the precise provider DTO."""
    try:
        parsed = urlsplit(raw_path)
        if parsed.scheme or parsed.netloc or parsed.fragment:
            raise ValueError
        if method == "GET":
            if parsed.path not in _REPORT_GET:
                raise ReportControlRequestError(404, "report_operation_unknown")
            operation, expected = _REPORT_GET[parsed.path]
            pairs = parse_qsl(
                parsed.query, keep_blank_values=True, strict_parsing=True,
                encoding="utf-8", errors="strict",
            )
            if len(pairs) != len(expected) or {key for key, _ in pairs} != expected:
                raise ReportControlRequestError(422, "invalid_report_request")
            if any(not value for _, value in pairs):
                raise ReportControlRequestError(422, "invalid_report_request")
            return operation, dict(pairs)
        if method == "POST":
            if parsed.path not in _REPORT_POST:
                raise ReportControlRequestError(404, "report_operation_unknown")
            if parsed.query or not isinstance(body, Mapping):
                raise ReportControlRequestError(422, "invalid_report_request")
            if any(not isinstance(key, str) for key in body):
                raise ReportControlRequestError(422, "invalid_report_request")
            return _REPORT_POST[parsed.path], dict(body)
        raise ReportControlRequestError(405, "report_method_not_allowed")
    except ReportControlRequestError:
        raise
    except (ValueError, UnicodeError):
        raise ReportControlRequestError(422, "invalid_report_request") from None


def read_report_json(headers: Mapping[str, str], stream: Any) -> dict[str, Any]:
    """Bounded strict read. Call only after the existing authentication guard."""
    get_all = getattr(headers, "get_all", None)
    if callable(get_all):
        transfer_encodings = get_all("Transfer-Encoding", [])
        lengths = get_all("Content-Length", [])
    else:
        transfer_encodings = [headers["Transfer-Encoding"]] if "Transfer-Encoding" in headers else []
        lengths = [headers["Content-Length"]] if "Content-Length" in headers else []
    if transfer_encodings:
        raise ReportControlRequestError(400, "invalid_report_transport")
    if len(lengths) != 1:
        raise ReportControlRequestError(411, "report_length_required")
    length = lengths[0]
    if not isinstance(length, str) or re.fullmatch(r"[0-9]{1,8}", length) is None:
        raise ReportControlRequestError(411, "report_length_required")
    count = int(length)
    if count > MAX_REPORT_BODY_BYTES:
        raise ReportControlRequestError(413, "report_request_too_large")
    if count == 0:
        raise ReportControlRequestError(422, "invalid_report_request")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def finite_float(number):
        value = float(number)
        if not math.isfinite(value):
            raise ValueError("nonfinite JSON number")
        return value

    try:
        raw = stream.read(count)
        if len(raw) != count:
            raise ValueError("short body")
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=unique_object, parse_float=finite_float,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        if not isinstance(value, dict):
            raise ValueError("object required")
        stack = [(value, 1)]
        while stack:
            item, depth = stack.pop()
            if depth > 32:
                raise ValueError("JSON nesting exceeds the report transport limit")
            if isinstance(item, dict):
                stack.extend((child, depth + 1) for child in item.values()
                             if isinstance(child, (dict, list)))
            elif isinstance(item, list):
                stack.extend((child, depth + 1) for child in item
                             if isinstance(child, (dict, list)))
        return value
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise ReportControlRequestError(422, "invalid_report_request") from None


class ControlReportOwner:
    """One Control-owned loop, with admission stop and natural task drain.

    The factory receives the actual running loop and must bind the existing
    runtime and trusted host ports. Missing configuration creates no thread.
    Shutdown never cancels a finish/tick which may have caused an effect.
    """

    def __init__(
        self,
        host_factory: Callable[[asyncio.AbstractEventLoop], Any] | None,
        unavailable_result: Callable[[str, Mapping[str, Any] | None], dict[str, Any]],
    ) -> None:
        self._host_factory = host_factory
        self._unavailable_result = unavailable_result
        self._host = None
        self._loop = None
        self._thread = None
        self._ready = threading.Event()
        self._lock = threading.RLock()
        self._accepting = False
        self._closing = False

    @property
    def thread_alive(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self, timeout: float = 5.0) -> bool:
        with self._lock:
            if self._closing or self._host_factory is None:
                return False
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="bach-report-control-owner", daemon=True,
                )
                self._thread.start()
        if not self._ready.wait(timeout=max(0.1, float(timeout))):
            self.close(timeout=0.1)
            return False
        with self._lock:
            return self._accepting

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop

        async def initialize() -> None:
            try:
                host = self._host_factory(loop)
                with self._lock:
                    self._host = host
                    self._accepting = host is not None and not self._closing
            except Exception:
                with self._lock:
                    self._host = None
                    self._accepting = False
            finally:
                self._ready.set()

        try:
            loop.run_until_complete(initialize())
            with self._lock:
                should_run = self._accepting
            if should_run:
                loop.run_forever()
        finally:
            with self._lock:
                self._accepting = False
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
            loop.close()
            self._ready.set()

    def call(
        self, operation: str, payload: Mapping[str, Any] | None = None,
        *, timeout: float = 30.0,
    ) -> dict[str, Any]:
        # Keep admission and submission ordered against close(). The host's
        # synchronous bridge submits before waiting; RPC threads may run in
        # parallel, while all provider work remains on one owned event loop.
        with self._lock:
            if not self._accepting or self._host is None:
                return self._unavailable_result(operation, payload)
            host = self._host
            loop = self._loop
            if loop is None or not loop.is_running():
                return self._unavailable_result(operation, payload)
            future = asyncio.run_coroutine_threadsafe(
                host.dispatch(operation, payload), loop,
            )
        try:
            return future.result(timeout=max(0.1, min(float(timeout), 120.0)))
        except TimeoutError:
            # A timed-out effect keeps running and is drained during shutdown.
            return host._timeout_response(operation, payload, "provider_effect_unknown")

    def close(self, timeout: float = 5.0) -> bool:
        """Stop accepting work; return false while owned effects still drain."""
        with self._lock:
            self._accepting = False
            thread = self._thread
            loop = self._loop
            first_close = not self._closing
            self._closing = True
            if first_close and loop is not None and loop.is_running():
                async def drain() -> None:
                    # The task submission callbacks admitted before close()
                    # have run by the time this coroutine takes its snapshot.
                    current = asyncio.current_task()
                    while True:
                        await asyncio.sleep(0)
                        pending = [task for task in asyncio.all_tasks(loop)
                                   if task is not current and not task.done()]
                        if not pending:
                            break
                        # Admitted tasks can spawn children while draining.
                        # Recheck after each batch rather than closing over
                        # one snapshot and abandoning later child tasks.
                        await asyncio.gather(*pending, return_exceptions=True)
                    loop.stop()

                loop.call_soon_threadsafe(lambda: loop.create_task(drain()))
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, float(timeout)))
        return not self.thread_alive
