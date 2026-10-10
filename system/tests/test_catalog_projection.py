"""bach.catalog.v1 projection (#2016): small fixture sources, no real host data."""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from hub._services import catalog_projection as cp

FIXTURE = Path(__file__).parent / "fixtures" / "catalog_projection_v1.json"
NOW = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
BS = chr(92)
WIN_PATH = "C:" + BS + "private" + BS + "alpha-core"


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
             "repo_aliases": ["alpha-old"],
             # embedded absolute paths in free text must be redacted, ordinary URLs and routes must not
             "description": "Synthetic module stored in " + WIN_PATH + " and /root/x or ~/notes/y, see /api/tasks and https://example.org/a/b",
             "source_of_truth": {"repository": "https://github.com/example-org/alpha-core", "type": "git-repository"},
             "runtime_source": WIN_PATH},
            {"id": "beta-tool", "display_name": "beta-tool", "category": "tools", "status": "development",
             "visibility": "private", "provides": [], "requires": [],
             "source_of_truth": {"repository": "https://github.com/example-org/beta-tool"}}]})
    _write(ai / ".BUNDLES" / "bundles.catalog.v1.json", {
        "schema": "ellmos.bundles.catalog.v1", "bundles": [
            {"id": "bundle-one", "status": "registered", "pillar": "control", "visibility": "private", "content_hash": "c" * 64},
            {"id": "bundle-lost", "status": "registered", "pillar": "control", "content_hash": "d" * 64},
            {"id": "../escape", "status": "registered", "pillar": "control", "content_hash": "e" * 64}]})
    _write(ai / ".BUNDLES" / "bundles" / "bundle-one" / "bundle.v1.json", {
        "schema": "ellmos.bundle.v1", "id": "bundle-one", "version": "1.0.0", "display_name": "Bundle One",
        "purpose": ["Synthetic bundle"], "components": [
            {"type": "module", "ref": {"ref": "module:alpha-core", "version": "v1"}, "requirement": "required"},
            {"type": "skill", "ref": "skill:assist:note", "requirement": "optional"},
            {"type": "module", "ref": {"ref": "module:beta-tool"}, "requirement": "bogus"}]})
    # a manifest OUTSIDE the bundles root that the traversal id would reach
    _write(ai / ".BUNDLES" / "escape" / "bundle.v1.json", {"version": "9.9.9", "display_name": "LEAKED"})
    _write(ai / ".SYSTEMS" / "stacks" / "sys-stack.v1.json", {
        "schema": "ellmos.stack.v2", "id": "homebase-stack", "version": "2.0.0", "purpose": "Synthetic deployment stack",
        "content_hash": "f" * 64, "bundle_refs": [{"ref": "bundle-one", "version": "1.0.0"}],
        "optional_bundle_refs": [{"ref": "bundle-lost"}]})
    _write(ai / ".SYSTEMS" / "stacks" / "broken.v1.json", "{not json")
    _write(ai / ".STACKS" / "mod-stack" / "stack.v2.json", {
        "schema": "ellmos.stack.v2", "id": "homebase-stack", "status": "active", "visibility": "public",
        "components": [{"id": "alpha-core"}], "bundle_refs": ["bundle-one"],
        "external_components": [{"id": "skills", "kind": "skill-library"}], "nested_stacks": ["other-stack"]})
    _write(root / "skills" / "components.json", {"components": [
        {"id": "skill:assist:note", "name": "note", "category": "assist", "version": "1.0.0", "status": "active",
         "description": "Synthetic skill", "languages": ["de", "en"], "path": "skills/assist/note/SKILL.md"},
        {"id": "tool:util:abs", "name": "abs", "category": "util", "path": WIN_PATH + BS + "SKILL.md"}]})
    _write(bot / "master_satellite_catalog.json", {
        "schema": "master-satellite-catalog-v1", "generated_at": "2026-10-10T08:00:00", "modules": [
            # dirty/branch/last_commit here are generator defaults and must NOT become git facts
            {"name": "sat-known", "org": "example-org", "category": "x", "dirty": False, "branch": "main",
             "last_commit": "2026-10-10T08:00:00", "provenance": "EIGENENTWICKLUNG", "upstream": "example-org/sat-known"},
            {"name": "sat-unknown", "org": "example-org", "category": "y", "dirty": False, "branch": "main",
             "last_commit": "2026-10-10T08:00:00"}]})
    # OneDrive conflict copy: different content, host-like suffix; must never be read
    _write(bot / "master_satellite_catalog-WORKSTATION-LG-2.json", {"modules": [{"name": "conflict-copy-sat", "org": "example-org"}]})
    _write(bot / "repo_registry.json", {
        "schema": "githubbot-repo-registry-v1", "generated_at": "2026-10-09T10:00:00+02:00", "generated_on_host": "REGISTRY-HOST",
        "repos": {"example-org/sat-known": {"hosts": {"TEST-HOST": {"clones": [
            {"path": WIN_PATH, "branch": "feature/x", "dirty": True,
             "last_commit": "2026-10-01T02:00:00+02:00", "added_at": "2026-10-09T09:00:00+02:00"}]}}}}})
    _write(sync / "slot-a" / "repos.json", {
        "schema": "repos-manifest-v1", "host": "MANIFEST-HOST", "generated_at": "2026-10-10T09:00:00+02:00",
        "repos": [{"name": "alpha-core", "path": WIN_PATH, "origin": "https://github.com/example-org/alpha-core.git",
                   "branch": "main", "dirty": False, "last_commit": "2026-09-01T00:00:00"}]})
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


