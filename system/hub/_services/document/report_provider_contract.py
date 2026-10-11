"""Neutral, content-free wire contract for optional report providers.

The public BACH layer accepts opaque source/template references only. Report
domain rules, prompts, templates, consent verification, and run persistence live
in the separately installed provider.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any, Mapping


SCHEMA = "ellmos.report-provider.v1"
_OPAQUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
PROVIDER_REASON_CODES = frozenset({
    # The optional provider facade normalizes its finite internal vocabulary for this wire.
    "prepared", "draft_created", "cleanup_completed", "watcher_configured",
    "watcher_state_read", "watcher_tick_completed", "provider_configured",
    "provider_not_configured", "provider_unavailable", "provider_invalid_request",
    "provider_consent_denied", "provider_consent_expired", "provider_source_unavailable",
    "provider_source_changed", "provider_template_unavailable", "provider_template_changed",
    "provider_run_store_unavailable", "provider_run_conflict", "provider_finish_denied",
    "provider_route_unverified", "provider_anonymization_unsupported",
    "provider_anonymization_receipt_invalid", "provider_hybrid_schema_invalid",
    "provider_report_schema_invalid", "provider_render_unavailable", "provider_effect_unknown",
    "provider_cleanup_denied", "provider_cleanup_unavailable", "provider_cleanup_partial",
    "provider_run_not_found", "provider_watcher_disabled", "provider_watcher_unavailable",
    "provider_watcher_consent_denied",
})
NEUTRAL_REASON_CODES = PROVIDER_REASON_CODES | frozenset({
    # Public adapter and generic host-port diagnostics.
    "anonymization_unavailable", "anonymization_unsupported", "artifact_cleanup_partial",
    "artifact_store_unavailable", "cloud_consent_unavailable", "cloud_route_unverified",
    "coverage_unavailable", "coverage_unverified", "host_port_unavailable",
    "hybrid_policy_unavailable", "local_route_unverified", "provider_ambiguous",
    "provider_invalid", "provider_missing", "receipt_unavailable", "request_blocked",
    "receipt_required", "residual_data_detected", "route_policy_mismatch", "route_unavailable",
    "source_extraction_incomplete", "source_revision_changed", "unsupported_source",
    "watcher_unavailable",
    # Stable public boundary outcomes for behavior the provider facade cannot perform.
    "cleanup_failed", "provider_watcher_unavailable", "source_deletion_unsupported",
    "watcher_clock_override_unsupported",
})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_REF = re.compile(r"^src_[0-9a-f]{48}$")
_SUBJECT_REF = re.compile(r"^sub_[0-9a-f]{48}$")
_MODES = frozenset({"local", "cloud", "hybrid"})
_MODE_ORDER = ("local", "cloud", "hybrid")


class ReportContractError(ValueError):
    """A value does not meet the neutral provider contract."""


def is_neutral_reason_code(value: Any) -> bool:
    """Return whether a provider reason is in the public, content-free vocabulary."""
    return isinstance(value, str) and value in NEUTRAL_REASON_CODES


def _opaque(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _OPAQUE.fullmatch(value):
        raise ReportContractError(f"invalid_{field}")
    return value


def _date(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ReportContractError(f"invalid_{field}")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ReportContractError(f"invalid_{field}") from exc


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(k, str) for k in value):
        raise ReportContractError(f"invalid_{field}")
    return value


def _exact_keys(data: Mapping[str, Any], keys: set[str], field: str) -> None:
    if set(data) != keys:
        raise ReportContractError(f"invalid_{field}_shape")


def _expiry(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ReportContractError(f"invalid_{field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReportContractError(f"invalid_{field}") from exc
    if parsed.tzinfo is None:
        raise ReportContractError(f"invalid_{field}")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _wire(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_wire") and callable(value.to_wire):
        value = value.to_wire()
    elif hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    if not isinstance(value, Mapping):
        raise ReportContractError("invalid_provider_response")
    return dict(value)


@dataclass(frozen=True)
class ProviderCapabilities:
    available: bool
    modes: tuple[str, ...]
    watcher_available: bool
    mode_statuses: Mapping[str, Mapping[str, Any]]
    reason_code: str | None = None
    schema: str = SCHEMA

    @classmethod
    def from_wire(cls, raw: Any) -> "ProviderCapabilities":
        data = _mapping(raw, "capabilities")
        required = {
            "schema", "available", "modes", "watcher_available", "mode_statuses",
        }
        if frozenset(data) not in {frozenset(required), frozenset(required | {"reason_code"})}:
            raise ReportContractError("invalid_capabilities_shape")
        if data.get("schema") != SCHEMA:
            raise ReportContractError("invalid_capabilities_schema")
        if type(data.get("available")) is not bool or type(data.get("watcher_available")) is not bool:
            raise ReportContractError("invalid_capabilities_flags")

        raw_statuses = _mapping(data.get("mode_statuses"), "mode_statuses")
        if set(raw_statuses) != _MODES:
            raise ReportContractError("invalid_mode_statuses")
        mode_statuses: dict[str, dict[str, Any]] = {}
        available_modes: list[str] = []
        for mode in _MODE_ORDER:
            status = _mapping(raw_statuses[mode], "mode_status")
            status_keys = frozenset(status)
            if status_keys not in {frozenset({"available"}), frozenset({"available", "reason_code"})}:
                raise ReportContractError("invalid_mode_status_shape")
            is_available = status.get("available")
            if type(is_available) is not bool:
                raise ReportContractError("invalid_mode_status")
            normalized: dict[str, Any] = {"available": is_available}
            if "reason_code" in status:
                reason = status["reason_code"]
                if not is_neutral_reason_code(reason):
                    raise ReportContractError("invalid_mode_reason_code")
                normalized["reason_code"] = reason
            if is_available:
                available_modes.append(mode)
            mode_statuses[mode] = normalized

        raw_modes = data.get("modes")
        if not isinstance(raw_modes, (list, tuple)) or any(
            not isinstance(mode, str) or mode not in _MODES for mode in raw_modes
        ):
            raise ReportContractError("invalid_capability_modes")
        if len(set(raw_modes)) != len(raw_modes) or set(raw_modes) != set(available_modes):
            raise ReportContractError("capability_modes_mismatch")
        if data["available"] != bool(available_modes):
            raise ReportContractError("capability_availability_mismatch")

        reason_code = data.get("reason_code")
        if "reason_code" in data and (
            not is_neutral_reason_code(reason_code)
        ):
            raise ReportContractError("invalid_reason_code")
        return cls(
            data["available"], tuple(available_modes), data["watcher_available"],
            mode_statuses, reason_code,
        )

    def to_wire(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema": self.schema,
            "available": self.available,
            "modes": list(self.modes),
            "watcher_available": self.watcher_available,
            "mode_statuses": {
                mode: dict(self.mode_statuses[mode]) for mode in _MODE_ORDER
            },
        }
        if self.reason_code is not None:
            result["reason_code"] = self.reason_code
        return result


@dataclass(frozen=True)
class ReportRequest:
    request_id: str
    subject_ref: str
    source_refs: tuple[str, ...]
    period_start: str
    period_end: str
    mode: str
    template_id: str
    mode_consent: Mapping[str, Any]
    schema: str = SCHEMA

    @classmethod
    def from_wire(cls, raw: Any) -> "ReportRequest":
        data = _mapping(raw, "request")
        allowed = {
            "schema", "request_id", "subject_ref", "source_refs", "period_start",
            "period_end", "mode", "template_id", "mode_consent",
        }
        if set(data) != allowed or data.get("schema") != SCHEMA:
            raise ReportContractError("invalid_request_shape")
        mode = data.get("mode")
        if not isinstance(mode, str) or mode not in _MODES:
            raise ReportContractError("invalid_mode")
        refs = data.get("source_refs")
        if not isinstance(refs, (list, tuple)) or not refs or len(refs) > 200:
            raise ReportContractError("invalid_source_refs")
        source_refs = tuple(_opaque(item, "source_ref") for item in refs)
        if any(_SOURCE_REF.fullmatch(item) is None for item in source_refs):
            raise ReportContractError("invalid_source_ref")
        if len(set(source_refs)) != len(source_refs):
            raise ReportContractError("duplicate_source_ref")
        start, end = _date(data.get("period_start"), "period_start"), _date(
            data.get("period_end"), "period_end"
        )
        if start > end:
            raise ReportContractError("invalid_period")
        consent = _mapping(data.get("mode_consent"), "mode_consent")
        _exact_keys(
            consent,
            {"mode", "consent_ref", "request_id", "request_digest", "approved", "expires_at"},
            "mode_consent",
        )
        if consent.get("mode") != mode:
            raise ReportContractError("consent_mode_mismatch")
        _opaque(consent.get("consent_ref"), "consent_ref")
        if consent.get("approved") is not True:
            raise ReportContractError("mode_consent_required")
        consent_request_id = _opaque(consent.get("request_id"), "consent_request_id")
        digest = consent.get("request_digest")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ReportContractError("invalid_request_digest")
        normalized_expiry = _expiry(consent.get("expires_at"), "consent_expiry")
        if datetime.fromisoformat(normalized_expiry.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            raise ReportContractError("expired_mode_consent")
        request = cls(
            request_id=_opaque(data.get("request_id"), "request_id"),
            subject_ref=_opaque(data.get("subject_ref"), "subject_ref"),
            source_refs=source_refs,
            period_start=start,
            period_end=end,
            mode=mode,
            template_id=_opaque(data.get("template_id"), "template_id"),
            mode_consent=dict(consent),
        )
        if _SUBJECT_REF.fullmatch(request.subject_ref) is None:
            raise ReportContractError("invalid_subject_ref")
        if consent_request_id != request.request_id:
            raise ReportContractError("consent_request_id_mismatch")
        if digest != request.digest:
            raise ReportContractError("consent_request_digest_mismatch")
        return request

    def stable_fields(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "request_id": self.request_id,
            "subject_ref": self.subject_ref,
            "source_refs": list(self.source_refs),
            "period_start": self.period_start,
            "period_end": self.period_end,
            "mode": self.mode,
            "template_id": self.template_id,
        }

    @property
    def digest(self) -> str:
        payload = json.dumps(
            self.stable_fields(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def to_wire(self) -> dict[str, Any]:
        return {**self.stable_fields(), "mode_consent": dict(self.mode_consent)}


@dataclass(frozen=True)
class PreparedRun:
    run_id: str | None
    status: str
    preview_ref: str | None
    expires_at: str | None
    request_digest: str
    source_revision: str | None
    template_revision: str | None
    source_count: int
    reason_code: str | None = None
    schema: str = SCHEMA

    @classmethod
    def from_wire(cls, raw: Any, *, expected_digest: str | None = None) -> "PreparedRun":
        data = _wire(raw)
        _exact_keys(
            data,
            {
                "schema", "run_id", "status", "preview_ref", "expires_at", "request_digest",
                "source_revision", "template_revision", "source_count", "reason_code",
            },
            "prepared_run",
        )
        if data.get("schema") != SCHEMA or data.get("status") not in {
            "prepared", "blocked", "unavailable"
        }:
            raise ReportContractError("invalid_prepared_run")
        raw_run_id = data.get("run_id")
        run_id = _opaque(raw_run_id, "run_id") if raw_run_id is not None else None
        digest = data.get("request_digest")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ReportContractError("invalid_request_digest")
        if expected_digest is not None and digest != expected_digest:
            raise ReportContractError("request_digest_mismatch")
        status = data["status"]
        preview = data.get("preview_ref")
        raw_expiry = data.get("expires_at")
        source_revision = data.get("source_revision")
        template_revision = data.get("template_revision")
        source_count = data.get("source_count")
        reason = data.get("reason_code")
        if type(source_count) is not int or not 0 <= source_count <= 200:
            raise ReportContractError("invalid_source_count")
        if status == "prepared":
            if run_id is None or source_count < 1:
                raise ReportContractError("invalid_prepared_run")
            preview = _opaque(preview, "preview_ref")
            source_revision = _opaque(source_revision, "source_revision")
            template_revision = _opaque(template_revision, "template_revision")
            expiry = _expiry(raw_expiry, "prepared_expiry")
            if datetime.fromisoformat(expiry.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                raise ReportContractError("expired_prepared_run")
            if reason is not None:
                raise ReportContractError("invalid_prepared_run")
        else:
            expiry = None
            if (run_id is not None or preview is not None or raw_expiry is not None
                    or source_revision is not None or template_revision is not None or source_count != 0):
                raise ReportContractError("unbound_prepared_run")
            if not is_neutral_reason_code(reason):
                raise ReportContractError("invalid_reason_code")
        return cls(
            run_id, status, preview, expiry, digest, source_revision, template_revision,
            source_count, reason,
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "run_id": self.run_id,
            "status": self.status,
            "preview_ref": self.preview_ref,
            "expires_at": self.expires_at,
            "request_digest": self.request_digest,
            "source_revision": self.source_revision,
            "template_revision": self.template_revision,
            "source_count": self.source_count,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class ReportApproval:
    approved: bool
    preview_ref: str
    consent_ref: str

    @classmethod
    def from_wire(cls, raw: Any) -> "ReportApproval":
        data = _mapping(raw, "approval")
        if set(data) != {"approved", "preview_ref", "consent_ref"}:
            raise ReportContractError("invalid_approval_shape")
        if data.get("approved") is not True:
            raise ReportContractError("approval_required")
        return cls(
            True,
            _opaque(data.get("preview_ref"), "preview_ref"),
            _opaque(data.get("consent_ref"), "consent_ref"),
        )

    def to_wire(self) -> dict[str, Any]:
        return {"approved": self.approved, "preview_ref": self.preview_ref, "consent_ref": self.consent_ref}


@dataclass(frozen=True)
class CleanupApproval:
    run_id: str
    consent_ref: str
    delete_sources: bool

    @classmethod
    def from_wire(cls, raw: Any, *, expected_run_id: str) -> "CleanupApproval":
        data = _mapping(raw, "cleanup_approval")
        keys = {"run_id", "consent_ref", "approved"}
        if "delete_sources" in data:
            keys.add("delete_sources")
        _exact_keys(data, keys, "cleanup_approval")
        if data.get("approved") is not True:
            raise ReportContractError("cleanup_approval_required")
        run_id = _opaque(data.get("run_id"), "run_id")
        if run_id != expected_run_id:
            raise ReportContractError("run_id_mismatch")
        delete_sources = data.get("delete_sources", False)
        if type(delete_sources) is not bool:
            raise ReportContractError("invalid_delete_sources")
        return cls(run_id, _opaque(data.get("consent_ref"), "consent_ref"), delete_sources)

    def to_wire(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "consent_ref": self.consent_ref,
            "approved": True,
            "delete_sources": self.delete_sources,
        }


@dataclass(frozen=True)
class WatcherConfig:
    enabled: bool
    auto_finish: bool
    subject_refs: tuple[str, ...]
    mode: str
    template_id: str
    period_start: str
    period_end: str
    consent_ref: str
    consent_expires_at: str
    schema: str = SCHEMA

    @classmethod
    def from_wire(cls, raw: Any) -> "WatcherConfig":
        data = _mapping(raw, "watcher_config")
        if data.get("schema") != SCHEMA:
            raise ReportContractError("invalid_watcher_schema")
        required = {
            "schema", "enabled", "auto_finish", "subject_refs", "mode", "template_id",
            "period_start", "period_end", "consent_ref", "consent_expires_at",
        }
        _exact_keys(data, required, "watcher_config")
        if type(data.get("enabled")) is not bool or type(data.get("auto_finish")) is not bool:
            raise ReportContractError("invalid_watcher_flags")
        raw_subject_refs = data.get("subject_refs")
        if (not isinstance(raw_subject_refs, (list, tuple)) or len(raw_subject_refs) > 200
                or (data["enabled"] and not raw_subject_refs)):
            raise ReportContractError("invalid_watcher_subject_refs")
        subject_refs = tuple(_opaque(item, "subject_ref") for item in raw_subject_refs)
        if any(_SUBJECT_REF.fullmatch(item) is None for item in subject_refs):
            raise ReportContractError("invalid_subject_ref")
        if len(set(subject_refs)) != len(subject_refs):
            raise ReportContractError("duplicate_subject_ref")
        mode = data.get("mode")
        if not isinstance(mode, str) or mode not in _MODES:
            raise ReportContractError("invalid_mode")
        start = _date(data.get("period_start"), "period_start")
        end = _date(data.get("period_end"), "period_end")
        if start > end:
            raise ReportContractError("invalid_period")
        expiry = _expiry(data.get("consent_expires_at"), "watcher_consent_expiry")
        if datetime.fromisoformat(expiry.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            raise ReportContractError("expired_watcher_consent")
        return cls(
            data["enabled"], data["auto_finish"], subject_refs, mode,
            _opaque(data.get("template_id"), "template_id"), start, end,
            _opaque(data.get("consent_ref"), "consent_ref"), expiry,
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "enabled": self.enabled,
            "auto_finish": self.auto_finish,
            "subject_refs": list(self.subject_refs),
            "mode": self.mode,
            "template_id": self.template_id,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "consent_ref": self.consent_ref,
            "consent_expires_at": self.consent_expires_at,
        }


@dataclass(frozen=True)
class ReportResult:
    run_id: str
    status: str
    effect: str
    reason_code: str
    artifact_refs: tuple[str, ...]
    review_required: bool = True
    schema: str = SCHEMA

    @classmethod
    def from_wire(cls, raw: Any, *, expected_run_id: str | None = None) -> "ReportResult":
        data = _wire(raw)
        _exact_keys(
            data,
            {"schema", "run_id", "status", "effect", "reason_code", "artifact_refs", "review_required"},
            "result",
        )
        if data.get("schema") != SCHEMA:
            raise ReportContractError("invalid_result_schema")
        run_id = _opaque(data.get("run_id"), "run_id")
        if expected_run_id is not None and run_id != expected_run_id:
            raise ReportContractError("run_id_mismatch")
        status = data.get("status")
        effect = data.get("effect")
        reason = data.get("reason_code")
        refs = data.get("artifact_refs")
        if status not in {"draft", "blocked", "unavailable"}:
            raise ReportContractError("invalid_result_status")
        if effect not in {"completed", "unknown", "none"}:
            raise ReportContractError("invalid_effect")
        if not is_neutral_reason_code(reason):
            raise ReportContractError("invalid_reason_code")
        if not isinstance(refs, (list, tuple)) or len(refs) > 64:
            raise ReportContractError("invalid_artifact_refs")
        artifact_refs = tuple(_opaque(item, "artifact_ref") for item in refs)
        if type(data.get("review_required")) is not bool or data.get("review_required") is not True:
            raise ReportContractError("review_required")
        if status != "draft" and artifact_refs:
            raise ReportContractError("unexpected_artifacts")
        if status == "draft" and effect != "completed":
            raise ReportContractError("incomplete_draft_effect")
        if status != "draft" and effect == "completed":
            raise ReportContractError("unexpected_completed_effect")
        return cls(run_id, status, effect, reason, artifact_refs)

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "run_id": self.run_id,
            "status": self.status,
            "effect": self.effect,
            "reason_code": self.reason_code,
            "artifact_refs": list(self.artifact_refs),
            "review_required": self.review_required,
        }
