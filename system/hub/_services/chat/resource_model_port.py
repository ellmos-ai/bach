# BACH Adapter: resource_model_port
# SPDX-License-Identifier: MIT
"""Exact-model cooperative return through BACH's existing inference protocol.

The host controller invokes this adapter outside its state mutex. A caller must
obtain a resource grant before entering HostInferenceGate, and leave that gate
before calling end_turn. The only callback while holding the gate is a short,
local arbiter identity check; it must never make an HTTP/controller RPC or wait
for another lock holder. No RAM is declared released by this adapter.
"""
from __future__ import annotations

import asyncio
import json
import time
import urllib.request

from hub._services.chat.host_inference_gate import HostInferenceGate


class ModelReturnUnconfirmed(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ModelReturnUnconfirmed("model_api_redirect_refused")


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ModelReturnUnconfirmed("duplicate_model_api_field")
        value[key] = item
    return value


class GuardedModelPort:
    """No load API; only exact local identity/readback and guarded return."""
    def __init__(self, *, gate_factory=HostInferenceGate, transport=None,
                 timeout_seconds=20, clock=time.monotonic):
        if not 0 < timeout_seconds <= 20:
            raise ValueError("bounded model return deadline required")
        self.gate_factory, self.transport = gate_factory, transport
        self.timeout_seconds, self.clock = timeout_seconds, clock
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def _api(self, spec, path, deadline, payload=None):
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise ModelReturnUnconfirmed("model_api_deadline")
        if self.transport is not None:
            value = self.transport(spec, path, payload)
        else:
            request = urllib.request.Request(
                "http://127.0.0.1:" + str(spec.port) + path,
                data=None if payload is None else json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="GET" if payload is None else "POST")
            with self.opener.open(request, timeout=min(5, remaining)) as response:
                raw = response.read(262145)
            if len(raw) > 262144:
                raise ModelReturnUnconfirmed("model_api_response_too_large")
            def nonfinite(_):
                raise ModelReturnUnconfirmed("invalid_model_api_number")
            value = json.loads(raw, object_pairs_hook=_unique, parse_constant=nonfinite)
        if type(value) is not dict:
            raise ModelReturnUnconfirmed("invalid_model_api_response")
        return value

    def _target(self, spec, snapshot, *, residency=False):
        models = snapshot.get("models")
        if not isinstance(models, list) or len(models) > 10000:
            raise ModelReturnUnconfirmed("invalid_model_api_list")
        found, seen = None, set()
        for model in models:
            if not isinstance(model, dict):
                raise ModelReturnUnconfirmed("invalid_model_api_record")
            name, digest = model.get("name"), model.get("digest")
            if (not isinstance(name, str) or not 1 <= len(name) <= 512
                    or not isinstance(digest, str) or len(digest) != 64
                    or any(c not in "0123456789abcdef" for c in digest) or name in seen):
                raise ModelReturnUnconfirmed("ambiguous_model_api_identity")
            seen.add(name)
            # Stored aliases are harmless; a resident alias sharing this digest
            # has ambiguous ownership and cannot be unloaded through our name.
            if name == spec.model or residency and digest == spec.digest:
                if name != spec.model or digest != spec.digest or found is not None:
                    raise ModelReturnUnconfirmed("configured_model_identity_changed")
                if residency and (type(model.get("size")) is not int or model["size"] <= 0):
                    raise ModelReturnUnconfirmed("unknown_model_residency")
                found = model
        return found

    def _available(self, spec, deadline):
        if self._api(spec, "/api/version", deadline).get("version") != "0.33.3":
            raise ModelReturnUnconfirmed("model_server_version_not_reviewed")
        if self._target(spec, self._api(spec, "/api/tags", deadline)) is None:
            raise ModelReturnUnconfirmed("configured_model_unavailable")

    def verify_available(self, spec):
        self._available(spec, self.clock() + self.timeout_seconds)

    def resident_bytes(self, spec):
        deadline = self.clock() + self.timeout_seconds
        self._available(spec, deadline)
        target = self._target(spec, self._api(spec, "/api/ps", deadline), residency=True)
        return target["size"] if target is not None else 0

    def unload(self, spec, check_owned):
        try:
            asyncio.run(self._unload(spec, check_owned))
        except Exception as exc:
            # Do not leak arbitrary HTTP errors or private model responses.
            # The durable intent is deliberately retained after uncertain POSTs.
            if isinstance(exc, ModelReturnUnconfirmed):
                raise
            raise ModelReturnUnconfirmed("model_return_unconfirmed") from exc

    async def _unload(self, spec, check_owned):
        from tools.maintenance.memory_pressure_unload_guard import (
            record_intent,
            sync_directory,
        )

        gate = self.gate_factory()
        deadline = self.clock() + self.timeout_seconds
        def ready():
            check_owned()
            if self.clock() >= deadline:
                raise ModelReturnUnconfirmed("model_return_deadline")
        ready()
        async with gate.turn("resource-model-return", "background", check_ready=ready):
            ready()
            self._available(spec, deadline)
            target = self._target(spec, self._api(spec, "/api/ps", deadline), residency=True)
            if target is None:
                return
            ready()
            pending = record_intent(gate.root, spec.model, spec.digest)
            ready()
            response = self._api(spec, "/api/generate", deadline,
                                 {"model": spec.model, "keep_alive": 0, "stream": False})
            if response.get("done") is not True or response.get("done_reason") != "unload":
                raise ModelReturnUnconfirmed("model_unload_ack_missing")
            while True:
                ready()
                target = self._target(spec, self._api(spec, "/api/ps", deadline), residency=True)
                if target is None:
                    break
                await asyncio.sleep(.1)
            ready()
            pending.unlink()
            sync_directory(gate.root)
