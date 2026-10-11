"""GET /api/capabilities/catalog: read-only ``bach.catalog.v1`` projection (#2016).

Authentication is not done here: like governance_registry.py, this route stays outside
DeviceAuthMiddleware.EXEMPT_API_PATHS, so the middleware demands a registered device token.
"""
import asyncio
from fastapi import APIRouter, HTTPException, Query
from hub._services.catalog_projection import KINDS, observe

router = APIRouter(prefix="/api/capabilities", tags=["catalog"])


@router.get("/catalog")
async def capabilities_catalog(kind: str | None = Query(None, pattern="^(" + "|".join(KINDS) + ")$"),
                               host: str | None = Query(None, min_length=1, max_length=80)):
    try:
        return await asyncio.to_thread(observe, kind=kind, host=host)
    except ValueError:
        raise HTTPException(400, "unsupported_kind") from None
