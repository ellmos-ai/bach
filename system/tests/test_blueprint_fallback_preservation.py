"""Native blueprint -> Living profile preservation, with isolated stores only."""
import json
import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest
from hub._services import blueprint_service as service
from hub._services.chat import slots_config as slots


@pytest.fixture
def state(tmp_path, monkeypatch):
    from hub._services import skill_source_service

    path = tmp_path / "slots.json"
    slots.initialize_slots_config(str(path))

    def guard(target):
        if Path(target).resolve() != path.resolve():
            raise PermissionError("Only the isolated profile file is writable")

    monkeypatch.setattr(skill_source_service, "check_write_locks", guard)
    conn = sqlite3.connect(tmp_path / "blueprints.db")
    conn.row_factory = sqlite3.Row
    service.ensure_blueprint_schema(conn)
    bp = service.save_blueprint(conn, {
        "name": "fallback-test", "title": "Fallback-Prüfung", "kind": "agent",
        "persona_role": "recherche", "persona_prompt": "Prüfe den synthetischen Auftrag.",
        "skills": [], "contractus": {"turns": 3},
        "governance": {"tool_whitelist": ["read_file"]},
    })
    yield conn, path, bp
    conn.close()


def configure(state, execution, **kwargs):
    conn, path, bp = state
    return service.materialize_blueprint(
        conn, bp["id"], expected_version=kwargs.pop("expected_version", bp["version"]),
        execution=execution,
        configuration_version=kwargs.pop(
            "configuration_version", slots.core_system_agents_snapshot(str(path))["configuration_version"]),
        slots_path=str(path), **kwargs,
    )


def readback(state, result):
    _, path, _ = state
    snapshot = slots.core_system_agents_snapshot(str(path))
    assert snapshot["configuration_version"] == result["configuration_version"]
    profile = next(item for item in snapshot["agents"] if item["id"] == result["slot_id"])
    stored = json.loads(path.read_text(encoding="utf-8"))["slots"][result["slot_id"]]
    assert profile["model_fallbacks"] == stored["model_fallbacks"]
    assert result["worker_started"] is False and result["is_running"] is False
    return profile


@pytest.mark.parametrize("primary,chain", [
    ({"backend": "ollama", "model": "local-primary"}, [
        {"backend": "ollama-cloud", "model": "remote:cloud"},
        {"backend": "codex", "model": "subscription-model"}]),
    ({"backend": "ollama-cloud", "model": "primary:cloud"}, [
        {"backend": "ollama", "model": "local-fallback"},
        {"backend": "openrouter", "model": "provider/model"}]),
    ({"backend": "codex", "model": "subscription-primary"}, [
        {"backend": "claude", "model": "subscription-fallback"},
        {"backend": "ollama", "model": "local-fallback"}]),
    ({"backend": "openai", "model": "api-primary"}, [
        {"backend": "claude-api", "model": "api-fallback"},
        {"backend": "ollama", "model": "local-fallback"}]),
])
def test_native_materialization_and_readback_preserve_order(state, primary, chain):
    execution = {**primary, "model_fallbacks": chain}
    original = deepcopy(execution)
    result = configure(state, execution)
    profile = readback(state, result)
    assert {key: profile[key] for key in ("backend", "model", "model_fallbacks")} == execution
    assert slots.get_system_slot(result["slot_id"], str(state[1]))["model_fallbacks"] == chain
    worker = slots.system_worker_at_version(
        result["slot_id"], result["configuration_version"], path=str(state[1]))
    assert worker["model_fallbacks"] == chain
    assert execution == original


def test_omitted_new_chain_defaults_empty_and_existing_omission_retains_chain(state):
    primary = {"backend": "ollama", "model": "local-primary"}
    created = configure(state, primary)
    assert readback(state, created)["model_fallbacks"] == []
    chain = [{"backend": "codex", "model": "second"}, {"backend": "ollama", "model": "third"}]
    configured = configure(state, {**primary, "model_fallbacks": chain}, terminal_verified=True)
    assert readback(state, configured)["model_fallbacks"] == chain
    unchanged = configure(state, {"backend": "claude", "model": "new-primary"}, terminal_verified=True)
    assert readback(state, unchanged)["model_fallbacks"] == chain
    reordered = configure(state, {**primary, "model_fallbacks": list(reversed(chain))}, terminal_verified=True)
    assert readback(state, reordered)["model_fallbacks"] == list(reversed(chain))
    cleared = configure(state, {**primary, "model_fallbacks": []}, terminal_verified=True)
    assert readback(state, cleared)["model_fallbacks"] == []


