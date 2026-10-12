# SPDX-License-Identifier: MIT
"""Authenticated GUI transport for the report provider in the Control owner."""
from __future__ import annotations

import asyncio
import json
import math
import re
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request

from hub._services.document.report_provider_adapter import ReportProviderAdapter
from hub._services.document.report_provider_contract import (
    ReportApproval,
    ReportContractError,
    ReportRequest,
    WatcherConfig,
    _opaque,
)


MAX_REPORT_REQUEST_BYTES = 256 * 1024
MAX_CONTROL_RESPONSE_BYTES = 512 * 1024
router = APIRouter(prefix="/api/reports", tags=["reports"])


def _error(status_code: int, code: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code})


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_field")
        result[key] = value
    return result


def _reject_constant(_value: str):
    raise ValueError("nonstandard_json_constant")


def _finite_json_float(raw: str) -> float:
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError("nonfinite_json_number")
    return value


def _validate_container_depth(value: Any, *, maximum: int = 32) -> None:
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if not isinstance(current, (dict, list)):
            continue
        if depth > maximum:
            raise ValueError("json_container_too_deep")
        children = current.values() if isinstance(current, dict) else current
        stack.extend((child, depth + 1) for child in children)


async def _authorized_token(request: Request) -> str:
    """Verify the active device before reading any query or request body."""
    try:
        from gui.api.unified_api import _require_memory_device_token

        return await asyncio.to_thread(_require_memory_device_token, request)
    except HTTPException as exc:
        if exc.status_code in {401, 403}:
            raise _error(exc.status_code, "device_auth_required" if exc.status_code == 401
                         else "device_auth_invalid") from None
        raise _error(503, "device_auth_unavailable") from None
    except Exception:
        raise _error(503, "device_auth_unavailable") from None


async def _read_object(request: Request) -> dict[str, Any]:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise _error(415, "json_required")
    raw = bytearray()
    try:
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_REPORT_REQUEST_BYTES:
                raise _error(413, "request_too_large")
            raw.extend(chunk)
    except HTTPException:
        raise
    except Exception:
        raise _error(400, "body_unavailable") from None
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_finite_json_float,
        )
        _validate_container_depth(value)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise _error(400, "invalid_json") from None
    if not isinstance(value, dict):
        raise _error(422, "object_required")
    return value


class _ControlReportProvider:
    """Fixed-path client for the authenticated Control owner; no URL overrides."""

    def __init__(self, device_token: str) -> None:
        self._device_token = device_token

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            from gui.api.worker_status_adapter import _control_context

            base, headers, ready_check = await asyncio.to_thread(
                _control_context, self._device_token,
            )
            async with httpx.AsyncClient(
                timeout=8.0, trust_env=False, follow_redirects=False,
            ) as client:
                status_response = await client.get(base + "/status", headers=headers)
                status_payload = status_response.json() if status_response.status_code == 200 else None
                if status_response.status_code != 200 or not ready_check(status_payload):
                    raise RuntimeError("control_identity_unavailable")
                if method != "GET":
                    auth_response = await client.get(base + "/auth/check", headers=headers)
                    auth_payload = auth_response.json() if auth_response.status_code == 200 else None
                    if (auth_response.status_code != 200 or not isinstance(auth_payload, dict)
                            or auth_payload.get("authenticated") is not True):
                        raise RuntimeError("control_auth_unavailable")
                response = await client.request(
                    method, f"{base}/{endpoint}", params=params, json=body,
                    headers=headers,
                )
            if len(response.content) > MAX_CONTROL_RESPONSE_BYTES:
                raise RuntimeError("control_response_too_large")
            if not 200 <= response.status_code < 300:
                raise RuntimeError("control_request_rejected")
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("control_response_invalid")
            return payload
        except Exception:
            # Do not leak URL, authorization headers, response text, or provider errors.
            raise RuntimeError("control_report_provider_unavailable") from None

    async def capabilities(self):
        return await self._request("GET", "reports/capabilities")

    async def list_sources(self, subject_ref: str):
        return await self._request(
            "GET", "reports/sources", params={"subject_ref": subject_ref},
        )

    async def prepare(self, request: dict[str, Any]):
        return await self._request("POST", "reports/prepare", body=request)

    async def finish(self, run_id: str, approval: dict[str, Any]):
        return await self._request(
            "POST", "reports/finish", body={"run_id": run_id, "approval": approval},
        )

    async def status(self, run_id: str):
        return await self._request("GET", "reports/status", params={"run_id": run_id})

    async def cleanup(self, run_id: str, approval: dict[str, Any]):
        return await self._request(
            "POST", "reports/cleanup", body={"run_id": run_id, "approval": approval},
        )

    async def watcher_status(self):
        return await self._request("GET", "reports/watcher/status")

    async def watcher_configure(self, config: dict[str, Any]):
        return await self._request("POST", "reports/watcher/configure", body=config)

    async def watcher_tick(self):
        return await self._request("POST", "reports/watcher/tick", body={})


