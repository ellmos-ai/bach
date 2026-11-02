# -*- coding: utf-8 -*-
"""Regression test for /api/health and /dist-manifest.json routes (#3744)."""

import asyncio
import json
from pathlib import Path
from fastapi.responses import FileResponse
import gui.server as srv


def test_api_health_returns_200_ok():
    res = asyncio.run(srv.get_api_health())
    assert res == {"status": "ok"}


def test_dist_manifest_serves_from_astro_dist_dir(tmp_path: Path, monkeypatch):
    manifest = tmp_path / "dist-manifest.json"
    manifest.write_text('{"kit_name":"ellmos-system-gui","kit_version":"0.2.30"}', encoding="utf-8")
    monkeypatch.setattr(srv, "ASTRO_DIST_DIR", tmp_path)

    res = asyncio.run(srv.get_dist_manifest())
    assert isinstance(res, FileResponse)
    assert Path(res.path) == manifest
    data = json.loads(Path(res.path).read_text(encoding="utf-8"))
    assert data["kit_name"] == "ellmos-system-gui"
