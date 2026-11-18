# BACH Adapter: resource_host_client
# SPDX-License-Identifier: MIT
"""BACH's native model-call boundary over the configured Ocean host authority."""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from hub._services.ocean_resources_provider import load_verified


class ResourceHostUnavailable(RuntimeError):
    pass


def _endpoint_url(backend):
    # The runtime treats missing endpoints and the IPv4 wildcard as local.
    # They are not reviewed broker targets, never evidence of an external call.
    try:
        url = urlsplit(str(getattr(backend, "base_url", "") or ""))
        hostname = url.hostname
    except ValueError:
        raise ResourceHostUnavailable("resource_model_endpoint_not_reviewed") from None
    if not hostname or hostname == "0.0.0.0":
        raise ResourceHostUnavailable("resource_model_endpoint_not_reviewed")
    return url


def _target(backend, model, models):
    url = _endpoint_url(backend)
    if url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return None  # External model providers do not use this host's resources.
    if (url.scheme != "http" or url.username or url.password or url.query or url.fragment
            or url.path not in {"", "/"} or url.hostname == "::1"):
        raise ResourceHostUnavailable("resource_model_endpoint_not_reviewed")
    port = url.port or 80
    candidates = [m for m in models if m.get("model") == model and m.get("port") == port]
    if len(candidates) != 1:
        raise ResourceHostUnavailable("resource_model_profile_missing_or_ambiguous")
    target = candidates[0]
    context = getattr(backend, "num_ctx", None)
    if (type(context) is not int or type(target.get("context_tokens")) is not int
            or not 512 <= context <= target["context_tokens"]):
        raise ResourceHostUnavailable("resource_model_context_not_reviewed")
    return target


@asynccontextmanager
async def resource_model_turn(backend, model, chat_id, priority, *, check_ready=None, warmup=None):
    """Acquire before reserve polling/inference.lock; release after leaving it.

    An unset configuration preserves the existing path. An explicitly configured
    but unavailable/changed authority fails closed; there is no unbrokered retry.
    Conversation, worker task lease, model binding and budgets remain BACH-owned.
    """
    path = os.environ.get("BACH_RESOURCE_BROKER_CONFIG")
    if not path:
        yield check_ready
        return
    url = _endpoint_url(backend)
    if url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        def external_ready():
            if check_ready is not None:
                check_ready()
            if urlsplit(str(getattr(backend, "base_url", ""))) != url:
                raise ResourceHostUnavailable("resource_model_endpoint_changed")
        yield external_ready
        return
    if check_ready is not None:
        check_ready()
    modules = await asyncio.to_thread(load_verified, ("ocean_resources.configuration", "ocean_resources.model_client",
                                                    "ocean_resources.model_executor"))
    client, models = await asyncio.to_thread(modules["ocean_resources.configuration"].read_client, path)
    target = _target(backend, model, models)
    if target is None:
        raise ResourceHostUnavailable("resource_model_endpoint_changed")
    def ready():
        if check_ready is not None:
            check_ready()
        if _target(backend, model, models) != target:
            raise ResourceHostUnavailable("resource_model_endpoint_changed")
    # Only the runtime's existing call-scoped, checked warmup capability may
    # request staged loading. Ordinary turns retain full-profile admission.
    staged = warmup is not None and warmup.get("allow_cold") is True
    if staged and (warmup.get("task") is not asyncio.current_task()
            or warmup.get("backend") is not backend or warmup.get("model") != model
            or warmup.get("chat_id") != str(chat_id) or not callable(warmup.get("check"))
            or not target.get("load_policy_sha256") or backend.num_ctx != target["context_tokens"]):
        raise ResourceHostUnavailable("resource_model_load_not_authorized")
    factory = modules["ocean_resources.model_client"].model_turn
    if staged:
        extra = await asyncio.to_thread(load_verified, ("ocean_resources.model_load_client",))
        factory = extra["ocean_resources.model_load_client"].model_load_turn
    from hub._services.chat.resource_model_port import GuardedModelPort
    spec = modules["ocean_resources.model_executor"].ModelSpec(**{
        k: target[k] for k in ("model", "digest", "context_tokens", "port")})
    ticket = None
    try:
        # Never use private chat content/identifiers as the native workload ID.
        async with factory(client, target["socket_id"], "bach-model", priority,
                           check_ready=ready) as ticket:
            await asyncio.to_thread(GuardedModelPort().verify_available, spec)
            if staged:
                permit = ticket["permit"]
                if (permit["policy_sha256"] != target["load_policy_sha256"]
                        or permit["spec"] != {k: target[k] for k in ("model", "digest", "context_tokens", "port")}):
                    raise ResourceHostUnavailable("resource_model_load_binding_changed")
                warmup["resource_load_ticket"] = ticket
                warmup["resource_load_check"] = lambda: GuardedModelPort().check_load_under_owner(spec, permit)
            def guarded_ready():
                ready()
                renewal = ticket.get("renewal") if isinstance(ticket, dict) else None
                if renewal is not None and renewal.done():
                    raise ResourceHostUnavailable("resource_model_lease_unavailable")
                if staged:
                    from hub._services.chat.local_resource_reserve import read_policy
                    if (warmup["check"]() or time.monotonic() >= ticket["permit"]["deadline"]
                            or read_policy()[1] != ticket["permit"]["policy_sha256"]):
                        raise ResourceHostUnavailable("resource_model_load_capability_changed")
            guarded_ready()
            yield guarded_ready
            if staged:
                guarded_ready()
                ticket["successful"] = (isinstance(warmup.get("result"), dict)
                                          and warmup["result"].get("state") == "loaded"
                                          and ticket.get("transport_terminal") is True)
        if staged and not ticket["successful"] and isinstance(warmup.get("result"), dict):
            if warmup["result"].get("state") == "loaded":
                warmup["result"]["state"] = "resource_load_aborted"
            warmup["result"]["cleanup_verified"] = ticket.get("completion", {}).get("state") == "RETURN_REQUESTED"
    except Exception as exc:
        if staged and ticket is not None and ticket.get("permit"):
            if ticket.get("completion", {}).get("state") == "RETURN_REQUESTED":
                warmup["result"] = {"state": "resource_load_aborted", "cleanup_verified": True}
                raise ResourceHostUnavailable("resource_load_aborted") from exc
            warmup["result"] = {"state": "resource_recovery_hold", "cleanup_verified": False}
            raise ResourceHostUnavailable("resource_load_recovery_hold") from exc
        raise
