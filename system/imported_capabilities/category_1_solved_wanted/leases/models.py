"""Value types returned by the Roshambo API.

All plain frozen dataclasses: they cross process and language boundaries (MCP tools,
Lambda payloads), so they stay trivially serialisable and carry no database handles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Outcome = Literal["success", "failure", "abandoned", "inconclusive"]
FactKind = Literal["fact", "lesson", "constraint"]
Confidence = Literal["high", "medium", "low"]
Provenance = Literal["agent-inferred", "human-confirmed", "human-corrected"]

OUTCOMES: tuple[str, ...] = ("success", "failure", "abandoned", "inconclusive")
FACT_KINDS: tuple[str, ...] = ("fact", "lesson", "constraint")
CONFIDENCES: tuple[str, ...] = ("high", "medium", "low")
PROVENANCES: tuple[str, ...] = ("agent-inferred", "human-confirmed", "human-corrected")


@dataclass(frozen=True)
class Claim:
    """An exclusive, time-limited hold on a resource."""

    claim_id: str
    resource: str
    agent_id: str
    intent: str
    expires_at: datetime
    framework: str = "unknown"
    host: str = "unknown"


@dataclass(frozen=True)
class ClaimDenied:
    """Somebody else holds a valid lease.

    This is a result, not an error: it names the holder and their intent so the caller
    can pick different work instead of duplicating or fighting over it.
    """

    resource: str
    held_by: str
    intent: str
    expires_at: datetime
    framework: str = "unknown"
    host: str = "unknown"


@dataclass(frozen=True)
class Trail:
    """One attempt and how it ended — the unit of Roshambo's negative memory."""

    trail_id: str
    topic: str
    approach: str
    outcome: Outcome
    evidence: str
    created_at: datetime
    agent_id: str | None = None
    artifact_uri: str | None = None
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RecallHit:
    """A trail found by vector search, with its distance and current stigmergic strength."""

    trail: Trail
    distance: float
    strength: float


@dataclass(frozen=True)
class Fact:
    """A curated statement distilled from one or more trails."""

    fact_id: str
    kind: FactKind
    statement: str
    confidence: Confidence
    source_trail: str | None = None


@dataclass(frozen=True)
class Decision:
    """A recorded choice with its provenance."""

    decision_id: str
    question: str
    choice: str
    provenance: Provenance
    rationale: str = ""
    confidence: Confidence = "medium"


@dataclass(frozen=True)
class SwarmStatus:
    """Counters for one swarm, as of the moment `status()` was called."""

    agents: int
    active_claims: int
    trails: int
    failures: int
    facts: int
