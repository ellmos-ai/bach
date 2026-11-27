"""Regression tests for Carbon-Review fixes on cloud call retry, handoff metadata, and 502/503/504."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.chat.chat_runtime import ChatRuntime, FailedAnswer
from hub._services.chat.local_resource_reserve import LocalReserveError
from hub._services.llm.backend_errors import (
    BackendRequestFailure,
    cloud_call_retry_eligible,
    normalize_backend_error,
)
from hub._services.llm.model_backend import OpenRouterBackend


class _StubOpenRouterBackend(OpenRouterBackend):
    manages_own_tools = False

    def __init__(self):
        self.calls = 0

    def get_default_model(self):
        return "openai/gpt-4o-mini"

    async def chat(self, *args, **kwargs):
        self.calls += 1
        return {"content": "should not be called"}


def _make_runtime_and_session(profile_box):
    backend = _StubOpenRouterBackend()
    runtime = ChatRuntime(backend=backend)
    session = runtime.get_session("worker-ttl-test")
    session.worker_task_binding = object()
    session.worker_slot_reader = lambda: profile_box[0]
    return runtime, session, backend


@pytest.mark.parametrize(
    "bad_expires",
    [
        (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(),
        "",
        "   ",
        "not-a-timestamp",
        12345,
        True,
        {"ts": "2099-01-01T00:00:00Z"},
    ],
)
def test_cloud_call_retry_entry_fails_closed_on_expired_or_invalid_ttl(bad_expires):
    profile = {
        "id": "worker-ttl-test",
        "type": "continuous",
        "status": "running",
        "enabled": True,
        "expires_at": bad_expires,
    }
    runtime, session, backend = _make_runtime_and_session([profile])

    with pytest.raises(RuntimeError, match="Worker-TTL abgelaufen oder ungültig"):
        asyncio.run(
            runtime._chat_with_cloud_call_retry(
                session,
                backend,
                "openai/gpt-4o-mini",
                [{"role": "user", "content": "hi"}],
            )
        )
    assert backend.calls == 0


def test_failed_answer_from_exception_preserves_handoff_wrapped_metadata():
    detail = normalize_backend_error(
        {
            "provider": "openrouter",
            "kind": "http_error",
            "error_type": "HTTPStatusError",
            "quota_exceeded": False,
            "status_code": 504,
        }
    )
    assert detail is not None
    inner = RuntimeError(detail["message"])
    inner.backend_error = detail
    inner.reason_code = "cloud_call_retry_exhausted"
    try:
        try:
            raise inner
        except RuntimeError as exc:
            raise RuntimeError(f"Kontext-Übergabe fehlgeschlagen: {exc}") from exc
    except RuntimeError as outer:
        ans = FailedAnswer.from_exception(outer)

    assert ans.backend_error is not None
    assert ans.backend_error["provider"] == "openrouter"
    assert ans.backend_error["status_code"] == 504
    assert ans.reason_code == "cloud_call_retry_exhausted"


def test_failed_answer_from_exception_preserves_wrapped_backend_failure():
    inner = BackendRequestFailure(
        {
            "provider": "openrouter",
            "kind": "http_error",
            "error_type": "HTTPStatusError",
            "quota_exceeded": False,
            "status_code": 503,
        }
    )
    try:
        try:
            raise inner
        except BackendRequestFailure as exc:
            raise RuntimeError("Kontext-Übergabe fehlgeschlagen") from exc
    except RuntimeError as outer:
        ans = FailedAnswer.from_exception(outer)

    assert ans.backend_error is not None
    assert ans.backend_error["status_code"] == 503


def test_failed_answer_from_exception_preserves_wrapped_local_reserve_and_httpx():
    reserve_exc = LocalReserveError("Lokale Ressourcenfreigabe: reserve_wait_expired")
    try:
        try:
            raise reserve_exc
        except LocalReserveError as exc:
            raise RuntimeError("Kontext-Übergabe fehlgeschlagen") from exc
    except RuntimeError as outer:
        ans = FailedAnswer.from_exception(outer)
    assert ans.reason_code == "local_reserve_reserve_wait_expired"

    timeout_exc = httpx.ReadTimeout("timed out")
    try:
        try:
            raise timeout_exc
        except httpx.ReadTimeout as exc:
            raise RuntimeError("Kontext-Übergabe fehlgeschlagen") from exc
    except RuntimeError as outer:
        ans2 = FailedAnswer.from_exception(outer)
    assert ans2.transient_failure == "httpx_read_timeout"


@pytest.mark.parametrize("status_code", [502, 503, 504])
def test_openrouter_gateway_codes_recognized_in_finish_assignment_logic(status_code):
    detail = normalize_backend_error(
        {
            "provider": "openrouter",
            "kind": "http_error",
            "error_type": "HTTPStatusError",
            "quota_exceeded": False,
            "status_code": status_code,
        }
    )
    assert detail is not None
    assert cloud_call_retry_eligible(detail) is True
    assert (
        detail.get("provider") == "openrouter"
        and detail.get("status_code") in {502, 503, 504}
    )
