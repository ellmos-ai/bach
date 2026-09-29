"""Distributed leases.

The whole point of this module is that it contains no "check, then write" logic.
Acquisition is a single statement whose outcome the database decides; Python only
reports what happened. Any version of this that first SELECTs the current holder and
then decides in the client would reintroduce exactly the race we are removing.
"""

from __future__ import annotations

from datetime import datetime

import psycopg

from .db import execute, fetch_one, retry_on_serialization_failure
from .models import Claim, ClaimDenied

#: Acquire or take over a lease in one atomic statement.
#:
#: Row exists and is still valid  -> ON CONFLICT fires, the WHERE fails, zero rows back.
#: Row exists and has expired     -> ON CONFLICT fires, the WHERE holds, we take it over.
#: No row                         -> plain INSERT, we get it.
#:
#: There is no window between the decision and the write, because they are the same
#: statement. `claim_id` is regenerated on takeover so the previous holder's id becomes
#: worthless the moment its lease lapses — a stale heartbeat cannot resurrect it.
ACQUIRE_SQL = """
INSERT INTO claims (swarm_id, resource, agent_id, intent,
                    framework_snapshot, host_snapshot, expires_at)
VALUES (%s, %s, %s, %s, %s, %s, now() + %s::INTERVAL)
ON CONFLICT (swarm_id, resource) DO UPDATE
   SET agent_id     = excluded.agent_id,
       claim_id     = gen_random_uuid(),
       intent       = excluded.intent,
       framework_snapshot = excluded.framework_snapshot,
       host_snapshot = excluded.host_snapshot,
       acquired_at  = now(),
       heartbeat_at = now(),
       expires_at   = excluded.expires_at
 WHERE claims.expires_at < now()
RETURNING claim_id, agent_id, intent, expires_at, framework_snapshot, host_snapshot
"""

HOLDER_SQL = """
SELECT claim_id, agent_id, intent, expires_at, framework_snapshot, host_snapshot
  FROM claims
 WHERE swarm_id = %s AND resource = %s AND expires_at > now()
"""

HEARTBEAT_SQL = """
UPDATE claims
   SET heartbeat_at = now(),
       expires_at   = now() + %s::INTERVAL
 WHERE swarm_id = %s AND claim_id = %s AND expires_at > now()
"""

RELEASE_SQL = "DELETE FROM claims WHERE swarm_id = %s AND claim_id = %s"


def _interval(seconds: int) -> str:
    return f"{int(seconds)} seconds"


def acquire(
    conn: psycopg.Connection,
    swarm_id: str,
    resource: str,
    agent_id: str,
    intent: str,
    ttl_seconds: int,
    framework: str = "unknown",
    host: str = "unknown",
) -> Claim | ClaimDenied:
    """Try to take the lease on `resource`.

    Returns a `Claim` on success and a `ClaimDenied` naming the current holder otherwise.
    """
    for _ in range(3):
        row = retry_on_serialization_failure(
            lambda: fetch_one(
                conn,
                ACQUIRE_SQL,
                (
                    swarm_id,
                    resource,
                    agent_id,
                    intent,
                    framework,
                    host,
                    _interval(ttl_seconds),
                ),
            )
        )
        if row is not None:
            claim_id, holder, held_intent, expires_at, held_framework, held_host = row
            return Claim(
                claim_id=str(claim_id),
                resource=resource,
                agent_id=str(holder),
                intent=held_intent,
                expires_at=expires_at,
                framework=held_framework,
                host=held_host,
            )

        holder_row = retry_on_serialization_failure(
            lambda: fetch_one(conn, HOLDER_SQL, (swarm_id, resource))
        )
        if holder_row is not None:
            _, holder, held_intent, expires_at, held_framework, held_host = holder_row
            return ClaimDenied(
                resource=resource,
                held_by=str(holder),
                intent=held_intent,
                expires_at=expires_at,
                framework=held_framework,
                host=held_host,
            )
        # The holder released (or its lease lapsed) between our two statements, so there
        # is nobody to name. Retrying is safe: the acquire is still atomic, and a loser
        # of the retry simply gets a denial naming whoever won it.

    return ClaimDenied(
        resource=resource,
        held_by="unknown",
        intent="lease changed hands repeatedly while resolving the holder",
        expires_at=datetime.now().astimezone(),
    )


def heartbeat(
    conn: psycopg.Connection, swarm_id: str, claim_id: str, ttl_seconds: int
) -> bool:
    """Extend a lease that is still valid. False if it has lapsed or is not ours.

    A lapsed lease is deliberately not renewable: it may already belong to somebody else,
    and letting a slow agent silently reclaim it would defeat the takeover rule.
    """
    rowcount = retry_on_serialization_failure(
        lambda: execute(conn, HEARTBEAT_SQL, (_interval(ttl_seconds), swarm_id, claim_id))
    )
    return rowcount > 0


def release(conn: psycopg.Connection, swarm_id: str, claim_id: str) -> bool:
    """Give up a lease. False if the id is unknown (already released or taken over)."""
    rowcount = retry_on_serialization_failure(
        lambda: execute(conn, RELEASE_SQL, (swarm_id, claim_id))
    )
    return rowcount > 0


def who_has(conn: psycopg.Connection, swarm_id: str, resource: str) -> Claim | None:
    """Current valid holder of `resource`, if any."""
    row = retry_on_serialization_failure(
        lambda: fetch_one(conn, HOLDER_SQL, (swarm_id, resource))
    )
    if row is None:
        return None
    claim_id, agent_id, intent, expires_at, framework, host = row
    return Claim(
        claim_id=str(claim_id),
        resource=resource,
        agent_id=str(agent_id),
        intent=intent,
        expires_at=expires_at,
        framework=framework,
        host=host,
    )
