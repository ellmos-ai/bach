# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit tests for standalone config module."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from config import load_config, resolve_backend_config, update_config


def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "config"
    assert data["selfcontained"] is True


def test_atomic_load_and_update(tmp_path: Path):
    cfg_path = tmp_path / "app.json"
    assert load_config(cfg_path, {"mode": "safe"}) == {"mode": "safe"}

    res = update_config(cfg_path, lambda d: {**d, "theme": "dark", "port": 8080})
    assert res["theme"] == "dark"
    assert load_config(cfg_path)["port"] == 8080


def test_resolve_backend_config():
    resolved = resolve_backend_config(
        {"backend": {"type": "lm-studio", "base_url": "http://localhost:1234/v1", "default_model": "auto"}},
        env={"LM_STUDIO_MODEL": "local-coder", "OLLAMA_URL": "http://ignored:11434"},
    )
    assert resolved["type"] == "lmstudio"
    assert resolved["default_model"] == "local-coder"
    assert resolved["base_url"] == "http://localhost:1234/v1"
