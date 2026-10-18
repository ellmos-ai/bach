# SPDX-License-Identifier: MIT
"""Local models and their agent bindings in the existing slots configuration.

The historical ``slots`` dictionary contains agent profiles, not models. This
module keeps those IDs and uses the same file lock, CAS and configuration file.
Reading a legacy file projects a migration without persisting or starting it.
Residency and measured capacity are deliberately not inferred from settings.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import platform
import re
import sys
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from . import slots_config as store

SCHEMA = "bach.model-sockets.v1"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}\Z")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,191}\Z")
_LOCAL_BACKENDS = frozenset({"ollama", "lmstudio"})
_PROFILE_MODEL_FIELDS = frozenset({"backend", "model", "model_fallbacks"})


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


def _profile_model_targets(profile):
    backend, model = profile.get("backend"), profile.get("model")
    if not isinstance(backend, str) or not isinstance(model, str):
        raise TypeError("Agentenprofil benötigt ein Primärmodell")
    if backend == "ollama" and model.lower().endswith(":cloud"):
        raise ValueError("Lokales Primärmodell darf kein Cloudmodell sein")
    if backend == "ollama-cloud" and not model.lower().endswith(":cloud"):
        raise ValueError("Ollama-Cloud-Primärmodell benötigt ein explizites :cloud-Modell")
    return [{"backend": backend, "model": model},
            *store._validated_model_fallback_profile(profile)]


def _reconcile_profile_bindings(config, agent_id):
    """Reconcile one profile's local primary/fallback bindings in memory only."""
    state = _validate_state(config.get("model_sockets"))
    if state["host_id"] != platform.node():
        raise RuntimeError("model_socket_host_mismatch")
    profile = _profiles(config).get(agent_id)
    if not isinstance(profile, dict):
        raise KeyError(agent_id)

    local_target_ids = []
    for target in _profile_model_targets(profile):
        if target["backend"] not in _LOCAL_BACKENDS:
            continue
        target_id = socket_id(target["backend"], target["model"], state["host_id"])
        offer = state["sockets"].get(target_id)
        if offer is None or offer["enabled"] is not True:
            raise ValueError("Lokales Modellangebot fehlt oder ist deaktiviert")
        local_target_ids.append(target_id)

    required = set(local_target_ids)
    for binding_id, binding in list(state["bindings"].items()):
        if binding["agent_id"] == agent_id and binding["socket_id"] not in required:
            del state["bindings"][binding_id]

    priority = ("background" if agent_id == "buddha_always_on"
                or profile.get("execution_kind") == "worker"
                or agent_id not in config["slots"] else "foreground")
    for target_id in local_target_ids:
        binding_id = _binding_id(agent_id, target_id)
        if binding_id not in state["bindings"]:
            state["bindings"][binding_id] = _new_binding(agent_id, target_id, priority)
    _validate_state(state)
    config["model_sockets"] = state
    return state


def _apply_profile_model_changes(config, agent_id, changes):
    if (type(changes) is not dict or not changes
            or set(changes) - _PROFILE_MODEL_FIELDS):
        raise ValueError("Ungültige Primär- oder Fallbackmodelländerung")
    profile = _profiles(config).get(agent_id)
    if not isinstance(profile, dict):
        raise KeyError(agent_id)
    profile.update(store._validated_core_edits(changes))
    _profile_model_targets(profile)
    _reconcile_profile_bindings(config, agent_id)
    return profile


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
            candidates = [effective]
            candidates.extend(store._validated_model_fallback_profile(effective))
            for candidate in candidates:
                backend, model = candidate.get("backend"), candidate.get("model")
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


