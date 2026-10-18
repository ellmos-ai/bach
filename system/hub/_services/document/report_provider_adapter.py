"""Optional entry-point adapter for neutral report-provider implementations.

This module deliberately does not import a personal report package. Providers
are discovered through ``ellmos.report_providers`` and receive only trusted
host ports supplied by their caller. All lifecycle methods are async so callers
inside BACH's chat event loop do not nest loops or create hidden worker threads.
"""
from __future__ import annotations

import importlib.metadata
import hashlib
import inspect
import json
import math
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from .report_provider_contract import (
    SCHEMA,
    CleanupApproval,
    PreparedRun,
    ProviderCapabilities,
    ReportApproval,
    ReportContractError,
    ReportRequest,
    ReportResult,
    WatcherConfig,
    _opaque,
    _wire,
    is_neutral_reason_code,
)


ENTRY_POINT_GROUP = "ellmos.report_providers"
_SOURCE_MEDIA_TYPES = frozenset({
    "text/plain",
    "text/markdown",
    "application/msword",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
})
_SAFE_STATES = frozenset({
    "disabled", "enabled", "queued", "prepared", "draft", "blocked",
    "unavailable", "unknown", "cleaned", "cleanup_failed",
})


def _reason(value: Any, fallback: str) -> str:
    if is_neutral_reason_code(value):
        return value
    return fallback if is_neutral_reason_code(fallback) else "provider_unavailable"


