# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit tests for Modular Core Remote-Registry Manifest-Feeds and Auto-Heal Rollback."""

import json
import shutil
import time
import zipfile
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from hub.modules import ModulesHandler
from gui.server import app


@pytest.fixture
def client(monkeypatch):
    import gui.server as server
    monkeypatch.setattr(
        server,
        "validate_token",
        lambda token: {"id": 1, "device_id": 1} if token == "test-token" else None,
    )
    return TestClient(app, headers={"Authorization": "Bearer test-token"})


def test_modules_feed_management_and_sync(tmp_path: Path):
    system_root = Path(__file__).parent.parent
    handler = ModulesHandler(system_root)

    # Use a custom temporary feeds file
    test_feeds_file = tmp_path / ".feeds.json"
    test_cache_file = tmp_path / ".feed_cache.json"
    handler._resolve_feeds_file = lambda: test_feeds_file
    handler._resolve_feed_cache_file = lambda: test_cache_file

    # Initially empty feeds
    feeds = handler.get_feeds()
    assert isinstance(feeds, list)

    # Create a local feed fixture
    feed_fixture = tmp_path / "test_feed.json"
    feed_data = {
        "schema": "bach.modules-feed.v1",
        "name": "Community Test Feed",
        "modules": [
            {
                "name": "cache",
                "version": "9.9.0",
                "download_url": "https://example.com/cache_9.9.0.zip",
                "sha256": "abc123def456",
                "description": "Super-fast cache module",
            }
        ]
    }
    feed_fixture.write_text(json.dumps(feed_data), encoding="utf-8")

    # Add feed
    ok_add, msg_add = handler.add_feed(str(feed_fixture), name="Test Feed")
    assert ok_add is True
    assert "erfolgreich registriert" in msg_add

    # Duplicate add rejected
    ok_dup, msg_dup = handler.add_feed(str(feed_fixture))
    assert ok_dup is False
    assert "bereits registriert" in msg_dup

    # Sync feeds
    sync_res = handler.sync_feeds(force=True)
    assert sync_res["feeds_count"] == 1
    assert sync_res["modules_count"] == 1
    assert sync_res["results"][0]["success"] is True

    # Get feed modules
    feed_mods = handler.get_feed_modules()
    assert len(feed_mods) == 1
    assert feed_mods[0]["name"] == "cache"
    assert feed_mods[0]["version"] == "9.9.0"

    # check_for_updates should now detect the feed update (9.9.0 > installed)
    chk = handler.check_for_updates(cache_ttl_sec=0)
    assert chk["has_updates"] is True
    feed_upds = [u for u in chk["updates"] if u.get("source_type") == "feed"]
    assert len(feed_upds) >= 1
    assert feed_upds[0]["name"] == "cache"
    assert feed_upds[0]["new_version"] == "9.9.0"

    # CLI feed list
    ok_cli, msg_cli = handler.handle("feed", ["list"])
    assert ok_cli is True
    assert "Test Feed" in msg_cli

    # Remove feed
    ok_rm, msg_rm = handler.remove_feed(feed_fixture.name)
    assert ok_rm is False  # Name is not ID or exact URL
    ok_rm2, msg_rm2 = handler.remove_feed(str(feed_fixture))
    assert ok_rm2 is True
    assert "entfernt" in msg_rm2


def test_modules_version_pins_and_quarantine(tmp_path: Path):
    system_root = Path(__file__).parent.parent
    handler = ModulesHandler(system_root)

    test_pins_file = tmp_path / ".version_pins.json"
    handler._resolve_pins_file = lambda: test_pins_file

    # Initially empty
    pins_data = handler.get_version_pins()
    assert pins_data["pins"] == {}
    assert pins_data["quarantined"] == {}

    # Pin module
    ok_pin, msg_pin = handler.pin_version("cache", "1.0.0", reason="Stabilitätsanforderung")
    assert ok_pin is True
    assert "fixiert" in msg_pin
    assert handler.is_module_pinned("cache") == "1.0.0"

    # Quarantine version
    handler.quarantine_version("cache", "1.5.0", reason="SyntaxError in Worker-Thread")
    assert handler.is_version_quarantined("cache", "1.5.0") is True
    assert handler.is_version_quarantined("cache", "1.0.0") is False

    # CLI pins list
    ok_pins_cli, msg_pins_cli = handler.handle("pins")
    assert ok_pins_cli is True
    assert "cache" in msg_pins_cli
    assert "1.0.0" in msg_pins_cli
    assert "1.5.0" in msg_pins_cli

    # Unpin module
    ok_unpin, msg_unpin = handler.unpin_version("cache")
    assert ok_unpin is True
    assert handler.is_module_pinned("cache") is None


