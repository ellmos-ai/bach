from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from enum import Enum, StrEnum
from typing import Any

CONTRACT_VERSION = "nemofold.contracts.v1"


class PrivacyMode(StrEnum):
    LOCAL_ONLY = "local_only"
    PREVIEW = "preview"
    ALLOW_ONCE = "allow_once"


class ActionMode(StrEnum):
    DRY_RUN = "dry_run"
    APPLY = "apply"


class RunStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    EXECUTED = "executed"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_id: str
    path: str
    display_name: str
    sha256: str
    mime_type: str
    extraction_status: str = "indexed"

    def external_descriptor(self) -> dict[str, str]:
        """Return source metadata that cannot reveal its local absolute path."""
        return {
            "mime_type": self.mime_type,
            "sha256": self.sha256,
            "source_id": self.source_id,
        }


@dataclass(frozen=True, slots=True)
class EvidenceLocator:
    source_id: str
    quote: str
    page: int | None = None
    section: str | None = None

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("evidence source_id must not be empty")
        if not self.quote.strip():
            raise ValueError("evidence quote must not be empty")
        if self.page is not None and self.page < 1:
            raise ValueError("evidence page must be positive")


@dataclass(frozen=True, slots=True)
class Claim:
    statement: str
    evidence: tuple[EvidenceLocator, ...] = ()
    uncertainty: float = 0.0
    conflict_status: str = "none"

    def __post_init__(self) -> None:
        if not self.statement.strip():
            raise ValueError("claim statement must not be empty")
        if not 0.0 <= self.uncertainty <= 1.0:
            raise ValueError("claim uncertainty must be between 0 and 1")
        if self.conflict_status not in {
            "confirmed_conflict",
            "none",
            "potential_conflict",
            "unverified",
        }:
            raise ValueError("claim conflict_status is invalid")


@dataclass(frozen=True, slots=True)
class Coverage:
    total_sources: int
    read_sources: int
    cited_sources: int
    unread_source_ids: tuple[str, ...] = ()
    uncited_read_source_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GateDecision:
    allowed: bool
    reasons: tuple[str, ...] = ()
    allowed_fields: tuple[str, ...] = ()
    recipient: str | None = None
    max_cost_usd: float = 0.0


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    format: str
    path: str
    sha256: str
    status: str = "written"


class WorkflowBlocked(RuntimeError):
    def __init__(
        self,
        errors: tuple[str, ...],
        *,
        actions: tuple[str, ...] = (),
        artifacts: tuple[ArtifactRecord, ...] = (),
        coverage: Coverage | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        super().__init__(", ".join(errors))
        self.errors = errors
        self.actions = actions
        self.artifacts = artifacts
        self.coverage = coverage
        self.metadata = metadata or {}


@dataclass(frozen=True, slots=True)
class UndoReceipt:
    action_id: str
    before: dict[str, Any]
    after: dict[str, Any]
    undo_plan: dict[str, Any]
    status: str = "available"


@dataclass(frozen=True, slots=True)
class JobEnvelope:
    workflow: str
    input_roots: tuple[str, ...]
    output_dir: str
    target_roots: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()
    privacy_mode: PrivacyMode = PrivacyMode.LOCAL_ONLY
    action_mode: ActionMode = ActionMode.DRY_RUN
    model_id: str | None = None
    model_budget_usd: float = 0.0
    sources: tuple[SourceRecord, ...] = ()
    response_schema: str = "nemofold.claims.v1"
    resume_run_id: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    handoff_context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            isinstance(self.model_budget_usd, bool)
            or not isinstance(self.model_budget_usd, (int, float))
            or not math.isfinite(self.model_budget_usd)
            or self.model_budget_usd < 0
        ):
            raise ValueError("model_budget_usd must be a finite non-negative number")

    @property
    def requires_external_model(self) -> bool:
        return self.model_id is not None

    def to_external_payload(self) -> dict[str, Any]:
        """Build the only payload shape accepted by an external model adapter."""
        payload: dict[str, Any] = {
            "contract_version": CONTRACT_VERSION,
            "workflow": self.workflow,
            "questions": list(self.questions),
            "sources": [source.external_descriptor() for source in self.sources],
            "response_schema": self.response_schema,
        }
        if self.model_id is not None:
            payload["model"] = {
                "id": self.model_id,
                "max_cost_usd": self.model_budget_usd,
            }
        return payload


@dataclass(frozen=True, slots=True)
class RunReport:
    run_id: str
    idempotency_key: str
    workflow: str
    status: RunStatus
    actions: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    gate_decision: GateDecision | None = None
    coverage: Coverage | None = None
    artifacts: tuple[ArtifactRecord, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ClaimValidation:
    verified: bool
    valid_locator_count: int
    invalid_locators: tuple[str, ...] = ()


def to_primitive(value: Any) -> Any:
    """Convert nested contracts to JSON-safe builtins without losing enum values."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {key: to_primitive(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_primitive(item) for item in value]
    return value
