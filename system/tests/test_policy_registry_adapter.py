"""No fallback, no policy content transfer, observable pointer verification."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from hub._services import policy_registry_adapter as adapter
from gui.api import governance_registry as api


def entry(**changes):
    return {"id": "rule-1", "kind": "rule", "title": "Prüfregel", "scope": "project:test", "version": "1",
        "privacy": "private", "status": "active", "adoption": "adopted", "priority": 1, "precedence": 1,
        "source": {"uri": "/private/location", "full_text": "NEVER_COPY"},
        "hash": {"value": "a" * 64}, "content": "NEVER_COPY", **changes}


def test_projection_contains_no_full_text_or_private_location():
    result = adapter.pointer(entry(), {"rule-1": {"state": "ok"}})
    assert result["source_verified"] and not result["enforcement_verified"]
    serialized = json.dumps(result)
    assert "NEVER_COPY" not in serialized and "/private/location" not in serialized
    for state in ("present", "remote-unchecked", "hash-mismatch", "missing", "unreadable"):
        assert not adapter.pointer(entry(), {"rule-1": {"state": state}})["source_verified"]


def test_disabled_provider_does_not_import_or_initialize(monkeypatch):
    monkeypatch.delenv("BACH_POLICY_REGISTRY_ENABLED", raising=False)
    monkeypatch.setattr(adapter.metadata, "distribution", lambda *_: pytest.fail("must not import"))
    with pytest.raises(adapter.PolicyProviderUnavailable, match="not_configured"):
        adapter._provider()


@pytest.mark.parametrize("url,commit,version", [("https://other.invalid/policy-registry", adapter.PIN, adapter.VERSION),
    (adapter.REPOSITORY, "b"*40, adapter.VERSION), (adapter.REPOSITORY, adapter.PIN, "999"),
    ("https://user:password@github.com/ellmos-ai/policy-registry", adapter.PIN, adapter.VERSION)])
def test_foreign_or_unpinned_package_is_rejected_before_import(monkeypatch, url, commit, version):
    monkeypatch.setenv("BACH_POLICY_REGISTRY_ENABLED", "1")
    record = {"url": url, "vcs_info": {"vcs": "git", "commit_id": commit}}
    dist = SimpleNamespace(version=version, read_text=lambda _: json.dumps(record))
    monkeypatch.setattr(adapter.metadata, "distribution", lambda _: dist)
    with pytest.raises(adapter.PolicyProviderUnavailable, match="provenance_mismatch"):
        adapter._provider()


class Registry:
    def __init__(self, path): self.path = path
    def search(self, **options): return [entry()]
    def verify(self): return {"checks": [{"id": "rule-1", "state": "present"}]}
    def resolve(self, **options): return {"status": "resolved", "reason": "canonical", "selected": entry(),
        "candidates": [entry()], "interaction_mode": "user-sovereign", "interaction_source": "configured",
        "governance_binding": False, "external_effect_gates": "user-controlled"}


def test_missing_registry_is_unavailable_not_empty_authority(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "_provider", lambda: Registry(tmp_path / "missing"))
    with pytest.raises(adapter.PolicyProviderUnavailable, match="registry_missing"):
        adapter.observe()


def test_observed_sources_do_not_become_enforced_and_reads_do_not_write(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    path.write_text("{}")
    before = path.read_bytes()
    monkeypatch.setattr(adapter, "_provider", lambda: Registry(path))
    result = adapter.observe(scope="project:test", effective=True)
    assert result["read_only"] and result["provider"]["source_commit"] == adapter.PIN
    assert not result["source_verification_complete"] and not result["effective"]["governance_binding"]
    assert path.read_bytes() == before


def test_concurrent_registry_change_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    path.write_text("{}")
    reg = Registry(path)
    def search(**options):
        path.write_text("changed")
        return []
    reg.search = search
    monkeypatch.setattr(adapter, "_provider", lambda: reg)
    with pytest.raises(adapter.PolicySnapshotChanged): adapter.observe()


def test_unavailable_api_uses_503_without_bundled_list(monkeypatch):
    def unavailable(**options): raise adapter.PolicyProviderUnavailable("policy_registry_missing")
    monkeypatch.setattr(api, "observe", unavailable)
    with pytest.raises(HTTPException) as denied: asyncio.run(api.read_registry())
    assert denied.value.status_code == 503 and denied.value.detail == "policy_registry_missing"


class PartlyUnreadableRegistry(Registry):
    def search(self, **options):
        return [entry(), entry(id="rule-2")]

    def verify(self):
        return {"checks": [
            {"id": "rule-1", "state": "unreadable"},
            {"id": "rule-2", "state": "ok", "actual": "a" * 64},
        ]}


@pytest.mark.parametrize("effective", [False, True])
def test_unreadable_pointer_keeps_other_entries_available(tmp_path, monkeypatch, effective):
    path = tmp_path / "registry.json"
    path.write_text("{}", encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(adapter, "_provider", lambda: PartlyUnreadableRegistry(path))

    result = asyncio.run(api.read_registry(scope="project:test", effective=effective))

    assert result["availability"] == "available" and result["count"] == 2
    pointers = {item["id"]: item for item in result["entries"]}
    assert pointers["rule-1"]["source_state"] == "unreadable"
    assert pointers["rule-1"]["source_verified"] is False
    assert pointers["rule-2"]["source_state"] == "ok"
    assert pointers["rule-2"]["source_verified"] is True
    assert result["source_verification_complete"] is False
    assert result["enforcement_verified"] is False
    assert all(item["enforcement_verified"] is False for item in pointers.values())
    if effective:
        assert result["effective"]["selected"]["source_state"] == "unreadable"
        assert result["effective"]["selected"]["source_verified"] is False
        assert result["effective"]["selected"]["enforcement_verified"] is False
    serialized = json.dumps(result)
    assert "NEVER_COPY" not in serialized and "/private/location" not in serialized
    assert path.read_bytes() == before