def source(result, source_id):
    return next(s for s in result["sources"] if s["id"] == source_id)


# ---------------------------------------------------------------- counts, types, stacks

def test_counts_are_derived_from_items_only(projection):
    result, _ = projection
    assert result["schema"] == "bach.catalog.v1"
    assert result["count"] == len(result["items"])
    for kind, n in result["counts"].items():
        assert n == sum(1 for i in result["items"] if i["type"] == kind)
    assert result["counts"] == {"module": 2, "bundle": 3, "stack": 2, "skill": 2, "satellite": 2}
    assert {i["type"] for i in result["items"]} == set(result["counts"])


def test_stacks_have_namespaced_stable_ids_and_declared_relations(projection):
    result, _ = projection
    deployment, module_stack = by_id(result, "systems/homebase-stack"), by_id(result, "stacks/homebase-stack")
    assert deployment["aliases"] == module_stack["aliases"] == ["homebase-stack"]
    assert deployment["category"] == "deployment-projection" and module_stack["category"] == "module-stack"
    assert deployment["pin"]["content_hash"] == "f" * 64
    assert [(r["target"], r["target_type"], r["requirement"]) for r in deployment["relations"]] == [
        ("bundle-one", "bundle", "required"), ("bundle-lost", "bundle", "optional")]
    assert [(r["target"], r["target_type"]) for r in module_stack["relations"]] == [
        ("bundle-one", "bundle"), ("alpha-core", "module"), ("skills", "skill-library"), ("other-stack", "stack")]
    assert all(r["basis"] == "declared" for r in deployment["relations"] + module_stack["relations"])
    assert source(result, "stacks_systems")["availability"] == "available"
    assert {"source": "stacks_systems", "reason": "JSONDecodeError", "item": "broken.v1.json"} in result["errors"]


# ---------------------------------------------------------------- path redaction