@pytest.mark.parametrize("chain", [
    None, "model", {}, [{"backend": "ollama"}],
    [{"backend": "ollama", "model": "local", "token": "not-allowed"}],
    [{"backend": "unknown", "model": "model"}],
    [{"backend": "ollama", "model": "wrong:cloud"}],
    [{"backend": "ollama-cloud", "model": "missing-cloud-suffix"}],
    [{"backend": "ollama", "model": "local-primary"}],
    [{"backend": "codex", "model": "duplicate"}, {"backend": "codex", "model": "duplicate"}],
])
def test_invalid_chain_does_not_write_or_reconcile(state, monkeypatch, chain):
    conn, path, bp = state
    before = path.read_bytes()
    defaults = deepcopy(slots.DEFAULT_CORE_SLOTS)
    execution = {"backend": "ollama", "model": "local-primary", "model_fallbacks": chain}
    original = deepcopy(execution)

    def forbidden(*_args):
        pytest.fail("Invalid profile reached model binding reconciliation")

    monkeypatch.setattr(slots, "_reconcile_available_model_bindings", forbidden)
    with pytest.raises(ValueError):
        configure(state, execution)
    assert path.read_bytes() == before and slots.DEFAULT_CORE_SLOTS == defaults
    assert execution == original
    assert conn.execute("SELECT is_materialized FROM agent_blueprints WHERE id=?", (bp["id"],)).fetchone()[0] == 0


@pytest.mark.parametrize("primary,chain", [
    ({"backend": "ollama", "model": "second"}, [{"backend": "ollama", "model": "second"}]),
    ({"backend": "openrouter", "model": "openrouter/free"},
     [{"backend": "ollama-cloud", "model": "paid:cloud"}]),
])
def test_changed_primary_revalidates_omitted_existing_chain_without_mutation(state, monkeypatch, primary, chain):
    configured = configure(state, {"backend": "ollama", "model": "original", "model_fallbacks": chain})
    path = state[1]
    held_profile = slots.get_system_slot(configured["slot_id"], str(path))
    held_before = deepcopy(held_profile)
    before = path.read_bytes()

    def forbidden(*_args):
        pytest.fail("Invalid merged profile reached reconciliation")

    monkeypatch.setattr(slots, "_reconcile_available_model_bindings", forbidden)
    with pytest.raises(ValueError):
        configure(state, primary, terminal_verified=True)
    assert path.read_bytes() == before and held_profile == held_before
    assert readback(state, configured)["model_fallbacks"] == chain


def test_free_tier_rejects_paid_chain_and_explicit_empty_can_change_primary(state):
    before = state[1].read_bytes()
    with pytest.raises(ValueError, match="Free"):
        configure(state, {"backend": "openrouter", "model": "openrouter/free", "model_fallbacks": [
            {"backend": "openrouter", "model": "paid/model"}]})
    assert state[1].read_bytes() == before
    result = configure(state, {"backend": "ollama", "model": "original", "model_fallbacks": [
        {"backend": "ollama", "model": "second"}]})
    cleared = configure(state, {"backend": "ollama", "model": "second", "model_fallbacks": []}, terminal_verified=True)
    assert cleared["slot_id"] == result["slot_id"]
    assert readback(state, cleared)["model_fallbacks"] == []


def test_existing_cas_and_terminal_guards_preserve_configuration(state):
    execution = {"backend": "ollama", "model": "original", "model_fallbacks": [
        {"backend": "codex", "model": "fallback"}]}
    stale = slots.core_system_agents_snapshot(str(state[1]))["configuration_version"]
    first = configure(state, execution)
    before = state[1].read_bytes()
    for kwargs, message in [({"expected_version": 999}, "blueprint_version_conflict"),
                            ({"terminal_verified": True, "configuration_version": stale}, "configuration_version_conflict"),
                            ({}, "worker_terminal_state_required")]:
        with pytest.raises(RuntimeError, match=message):
            configure(state, {**execution, "model_fallbacks": []}, **kwargs)
        assert state[1].read_bytes() == before
    assert readback(state, first)["model_fallbacks"] == execution["model_fallbacks"]