def _live_runtime_evidence() -> dict[str, Any]:
    """Read live controller and host-owner evidence without starting a provider."""
    from .execution_target import local_execution_target, project_execution_target
    from .host_inference_gate import HostInferenceGate

    evidence = {
        "gate_available": False,
        "gate_active": False,
        "gate_target": None,
        "control_available": False,
        "targets": [],
        "agent_states": {},
    }
    try:
        gate = HostInferenceGate().status()
        evidence["gate_available"] = True
        evidence["gate_active"] = gate.get("active") is True
        model_target = gate.get("model_target")
        if evidence["gate_active"] and isinstance(model_target, dict):
            fields = {"socket_id", "binding_id", "agent_id", "backend", "model"}
            if set(model_target) == fields:
                evidence["gate_target"] = local_execution_target(
                    model_target["backend"], model_target["model"],
                    binding=model_target, source="host_inference_gate",
                )
    except Exception:  # noqa: BLE001 -- an unavailable owner source is explicit below
        pass

    module = sys.modules.get("hub._services.chat.telegram_chat")
    if module is None:
        try:
            module = importlib.import_module("hub._services.chat.telegram_chat")
        except Exception:  # noqa: BLE001 -- controller evidence remains unavailable
            module = None
    if module is None:
        return evidence

    try:
        system_reader = getattr(module, "_system_slots_snapshot", None)
        if callable(system_reader):
            snapshot = system_reader()
            agents = snapshot.get("agents", []) if isinstance(snapshot, dict) else []
            evidence["control_available"] = isinstance(agents, list)
            for agent in agents:
                if not isinstance(agent, dict) or not isinstance(agent.get("id"), str):
                    continue
                evidence["agent_states"][agent["id"]] = {
                    "running": agent.get("running"),
                    "target_seen": False,
                }
                target = project_execution_target(agent.get("resolved_execution_target"))
                if target is not None:
                    evidence["targets"].append(target)
                    evidence["agent_states"][agent["id"]]["target_seen"] = True

        worker_reader = getattr(module, "_worker_execution_snapshots", None)
        if callable(worker_reader):
            workers = worker_reader()
            if isinstance(workers, list):
                evidence["control_available"] = True
                for worker in workers:
                    if not isinstance(worker, dict) or not isinstance(worker.get("id"), str):
                        continue
                    evidence["agent_states"].setdefault(worker["id"], {
                        "running": worker.get("running"), "target_seen": False,
                    })
                    target = project_execution_target(worker.get("resolved_execution_target"))
                    if target is not None:
                        evidence["targets"].append(target)
                        evidence["agent_states"][worker["id"]]["target_seen"] = True
    except Exception:  # noqa: BLE001 -- malformed live data is not configuration proof
        evidence["control_available"] = False
    return evidence


def _target_matches(target: dict[str, Any], socket: dict[str, Any], binding: dict[str, Any] | None = None) -> bool:
    if target.get("locality") != "local":
        return False
    if target.get("socket_id") != socket.get("id"):
        return False
    if binding is not None and target.get("binding_id") != binding.get("id"):
        return False
    return target.get("provider") == socket.get("backend") and target.get("model") == socket.get("model")


