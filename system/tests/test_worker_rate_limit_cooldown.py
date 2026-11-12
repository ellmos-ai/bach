"""Tests for 429 Cooldown / Retry-After execution policy and open-return binding (#2994, #2995)."""
from __future__ import annotations

import hashlib
import math
import pytest

from hub._services.worker_rate_limit_cooldown import (
    DEFAULT_429_COOLDOWN_SECONDS,
    RateLimitCooldownError,
    bind_post_cooldown_submission,
    evaluate_429_cooldown,
    parse_retry_after_seconds,
)


def test_evaluate_429_cooldown_parses_retry_after_seconds_and_keeps_task_pending():
    decision = evaluate_429_cooldown(429, {"Retry-After": "45"})
    assert decision.is_rate_limited is True
    assert decision.cooldown_seconds == 45.0
    assert decision.retry_after_source == "retry-after-seconds"
    assert decision.task_return_state == "pending"
    assert decision.require_new_session_scope is True


def test_evaluate_429_cooldown_falls_back_to_default_when_header_missing():
    decision = evaluate_429_cooldown(429, {})
    assert decision.is_rate_limited is True
    assert decision.cooldown_seconds == DEFAULT_429_COOLDOWN_SECONDS
    assert decision.retry_after_source == "default"
    assert decision.task_return_state == "pending"


def test_parse_retry_after_http_date():
    seconds, source = parse_retry_after_seconds(
        {"Retry-After": "Sun, 02 Nov 2026 05:01:30 GMT"},
        now_epoch=1793595660.0,  # 2026-11-02 05:01:00 UTC
    )
    assert source == "retry-after-date"
    assert seconds == 30.0


def test_non_429_does_not_trigger_cooldown():
    decision = evaluate_429_cooldown(200, {"Retry-After": "120"})
    assert decision.is_rate_limited is False
    assert decision.cooldown_seconds == 0.0
    assert decision.task_return_state == "unchanged"
    assert decision.require_new_session_scope is False


@pytest.mark.parametrize("value", ["NaN", "inf", "-inf", "Infinity"])
def test_nonfinite_header_uses_bounded_default(value):
    seconds, source = parse_retry_after_seconds({"Retry-After": value})
    assert seconds == DEFAULT_429_COOLDOWN_SECONDS
    assert math.isfinite(seconds)
    assert source == "default"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), None, "invalid"])
def test_invalid_default_cannot_escape_bounds(value):
    seconds, source = parse_retry_after_seconds(None, default_seconds=value)
    assert seconds == DEFAULT_429_COOLDOWN_SECONDS
    assert math.isfinite(seconds) and source == "default"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_clock_cannot_create_date_cooldown(value):
    seconds, source = parse_retry_after_seconds(
        {"Retry-After": "Sun, 02 Nov 2026 05:01:30 GMT"}, now_epoch=value)
    assert seconds == DEFAULT_429_COOLDOWN_SECONDS
    assert source == "default"


@pytest.mark.parametrize("previous,current", [("old", "old "), (" old", "old"), (" old ", "\told\n")])
def test_scope_freshness_compares_canonical_identities(previous, current):
    with pytest.raises(RateLimitCooldownError, match="fresh session_scope_id"):
        bind_post_cooldown_submission(task_id=1, claim_fence=2, result_text="new result",
            session_scope_id=current, cooldown_generation=1, previous_claim_fence=1,
            previous_session_scope_id=previous)


@pytest.mark.parametrize("previous", ["", " ", 1, False])
def test_invalid_previous_scope_is_rejected(previous):
    with pytest.raises(RateLimitCooldownError, match="previous_session_scope_id"):
        bind_post_cooldown_submission(task_id=1, claim_fence=2, result_text="new result",
            session_scope_id="new", cooldown_generation=1, previous_session_scope_id=previous)


def test_bind_post_cooldown_rejects_unchanged_result_and_stale_fence_or_scope():
    prior_text = "Result297 payload"
    prior_sha = hashlib.sha256(prior_text.encode("utf-8")).hexdigest()

    with pytest.raises(RateLimitCooldownError, match="unchanged result payload"):
        bind_post_cooldown_submission(
            task_id=2431,
            claim_fence=75,
            result_text=prior_text,
            session_scope_id="sess-new",
            cooldown_generation=1,
            previous_result_sha256=prior_sha,
            previous_claim_fence=74,
            previous_session_scope_id="sess-old",
        )

    with pytest.raises(RateLimitCooldownError, match="strictly newer claim_fence"):
        bind_post_cooldown_submission(
            task_id=2431,
            claim_fence=74,
            result_text="Updated payload after cooldown",
            session_scope_id="sess-new",
            cooldown_generation=1,
            previous_result_sha256=prior_sha,
            previous_claim_fence=74,
            previous_session_scope_id="sess-old",
        )

    with pytest.raises(RateLimitCooldownError, match="fresh session_scope_id"):
        bind_post_cooldown_submission(
            task_id=2431,
            claim_fence=75,
            result_text="Updated payload after cooldown",
            session_scope_id="sess-old",
            cooldown_generation=1,
            previous_result_sha256=prior_sha,
            previous_claim_fence=74,
            previous_session_scope_id="sess-old",
        )

    bound = bind_post_cooldown_submission(
        task_id=2431,
        claim_fence=75,
        result_text="Updated payload after cooldown",
        session_scope_id="sess-new",
        cooldown_generation=1,
        previous_result_sha256=prior_sha,
        previous_claim_fence=74,
        previous_session_scope_id="sess-old",
    )
    assert bound.task_id == 2431
    assert bound.claim_fence == 75
    assert bound.session_scope_id == "sess-new"
    assert bound.result_sha256 != prior_sha