def test_modules_auto_heal_on_corrupted_update(tmp_path: Path):
    system_root = Path(__file__).parent.parent
    handler = ModulesHandler(system_root)

    test_modules_dir = tmp_path / ".MODULES"
    test_modules_dir.mkdir(parents=True, exist_ok=True)
    handler.modules_dir = test_modules_dir

    test_pins_file = test_modules_dir / ".version_pins.json"
    handler._resolve_pins_file = lambda: test_pins_file

    # 1. Install a valid v1.0.0 module
    mod_v1 = tmp_path / "sample_mod_v1"
    mod_v1.mkdir(parents=True, exist_ok=True)
    (mod_v1 / "manifest.json").write_text(json.dumps({
        "name": "sample_mod",
        "version": "1.0.0",
        "entrypoints": {"library": "src/main.py"}
    }), encoding="utf-8")
    src_v1 = mod_v1 / "src"
    src_v1.mkdir(parents=True, exist_ok=True)
    (src_v1 / "main.py").write_text("# valid code\ndef run():\n    return 42\n", encoding="utf-8")

    ok_v1, msg_v1 = handler._install_module(str(mod_v1))
    assert ok_v1 is True
    assert (test_modules_dir / "sample_mod" / "manifest.json").is_file()

    # 2. Try to update with a corrupted v1.1.0 module (contains SyntaxError)
    mod_v2 = tmp_path / "sample_mod_v2"
    mod_v2.mkdir(parents=True, exist_ok=True)
    (mod_v2 / "manifest.json").write_text(json.dumps({
        "name": "sample_mod",
        "version": "1.1.0",
        "entrypoints": {"library": "src/main.py"}
    }), encoding="utf-8")
    src_v2 = mod_v2 / "src"
    src_v2.mkdir(parents=True, exist_ok=True)
    (src_v2 / "main.py").write_text("def broken_syntax(:\n    pass\n", encoding="utf-8")

    ok_v2, msg_v2 = handler._install_module(str(mod_v2))
    assert ok_v2 is False
    assert "[AUTO-HEAL]" in msg_v2
    assert "Syntax-Fehler" in msg_v2

    # Verify Auto-Heal restored the original v1.0.0 working version
    installed_manifest = json.loads((test_modules_dir / "sample_mod" / "manifest.json").read_text(encoding="utf-8"))
    assert installed_manifest["version"] == "1.0.0"
    installed_main = (test_modules_dir / "sample_mod" / "src" / "main.py").read_text(encoding="utf-8")
    assert "def run():" in installed_main

    # Verify v1.1.0 was quarantined
    assert handler.is_version_quarantined("sample_mod", "1.1.0") is True


def test_gui_api_feeds_and_pins_endpoints(client):
    # GET /api/modules/feeds
    res_feeds = client.get("/api/modules/feeds")
    assert res_feeds.status_code == 200
    data_feeds = res_feeds.json()
    assert data_feeds["status"] == "ok"
    assert "feeds" in data_feeds
    assert "feed_modules" in data_feeds

    # POST /api/modules/feeds (validation error on empty url)
    res_add_bad = client.post("/api/modules/feeds", json={})
    assert res_add_bad.status_code == 400

    # GET /api/modules/pins
    res_pins = client.get("/api/modules/pins")
    assert res_pins.status_code == 200
    data_pins = res_pins.json()
    assert data_pins["status"] == "ok"
    assert "pins" in data_pins
    assert "quarantined" in data_pins


def test_prompts_direct_execute_endpoint(client):
    # POST /api/prompts/execute
    res = client.post("/api/prompts/execute", json={
        "prompt": "Guten Tag, das ist ein Test-Prompt.",
        "persona": "buddha",
        "language": "de"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "reply" in data
    assert "clean_reply" in data
    assert data["persona"] == "buddha"

    # POST /api/prompts/stream
    res_stream = client.post("/api/prompts/stream", json={
        "prompt": "Kurzer Stream Test",
        "persona": "buddha"
    })
    assert res_stream.status_code == 200
    assert "text/event-stream" in res_stream.headers.get("content-type", "")
    stream_text = res_stream.text
    assert "event: start" in stream_text
    assert "event: done" in stream_text
