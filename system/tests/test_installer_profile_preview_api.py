"""The installer preview API stays authenticated and fail-closed."""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from hub._services import installer_profile_preview_service as service

_SCHEMA = "bach.installer.profile-preview.v1"
_PROFILE = "memory"


def _unavailable(profile_id: str, reason_code: str) -> dict:
    return {
        "schema": _SCHEMA,
        "status": "unavailable",
        "profile_id": profile_id,
        "reason_code": reason_code,
        "apply_allowed": False,
        "deployable": False,
    }


def _app():
    from gui.api import installer_profile_preview, unified_api

    parent = unified_api.router
    original_routes = list(parent.routes)
    try:
        route_path = "/api/installer/profiles/{profile_id}/preview"
        if not any(getattr(route, "path", None) == route_path for route in parent.routes):
            parent.include_router(installer_profile_preview.router)
        app = FastAPI()
        app.include_router(parent)
        return app
    finally:
        parent.routes[:] = original_routes


def test_composed_get_router_calls_native_factory_without_client_paths(monkeypatch):
    from gui.api import unified_api

    auth_paths = []
    monkeypatch.setattr(
        unified_api,
        "_require_memory_device",
        lambda request: auth_paths.append(request.url.path),
    )
    calls = []

    def native_preview(profile_id, *, instance_path):
        calls.append((profile_id, instance_path))
        return _unavailable(profile_id, "native_instance_source_required")

    monkeypatch.setattr(
        service,
        "_load_factory",
        lambda: SimpleNamespace(preview_profile_from_native_runtime=native_preview),
    )

    response = TestClient(_app()).get(f"/api/installer/profiles/{_PROFILE}/preview")

    assert response.status_code == 200
    assert response.json() == _unavailable(_PROFILE, "native_instance_source_required")
    assert calls == [(_PROFILE, None)]
    assert auth_paths == [f"/api/installer/profiles/{_PROFILE}/preview"]


def test_auth_rejection_prevents_factory_call(monkeypatch):
    from gui.api import unified_api

    calls = []
    monkeypatch.setattr(
        unified_api,
        "_require_memory_device",
        lambda _request: (_ for _ in ()).throw(HTTPException(status_code=401)),
    )
    monkeypatch.setattr(service, "_load_factory", lambda: calls.append("loaded"))

    response = TestClient(_app()).get(f"/api/installer/profiles/{_PROFILE}/preview")

    assert response.status_code == 401
    assert calls == []


def test_invalid_profile_id_is_rejected_before_factory_call(monkeypatch):
    from gui.api import unified_api

    calls = []
    monkeypatch.setattr(unified_api, "_require_memory_device", lambda _request: None)
    monkeypatch.setattr(service, "_load_factory", lambda: calls.append("loaded"))

    response = TestClient(_app()).get("/api/installer/profiles/Bad_ID/preview")

    assert response.status_code == 422
    assert response.json()["detail"] == "Ungültige Profil-ID"
    assert calls == []


def test_missing_optional_installer_package_is_safe_and_does_not_echo_error(monkeypatch, caplog):
    def fail_import():
        raise ModuleNotFoundError("PRIVATE_TOKEN=do-not-return")

    monkeypatch.setattr(service, "_load_factory", fail_import)
    result = service.preview_selection_profile(_PROFILE)

    assert result == _unavailable(_PROFILE, "native_installer_unavailable")
    assert "PRIVATE_TOKEN" not in str(result)
    assert "PRIVATE_TOKEN" not in caplog.text


def test_factory_cannot_promote_preview_to_apply_authority(monkeypatch):
    monkeypatch.setattr(
        service,
        "_load_factory",
        lambda: SimpleNamespace(
            preview_profile_from_native_runtime=lambda profile_id, **_kwargs: {
                **_unavailable(profile_id, "native_instance_source_required"),
                "apply_allowed": True,
                "deployable": True,
            }
        ),
    )

    assert service.preview_selection_profile(_PROFILE) == _unavailable(
        _PROFILE, "native_preview_response_invalid"
    )


def test_malformed_factory_status_type_fails_closed(monkeypatch):
    monkeypatch.setattr(
        service,
        "_load_factory",
        lambda: SimpleNamespace(
            preview_profile_from_native_runtime=lambda profile_id, **_kwargs: {
                **_unavailable(profile_id, "native_instance_source_required"),
                "status": [],
            }
        ),
    )

    assert service.preview_selection_profile(_PROFILE) == _unavailable(
        _PROFILE, "native_preview_response_invalid"
    )


def _native_factory_available() -> bool:
    try:
        return importlib.util.find_spec("ellmos_installer.bach_profile_factory") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


@pytest.mark.skipif(
    not _native_factory_available(),
    reason="PR4-Installer ist im Standard-BACH-Testextra nicht installiert",
)
def test_real_pr4_factory_reports_missing_instance_before_discovery():
    factory = importlib.import_module("ellmos_installer.bach_profile_factory")

    result = factory.preview_profile_from_native_runtime(_PROFILE, instance_path=None)

    assert result == _unavailable(_PROFILE, "native_instance_source_required")