def test_no_absolute_path_or_private_value_leaks_and_embedded_paths_are_redacted(projection):
    result, tmp = projection
    text = json.dumps(result).replace('"visibility": "private"', "")
    for needle in (str(tmp), "private", "/root/x", "~/notes", "C:" + BS):
        assert needle not in text, needle
    description = by_id(result, "alpha-core")["description"]
    assert description.count("<pfad>") == 3
    assert "/api/tasks" in description and "https://example.org/a/b" in description
    assert result["redactions"] >= 3
    assert by_id(result, "tool:util:abs")["path_label"] is None
    assert by_id(result, "skill:assist:note")["path_label"] == "skills/assist/note/SKILL.md"


VECTORS = json.loads((Path(__file__).parent / "fixtures" / "catalog_redaction_vectors.json").read_text(encoding="utf-8"))["vectors"]


@pytest.mark.parametrize("vector", VECTORS, ids=[v["text"][:40] for v in VECTORS])
def test_redaction_follows_the_shared_vectors(vector):
    """Same list as the GUI test (byte-identical file): the client must flag exactly what the server redacts."""
    counter = [0]
    assert cp._redact(vector["text"], counter) == vector["redacted"]
    assert (counter[0] > 0) == (vector["redacted"] != vector["text"])
    assert cp._redact(vector["redacted"], [0]) == vector["redacted"]  # idempotent


def test_redaction_reaches_every_string_field_including_errors_item(tmp_path):
    config = build_sources(tmp_path)
    _write(tmp_path / "ai" / ".STACKS" / "p-stack" / "stack.v2.json", {"id": "p-stack", "purpose": "in /srv/data/x here"})
    result = cp.observe(config=config, now=NOW)
    assert "/srv/data/x" not in json.dumps(result)
    assert by_id(result, "stacks/p-stack")["description"] == "in <pfad> here"
    leaked = cp._redact({"errors": [{"item": "/var/lib/secret/file"}]}, [0])
    assert leaked["errors"][0]["item"] == "<pfad>"


# ---------------------------------------------------------------- path safety

@pytest.mark.parametrize("segment", ["..", ".", "../x", "a/b", "/abs", "C:" + BS + "x", "a" + BS + "b", "", "x" * 201, "a b", "a\x00b"])
def test_unsafe_segments_are_rejected(tmp_path, segment):
    assert cp._safe_child(tmp_path, segment) is None


def test_traversal_id_never_reads_outside_the_bundle_root(projection):
    result, _ = projection
    escaped = by_id(result, "../escape")
    assert escaped["version"] is None and escaped["relations"] == []
    assert "LEAKED" not in json.dumps(result)
    assert {"source": "bundles_catalog", "reason": "unsafe_id", "item": "../escape"} in result["errors"]


def test_absolute_bundle_id_is_not_followed(tmp_path):
    config = build_sources(tmp_path)
    outside = tmp_path / "outside"
    _write(outside / "bundle.v1.json", {"version": "9", "display_name": "LEAKED"})
    _write(tmp_path / "ai" / ".BUNDLES" / "bundles.catalog.v1.json", {"bundles": [{"id": str(outside), "status": "x"}, {"id": "/etc/passwd"}]})
    result = cp.observe(kind="bundle", config=config, now=NOW)
    assert "LEAKED" not in json.dumps(result)
    assert [e["reason"] for e in result["errors"]] == ["unsafe_id", "unsafe_id"]


def _make_link(link: Path, target: Path) -> bool:
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if sys.platform == "win32":  # junctions need no privilege
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        return done.returncode == 0
    return False


def test_link_in_a_parent_component_is_refused(tmp_path):
    config = build_sources(tmp_path)
    outside = tmp_path / "outside-bundle"
    _write(outside / "bundle.v1.json", {"version": "9.9.9", "display_name": "LEAKED"})
    link = tmp_path / "ai" / ".BUNDLES" / "bundles" / "linked"
    if not _make_link(link, outside):
        pytest.skip("neither symlink nor junction could be created on this host (no privilege)")
    _write(tmp_path / "ai" / ".BUNDLES" / "bundles.catalog.v1.json", {"bundles": [{"id": "linked", "status": "x"}]})
    result = cp.observe(kind="bundle", config=config, now=NOW)
    assert "LEAKED" not in json.dumps(result)
    assert result["errors"] == [{"source": "bundles_catalog", "reason": "unsafe_id", "item": "linked"}]
    assert cp._safe_child(tmp_path / "ai", ".BUNDLES", "bundles", "linked", "bundle.v1.json") is None


