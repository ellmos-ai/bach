# SPDX-License-Identifier: MIT
"""Prüft die modellbezogene num-ctx-Auflösung in local_resource_reserve."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from hub._services.chat import local_resource_reserve as reserve
from hub._services.llm.model_backend import OllamaBackend

GIB = reserve.GIB
MODEL = "example:small"
DIGEST = "a" * 64


def policy():
    return {"schema": reserve.SCHEMA, "enabled": True,
            "memory_reserve_bytes": GIB, "disk_reserve_bytes": GIB,
            "wait_seconds": 2, "poll_seconds": 1,
            "models": {MODEL: {"digest": DIGEST, "weight_budget_bytes": 2 * GIB,
                               "kv_headroom_bytes": GIB // 2, "overhead_bytes": GIB // 4,
                               "num_ctx": 1024}}}


@pytest.fixture
def resources(tmp_path, monkeypatch):
    path = tmp_path / "resource-reserve.json"
    path.write_text(json.dumps(policy()), encoding="utf-8")
    monkeypatch.setattr(reserve, "policy_path", lambda: path)
    monkeypatch.setattr(reserve, "_data_roots", lambda: {
        "taskdb": tmp_path / "db", "slots": tmp_path / "slots", "runtime": tmp_path / "runtime"})
    monkeypatch.setattr(reserve.psutil, "virtual_memory", lambda: SimpleNamespace(total=32 * GIB, available=8 * GIB))
    monkeypatch.setattr(reserve.shutil, "disk_usage", lambda p: SimpleNamespace(free=4 * GIB))
    async def observed(*_):
        return {"external": False, "digest": DIGEST, "weight_floor_bytes": 2 * GIB,
                "resident_context": None, "server_responded": True}
    monkeypatch.setattr(reserve, "observe_ollama", observed)
    return path, OllamaBackend(default_model=MODEL, num_ctx=1024)


def test_external_handoff_threshold_uses_config_num_ctx(resources, monkeypatch):
    _, backend = resources

    async def external(*_):
        return {"external": True}

    monkeypatch.setattr(reserve, "observe_ollama", external)
    monkeypatch.setattr(reserve, "_ollama_num_ctx_config", lambda: {MODEL: {"num_ctx": 4096}})
    result = asyncio.run(reserve.probe(backend, MODEL))
    assert result["state"] == "external_target"
    assert result["handoff_context_threshold"] == 3276


def test_external_handoff_threshold_uses_config_recommendation(resources, monkeypatch):
    _, backend = resources

    async def external(*_):
        return {"external": True}

    monkeypatch.setattr(reserve, "observe_ollama", external)
    monkeypatch.setattr(reserve, "_ollama_num_ctx_config", lambda: {MODEL: {"num_ctx_recommended": 2048}})
    result = asyncio.run(reserve.probe(backend, MODEL))
    assert result["state"] == "external_target"
    assert result["handoff_context_threshold"] == 1638


def test_external_handoff_threshold_falls_back_to_backend(resources, monkeypatch):
    _, backend = resources

    async def external(*_):
        return {"external": True}

    monkeypatch.setattr(reserve, "observe_ollama", external)
    monkeypatch.setattr(reserve, "_ollama_num_ctx_config", lambda: {})
    result = asyncio.run(reserve.probe(backend, MODEL))
    assert result["state"] == "external_target"
    assert result["handoff_context_threshold"] == 819


def test_matching_config_num_ctx_is_no_conflict(resources, monkeypatch):
    path, backend = resources
    data = json.loads(path.read_text(encoding="utf-8"))
    data["models"][MODEL]["num_ctx"] = 4096
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(reserve, "_ollama_num_ctx_config", lambda: {MODEL: {"num_ctx": 4096}})
    result = asyncio.run(reserve.probe(backend, MODEL))
    assert result["state"] == "ready"


def test_mismatched_config_num_ctx_conflicts(resources, monkeypatch):
    _, backend = resources
    monkeypatch.setattr(reserve, "_ollama_num_ctx_config", lambda: {MODEL: {"num_ctx": 2048}})
    result = asyncio.run(reserve.probe(backend, MODEL))
    assert result["state"] == "model_budget_conflict"
    assert result["retryable"] is False