def _with_runtime(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Overlay measured ownership and current target state on a config snapshot."""
    evidence = _live_runtime_evidence()
    gate_available = evidence["gate_available"]
    control_available = evidence["control_available"]
    gate_active = evidence["gate_active"]
    gate_target = evidence["gate_target"]
    targets = list(evidence["targets"])
    local_targets = [target for target in targets if target.get("locality") == "local"]
    source_available = gate_available or control_available
    target_map = {}
    for target in targets:
        for key in ("agent_id", "binding_id"):
            value = target.get(key)
            if value:
                target_map[(key, value)] = target

    result = {**snapshot, "sockets": [dict(socket) for socket in snapshot["sockets"]]}
    result["runtime_observed_at"] = datetime.now(timezone.utc).isoformat()
    result["resource_formula"] = "socket_share × relative_slot_share"
    if gate_available and control_available:
        result["runtime_source"] = "host_inference_gate+control_runtime"
    elif gate_available:
        result["runtime_source"] = "host_inference_gate"
    elif control_available:
        result["runtime_source"] = "control_runtime"
    else:
        result["runtime_source"] = "unavailable"

    if not source_available:
        result.update(runtime_verified=False, runtime_reason_code="source_unavailable")
        for socket in result["sockets"]:
            socket["resource_share_state"] = "source_unavailable"
            socket["slots"] = [dict(binding, resource_share_state="source_unavailable")
                                for binding in socket.get("slots", [])]
        return result

    if gate_active and gate_target is None:
        result.update(runtime_verified=True, runtime_reason_code="active_target_unavailable")
    elif gate_active and gate_target is not None:
        result.update(runtime_verified=True, runtime_reason_code="host_owner")
    elif local_targets:
        result.update(runtime_verified=True, runtime_reason_code="local_target_resource_unmeasured")
    else:
        result.update(runtime_verified=True, runtime_reason_code="live_idle")

    configured_gate_socket = bool(
        gate_target and any(_target_matches(gate_target, socket) for socket in result["sockets"])
    )
    for socket in result["sockets"]:
        projected_bindings = []
        socket_has_unknown = False
        socket_has_local_target = False
        socket_has_gate_owner = bool(gate_target and _target_matches(gate_target, socket))
        for binding in socket.get("slots", []):
            binding = dict(binding)
            binding_target = target_map.get(("binding_id", binding.get("id")))
            agent_target = target_map.get(("agent_id", binding.get("agent_id")))
            target = binding_target or agent_target
            if gate_active:
                if gate_target is None or not configured_gate_socket:
                    binding.update(running=None, resource_share=None,
                                   relative_slot_share=None,
                                   resource_share_state="active_target_unavailable")
                    socket_has_unknown = True
                elif socket_has_gate_owner and _target_matches(gate_target, socket, binding):
                    binding.update(running=True, resource_share=1.0,
                                   relative_slot_share=1.0,
                                   resource_share_state="measured_owner")
                elif socket_has_gate_owner:
                    binding.update(running=None, resource_share=None,
                                   relative_slot_share=None,
                                   resource_share_state="target_unavailable")
                    socket_has_unknown = True
                else:
                    binding.update(running=False, resource_share=0.0,
                                   relative_slot_share=0.0,
                                   resource_share_state="idle")
            elif target is not None and target.get("locality") == "local" and _target_matches(target, socket, binding):
                binding.update(running=True, resource_share=None,
                               relative_slot_share=None,
                               resource_share_state="source_unavailable")
                socket_has_local_target = True
            elif target is not None and target.get("locality") == "external" and target.get("agent_id") == binding.get("agent_id"):
                binding.update(running=False, resource_share=0.0,
                               relative_slot_share=0.0,
                               resource_share_state="external_target")
            else:
                agent_state = evidence["agent_states"].get(binding.get("agent_id"), {})
                if agent_state.get("running") is True:
                    binding.update(running=None, resource_share=None,
                                   relative_slot_share=None,
                                   resource_share_state="target_unavailable")
                    socket_has_unknown = True
                else:
                    binding.update(running=False, resource_share=0.0,
                                   relative_slot_share=0.0,
                                   resource_share_state="idle")
            projected_bindings.append(binding)

        if gate_active:
            if gate_target is None or not configured_gate_socket:
                socket_share, state = None, "active_target_unavailable"
            elif socket_has_gate_owner:
                socket_share = 1.0
                state = ("measured_owner" if any(
                    binding.get("resource_share_state") == "measured_owner"
                    for binding in projected_bindings) else "target_unavailable")
            else:
                socket_share, state = 0.0, "idle"
        elif socket_has_local_target or socket_has_unknown:
            socket_share, state = None, "source_unavailable" if socket_has_local_target else "target_unavailable"
        else:
            socket_share, state = 0.0, "idle"
        socket["resource_share"] = socket_share
        socket["resource_share_state"] = state
        socket["slots"] = projected_bindings
    return result


def model_sockets_snapshot(path: str | None = None, *, include_runtime: bool = False) -> dict[str, Any]:
    """Read model sockets; optionally overlay read-only live runtime evidence."""
    config, version = _read(path)
    snapshot = _snapshot(config, version)
    return _with_runtime(snapshot) if include_runtime else snapshot


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
def rebind_model_profile(expected_version: str, agent_id: str, changes: dict[str, Any], *,
                         path: str | None = None):
    """Atomically update a profile's primary/fallbacks and its local bindings."""
    config, current_version = _read(path)
    if expected_version != current_version:
        raise RuntimeError("configuration_version_conflict")
    if "model_sockets" not in config:
        raise RuntimeError("model_socket_registry_unavailable")
    from hub._services.skill_source_service import check_write_locks
    check_write_locks(store._resolve_path(path))
    _apply_profile_model_changes(config, agent_id, changes)
    version = store._core_configuration_version(config)
    store.save_slots_config(config, path)
    return _snapshot(config, version)


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
    if not target and not binding:
        profile = profiles[agent_id]
        fallbacks = store._validated_model_fallback_profile(profile)
        configured = any(item["backend"] == backend and item["model"] == model for item in fallbacks)
        if not configured or profile.get("enabled", True) is not True:
            raise RuntimeError("model_socket_binding_unavailable")
        # A post-migration fallback is projected only when that local target
        # is selected for a call. It is not persisted or pre-reserved.
        target = _new_socket(backend, model, state["host_id"])
        priority = ("background" if (agent_id == "buddha_always_on"
                    or profile.get("execution_kind") == "worker"
                    or agent_id not in config["slots"]) else "foreground")
        binding = _new_binding(agent_id, target_id, priority)
    if (not target or not binding or not target["enabled"] or not binding["enabled"]):
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

def model_fallbacks_for_profile(profile):
    """Read and validate the ordered chain against the native primary model."""
    return store._validated_model_fallback_profile(profile)


def _is_local_endpoint(backend):
    base_url = getattr(backend, "base_url", None)
    if not isinstance(base_url, str):
        return False
    try:
        parsed = urlsplit(base_url)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and parsed.hostname in {
        "localhost", "127.0.0.1", "::1", "0.0.0.0"
    }


def profile_backend_matches(profile_backend, backend, model=None):
    """Match provider identity; Ollama cloud is external even via localhost."""
    from hub._services.llm.model_backend import backend_identifier
    actual = backend_identifier(backend)
    local_endpoint = _is_local_endpoint(backend)
    cloud_model = isinstance(model, str) and model.lower().endswith(":cloud")
    if profile_backend == "ollama":
        return actual == "ollama" and local_endpoint and not cloud_model
    if profile_backend == "ollama-cloud":
        return actual == "ollama" and cloud_model
    if profile_backend == "lmstudio":
        return actual == "lmstudio" and local_endpoint
    return actual == profile_backend and not local_endpoint


def resolve_fallback_backend(target):
    """Use an already-loaded BACH resolver; importing the connector starts side effects."""
    normalized = store._validated_model_fallbacks([target])[0]
    if normalized["backend"] in {"claude", "codex"}:
        raise RuntimeError("fallback_cli_backend_unsupported")
    module = sys.modules.get("hub._services.chat.telegram_chat")
    factory = getattr(module, "_get_or_create_backend", None) if module is not None else None
    if not callable(factory):
        # This is unavailable runtime state, not an invalid caller type.
        raise RuntimeError("fallback_backend_resolver_unavailable")  # noqa: TRY004
    backend = factory(normalized["backend"], normalized["model"])
    from hub._services.llm.model_backend import (
        AnthropicBackend,
        HermesBackend,
        LMStudioBackend,
        OllamaBackend,
        OpenAIBackend,
        OpenRouterBackend,
        backend_identifier,
    )
    target_backend = normalized["backend"]
    local_endpoint = _is_local_endpoint(backend)
    identifier = backend_identifier(backend)
    if target_backend == "ollama":
        valid = identifier == "ollama" and isinstance(backend, OllamaBackend) and local_endpoint
    elif target_backend == "ollama-cloud":
        # Cloud inference may use BACH's local Ollama proxy. The explicit
        # :cloud model suffix, not the proxy URL, determines resource routing.
        valid = (identifier == "ollama" and isinstance(backend, OllamaBackend)
                 and normalized["model"].lower().endswith(":cloud"))
    elif target_backend == "lmstudio":
        valid = identifier == "lmstudio" and isinstance(backend, LMStudioBackend) and local_endpoint
    elif target_backend == "openrouter":
        valid = identifier == "openrouter" and isinstance(backend, OpenRouterBackend) and not local_endpoint
    elif target_backend == "hermes":
        valid = (identifier == "hermes" and isinstance(backend, HermesBackend)
                 and not isinstance(backend, OpenRouterBackend) and not local_endpoint)
    elif target_backend == "claude-api":
        valid = identifier == "claude-api" and isinstance(backend, AnthropicBackend) and not local_endpoint
    elif target_backend == "openai":
        valid = (identifier == "openai" and isinstance(backend, OpenAIBackend)
                 and not isinstance(backend, (LMStudioBackend, HermesBackend, OpenRouterBackend))
                 and not local_endpoint)
    else:
        valid = False
    if not valid or backend.get_default_model() != normalized["model"]:
        raise RuntimeError("fallback_backend_identity_mismatch")
    return backend