def test_linked_slot_directory_is_not_read(tmp_path):
    config = build_sources(tmp_path)
    outside = tmp_path / "outside-slot"
    _write(outside / "repos.json", {"host": "LEAKED-HOST", "repos": []})
    if not _make_link(tmp_path / "sync" / "slot-link", outside):
        pytest.skip("neither symlink nor junction could be created on this host (no privilege)")
    assert "LEAKED-HOST" not in json.dumps(cp.observe(config=config, now=NOW))


# ---------------------------------------------------------------- architecture, measurement, git

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
    assert known["git"]["state"] == "dirty" and known["git"]["branch"] == "feature/x" and known["git"]["host"] == "TEST-HOST"
    assert known["git"]["last_commit"] == "2026-10-01T00:00:00+00:00"  # +02:00 normalised to UTC
    module = by_id(result, "alpha-core")
    assert module["git"]["state"] == "unknown"  # record exists for MANIFEST-HOST only, local host is TEST-HOST
    assert [(g["host"], g["state"]) for g in module["git_hosts"]] == [("MANIFEST-HOST", "clean")]
    assert {s["host"] for s in result["sources"] if s["host"]} == {"REGISTRY-HOST", "MANIFEST-HOST"}


def test_conflict_copy_file_names_never_create_hosts_or_items(projection):
    result, _ = projection
    assert not any("conflict-copy-sat" in i["id"] for i in result["items"])
    text = json.dumps(result)
    assert "SUFFIX-HOST" not in text and "WORKSTATION-LG" not in text


def test_catalog_git_defaults_are_not_used_as_facts(projection):
    result, _ = projection
    assert by_id(result, "example-org/sat-unknown")["git"]["branch"] != "main"


def test_host_parameter_selects_the_git_record_and_never_filters_items(tmp_path):
    config = build_sources(tmp_path)
    a = cp.observe(config=config, host="TEST-HOST", now=NOW)
    b = cp.observe(config=config, host="MANIFEST-HOST", now=NOW)
    c = cp.observe(config=config, host="NO-SUCH-HOST", now=NOW)
    ids = lambda r: [i["id"] for i in r["items"]]
    assert ids(a) == ids(b) == ids(c) and a["counts"] == b["counts"] == c["counts"]
    assert by_id(a, "example-org/sat-known")["git"]["state"] == "dirty"
    assert by_id(b, "example-org/sat-known")["git"]["state"] == "unknown"
    assert by_id(b, "alpha-core")["git"]["state"] == "clean"
    assert by_id(c, "alpha-core")["git"]["state"] == "unknown"
    assert [g["host"] for g in by_id(c, "alpha-core")["git_hosts"]] == ["MANIFEST-HOST"]  # always listed
    assert c["host"] == {"id": "NO-SUCH-HOST", "source": "declared"}


# ---------------------------------------------------------------- time

def test_time_normalisation_never_presents_a_naive_value_as_utc():
    assert cp._time("2026-10-10T10:00:00+02:00") == ("2026-10-10T08:00:00+00:00", "declared", None)
    assert cp._time("2026-10-10T08:00:00Z") == ("2026-10-10T08:00:00+00:00", "declared", None)
    assert cp._time("2026-10-10T08:00:00") == (None, "no_timezone", "2026-10-10T08:00:00")
    assert cp._time("yesterday") == (None, "unparsable", "yesterday")
    assert cp._time(None) == (None, "absent", None)
    assert cp._time(12345) == (None, "unparsable", None)


