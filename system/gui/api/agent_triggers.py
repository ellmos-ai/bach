# SPDX-License-Identifier: MIT
"""Device-authenticated projection of the external scheduler's trigger authority.

No legacy scheduler database, migrations, executor calls or provider starts.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from hub import scheduler_provider

router = APIRouter(prefix="/api/agent-triggers", tags=["agent-triggers"])
SCHEMA = "bach.agent-triggers.v1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}\Z")
_CONFIG = {
    "agent_id",
    "schedule",
    "executor",
    "payload",
    "enabled",
    "authorities",
    "lease_seconds",
    "timeout_seconds",
}
_FIELDS = _CONFIG | {"id", "version", "revision", "deleted"}
_SECRET_KEYS = {
    "token",
    "api_key",
    "apikey",
    "password",
    "secret",
    "authorization",
    "access_token",
    "refresh_token",
    "device_token",
    "operator_token",
}


def _error(status: int, state: str, reason: str):
    raise HTTPException(
        status,
        detail={
            "schema": "bach.agent-triggers.error.v1",
            "state": state,
            "reason_code": reason,
        },
    )


def _authorize(request: Request):
    from .unified_api import _require_memory_device

    _require_memory_device(request)


def _identifier(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        _error(400, "invalid", "invalid_identifier")
    return value


def _version(value, *, create=False):
    if type(value) is not int or (value != 0 if create else value < 1):
        _error(400, "invalid", "invalid_expected_version")
    return value


def _no_credentials(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower().replace("-", "_") in _SECRET_KEYS:
                raise ValueError("credential_field")
            _no_credentials(child)
    elif isinstance(value, list):
        for child in value:
            _no_credentials(child)


def _transport_credentials(request: Request):
    """Use the same whitespace normalization as device/session authentication."""
    header = request.headers.get("Authorization", "").strip()
    credentials = [request.cookies.get("bach_device_token", "").strip()]
    if header.startswith("Bearer "):
        credentials.append(header[7:].strip())
    return tuple(dict.fromkeys(value for value in credentials if value))


def _contains_transport_credential(value, credentials):
    if isinstance(value, str):
        return any(credential in value for credential in credentials)
    if isinstance(value, dict):
        return any(
            _contains_transport_credential(key, credentials)
            or _contains_transport_credential(child, credentials)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_transport_credential(child, credentials) for child in value)
    return False


def _reject_transport_credentials(request: Request, payload, *, response=False):
    """Never persist or echo the request credential, including JSON object keys."""
    if _contains_transport_credential(payload, _transport_credentials(request)):
        if response:
            _error(503, "unavailable", "credential_in_response")
        _error(400, "invalid", "credential_in_payload")


async def _checked_response(request: Request, *args, **kwargs):
    result = await asyncio.to_thread(_execute, *args, **kwargs)
    _reject_transport_credentials(request, result, response=True)
    return result


def _provider():
    """Obtain configuration APIs only. Constructors must not initialize state."""
    if not scheduler_provider.probe_scheduler_provider().external:
        _error(503, "unavailable", "provider_unavailable")
    module = scheduler_provider.load_external_scheduler()
    for name in (
        "SchedulerStore",
        "AgentTriggers",
        "DefinitionConflict",
        "executor_names",
    ):
        if not hasattr(module, name):
            _error(503, "unavailable", "provider_unavailable")
    configured = os.environ.get("BACH_EXTERNAL_SCHEDULER_DB")
    path = (
        Path(configured).expanduser().resolve()
        if configured
        else Path(__file__).resolve().parents[2]
        / "data"
        / "scheduler_external"
        / "state.db"
    )
    store = module.SchedulerStore(path)
    return module, store, module.AgentTriggers(store)


def _snapshot(value):
    if not isinstance(value, dict) or not _FIELDS.issubset(value):
        _error(503, "unavailable", "invalid_provider_snapshot")
    if (
        not isinstance(value["id"], str)
        or not _ID.fullmatch(value["id"])
        or not isinstance(value["agent_id"], str)
        or not _ID.fullmatch(value["agent_id"])
        or type(value["version"]) is not int
        or value["version"] < 1
        or type(value["revision"]) is not int
        or value["revision"] < 1
        or type(value["enabled"]) is not bool
        or type(value["deleted"]) is not bool
        or not isinstance(value["schedule"], dict)
        or not isinstance(value["payload"], dict)
        or not isinstance(value["authorities"], list)
        or not isinstance(value["executor"], str)
        or type(value["lease_seconds"]) is not int
        or value["lease_seconds"] <= 0
        or type(value["timeout_seconds"]) is not int
        or value["timeout_seconds"] <= 0
    ):
        _error(503, "unavailable", "invalid_provider_snapshot")
    # Never expose provider-specific fields, exception text, filesystem paths or credentials.
    result = {key: value[key] for key in _FIELDS}
    try:
        _no_credentials(result)
    except (ValueError, TypeError, AttributeError):
        _error(503, "unavailable", "invalid_provider_snapshot")
    return result


def _response(**values):
    return {
        "schema": SCHEMA,
        "provider": "ellmos-scheduler",
        "source": "external_scheduler",
        "state": "available",
        **values,
    }


def _config(value, module):
    if not isinstance(value, dict) or not value or not set(value).issubset(_CONFIG):
        _error(400, "invalid", "invalid_changes")
    if "agent_id" in value:
        _identifier(value["agent_id"])
    if "enabled" in value and type(value["enabled"]) is not bool:
        _error(400, "invalid", "invalid_enabled")
    if "executor" in value and value["executor"] not in module.executor_names():
        _error(400, "invalid", "unknown_executor")
    _no_credentials(value)
    return value


def _execute(operation, identifier=None, payload=None, agent_id=None):
    module = None
    try:
        module, store, triggers = _provider()
        if operation == "list":
            if agent_id is not None:
                _identifier(agent_id)
            snapshots = [_snapshot(row) for row in triggers.list(agent_id=agent_id)]
            if agent_id is not None and any(
                row["agent_id"] != agent_id for row in snapshots
            ):
                _error(503, "unavailable", "readback_unverified")
            return _response(triggers=snapshots)
        identifier = _identifier(identifier)
        if operation == "get":
            current = _snapshot(triggers.get(identifier))
            if current["id"] != identifier:
                _error(503, "unavailable", "readback_unverified")
            return _response(trigger=current)
        if not isinstance(payload, dict):
            _error(400, "invalid", "invalid_request")
        _no_credentials(payload)
        # Readiness uses the provider's native RO API: a missing store/schema must
        # not be created as a side effect of attempting a write.
        triggers.list()
        expected = _version(
            payload.get("expected_version"), create=operation == "create"
        )
        if operation == "create":
            if not {
                "id",
                "expected_version",
                "agent_id",
                "schedule",
                "executor",
            }.issubset(payload):
                _error(400, "invalid", "missing_fields")
            if not set(payload).issubset(_CONFIG | {"id", "expected_version"}):
                _error(400, "invalid", "unknown_fields")
            config = _config(
                {key: val for key, val in payload.items() if key in _CONFIG}, module
            )
            mutation = triggers.create(identifier, **config)
        elif operation == "update":
            if set(payload) != {"expected_version", "changes"}:
                _error(400, "invalid", "unknown_fields")
            mutation = triggers.update(
                identifier,
                expected_version=expected,
                changes=_config(payload["changes"], module),
            )
        elif operation == "delete":
            if set(payload) != {"expected_version"}:
                _error(400, "invalid", "unknown_fields")
            mutation = triggers.delete(identifier, expected_version=expected)
        else:
            required = {"expected_version", "event_id", "event_type", "source"}
            if not required.issubset(payload) or not set(payload).issubset(
                required | {"lineage"}
            ):
                _error(400, "invalid", "invalid_delivery")
            before = _snapshot(triggers.get(identifier))
            if before["id"] != identifier:
                _error(503, "unavailable", "readback_unverified")
            delivery = triggers.deliver(identifier, **payload)
            after = _snapshot(triggers.get(identifier))
            if (
                after["id"] != identifier
                or before != after
                or after["version"] != expected
            ):
                _error(503, "unavailable", "readback_unverified")
            if (
                not isinstance(delivery, dict)
                or delivery.get("state") != "materialized"
                or type(delivery.get("duplicate")) is not bool
                or not isinstance(delivery.get("job_id"), str)
            ):
                _error(503, "unavailable", "delivery_unverified")
            materialized = next(
                (
                    row
                    for row in store.list_jobs()
                    if row.get("id") == delivery["job_id"]
                ),
                None,
            )
            try:
                job_payload = json.loads(materialized["payload_json"])
                provenance = job_payload["_scheduler_event"]
                definition = job_payload["_agent_trigger"]
                verified = (
                    definition["id"] == identifier
                    and provenance["trigger_id"] == identifier
                    and all(
                        provenance[key] == payload[key]
                        for key in ("event_id", "event_type", "source")
                    )
                    and provenance["lineage"]
                    == [*(payload.get("lineage") or []), identifier]
                    and (
                        delivery["duplicate"]
                        or definition["revision"] == after["revision"]
                    )
                )
            except (KeyError, TypeError, ValueError):
                verified = False
            if not verified:
                _error(503, "unavailable", "delivery_unverified")
            return _response(
                trigger=after,
                delivery={
                    key: delivery[key] for key in ("job_id", "duplicate", "state")
                },
                ack={
                    "configuration_saved": False,
                    "readback_verified": True,
                    "worker_started": False,
                },
            )
        confirmed = _snapshot(triggers.get(identifier))
        expected_next = 1 if operation == "create" else expected + 1
        if (
            confirmed["id"] != identifier
            or _snapshot(mutation) != confirmed
            or confirmed["version"] != expected_next
            or (operation == "delete" and not confirmed["deleted"])
        ):
            _error(503, "unavailable", "readback_unverified")
        return _response(
            trigger=confirmed,
            ack={
                "configuration_saved": True,
                "readback_verified": True,
                "worker_started": False,
            },
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - provider exceptions may contain private data
        if module is not None and isinstance(exc, module.DefinitionConflict):
            _error(409, "conflict", "version_conflict")
        if isinstance(exc, KeyError):
            _error(404, "not_found", "trigger_not_found")
        if isinstance(exc, ValueError):
            _error(400, "invalid", "invalid_request")
        if isinstance(exc, sqlite3.Error):
            _error(503, "unavailable", "schema_unavailable")
        _error(503, "unavailable", "provider_unavailable")


@router.get("")
async def list_triggers(request: Request, agent_id: str | None = None):
    _authorize(request)
    return await _checked_response(request, "list", agent_id=agent_id)


@router.get("/{identifier:path}")
async def get_trigger(identifier: str, request: Request):
    _authorize(request)
    return await _checked_response(request, "get", identifier)


@router.post("")
async def create_trigger(request: Request, payload: Any = Body(...)):  # noqa: B008 - FastAPI injection
    _authorize(request)
    _reject_transport_credentials(request, payload)
    return await _checked_response(
        request,
        "create",
        payload.get("id") if isinstance(payload, dict) else None,
        payload,
    )


@router.put("/{identifier:path}")
async def update_trigger(identifier: str, request: Request, payload: Any = Body(...)):  # noqa: B008 - FastAPI injection
    _authorize(request)
    _reject_transport_credentials(request, payload)
    return await _checked_response(request, "update", identifier, payload)


@router.delete("/{identifier:path}")
async def delete_trigger(identifier: str, request: Request, payload: Any = Body(...)):  # noqa: B008 - FastAPI injection
    _authorize(request)
    _reject_transport_credentials(request, payload)
    return await _checked_response(request, "delete", identifier, payload)


@router.post("/{identifier:path}/deliver")
async def deliver_event(identifier: str, request: Request, payload: Any = Body(...)):  # noqa: B008 - FastAPI injection
    """Explicit authenticated action, never evidence of trusted task ingestion."""
    _authorize(request)
    _reject_transport_credentials(request, payload)
    return await _checked_response(request, "deliver", identifier, payload)
