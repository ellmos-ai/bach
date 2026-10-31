# SPDX-License-Identifier: MIT
"""Source-aware result facts from trusted DB readers, never worker assertions.

External provenance has its own receipt and revision. None of these helpers
invent native execution fields. Their inputs are internal read_result DTOs;
they are not validators for client-supplied provenance documents.
"""
from __future__ import annotations

import hashlib
import json
import re

from .worker_review_identity import principal_for_execution

EXTERNAL_SCOPE_SCHEMA = "bach.worker-external-scope-evidence.v1"
_HEX = re.compile(r"[a-f0-9]{64}\Z")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def source_kind(record):
    # Existing internal/native fixtures and old in-process DTOs have no tag.
    return record.get("source_kind", "native") if isinstance(record, dict) else None


def external_scope(data):
    """Common scope fields, explicitly tagged with the external schema."""
    fields = {key: data[key] for key in (
        "availability", "reason", "task_id", "result_id", "submission_revision",
        "scope_receipt_sha256", "scope_event_id", "snapshot", "result_revision") if key in data}
    return {**fields, "schema": EXTERNAL_SCOPE_SCHEMA, "source_kind": "external_attested"}


def read_result_source(conn, record):
    """Augment a trusted result, with no DDL, Git or recursive result read.

    A persisted external binding is sticky even if invalid or revoked. It
    must never fall back to native evidence and regain acceptance authority.
    """
    from . import worker_external_attestation as external
    result_id = record["result_id"]
    has_external = (external._exists(conn, external._TABLE) and conn.execute(
        "SELECT 1 FROM worker_external_attestations WHERE result_id=?", (result_id,)).fetchone() is not None)
    if has_external:
        provenance = external.read_external_attestation(conn, record)
        record.update(source_kind="external_attested", external_provenance=provenance,
                      scope=external_scope(provenance), result_revision=None)
    else:
        record["source_kind"] = "native" if external._native_linked(conn, result_id) else "unattested"
    return record


def source_pin(record):
    """DB-verifiable author source, independent of the current Git projection."""
    if not isinstance(record, dict):
        return None
    scope = record.get("scope", {})
    if scope.get("availability") not in {"recorded", "available"}:
        return None
    if source_kind(record) == "external_attested":
        from .worker_external_attestation import external_result_revision
        data = record.get("external_provenance", {})
        if (external_result_revision(data) is None
                or scope.get("schema") != EXTERNAL_SCOPE_SCHEMA
                or scope.get("source_kind") != "external_attested"
                or data.get("task_id") != record.get("task_id")
                or data.get("result_id") != record.get("result_id")
                or data.get("submission_revision") != record.get("submission_revision")
                or any(scope.get(key) != data.get(key) for key in (
                    "scope_receipt_sha256", "scope_event_id", "snapshot"))
                or type(data.get("model_principal_id")) is not str or not data["model_principal_id"]):
            return None
        return {"source_kind": "external_attested", **{key: data[key] for key in (
            "attestation_sha256", "attestation_event_id", "scope_receipt_sha256",
            "scope_event_id", "model_principal_id")}}
    if source_kind(record) != "native":
        return None
    execution = record.get("execution", {})
    if (execution.get("availability") != "available"
            or type(execution.get("execution_id")) is not str or not execution["execution_id"]
            or type(execution.get("execution_revision")) is not str
            or not _HEX.fullmatch(execution["execution_revision"])):
        return None
    receipt, event_id = scope.get("scope_receipt_sha256"), scope.get("scope_event_id")
    if (type(receipt) is not str or not _HEX.fullmatch(receipt)
            or type(event_id) is not int or event_id <= 0):
        return None
    return {"source_kind": "native", "execution_id": execution["execution_id"],
            "execution_revision": execution["execution_revision"], "slot_id": execution.get("slot_id"),
            "scope_receipt_sha256": receipt, "scope_event_id": event_id}


def author_principal(identity, record):
    pin = source_pin(record)
    if pin is None:
        return None
    if pin["source_kind"] == "external_attested":
        # read_external_attestation already resolved the current explicit
        # mapping against the shared global model-principal catalogue.
        return pin["model_principal_id"]
    return principal_for_execution(identity, record["execution"])


def author_slot(record):
    return record.get("execution", {}).get("slot_id") if source_kind(record) == "native" else None


def current_result_revision(record):
    """Pure DB revision reconstruction for final CAS, without observing Git."""
    pin = source_pin(record)
    if pin is None:
        return None
    if pin["source_kind"] == "external_attested":
        from .worker_external_attestation import external_result_revision
        return external_result_revision(record["external_provenance"])
    return _digest({"schema": "bach.worker-result-revision.v1",
        "submission_revision": record.get("submission_revision"),
        "execution_revision": pin["execution_revision"],
        "scope_receipt_sha256": pin["scope_receipt_sha256"], "scope_event_id": pin["scope_event_id"]})
