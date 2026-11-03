# SPDX-License-Identifier: MIT
"""Rate Limit Policy & 429 Cooldown Provider (fail-soft standalone service)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Mapping

__version__ = "1.0.0"
log = logging.getLogger(__name__)

DEFAULT_429_COOLDOWN_SECONDS = 60.0
MIN_429_COOLDOWN_SECONDS = 1.0
MAX_429_COOLDOWN_SECONDS = 3600.0


@dataclass(frozen=True, slots=True)
class RateLimitPolicyDecision:
    status_code: int
    is_rate_limited: bool
    cooldown_seconds: float
    retry_after_source: str
    task_return_state: str
    require_new_session_scope: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_retry_after_seconds(
    headers: Mapping[str, str] | None,
    *,
    now_epoch: float | None = None,
    default_seconds: float = DEFAULT_429_COOLDOWN_SECONDS,
) -> tuple[float, str]:
    """Parse Retry-After or x-ratelimit-reset headers into bounded cooldown seconds."""
    if not headers:
        return default_seconds, "default"

    norm_headers = {str(k).lower(): str(v) for k, v in headers.items()}
    raw_val = norm_headers.get("retry-after")
    if raw_val is not None:
        raw_val = raw_val.strip()
        try:
            sec = float(raw_val)
            bounded = max(MIN_429_COOLDOWN_SECONDS, min(MAX_429_COOLDOWN_SECONDS, sec))
            return bounded, "retry-after-seconds"
        except ValueError:
            try:
                dt = parsedate_to_datetime(raw_val)
                ref_time = now_epoch if now_epoch is not None else datetime.now(timezone.utc).timestamp()
                sec = max(0.0, dt.timestamp() - ref_time)
                bounded = max(MIN_429_COOLDOWN_SECONDS, min(MAX_429_COOLDOWN_SECONDS, sec))
                return bounded, "retry-after-date"
            except Exception:
                pass

    raw_reset = norm_headers.get("x-ratelimit-reset")
    if raw_reset is not None:
        raw_reset = raw_reset.strip()
        try:
            reset_epoch = float(raw_reset)
            ref_time = now_epoch if now_epoch is not None else datetime.now(timezone.utc).timestamp()
            sec = max(0.0, reset_epoch - ref_time) if reset_epoch > 1_000_000_000 else reset_epoch
            bounded = max(MIN_429_COOLDOWN_SECONDS, min(MAX_429_COOLDOWN_SECONDS, sec))
            return bounded, "x-ratelimit-reset"
        except ValueError:
            pass

    return default_seconds, "default"


def evaluate_rate_limit(
    headers: Mapping[str, str] | None = None,
    status_code: int = 200,
    default_cooldown: float = DEFAULT_429_COOLDOWN_SECONDS,
) -> dict[str, Any]:
    """Evaluate HTTP status and headers to produce a rate-limit cooldown decision."""
    is_429 = (status_code == 429)
    if is_429:
        cooldown_sec, source = parse_retry_after_seconds(headers, default_seconds=default_cooldown)
        decision = RateLimitPolicyDecision(
            status_code=status_code,
            is_rate_limited=True,
            cooldown_seconds=cooldown_sec,
            retry_after_source=source,
            task_return_state="pending_retry",
            require_new_session_scope=True,
        )
    else:
        decision = RateLimitPolicyDecision(
            status_code=status_code,
            is_rate_limited=False,
            cooldown_seconds=0.0,
            retry_after_source="none",
            task_return_state="completed",
            require_new_session_scope=False,
        )
    return decision.to_dict()


def calculate_backoff(attempt: int, base_seconds: float = 1.0, max_seconds: float = 60.0) -> float:
    """Deterministic exponential backoff with ceiling."""
    factor = 2 ** max(0, attempt - 1)
    return min(max_seconds, base_seconds * factor)


def get_rate_limit_status() -> dict[str, Any]:
    """Return status of rate-limit policy provider."""
    return {
        "status": "ok",
        "provider": "rate_limit_policy",
        "version": __version__,
        "min_cooldown": MIN_429_COOLDOWN_SECONDS,
        "max_cooldown": MAX_429_COOLDOWN_SECONDS,
        "default_cooldown": DEFAULT_429_COOLDOWN_SECONDS,
    }
