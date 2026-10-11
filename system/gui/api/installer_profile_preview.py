"""Authenticated GET surface for selection-only installer profile previews."""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from hub._services.installer_profile_preview_service import preview_selection_profile

router = APIRouter(tags=["installer-preview"])
_PROFILE_ID = re.compile(r"[a-z][a-z0-9-]{0,79}\Z")


@router.get("/installer/profiles/{profile_id}/preview")
def get_installer_profile_preview(profile_id: str, request: Request) -> dict:
    """Return a read-only selection preview; this endpoint cannot install."""
    from .unified_api import _require_memory_device

    _require_memory_device(request)
    if not _PROFILE_ID.fullmatch(profile_id):
        raise HTTPException(status_code=422, detail="Ungültige Profil-ID")
    return preview_selection_profile(profile_id)