def test_sources_expose_normalised_or_marked_generated_at(projection):
    result, _ = projection
    registry = source(result, "repo_registry")
    assert registry["generated_at"] == "2026-10-09T08:00:00+00:00" and registry["generated_at_basis"] == "declared"
    satellite = source(result, "satellite_catalog")
    assert satellite["generated_at"] is None and satellite["generated_at_basis"] == "no_timezone"
    assert satellite["generated_at_raw"] == "2026-10-10T08:00:00" and satellite["modified_at"].endswith("+00:00")
    modules = source(result, "modules_catalog")
    assert modules["generated_at_basis"] == "file_mtime" and modules["generated_at"] == modules["modified_at"]


def test_observed_at_is_only_a_real_observation_time(projection):
    result, _ = projection
    manifest_entry = by_id(result, "alpha-core")["git_hosts"][0]
    assert manifest_entry["observed_at"] == "2026-10-10T07:00:00+00:00" and manifest_entry["observed_at_basis"] == "declared"
    assert manifest_entry["last_commit"] is None and manifest_entry["last_commit_raw"] == "2026-09-01T00:00:00"
    registry_entry = by_id(result, "example-org/sat-known")["git"]
    assert registry_entry["observed_at"] is None and registry_entry["observed_at_basis"] == "absent"  # added_at is no observation


# ---------------------------------------------------------------- missing, broken, malformed sources

def test_missing_source_is_missing_with_empty_items_and_no_mock(tmp_path):
    config = build_sources(tmp_path)
    (tmp_path / "bot" / "master_satellite_catalog.json").unlink()
    result = cp.observe(config=config, now=NOW)
    entry = source(result, "satellite_catalog")
    assert entry["availability"] == "missing" and entry["error"] == "file_missing"
    assert result["counts"]["satellite"] == 0
    empty = cp.observe(config=cp.CatalogConfig(), now=NOW)
    assert empty["items"] == [] and empty["count"] == 0
    assert all(s["availability"] != "available" for s in empty["sources"])


def test_broken_json_is_an_error_not_a_crash(tmp_path):
    config = build_sources(tmp_path)
    (tmp_path / "skills" / "components.json").write_text("{not json", encoding="utf-8")
    result = cp.observe(config=config, now=NOW)
    assert source(result, "skills_registry")["availability"] == "error"
    assert result["counts"]["skill"] == 0 and result["counts"]["module"] == 2


MALFORMED = {
    "repo_registry": ("bot/repo_registry.json", {"repos": []}, "repo_registry"),
    "repo_registry_repo": ("bot/repo_registry.json", {"repos": {"o/r": []}}, "repo_registry"),
    "repo_registry_hosts": ("bot/repo_registry.json", {"repos": {"o/r": {"hosts": []}}}, "repo_registry"),
    "repo_registry_host": ("bot/repo_registry.json", {"repos": {"o/r": {"hosts": {"H": "x"}}}}, "repo_registry"),
    "repo_registry_clones": ("bot/repo_registry.json", {"repos": {"o/r": {"hosts": {"H": {"clones": "x"}}}}}, "repo_registry"),
    "repo_registry_clone_item": ("bot/repo_registry.json", {"repos": {"o/r": {"hosts": {"H": {"clones": ["x"]}}}}}, "repo_registry"),
    "repos_manifest": ("sync/slot-a/repos.json", {"host": "H", "repos": {}}, "repos_manifest:slot-a"),
    "modules_catalog": ("ai/.MODULES/modules.catalog.json", {"modules": {}}, "modules_catalog"),
    "bundles_catalog": ("ai/.BUNDLES/bundles.catalog.v1.json", {"bundles": "x"}, "bundles_catalog"),
    "skills_registry": ("skills/components.json", {"components": 5}, "skills_registry"),
    "satellite_catalog": ("bot/master_satellite_catalog.json", {"modules": "x"}, "satellite_catalog"),
}
KIND_SOURCE = {"module": "modules_catalog", "bundle": "bundles_catalog", "skill": "skills_registry",
               "satellite": "satellite_catalog"}


