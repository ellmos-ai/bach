# SPDX-License-Identifier: MIT
"""Shared read-only BACH/Ocean boundary; never a production DB or queue."""
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services import ocean_pipeline_adapter as adapter
from hub.pipeline import PipelineCoordinationHandler, _handle_pipeline


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("read-only Ocean projection must not open SQLite")
    monkeypatch.setattr(sqlite3, "connect", refuse)


def test_disabled_provider_is_explicit_hold_and_never_imports_ocean(monkeypatch):
    monkeypatch.delenv("BACH_PIPELINE_COORDINATION_ENABLED", raising=False)
    monkeypatch.setattr(adapter.metadata, "distribution", lambda name: pytest.fail("disabled provider lookup"))
    success, report = adapter.observe("catalog")
    assert not success and report["state"] == "HOLD"
    assert report["reason"] == "pipeline_coordination_disabled"
    assert report["read_only"] and report["start_authorized"] is False


@pytest.mark.parametrize("url,commit,version", [
    ("https://github.com/foreign/open-ocean.git", adapter.PIN, adapter.VERSION),
    (adapter.REPOSITORY + ".git", "0" * 40, adapter.VERSION),
    (adapter.REPOSITORY + ".git", adapter.PIN, "99.0"),
    (adapter.REPOSITORY + ".git?unexpected=1", adapter.PIN, adapter.VERSION),
])
def test_foreign_or_wrong_provider_rejected_before_import(monkeypatch, url, commit, version):
    monkeypatch.setenv("BACH_PIPELINE_COORDINATION_ENABLED", "1")
    direct = {"url": url, "vcs_info": {"vcs": "git", "commit_id": commit}}
    dist = SimpleNamespace(version=version, read_text=lambda _: json.dumps(direct))
    monkeypatch.setattr(adapter.metadata, "distribution", lambda _: dist)
    monkeypatch.setattr(adapter.util, "find_spec", lambda _: pytest.fail("unverified provider import"))
    success, report = adapter.observe("catalog")
    assert not success and report["reason"] == "pipeline_provider_provenance_mismatch"


def test_shadowed_import_is_rejected_before_loading_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("BACH_PIPELINE_COORDINATION_ENABLED", "1")
    direct = {"url": adapter.REPOSITORY + ".git", "vcs_info": {"vcs": "git", "commit_id": adapter.PIN}}
    dist = SimpleNamespace(version=adapter.VERSION, read_text=lambda _: json.dumps(direct),
                           locate_file=lambda path: tmp_path / path)
    monkeypatch.setattr(adapter.metadata, "distribution", lambda _: dist)
    monkeypatch.setattr(adapter.util, "find_spec", lambda _: SimpleNamespace(origin=str(tmp_path / "foreign.py")))
    success, report = adapter.observe("catalog")
    assert not success and report["reason"] == "pipeline_provider_import_mismatch"


@pytest.mark.parametrize("operation,args", [
    ("run", []), ("schedule", []), ("catalog", ["--run"]),
    ("shadow", ["--jobs", "private-unread.json"]),
])
def test_no_mutation_operation_or_implicit_shadow_defaults(monkeypatch, operation, args):
    monkeypatch.setattr(adapter, "_provider", lambda: pytest.fail("invalid request reached provider"))
    success, report = adapter.observe(operation, args)
    assert not success and report["start_authorized"] is False


