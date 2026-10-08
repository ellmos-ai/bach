"""Device-authenticated metadata reads from the canonical policy-registry."""
import asyncio
from fastapi import APIRouter, HTTPException, Query
from hub._services.policy_registry_adapter import observe, PolicyProviderUnavailable, PolicySnapshotChanged

router = APIRouter(prefix="/api/governance", tags=["policy-registry"])


async def read_registry(**options):
    try:
        return await asyncio.to_thread(observe, **options)
    except PolicyProviderUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    except PolicySnapshotChanged as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/policy-registry")
async def registry_entries(scope: str | None = Query(None, max_length=256),
        consumer: str | None = Query(None, max_length=256), query: str = Query("", max_length=512),
        kind: str | None = Query(None, pattern="^(policy|rule|decision|evidence|decision-candidate)$")):
    return await read_registry(scope=scope, consumer=consumer, query=query, kind=kind)


@router.get("/effective-policy")
async def effective_policy(scope: str = Query(..., min_length=1, max_length=256),
        consumer: str | None = Query(None, max_length=256), query: str = Query("", max_length=512)):
    return await read_registry(scope=scope, consumer=consumer, query=query, effective=True)
