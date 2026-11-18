# SPDX-License-Identifier: MIT
"""BACH's native model-call boundary over the configured Ocean host authority."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from hub._services.ocean_resources_provider import load_verified


class ResourceHostUnavailable(RuntimeError):
    pass


def _target(backend, model, models):
    url = urlsplit(str(getattr(backend, "base_url", "")))
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
async def resource_model_turn(backend, model, chat_id, priority, *, check_ready=None):
    """Acquire before reserve polling/inference.lock; release after leaving it.

    An unset configuration preserves the existing path. An explicitly configured
    but unavailable/changed authority fails closed; there is no unbrokered retry.
    Conversation, worker task lease, model binding and budgets remain BACH-owned.
    """
    path = os.environ.get("BACH_RESOURCE_BROKER_CONFIG")
    if not path:
        yield check_ready
        return
    url = urlsplit(str(getattr(backend, "base_url", "")))
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
    # Never use private chat content/identifiers as the native workload identity.
    async with modules["ocean_resources.model_client"].model_turn(
            client, target["socket_id"], "bach-model", priority, check_ready=ready):
        from hub._services.chat.resource_model_port import GuardedModelPort
        spec = modules["ocean_resources.model_executor"].ModelSpec(**{k: v for k, v in target.items() if k != "socket_id"})
        await asyncio.to_thread(GuardedModelPort().verify_available, spec)
        ready()
        yield ready
