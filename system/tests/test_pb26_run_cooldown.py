"""PB-26 Paket 3: after each run a local model worker waits for the RAM distributor.

Lukas, 08.11.2026: "nach abschluss eines laufes eine zwangspause einlegen lassen und nach
cooldown wieder anfahren, das ist für einen hintergrundworker völlig okay". The admission
lives in ocean-resources (``RunCooldownGate``); the worker only asks, waits with a visible
reason and unloads its model once when the pause gets long. The Mac Studio swapped out
198 to 1171 MiB/min on 08.11. while its pressure level stayed normal.
"""
import importlib
import threading
from types import SimpleNamespace

import pytest

from hub._services.chat import run_cooldown
from hub._services.llm.model_backend import OllamaBackend, OpenRouterBackend
from system.tests.test_pb26_idle_unload import MODEL, ollama  # noqa: F401 -- HTTP-recording fixture

UNLOAD = ("unload", {"model": MODEL, "keep_alive": 0})
REAL_OPEN_GATE = run_cooldown.open_gate  # conftest stubs it per test


def _controller():
    return importlib.import_module("hub._services.chat.telegram_chat")


class ScriptedGate:
    """Answers like RunCooldownGate.check() from a script; records what it was shown."""

    def __init__(self, *reasons, unload_after=0.0, rate=198.0):
        self.reasons, self.seen = list(reasons), []
        self.policy = SimpleNamespace(unload_after_seconds=unload_after)
        self.rate = rate

    def check(self, sample, *, seconds_since_run_end):
        self.seen.append(sample)
        reason = self.reasons.pop(0) if self.reasons else "admitted"
        return SimpleNamespace(admitted=reason == "admitted", reason=reason, swapout_mib_per_minute=self.rate)


@pytest.fixture
def run(monkeypatch, ollama):  # noqa: F811
    """A local-model worker control at the end of a run; slot writes are recorded."""
    control = _controller()
    worker = control._WorkerControl(worker_id="w")
    worker._review_backend = OllamaBackend(default_model=MODEL)
    worker._review_requested_model = MODEL
    updates = []

    def update(ctrl, changes):
        updates.append(changes)
        return {} if not ctrl.stop_event.is_set() else None
    monkeypatch.setattr(control, "_worker_metadata_available", lambda worker_id: True)
    monkeypatch.setattr(control, "bump_pause_counter", lambda *a, **kw: False)  # no slot pause
    monkeypatch.setattr(control, "_update_worker_slot", update)
    monkeypatch.setattr(control, "_record_worker_activity", lambda *a, **kw: None)
    monkeypatch.setattr(control, "_RUN_COOLDOWN_POLL_SECONDS", 0)

    def gate(scripted, sampler=lambda: "sample"):
        monkeypatch.setattr(run_cooldown, "open_gate", lambda backend, model: (scripted, sampler))
        return control._wait_worker_cooldown(worker)
    return SimpleNamespace(worker=worker, updates=updates, gate=gate)


def test_swap_cooldown_shows_reason_and_rate_unloads_once_and_resumes(run, ollama):  # noqa: F811
    assert run.gate(ScriptedGate("cooldown:swap", "cooldown:swap", "cooldown:swap")) is True
    assert ollama == [UNLOAD]  # a long pause unloads exactly once
    paused = [u for u in run.updates if u.get("current_activity", "").startswith("Abkühlpause (")]
    # "paused" + auto_paused needs pause_started_at; without it startup refuses (invalid_cooldown)
    assert len(paused) == 3 and all(u["status"] == "running" and "auto_paused" not in u for u in paused)
    assert "cooldown:swap" in paused[0]["current_activity"]
    assert "198 MiB/min" in paused[0]["current_activity"]
    assert run.updates[-1]["status"] == "running" and run.updates[-1]["auto_paused"] is False


