"""Tests for BACH's unified hardware-/RAM-coupled `num_ctx` resolver."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from hub._services.llm.model_tuning_resolver import (
    apply_model_num_ctx_change,
    resolve_effective_num_ctx,
)


def test_unified_precedence_chain_with_hardware_catalog_and_reserve(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
    monkeypatch.delenv("OLLAMA_NUM_CFG", raising=False)

    cfg_path = tmp_path / "ollama_config.json"
    cfg_path.write_text(
        json.dumps({"models": {"inkling-2-mini:latest": {"num_ctx": 12288}}}),
        encoding="utf-8",
    )
    reserve = {"models": {"inkling-2-mini:latest": {"num_ctx": 16384}}}

    # 1. Explicit beats everything
    r_exp = resolve_effective_num_ctx(
        "inkling-2-mini:latest",
        explicit_num_ctx=8192,
        slot_override={"num_ctx": 10240},
        ollama_config_path=cfg_path,
        reserve_policy=reserve,
        host_ram_gib=32.0,
    )
    assert r_exp["num_ctx"] == 8192
    assert r_exp["num_ctx_source"] == "explicit"

    # 2. Slot override beats ollama_config & reserve & catalog
    r_slot = resolve_effective_num_ctx(
        "inkling-2-mini:latest",
        slot_override={"num_ctx": 10240},
        ollama_config_path=cfg_path,
        reserve_policy=reserve,
        host_ram_gib=32.0,
    )
    assert r_slot["num_ctx"] == 10240
    assert r_slot["num_ctx_source"] == "slot_override"

    # 3. ollama_config beats reserve & catalog
    r_cfg = resolve_effective_num_ctx(
        "inkling-2-mini:latest",
        ollama_config_path=cfg_path,
        reserve_policy=reserve,
        host_ram_gib=32.0,
    )
    assert r_cfg["num_ctx"] == 12288
    assert r_cfg["num_ctx_source"] == "model_config"

    # 4. Reserve policy beats catalog default (prevents model_budget_conflict)
    r_res = resolve_effective_num_ctx(
        "inkling-2-mini:latest",
        reserve_policy={"models": {"inkling-2-mini:latest": {"num_ctx": 16384}}},
        host_ram_gib=64.0,
    )
    assert r_res["num_ctx"] == 16384
    assert r_res["num_ctx_source"] == "reserve_policy"

    # 5. Catalog default matches host RAM tier (32 GiB -> 12288/40 turns; 64 GiB -> 32768/50 turns)
    r_32 = resolve_effective_num_ctx("inkling-2-mini:latest", host_ram_gib=32.0)
    assert r_32["num_ctx"] == 12288
    assert r_32["num_ctx_source"] == "catalog_default"
    assert r_32["recommended_max_tool_rounds"] == 40
    assert r_32["confidence_tier"] == "measured_live"

    r_64 = resolve_effective_num_ctx("inkling-2-mini:latest", host_ram_gib=64.0)
    assert r_64["num_ctx"] == 32768
    assert r_64["recommended_max_tool_rounds"] == 50

    # 6. Unknown model uses env_fallback, then safe_baseline
    r_env = resolve_effective_num_ctx("llama3.2", host_ram_gib=32.0, env_num_ctx="8192")
    assert r_env["num_ctx"] == 8192
    assert r_env["num_ctx_source"] == "env_fallback"

    r_base = resolve_effective_num_ctx("llama3.2", host_ram_gib=32.0)
    assert r_base["num_ctx"] == 4096
    assert r_base["num_ctx_source"] == "safe_baseline"


def test_apply_model_num_ctx_change_syncs_config_reserve_and_unloads(tmp_path: Path):
    cfg_path = tmp_path / "ollama_config.json"
    reserve_path = tmp_path / "resource-reserve.json"
    reserve_path.write_text(
        json.dumps(
            {
                "schema": "bach.local-resource-reserve.v1",
                "enabled": True,
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

    unloaded_models: list[str] = []

    class _FakeBackend:
        def unload(self, model: str) -> bool:
            unloaded_models.append(model)
            return True

    receipt = apply_model_num_ctx_change(
        "inkling-2-mini:latest",
        24576,
        ollama_config_path=cfg_path,
        reserve_policy_path=reserve_path,
        num_ctx_recommended=16384,
        backend=_FakeBackend(),
        unload_running_model=True,
    )
    assert receipt["num_ctx"] == 24576
    assert receipt["reserve_policy_synced"] is True
    assert receipt["runner_unloaded"] is True
    assert unloaded_models == ["inkling-2-mini:latest"]

    saved_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert saved_cfg["models"]["inkling-2-mini:latest"]["num_ctx"] == 24576
    assert saved_cfg["models"]["inkling-2-mini:latest"]["num_ctx_recommended"] == 16384

    saved_reserve = json.loads(reserve_path.read_text(encoding="utf-8"))
    assert saved_reserve["models"]["inkling-2-mini:latest"]["num_ctx"] == 24576


def test_invalid_num_ctx_raises_canonical_error():
    with pytest.raises(ValueError, match="ganze Zahl"):
        resolve_effective_num_ctx("inkling-2-mini:latest", explicit_num_ctx=True)
    with pytest.raises(ValueError, match="zwischen 512 und 262144"):
        resolve_effective_num_ctx("inkling-2-mini:latest", explicit_num_ctx=256)
