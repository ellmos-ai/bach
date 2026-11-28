"""FastAPI-Preflight-Route für den Merge-Agenten (Task #2039).

POST /api/system/core-agents/merge-agent/preflight

Der Endpunkt nimmt den PR-Kontext plus Review-Freigaben entgegen und liefert
das Preflight-Prüfprotokoll zurück. Credential-Material im Request-Body wird
grundsätzlich verworfen (HTTP 400): erlaubt sind nur Secret-Provider-
Referenzen (Provider + Key), nie Geheimniswerte.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List

from fastapi import APIRouter, HTTPException, Request

from hub.merge_agent_service import (
    MERGE_AGENT_API_PREFIX,
    MERGE_AGENT_PREFLIGHT_PATH,
    ROLE_MERGE_AGENT_BLUEPRINT,
    MergeAgentIdentity,
    MergeAgentService,
    MergeApproval,
    PullRequestContext,
    SecretProviderReference,
)

router = APIRouter(prefix=MERGE_AGENT_API_PREFIX, tags=["merge-agent-preflight"])

PREFLIGHT_SCHEMA = "bach.merge-agent-preflight.v1"

_FORBIDDEN_BODY_KEYS = {
    "credential",
    "credentials",
    "secret",
    "secret_value",
    "token",
    "github_token",
    "access_token",
    "api_key",
    "password",
    "authorization",
}


def authorize(request: Request) -> None:
    """Standard-Zugriffsschutz, analog zur Agent-History-Route."""
    from .unified_api import _require_memory_device

    _require_memory_device(request)


def _iter_body_keys(value: Any) -> Iterator[Any]:
    if isinstance(value, dict):
        for key, sub in value.items():
            yield key
            yield from _iter_body_keys(sub)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_body_keys(item)


def _contains_credential_material(body: Any) -> bool:
    for key in _iter_body_keys(body):
        if isinstance(key, str) and key.strip().lower() in _FORBIDDEN_BODY_KEYS:
            return True
    return False


def _default_identity() -> MergeAgentIdentity:
    reference = SecretProviderReference("system", "github/merge_agent")
    return MergeAgentIdentity(
        principal=str(ROLE_MERGE_AGENT_BLUEPRINT["identity"]["principal"]),
        secret=reference,
    )


def _identity_from_body(payload: Any) -> MergeAgentIdentity:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Feld 'identity' muss ein JSON-Objekt sein.")
    base = _default_identity()
    principal = str(payload.get("principal") or base.principal).strip()
    reference_payload = payload.get("secret_provider_reference") or {}
    if not isinstance(reference_payload, dict):
        raise HTTPException(
            status_code=400,
            detail="Feld 'identity.secret_provider_reference' muss ein JSON-Objekt sein.",
        )
    provider = str(reference_payload.get("provider_name") or base.secret.provider_name).strip()
    secret_key = str(reference_payload.get("secret_key") or base.secret.secret_key).strip()
    return MergeAgentIdentity(
        principal=principal,
        secret=SecretProviderReference(provider, secret_key),
    )


def _context_from_body(payload: Any) -> PullRequestContext:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Feld 'pr' muss ein JSON-Objekt sein.")
    head_sha = str(payload.get("head_sha") or "").strip()
    if not head_sha:
        raise HTTPException(
            status_code=400,
            detail="Feld 'pr.head_sha' ist erforderlich und darf nicht leer sein.",
        )
    try:
        pr_number = int(payload.get("pr_number") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail="Feld 'pr.pr_number' muss eine Ganzzahl sein."
        ) from exc
    stacked_numbers = payload.get("stacked_pr_numbers") or []
    if not isinstance(stacked_numbers, list):
        raise HTTPException(
            status_code=400, detail="Feld 'pr.stacked_pr_numbers' muss eine Liste sein."
        )
    try:
        stacked_nums = [int(n) for n in stacked_numbers]
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Feld 'pr.stacked_pr_numbers' muss Ganzzahlen enthalten.",
        ) from exc
    ci_states = payload.get("ci_check_states") or {}
    if not isinstance(ci_states, dict):
        raise HTTPException(
            status_code=400, detail="Feld 'pr.ci_check_states' muss ein Objekt sein."
        )
    return PullRequestContext(
        repository=str(payload.get("repository") or ""),
        pr_number=pr_number,
        author_principal=str(payload.get("author_principal") or ""),
        head_branch=str(payload.get("head_branch") or ""),
        base_branch=str(payload.get("base_branch") or ""),
        head_sha=head_sha,
        is_draft=bool(payload.get("is_draft") or False),
        stacked=bool(payload.get("stacked") or False),
        stacked_pr_numbers=stacked_nums,
        ci_check_states={str(k): str(v) for k, v in ci_states.items()},
    )


def _approvals_from_body(payload: Any) -> List[MergeApproval]:
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise HTTPException(status_code=400, detail="Feld 'approvals' muss eine Liste sein.")
    approvals: List[MergeApproval] = []
    for item in payload:
        if not isinstance(item, dict):
            raise HTTPException(
                status_code=400, detail="Jede Freigabe in 'approvals' muss ein JSON-Objekt sein."
            )
        approver = str(item.get("approver") or "").strip()
        commit_sha = str(item.get("commit_sha") or "").strip()
        if not approver or not commit_sha:
            raise HTTPException(
                status_code=400,
                detail="Freigaben benötigen 'approver' und 'commit_sha'.",
            )
        expires_at = None
        ttl_minutes = item.get("ttl_minutes")
        if ttl_minutes is not None:
            if isinstance(ttl_minutes, bool):
                raise HTTPException(
                    status_code=400, detail="Feld 'ttl_minutes' muss eine Zahl sein."
                )
            try:
                minutes = float(ttl_minutes)
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=400, detail="Feld 'ttl_minutes' muss eine Zahl sein."
                ) from exc
            if not math.isfinite(minutes):
                raise HTTPException(
                    status_code=400, detail="Feld 'ttl_minutes' muss endlich sein."
                )
            try:
                expires_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
            except OverflowError as exc:
                raise HTTPException(
                    status_code=400, detail="Feld 'ttl_minutes' liegt außerhalb des gültigen Bereichs."
                ) from exc
        elif item.get("expires_at"):
            raw = str(item.get("expires_at")).strip()
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail="Feld 'expires_at' muss eine ISO-8601-Zeit sein.",
                ) from exc
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            expires_at = parsed
        revoked = item.get("revoked", False)
        if revoked is None:
            revoked = False
        if not isinstance(revoked, bool):
            raise HTTPException(
                status_code=400, detail="Feld 'revoked' muss ein Boolean sein."
            )
        approvals.append(
            MergeApproval(
                approver=approver,
                commit_sha=commit_sha,
                expires_at=expires_at,
                revoked=revoked,
            )
        )
    return approvals


@router.post(MERGE_AGENT_PREFLIGHT_PATH)
async def merge_agent_preflight(request: Request) -> Dict[str, Any]:
    """Führt den Merge-Preflight aus und liefert das Prüfprotokoll.

    Antwortstatus bleibt 200 auch bei ok=False: Verletzungen sind ein
    Geschäftsergebnis (Liste der Violations), kein Transportfehler.
    """
    authorize(request)

    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail="Ungültiger JSON-Request-Body."
        ) from exc

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Request-Body muss ein JSON-Objekt sein.")

    if _contains_credential_material(body):
        raise HTTPException(
            status_code=400,
            detail="Credential-Material im Request abgelehnt: nur Secret-Provider-Referenzen erlaubt.",
        )

    identity = _identity_from_body(body.get("identity") or {})
    pr = _context_from_body(body.get("pr") or {})
    approvals = _approvals_from_body(body.get("approvals"))

    service = MergeAgentService(identity)
    payload = service.evaluate_preflight(pr, approvals=approvals).to_dict()
    payload["schema"] = PREFLIGHT_SCHEMA
    return payload
