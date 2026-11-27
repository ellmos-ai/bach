"""Tests for GET/PUT /api/system/models/tuning (#2972 / #4445)."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from gui.api import unified_api


def _make_client(monkeypatch, tmp_path: Path):
    cfg_path = tmp_path / "ollama_config.json"
    reserve_path = tmp_path / "resource-reserve.json"
    reserve_path.write_text(
        json.dumps(
            {
                "schema": "bach.local-resource-reserve.v1",
                "enabled": True,
                "memory_reserve_bytes": 2 * 1024**3,
                "disk_reserve_bytes": 1024**3,
                "wait_seconds": 30,
                "poll_seconds": 2,
                "models": {
                    "inkling-2-mini:latest": {
                        "digest": "a" * 64,
                        "weight_budget_bytes": 22 * 1024**3,
                        "kv_headroom_bytes": 2 * 1024**3,
                        "overhead_bytes": 1 * 1024**3,
                        "num_ctx": 16384,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(unified_api, "_require_memory_device", lambda _req: {"id": "test-device"})
    monkeypatch.setattr(unified_api, "_ollama_config_path", lambda: cfg_path)
    monkeypatch.setattr(
        unified_api,
        "_installed_local_ollama_models",
        lambda timeout=1.5: {"inkling-2-mini:latest"},
    )
    monkeypatch.setattr(
        "hub._services.llm.model_tuning_resolver.detect_host_ram_gib",
        lambda: 32.0,
    )
    monkeypatch.setattr(
        "hub._services.chat.local_resource_reserve.policy_path",
        lambda: reserve_path,
    )
    monkeypatch.setattr(
        "hub._services.chat.local_resource_reserve.read_policy",
        lambda: (json.loads(reserve_path.read_text(encoding="utf-8")), "vtest"),
    )

    app = FastAPI()
    app.include_router(unified_api.router)
    return TestClient(app), cfg_path, reserve_path


def test_get_and_put_local_model_tuning_roundtrip_and_reset(monkeypatch, tmp_path: Path):
    client, cfg_path, reserve_path = _make_client(monkeypatch, tmp_path)

    resp = client.get("/api/system/models/tuning")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["host_ram_gib"] == 32.0
    ink = next(m for m in data["models"] if m["model"] == "inkling-2-mini:latest")
    assert ink["installed"] is True
    assert ink["num_ctx"] == 16384
    assert ink["recommended_max_tool_rounds"] == 40
    assert ink["has_manual_override"] is False

    # Reject invalid num_ctx and cloud model names
    bad_ctx = client.put("/api/system/models/tuning", json={"model": "inkling-2-mini:latest", "num_ctx": 256})
    assert bad_ctx.status_code == 400
    bad_cloud = client.put("/api/system/models/tuning", json={"model": "kimi-k3:cloud", "num_ctx": 8192})
    assert bad_cloud.status_code == 400

    # Save manual override and verify both ollama_config.json & resource-reserve.json sync
    upd = client.put("/api/system/models/tuning", json={"model": "inkling-2-mini:latest", "num_ctx": 12288})
    assert upd.status_code == 200
    upd_json = upd.json()
    assert upd_json["ok"] is True
    assert upd_json["reserve_policy_synced"] is True
    assert upd_json["resolved"]["num_ctx"] == 12288
    assert upd_json["resolved"]["num_ctx_source"] == "model_config"
    assert json.loads(cfg_path.read_text(encoding="utf-8"))["models"]["inkling-2-mini:latest"]["num_ctx"] == 12288
    assert json.loads(reserve_path.read_text(encoding="utf-8"))["models"]["inkling-2-mini:latest"]["num_ctx"] == 12288

    # Reset back to hardware default (16384)
    rst = client.put(
        "/api/system/models/tuning",
        json={"model": "inkling-2-mini:latest", "reset_to_default": True},
    )
    assert rst.status_code == 200
    rst_json = rst.json()
    assert rst_json["ok"] is True
    assert rst_json["reserve_policy_synced"] is True
    assert rst_json["resolved"]["num_ctx"] == 16384
    assert json.loads(reserve_path.read_text(encoding="utf-8"))["models"]["inkling-2-mini:latest"]["num_ctx"] == 16384
