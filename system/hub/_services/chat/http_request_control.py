# BACH Adapter: http_request_control
# SPDX-License-Identifier: MIT
"""Private foreground HTTP cancellation; no task, slot or resource authority."""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import hmac
import json
import secrets
import threading
import time

_CURRENT = contextvars.ContextVar("bach_http_request", default=None)


class HttpRequestBindingError(ValueError):
    reason_code = "http_request_binding_invalid"


class HttpRequestDisconnected(RuntimeError):
    reason_code = "http_disconnect"

    def __init__(self):
        super().__init__("HTTP-Anfrage wurde vom aufrufenden Gerät beendet")


def _same_text(left, right):
    if type(left) is not str:
        return False
    try:
        return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
    except UnicodeEncodeError:
        return False


def current_http_request():
    entry = _CURRENT.get()
    if entry is not None and asyncio.current_task() is not entry.owner:
        raise RuntimeError("HTTP request owner changed")
    return entry


def check_http_request():
    entry = current_http_request()
    if entry is not None:
        entry.check()
    return entry


class HttpRequest:
    def __init__(self, binding, *, slot_guard=None):
        self.binding = binding
        self._slot_guard = slot_guard
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.created = self.updated = time.monotonic()
        self.state = "prepared"
        self.owner = self.loop = self.cancel_event = None
        self.accepted = self.persisted = self.committed = False
        self.cleanup_complete = True
        self.partial = ""
        self._response_open = self._response_closed = self._client_closed = False

    def snapshot(self):
        with self.lock:
            return {
                "ok": True, "state": self.state,
                "cancel_requested": self.stop_event.is_set(),
                "cleanup_complete": (self.cleanup_complete and self.owner is None
                                     and self.state in {"finished", "aborted", "failed"}),
                "persisted": self.persisted,
                **({"reason_code": "http_disconnect"} if self.stop_event.is_set() else {}),
            }

    def cancel(self):
        with self.lock:
            if self.state in {"finished", "aborted", "failed"}:
                return self.snapshot()
            self.stop_event.set()
            self.updated = time.monotonic()
            if self.state == "prepared":
                self.state = "aborted"
            else:
                self.state = "aborting"
                loop, event = self.loop, self.cancel_event
                if loop is not None and event is not None:
                    try:
                        loop.call_soon_threadsafe(event.set)
                    except RuntimeError:
                        self.cleanup_complete = False
            return self.snapshot()

    def check(self):
        if self.stop_event.is_set():
            raise HttpRequestDisconnected()
        if self._slot_guard is not None:
            try:
                valid = self._slot_guard()
            except Exception:
                valid = False
            if not valid:
                raise HttpRequestBindingError("HTTP-Steckplatzbindung nicht mehr bestätigt")

    async def run(self, operation, *, warmup=False):
        with self.lock:
            self.owner = asyncio.current_task()
            self.loop = asyncio.get_running_loop()
            self.cancel_event = asyncio.Event()
            if self.stop_event.is_set():
                self.cancel_event.set()
            if warmup:
                self.cleanup_complete = False
        token = _CURRENT.set(self)
        try:
            self.check()
            result = await operation
            if warmup:
                with self.lock:
                    self.cleanup_complete = isinstance(result, dict) and (
                        result.get("cleanup_verified") is True
                        or ("cleanup_verified" not in result
                            and result.get("state") in {"loaded", "resident", "warmup_busy"}))
            return result
        finally:
            # An operation rejected before its first await must not be leaked.
            if getattr(operation, "cr_frame", None) is not None:
                operation.close()
            _CURRENT.reset(token)
            with self.lock:
                self.owner = self.loop = self.cancel_event = None

    def provider_start(self):
        self.check()
        with self.lock:
            self.cleanup_complete = False
            self._response_open = self._response_closed = self._client_closed = False

    def observe(self, phase, **_details):
        with self.lock:
            if phase == "response_headers_received":
                self._response_open = True
            elif phase == "response_cleanup_complete":
                self._response_closed = True
            elif phase == "client_cleanup_complete":
                self._client_closed = True
            self.cleanup_complete = (
                self._client_closed and (not self._response_open or self._response_closed)
            )

    def provider_returned(self, result, *, instrumented, capture_partial=True):
        with self.lock:
            if capture_partial and isinstance(result, dict):
                content = result.get("content")
                if isinstance(content, str) and content:
                    self.partial = content
            # For other backends, only an actual return is an end-of-call proof.
            # They are not forcibly interrupted and never get Ollama's event.
            if not instrumented:
                self.cleanup_complete = True

    def finalize(self, persist_answer):
        """Linearize completion vs cancel around the single transcript write."""
        with self.lock:
            answer = persist_answer(self.stop_event.is_set())
            self.persisted = True
            self.committed = True
            self.state = "aborted" if self.stop_event.is_set() else "finished"
            self.updated = time.monotonic()
            return answer

    def finish(self):
        with self.lock:
            if not self.committed:
                self.state = ("aborted" if self.stop_event.is_set() else
                              "failed" if self.accepted and not self.persisted else "finished")
                self.updated = time.monotonic()


