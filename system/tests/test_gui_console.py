# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Vertragstests fuer den optionalen Unified-GUI-Mount."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gui.config import Settings
from gui.console import mount_console


def test_console_settings_are_disabled_by_default():
    settings = Settings.from_env({})
    assert settings.console_enabled is False
    assert settings.console_prefix == "/control"


def test_console_settings_read_explicit_host_switches():
    settings = Settings.from_env(
        {
            "BACH_GUI_CONSOLE_ENABLED": "true",
            "BACH_GUI_CONSOLE_PREFIX": "/operator/",
        }
    )
    assert settings.console_enabled is True
    assert settings.console_prefix == "/operator"


def test_mount_console_degrades_without_optional_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "unified_gui", None)
    app = FastAPI()

    assert mount_console(app) is False
    assert TestClient(app).get("/control/").status_code == 404


def test_mount_console_uses_existing_mount_contract(monkeypatch):
    calls: list[tuple[FastAPI, str]] = []
    module = ModuleType("unified_gui")

    def fake_mount(host_app: FastAPI, prefix: str):
        sub_app = FastAPI()

        @sub_app.get("/")
        def index():
            return {"surface": "ellmos-unified-gui"}

        host_app.mount(prefix, sub_app)
        calls.append((host_app, prefix))
        return sub_app

    module.mount = fake_mount  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "unified_gui", module)
    app = FastAPI()

    assert mount_console(app, prefix="/operator") is True
    assert calls == [(app, "/operator")]
    assert TestClient(app).get("/operator/").json() == {
        "surface": "ellmos-unified-gui"
    }


def test_mount_console_does_not_stop_bach_when_mount_fails(monkeypatch):
    module = ModuleType("unified_gui")

    def broken_mount(_host_app: FastAPI, _prefix: str):
        raise RuntimeError("kaputter optionaler Mount")

    module.mount = broken_mount  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "unified_gui", module)

    assert mount_console(FastAPI()) is False


def _real_unified_gui_src() -> Path | None:
    configured = os.environ.get("BACH_UNIFIED_GUI_SRC")
    if configured:
        candidate = Path(configured)
        return candidate if candidate.is_dir() else None

    repo_root = Path(__file__).resolve().parents[2]
    candidate = repo_root.parent / "unified-gui" / "src"
    return candidate if candidate.is_dir() else None


def test_mount_console_with_real_sibling_when_available(monkeypatch):
    """Lokaler Cross-Repo-Smoke; in Einzel-Repo-CI bewusst ein sauberer Skip."""
    source = _real_unified_gui_src()
    if source is None:
        pytest.skip("kein ellmos-unified-gui-Geschwistercheckout vorhanden")

    existing_modules = set(sys.modules)
    monkeypatch.syspath_prepend(str(source))
    app = FastAPI()
    try:
        assert mount_console(app, prefix="/control") is True
        response = TestClient(app).get("/control/")
        assert response.status_code == 200
        assert "<h1>Backends & Panels</h1>" in response.text
    finally:
        for name in list(sys.modules):
            if name == "unified_gui" or name.startswith("unified_gui."):
                if name not in existing_modules:
                    sys.modules.pop(name, None)
