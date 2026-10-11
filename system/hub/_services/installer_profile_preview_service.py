"""Read-only selection-profile previews through the native installer factory.

This adapter never resolves a client-supplied path or grants apply authority.
"""
from __future__ import annotations

import importlib
import json
import logging
import re
from collections.abc import Mapping
from typing import Any

_LOG = logging.getLogger(__name__)
_FACTORY_MODULE = "ellmos_installer.bach_profile_factory"
_PROFILE_ID = re.compile(r"[a-z][a-z0-9-]{0,79}\Z")
_REASON_CODE = re.compile(r"[a-z][a-z0-9_]{0,95}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE_ID = re.compile(r"[A-Za-z0-9._:-]{1,160}\Z")
_RESPONSE_SCHEMA = "bach.installer.profile-preview.v1"
_ALLOWED_STATUSES = {"unavailable", "awaiting_audit", "ready"}
_MAX_PREVIEW_BYTES = 1_000_000


def _unavailable(profile_id: str, reason_code: str) -> dict[str, Any]:
    return {
        "schema": _RESPONSE_SCHEMA,
        "status": "unavailable",
        "profile_id": profile_id,
        "reason_code": reason_code,
        "apply_allowed": False,
        "deployable": False,
    }


def _load_factory() -> Any:
    return importlib.import_module(_FACTORY_MODULE)


def _json_mapping(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        encoded = json.dumps(dict(value), ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > _MAX_PREVIEW_BYTES:
            return None
        decoded = json.loads(encoded)
    except (TypeError, ValueError, UnicodeEncodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _safe_diagnostics(value: Any) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    source_id = value.get("source_id")
    expected = value.get("expected_sha256")
    actual = value.get("actual_sha256")
    if (
        not isinstance(source_id, str)
        or not _SOURCE_ID.fullmatch(source_id)
        or not isinstance(expected, str)
        or not _SHA256.fullmatch(expected)
        or not isinstance(actual, str)
        or not _SHA256.fullmatch(actual)
    ):
        return None
    return {
        "source_id": source_id,
        "expected_sha256": expected,
        "actual_sha256": actual,
    }


def _project_factory_response(value: Any, profile_id: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return _unavailable(profile_id, "native_preview_response_invalid")
    status = value.get("status")
    if (
        value.get("schema") != _RESPONSE_SCHEMA
        or value.get("profile_id") != profile_id
        or not isinstance(status, str)
        or status not in _ALLOWED_STATUSES
        or value.get("apply_allowed") is not False
        or value.get("deployable") is not False
    ):
        return _unavailable(profile_id, "native_preview_response_invalid")

    result: dict[str, Any] = {
        "schema": _RESPONSE_SCHEMA,
        "status": status,
        "profile_id": profile_id,
        "apply_allowed": False,
        "deployable": False,
    }

    for field in ("catalog_sha256", "discovery_hash"):
        item = value.get(field)
        if item is not None:
            if not isinstance(item, str) or not _SHA256.fullmatch(item):
                return _unavailable(profile_id, "native_preview_response_invalid")
            result[field] = item

    refs = value.get("component_refs")
    if refs is not None:
        if (
            not isinstance(refs, list)
            or len(refs) > 256
            or any(not isinstance(ref, str) or not ref or len(ref) > 180 for ref in refs)
        ):
            return _unavailable(profile_id, "native_preview_response_invalid")
        result["component_refs"] = list(refs)

    reason_code = value.get("reason_code")
    if status in {"unavailable", "awaiting_audit"}:
        if not isinstance(reason_code, str) or not _REASON_CODE.fullmatch(reason_code):
            return _unavailable(profile_id, "native_preview_response_invalid")
        result["reason_code"] = reason_code

    diagnostics = value.get("diagnostics")
    if diagnostics is not None:
        safe = _safe_diagnostics(diagnostics)
        if safe is None:
            return _unavailable(profile_id, "native_preview_response_invalid")
        result["diagnostics"] = safe

    design = value.get("design_preview")
    plan = value.get("plan_preview")
    if status == "unavailable":
        return result
    if status == "awaiting_audit":
        projected_design = _json_mapping(design)
        if projected_design is None or plan is not None:
            return _unavailable(profile_id, "native_preview_response_invalid")
        result["design_preview"] = projected_design
        result["plan_preview"] = None
        return result

    projected_design = _json_mapping(design)
    projected_plan = _json_mapping(plan)
    if projected_design is None or projected_plan is None:
        return _unavailable(profile_id, "native_preview_response_invalid")
    result["design_preview"] = projected_design
    result["plan_preview"] = projected_plan
    return result


def preview_selection_profile(profile_id: str) -> dict[str, Any]:
    """Return an authenticated caller's safe, read-only native preview result."""
    if not isinstance(profile_id, str) or not _PROFILE_ID.fullmatch(profile_id):
        return _unavailable("invalid", "profile_id_invalid")

    try:
        factory = _load_factory()
    # Ordinary import failures from the optional peer stay fail-closed.
    except Exception as exc:  # noqa: BLE001
        _LOG.warning(
            "native profile preview unavailable phase=import exception_class=%s",
            type(exc).__name__,
        )
        return _unavailable(profile_id, "native_installer_unavailable")

    caller = getattr(factory, "preview_profile_from_native_runtime", None)
    if not callable(caller):
        _LOG.warning("native profile preview unavailable phase=contract")
        return _unavailable(profile_id, "native_installer_contract_unavailable")

    try:
        # BACH has no canonical native instance source yet. Passing None lets
        # PR4's factory return its own fail-closed reason before Discovery.
        response = caller(profile_id, instance_path=None)
    # Native peer failures must not escape this read-only API.
    except Exception as exc:  # noqa: BLE001
        _LOG.warning(
            "native profile preview unavailable phase=preview exception_class=%s",
            type(exc).__name__,
        )
        return _unavailable(profile_id, "native_preview_failed")

    try:
        return _project_factory_response(response, profile_id)
    except Exception as exc:  # noqa: BLE001
        _LOG.warning(
            "native profile preview unavailable phase=projection exception_class=%s",
            type(exc).__name__,
        )
        return _unavailable(profile_id, "native_preview_response_invalid")