@pytest.mark.parametrize("name", sorted(MALFORMED))
def test_valid_json_with_wrong_nested_types_marks_only_that_source(tmp_path, name):
    config = build_sources(tmp_path)
    relative, body, expected_error = MALFORMED[name]
    _write(tmp_path / relative, body)
    result = cp.observe(config=config, now=NOW)  # must not raise
    json.dumps(result)
    errored = {s["id"] for s in result["sources"] if s["availability"] == "error"}
    assert errored == ({expected_error} if expected_error else set())
    if expected_error:  # the failure is visible in errors[], not silently skipped
        assert {"source": expected_error, "reason": "invalid_structure", "item": None} in result["errors"] or \
            any(e["source"] == expected_error for e in result["errors"])
    for kind, source_id in KIND_SOURCE.items():
        if source_id not in errored:
            assert result["counts"][kind] > 0, kind  # the other sources keep projecting


def test_nested_item_shape_errors_in_one_source_do_not_stop_the_others(tmp_path):
    config = build_sources(tmp_path)
    _write(tmp_path / "ai" / ".MODULES" / "modules.catalog.json", {"modules": [
        {"id": "ok-mod", "provides": 5, "requires": "x", "source_of_truth": ["bad"], "repo_aliases": {"a": 1}}, "junk", None]})
    _write(tmp_path / "ai" / ".STACKS" / "weird" / "stack.v2.json", {
        "id": "weird", "components": 5, "bundle_refs": "x", "external_components": [1], "nested_stacks": {"a": 1}})
    result = cp.observe(config=config, now=NOW)
    assert by_id(result, "ok-mod")["provides"] == [] and by_id(result, "stacks/weird")["relations"] == []
    assert result["counts"]["skill"] == 2


def test_an_unexpected_exception_in_one_projection_is_isolated(tmp_path, monkeypatch):
    config = build_sources(tmp_path)

    def explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(cp, "_modules", explode)
    result = cp.observe(config=config, now=NOW)
    entry = source(result, "modules_catalog")
    assert entry["availability"] == "error" and entry["error"] == "invalid_structure"
    assert {"source": "modules_catalog", "reason": "invalid_structure", "item": None} in result["errors"]
    assert result["counts"]["skill"] == 2 and result["counts"]["module"] == 0


def test_kind_filter_and_unsupported_kind(tmp_path):
    config = build_sources(tmp_path)
    only = cp.observe(kind="stack", config=config, now=NOW)
    assert set(only["counts"]) == {"stack"} and {i["type"] for i in only["items"]} == {"stack"} and only["count"] == 2
    with pytest.raises(ValueError):
        cp.observe(kind="plugin", config=config)


# ---------------------------------------------------------------- open-then-verify, reparse points

def test_read_verifies_the_final_path_of_the_open_handle(tmp_path):
    root = tmp_path / "root"
    _write(root / "ok.json", {"a": 1})
    assert cp._read(root / "ok.json", root)[0] == {"a": 1}
    outside = tmp_path / "outside"
    _write(outside / "secret.json", {"leak": True})
    with pytest.raises(PermissionError):
        cp._read(outside / "secret.json", root)  # a file outside the root is refused even without any link


def test_swapped_parent_link_is_caught_at_open_time_even_if_the_prefilter_was_passed(tmp_path):
    """TOCTOU: the component check passed earlier; now a parent is a link to the outside. The handle check must refuse."""
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    _write(outside / "secret.json", {"leak": True})
    link = root / "swapped"
    if not _make_link(link, outside):
        pytest.skip("neither symlink nor junction could be created on this host (no privilege)")
    with pytest.raises(PermissionError):
        cp._read(link / "secret.json", root)  # bypasses _safe_child on purpose
    assert cp._safe_child(root, "swapped", "secret.json") is None  # and the pre-filter alone also refuses it


