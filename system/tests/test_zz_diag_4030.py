import json
import pytest

def test_diag_4030_seed_registry_loads(tmp_path, monkeypatch):
    from hub._services.chat import worker_repo_registry as _wrr
    d = tmp_path / ".bach"
    d.mkdir(mode=0o700)
    d.chmod(0o700)
    f = d / "worker_repo_registry.v1.json"
    f.write_text(json.dumps({
        "schema": _wrr.REGISTRY_SCHEMA,
        "repositories": {"bach-test/bach": {"origin": "https://github.com/bach-test/bach", "default_branch": "main", "visibility": "public"}},
        "tasks": {"1": {"repository": "bach-test/bach", "source_sha": "a" * 40}},
    }), encoding="utf-8")
    f.chmod(0o600)
    monkeypatch.setenv("HOME", str(tmp_path))
    data = _wrr.load_registry(_wrr.registry_path())
    binding = _wrr.resolve_task_repository(1)
    assert _wrr.registry_path() == tmp_path / ".bach" / "worker_repo_registry.v1.json"
    assert data and binding.source_sha == "a" * 40
