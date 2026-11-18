# SPDX-License-Identifier: MIT
"""Canonical source/content admission with temporary fixture repositories."""
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hub._services import ocean_resources_provider as provider


@pytest.fixture
def package(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    p = root / "ocean_resources"
    p.mkdir()
    source = p / "__init__.py"
    source.write_text("value = 'reviewed fixture'\n")
    pin = {"schema": "bach.ocean-resources-pin.v1", "version": provider.VERSION,
           "repository": provider.REPOSITORY, "commit": "a" * 40,
           "files": {"ocean_resources/__init__.py": hashlib.sha256(source.read_bytes()).hexdigest()}}
    direct = {"url": provider.REPOSITORY, "vcs_info": {"vcs": "git", "commit_id": pin["commit"]}}
    dist = SimpleNamespace(version=provider.VERSION, read_text=lambda name: json.dumps(direct),
                           locate_file=lambda relative: root / relative)
    monkeypatch.setattr(provider, "pin", lambda: pin)
    monkeypatch.setattr(provider.metadata, "distribution", lambda name: dist if name == "ocean-resources" else pytest.fail("old provider"))
    monkeypatch.setattr(provider.util, "find_spec", lambda name: SimpleNamespace(origin=str(source)))
    monkeypatch.setattr(provider, "_VERIFIED_ROOT", None)
    for name in list(sys.modules):
        if name == "ocean_resources" or name.startswith("ocean_resources."):
            monkeypatch.delitem(sys.modules, name)
    loaded = []
    def imported(name):
        loaded.append(name)
        module = SimpleNamespace(__file__=str(source))
        monkeypatch.setitem(sys.modules, name, module)
        return module
    monkeypatch.setattr(provider.importlib, "import_module", imported)
    return root, source, pin, direct, loaded


def test_canonical_exact_source_can_load_and_revalidate(package):
    _root, _source, _pin, _direct, loaded = package
    provider.load_verified(("ocean_resources",))
    provider.load_verified(("ocean_resources",))
    assert loaded == ["ocean_resources", "ocean_resources"]


@pytest.mark.parametrize("change", ["source", "extra", "old-distribution", "foreign-vcs", "wrong-commit"])
def test_content_and_provenance_fail_before_any_import(package, change):
    _root, source, _pin, direct, loaded = package
    if change == "source":
        source.write_text("raise RuntimeError('never execute')\n")
    elif change == "extra":
        (source.parent / "unreviewed.py").write_text("# unexpected\n")
    elif change == "old-distribution":
        direct["url"] = "https://github.com/ellmos-ai/open-ocean"
    elif change == "foreign-vcs":
        direct["url"] = "https://github.com/other/ocean-resources"
    else:
        direct["vcs_info"]["commit_id"] = "b" * 40
    with pytest.raises(provider.PipelineProviderUnavailable):
        provider.load_verified(("ocean_resources",))
    assert loaded == []


def test_editable_install_requires_origin_revision_and_clean_package(package, monkeypatch):
    root, _source, pin, direct, _loaded = package
    direct.clear()
    direct.update(url=root.as_uri(), dir_info={"editable": True})
    calls = []
    def git(actual, *args):
        assert actual == root
        calls.append(args)
        return provider.REPOSITORY if args[:2] == ("remote", "get-url") else ""
    monkeypatch.setattr(provider, "_git", git)
    provider.load_verified(("ocean_resources",))
    assert ("merge-base", "--is-ancestor", pin["commit"], "HEAD") in calls
    assert ("diff", "--quiet", "HEAD", "--", "ocean_resources") in calls
    monkeypatch.setattr(provider, "_git", lambda *args: (_ for _ in ()).throw(provider.PipelineProviderUnavailable("dirty")))
    with pytest.raises(provider.PipelineProviderUnavailable):
        provider.load_verified(("ocean_resources",))


def test_unverified_preloaded_package_cannot_be_adopted(package, monkeypatch):
    _root, source, _pin, _direct, loaded = package
    monkeypatch.setitem(sys.modules, "ocean_resources", SimpleNamespace(__file__=str(source)))
    with pytest.raises(provider.PipelineProviderUnavailable, match="preloaded"):
        provider.load_verified(("ocean_resources",))
    assert loaded == []


def test_changed_pin_cannot_replace_already_loaded_code(package):
    _root, source, pin, _direct, loaded = package
    provider.load_verified(("ocean_resources",))
    source.write_text("value = 'changed fixture'\n")
    pin["files"]["ocean_resources/__init__.py"] = hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(provider.PipelineProviderUnavailable, match="changed_in_process"):
        provider.load_verified(("ocean_resources",))
    assert loaded == ["ocean_resources"]