class HttpRequestRegistry:
    """Bounded tombstones; active native owners are never evicted or replaced."""
    def __init__(self, service_instance, slot_reader, *, capacity=1024, ttl=900):
        self.service_instance = service_instance
        self.slot_reader = slot_reader
        self.capacity, self.ttl = capacity, ttl
        self.lock = threading.RLock()
        self.entries = {}

    def _slot_binding(self, chat_id):
        from .slots_config import CORE_EDITABLE_FIELDS
        slot = self.slot_reader(chat_id)
        if not isinstance(slot, dict):
            raise HttpRequestBindingError("Steckplatz nicht verifizierbar")
        fields = set(CORE_EDITABLE_FIELDS) | {"id", "enabled"}
        value = {"chat_id": chat_id, "slot": {k: slot.get(k) for k in fields}}
        return hashlib.sha256(json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")).hexdigest()

    def prepare(self, device_id, chat_id, service_instance):
        if (service_instance != self.service_instance
                or type(device_id) is not str or not device_id or len(device_id) > 128
                or type(chat_id) is not str or not chat_id or len(chat_id) > 256):
            raise HttpRequestBindingError("HTTP-Anfragebindung nicht bestätigt")
        slot_binding = self._slot_binding(chat_id)
        with self.lock:
            now = time.monotonic()
            self.entries = {key: entry for key, entry in self.entries.items()
                            if entry.state in {"active", "aborting"}
                            or now - entry.updated < self.ttl}
            if len(self.entries) >= self.capacity:
                raise HttpRequestBindingError("HTTP-Anfragekapazität ausgeschöpft")
            binding = {
                "device_id": device_id, "chat_id": chat_id,
                "service_instance": self.service_instance,
                "request_id": secrets.token_hex(24),
                "cancel_token": secrets.token_urlsafe(32),
                "slot_binding": slot_binding,
            }
            self.entries[binding["request_id"]] = HttpRequest(
                binding, slot_guard=lambda: self._slot_binding(chat_id) == slot_binding)
            return dict(binding)

    def get(self, binding):
        with self.lock:
            if type(binding) is not dict:
                raise HttpRequestBindingError("HTTP-Anfragebindung nicht bestätigt")
            request_id = binding.get("request_id")
            entry = self.entries.get(request_id) if type(request_id) is str else None
            if (entry is None or set(binding) != set(entry.binding)
                    or any(not _same_text(binding[k], value)
                           for k, value in entry.binding.items())
                    or (entry.state == "prepared"
                        and time.monotonic() - entry.created >= self.ttl)):
                raise HttpRequestBindingError("HTTP-Anfragebindung nicht bestätigt")
            return entry

    def claim(self, binding, chat_id):
        entry = self.get(binding)
        if entry.binding["chat_id"] != chat_id:
            raise HttpRequestBindingError("HTTP-Anfragebindung nicht bestätigt")
        current_slot = self._slot_binding(chat_id)
        with entry.lock:
            if entry.stop_event.is_set():
                raise HttpRequestDisconnected()
            if entry.state != "prepared" or current_slot != entry.binding["slot_binding"]:
                raise HttpRequestBindingError("HTTP-Anfragebindung nicht bestätigt")
            entry.state, entry.updated = "active", time.monotonic()
            return entry