@pytest.mark.parametrize("raw", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'])
def test_invalid_projection_json_rejected(tmp_path, raw):
    path = tmp_path / "jobs.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        adapter._read_json(path)


def test_cli_returns_failure_status_for_hold(monkeypatch, capsys):
    monkeypatch.delenv("BACH_PIPELINE_COORDINATION_ENABLED", raising=False)
    assert _handle_pipeline(["catalog"]) == 2
    assert json.loads(capsys.readouterr().out)["state"] == "HOLD"


def test_read_only_handler_is_discoverable_without_database(tmp_path):
    from core.registry import HandlerRegistry
    registry = HandlerRegistry()
    assert registry._load_handlers_from_file(SYSTEM_ROOT / "hub" / "pipeline.py", SYSTEM_ROOT / "hub") == 1
    assert "pipeline" in registry._handlers
    assert set(PipelineCoordinationHandler(tmp_path).get_operations()) == adapter.OPERATIONS


@pytest.fixture
def installed_provider(monkeypatch):
    monkeypatch.setenv("BACH_PIPELINE_COORDINATION_ENABLED", "1")
    try:
        adapter._provider()
    except adapter.PipelineProviderUnavailable as exc:
        pytest.skip("canonical pinned optional Ocean provider required: " + str(exc))


@pytest.mark.parametrize("operation", ["resources", "catalog", "host"])
def test_actual_pinned_provider_reads_with_no_database(installed_provider, operation):
    success, report = adapter.observe(operation)
    assert success, report
    assert report["state"] == "OBSERVED" and report["start_authorized"] is False
    if operation == "catalog":
        assert len(report["data"]["pipelines"]) == 15


def test_actual_shadow_preserves_input_bytes_and_starts_nothing(installed_provider, tmp_path):
    jobs = tmp_path / "jobs.json"
    jobs.write_bytes(b"[]\n")
    before = jobs.read_bytes()
    success, report = adapter.observe("shadow", ["--jobs", str(jobs), "--reserve-ram-bytes", "1073741824",
                                                 "--reserve-disk-bytes", "1073741824"])
    assert success, report
    assert report["data"]["start_authorized"] is False
    assert jobs.read_bytes() == before


def test_structured_api_and_cli_share_real_provider_without_session(installed_provider, tmp_path, monkeypatch, capsys):
    import bach_api
    monkeypatch.setattr(bach_api, "get_app", lambda: pytest.fail("projection unexpectedly booted App"))
    report = bach_api.pipeline.catalog()
    assert len(report["data"]["pipelines"]) == 15
    assert _handle_pipeline(["catalog"]) == 0
    assert json.loads(capsys.readouterr().out) == report
    assert "pipeline" in bach_api.__all__
    success, raw = PipelineCoordinationHandler(tmp_path).handle("catalog", [], dry_run=True)
    assert success and json.loads(raw) == report


@pytest.mark.parametrize("command", ["pipeline", "--pipeline"])
@pytest.mark.parametrize("operation", ["resources", "catalog", "host", "shadow"])
def test_real_cli_entrypoint_bypasses_all_startup_before_provider_gate(monkeypatch, capsys, command, operation):
    import bach as cli

    def refuse(*args, **kwargs):
        pytest.fail("read-only pipeline command reached global BACH startup")

    monkeypatch.delenv("BACH_PIPELINE_COORDINATION_ENABLED", raising=False)
    for name in ("get_logger", "_run_prosync_startup", "_track_activity", "_get_app", "_run_injectors"):
        monkeypatch.setattr(cli, name, refuse)
    args = [command, operation]
    if operation == "shadow":
        args.extend(["--jobs", "not-read.json", "--reserve-ram-bytes", "1", "--reserve-disk-bytes", "1"])
    monkeypatch.setattr(sys, "argv", ["bach", *args])
    assert cli.main() == 2
    report = json.loads(capsys.readouterr().out)
    assert report["state"] == "HOLD" and report["reason"] == "pipeline_coordination_disabled"


def test_real_cli_entrypoint_uses_pinned_provider_without_startup(installed_provider, monkeypatch, capsys):
    import bach as cli

    def refuse(*args, **kwargs):
        pytest.fail("read-only pipeline command reached global BACH startup")

    for name in ("get_logger", "_run_prosync_startup", "_track_activity", "_get_app", "_run_injectors"):
        monkeypatch.setattr(cli, name, refuse)
    monkeypatch.setattr(sys, "argv", ["bach", "pipeline", "catalog"])
    assert cli.main() == 0
    assert len(json.loads(capsys.readouterr().out)["data"]["pipelines"]) == 15


def test_api_introspection_raw_and_unknown_calls_never_boot_app(monkeypatch, capsys):
    import bach_api
    monkeypatch.setattr(bach_api, "get_app", lambda: pytest.fail("API introspection booted App"))
    monkeypatch.delenv("BACH_PIPELINE_COORDINATION_ENABLED", raising=False)
    assert set(bach_api.pipeline.available_operations()) == adapter.OPERATIONS
    assert adapter.OPERATIONS <= set(dir(bach_api.pipeline))
    for call in (lambda: bach_api.pipeline.raw("catalog"), lambda: bach_api.pipeline("catalog")):
        success, report = call()
        assert not success and report["state"] == "HOLD"
    report = bach_api.pipeline.run("forbidden")
    assert report["reason"] == "unknown_read_only_operation"
    assert "HOLD" in capsys.readouterr().out
