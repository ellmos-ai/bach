"""bach.catalog.v1 projection (#2016): small fixture sources, no real host data."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from hub._services import catalog_projection as cp

FIXTURE = Path(__file__).parent / "fixtures" / "catalog_projection_v1.json"
NOW = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)


def _write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


def build_sources(root: Path) -> cp.CatalogConfig:
    ai, bot, sync = root / "ai", root / "bot", root / "sync"
    _write(ai / ".MODULES" / "modules.catalog.json", {
        "schema": "ellmos.modules-catalog.v1", "module_count": 2, "modules": [
            {"id": "alpha-core", "display_name": "Alpha Core", "category": "runtime", "status": "active",
             "visibility": "public", "version": "1.0.0", "commit_sha": "a" * 40,
             "provides": ["alpha.store"], "requires": ["beta.api"], "optional": ["gamma.hint"],
             "repo_aliases": ["alpha-old"], "description": "Synthetic module",
             "source_of_truth": {"repository": "https://github.com/example-org/alpha-core", "type": "git-repository"},
             "runtime_source": "C:\\private\\path\\alpha-core"},
            {"id": "beta-tool", "display_name": "beta-tool", "category": "tools", "status": "development",
             "visibility": "private", "provides": [], "requires": [],
             "source_of_truth": {"repository": "https://github.com/example-org/beta-tool"}}]})
    _write(ai / ".BUNDLES" / "bundles.catalog.v1.json", {
        "schema": "ellmos.bundles.catalog.v1", "bundles": [
            {"id": "bundle-one", "status": "registered", "pillar": "control", "visibility": "private",
             "content_hash": "c" * 64},
            {"id": "bundle-lost", "status": "registered", "pillar": "control", "content_hash": "d" * 64}]})
    _write(ai / ".BUNDLES" / "bundles" / "bundle-one" / "bundle.v1.json", {
        "schema": "ellmos.bundle.v1", "id": "bundle-one", "version": "1.0.0", "display_name": "Bundle One",
        "purpose": ["Synthetic bundle"], "components": [
            {"type": "module", "ref": {"ref": "module:alpha-core", "version": "v1"}, "requirement": "required"},
            {"type": "skill", "ref": "skill:assist:note", "requirement": "optional"},
            {"type": "module", "ref": {"ref": "module:beta-tool"}, "requirement": "bogus"}]})
    _write(root / "skills" / "components.json", {"components": [
        {"id": "skill:assist:note", "name": "note", "category": "assist", "version": "1.0.0", "status": "active",
         "description": "Synthetic skill", "languages": ["de", "en"], "path": "skills/assist/note/SKILL.md"},
        {"id": "tool:util:abs", "name": "abs", "category": "util", "path": "C:\\private\\abs\\SKILL.md"}]})
    _write(bot / "master_satellite_catalog.json", {
        "schema": "master-satellite-catalog-v1", "generated_at": "2026-10-10T08:00:00", "modules": [
            # dirty/branch/last_commit here are generator defaults and must NOT become git facts
            {"name": "sat-known", "org": "example-org", "category": "x", "dirty": False, "branch": "main",
             "last_commit": "2026-10-10T08:00:00", "provenance": "EIGENENTWICKLUNG", "upstream": "example-org/sat-known"},
            {"name": "sat-unknown", "org": "example-org", "category": "y", "dirty": False, "branch": "main",
             "last_commit": "2026-10-10T08:00:00"}]})
    # OneDrive conflict copy: different content, host-like suffix; must never be read
    _write(bot / "master_satellite_catalog-WORKSTATION-LG-2.json", {"modules": [
        {"name": "conflict-copy-sat", "org": "example-org"}]})
    _write(bot / "repo_registry.json", {
        "schema": "githubbot-repo-registry-v1", "generated_at": "2026-10-09T10:00:00+02:00", "generated_on_host": "REGISTRY-HOST",
        "repos": {"example-org/sat-known": {"hosts": {"TEST-HOST": {"clones": [
            {"path": "C:\\private\\sat-known", "branch": "feature/x", "dirty": True,
             "last_commit": "2026-10-01T00:00:00+00:00", "added_at": "2026-10-09T09:00:00+02:00"}]}}}}})
    _write(sync / "slot-a" / "repos.json", {
        "schema": "repos-manifest-v1", "host": "MANIFEST-HOST", "generated_at": "2026-10-10T07:00:00+00:00",
        "repos": [{"name": "alpha-core", "path": "C:\\private\\alpha-core",
                   "origin": "https://github.com/example-org/alpha-core.git", "branch": "main", "dirty": False,
                   "last_commit": "2026-09-01T00:00:00+00:00"}]})
    _write(sync / "slot-a" / "repos-WORKSTATION-LG.json", {"host": "SUFFIX-HOST", "repos": []})
    for file in root.rglob("*.json"):
        os.utime(file, (1760000000, 1760000000))  # file_mtime fallbacks must be reproducible
    return cp.CatalogConfig(ai_root=ai, skills_registry=root / "skills" / "components.json",
                            githubbot_config=bot, sync_root=sync)


@pytest.fixture()
def projection(tmp_path):
    config = build_sources(tmp_path)
    return cp.observe(config=config, host="TEST-HOST", now=NOW), tmp_path


def by_id(result, item_id):
    return next(i for i in result["items"] if i["id"] == item_id)


def test_counts_are_derived_from_items_only(projection):
    result, _ = projection
    assert result["schema"] == "bach.catalog.v1"
    assert result["count"] == len(result["items"]) == 2 + 2 + 2 + 2
    for kind, n in result["counts"].items():
        assert n == sum(1 for i in result["items"] if i["type"] == kind)
    assert result["counts"] == {"module": 2, "bundle": 2, "skill": 2, "satellite": 2}


def test_no_absolute_path_or_private_value_leaks(projection):
    result, tmp = projection
    text = json.dumps(result)
    assert str(tmp) not in text and "\\private" not in text and "C:\\\\" not in text
    absolute = by_id(result, "tool:util:abs")
    assert absolute["path_label"] is None
    assert by_id(result, "skill:assist:note")["path_label"] == "skills/assist/note/SKILL.md"
    assert all("path" not in s for s in result["sources"])


def test_architecture_is_declared_and_separate_from_measurement(projection):
    result, _ = projection
    module = by_id(result, "alpha-core")
    assert module["aliases"] == ["Alpha Core", "alpha-old"]
    assert module["pin"]["commit"] == "a" * 40
    assert {(r["target"], r["requirement"], r["basis"]) for r in module["relations"]} == {
        ("beta.api", "required", "declared"), ("gamma.hint", "optional", "declared")}
    assert module["measured"] == {"installed": None, "runtime_active": None, "connection_state": "unverified",
                                  "observed_at": None, "host": None, "evidence": None}
    bundle = by_id(result, "bundle-one")
    assert bundle["pin"]["content_hash"] == "c" * 64 and bundle["pin"]["source_version"]
    assert [(r["target"], r["target_type"], r["requirement"]) for r in bundle["relations"]] == [
        ("module:alpha-core", "module", "required"), ("skill:assist:note", "skill", "optional"),
        ("module:beta-tool", "module", None)]


def test_missing_bundle_manifest_is_reported_not_invented(projection):
    result, _ = projection
    assert by_id(result, "bundle-lost")["relations"] == []
    assert {"source": "bundles_catalog", "reason": "manifest_FileNotFoundError", "item": "bundle-lost"} in result["errors"]


def test_git_is_unknown_without_a_host_bound_record(projection):
    result, _ = projection
    unknown = by_id(result, "example-org/sat-unknown")
    assert unknown["git"]["state"] == "unknown"
    assert unknown["git"]["branch"] is None and unknown["git"]["last_commit"] is None and unknown["git_hosts"] == []


def test_git_comes_from_host_records_with_content_derived_host(projection):
    result, _ = projection
    known = by_id(result, "example-org/sat-known")
    assert known["git"] == {"state": "dirty", "branch": "feature/x", "last_commit": "2026-10-01T00:00:00+00:00",
                            "observed_at": "2026-10-09T09:00:00+02:00", "host": "TEST-HOST", "source": "repo_registry"}
    module = by_id(result, "alpha-core")
    assert module["git"]["state"] == "unknown"  # record exists for MANIFEST-HOST only, local host is TEST-HOST
    assert [(g["host"], g["state"]) for g in module["git_hosts"]] == [("MANIFEST-HOST", "clean")]
    hosts = {s["host"] for s in result["sources"] if s["host"]}
    assert hosts == {"REGISTRY-HOST", "MANIFEST-HOST"}


def test_conflict_copy_file_names_never_create_hosts_or_items(projection):
    result, _ = projection
    assert not any("conflict-copy-sat" in i["id"] for i in result["items"])
    text = json.dumps(result)
    assert "SUFFIX-HOST" not in text and "WORKSTATION-LG" not in text


def test_catalog_git_defaults_are_not_used_as_facts(projection):
    result, _ = projection
    assert by_id(result, "example-org/sat-unknown")["git"]["branch"] != "main"


def test_missing_source_is_missing_with_empty_items_and_no_mock(tmp_path):
    config = build_sources(tmp_path)
    (tmp_path / "bot" / "master_satellite_catalog.json").unlink()
    result = cp.observe(config=config, now=NOW)
    source = next(s for s in result["sources"] if s["id"] == "satellite_catalog")
    assert source["availability"] == "missing" and source["error"] == "file_missing"
    assert result["counts"]["satellite"] == 0 and result["count"] == 6
    empty = cp.observe(config=cp.CatalogConfig(), now=NOW)
    assert empty["items"] == [] and empty["count"] == 0
    assert all(s["availability"] == "missing" for s in empty["sources"])


def test_broken_source_is_an_error_not_a_crash(tmp_path):
    config = build_sources(tmp_path)
    (tmp_path / "skills" / "components.json").write_text("{not json", encoding="utf-8")
    result = cp.observe(config=config, now=NOW)
    source = next(s for s in result["sources"] if s["id"] == "skills_registry")
    assert source["availability"] == "error"
    assert {"source": "skills_registry", "reason": source["error"]} in result["errors"]
    assert result["counts"]["skill"] == 0 and result["counts"]["module"] == 2


def test_kind_filter_and_unsupported_kind(tmp_path):
    config = build_sources(tmp_path)
    only = cp.observe(kind="skill", config=config, now=NOW)
    assert set(only["counts"]) == {"skill"} and {i["type"] for i in only["items"]} == {"skill"}
    with pytest.raises(ValueError):
        cp.observe(kind="plugin", config=config)


def test_generated_at_is_declared_or_marked_as_file_mtime(projection):
    result, _ = projection
    sources = {s["id"]: s for s in result["sources"]}
    assert sources["satellite_catalog"]["generated_at"] == "2026-10-10T08:00:00"
    assert sources["satellite_catalog"]["generated_at_basis"] == "declared"
    assert sources["modules_catalog"]["generated_at_basis"] == "file_mtime"


def test_fixture_matches_checked_in_copy(projection):
    result, _ = projection
    target = os.environ.get("BACH_WRITE_CATALOG_FIXTURE")
    if target:
        Path(target).write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # source_version is the SHA-256 of the fixture files written above (content-stable).
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == json.loads(json.dumps(result))


def test_route_requires_device_token_and_serves_projection(tmp_path, monkeypatch):
    from gui import server
    build_sources(tmp_path)
    monkeypatch.setenv("BACH_CATALOG_AI_ROOT", str(tmp_path / "ai"))
    monkeypatch.setenv("BACH_CATALOG_SKILLS_REGISTRY", str(tmp_path / "skills" / "components.json"))
    monkeypatch.setenv("BACH_CATALOG_GITHUBBOT_CONFIG", str(tmp_path / "bot"))
    monkeypatch.setenv("BACH_CATALOG_SYNC_ROOT", str(tmp_path / "sync"))
    assert "/api/capabilities/catalog" not in server.DeviceAuthMiddleware.EXEMPT_API_PATHS
    with TestClient(server.app, base_url="http://testserver") as client:
        assert client.get("/api/capabilities/catalog").status_code == 401
        monkeypatch.setattr(server, "validate_token", lambda token: {"name": "test"} if token == "good" else None)
        assert client.get("/api/capabilities/catalog", headers={"Authorization": "Bearer bad"}).status_code in (401, 403)
        ok = client.get("/api/capabilities/catalog", headers={"Authorization": "Bearer good"})
        assert ok.status_code == 200 and ok.json()["schema"] == "bach.catalog.v1" and ok.json()["count"] == 8
        assert str(tmp_path) not in ok.text
        only = client.get("/api/capabilities/catalog?kind=bundle", headers={"Authorization": "Bearer good"}).json()
        assert only["counts"] == {"bundle": 2}
        assert client.get("/api/capabilities/catalog?kind=nope", headers={"Authorization": "Bearer good"}).status_code == 422
