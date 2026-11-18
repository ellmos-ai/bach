# SPDX-License-Identifier: MIT
"""Concrete staged warmup transport evidence under the native inference owner."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import re
from urllib.parse import urlsplit

from hub._services.chat.host_inference_gate import HostInferenceGate

_ACTIVE_LOAD: ContextVar[_LoadTransport | None] = ContextVar("resource_load_transport", default=None)


def _positive_keep_alive(value):
    # Preserve only understood, nonzero provider durations. Never replace a
    # compute-policy zero with a load-friendly value: zero means unload.
    if type(value) is int:
        seconds = value
    elif (type(value) is str and len(value) <= 64
          and re.fullmatch(r"(?:[0-9]+[smh])+", value)):
        seconds = sum(int(amount) * {"s": 1, "m": 60, "h": 3600}[unit]
                      for amount, unit in re.findall(r"([0-9]+)([smh])", value))
    else:
        return False
    # Provider durations use signed int64 nanoseconds.
    return 1 <= seconds <= 9_223_372_036


class _LoadTransport:
    def __init__(self, grant):
        self.backend = grant["backend"]
        self.model = grant["model"]
        self.spec = dict(grant["resource_load_ticket"]["permit"]["spec"])
        self.check = grant["resource_load_check"]
        self.owner = HostInferenceGate.current_owner()
        self.task = asyncio.current_task()
        self.started = False
        self.handle = None
        self.terminal_seen = False
        self.confirmed = False

    def _owned(self):
        if (asyncio.current_task() is not self.task
                or HostInferenceGate.current_owner() is not self.owner):
            raise RuntimeError("resource_model_transport_owner_changed")

    def begin(self, backend, url, payload):
        self._owned()
        endpoint = urlsplit(url)
        spec = self.spec
        if (self.started or backend is not self.backend
                or set(payload) != {"model", "messages", "stream", "think", "keep_alive", "options"}
                or not _positive_keep_alive(payload.get("keep_alive"))
                or spec.get("model") != self.model
                or payload.get("model") != self.model
                or payload.get("messages") != []
                or payload.get("stream") is not True
                or payload.get("think") is not False
                or payload.get("options") != {"num_ctx": spec.get("context_tokens")}
                or endpoint.scheme != "http"
                or endpoint.hostname not in {"127.0.0.1", "localhost"}
                or (80 if endpoint.port is None else endpoint.port) != spec.get("port")
                or endpoint.path != "/api/chat"
                or endpoint.username is not None or endpoint.password is not None
                or endpoint.query or endpoint.fragment):
            raise RuntimeError("resource_model_transport_binding_changed")
        target = dict(self.owner._check_owned_record().record.get("model_target", {}))
        if target.get("backend") != "ollama" or target.get("model") != self.model:
            raise RuntimeError("resource_model_transport_target_changed")
        digest = hashlib.sha256(json.dumps(
            {"url": url, "payload": payload}, sort_keys=True,
            ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        self.started = True
        # Preparation and durable intent IO can both block. Recheck the native
        # authority after each, using only this owner's exact opaque handle.
        self.check()
        self.handle = self.owner.begin_dispatch(digest, target)
        self.check(dispatch_handle=self.handle)

    def decode_chunk(self, line):
        if self.terminal_seen:
            raise ValueError("data after load terminal")

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate load response field")
                result[key] = value
            return result

        def nonfinite(_value):
            raise ValueError("nonfinite load response value")

        chunk = json.loads(line, object_pairs_hook=unique, parse_constant=nonfinite)
        if (type(chunk) is not dict
                or ("model" in chunk and chunk["model"] != self.model)
                or ("done" in chunk and type(chunk["done"]) is not bool)):
            raise ValueError("invalid load response")
        if chunk.get("done") is True:
            if chunk.get("model") != self.model or chunk.get("done_reason") != "load":
                raise ValueError("invalid load terminal")
            self.terminal_seen = True
        return chunk

    def finish(self):
        self._owned()
        if self.handle is None or not self.terminal_seen or self.confirmed:
            raise RuntimeError("resource_model_dispatch_unconfirmed")
        # Timeout/cancellation/malformed response and even close failure leave
        # dispatch_pending durable. Only the concrete parser reaches this path.
        self.owner.finish_dispatch(self.handle)
        self.confirmed = True


@contextmanager
def staged_warmup_transport(grant):
    if grant.get("resource_load_ticket") is None:
        yield None
        return
    if _ACTIVE_LOAD.get() is not None:
        raise RuntimeError("resource_model_transport_already_active")
    transport = _LoadTransport(grant)
    token = _ACTIVE_LOAD.set(transport)
    try:
        yield transport
    finally:
        _ACTIVE_LOAD.reset(token)


def staged_chat_transport():
    """The runtime owns this scope; the concrete backend starts its one POST."""
    return _ACTIVE_LOAD.get()
