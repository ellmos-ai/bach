# SPDX-License-Identifier: MIT
"""Local models and their agent bindings in the existing slots configuration.

The historical ``slots`` dictionary contains agent profiles, not models. This
module keeps those IDs and uses the same file lock, CAS and configuration file.
Reading a legacy file projects a migration without persisting or starting it.
Residency and measured capacity are deliberately not inferred from settings.
"""
from __future__ import annotations

import hashlib
import json
import platform
import re
from typing import Any

from . import slots_config as store

SCHEMA = "bach.model-sockets.v1"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}\Z")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,191}\Z")
_LOCAL_BACKENDS = frozenset({"ollama", "lmstudio"})


def _text(value, pattern):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError("Ungültige Modell- oder Agentenidentität")
    return value


def _int(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Ungültige Slotkapazität")
    return value


def socket_id(backend: str, model: str, host_id: str) -> str:
    if not isinstance(backend, str) or backend not in _LOCAL_BACKENDS:
        raise ValueError("Externe Anbieter haben keinen lokalen Modellsteckplatz")
    _text(model, _MODEL)
    _text(host_id, _IDENTIFIER)
    if model.lower().endswith(":cloud"):
        raise ValueError("Cloudinferenz hat keinen lokalen Modellsteckplatz")
    encoded = json.dumps([backend, model, host_id], separators=(",", ":"))
    return "model-" + hashlib.sha256(encoded.encode()).hexdigest()[:24]


def _binding_id(agent_id: str, target_id: str) -> str:
    encoded = json.dumps([agent_id, target_id], separators=(",", ":"))
    return "binding-" + hashlib.sha256(encoded.encode()).hexdigest()[:24]


def _profiles(config):
    result = dict(config["slots"])
    for worker in config.get("dynamic_workers", []):
        if not isinstance(worker, dict):
            raise ValueError("Ungültige Agentenkonfiguration")
        key = worker.get("id")
        if key in result:
            raise ValueError("Agenten-ID ist nicht eindeutig")
        _text(key, _IDENTIFIER)
        result[key] = worker
    return result


def _new_socket(backend, model, host_id):
    key = socket_id(backend, model, host_id)
    return {"id": key, "backend": backend, "model": model, "host_id": host_id,
            "enabled": True, "max_active_slots": 1, "residency_policy": "exclusive"}


def _new_binding(agent_id, target_id, priority="background"):
    _text(agent_id, _IDENTIFIER)
    key = _binding_id(agent_id, target_id)
    return {"id": key, "agent_id": agent_id, "socket_id": target_id,
            "enabled": True, "priority": priority, "context_tokens": None}


def _legacy_projection(config, host_id):
    state = {"schema": SCHEMA, "host_id": host_id, "sockets": {}, "bindings": {}}
    for agent_id, profile in _profiles(config).items():
        targets = [profile]
        if agent_id == "buddha_connector":
            for provider in ("telegram", "whatsapp", "signal"):
                targets.append(store.connector_slot_for_provider(profile, provider))
        priority = "background" if (agent_id == "buddha_always_on" or
                    profile.get("execution_kind") == "worker" or
                    agent_id not in config["slots"]) else "foreground"
        for effective in targets:
            backend, model = effective.get("backend"), effective.get("model")
            if backend not in _LOCAL_BACKENDS or str(model).lower().endswith(":cloud"):
                continue
            target = _new_socket(backend, model, host_id)
            state["sockets"][target["id"]] = target
            binding = _new_binding(agent_id, target["id"], priority)
            state["bindings"][binding["id"]] = binding
    return state


def _validate_state(state):
    if (not isinstance(state, dict) or set(state) != {"schema", "host_id", "sockets", "bindings"}
            or state["schema"] != SCHEMA):
        raise ValueError("Ungültiges Modellsteckplatzschema")
    _text(state["host_id"], _IDENTIFIER)
    sockets, bindings = state["sockets"], state["bindings"]
    if not isinstance(sockets, dict) or not isinstance(bindings, dict):
        raise ValueError("Ungültiger Modellsteckplatzkatalog")
    for key, target in sockets.items():
        fields = {"id", "backend", "model", "host_id", "enabled", "max_active_slots", "residency_policy"}
        if not isinstance(target, dict) or set(target) != fields:
            raise ValueError("Ungültiger Modellsteckplatz")
        if (key != target["id"] or key != socket_id(target["backend"], target["model"], target["host_id"])
                or target["host_id"] != state["host_id"] or type(target["enabled"]) is not bool
                or target["residency_policy"] not in {"exclusive", "shared"}):
            raise ValueError("Ungültige Modellsteckplatzidentität")
        _int(target["max_active_slots"], 1, 1000)
    for key, binding in bindings.items():
        fields = {"id", "agent_id", "socket_id", "enabled", "priority", "context_tokens"}
        if not isinstance(binding, dict) or set(binding) != fields:
            raise ValueError("Ungültige Agentenslotbindung")
        _text(binding["agent_id"], _IDENTIFIER)
        if (key != binding["id"] or key != _binding_id(binding["agent_id"], binding["socket_id"])
                or binding["socket_id"] not in sockets or type(binding["enabled"]) is not bool
                or binding["priority"] not in {"foreground", "background"}):
            raise ValueError("Ungültige Agentenslotidentität")
        if binding["context_tokens"] is not None:
            _int(binding["context_tokens"], 1, 1_048_576)
    return state


def _read(path=None):
    raw = store._resolve_path(path).read_bytes()
    snapshot = store._core_snapshot_from_bytes(raw)
    config = json.loads(raw.decode("utf-8"))
    format_version = config.get("version", 1)
    if type(format_version) is not int or format_version < 1:
        raise ValueError("Ungültige Konfigurationsformatversion")
    if format_version >= 4 and "model_sockets" not in config:
        raise ValueError("Modellsteckplatzregistry fehlt nach Migration")
    return config, snapshot["configuration_version"]


def _snapshot(config, version):
    projected = "model_sockets" not in config
    state = (_legacy_projection(config, platform.node()) if projected
             else _validate_state(config["model_sockets"]))
    profiles = _profiles(config)
    targets = []
    for target in state["sockets"].values():
        bindings = []
        for binding in state["bindings"].values():
            if binding["socket_id"] != target["id"]:
                continue
            profile = profiles.get(binding["agent_id"])
            bindings.append({**binding, "name": profile.get("name", binding["agent_id"]) if profile else binding["agent_id"],
                             "orphaned": profile is None, "running": None, "resource_share": None})
        targets.append({**target, "slots": bindings, "residency": "unknown",
                        "weight_bytes": None, "resource_share": None,
                        "effective_max_active_slots": 1, "capacity_verified": False})
    bound_agents = {item["agent_id"] for item in state["bindings"].values()}
    return {"schema": SCHEMA, "configuration_version": version,
            "migration_required": projected, "host_id": state["host_id"],
            "source": "legacy_projection" if projected else "canonical_slots_config",
            "runtime_verified": False, "sockets": targets,
            "unbound_agent_ids": sorted(set(profiles) - bound_agents),
            "host_inference_limit": 1}


def model_sockets_snapshot(path: str | None = None) -> dict[str, Any]:
    """Configuration only: no network, initialization, occupancy or resource claims."""
    config, version = _read(path)
    return _snapshot(config, version)


def _mutate(expected_version, operation, path):
    config, version = _read(path)
    if expected_version != version:
        raise RuntimeError("configuration_version_conflict")
    from hub._services.skill_source_service import check_write_locks
    check_write_locks(store._resolve_path(path))
    operation(config)
    _validate_state(config["model_sockets"])
    store.save_slots_config(config, path)
    return model_sockets_snapshot(path)


@store._serialized_mutation
def migrate_model_sockets(expected_version: str, *, path: str | None = None):
    """Explicit in-place migration, preserving profiles, progress and unknown fields."""
    def migrate(config):
        if "model_sockets" in config:
            raise ValueError("Modellsteckplätze sind bereits migriert")
        config["model_sockets"] = _legacy_projection(config, platform.node())
        config["version"] = max(config.get("version", 3), 4)
    return _mutate(expected_version, migrate, path)


@store._serialized_mutation
def configure_model_socket(expected_version: str, changes: dict[str, Any], *, path: str | None = None):
    """Register or edit an offered local target; never load it or launch an agent."""
    if not isinstance(changes, dict) or set(changes) - {"backend", "model", "enabled", "max_active_slots", "residency_policy"}:
        raise ValueError("Ungültige Steckplatzänderung")
    def configure(config):
        state = _validate_state(config.get("model_sockets"))
        target = _new_socket(changes.get("backend"), changes.get("model"), state["host_id"])
        previous = state["sockets"].get(target["id"], target)
        state["sockets"][target["id"]] = {**previous, **changes}
    return _mutate(expected_version, configure, path)


@store._serialized_mutation
def bind_model_agent(expected_version: str, agent_id: str, target_id: str, changes=None, *, path: str | None = None):
    """One stable binding per agent/model; fallback bindings do not acquire resources."""
    changes = {} if changes is None else changes
    if not isinstance(changes, dict) or set(changes) - {"enabled", "priority", "context_tokens"}:
        raise ValueError("Ungültige Agentenslotänderung")
    def bind(config):
        state = _validate_state(config.get("model_sockets"))
        if agent_id not in _profiles(config) or target_id not in state["sockets"]:
            raise ValueError("Agent oder Modellsteckplatz fehlt")
        binding = _new_binding(agent_id, target_id)
        previous = state["bindings"].get(binding["id"], binding)
        state["bindings"][binding["id"]] = {**previous, **changes}
    return _mutate(expected_version, bind, path)


@store._serialized_mutation
def remove_model_binding(expected_version: str, binding_id: str, *, path: str | None = None):
    def remove(config):
        state = _validate_state(config.get("model_sockets"))
        if binding_id not in state["bindings"]:
            raise KeyError("Agentenslotbindung fehlt")
        del state["bindings"][binding_id]
    return _mutate(expected_version, remove, path)


def require_model_binding(agent_id: str | None, backend: str, model: str, *, path: str | None = None):
    """Read a local call's binding from one file image, never from cached UI state.

    Caller establishes the actual local inference target first. A missing legacy
    migration is explicit; a present invalid state or missing binding denies.
    """
    config, version = _read(path)
    return _binding_from_config(config, version, agent_id, backend, model)


def _binding_from_config(config, version, agent_id, backend, model):
    if "model_sockets" not in config:
        return None
    state = _validate_state(config["model_sockets"])
    if state["host_id"] != platform.node():
        raise RuntimeError("model_socket_host_mismatch")
    profiles = _profiles(config)
    if agent_id not in profiles:
        raise RuntimeError("model_socket_agent_unbound")
    target_id = socket_id(backend, model, state["host_id"])
    target = state["sockets"].get(target_id)
    binding = state["bindings"].get(_binding_id(agent_id, target_id))
    if not target or not binding or not target["enabled"] or not binding["enabled"]:
        raise RuntimeError("model_socket_binding_unavailable")
    return {"socket_id": target_id, "binding_id": binding["id"], "agent_id": agent_id,
            "backend": backend, "model": model, "configuration_version": version,
            "priority": binding["priority"], "context_tokens": binding["context_tokens"]}


def configured_agent_for_chat(chat_id: str, *, path: str | None = None) -> str | None:
    """Resolve only persisted, unambiguous aliases; no guessed connector prefixes."""
    config, _ = _read(path)
    return _agent_for_chat(config, chat_id)


def _agent_for_chat(config, chat_id):
    matches = [key for key, value in _profiles(config).items()
               if key == chat_id or value.get("chat_id") == chat_id]
    if len(matches) > 1:
        raise RuntimeError("model_socket_agent_ambiguous")
    return matches[0] if matches else None


def model_binding_for_call(chat_id, backend, model, *, agent_id=None, path=None, require_config=False):
    """Optional legacy seam; migrated state is strict, including unknown aliases."""
    try:
        config, version = _read(path)
    except FileNotFoundError:
        if require_config:
            raise RuntimeError("model_socket_config_unavailable") from None
        # Standalone ChatRuntime also works without BACH's native registry.
        # Bound BACH workers additionally validate their canonical profile.
        return None
    if "model_sockets" not in config:
        if require_config:
            # Native dispatch requires the schema, even if a damaged or
            # downgraded file advertises an old outer format version.
            raise RuntimeError("model_socket_registry_unavailable")
        return None
    _validate_state(config["model_sockets"])
    if agent_id is None:
        agent_id = _agent_for_chat(config, chat_id)
    return _binding_from_config(config, version, agent_id, backend, model)
