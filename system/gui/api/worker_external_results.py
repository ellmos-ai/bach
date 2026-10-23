# SPDX-License-Identifier: MIT
"""Bounded, operator-authorized external result API; no inference or acceptance."""
from __future__ import annotations

import asyncio
import base64
import binascii
import json

from fastapi import APIRouter, HTTPException, Request, Response
from hub._services import worker_external_evidence as evidence
from hub._services import worker_external_results as service
from hub._services import worker_policy_settings as settings
from hub._services import worker_review_identity as identity

router = APIRouter(tags=["worker-external-results"])
MAX_BODY_BYTES = 3 * 1024 * 1024
_PRIVATE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _db_path():
    from hub.bach_paths import BACH_DB
    return BACH_DB


async def _call(function, *args, **kwargs):
    try:
        return await asyncio.to_thread(function, *args, db_path=_db_path(), **kwargs)
    except PermissionError as exc:
        raise HTTPException(403, "Gesonderte Operatorberechtigung erforderlich",
                            headers=_PRIVATE_HEADERS) from exc
    except settings.PolicyConflict as exc:
        raise HTTPException(409, "Ergebnis- oder Konfigurationsrevision wurde geändert",
                            headers=_PRIVATE_HEADERS) from exc
    except settings.PolicyUnavailable as exc:
        raise HTTPException(503, "Kanonischer Ergebnisbeleg nicht verfügbar",
                            headers=_PRIVATE_HEADERS) from exc
    except KeyError as exc:
        raise HTTPException(404, "Ergebnisbeleg nicht gefunden", headers=_PRIVATE_HEADERS) from exc
    except (ValueError, TypeError) as exc:
        # Do not echo private input, identifiers or tokens into error bodies.
        raise HTTPException(400, "Ungültiger externer Ergebnisauftrag",
                            headers=_PRIVATE_HEADERS) from exc


async def _operator(request, response):
    from .unified_api import _require_memory_device
    _require_memory_device(request)
    response.headers.update(_PRIVATE_HEADERS)
    token = request.headers.get("X-BACH-Result-Operator", "")
    await _call(service.authorize, operator_token=token)
    return token


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate key")
        result[key] = value
    return result


async def _payload(request):
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(415, "JSON erforderlich", headers=_PRIVATE_HEADERS)
    length = request.headers.get("content-length")
    if length is not None:
        try:
            size = int(length)
        except ValueError:
            raise HTTPException(400, "Ungültige Inhaltslänge", headers=_PRIVATE_HEADERS) from None
        if size < 0 or size > MAX_BODY_BYTES:
            raise HTTPException(413, "Ergebnisauftrag ist zu groß", headers=_PRIVATE_HEADERS)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY_BYTES:
            raise HTTPException(413, "Ergebnisauftrag ist zu groß", headers=_PRIVATE_HEADERS)
        body.extend(chunk)
    try:
        def invalid_constant(_):
            raise ValueError("Nonfinite number")
        value = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=invalid_constant)
        if type(value) is not dict:
            raise ValueError("Object required")
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(400, "Ungültiges JSON-Objekt", headers=_PRIVATE_HEADERS) from None


@router.get("/system/worker-model-principal-catalog")
async def get_catalog(request: Request, response: Response):
    token = await _operator(request, response)
    return await _call(service.read_catalog, operator_token=token)


@router.put("/system/worker-model-principal-catalog")
async def put_catalog(request: Request, response: Response):
    token = await _operator(request, response)
    return await _call(identity.write_model_principal_catalog, await _payload(request),
                       operator_token=token)


@router.get("/system/worker-external-principals")
async def get_sources(request: Request, response: Response):
    token = await _operator(request, response)
    return await _call(service.read_sources, operator_token=token)


@router.put("/system/worker-external-principals")
async def put_sources(request: Request, response: Response):
    token = await _operator(request, response)
    return await _call(evidence.write_external_principals, await _payload(request),
                       operator_token=token)


def _artifact(payload):
    settings._object(payload, {"media_type", "content_base64"})
    value = payload["content_base64"]
    if type(value) is not str or len(value) > 4 * ((evidence.MAX_ARTIFACT_BYTES + 2) // 3):
        raise ValueError("Invalid artifact size")
    try:
        content = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Invalid base64") from None
    # Canonical encoding prevents alternative encodings for the same bytes.
    if base64.b64encode(content).decode("ascii") != value:
        raise ValueError("Noncanonical base64")
    return content


@router.post("/system/worker-external-artifacts")
async def store_artifact(request: Request, response: Response):
    token = await _operator(request, response)
    payload = await _payload(request)
    try:
        content = _artifact(payload)
    except (ValueError, TypeError):
        raise HTTPException(400, "Ungültiges privates Herkunftsartefakt",
                            headers=_PRIVATE_HEADERS) from None
    return await _call(evidence.store_external_artifact, content,
                       media_type=payload["media_type"], operator_token=token)


@router.get("/system/worker-external-artifacts/{artifact_id}")
async def get_artifact(artifact_id: str, request: Request, response: Response):
    token = await _operator(request, response)
    result = await _call(evidence.read_external_artifact, artifact_id, operator_token=token)
    content = result.pop("content")
    return {**result, "content_base64": base64.b64encode(content).decode("ascii")}


@router.post("/tasks/{task_id}/result/external-attestation")
async def attest_result(task_id: int, request: Request, response: Response):
    token = await _operator(request, response)
    return await _call(service.attest, task_id, await _payload(request), operator_token=token)


@router.post("/tasks/{task_id}/result/external-review")
async def prepare_review(task_id: int, request: Request, response: Response):
    token = await _operator(request, response)
    return await _call(service.prepare_review, task_id, await _payload(request), operator_token=token)