def test_thermal_cooldown_is_visible_and_short_pauses_do_not_unload(run, ollama):  # noqa: F811
    assert run.gate(ScriptedGate("cooldown:thermal", unload_after=3600)) is True
    assert ollama == []
    assert "cooldown:thermal" in run.updates[0]["current_activity"]


def test_minimum_pause_never_unloads(run, ollama):  # noqa: F811
    assert run.gate(ScriptedGate("cooldown:min", "cooldown:min")) is True
    assert ollama == []
    assert "cooldown:min" in run.updates[0]["current_activity"]


def test_admitted_at_once_changes_nothing(run, ollama):  # noqa: F811
    assert run.gate(ScriptedGate()) is True
    assert (ollama, run.updates) == ([], [])


def test_failed_measurement_does_not_crash_and_reaches_the_gate_as_unknown(run, ollama):  # noqa: F811
    def broken():
        raise OSError("vm_stat gone")
    gate = ScriptedGate("cooldown:min")
    assert run.gate(gate, sampler=broken) is True
    assert gate.seen == [None, None]


def test_stop_during_the_cooldown_ends_the_wait(run, ollama):  # noqa: F811
    run.worker.stop_event = threading.Event()
    run.worker.stop_event.set()
    assert run.gate(ScriptedGate("cooldown:swap")) is False


def test_cloud_and_other_backends_get_no_gate_and_load_nothing(monkeypatch):
    def no_load():
        raise AssertionError("cloud models must not consult the RAM distributor")
    monkeypatch.setattr("hub._services.ocean_stack_bridge.load_ocean_ram_distributor_module", no_load)
    ollama_backend = OllamaBackend(default_model=MODEL)
    for backend, model in ((ollama_backend, "glm-5.3:cloud"), (ollama_backend, "gpt-oss:120b-cloud"),
                           (ollama_backend, ""), (OpenRouterBackend.__new__(OpenRouterBackend), MODEL)):
        assert REAL_OPEN_GATE(backend, model) is None


def test_missing_gate_or_failed_baseline_is_safe(monkeypatch):
    backend = OllamaBackend(default_model=MODEL)
    old = SimpleNamespace()  # ocean-resources before PB-26 (the Mac until it is pulled)
    monkeypatch.setattr("hub._services.ocean_stack_bridge.load_ocean_ram_distributor_module", lambda: old)
    assert REAL_OPEN_GATE(backend, MODEL) is None

    def broken():
        raise OSError("probe failed")
    made = []
    current = SimpleNamespace(sample_stress=broken,
                              RunCooldownGate=lambda baseline: made.append(baseline) or "gate")
    monkeypatch.setattr("hub._services.ocean_stack_bridge.load_ocean_ram_distributor_module", lambda: current)
    assert REAL_OPEN_GATE(backend, MODEL) == ("gate", broken)  # still a gate: minimum pause stays
    assert made == [None]


def test_real_ram_distributor_gate_through_the_worker_wait(run, ollama, monkeypatch):  # noqa: F811
    from hub._services.ocean_stack_bridge import load_ocean_ram_distributor_module
    mod = load_ocean_ram_distributor_module()
    if not hasattr(mod, "RunCooldownGate"):
        pytest.skip("ocean-resources without the PB-26 gate on this host")
    mib = 1024**2
    samples = iter([mod.StressSample(60.0, 300 * mib, 1, False),   # 300 MiB/min since the run end
                    mod.StressSample(90.0, 301 * mib, 1, False)])  # quiet again
    gate = mod.RunCooldownGate(baseline=mod.StressSample(0.0, 0, 1, False),
                               policy=mod.RunCooldownPolicy(min_pause_seconds=0, unload_after_seconds=0))
    assert run.gate(gate, sampler=lambda: next(samples)) is True
    assert ollama == [UNLOAD]
    assert "cooldown:swap" in run.updates[0]["current_activity"]
    assert "300 MiB/min" in run.updates[0]["current_activity"]
