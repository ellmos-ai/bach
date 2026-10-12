from __future__ import annotations

import ast
import asyncio
import importlib.util
from pathlib import Path

import httpx
import pytest

from gui.api import report_provider, worker_status_adapter
from hub._services.document.report_operator_client import create_report_control_client


def test_factory_reuses_existing_client_without_io(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("client construction performed transport or configuration IO")
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    monkeypatch.setattr(worker_status_adapter, "_control_context", forbidden)
    client = create_report_control_client()
    assert type(client) is report_provider._ControlReportProvider
    assert client._device_token == ""


@pytest.mark.parametrize("method,args,verb,path", [
    ("capabilities", (), "GET", "reports/capabilities"),
    ("list_sources", ("sub_" + "1" * 48,), "GET", "reports/sources"),
    ("prepare", ({"fixture": True},), "POST", "reports/prepare"),
    ("finish", ("run-fixture", {"fixture": True}), "POST", "reports/finish"),
    ("status", ("run-fixture",), "GET", "reports/status"),
    ("cleanup", ("run-fixture", {"fixture": True}), "POST", "reports/cleanup"),
    ("watcher_status", (), "GET", "reports/watcher/status"),
    ("watcher_configure", ({"fixture": True},), "POST", "reports/watcher/configure"),
    ("watcher_tick", (), "POST", "reports/watcher/tick"),
])
def test_factory_exposes_same_nine_rpc_paths(monkeypatch, method, args, verb, path):
    client = create_report_control_client()
    calls = []
    async def record(request_verb, endpoint, **kwargs):
        calls.append((request_verb, endpoint))
        return {"fixture": True}
    monkeypatch.setattr(client, "_request", record)
    assert asyncio.run(getattr(client, method)(*args)) == {"fixture": True}
    assert calls == [(verb, path)]


def test_root_editable_shim_and_packaging_register_same_factory(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("fixture_bach_report_client", root / "bach_report_client.py")
    shim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shim)
    assert type(shim.create_report_control_client()) is report_provider._ControlReportProvider
    project = (root / "pyproject.toml").read_text()
    assert '[project.entry-points."ellmos.report_clients"]' in project
    assert 'bach-control = "bach_report_client:create_report_control_client"' in project
    assert 'py-modules = ["bach", "bach_api", "bach_report_client"]' in project
    tree = ast.parse((root / "setup.py").read_text())
    setup_call = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                      and node.func.id == "setuptools_setup")
    kwargs = {item.arg: item.value for item in setup_call.keywords}
    assert "bach_report_client" in ast.literal_eval(kwargs["py_modules"])
    assert ast.literal_eval(kwargs["entry_points"])["ellmos.report_clients"] == [
        "bach-control=bach_report_client:create_report_control_client",
    ]
