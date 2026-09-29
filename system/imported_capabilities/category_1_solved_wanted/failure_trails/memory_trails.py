"""The Roshambo client: coordination, memory, decisions.

One instance owns one database connection and represents one agent's view of one swarm.
It is not thread safe by design — see `roshambo.db.connect`.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
import uuid
from collections.abc import Sequence
from typing import Any

import psycopg

from .config import RoshamboConfig
from .db import (
    connect,
    execute,
    fetch_all,
    fetch_one,
    retry_on_serialization_failure,
    to_vector_literal,
)
from .errors import EmbeddingError
from .leases import acquire, heartbeat, release, who_has
from .models import (
    CONFIDENCES,
    FACT_KINDS,
    OUTCOMES,
    PROVENANCES,
    Claim,
    ClaimDenied,
    Confidence,
    Decision,
    Fact,
    FactKind,
    Outcome,
    Provenance,
    RecallHit,
    SwarmStatus,
    Trail,
)

#: Cosine distance. Trails are compared by direction, not magnitude: a long evidence
#: text and a short query sentence should be able to match.
DISTANCE_OP = "<=>"

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class PlaceholderEmbedder:
    """Offline stand-in for a real embedding model. **Not a semantic model.**

    It hashes word tokens and character trigrams into a fixed-width vector, so two texts
    are close when they share vocabulary and word fragments — nothing more. It exists so
    the test suite and the CLI work without cloud credentials, and it is used whenever
    `roshambo.embeddings` is unavailable.

    Anything it produces must be described as lexical overlap, never as semantic
    similarity. The real embedder is Amazon Titan Text Embeddings V2 via
    `roshambo.embeddings.get_embedder`.
    """

    is_placeholder = True

    def __init__(self, dim: int = 1024) -> None:
        if dim <= 0:
            raise EmbeddingError(f"dim must be positive, got {dim}")
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for feature, weight in self._features(text).items():
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign * weight

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            # An empty or unusable text still needs a well-defined, non-zero vector:
            # cosine distance against an all-zero vector is undefined.
            vector[0] = 1.0
            return vector
        return [v / norm for v in vector]

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]

    @staticmethod
    def _features(text: str) -> dict[str, float]:
        tokens = _TOKEN_RE.findall(text.lower())
        counts: dict[str, int] = {}
        for token in tokens:
            counts[f"w:{token}"] = counts.get(f"w:{token}", 0) + 1
            padded = f" {token} "
            for i in range(len(padded) - 2):
                trigram = f"c:{padded[i : i + 3]}"
                counts[trigram] = counts.get(trigram, 0) + 1
        # Sublinear term frequency: a word repeated ten times should not swamp the rest.
        return {feature: 1.0 + math.log(count) for feature, count in counts.items()}


#: `embedding_provider` value that selects `PlaceholderEmbedder` directly.
#:
#: Everything else is delegated to `roshambo.embeddings.get_embedder`. This value exists
#: because the offline path has to keep some retrieval signal: an embedder that hashes
#: the whole text produces uncorrelated vectors, which is fine for exercising the write
#: path but makes `recall()` rank arbitrarily. See docs/HANDOFF.md.
PLACEHOLDER_PROVIDER = "placeholder"


def _resolve_embedder(cfg: RoshamboConfig, embedder: Any | None) -> Any:
    if embedder is not None:
        return embedder
    if cfg.embedding_provider == PLACEHOLDER_PROVIDER:
        return PlaceholderEmbedder(dim=cfg.embedding_dim)
    try:
        from .embeddings import get_embedder  # type: ignore[attr-defined]
    except ImportError:
        return PlaceholderEmbedder(dim=cfg.embedding_dim)
    return get_embedder(cfg)


class Roshambo:
    """Client for one swarm.

    ``claim`` / ``release`` are the coordination half, ``remember`` / ``recall`` the
    memory half. They live in one class because they live in one database: a lease and
    the trail explaining why it was abandoned are written against the same cluster, so
    they cannot drift apart.
    """

    def __init__(self, cfg: RoshamboConfig, embedder: Any | None = None) -> None:
        self.cfg = cfg
        self.embedder = _resolve_embedder(cfg, embedder)
        self._conn: psycopg.Connection | None = None

    # ------------------------------------------------------------------ lifecycle

    @property
    def conn(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed:
            self._conn = connect(self.cfg)
        return self._conn

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
        self._conn = None

    def __enter__(self) -> Roshambo:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # --------------------------------------------------------------- coordination

    def claim(
        self,
        resource: str,
        agent_id: str,
        intent: str,
        ttl_seconds: int | None = None,
    ) -> Claim | ClaimDenied:
        """Take an exclusive lease on `resource`, or learn who already has it."""
        ttl = ttl_seconds if ttl_seconds is not None else self.cfg.lease_ttl_seconds
        started = time.perf_counter()
        framework, host = self._agent_identity(agent_id)
        result = acquire(
            self.conn,
            self.cfg.swarm_id,
            resource,
            agent_id,
            intent,
            ttl,
            framework,
            host,
        )
        granted = isinstance(result, Claim)
        self._audit(
            verb="claim",
            agent_id=agent_id,
            resource=resource,
            allowed=granted,
            reason=None if granted else f"held by {result.held_by}",  # type: ignore[union-attr]
            started=started,
            framework=framework,
            host=host,
        )
        return result

    def heartbeat(self, claim_id: str) -> bool:
        """Keep a lease alive. False once it has lapsed — then it is not ours any more."""
        started = time.perf_counter()
        identity = self._claim_identity(claim_id)
        alive = heartbeat(self.conn, self.cfg.swarm_id, claim_id, self.cfg.lease_ttl_seconds)
        self._audit(
            verb="heartbeat",
            agent_id=identity[0] if identity else None,
            resource=None,
            allowed=alive,
            reason=None if alive else "unknown or expired claim_id",
            started=started,
            framework=identity[1] if identity else None,
            host=identity[2] if identity else None,
        )
        return alive

    def release(self, claim_id: str) -> bool:
        """Hand a lease back before it expires."""
        started = time.perf_counter()
        identity = self._claim_identity(claim_id)
        ok = release(self.conn, self.cfg.swarm_id, claim_id)
        self._audit(
            verb="release",
            agent_id=identity[0] if identity else None,
            resource=None,
            allowed=ok,
            reason=None if ok else "unknown claim_id",
            started=started,
            framework=identity[1] if identity else None,
            host=identity[2] if identity else None,
        )
        return ok

    def who_has(self, resource: str) -> Claim | None:
        """Current holder of `resource`, or None if it is free."""
        return who_has(self.conn, self.cfg.swarm_id, resource)

    # --------------------------------------------------------------------- memory

    def remember(
        self,
        topic: str,
        approach: str,
        outcome: Outcome,
        evidence: str,
        agent_id: str | None = None,
        detail: dict | None = None,
        artifact_uri: str | None = None,
    ) -> Trail:
        """Record one attempt and how it ended.

        Failures are first-class here: they are the entries that stop the next agent from
        walking into the same wall, and they are indexed exactly like successes.
        """
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of {OUTCOMES}, got {outcome!r}")

        started = time.perf_counter()
        embedding = self._embed(self._trail_text(topic, approach, evidence))

        # One row per statement: CockroachDB documents that batch inserts degrade the
        # quality of a vector index, so there is no multi-row variant of this call.
        row = retry_on_serialization_failure(
            lambda: fetch_one(
                self.conn,
                """
                INSERT INTO trails (swarm_id, agent_id, topic, approach, outcome,
                                    evidence, detail, artifact_uri, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::VECTOR)
                RETURNING trail_id, created_at
                """,
                (
                    self.cfg.swarm_id,
                    agent_id,
                    topic,
                    approach,
                    outcome,
                    evidence,
                    psycopg.types.json.Json(detail or {}),
                    artifact_uri,
                    to_vector_literal(embedding),
                ),
            )
        )
        assert row is not None
        trail_id, created_at = row
        self._audit(
            verb="remember",
            agent_id=agent_id,
            resource=topic,
            allowed=True,
            reason=outcome,
            started=started,
        )
        return Trail(
            trail_id=str(trail_id),
            topic=topic,
            approach=approach,
            outcome=outcome,
            evidence=evidence,
            created_at=created_at,
            agent_id=agent_id,
            artifact_uri=artifact_uri,
            detail=dict(detail or {}),
        )

    def recall(
        self,
        query: str,
        limit: int = 5,
        outcomes: Sequence[Outcome] | None = None,
    ) -> list[RecallHit]:
        """Find prior attempts close to `query`, nearest first.

        The `swarm_id` filter is on the vector index prefix column, which is what lets
        CockroachDB use the index rather than scanning. An `outcomes` filter is not on a
        prefix column, so it is applied to an over-fetched candidate set instead of being
        pushed into the indexed lookup — otherwise a run of unrelated outcomes near the
        query could return fewer rows than asked for.
        """
        if limit <= 0:
            return []
        started = time.perf_counter()
        vector = to_vector_literal(self._embed(query))

        columns = (
            "trail_id, topic, approach, outcome, evidence, detail, artifact_uri, "
            "agent_id, created_at, strength"
        )
        if outcomes:
            for outcome in outcomes:
                if outcome not in OUTCOMES:
                    raise ValueError(f"outcome must be one of {OUTCOMES}, got {outcome!r}")
            inner_limit = max(limit * 8, 40)
            sql = f"""
                SELECT {columns}, distance FROM (
                    SELECT {columns},
                           embedding {DISTANCE_OP} %s::VECTOR AS distance
                      FROM trails
                     WHERE swarm_id = %s
                     ORDER BY embedding {DISTANCE_OP} %s::VECTOR
                     LIMIT %s
                ) AS candidates
                WHERE outcome = ANY(%s)
                ORDER BY distance
                LIMIT %s
            """
            params: tuple[Any, ...] = (
                vector,
                self.cfg.swarm_id,
                vector,
                inner_limit,
                list(outcomes),
                limit,
            )
        else:
            sql = f"""
                SELECT {columns},
                       embedding {DISTANCE_OP} %s::VECTOR AS distance
                  FROM trails
                 WHERE swarm_id = %s
                 ORDER BY embedding {DISTANCE_OP} %s::VECTOR
                 LIMIT %s
            """
            params = (vector, self.cfg.swarm_id, vector, limit)

        rows = retry_on_serialization_failure(lambda: fetch_all(self.conn, sql, params))
        hits = [
            RecallHit(
                trail=Trail(
                    trail_id=str(r[0]),
                    topic=r[1],
                    approach=r[2],
                    outcome=r[3],
                    evidence=r[4],
                    created_at=r[8],
                    agent_id=r[7],
                    artifact_uri=r[6],
                    detail=r[5] or {},
                ),
                distance=float(r[10]),
                strength=float(r[9]),
            )
            for r in rows
        ]
        self._audit(
            verb="recall",
            agent_id=None,
            resource=query[:200],
            allowed=True,
            reason=f"{len(hits)} hits",
            started=started,
        )
        return hits

    def reinforce(self, trail_id: str, amount: float = 1.0) -> float | None:
        """Strengthen a trail that was found useful again (stigmergy).

        Returns the new strength, or None if the trail is unknown.
        """
        row = retry_on_serialization_failure(
            lambda: fetch_one(
                self.conn,
                """
                UPDATE trails SET strength = strength + %s
                 WHERE swarm_id = %s AND trail_id = %s
                RETURNING strength
                """,
                (float(amount), self.cfg.swarm_id, trail_id),
            )
        )
        return None if row is None else float(row[0])

    def learn(
        self,
        statement: str,
        kind: FactKind = "lesson",
        confidence: Confidence = "medium",
        source_trail: str | None = None,
    ) -> Fact:
        """Promote something learned into curated knowledge."""
        if kind not in FACT_KINDS:
            raise ValueError(f"kind must be one of {FACT_KINDS}, got {kind!r}")
        if confidence not in CONFIDENCES:
            raise ValueError(f"confidence must be one of {CONFIDENCES}, got {confidence!r}")

        embedding = to_vector_literal(self._embed(statement))
        row = retry_on_serialization_failure(
            lambda: fetch_one(
                self.conn,
                """
                INSERT INTO facts (swarm_id, kind, statement, source_trail,
                                   confidence, embedding)
                VALUES (%s, %s, %s, %s, %s, %s::VECTOR)
                RETURNING fact_id
                """,
                (self.cfg.swarm_id, kind, statement, source_trail, confidence, embedding),
            )
        )
        assert row is not None
        return Fact(
            fact_id=str(row[0]),
            kind=kind,
            statement=statement,
            confidence=confidence,
            source_trail=source_trail,
        )

    # ------------------------------------------------------------------ decisions

    def decide(
        self,
        question: str,
        choice: str,
        rationale: str,
        confidence: Confidence,
        provenance: Provenance,
        agent_id: str | None = None,
    ) -> Decision:
        """Append to the decision ledger.

        `provenance` is mandatory and not defaulted: whether a human confirmed a choice
        is precisely the thing that must not be guessed later.
        """
        if confidence not in CONFIDENCES:
            raise ValueError(f"confidence must be one of {CONFIDENCES}, got {confidence!r}")
        if provenance not in PROVENANCES:
            raise ValueError(f"provenance must be one of {PROVENANCES}, got {provenance!r}")

        started = time.perf_counter()
        row = retry_on_serialization_failure(
            lambda: fetch_one(
                self.conn,
                """
                INSERT INTO decisions (swarm_id, agent_id, question, choice,
                                       rationale, confidence, provenance)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING decision_id
                """,
                (
                    self.cfg.swarm_id,
                    agent_id,
                    question,
                    choice,
                    rationale,
                    confidence,
                    provenance,
                ),
            )
        )
        assert row is not None
        self._audit(
            verb="decide",
            agent_id=agent_id,
            resource=question[:200],
            allowed=True,
            reason=provenance,
            started=started,
        )
        return Decision(
            decision_id=str(row[0]),
            question=question,
            choice=choice,
            provenance=provenance,
            rationale=rationale,
            confidence=confidence,
        )

    # --------------------------------------------------------------------- status

    def status(self) -> SwarmStatus:
        """Counters for this swarm."""
        row = fetch_one(
            self.conn,
            """
            SELECT (SELECT count(*) FROM agents   WHERE swarm_id = %s),
                   (SELECT count(*) FROM claims   WHERE swarm_id = %s AND expires_at > now()),
                   (SELECT count(*) FROM trails   WHERE swarm_id = %s),
                   (SELECT count(*) FROM trails   WHERE swarm_id = %s AND outcome = 'failure'),
                   (SELECT count(*) FROM facts    WHERE swarm_id = %s)
            """,
            (self.cfg.swarm_id,) * 5,
        )
        assert row is not None
        return SwarmStatus(
            agents=int(row[0]),
            active_claims=int(row[1]),
            trails=int(row[2]),
            failures=int(row[3]),
            facts=int(row[4]),
        )

    def register_agent(
        self,
        framework: str,
        host: str,
        capabilities: dict | None = None,
        agent_id: str | None = None,
    ) -> str:
        """Register a stable caller identity and return its collision-safe key.

        Re-registering the same key updates the *current* registry row. Prior audit
        events retain their immutable framework/host snapshots.
        """
        key = agent_id or str(uuid.uuid4())
        started = time.perf_counter()
        row = retry_on_serialization_failure(
            lambda: fetch_one(
                self.conn,
                """
                INSERT INTO agents (swarm_id, agent_key, framework, host, capabilities)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (swarm_id, agent_key) DO UPDATE
                   SET framework = excluded.framework,
                       host = excluded.host,
                       capabilities = excluded.capabilities,
                       last_heartbeat = now()
                RETURNING agent_key
                """,
                (
                    self.cfg.swarm_id,
                    key,
                    framework,
                    host,
                    psycopg.types.json.Json(capabilities or {}),
                ),
            )
        )
        assert row is not None
        registered = str(row[0])
        self._audit(
            verb="register_agent",
            agent_id=registered,
            resource=None,
            allowed=True,
            reason="registered",
            started=started,
            framework=framework,
            host=host,
        )
        return registered

    # -------------------------------------------------------------------- private

    @staticmethod
    def _trail_text(topic: str, approach: str, evidence: str) -> str:
        """What actually gets embedded.

        All three parts go in: the topic alone is too thin to retrieve on, and the
        evidence carries the error text a later agent is most likely to search for.
        """
        return f"{topic}\n{approach}\n{evidence}"

    def _embed(self, text: str) -> list[float]:
        vector = self.embedder.embed(text)
        if len(vector) != self.cfg.embedding_dim:
            raise EmbeddingError(
                f"embedder returned {len(vector)} dimensions, "
                f"schema expects {self.cfg.embedding_dim}"
            )
        return vector

    def _agent_identity(self, agent_id: str) -> tuple[str, str]:
        """Resolve a registry key, creating an honest legacy row when needed."""
        row = fetch_one(
            self.conn,
            """
            SELECT framework, host
              FROM agents
             WHERE swarm_id = %s AND agent_key = %s
            """,
            (self.cfg.swarm_id, agent_id),
        )
        if row is not None:
            return str(row[0]), str(row[1])

        row = retry_on_serialization_failure(
            lambda: fetch_one(
                self.conn,
                """
                INSERT INTO agents (swarm_id, agent_key, framework, host, capabilities)
                VALUES (%s, %s, 'unregistered', 'unknown', '{"auto_registered": true}'::JSONB)
                ON CONFLICT (swarm_id, agent_key) DO UPDATE
                   SET last_heartbeat = now()
                RETURNING framework, host
                """,
                (self.cfg.swarm_id, agent_id),
            )
        )
        assert row is not None
        return str(row[0]), str(row[1])

    def _claim_identity(self, claim_id: str) -> tuple[str, str, str] | None:
        row = fetch_one(
            self.conn,
            """
            SELECT agent_id, framework_snapshot, host_snapshot
              FROM claims
             WHERE swarm_id = %s AND claim_id = %s
            """,
            (self.cfg.swarm_id, claim_id),
        )
        if row is None:
            return None
        return str(row[0]), str(row[1]), str(row[2])

    def _audit(
        self,
        *,
        verb: str,
        agent_id: str | None,
        resource: str | None,
        allowed: bool,
        reason: str | None,
        started: float,
        framework: str | None = None,
        host: str | None = None,
    ) -> None:
        """Append to the black box. Best effort: never fails the operation it records."""
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            if agent_id is not None and (framework is None or host is None):
                framework, host = self._agent_identity(agent_id)
            execute(
                self.conn,
                """
                INSERT INTO audit_log (swarm_id, agent_id, framework_snapshot,
                                       host_snapshot, verb, resource,
                                       allowed, reason, latency_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    self.cfg.swarm_id,
                    agent_id,
                    framework,
                    host,
                    verb,
                    resource,
                    allowed,
                    reason,
                    latency_ms,
                ),
            )
        except psycopg.Error:
            pass
