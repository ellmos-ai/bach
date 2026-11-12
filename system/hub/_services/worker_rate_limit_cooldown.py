"""429 Cooldown / Retry-After execution policy and open-return result/scope binding (#2994, #2995).

Binds HTTP 429 rate-limit responses to deterministic cooldown intervals, open task
return (task remains pending/open on 429), fenced result revision checks (preventing
stale result resubmission), and fresh session scope allocation after cooldown.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import math
from typing import Mapping

DEFAULT_429_COOLDOWN_SECONDS = 60.0
MIN_429_COOLDOWN_SECONDS = 1.0
MAX_429_COOLDOWN_SECONDS = 3600.0


class RateLimitCooldownError(ValueError):
    """Raised when a 429 cooldown or result-revision binding is invalid or stale."""


@dataclass(frozen=True, slots=True)
class RateLimitCooldownDecision:
    status_code: int
    is_rate_limited: bool
    cooldown_seconds: float
    retry_after_source: str
    task_return_state: str
    require_new_session_scope: bool


@dataclass(frozen=True, slots=True)
class CooldownBoundSubmission:
    task_id: int
    claim_fence: int
    result_sha256: str
    session_scope_id: str
    cooldown_generation: int


def parse_retry_after_seconds(
    headers: Mapping[str, str] | None,
    *,
    now_epoch: float | None = None,
    default_seconds: float = DEFAULT_429_COOLDOWN_SECONDS,
) -> tuple[float, str]:
    """Parse Retry-After or x-ratelimit-reset headers into bounded cooldown seconds."""
    if not headers:
        return _clamp(default_seconds), "default"
    lowered = {str(k).strip().lower(): str(v).strip() for k, v in headers.items() if k and v is not None}
    raw = lowered.get("retry-after") or lowered.get("x-ratelimit-reset-after")
    if raw:
        try:
            seconds = float(raw)
            if math.isfinite(seconds):
                return _clamp(seconds), "retry-after-seconds"
        except ValueError:
            pass
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ref = float(now_epoch) if now_epoch is not None else datetime.now(timezone.utc).timestamp()
            if not math.isfinite(ref):
                raise ValueError("nonfinite clock reference")
            return _clamp(max(MIN_429_COOLDOWN_SECONDS, dt.timestamp() - ref)), "retry-after-date"
        except (TypeError, ValueError, OverflowError):
            pass
    return _clamp(default_seconds), "default"


def _clamp(value: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        value = DEFAULT_429_COOLDOWN_SECONDS
    if not math.isfinite(value):
        value = DEFAULT_429_COOLDOWN_SECONDS
    if value < MIN_429_COOLDOWN_SECONDS:
        return MIN_429_COOLDOWN_SECONDS
    if value > MAX_429_COOLDOWN_SECONDS:
        return MAX_429_COOLDOWN_SECONDS
    return float(value)


def evaluate_429_cooldown(
    status_code: int,
    headers: Mapping[str, str] | None = None,
    *,
    now_epoch: float | None = None,
) -> RateLimitCooldownDecision:
    """Return the execution decision for HTTP 429 vs non-429 responses (#2994, #2995)."""
    if status_code != 429:
        return RateLimitCooldownDecision(
            status_code=status_code,
            is_rate_limited=False,
            cooldown_seconds=0.0,
            retry_after_source="none",
            task_return_state="unchanged",
            require_new_session_scope=False,
        )
    seconds, source = parse_retry_after_seconds(headers, now_epoch=now_epoch)
    return RateLimitCooldownDecision(
        status_code=429,
        is_rate_limited=True,
        cooldown_seconds=seconds,
        retry_after_source=source,
        task_return_state="pending",
        require_new_session_scope=True,
    )


def bind_post_cooldown_submission(
    *,
    task_id: int,
    claim_fence: int,
    result_text: str,
    session_scope_id: str,
    cooldown_generation: int,
    previous_result_sha256: str | None = None,
    previous_claim_fence: int | None = None,
    previous_session_scope_id: str | None = None,
) -> CooldownBoundSubmission:
    """Bind a result revision and session scope to a post-429 cooldown cycle (#2995).

    Rejects unchanged resubmission of a prior result (e.g. Result297) or reuse of a
    pre-cooldown session scope or stale claim fence.
    """
    if type(task_id) is not int or task_id <= 0:
        raise RateLimitCooldownError("task_id must be a positive integer")
    if type(claim_fence) is not int or claim_fence <= 0:
        raise RateLimitCooldownError("claim_fence must be a positive integer")
    if type(cooldown_generation) is not int or cooldown_generation < 0:
        raise RateLimitCooldownError("cooldown_generation must be a non-negative integer")
    if not isinstance(result_text, str) or not result_text.strip():
        raise RateLimitCooldownError("result_text must be a non-empty string")
    if not isinstance(session_scope_id, str) or not session_scope_id.strip():
        raise RateLimitCooldownError("session_scope_id must be a non-empty string")
    session_scope_id = session_scope_id.strip()
    if previous_session_scope_id is not None:
        if not isinstance(previous_session_scope_id, str) or not previous_session_scope_id.strip():
            raise RateLimitCooldownError("previous_session_scope_id must be a non-empty string")
        previous_session_scope_id = previous_session_scope_id.strip()

    digest = hashlib.sha256(result_text.encode("utf-8")).hexdigest()
    if previous_result_sha256 is not None and digest == previous_result_sha256:
        raise RateLimitCooldownError(
            "unchanged result payload cannot be resubmitted after a 429 cooldown cycle"
        )
    if previous_claim_fence is not None and claim_fence <= previous_claim_fence:
        raise RateLimitCooldownError(
            "post-cooldown submission requires a strictly newer claim_fence"
        )
    if (
        cooldown_generation > 0
        and previous_session_scope_id is not None
        and session_scope_id == previous_session_scope_id
    ):
        raise RateLimitCooldownError(
            "post-cooldown submission requires a fresh session_scope_id"
        )

    return CooldownBoundSubmission(
        task_id=task_id,
        claim_fence=claim_fence,
        result_sha256=digest,
        session_scope_id=session_scope_id,
        cooldown_generation=cooldown_generation,
    )
