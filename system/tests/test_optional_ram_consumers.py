# SPDX-License-Identifier: MIT
"""Tests for optional on-demand RAM consumers (Colima, n8n) in ocean-resources and local_resource_reserve."""
from __future__ import annotations

import asyncio
import json
import subprocess
from copy import deepcopy
from types import SimpleNamespace

import pytest
from hub._services.chat import local_resource_reserve as reserve
from hub._services.llm.model_backend import OllamaBackend

GIB = reserve.GIB
MODEL = "example:small"
DIGEST = "a" * 64


def _base_policy():
    mod = reserve._load_optional_consumers_module()
    return {
        "schema": reserve.SCHEMA,
        "enabled": True,
        "memory_reserve_bytes": GIB,
        "disk_reserve_bytes": GIB,
        "wait_seconds": 2,
        "poll_seconds": 1,
        "optional_consumers": deepcopy(mod.DEFAULT_OPTIONAL_CONSUMERS),
        "models": {
            MODEL: {
                "digest": DIGEST,
                "weight_budget_bytes": 2 * GIB,
                "kv_headroom_bytes": GIB // 2,
                "overhead_bytes": GIB // 4,
                "num_ctx": 1024,
            }
        },
    }


def test_validate_policy_accepts_valid_optional_consumers_and_preserves_receipt_shape(tmp_path, monkeypatch):
    path = tmp_path / "resource-reserve.json"
    path.write_text(json.dumps(_base_policy()), encoding="utf-8")
    monkeypatch.setattr(reserve, "policy_path", lambda: path)
    monkeypatch.setattr(
        reserve,
        "_data_roots",
        lambda: {"taskdb": tmp_path / "db", "slots": tmp_path / "slots", "runtime": tmp_path / "runtime"},
    )
    monkeypatch.setattr(reserve.psutil, "virtual_memory", lambda: SimpleNamespace(total=32 * GIB, available=8 * GIB))
    monkeypatch.setattr(reserve.shutil, "disk_usage", lambda _p: SimpleNamespace(free=4 * GIB))

    async def observed(*_):
        return {
            "external": False,
            "digest": DIGEST,
            "weight_floor_bytes": 2 * GIB,
            "resident_context": None,
            "server_responded": True,
        }

    monkeypatch.setattr(reserve, "observe_ollama", observed)
    receipt = asyncio.run(reserve.probe(OllamaBackend(default_model=MODEL, num_ctx=1024), MODEL))
    assert receipt["state"] == "ready" and receipt["admitted"] is True
    assert reserve.valid_capacity_receipt_shape(receipt)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c["colima"].update(autostart=True),
        lambda c: c["colima"].update(start_mode="always"),
        lambda c: c["colima"].update(ram_budget_bytes=0),
        lambda c: c["n8n"].update(idle_timeout_seconds=10),
        lambda c: c.update({"BAD NAME": c["colima"]}),
        lambda c: c["n8n"].update(unknown_field=1),
    ],
)
def test_invalid_optional_consumers_fail_closed(mutate):
    raw = _base_policy()
    mutate(raw["optional_consumers"])
    with pytest.raises(ValueError):
        reserve.validate_policy(raw)


def test_stopped_optional_consumers_account_zero_bytes_and_running_account_budget():
    mod = reserve._load_optional_consumers_module()
    consumers = mod.DEFAULT_OPTIONAL_CONSUMERS

    stopped_eval = reserve.evaluate_optional_consumers(consumers, detector=lambda _n, _s: False)
    assert stopped_eval["configured"] is True
    assert stopped_eval["active_ram_bytes"] == 0
    assert stopped_eval["standby_ram_bytes"] == 3 * GIB
    assert stopped_eval["consumers"]["colima"]["accounted_ram_bytes"] == 0
    assert stopped_eval["consumers"]["n8n"]["accounted_ram_bytes"] == 0

    running_colima = reserve.evaluate_optional_consumers(consumers, detector=lambda n, _s: n == "colima")
    assert running_colima["active_ram_bytes"] == 2 * GIB
    assert running_colima["standby_ram_bytes"] == 1 * GIB
    assert running_colima["consumers"]["colima"]["accounted_ram_bytes"] == 2 * GIB
    assert running_colima["consumers"]["n8n"]["accounted_ram_bytes"] == 0


def test_on_demand_controller_starts_dependency_and_stops_after_idle_timeout(tmp_path):
    mod = reserve._load_optional_consumers_module()
    consumers = mod.validate_optional_consumers(mod.DEFAULT_OPTIONAL_CONSUMERS)
    controller = mod.OnDemandController(state_dir=tmp_path / "state", consumers=consumers)

    running_state = {"colima": False, "n8n": False}
    commands: list[list[str]] = []

    def fake_detector(name: str, _spec):
        return running_state[name]

    def fake_runner(cmd, **_kwargs):
        commands.append(list(cmd))
        if cmd[:2] == ["colima", "start"]:
            running_state["colima"] = True
        elif cmd[:3] == ["docker", "compose", "up"]:
            running_state["n8n"] = True
        elif cmd[:2] == ["colima", "stop"]:
            running_state["colima"] = False
        elif cmd[:3] == ["docker", "compose", "stop"]:
            running_state["n8n"] = False
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    # Insufficient RAM refuses on-demand start
    denied = controller.start_consumer(
        "n8n",
        available_ram_bytes=3 * GIB,
        reserve_ram_bytes=2 * GIB,
        runner=fake_runner,
        detector=fake_detector,
        now=1000.0,
    )
    assert denied["state"] == "waiting_memory_reserve" and denied["started"] is False
    assert commands == []

    # Sufficient RAM starts colima dependency then n8n
    started = controller.start_consumer(
        "n8n",
        available_ram_bytes=8 * GIB,
        reserve_ram_bytes=2 * GIB,
        runner=fake_runner,
        detector=fake_detector,
        now=1000.0,
    )
    assert started["state"] == "started" and started["started"] is True
    assert running_state == {"colima": True, "n8n": True}
    assert commands[0][:2] == ["colima", "start"]
    assert commands[1][:3] == ["docker", "compose", "up"]

    # Before idle timeout (1800s), nothing stops
    assert controller.stop_idle_consumers(now=2000.0, runner=fake_runner, detector=fake_detector) == []
    assert running_state == {"colima": True, "n8n": True}

    # After idle timeout (1800s), n8n stops before colima
    stopped = controller.stop_idle_consumers(now=2900.0, runner=fake_runner, detector=fake_detector)
    assert [item["consumer"] for item in stopped] == ["n8n", "colima"]
    assert running_state == {"colima": False, "n8n": False}
