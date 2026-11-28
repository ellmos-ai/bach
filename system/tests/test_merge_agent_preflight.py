"""Tests für Merge-Agent-Preflight-Service und -Route (Task #2039)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub.merge_agent_service import (
    DEFAULT_ALLOWED_BASE_BRANCHES,
    MERGE_AGENT_API_PREFIX,
    MERGE_AGENT_AUDIT_EVENT,
    MERGE_AGENT_PREFLIGHT_PATH,
    MERGE_AGENT_PROFILE_NAME,
    MERGE_AGENT_ROLE_KEY,
    PROTECTED_HEAD_BRANCHES,
    ROLE_MERGE_AGENT_BLUEPRINT,
    MergeAgentIdentity,
    MergeAgentService,
    MergeApproval,
    PreflightViolation,
    PullRequestContext,
    SecretProviderReference,
    role_merge_agent_seed,
)

try:
    from gui.api import merge_agent_preflight as merge_agent_preflight_mod
except ImportError:
    from system.gui.api import merge_agent_preflight as merge_agent_preflight_mod

NOW = datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc)
HEAD_SHA = "a" * 40
API_ROUTE = MERGE_AGENT_API_PREFIX + MERGE_AGENT_PREFLIGHT_PATH


def make_identity(principal: str = "merge-agent@bach.local") -> MergeAgentIdentity:
    return MergeAgentIdentity(principal, SecretProviderReference("system", "github/merge_agent"))


def make_pr(**overrides) -> PullRequestContext:
    defaults = dict(
        repository="ellmos-ai/bach",
        pr_number=2039,
        author_principal="lukas@bach.local",
        head_branch="feature/merge-agent",
        base_branch="main",
        head_sha=HEAD_SHA,
        is_draft=False,
        stacked=False,
        stacked_pr_numbers=[],
        ci_check_states={"unit": "success", "integration": "success"},
    )
    defaults.update(overrides)
    return PullRequestContext(**defaults)


def make_service(events=None):
    if events is None:
        events = []

    def auditor(event, payload):
        events.append((event, payload))
        return True

    return MergeAgentService(make_identity(), auditor=auditor), events


def valid_approvals() -> list:
    return [MergeApproval("devon@bach.local", HEAD_SHA, expires_at=NOW + timedelta(minutes=30))]


def codes(result) -> list:
    return [v.code for v in result.violations]


def collect_keys(value) -> set:
    keys = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(key)
            keys |= collect_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            keys |= collect_keys(item)
    return keys


def evaluate(service, pr=None, *, approvals=None, now=None, bypass=None):
    return service.evaluate_preflight(
        pr if pr is not None else make_pr(),
        approvals=valid_approvals() if approvals is None else approvals,
        now=NOW if now is None else now,
        bypass=bypass,
    )


# --- Blueprint / Seed (1-5) --------------------------------------------------


def test_seed_blueprint_shape_and_isolation():
    seed = role_merge_agent_seed()
    assert seed["role"] == MERGE_AGENT_PROFILE_NAME
    assert seed["profile_name"] == MERGE_AGENT_PROFILE_NAME
    assert seed["category"] == "core_agent"
    assert seed["identity"]["principal"] == "merge-agent@bach.local"
    assert DEFAULT_ALLOWED_BASE_BRANCHES == ("main",)
    assert PROTECTED_HEAD_BRANCHES == ("main", "master", "release", "production")
    assert ROLE_MERGE_AGENT_BLUEPRINT["role"] == "merge_agent"
    seed["identity"]["principal"] = "mutated"
    assert role_merge_agent_seed()["identity"]["principal"] == "merge-agent@bach.local"


def test_seed_api_route_matches_constants():
    seed = role_merge_agent_seed()
    assert seed["api"]["route"] == API_ROUTE
    assert MERGE_AGENT_API_PREFIX + MERGE_AGENT_PREFLIGHT_PATH == API_ROUTE
    assert seed["api"]["route"] == "/api/system/core-agents/merge-agent/preflight"


def test_seed_secret_provider_reference_is_reference_only():
    seed = role_merge_agent_seed()
    reference = seed["identity"]["secret_provider_reference"]
    assert reference["fields"] == ["provider_name", "secret_key"]
    assert reference["kind"] == "reference_only"
    assert "value" not in reference
    for key in reference:
        assert "token" not in key


def test_seed_forbidden_includes_self_approval_and_admin_bypass():
    seed = role_merge_agent_seed()
    assert {"self_approval", "admin_bypass"}.issubset(set(seed["forbidden"]))


def test_secret_provider_reference_describe_and_as_reference():
    reference = SecretProviderReference("system", "github/merge_agent")
    assert reference.describe() == {"provider_name": "system", "secret_key": "github/merge_agent"}
    assert len(reference.describe()) == 2
    assert reference.as_reference() == reference.describe()


# --- Service-Konstruktion / Identität (6-7) ----------------------------------


def test_service_rejects_credential_kwargs():
    with pytest.raises(TypeError):
        MergeAgentService(make_identity(), token="x")
    with pytest.raises(TypeError):
        MergeAgentService(make_identity(), credentials={"provider": "system"})


def test_identity_describe_is_secret_free():
    identity = make_identity()
    described = identity.describe()
    assert set(described) == {
        "principal",
        "separate_from_user_principals",
        "secret_provider_reference",
    }
    assert described["separate_from_user_principals"] is True
    assert described["secret_provider_reference"] == {
        "provider_name": "system",
        "secret_key": "github/merge_agent",
    }
    assert "token" not in json.dumps(described)


# --- Preflight-Regeln (8-23) --------------------------------------------------


def test_happy_path_preflight_ok():
    service, _ = make_service()
    result = service.evaluate_preflight(make_pr(), approvals=valid_approvals(), now=NOW)
    assert result.ok is True
    assert result.violations == []
    assert all(result.checks.values())
    assert result.role == MERGE_AGENT_ROLE_KEY
    assert result.audit_event == MERGE_AGENT_AUDIT_EVENT


def test_identity_mismatch_rejected():
    service = MergeAgentService(
        MergeAgentIdentity("lukas@bach.local", SecretProviderReference("system", "github/merge_agent"))
    )
    result = service.evaluate_preflight(make_pr(), approvals=valid_approvals(), now=NOW)
    assert result.ok is False
    assert result.checks["identity_not_pr_author"] is False
    assert "identity_not_pr_author" in codes(result)


def test_self_approval_ignored():
    service, _ = make_service()
    result = service.evaluate_preflight(
        make_pr(),
        approvals=[MergeApproval("lukas@bach.local", HEAD_SHA, expires_at=NOW + timedelta(minutes=30))],
        now=NOW,
    )
    assert result.ok is False
    assert "approval_ignored_from_author" in codes(result)


def test_draft_rejected():
    service, _ = make_service()
    result = service.evaluate_preflight(make_pr(is_draft=True), approvals=valid_approvals(), now=NOW)
    assert result.ok is False
    assert "no_draft" in codes(result)


def test_stacked_true_rejected():
    service, _ = make_service()
    result = service.evaluate_preflight(make_pr(stacked=True), approvals=valid_approvals(), now=NOW)
    assert result.ok is False
    assert "no_stack" in codes(result)


def test_stacked_pr_numbers_rejected():
    service, _ = make_service()
    result = service.evaluate_preflight(
        make_pr(stacked_pr_numbers=[2038]), approvals=valid_approvals(), now=NOW
    )
    assert result.ok is False
    assert "no_stack" in codes(result)


def test_protected_head_branch_rejected():
    service, _ = make_service()
    result = service.evaluate_preflight(make_pr(head_branch="main"), approvals=valid_approvals(), now=NOW)
    assert result.ok is False
    assert "unprotected_head_branch" in codes(result)


def test_disallowed_base_branch_rejected():
    service, _ = make_service()
    result = service.evaluate_preflight(
        make_pr(base_branch="feature-x"), approvals=valid_approvals(), now=NOW
    )
    assert result.ok is False
    assert "allowed_base_branch" in codes(result)


def test_ci_failure_rejected_and_case_insensitive_success():
    service, _ = make_service()
    result = service.evaluate_preflight(
        make_pr(ci_check_states={"unit": "success", "integration": "failure"}),
        approvals=valid_approvals(),
        now=NOW,
    )
    assert result.ok is False
    assert "ci_all_success" in codes(result)
    tolerant = service.evaluate_preflight(
        make_pr(ci_check_states={"unit": "SUCCESS", "integration": "Success"}),
        approvals=valid_approvals(),
        now=NOW,
    )
    assert tolerant.checks["ci_all_success"] is True


def test_missing_ci_rejected():
    service, _ = make_service()
    result = service.evaluate_preflight(make_pr(ci_check_states={}), approvals=valid_approvals(), now=NOW)
    assert result.ok is False
    assert "ci_all_success" in codes(result)


def test_missing_approval_rejected():
    service, _ = make_service()
    result = service.evaluate_preflight(make_pr(), approvals=(), now=NOW)
    assert result.ok is False
    assert "approval_missing_exact_head" in codes(result)


def test_valid_approval_covers_head():
    service, _ = make_service()
    result = service.evaluate_preflight(
        make_pr(),
        approvals=[MergeApproval("devon@bach.local", HEAD_SHA, expires_at=NOW + timedelta(hours=1))],
        now=NOW,
    )
    assert result.ok is True
    assert result.approved_by == ["devon@bach.local"]


def test_approval_stale_new_head():
    service, _ = make_service()
    result = service.evaluate_preflight(
        make_pr(),
        approvals=[
            MergeApproval("devon@bach.local", "b" * 40, expires_at=NOW + timedelta(hours=1))
        ],
        now=NOW,
    )
    assert result.ok is False
    assert "approval_stale_new_head" in codes(result)


def test_approval_expired():
    service, _ = make_service()
    result = service.evaluate_preflight(
        make_pr(),
        approvals=[MergeApproval("devon@bach.local", HEAD_SHA, expires_at=NOW - timedelta(minutes=1))],
        now=NOW,
    )
    assert result.ok is False
    assert "approval_expired" in codes(result)


def test_approval_revoked():
    service, _ = make_service()
    result = service.evaluate_preflight(
        make_pr(),
        approvals=[MergeApproval("devon@bach.local", HEAD_SHA, expires_at=NOW + timedelta(hours=1), revoked=True)],
        now=NOW,
    )
    assert result.ok is False
    assert "approval_revoked" in codes(result)


def test_bypass_rejected():
    service, _ = make_service()
    result = service.evaluate_preflight(
        make_pr(), approvals=valid_approvals(), now=NOW, bypass="admin"
    )
    assert result.ok is False
    assert result.checks["no_bypass"] is False
    assert "no_bypass" in codes(result)


# --- Audit + Payload-Hygiene (24-26) ------------------------------------------


def test_auditor_receives_single_event():
    events = []
    service, events = make_service(events)
    result = service.evaluate_preflight(make_pr(), approvals=valid_approvals(), now=NOW)
    assert result.ok is True
    assert len(events) == 1
    assert events[0][0] == MERGE_AGENT_AUDIT_EVENT
    assert events[0][1]["ok"] is True


def test_payload_contains_no_credential_keys():
    service, _ = make_service()
    payload = service.evaluate_preflight(make_pr(), approvals=valid_approvals(), now=NOW).to_dict()
    keys = collect_keys(payload)
    forbidden = {
        "credential",
        "credentials",
        "secret_value",
        "token",
        "access_token",
        "api_key",
        "password",
        "github_token",
    }
    assert not (keys & forbidden)
    assert "secret" not in keys  # exakter Vergleich: secret_key/secret_provider_reference bleiben erlaubt


def test_payload_json_round_trip():
    service, _ = make_service()
    payload = service.evaluate_preflight(make_pr(), approvals=valid_approvals(), now=NOW).to_dict()
    data = json.loads(json.dumps(payload))
    assert data["ok"] is True
    assert data["pr_number"] == 2039
    assert data["approved_by"] == ["devon@bach.local"]
    assert data["identity"]["secret_provider_reference"]["secret_key"] == "github/merge_agent"


# --- API-Route (27-29) ---------------------------------------------------------


@pytest.fixture()
def api_client(monkeypatch):
    app = FastAPI()
    app.include_router(merge_agent_preflight_mod.router)
    monkeypatch.setattr(merge_agent_preflight_mod, "authorize", lambda request: None)
    with TestClient(app) as client:
        yield client


def test_api_preflight_happy_path(api_client):
    response = api_client.post(
        API_ROUTE,
        json={
            "identity": {"principal": "merge-agent@bach.local"},
            "pr": {
                "repository": "ellmos-ai/bach",
                "pr_number": 2039,
                "author_principal": "lukas@bach.local",
                "head_branch": "feature/merge-agent",
                "base_branch": "main",
                "head_sha": HEAD_SHA,
                "is_draft": False,
                "ci_check_states": {"unit": "success", "integration": "success"},
            },
            "approvals": [
                {"approver": "devon@bach.local", "commit_sha": HEAD_SHA, "ttl_minutes": 30}
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["schema"] == merge_agent_preflight_mod.PREFLIGHT_SCHEMA
    assert body["approved_by"] == ["devon@bach.local"]
    assert body["role"] == MERGE_AGENT_ROLE_KEY


def test_api_rejects_credential_material(api_client):
    response = api_client.post(
        API_ROUTE,
        json={
            "identity": {"principal": "merge-agent@bach.local"},
            "pr": {
                "repository": "ellmos-ai/bach",
                "pr_number": 2039,
                "author_principal": "lukas@bach.local",
                "head_branch": "feature/merge-agent",
                "base_branch": "main",
                "head_sha": HEAD_SHA,
            },
            "token": "x",
        },
    )
    assert response.status_code == 400
    assert "abgelehnt" in response.json()["detail"]


def test_api_draft_returns_violations(api_client):
    response = api_client.post(
        API_ROUTE,
        json={
            "identity": {"principal": "merge-agent@bach.local"},
            "pr": {
                "repository": "ellmos-ai/bach",
                "pr_number": 2039,
                "author_principal": "lukas@bach.local",
                "head_branch": "feature/merge-agent",
                "base_branch": "main",
                "head_sha": HEAD_SHA,
                "is_draft": True,
                "ci_check_states": {"unit": "success", "integration": "success"},
            },
            "approvals": [
                {"approver": "devon@bach.local", "commit_sha": HEAD_SHA, "ttl_minutes": 30}
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert len(body["violations"]) >= 1
    assert "no_draft" in [v["code"] for v in body["violations"]]
