"""Authenticated projection; status reads never initialize the scheduler store."""

from pathlib import Path

from fastapi import APIRouter, Request
from hub._services.docs.maintenance_runtime import readonly_status
from hub.bach_paths import BACH_DB

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])


@router.get("/status")
def status(request: Request):
    from .unified_api import _require_memory_device

    _require_memory_device(request)
    root = Path(__file__).resolve().parents[3]
    return readonly_status(BACH_DB.parent / "maintenance", root=root)
