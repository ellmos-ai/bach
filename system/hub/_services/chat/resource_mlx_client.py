# BACH Adapter: ocean_mlx_resource_client
# SPDX-License-Identifier: MIT
"""BACH text calls through the owned, in-process Ocean MLX port."""
from __future__ import annotations

import asyncio
import os
import time
import uuid

from hub._services.chat.host_inference_gate import HostInferenceGate
from hub._services.chat.resource_host_client import ResourceHostUnavailable
from hub._services.ocean_resources_provider import load_verified

_MODULES = ("ocean_resources.configuration", "ocean_resources.contracts",
            "ocean_resources.model_client", "ocean_resources.model_load_client")


def _target(models, model, digest, context_tokens):
    matches = [item for item in models if isinstance(item, dict) and item.get("model") == model
               and item.get("backend") == "mlx-qwen"]
    if (len(matches) != 1 or matches[0].get("digest") != digest
            or matches[0].get("context_tokens") != context_tokens
            or not matches[0].get("load_policy_sha256") or not matches[0].get("socket_id")):
        raise ResourceHostUnavailable("resource_mlx_target_unavailable")
    return matches[0]


async def _call_until(operation, *, client, grant, hold, intermediate, done, deadline, ready):
    while True:
        ready()
        if time.monotonic() >= deadline:
            raise ResourceHostUnavailable("resource_mlx_request_deadline")
        try:
            reply = await asyncio.to_thread(operation)
        except hold:
            current = await asyncio.to_thread(client.request_status, grant.request_id)
            if current["state"] not in {"LOAD_PENDING", "RUNNING"}:
                raise ResourceHostUnavailable("resource_mlx_request_held") from None
        else:
            ready()
            if reply["state"] == done:
                return reply
            if reply["state"] != intermediate:
                raise ResourceHostUnavailable("resource_mlx_request_failed")
        await asyncio.sleep(.1)


async def generate_mlx_tokens(model, digest, context_tokens, prompt, max_new_tokens, stop_tokens, *,
                              priority, timeout_seconds, check_ready=None):
    path = os.environ.get("BACH_RESOURCE_BROKER_CONFIG")
    if not path:
        raise ResourceHostUnavailable("resource_mlx_host_not_configured")
    modules = await asyncio.to_thread(load_verified, _MODULES)
    contracts = modules["ocean_resources.contracts"]
    client, models = await asyncio.to_thread(modules["ocean_resources.configuration"].read_client, path)
    if not all(callable(getattr(client, name, None)) for name in ("materialize_model_load", "generate_model")):
        raise ResourceHostUnavailable("resource_mlx_ocean_provider_unavailable")
    target = _target(models, model, digest, context_tokens)
    socket = target["socket_id"]
    deadline = time.monotonic() + timeout_seconds
    owner_id = "ocean-mlx-" + uuid.uuid4().hex

    def ready(ticket=None):
        if check_ready is not None:
            check_ready()
        renewal = ticket.get("renewal") if ticket else None
        if renewal is not None and renewal.done():
            raise ResourceHostUnavailable("resource_mlx_lease_ended")
        if time.monotonic() >= deadline:
            raise ResourceHostUnavailable("resource_mlx_request_deadline")

    ready()
    active = (await asyncio.to_thread(client.status)).get("torch")
    resident = False
    if isinstance(active, dict) and active.get("socket_id") == socket:
        current = await asyncio.to_thread(client.request_status, active["request_id"])
        resident = current["state"] == "RUNNING" and current["grant"] == active

    if not resident:
        factory = modules["ocean_resources.model_load_client"].model_load_turn
        async with factory(client, socket, "bach-model", priority, check_ready=ready) as ticket:
            permit = ticket["permit"]
            grant = contracts.Grant(**permit["grant"])
            expected = {key: target[key] for key in ("model", "digest", "context_tokens", "port")}
            if (permit.get("spec") != expected or permit.get("policy_sha256") != target["load_policy_sha256"]
                    or grant.socket_id != socket):
                raise ResourceHostUnavailable("resource_mlx_load_binding_changed")
            try:
                async with HostInferenceGate().turn(owner_id, priority, check_ready=lambda: ready(ticket)):
                    await _call_until(lambda: client.materialize_model_load(grant, permit["turn_id"]),
                                      client=client, grant=grant, hold=contracts.Hold,
                                      intermediate="LOADING", done="READY", deadline=deadline,
                                      ready=lambda: ready(ticket))
                ticket["successful"] = True
            except BaseException:
                # Revoke the exact load lease before Ocean attempts native cleanup.
                # A missing ACK leaves the staged grant to its normal recovery path.
                try:
                    current = await asyncio.to_thread(client.request_status, grant.request_id)
                    lease = contracts.RequestLease(**current["lease"])
                    if lease.authority_id == grant.authority_id and lease.request_id == grant.request_id:
                        await asyncio.to_thread(client.cancel, lease)
                except contracts.Hold:
                    pass
                raise

    factory = modules["ocean_resources.model_client"].model_turn
    async with factory(client, socket, "bach-model", priority, check_ready=ready) as ticket:
        grant = contracts.Grant(**ticket["grant"])
        async with HostInferenceGate().turn(owner_id, priority, check_ready=lambda: ready(ticket)):
            reply = await _call_until(
                lambda: client.generate_model(grant, ticket["turn_id"], prompt, max_new_tokens,
                                              stop_tokens=stop_tokens),
                client=client, grant=grant, hold=contracts.Hold, intermediate="RUNNING",
                done="COMPLETE", deadline=deadline, ready=lambda: ready(ticket))
        return reply["tokens"]
