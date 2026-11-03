# SPDX-License-Identifier: MIT
"""Token Budget & Quota Evaluation Provider (fail-soft standalone service)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__version__ = "1.0.0"
log = logging.getLogger(__name__)

DEFAULT_DAILY_TOKEN_LIMIT = 1_000_000
DEFAULT_WEEKLY_TOKEN_LIMIT = 7_000_000


@dataclass(frozen=True, slots=True)
class TokenBudgetQuota:
    model: str
    requested_tokens: int
    daily_used: int
    daily_limit: int
    weekly_used: int
    weekly_limit: int
    allowed: bool
    remaining_daily: int
    burn_rate_status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_token_budget(
    model: str,
    requested_tokens: int,
    daily_used: int = 0,
    daily_limit: int = DEFAULT_DAILY_TOKEN_LIMIT,
    weekly_used: int = 0,
    weekly_limit: int = DEFAULT_WEEKLY_TOKEN_LIMIT,
) -> dict[str, Any]:
    """Fail-soft evaluation whether a model request fits into token quotas."""
    remaining_daily = max(0, daily_limit - daily_used)
    remaining_weekly = max(0, weekly_limit - weekly_used)
    allowed = (requested_tokens <= remaining_daily) and (requested_tokens <= remaining_weekly)

    ratio_daily = (daily_used + requested_tokens) / max(1, daily_limit)
    if ratio_daily > 1.0:
        burn_status = "EXCEEDED"
    elif ratio_daily > 0.8:
        burn_status = "WARNING_HIGH"
    elif ratio_daily > 0.5:
        burn_status = "ELEVATED"
    else:
        burn_status = "NORMAL"

    quota = TokenBudgetQuota(
        model=model,
        requested_tokens=requested_tokens,
        daily_used=daily_used,
        daily_limit=daily_limit,
        weekly_used=weekly_used,
        weekly_limit=weekly_limit,
        allowed=allowed,
        remaining_daily=remaining_daily,
        burn_rate_status=burn_status,
    )
    return quota.to_dict()


def get_token_budget_status(data_dir: Path | None = None) -> dict[str, Any]:
    """Return high-level token budget metrics for runtime and status queries."""
    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "status": "ok",
        "provider": "token_budget",
        "version": __version__,
        "timestamp": now_iso,
        "default_daily_limit": DEFAULT_DAILY_TOKEN_LIMIT,
        "default_weekly_limit": DEFAULT_WEEKLY_TOKEN_LIMIT,
        "quota_mode": "soft_gate",
    }