def _adapter(token: str) -> ReportProviderAdapter:
    return ReportProviderAdapter(_ControlReportProvider(token))


def _query_value(request: Request, key: str) -> str:
    items = request.query_params.multi_items()
    if len(items) != 1 or items[0][0] != key or not items[0][1]:
        raise _error(422, "invalid_query")
    return items[0][1]


def _no_query(request: Request) -> None:
    if request.query_params:
        raise _error(422, "invalid_query")


@router.get("/capabilities")
async def get_report_capabilities(request: Request):
    token = await _authorized_token(request)
    _no_query(request)
    return await _adapter(token).capabilities()


@router.get("/sources")
async def get_report_sources(request: Request):
    token = await _authorized_token(request)
    subject_ref = _query_value(request, "subject_ref")
    if re.fullmatch(r"sub_[0-9a-f]{48}", subject_ref) is None:
        raise _error(422, "invalid_subject_ref")
    return await _adapter(token).list_sources(subject_ref)


@router.get("/status")
async def get_report_status(request: Request):
    token = await _authorized_token(request)
    run_id = _query_value(request, "run_id")
    try:
        run_id = _opaque(run_id, "run_id")
    except ReportContractError:
        raise _error(422, "invalid_run_id") from None
    return await _adapter(token).status(run_id)


@router.get("/watcher/status")
async def get_report_watcher_status(request: Request):
    token = await _authorized_token(request)
    if request.query_params:
        raise _error(422, "invalid_query")
    return await _adapter(token).watcher_status()


@router.post("/prepare")
async def prepare_report(request: Request):
    token = await _authorized_token(request)
    _no_query(request)
    payload = await _read_object(request)
    try:
        parsed = ReportRequest.from_wire(payload)
    except ReportContractError:
        raise _error(422, "invalid_report_request") from None
    return await _adapter(token).prepare(parsed.to_wire())


@router.post("/finish")
async def finish_report(request: Request):
    token = await _authorized_token(request)
    _no_query(request)
    payload = await _read_object(request)
    if set(payload) != {"run_id", "approval"} or not isinstance(payload.get("approval"), dict):
        raise _error(422, "invalid_finish_request")
    try:
        run_id = _opaque(payload["run_id"], "run_id")
        approval = ReportApproval.from_wire(payload["approval"])
    except ReportContractError:
        raise _error(422, "invalid_finish_request") from None
    return await _adapter(token).finish(run_id, approval.to_wire())


@router.post("/cleanup")
async def cleanup_report(request: Request):
    token = await _authorized_token(request)
    _no_query(request)
    payload = await _read_object(request)
    if set(payload) != {"run_id", "approval"} or not isinstance(payload.get("approval"), dict):
        raise _error(422, "invalid_cleanup_request")
    try:
        run_id = _opaque(payload["run_id"], "run_id")
        # Reuse the contract parser used by the provider adapter, without issuing consent.
        from hub._services.document.report_provider_contract import CleanupApproval

        approval = CleanupApproval.from_wire(payload["approval"], expected_run_id=run_id)
    except ReportContractError:
        raise _error(422, "invalid_cleanup_request") from None
    return await _adapter(token).cleanup(run_id, approval.to_wire())


@router.post("/watcher/configure")
async def configure_report_watcher(request: Request):
    token = await _authorized_token(request)
    _no_query(request)
    payload = await _read_object(request)
    try:
        config = WatcherConfig.from_wire(payload)
    except ReportContractError:
        raise _error(422, "invalid_watcher_config") from None
    return await _adapter(token).watcher_configure(config.to_wire())


@router.post("/watcher/tick")
async def tick_report_watcher(request: Request):
    token = await _authorized_token(request)
    _no_query(request)
    payload = await _read_object(request)
    if payload:
        raise _error(422, "invalid_watcher_tick")
    return await _adapter(token).watcher_tick()