def test_platform_without_a_final_path_fails_closed(tmp_path, monkeypatch):
    config = build_sources(tmp_path)
    monkeypatch.setattr(cp, "_final_path", lambda _fd: None)
    result = cp.observe(config=config, now=NOW)
    assert result["items"] == []
    errored = {s["id"] for s in result["sources"] if s["availability"] == "error"}
    assert {"modules_catalog", "bundles_catalog", "skills_registry", "satellite_catalog", "repo_registry"} <= errored
    assert all(s["error"] == "PermissionError" for s in result["sources"] if s["availability"] == "error")
    assert any(e["source"].startswith("stacks_") and e["reason"] == "PermissionError" for e in result["errors"])


def test_final_path_of_a_real_handle_matches_the_file(tmp_path):
    target = tmp_path / "f.json"
    _write(target, {"a": 1})
    fd = os.open(target, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    try:
        final = cp._final_path(fd)
    finally:
        os.close(fd)
    if final is None:
        pytest.skip("no final-path support on this platform (the reader fails closed there)")
    assert os.path.normcase(os.path.realpath(final)) == os.path.normcase(os.path.realpath(target))


def test_reparse_points_are_refused_without_os_path_isjunction(tmp_path, monkeypatch):
    """Python 3.10/3.11 have no os.path.isjunction: detection must not depend on it."""
    monkeypatch.delattr(os.path, "isjunction", raising=False)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    if not _make_link(link, outside):
        pytest.skip("neither symlink nor junction could be created on this host (no privilege)")
    assert cp._is_link(link) is True
    assert cp._is_link(outside) is False
    assert cp._safe_child(tmp_path, "link", "x.json") is None


def test_cloud_placeholders_are_not_treated_as_links():
    assert cp._is_cloud_placeholder(0x9000001A) and cp._is_cloud_placeholder(0x9000F01A)
    assert not cp._is_cloud_placeholder(0xA0000003) and not cp._is_cloud_placeholder(0xA000000C)


def test_aliases_are_not_unique_keys(projection):
    result, _ = projection
    a, b = by_id(result, "systems/homebase-stack"), by_id(result, "stacks/homebase-stack")
    assert a["aliases"] == b["aliases"] == ["homebase-stack"] and a["id"] != b["id"]
    assert len({(i["type"], i["id"]) for i in result["items"]}) == len(result["items"])  # type + id is the key
    assert "are NOT unique keys" in cp.__doc__


# ---------------------------------------------------------------- fixture and route

def test_fixture_matches_checked_in_copy(projection):
    result, _ = projection
    target = os.environ.get("BACH_WRITE_CATALOG_FIXTURE")
    if target:
        with open(target, "w", encoding="utf-8", newline="\n") as handle:  # LF: the GUI repo pins this file's SHA-256
            handle.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
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
        good = {"Authorization": "Bearer good"}
        ok = client.get("/api/capabilities/catalog", headers=good)
        assert ok.status_code == 200 and ok.json()["schema"] == "bach.catalog.v1" and ok.json()["count"] == 11
        assert str(tmp_path) not in ok.text
        assert client.get("/api/capabilities/catalog?kind=stack", headers=good).json()["counts"] == {"stack": 2}
        assert client.get("/api/capabilities/catalog?kind=nope", headers=good).status_code == 422
        # malformed sources must never become HTTP 500
        _write(tmp_path / "bot" / "repo_registry.json", {"repos": {"o/r": {"hosts": 7}}})
        _write(tmp_path / "ai" / ".MODULES" / "modules.catalog.json", {"modules": {}})
        broken = client.get("/api/capabilities/catalog", headers=good)
        assert broken.status_code == 200
        assert any(s["id"] == "modules_catalog" and s["availability"] == "error" for s in broken.json()["sources"])