async def _resolve(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class ReportHostPortError(RuntimeError):
    """Redacted failure from an explicitly configured BACH host port."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = _reason(reason_code, "host_port_unavailable")
        super().__init__(self.reason_code)


class OwnerExecutionProfileReader:
    """Fixed-identity view supplied by the real Control process owner.

    ``read_current`` must be the Control owner's execution-profile reader
    (the closure built from ``_execution_slot_reader``), which rechecks the
    worker configuration and its pinned governance on every read. This class
    validates the returned projection and never accepts an agent ID from a
    report request.
    """

    def __init__(self, agent_id: str, read_current: Any) -> None:
        if (not isinstance(agent_id, str)
                or re.fullmatch(r"[A-Za-z0-9_-]{1,80}", agent_id) is None
                or not callable(read_current)):
            raise ReportHostPortError("provider_route_unverified")
        self.agent_id = agent_id
        self._read_current = read_current

    def read(self) -> dict[str, Any]:
        try:
            profile = _wire(self._read_current())
        except Exception:
            raise ReportHostPortError("provider_route_unverified") from None
        if (profile.get("id") != self.agent_id
                or profile.get("enabled") is not True
                or profile.get("execution_kind") != "worker"
                or type(profile.get("blueprint_id")) is not int
                or profile["blueprint_id"] <= 0
                or type(profile.get("blueprint_version")) is not int
                or profile["blueprint_version"] < 1):
            raise ReportHostPortError("provider_route_unverified")
        governance = profile.get("governance_binding")
        if (not isinstance(governance, Mapping)
                or governance.get("legacy") is not False
                or not isinstance(governance.get("effective_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", governance["effective_sha256"]) is None
                or not isinstance(governance.get("refs"), (list, tuple))):
            raise ReportHostPortError("provider_route_unverified")
        return dict(profile)


class BachOperatorConfirmationPort:
    """Verify host-issued confirmation receipts; this port cannot issue consent."""

    _BINDINGS = {
        "report.mode_consent": {
            "action", "request_id", "request_digest", "subject_ref", "mode", "template_id", "expires_at",
        },
        "report.finish": {"action", "run_id", "preview_ref", "request_digest", "mode"},
        "report.cleanup": {"action", "run_id", "request_digest", "delete_sources"},
        "report.watcher.configure": {"action", "config_digest", "expires_at"},
    }

    def __init__(self, verifier: Any) -> None:
        self._verifier = verifier

    @staticmethod
    def _expiry(value: Any) -> str:
        if not isinstance(value, str):
            raise ReportHostPortError("operator_confirmation_invalid")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ReportHostPortError("operator_confirmation_invalid") from None
        if parsed.tzinfo is None:
            raise ReportHostPortError("operator_confirmation_invalid")
        normalized = parsed.astimezone(timezone.utc)
        if normalized <= datetime.now(timezone.utc):
            raise ReportHostPortError("operator_confirmation_expired")
        return normalized.isoformat().replace("+00:00", "Z")

    @classmethod
    def _binding(cls, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, Mapping) or any(not isinstance(k, str) for k in raw):
            raise ReportHostPortError("operator_confirmation_invalid")
        binding = dict(raw)
        action = binding.get("action")
        if not isinstance(action, str) or action not in cls._BINDINGS or set(binding) != cls._BINDINGS[action]:
            raise ReportHostPortError("operator_confirmation_invalid")
        digest_key = "config_digest" if action == "report.watcher.configure" else "request_digest"
        if not isinstance(binding.get(digest_key), str) or re.fullmatch(r"[0-9a-f]{64}", binding[digest_key]) is None:
            raise ReportHostPortError("operator_confirmation_invalid")
        if action in {"report.mode_consent", "report.finish"}:
            if binding.get("mode") not in {"local", "cloud", "hybrid"}:
                raise ReportHostPortError("operator_confirmation_invalid")
        if action == "report.mode_consent":
            if (not isinstance(binding.get("subject_ref"), str)
                    or re.fullmatch(r"sub_[0-9a-f]{48}", binding["subject_ref"]) is None):
                raise ReportHostPortError("operator_confirmation_invalid")
            _opaque(binding.get("request_id"), "request_id")
            _opaque(binding.get("template_id"), "template_id")
        if action == "report.finish":
            _opaque(binding.get("run_id"), "run_id")
            _opaque(binding.get("preview_ref"), "preview_ref")
        if action == "report.cleanup":
            _opaque(binding.get("run_id"), "run_id")
            if type(binding.get("delete_sources")) is not bool:
                raise ReportHostPortError("operator_confirmation_invalid")
        if "expires_at" in binding:
            binding["expires_at"] = cls._expiry(binding["expires_at"])
        return binding

    async def verify_confirmation(self, confirmation: str, expected_binding: Any) -> dict[str, Any]:
        confirmation_ref = _opaque(confirmation, "confirmation_ref")
        binding = self._binding(expected_binding)
        verifier = _require_port_method(self._verifier, "verify_confirmation")
        try:
            data = _wire(await _resolve(verifier(confirmation_ref, binding)))
            required = {"verified", "operator_confirmed", "binding", "proof_ref", "expires_at"}
            if set(data) != required or data.get("verified") is not True or data.get("operator_confirmed") is not True:
                raise ReportHostPortError("operator_confirmation_invalid")
            verified_binding = self._binding(data.get("binding"))
            if verified_binding != binding:
                raise ReportHostPortError("operator_confirmation_binding_mismatch")
            proof_ref = _opaque(data.get("proof_ref"), "proof_ref")
            expiry = self._expiry(data.get("expires_at"))
            if "expires_at" in binding:
                bound_expiry = datetime.fromisoformat(binding["expires_at"].replace("Z", "+00:00"))
                proof_expiry = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                if proof_expiry < bound_expiry:
                    raise ReportHostPortError("operator_confirmation_binding_mismatch")
            return {
                "verified": True,
                "operator_confirmed": True,
                "binding": binding,
                "proof_ref": proof_ref,
                "expires_at": expiry,
            }
        except ReportHostPortError:
            raise
        except Exception:
            raise ReportHostPortError("operator_confirmation_unavailable") from None


def _require_port_method(port: Any, name: str) -> Any:
    method = getattr(port, name, None)
    if not callable(method):
        raise ReportHostPortError("host_port_unavailable")
    return method


def _json_value(value: Any) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ReportHostPortError("invalid_report_data") from None
    if len(encoded.encode("utf-8")) > 2_000_000:
        raise ReportHostPortError("report_data_too_large")
    return encoded


def _artifact_ref_list(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple)) or len(raw) > 256:
        raise ReportContractError("invalid_artifact_refs")
    refs = tuple(_opaque(item, "artifact_ref") for item in raw)
    if len(set(refs)) != len(refs):
        raise ReportContractError("duplicate_artifact_ref")
    return refs


async def _delete_run_artifacts(store: Any, run_id: str, refs: tuple[str, ...]) -> dict[str, Any]:
    if not refs:
        return {"complete": True, "deleted_count": 0}
    delete = getattr(store, "delete", None)
    if not callable(delete):
        return {"complete": False, "deleted_count": 0}
    deleted = 0
    for ref in refs:
        try:
            result = await _resolve(delete(run_id, ref))
            if result is True or (isinstance(result, Mapping) and dict(result) == {"deleted": True}):
                deleted += 1
        except Exception:
            continue
    return {"complete": deleted == len(refs), "deleted_count": deleted}


def _receipt_projection(
    verified: bool,
    run_id: str,
    source_ref: str,
    source_revision: str,
    artifact_ref: str,
    receipt_ref: str,
    input_sha256: str | None,
    output_sha256: str | None,
    policy_version: str | None,
) -> dict[str, Any]:
    return {
        "verified": verified,
        "coverage": "complete" if verified else "unsupported",
        "policy_version": policy_version if verified and policy_version is not None else "unknown",
        "run_id": run_id,
        "source_ref": source_ref,
        "source_revision": source_revision,
        "artifact_ref": artifact_ref,
        "receipt_ref": receipt_ref,
        "input_sha256": input_sha256,
        "output_sha256": output_sha256,
    }


class BachWordTemplatePort:
    """Render a generic mapping through WordTemplateService and opaque storage.

    The private provider binds its own trusted resolver once. It returns only
    bytes, media type, and a revision; no template path crosses this adapter.
    """

    def __init__(
        self,
        artifact_store: Any,
        *,
        service: Any = None,
    ) -> None:
        if service is None:
            from hub._services.document.word_template_service import WordTemplateService

            service = WordTemplateService()
        self._service = service
        self._template_resolver = None
        self._artifact_store = artifact_store

    def bind_resolver(self, resolver: Any) -> None:
        """Bind exactly one private registry resolver; never accept a request path."""
        if self._template_resolver is not None:
            raise ReportHostPortError("template_resolver_already_bound")
        if not callable(getattr(resolver, "resolve", None)):
            raise ReportHostPortError("template_resolver_unavailable")
        self._template_resolver = resolver

    async def _template_snapshot(self, template_id: str, expected_revision: str) -> tuple[bytes, str, str]:
        if self._template_resolver is None:
            raise ReportHostPortError("template_unavailable")
        resolver = _require_port_method(self._template_resolver, "resolve")
        try:
            raw = await _resolve(resolver(template_id, expected_revision=expected_revision))
            data = _wire(raw)
            if set(data) != {"available", "content", "revision", "media_type"}:
                raise ReportHostPortError("template_unavailable")
            if data.get("available") is not True:
                raise ReportHostPortError("template_unavailable")
            revision = _opaque(data.get("revision"), "template_revision")
            content = data.get("content")
            if not isinstance(content, bytes) or not content or len(content) > 32_000_000:
                raise ReportHostPortError("template_unavailable")
            if data.get("media_type") != "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                raise ReportHostPortError("template_unavailable")
            if revision != expected_revision:
                raise ReportHostPortError("template_revision_changed")
            return content, revision, hashlib.sha256(content).hexdigest()
        except ReportHostPortError:
            raise
        except Exception:
            raise ReportHostPortError("template_unavailable") from None

    async def render_draft(
        self,
        schema_version: str,
        report: Mapping[str, Any],
        template_id: str,
        expected_revision: str,
        *,
        run_id: str,
    ) -> dict[str, str]:
        _opaque(run_id, "run_id")
        _opaque(template_id, "template_id")
        _opaque(expected_revision, "template_revision")
        if not isinstance(schema_version, str) or not schema_version or len(schema_version) > 128:
            raise ReportHostPortError("invalid_report_schema")
        if not isinstance(report, Mapping) or len(report) > 512 or any(not isinstance(k, str) for k in report):
            raise ReportHostPortError("invalid_report_data")
        content, revision, content_sha = await self._template_snapshot(template_id, expected_revision)
        placeholders: dict[str, str] = {}
        for key, value in report.items():
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", key):
                raise ReportHostPortError("invalid_report_data")
            placeholders["{{" + key + "}}"] = value if isinstance(value, str) else _json_value(value)

        try:
            with tempfile.TemporaryDirectory(prefix="bach-report-render-") as directory:
                template_copy = Path(directory) / "template.docx"
                output_path = Path(directory) / "draft.docx"
                template_copy.write_bytes(content)
                document = self._service.load_template(str(template_copy))
                self._service.replace_placeholders(document, placeholders)
                self._service.save(document, str(output_path))
                output = output_path.read_bytes()
            if len(output) > 32_000_000:
                raise ReportHostPortError("rendered_artifact_too_large")
            # Re-read the trusted registry and the source hash immediately before
            # storing the artifact; edits during rendering invalidate this draft.
            current_content, current_revision, current_sha = await self._template_snapshot(
                template_id, expected_revision
            )
            if (current_revision != revision or current_sha != content_sha
                    or hashlib.sha256(current_content).hexdigest() != content_sha):
                raise ReportHostPortError("template_revision_changed")
            put = _require_port_method(self._artifact_store, "put")
            output_sha = hashlib.sha256(output).hexdigest()
            stored = await _resolve(put(run_id, output, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
            result = _wire(stored)
            if set(result) != {"artifact_ref", "content_sha256"}:
                raise ReportHostPortError("artifact_store_unavailable")
            artifact_ref = _opaque(result.get("artifact_ref"), "artifact_ref")
            if result.get("content_sha256") != output_sha:
                raise ReportHostPortError("artifact_store_unavailable")
            return {"artifact_ref": artifact_ref, "template_revision": revision}
        except ReportHostPortError:
            raise
        except Exception:
            raise ReportHostPortError("template_render_failed") from None

    async def delete_run_artifacts(self, run_id: str, artifact_refs: Any) -> dict[str, Any]:
        safe_run_id = _opaque(run_id, "run_id")
        refs = _artifact_ref_list(artifact_refs)
        return await _delete_run_artifacts(self._artifact_store, safe_run_id, refs)


class BachDocumentReaderPort:
    """Extract supported local document formats without scanning directories.

    A private, trusted source resolver supplies the path in-process. The
    revision is the lowercase SHA-256 of the original file. The generic
    ``DocumentPipeline`` is used only for its local text extraction method;
    classification/scanning and unsupported or potentially partial formats
    are not exposed through this port.
    """

    _EXTENSIONS = frozenset({".txt", ".md", ".doc", ".docx", ".pdf", ".xlsx"})
    _ERROR_PREFIXES = (
        "[FEHLER bei ", "[DOCX-Fehler:", "[python-docx nicht installiert]",
        "[openpyxl nicht installiert]", "[Nicht unterstuetztes Format:",
        "[.doc-Extraktion fehlgeschlagen", "[PDF-Extraktion fehlgeschlagen",
    )

    def __init__(self, service: Any = None) -> None:
        self._service = service

    def extract(self, path: str | os.PathLike[str], *, expected_revision: str, run_id: str) -> dict[str, Any]:
        _opaque(run_id, "run_id")
        if not isinstance(expected_revision, str) or re.fullmatch(r"[0-9a-f]{64}", expected_revision) is None:
            raise ReportHostPortError("invalid_source_revision")
        try:
            source_path = Path(path).resolve(strict=True)
            if not source_path.is_file() or source_path.suffix.lower() not in self._EXTENSIONS:
                raise ReportHostPortError("unsupported_source")
            original = source_path.read_bytes()
            if not original or len(original) > 32_000_000:
                raise ReportHostPortError("unsupported_source")
            before_sha = hashlib.sha256(original).hexdigest()
            if before_sha != expected_revision:
                raise ReportHostPortError("source_revision_changed")
            with tempfile.TemporaryDirectory(prefix="bach-report-read-") as directory:
                copy = Path(directory) / ("source" + source_path.suffix.lower())
                copy.write_bytes(original)
                pdf_text = self._validate_pdf(copy) if copy.suffix == ".pdf" else None
                service = self._service
                if service is None:
                    from hub._services.document.document_pipeline import DocumentPipeline

                    service = DocumentPipeline()
                extractor = _require_port_method(service, "_extract_text_from_file")
                text = extractor(copy)
            if (not isinstance(text, str) or not text or len(text.encode("utf-8")) > 8_000_000
                    or text.startswith(self._ERROR_PREFIXES)):
                raise ReportHostPortError("source_extraction_incomplete")
            if pdf_text is not None and text.strip() != pdf_text:
                raise ReportHostPortError("source_extraction_incomplete")
            after_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
            if after_sha != expected_revision:
                raise ReportHostPortError("source_revision_changed")
            return {
                "content": text,
                "media_type": "text/plain",
                "source_revision": expected_revision,
                "complete": True,
            }
        except ReportHostPortError:
            raise
        except Exception:
            raise ReportHostPortError("source_extraction_unavailable") from None

    @staticmethod
    def _validate_pdf(path: Path) -> str:
        """Require complete text-only page extraction before generic PDF reading.

        The generic pipeline has OCR and partial-page fallbacks. This adapter
        admits only PDFs whose every page has text and whose visible payload
        has no image/form/annotation/embedded-file content that this reader
        cannot attest. It then requires the pipeline result to match the same
        page text exactly.
        """
        try:
            from pypdf import PdfReader
            from pypdf.generic import ContentStream

            reader = PdfReader(str(path))
            if reader.is_encrypted or not reader.pages:
                raise ReportHostPortError("source_extraction_incomplete")
            root = reader.trailer.get("/Root")
            root = root.get_object() if hasattr(root, "get_object") else root
            if not isinstance(root, Mapping):
                raise ReportHostPortError("source_extraction_incomplete")
            if root.get("/AcroForm") or root.get("/OCProperties"):
                raise ReportHostPortError("source_extraction_incomplete")
            names = root.get("/Names")
            names = names.get_object() if hasattr(names, "get_object") else names
            if isinstance(names, Mapping) and names.get("/EmbeddedFiles"):
                raise ReportHostPortError("source_extraction_incomplete")

            pages: list[str] = []
            for page in reader.pages:
                annotations = page.get("/Annots")
                if annotations and len(annotations):
                    raise ReportHostPortError("source_extraction_incomplete")
                resources = page.get("/Resources")
                resources = resources.get_object() if hasattr(resources, "get_object") else resources
                if isinstance(resources, Mapping):
                    xobjects = resources.get("/XObject")
                    xobjects = xobjects.get_object() if hasattr(xobjects, "get_object") else xobjects
                    if xobjects and len(xobjects):
                        raise ReportHostPortError("source_extraction_incomplete")
                contents = page.get_contents()
                if contents is not None:
                    operations = ContentStream(contents, reader).operations
                    if any(operator in {b"BI", b"Do"} for _operands, operator in operations):
                        raise ReportHostPortError("source_extraction_incomplete")
                page_text = (page.extract_text() or "").strip()
                if not page_text:
                    raise ReportHostPortError("source_extraction_incomplete")
                pages.append(page_text)
            return "\n".join(pages)
        except ReportHostPortError:
            raise
        except ImportError:
            raise ReportHostPortError("source_extraction_unavailable") from None
        except Exception:
            raise ReportHostPortError("source_extraction_incomplete") from None


class BachDocumentAnonymizerPort:
    """Use the generic document anonymizer only with a complete receipt authority.

    A replacement count alone is not a cloud-safety receipt. Without an
    injected verifier that attests complete coverage, this port reports the
    file as unsupported and stores no output artifact.
    """

    _SUFFIXES = {
        "text/plain": ".txt",
        "text/markdown": ".md",
        "application/pdf": ".pdf",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.ms-excel": ".xls",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "message/rfc822": ".eml",
    }

    def __init__(
        self,
        artifact_store: Any,
        profile_factory: Any,
        receipt_authority: Any,
        service: Any = None,
        restore_report: Any = None,
    ) -> None:
        if service is None:
            from hub._services.document.anonymizer_service import DocumentAnonymizer

            service = DocumentAnonymizer()
        self._service = service
        self._artifact_store = artifact_store
        self._profile_factory = profile_factory
        self._receipt_authority = receipt_authority
        self._restore_report = restore_report
        self._verified_reads: dict[tuple[str, str], dict[str, str]] = {}

    async def anonymize(self, file: Mapping[str, Any], *, run_id: str) -> dict[str, Any]:
        safe_run_id = _opaque(run_id, "run_id")
        if not isinstance(file, Mapping):
            raise ReportContractError("invalid_source_file")
        if set(file) != {"source_ref", "source_revision", "media_type", "content", "anonymization_profile"}:
            raise ReportContractError("invalid_source_file")
        source_ref = _opaque(file.get("source_ref"), "source_ref")
        source_revision = _opaque(file.get("source_revision"), "source_revision")
        if re.fullmatch(r"[0-9a-f]{64}", source_revision) is None:
            raise ReportContractError("invalid_source_revision")
        media_type = file.get("media_type")
        raw_content = file.get("content")
        profile_binding = file.get("anonymization_profile")
        if not isinstance(profile_binding, Mapping) or set(profile_binding) != {"profile_id", "policy_version"}:
            raise ReportContractError("invalid_anonymization_profile")
        profile_id = _opaque(profile_binding.get("profile_id"), "profile_id")
        policy_version = _opaque(profile_binding.get("policy_version"), "policy_version")
        suffix = self._SUFFIXES.get(media_type) if isinstance(media_type, str) else None
        if isinstance(raw_content, str):
            content = raw_content.encode("utf-8")
        elif isinstance(raw_content, bytes):
            content = raw_content
        else:
            content = b""
        if suffix is None or not content or len(content) > 32_000_000:
            return {"status": "unsupported", "reason_code": "unsupported_source", "source_revision": source_revision}
        if not callable(getattr(self._receipt_authority, "issue", None)) or not callable(
            getattr(self._receipt_authority, "verify", None)
        ):
            return {"status": "unsupported", "reason_code": "receipt_unavailable", "source_revision": source_revision}
        if callable(self._profile_factory):
            profile_factory = self._profile_factory
        else:
            profile_factory = _require_port_method(self._profile_factory, "create")
        try:
            from hub._services.document.anonymizer_service import AnonymProfile

            profile_data = await _resolve(profile_factory(profile_id, policy_version))
            data = _wire(profile_data)
            if set(data) != {"profile_id", "policy_version", "profile"}:
                raise ReportHostPortError("anonymization_profile_unavailable")
            if data.get("profile_id") != profile_id or data.get("policy_version") != policy_version:
                raise ReportHostPortError("anonymization_profile_unavailable")
            data = _wire(data.get("profile"))
            required = {"client_id", "tarnname", "fake_geburtsdatum", "mappings", "created", "version", "whitelist"}
            if set(data) != required:
                raise ReportHostPortError("anonymization_profile_unavailable")
            profile = AnonymProfile(**data)
            source_sha = hashlib.sha256(content).hexdigest()
            with tempfile.TemporaryDirectory(prefix="bach-report-anonymize-") as directory:
                target = Path(directory) / ("source" + suffix)
                target.write_bytes(content)
                ok, replacement_count = self._service.anonymize_file(str(target), profile)
                if ok is not True or type(replacement_count) is not int or replacement_count < 0:
                    return {"status": "unsupported", "reason_code": "anonymization_unsupported", "source_revision": source_revision}
                extracted = self._service.extract_text_from_file(str(target))
                if not isinstance(extracted, str):
                    return {"status": "unsupported", "reason_code": "coverage_unavailable", "source_revision": source_revision}
                residual = self._service.scan_text_for_sensitive_data(extracted)
                if not isinstance(residual, Mapping) or any(bool(items) for items in residual.values()):
                    return {"status": "unsupported", "reason_code": "residual_data_detected", "source_revision": source_revision}
                output = target.read_bytes()
            output_sha = hashlib.sha256(output).hexdigest()
            store = _require_port_method(self._artifact_store, "put")
            stored = _wire(await _resolve(store(safe_run_id, output, media_type)))
            if set(stored) != {"artifact_ref", "content_sha256"}:
                return {"status": "unsupported", "reason_code": "artifact_store_unavailable", "source_revision": source_revision}
            artifact_ref = _opaque(stored.get("artifact_ref"), "artifact_ref")
            if stored.get("content_sha256") != output_sha:
                await self._discard_artifact(safe_run_id, artifact_ref)
                raise ReportHostPortError("artifact_store_unavailable")
            receipt_raw = await _resolve(self._receipt_authority.issue({
                "run_id": safe_run_id,
                "source_ref": source_ref,
                "source_revision": source_revision,
                "input_sha256": source_sha,
                "output_sha256": output_sha,
                "artifact_ref": artifact_ref,
                "media_type": media_type,
                "profile_id": profile_id,
                "policy_version": policy_version,
                "replacement_count": replacement_count,
                "coverage": "complete",
            }))
            receipt = _wire(receipt_raw)
            receipt_keys = {
                "verified", "coverage", "receipt_ref", "policy_version", "run_id", "source_ref",
                "source_revision", "artifact_ref", "input_sha256", "output_sha256",
            }
            if (set(receipt) != receipt_keys or receipt.get("verified") is not True
                    or receipt.get("coverage") != "complete" or receipt.get("run_id") != safe_run_id
                    or receipt.get("source_ref") != source_ref
                    or receipt.get("source_revision") != source_revision
                    or receipt.get("artifact_ref") != artifact_ref
                    or receipt.get("policy_version") != policy_version
                    or receipt.get("input_sha256") != source_sha
                    or receipt.get("output_sha256") != output_sha):
                await self._discard_artifact(safe_run_id, artifact_ref)
                return {"status": "unsupported", "reason_code": "coverage_unverified", "source_revision": source_revision}
            receipt_ref = _opaque(receipt.get("receipt_ref"), "receipt_ref")
            return {
                "status": "ok", "artifact_ref": artifact_ref, "receipt_ref": receipt_ref,
                "source_revision": source_revision, "policy_version": policy_version,
            }
        except ReportHostPortError:
            raise
        except Exception:
            # Never include a source path, PII, plugin exception, or profile in the result.
            return {"status": "unsupported", "reason_code": "anonymization_unavailable", "source_revision": source_revision}

    async def verify_receipt(
        self,
        receipt_ref: str,
        *,
        run_id: str,
        source_ref: str,
        source_revision: str,
        artifact_ref: str,
        expected_input_sha256: str,
    ) -> dict[str, Any]:
        safe_receipt_ref = _opaque(receipt_ref, "receipt_ref")
        safe_run_id = _opaque(run_id, "run_id")
        safe_source_ref = _opaque(source_ref, "source_ref")
        safe_artifact_ref = _opaque(artifact_ref, "artifact_ref")
        safe_source_revision = _opaque(source_revision, "source_revision")
        self._verified_reads.pop((safe_run_id, safe_artifact_ref), None)
        if re.fullmatch(r"[0-9a-f]{64}", safe_source_revision) is None:
            return _receipt_projection(
                False, safe_run_id, safe_source_ref, safe_source_revision, safe_artifact_ref,
                safe_receipt_ref, expected_input_sha256, None, None,
            )
        if not isinstance(expected_input_sha256, str) or re.fullmatch(
            r"[0-9a-f]{64}", expected_input_sha256
        ) is None:
            return _receipt_projection(
                False, safe_run_id, safe_source_ref, safe_source_revision, safe_artifact_ref,
                safe_receipt_ref, None, None, None,
            )
        try:
            raw = await _resolve(self._receipt_authority.verify(
                safe_receipt_ref,
                {
                    "run_id": safe_run_id,
                    "source_ref": safe_source_ref,
                    "source_revision": safe_source_revision,
                    "artifact_ref": safe_artifact_ref,
                    "input_sha256": expected_input_sha256,
                },
            ))
            data = _wire(raw)
            required = {
                "verified", "coverage", "policy_version", "run_id", "source_ref", "source_revision",
                "artifact_ref", "receipt_ref", "input_sha256", "output_sha256",
            }
            verified = (
                set(data) == required and data.get("verified") is True and data.get("coverage") == "complete"
                and data.get("run_id") == safe_run_id and data.get("source_ref") == safe_source_ref
                and data.get("source_revision") == safe_source_revision and data.get("artifact_ref") == safe_artifact_ref
                and data.get("receipt_ref") == safe_receipt_ref and data.get("input_sha256") == expected_input_sha256
                and isinstance(data.get("output_sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", data["output_sha256"]) is not None
                and isinstance(data.get("policy_version"), str)
                and _opaque(data["policy_version"], "policy_version") == data["policy_version"]
            )
            if verified:
                self._verified_reads[(safe_run_id, safe_artifact_ref)] = {
                    "receipt_ref": safe_receipt_ref,
                    "source_ref": safe_source_ref,
                    "source_revision": safe_source_revision,
                    "input_sha256": expected_input_sha256,
                    "output_sha256": data["output_sha256"],
                    "policy_version": data["policy_version"],
                }
                return _receipt_projection(
                    True, safe_run_id, safe_source_ref, safe_source_revision, safe_artifact_ref,
                    safe_receipt_ref, expected_input_sha256, data["output_sha256"], data["policy_version"],
                )
            return _receipt_projection(
                False, safe_run_id, safe_source_ref, safe_source_revision, safe_artifact_ref,
                safe_receipt_ref, expected_input_sha256, None, None,
            )
        except Exception:
            return _receipt_projection(
                False, safe_run_id, safe_source_ref, safe_source_revision, safe_artifact_ref,
                safe_receipt_ref, expected_input_sha256, None, None,
            )

    async def read_artifact(self, artifact_ref: str, *, run_id: str) -> bytes | str:
        safe_ref = _opaque(artifact_ref, "artifact_ref")
        safe_run_id = _opaque(run_id, "run_id")
        verified = self._verified_reads.pop((safe_run_id, safe_ref), None)
        if verified is None:
            raise ReportHostPortError("receipt_required")
        verifier = _require_port_method(self._receipt_authority, "verify")
        try:
            receipt = _wire(await _resolve(verifier(
                verified["receipt_ref"],
                {
                    "run_id": safe_run_id,
                    "source_ref": verified["source_ref"],
                    "source_revision": verified["source_revision"],
                    "artifact_ref": safe_ref,
                    "input_sha256": verified["input_sha256"],
                },
            )))
            expected_keys = {
                "verified", "coverage", "policy_version", "run_id", "source_ref", "source_revision",
                "artifact_ref", "receipt_ref", "input_sha256", "output_sha256",
            }
            if (set(receipt) != expected_keys or receipt.get("verified") is not True
                    or receipt.get("coverage") != "complete" or receipt.get("run_id") != safe_run_id
                    or receipt.get("source_ref") != verified["source_ref"]
                    or receipt.get("source_revision") != verified["source_revision"]
                    or receipt.get("artifact_ref") != safe_ref
                    or receipt.get("receipt_ref") != verified["receipt_ref"]
                    or receipt.get("input_sha256") != verified["input_sha256"]
                    or receipt.get("output_sha256") != verified["output_sha256"]
                    or receipt.get("policy_version") != verified["policy_version"]):
                raise ReportHostPortError("coverage_unverified")
        except ReportHostPortError:
            raise
        except Exception:
            raise ReportHostPortError("coverage_unverified") from None
        reader = _require_port_method(self._artifact_store, "read")
        try:
            content = await _resolve(reader(safe_run_id, safe_ref))
            if not isinstance(content, (bytes, str)):
                raise ReportHostPortError("artifact_unavailable")
            content_bytes = content.encode("utf-8") if isinstance(content, str) else content
            if hashlib.sha256(content_bytes).hexdigest() != verified["output_sha256"]:
                raise ReportHostPortError("artifact_integrity_failed")
            return content
        except ReportHostPortError:
            raise
        except Exception:
            raise ReportHostPortError("artifact_unavailable") from None

    async def verify_report(self, report: Mapping[str, Any], receipt_refs: Any) -> dict[str, Any]:
        verifier = getattr(self._receipt_authority, "verify_report", None)
        if not callable(verifier):
            return {"verified": False, "reason_code": "coverage_unverified"}
        try:
            data = _wire(await _resolve(verifier(report, receipt_refs)))
            return {"verified": data.get("verified") is True}
        except Exception:
            return {"verified": False, "reason_code": "coverage_unverified"}

    async def restore_report(self, report: Mapping[str, Any], receipt_refs: Any, *, run_id: str) -> Any:
        if not callable(self._restore_report):
            raise ReportHostPortError("restore_unavailable")
        return await _resolve(self._restore_report(report, receipt_refs, run_id=run_id))

    async def _discard_artifact(self, run_id: str, artifact_ref: str) -> None:
        delete = getattr(self._artifact_store, "delete", None)
        if callable(delete):
            try:
                await _resolve(delete(run_id, artifact_ref))
            except Exception:
                pass

    async def delete_run_artifacts(self, run_id: str, artifact_refs: Any) -> dict[str, Any]:
        safe_run_id = _opaque(run_id, "run_id")
        refs = _artifact_ref_list(artifact_refs)
        return await _delete_run_artifacts(self._artifact_store, safe_run_id, refs)


class BachModelRoutePort:
    """Run-pinned model port with native admission for local inference."""

    def __init__(
        self,
        backend: Any,
        model: str,
        mode: str,
        *,
        cloud_attestor: Any = None,
        runtime: Any = None,
        agent_id: str | None = None,
        execution_profile_reader: OwnerExecutionProfileReader | None = None,
    ) -> None:
        if mode not in {"local", "cloud"} or not isinstance(model, str) or not model:
            raise ValueError("invalid report model route configuration")
        self._backend = backend
        self._model = model
        self._mode = mode
        self._cloud_attestor = cloud_attestor
        self._runtime = runtime
        self._agent_id = agent_id
        self._execution_profile_reader = execution_profile_reader
        self._pins: dict[tuple[str, str, str], tuple[str, str, str, dict[str, Any] | None]] = {}

    def _local_route_snapshot(self) -> dict[str, Any] | None:
        """Bind one configured slot, local model and real BACH dispatcher."""
        if (self._mode != "local" or not isinstance(self._agent_id, str)
                or re.fullmatch(r"[A-Za-z0-9_-]{1,80}", self._agent_id) is None
                or self._model.lower().endswith(":cloud")):
            return None
        try:
            from hub._services.agent_manage_service import verified_local_agent_model
            from hub._services.chat import model_sockets, slots_config
            from hub._services.chat.chat_runtime import ChatRuntime
            from hub._services.llm.model_backend import (
                LMStudioBackend,
                OllamaBackend,
                backend_identifier,
            )

            if (type(self._runtime) is not ChatRuntime
                    or type(self._backend) not in {OllamaBackend, LMStudioBackend}
                    or self._runtime.backend is not self._backend
                    or getattr(self._runtime, "require_model_socket_config", None) is not True
                    or not callable(getattr(self._runtime, "prepare_inference_call", None))
                    or not callable(getattr(self._runtime, "_chat_with_compute_turn", None))):
                return None
            reader = self._execution_profile_reader
            if (type(reader) is not OwnerExecutionProfileReader
                    or reader.agent_id != self._agent_id):
                return None

            identifier = backend_identifier(self._backend)
            base_url = getattr(self._backend, "base_url", None)
            if identifier not in {"ollama", "lmstudio"} or not isinstance(base_url, str):
                return None
            endpoint = urlsplit(base_url)
            if (endpoint.scheme not in {"http", "https"}
                    or endpoint.hostname not in {"localhost", "127.0.0.1", "::1"}
                    or endpoint.username is not None or endpoint.password is not None
                    or endpoint.query or endpoint.fragment):
                return None
            if (not isinstance(self._model, str) or not self._model.strip()
                    or self._model.lower() in {"auto", "default", "local-model"}):
                return None

            profile = reader.read()
            if (not isinstance(profile, dict) or profile.get("id") != self._agent_id
                    or profile.get("enabled") is not True
                    or profile.get("execution_kind") != "worker"
                    or profile.get("backend") != identifier
                    or profile.get("model") != self._model):
                return None
            binding = model_sockets.model_binding_for_call(
                f"report-local-{secrets.token_hex(16)}",
                identifier,
                self._model,
                agent_id=self._agent_id,
                require_config=True,
            )
            required = {"agent_id": self._agent_id, "backend": identifier, "model": self._model}
            if (not isinstance(binding, dict)
                    or any(binding.get(key) != value for key, value in required.items())
                    or binding.get("priority") not in {"foreground", "background"}
                    or not isinstance(binding.get("configuration_version"), str)
                    or re.fullmatch(r"[0-9a-f]{64}", binding["configuration_version"]) is None):
                return None
            if verified_local_agent_model(self._backend, self._model) is not True:
                return None

            binding_fingerprint = "\0".join((
                self._agent_id, binding["socket_id"], binding["binding_id"],
                binding["configuration_version"], binding["priority"],
                str(profile["blueprint_id"]), str(profile["blueprint_version"]),
                profile["governance_binding"]["effective_sha256"],
            ))
            return {
                "binding": dict(binding),
                "profile": dict(profile),
                "route_id": _route_id("local", identifier, f"{self._model}\0{binding_fingerprint}"),
            }
        except Exception:
            # Do not project native configuration, metadata, or runtime errors.
            return None

    def _signature(self) -> tuple[str, str, str]:
        from hub._services.llm.model_backend import backend_identifier

        identifier = backend_identifier(self._backend)
        base_url = str(getattr(self._backend, "base_url", ""))
        base_digest = hashlib.sha256(base_url.encode("utf-8")).hexdigest()
        return identifier, self._model, base_digest

    async def route_status(self) -> dict[str, Any]:
        identifier, model, _base_digest = self._signature()
        if self._mode == "local":
            snapshot = self._local_route_snapshot()
            local = snapshot is not None
            return {
                "available": local,
                "mode": "local",
                "verified_local": local,
                "cloud_route": False,
                "local_only": True,
                "fallback_disabled": True,
                "route_id": (snapshot["route_id"] if snapshot is not None
                             else _route_id("local", identifier, model)),
                **({} if local else {"reason_code": "provider_route_unverified"}),
            }
        if not callable(self._cloud_attestor):
            return {"available": False, "cloud_route": False, "fallback_disabled": True}
        try:
            raw = await _resolve(self._cloud_attestor(self._backend, model))
            data = _wire(raw)
            route_id = _opaque(data.get("route_id"), "route_id")
            ok = (data.get("verified") is True and data.get("cloud_route") is True
                  and data.get("fallback_disabled") is True)
            return {
                "available": ok,
                "mode": "cloud",
                "verified": ok,
                "cloud_route": ok,
                "local_only": False,
                "fallback_disabled": ok,
                "route_id": route_id,
            }
        except Exception:
            return {"available": False, "mode": "cloud", "cloud_route": False,
                    "local_only": False, "fallback_disabled": True}

    async def pin_route(
        self,
        run_id: str,
        *,
        expected_mode: str,
        request_mode: str | None = None,
        allow_fallback: bool = False,
        local_only: bool | None = None,
    ) -> dict[str, Any]:
        safe_run_id = _opaque(run_id, "run_id")
        request_mode = request_mode or expected_mode
        if (expected_mode != self._mode or request_mode not in {"local", "cloud", "hybrid"}
                or allow_fallback is not False or type(local_only) is not bool
                or local_only is not (self._mode == "local")):
            return {"verified": False, "reason_code": "route_policy_mismatch"}
        status = await self.route_status()
        signature = self._signature()
        route_id = status.get("route_id")
        if (status.get("available") is not True or not isinstance(route_id, str)
                or status.get("mode") != self._mode
                or status.get("local_only") is not (self._mode == "local")
                or status.get("fallback_disabled") is not True):
            return {"verified": False, "reason_code": "route_unavailable"}
        if self._mode == "local":
            if (status.get("verified_local") is not True or status.get("cloud_route") is not False
                    or status.get("local_only") is not True or local_only is not True):
                return {"verified": False, "reason_code": "provider_route_unverified"}
            local_flag = True
            local_snapshot = self._local_route_snapshot()
            if local_snapshot is None or local_snapshot.get("route_id") != route_id:
                return {"verified": False, "reason_code": "provider_route_unverified"}
            local_binding = local_snapshot["binding"]
        else:
            if status.get("cloud_route") is not True or local_only is not False:
                return {"verified": False, "reason_code": "cloud_route_unverified"}
            local_flag = False
            local_binding = None
        route_ref = secrets.token_urlsafe(24).replace("-", "x").replace("_", "y")
        self._pins[(safe_run_id, self._mode, request_mode)] = (
            route_id, route_ref, signature[2], local_binding,
        )
        return {
            "verified": True,
            "run_id": safe_run_id,
            "mode": self._mode,
            "request_mode": request_mode,
            "route_id": route_id,
            "route_ref": route_ref,
            "verified_local": self._mode == "local",
            "cloud_route": self._mode == "cloud",
            "local_only": local_flag,
            "fallback_disabled": True,
        }

    async def generate(
        self,
        prompt: str,
        *,
        run_id: str,
        mode: str,
        request_mode: str,
        route_id: str,
        route_ref: str,
        allow_fallback: bool = False,
        local_only: bool = False,
        purpose: str = "report",
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        safe_run_id = _opaque(run_id, "run_id")
        safe_route_id = _opaque(route_id, "route_id")
        safe_route_ref = _opaque(route_ref, "route_ref")
        if request_mode not in {"local", "cloud", "hybrid"}:
            raise ReportHostPortError("route_pin_mismatch")
        key = (safe_run_id, self._mode, request_mode)
        pin = self._pins.get(key)
        signature = self._signature()
        if (mode != self._mode or allow_fallback is not False or type(local_only) is not bool
                or local_only != (self._mode == "local") or pin is None
                or pin[:3] != (safe_route_id, safe_route_ref, signature[2]) or not isinstance(prompt, str)
                or len(prompt.encode("utf-8")) > 2_000_000
                or (system_prompt is not None and (not isinstance(system_prompt, str)
                    or len(system_prompt.encode("utf-8")) > 256_000))):
            raise ReportHostPortError("route_pin_mismatch")
        current = await self.route_status()
        if (current.get("available") is not True or current.get("mode") != self._mode
                or current.get("local_only") is not (self._mode == "local")
                or current.get("route_id") != safe_route_id
                or current.get("fallback_disabled") is not True
                or (self._mode == "local" and (
                    current.get("verified_local") is not True or current.get("cloud_route") is not False
                    or current.get("local_only") is not True
                ))
                or (self._mode == "cloud" and current.get("cloud_route") is not True)):
            raise ReportHostPortError("provider_route_unverified")
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        try:
            if self._mode == "local":
                if not isinstance(pin[3], dict):
                    raise ReportHostPortError("provider_route_unverified")
                _require_local_context_fit(self._runtime, self._backend, self._model, messages)
                result = await self._generate_local(
                    messages,
                    expected_route_id=safe_route_id,
                    expected_binding=pin[3],
                )
            else:
                result = await self._backend.chat(messages, tools=None, model=self._model)
        except ReportHostPortError:
            raise
        except Exception:
            raise ReportHostPortError("model_call_failed") from None
        if isinstance(result, str):
            text = result
        elif isinstance(result, Mapping) and isinstance(result.get("content"), str):
            if result.get("error"):
                raise ReportHostPortError("model_call_failed")
            text = result["content"]
        else:
            raise ReportHostPortError("invalid_model_response")
        if len(text.encode("utf-8")) > 2_000_000:
            raise ReportHostPortError("model_response_too_large")
        return {
            "text": text,
            "run_id": safe_run_id,
            "mode": self._mode,
            "request_mode": request_mode,
            "route_id": safe_route_id,
            "route_ref": safe_route_ref,
        }

    async def _generate_local(
        self,
        messages: list[dict[str, str]],
        *,
        expected_route_id: str,
        expected_binding: dict[str, Any],
    ) -> Any:
        """Use the owning ChatRuntime gates and re-attest at backend dispatch."""
        from hub._services.chat import slots_config
        from hub._services.chat.chat_runtime import ChatRuntime, ChatSession

        runtime = self._runtime
        if type(runtime) is not ChatRuntime:
            raise ReportHostPortError("provider_route_unverified")
        snapshot = self._local_route_snapshot()
        if (snapshot is None or snapshot.get("route_id") != expected_route_id
                or snapshot.get("binding") != expected_binding):
            raise ReportHostPortError("provider_route_unverified")

        chat_id = f"report-local-{secrets.token_hex(16)}"
        profile = snapshot["profile"]
        session = ChatSession()
        session.chat_id = chat_id
        session.backend = self._backend
        session.model = self._model
        session.resolved_model = self._model
        session.system_slot_id = self._agent_id
        reader = self._execution_profile_reader
        if type(reader) is not OwnerExecutionProfileReader or reader.agent_id != self._agent_id:
            raise ReportHostPortError("provider_route_unverified")
        session.system_slot_reader = reader.read
        session.system_slot_configuration = {
            key: profile.get(key)
            for key in slots_config.CORE_EDITABLE_FIELDS
            if key != "enabled"
        }
        session.allow_tools = False
        session.allowed_tools = []
        session._trusted_memory_hook_opt_in = False
        if chat_id in runtime.sessions:
            raise ReportHostPortError("provider_route_unverified")
        runtime.sessions[chat_id] = session

        async def dispatch(*args: Any, **kwargs: Any) -> Any:
            if (len(args) != 1 or not isinstance(args[0], list)
                    or kwargs.get("model") != self._model
                    or kwargs.get("tools") is not None):
                raise ReportHostPortError("provider_route_unverified")
            try:
                from hub._services.chat.host_inference_gate import HostInferenceGate

                owner = HostInferenceGate().status()
                target = owner.get("model_target") if isinstance(owner, dict) else None
                with runtime._compute_turn_gate.condition:
                    compute_owned = (
                        runtime._compute_turn_gate.active is True
                        and runtime._compute_turn_gate.chat_id == chat_id
                        and runtime._compute_turn_gate.priority == expected_binding["priority"]
                    )
                if (owner.get("active") is not True
                        or owner.get("chat_id") != chat_id
                        or owner.get("priority") != expected_binding["priority"]
                        or not isinstance(target, dict)
                        or any(target.get(key) != expected_binding.get(key) for key in (
                            "socket_id", "binding_id", "agent_id", "backend", "model",
                        ))
                        or not compute_owned):
                    raise ReportHostPortError("provider_route_unverified")
            except ReportHostPortError:
                raise
            except Exception:
                raise ReportHostPortError("provider_route_unverified") from None
            try:
                receipt, binding = await runtime.prepare_inference_call(
                    guarded_backend,
                    self._model,
                    chat_id=chat_id,
                )
            except Exception:
                raise ReportHostPortError("provider_route_unverified") from None
            if (not isinstance(receipt, dict)
                    or receipt.get("state") != "ready"
                    or receipt.get("admitted") is not True
                    or receipt.get("enforced") is not True
                    or receipt.get("retryable") is not False
                    or binding != expected_binding):
                raise ReportHostPortError("provider_route_unverified")

            # This checks the effective slot/socket and model metadata at the
            # final backend boundary. It cannot prevent a server-side target
            # change after the metadata request has returned.
            current = self._local_route_snapshot()
            if (current is None or current.get("route_id") != expected_route_id
                    or current.get("binding") != expected_binding):
                raise ReportHostPortError("provider_route_unverified")
            return await self._backend.chat(*args, **kwargs)

        guarded_backend = _make_guarded_backend(self._backend, dispatch)
        token = runtime._compute_turn_context.set((chat_id, expected_binding["priority"]))
        try:
            return await runtime._chat_with_compute_turn(
                guarded_backend,
                messages,
                tools=None,
                model=self._model,
            )
        except ReportHostPortError:
            raise
        except Exception:
            raise ReportHostPortError("provider_route_unverified") from None
        finally:
            runtime._compute_turn_context.reset(token)
            if runtime.sessions.get(chat_id) is session:
                runtime.sessions.pop(chat_id, None)
            runtime._session_locks.pop(chat_id, None)
            with runtime._chat_turn_gates_lock:
                runtime._chat_turn_gates.pop(chat_id, None)
            with runtime._local_resource_waiters_lock:
                runtime._local_resource_waiters.pop(chat_id, None)
            with runtime._task_completion_receipts_lock:
                runtime._task_completion_receipts.pop(chat_id, None)


# Conservative estimate for German report text, so a borderline prompt is
# refused rather than truncated.
_LOCAL_CHARS_PER_TOKEN = 3
_LOCAL_RESPONSE_RESERVE_TOKENS = 4096


def _require_local_context_fit(runtime: Any, backend: Any, model: str,
                               messages: list[dict[str, str]]) -> None:
    """Refuse a local call whose prompt cannot fit the backend context window.

    Ollama keeps only the newest tokens of an oversized prompt and does not
    report an error, so the model would silently lose the report instructions
    and parts of the source. The limit is the same value the runtime sends as
    ``num_ctx``; part of it stays reserved for the answer.
    """
    try:
        limit = int(runtime._context_limit_for_backend(backend, model))
    except Exception:
        raise ReportHostPortError("local_route_unverified") from None
    if limit <= 0:
        raise ReportHostPortError("local_route_unverified")
    chars = sum(len(message.get("content", "")) for message in messages)
    reserve = min(_LOCAL_RESPONSE_RESERVE_TOKENS, limit // 4)
    if math.ceil(chars / _LOCAL_CHARS_PER_TOKEN) + reserve > limit:
        raise ReportHostPortError("source_extraction_incomplete")


class _GuardedBackend:
    """Recognized backend proxy that gates the actual chat call."""

    def __init__(self, delegate: Any, dispatch: Any) -> None:
        self._delegate = delegate
        self._dispatch = dispatch

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    async def chat(self, *args: Any, **kwargs: Any) -> Any:
        return await self._dispatch(*args, **kwargs)


def _make_guarded_backend(delegate: Any, dispatch: Any) -> Any:
    """Return only a proxy recognized by one of BACH's two local backends."""
    from hub._services.llm.model_backend import LMStudioBackend, OllamaBackend

    if type(delegate) is OllamaBackend:
        backend_type = OllamaBackend
        name = "_ReportGuardedOllamaBackend"
    elif type(delegate) is LMStudioBackend:
        backend_type = LMStudioBackend
        name = "_ReportGuardedLMStudioBackend"
    else:
        raise ReportHostPortError("provider_route_unverified")
    proxy_type = type(name, (_GuardedBackend, backend_type), {})
    return proxy_type(delegate, dispatch)


def _route_id(mode: str, backend: str, model: str) -> str:
    digest = hashlib.sha256(f"{mode}\0{backend}\0{model}".encode("utf-8")).hexdigest()
    return f"{mode}_{digest[:32]}"


def _trusted_config(raw: Any, allowed: set[str], field: str) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or any(not isinstance(key, str) for key in raw):
        raise ReportHostPortError(f"invalid_{field}_configuration")
    data = dict(raw)
    if not set(data) <= allowed:
        raise ReportHostPortError(f"invalid_{field}_configuration")
    return data


def build_report_host_ports(
    *,
    word_template: Mapping[str, Any] | None = None,
    anonymizer: Mapping[str, Any] | None = None,
    document_reader: Mapping[str, Any] | None = None,
    operator_confirmation: Any = None,
    local_model: Mapping[str, Any] | None = None,
    cloud_model: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build explicitly configured generic ports from trusted host settings.

    The mappings are supplied by the application host, never from request
    fields. Missing ports stay absent, so an installed provider can report
    ``unavailable`` without guessing a path, model, endpoint, or consent.
    """
    ports: dict[str, Any] = {}
    word = _trusted_config(
        word_template,
        {"artifact_store", "service"},
        "word_template",
    )
    if word is not None:
        if "artifact_store" not in word:
            raise ReportHostPortError("incomplete_word_template_configuration")
        _require_port_method(word["artifact_store"], "put")
        ports["word_template"] = BachWordTemplatePort(
            word["artifact_store"], service=word.get("service"),
        )

    reader = _trusted_config(document_reader, {"service"}, "document_reader")
    ports["document_reader"] = BachDocumentReaderPort(
        service=reader.get("service") if reader is not None else None
    )

    anon = _trusted_config(
        anonymizer,
        {"artifact_store", "profile_factory", "receipt_authority", "service", "restore_report"},
        "anonymizer",
    )
    if anon is not None:
        if not {"artifact_store", "profile_factory", "receipt_authority"} <= set(anon):
            raise ReportHostPortError("incomplete_anonymizer_configuration")
        _require_port_method(anon["artifact_store"], "put")
        _require_port_method(anon["artifact_store"], "read")
        _require_port_method(anon["receipt_authority"], "issue")
        _require_port_method(anon["receipt_authority"], "verify")
        ports["anonymizer"] = BachDocumentAnonymizerPort(
            anon["artifact_store"], anon["profile_factory"], anon["receipt_authority"],
            service=anon.get("service"), restore_report=anon.get("restore_report"),
        )

    if operator_confirmation is not None:
        if not callable(getattr(operator_confirmation, "verify_confirmation", None)):
            raise ReportHostPortError("operator_confirmation_unavailable")
        ports["operator_confirmation"] = BachOperatorConfirmationPort(operator_confirmation)

    local = _trusted_config(
        local_model,
        {"backend", "model", "runtime", "agent_id", "execution_profile_reader"},
        "local_model",
    )
    if local is not None:
        if not {"backend", "model"} <= set(local):
            raise ReportHostPortError("incomplete_local_model_configuration")
        ports["local_model"] = BachModelRoutePort(
            local["backend"],
            local["model"],
            "local",
            runtime=local.get("runtime"),
            agent_id=local.get("agent_id"),
            execution_profile_reader=local.get("execution_profile_reader"),
        )

    cloud = _trusted_config(cloud_model, {"backend", "model", "cloud_attestor"}, "cloud_model")
    if cloud is not None:
        if set(cloud) != {"backend", "model", "cloud_attestor"}:
            raise ReportHostPortError("incomplete_cloud_model_configuration")
        ports["cloud_model"] = BachModelRoutePort(
            cloud["backend"], cloud["model"], "cloud", cloud_attestor=cloud["cloud_attestor"]
        )
    return ports


class UnavailableReportProvider:
    """Safe result when no uniquely selected private provider is installed."""

    def __init__(self, reason_code: str = "provider_missing") -> None:
        self._reason_code = _reason(reason_code, "provider_missing")

    async def capabilities(self) -> dict[str, Any]:
        mode_statuses = {
            mode: {"available": False, "reason_code": self._reason_code}
            for mode in ("local", "cloud", "hybrid")
        }
        return {
            "schema": SCHEMA,
            "available": False,
            "modes": [],
            "watcher_available": False,
            "mode_statuses": mode_statuses,
            "reason_code": self._reason_code,
        }

    async def prepare(self, request: Mapping[str, Any]) -> dict[str, Any]:
        parsed = ReportRequest.from_wire(request)
        return PreparedRun(
            run_id=None,
            status="unavailable",
            preview_ref=None,
            expires_at=None,
            request_digest=parsed.digest,
            source_revision=None,
            template_revision=None,
            source_count=0,
            reason_code=self._reason_code,
        ).to_wire()

    async def finish(self, run_id: str, approval: Mapping[str, Any]) -> dict[str, Any]:
        safe_run_id = _opaque(run_id, "run_id")
        return ReportResult(
            safe_run_id, "unavailable", "none", self._reason_code, ()
        ).to_wire()

    async def status(self, run_id: str) -> dict[str, Any]:
        safe_run_id = _opaque(run_id, "run_id")
        return {
            "schema": SCHEMA,
            "run_id": safe_run_id,
            "status": "unavailable",
            "reason_code": self._reason_code,
            "review_required": True,
        }

    async def cleanup(self, run_id: str, approval: Mapping[str, Any]) -> dict[str, Any]:
        safe_run_id = _opaque(run_id, "run_id")
        return {
            "schema": SCHEMA,
            "run_id": safe_run_id,
            "status": "unavailable",
            "reason_code": self._reason_code,
            "sources_retained": True,
        }

    async def watcher_status(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "status": "disabled", "enabled": False}


class ReportProviderAdapter:
    """Validate and privacy-project calls to a structurally compatible provider."""

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    @classmethod
    def unavailable(cls, reason_code: str) -> "ReportProviderAdapter":
        return cls(UnavailableReportProvider(reason_code))

    async def capabilities(self) -> dict[str, Any]:
        try:
            raw = await _resolve(self._provider.capabilities())
            return ProviderCapabilities.from_wire(raw).to_wire()
        except Exception:
            return await UnavailableReportProvider("provider_unavailable").capabilities()

    async def list_sources(self, subject_ref: str) -> dict[str, Any]:
        """Project a complete private catalog into opaque metadata only."""
        safe_subject_ref = _opaque(subject_ref, "subject_ref")
        unavailable = {"schema": SCHEMA, "complete": False, "sources": []}
        if re.fullmatch(r"sub_[0-9a-f]{48}", safe_subject_ref) is None:
            raise ReportContractError("invalid_subject_ref")
        method = getattr(self._provider, "list_sources", None)
        if not callable(method):
            return unavailable
        try:
            data = _wire(await _resolve(method(safe_subject_ref)))
            if (set(data) != {"schema", "complete", "sources"} or data.get("schema") != SCHEMA
                    or type(data.get("complete")) is not bool):
                return unavailable
            raw_sources = data.get("sources")
            if not isinstance(raw_sources, (list, tuple)) or len(raw_sources) > 200:
                return unavailable
            if data["complete"] is False:
                # A partial result must not look like an empty inventory.
                return unavailable
            sources: list[dict[str, str]] = []
            seen_refs: set[str] = set()
            for raw_source in raw_sources:
                source = _wire(raw_source)
                if set(source) != {"source_ref", "source_revision", "media_type"}:
                    return unavailable
                source_ref = _opaque(source.get("source_ref"), "source_ref")
                if re.fullmatch(r"src_[0-9a-f]{48}", source_ref) is None or source_ref in seen_refs:
                    return unavailable
                revision = source.get("source_revision")
                media_type = source.get("media_type")
                if (not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{64}", revision) is None
                        or not isinstance(media_type, str) or media_type not in _SOURCE_MEDIA_TYPES):
                    return unavailable
                seen_refs.add(source_ref)
                sources.append({
                    "source_ref": source_ref,
                    "source_revision": revision,
                    "media_type": media_type,
                })
            return {"schema": SCHEMA, "complete": True, "sources": sources}
        except Exception:
            return unavailable

    async def prepare(self, request: Any) -> dict[str, Any]:
        parsed = ReportRequest.from_wire(request)
        try:
            raw = await _resolve(self._provider.prepare(parsed.to_wire()))
            return PreparedRun.from_wire(raw, expected_digest=parsed.digest).to_wire()
        except ReportContractError:
            raise
        except Exception:
            return PreparedRun(
                run_id=None,
                status="unavailable",
                preview_ref=None,
                expires_at=None,
                request_digest=parsed.digest,
                source_revision=None,
                template_revision=None,
                source_count=0,
                reason_code="provider_unavailable",
            ).to_wire()

    async def finish(self, run_id: str, approval: Any) -> dict[str, Any]:
        safe_run_id = _opaque(run_id, "run_id")
        parsed_approval = ReportApproval.from_wire(approval)
        try:
            raw = await _resolve(self._provider.finish(safe_run_id, parsed_approval.to_wire()))
            return ReportResult.from_wire(raw, expected_run_id=safe_run_id).to_wire()
        except ReportContractError:
            raise
        except Exception:
            return ReportResult(
                safe_run_id, "unavailable", "unknown", "provider_unavailable", ()
            ).to_wire()

    async def status(self, run_id: str) -> dict[str, Any]:
        safe_run_id = _opaque(run_id, "run_id")
        try:
            data = _wire(await _resolve(self._provider.status(safe_run_id)))
            required = {"schema", "run_id", "status", "review_required"}
            if frozenset(data) not in {frozenset(required), frozenset(required | {"reason_code"})}:
                raise ReportContractError("invalid_status_shape")
            if (data.get("schema") != SCHEMA or data.get("run_id") != safe_run_id
                    or data.get("review_required") is not True):
                raise ReportContractError("invalid_status")
            status = data.get("status")
            if status not in _SAFE_STATES:
                raise ReportContractError("invalid_status")
            if "reason_code" in data and (
                not is_neutral_reason_code(data["reason_code"])
            ):
                raise ReportContractError("invalid_status_reason")
            result: dict[str, Any] = {
                "schema": SCHEMA,
                "run_id": safe_run_id,
                "status": status,
                "review_required": True,
            }
            if "reason_code" in data:
                result["reason_code"] = _reason(data["reason_code"], "provider_unavailable")
            return result
        except Exception:
            return {
                "schema": SCHEMA,
                "run_id": safe_run_id,
                "status": "unknown",
                "reason_code": "provider_unavailable",
                "review_required": True,
            }

    async def cleanup(self, run_id: str, approval: Any) -> dict[str, Any]:
        safe_run_id = _opaque(run_id, "run_id")
        consent = CleanupApproval.from_wire(approval, expected_run_id=safe_run_id)
        if consent.delete_sources:
            # Source deletion is intentionally unsupported until the neutral
            # result can represent partial or unknown retention honestly.
            return {
                "schema": SCHEMA,
                "run_id": safe_run_id,
                "status": "blocked",
                "reason_code": "source_deletion_unsupported",
                "sources_retained": True,
            }
        try:
            data = _wire(await _resolve(self._provider.cleanup(safe_run_id, consent.to_wire())))
            required = {"schema", "run_id", "status", "sources_retained"}
            if frozenset(data) not in {frozenset(required), frozenset(required | {"reason_code"})}:
                raise ReportContractError("invalid_cleanup_shape")
            if data.get("schema") != SCHEMA or data.get("run_id") != safe_run_id:
                raise ReportContractError("invalid_cleanup")
            status = data.get("status")
            if status not in {"cleaned", "blocked", "cleanup_failed", "unavailable", "unknown"}:
                raise ReportContractError("invalid_cleanup")
            retained = data.get("sources_retained")
            if type(retained) is not bool:
                raise ReportContractError("invalid_cleanup")
            if "reason_code" in data and (
                not is_neutral_reason_code(data["reason_code"])
            ):
                raise ReportContractError("invalid_cleanup_reason")
            result = {
                "schema": SCHEMA,
                "run_id": safe_run_id,
                "status": status,
                "sources_retained": retained,
            }
            if "reason_code" in data:
                result["reason_code"] = _reason(data["reason_code"], "cleanup_failed")
            return result
        except Exception:
            return {
                "schema": SCHEMA,
                "run_id": safe_run_id,
                "status": "unknown",
                "reason_code": "cleanup_failed",
                "sources_retained": True,
            }

    async def watcher_configure(self, config: Any) -> dict[str, Any]:
        parsed = WatcherConfig.from_wire(config)
        return await self._watcher_call("watcher_configure", parsed.to_wire())

    async def watcher_status(self) -> dict[str, Any]:
        if not callable(getattr(self._provider, "watcher_status", None)):
            return {"schema": SCHEMA, "status": "disabled", "enabled": False}
        return await self._watcher_call("watcher_status")

    async def watcher_tick(self, now: str | None = None) -> dict[str, Any]:
        return await self._watcher_call("watcher_tick", now)

    async def _watcher_call(self, method_name: str, *args: Any) -> dict[str, Any]:
        method = getattr(self._provider, method_name, None)
        if not callable(method):
            return {"schema": SCHEMA, "status": "disabled", "enabled": False}
        try:
            raw = await _resolve(method(*args))
            data = _wire(raw)
            required = {"schema", "status", "enabled"}
            if frozenset(data) not in {frozenset(required), frozenset(required | {"reason_code"})}:
                raise ReportContractError("invalid_watcher_response_shape")
            status = data.get("status")
            enabled = data.get("enabled")
            if data.get("schema") != SCHEMA or status not in _SAFE_STATES or type(enabled) is not bool:
                raise ReportContractError("invalid_watcher_response")
            if "reason_code" in data and (
                not is_neutral_reason_code(data["reason_code"])
            ):
                raise ReportContractError("invalid_watcher_reason")
            result = {"schema": SCHEMA, "status": status, "enabled": enabled}
            if "reason_code" in data:
                result["reason_code"] = _reason(data["reason_code"], "watcher_unavailable")
            return result
        except Exception:
            return {
                "schema": SCHEMA,
                "status": "unknown",
                "enabled": False,
                "reason_code": "watcher_unavailable",
            }


def load_report_provider(
    host_ports: Mapping[str, Any] | None = None,
    *,
    provider_name: str | None = None,
) -> ReportProviderAdapter:
    """Load one optional installed entry point without installing or starting it.

    ``provider_name`` is trusted application configuration, never request data.
    Ambiguous registries fail closed rather than selecting an arbitrary provider.
    """
    try:
        discovered = importlib.metadata.entry_points()
        if hasattr(discovered, "select"):
            entries = list(discovered.select(group=ENTRY_POINT_GROUP))
        else:  # pragma: no cover - compatibility with old Python packaging APIs
            entries = list(discovered.get(ENTRY_POINT_GROUP, ()))
        if provider_name is not None:
            entries = [entry for entry in entries if entry.name == provider_name]
        if not entries:
            return ReportProviderAdapter.unavailable("provider_missing")
        if len(entries) != 1:
            return ReportProviderAdapter.unavailable("provider_ambiguous")
        factory = entries[0].load()
        if not callable(factory):
            return ReportProviderAdapter.unavailable("provider_invalid")
        provider = factory(dict(host_ports or {}))
        if not all(callable(getattr(provider, name, None)) for name in ("capabilities", "prepare", "finish", "status", "cleanup")):
            return ReportProviderAdapter.unavailable("provider_invalid")
        return ReportProviderAdapter(provider)
    except Exception:
        return ReportProviderAdapter.unavailable("provider_unavailable")


def report_result_for_error(run_id: str, reason_code: str, *, effect: str = "none") -> dict[str, Any]:
    """Create a safe, content-free failure result for callers."""
    safe_run_id = _opaque(run_id, "run_id")
    if effect not in {"none", "unknown"}:
        effect = "none"
    return ReportResult(
        safe_run_id, "blocked", effect, _reason(reason_code, "request_blocked"), ()
    ).to_wire()
