"""Readback diagnostics must not turn missing evidence into acceptance."""

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def readback(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "gui_readback_3718.py"
    spec = importlib.util.spec_from_file_location("readback_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "write_result_file", dict)
    module.KIT_SUMMARY.update(
        http_status=200,
        schema="ellmos-system-gui.kit-manifest.v1",
        pinned_source_commit=module.PINNED_SOURCE_COMMIT,
        installed_dist={
            "installed": True,
            "verified": True,
            "reason_code": None,
            "source_commit": module.PINNED_SOURCE_COMMIT,
            "page_count": module.EXPECTED_DIST_FILE_COUNT,
        },
    )
    module.ROUTE_LIST[:] = [(f"/page/{n}", "page") for n in range(module.EXPECTED_PAGE_COUNT)]
    module.ENTRIES[:] = [
        {"route": route, "kind": kind, "status": 200}
        for route, kind in module.ROUTE_LIST
    ]
    return module


def test_complete_verified_readback_is_ok(readback):
    assert readback.compute_verdict()[0] == "OK"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("installed", False),
        ("installed", None),
        ("verified", None),
        ("verified", 1),
        ("verified", False),
        ("source_commit", "f" * 40),
        ("source_commit", None),
        ("page_count", None),
        ("page_count", 1),
        ("reason_code", "commit_mismatch"),
    ],
)
def test_incomplete_or_wrong_installation_is_not_ok(readback, field, value):
    readback.KIT_SUMMARY["installed_dist"][field] = value
    assert readback.compute_verdict()[0] == "NOT-OK"


@pytest.mark.parametrize("value", [None, [], "unknown"])
def test_non_object_installation_is_not_ok(readback, value):
    readback.KIT_SUMMARY["installed_dist"] = value
    assert readback.compute_verdict()[0] == "NOT-OK"


@pytest.mark.parametrize(
    ("field", "value"),
    [("http_status", 401), ("schema", "unknown"), ("pinned_source_commit", "f" * 40)],
)
def test_invalid_kit_evidence_is_not_ok(readback, field, value):
    readback.KIT_SUMMARY[field] = value
    assert readback.compute_verdict()[0] == "NOT-OK"


@pytest.mark.parametrize("case", ["missing_get", "empty_plan", "short_plan", "duplicate_plan", "bad_get"])
def test_route_coverage_must_be_complete(readback, case):
    if case == "missing_get":
        readback.ENTRIES.pop()
    elif case == "empty_plan":
        readback.ROUTE_LIST.clear()
    elif case == "short_plan":
        readback.ROUTE_LIST.pop()
    elif case == "duplicate_plan":
        readback.ROUTE_LIST[-1] = readback.ROUTE_LIST[0]
    else:
        readback.ENTRIES[-1]["status"] = 404
    assert readback.compute_verdict()[0] == "NOT-OK"


def test_missing_installed_dist_is_recorded_without_type_error(readback, monkeypatch):
    body = json.dumps({"pinned_source_commit": readback.PINNED_SOURCE_COMMIT}).encode()
    monkeypatch.setattr(readback, "fetch", lambda route: (200, body, None))
    test = readback.GuiReadback3718("test_02_api_gui_kit_manifest_hard_pin")
    test.test_02_api_gui_kit_manifest_hard_pin()
    assert readback.compute_verdict()[0] == "NOT-OK"
    assert any(entry["route"] == "/api/gui/kit-manifest.page_count" for entry in readback.ENTRIES)


def test_historical_failed_installation_remains_not_ok(readback):
    path = Path(readback.__file__).with_name("gui_readback_3718_result.json")
    historical = json.loads(path.read_text(encoding="utf-8"))
    readback.KIT_SUMMARY.clear()
    readback.KIT_SUMMARY.update(historical["kit_summary"])
    readback.ENTRIES[:] = [json.loads(entry) for entry in historical["entries"]]
    assert historical["verdict"] == "NOT-OK"
    assert readback.compute_verdict()[0] == "NOT-OK"
