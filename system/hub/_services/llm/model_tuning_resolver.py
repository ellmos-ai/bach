# BACH Adapter: ocean-resources (model-tuning-catalog.v1)
# SPDX-License-Identifier: MIT
"""Unified model-specific `num_ctx` & hardware-/RAM-coupled tuning resolver for BACH.

Resolves local model tuning from one shared truth across `chat_runtime`,
`OllamaBackend`, `local_resource_reserve`, and `ollama_config.json`:

    explicit_num_ctx > slot_override > ollama_config > reserve_policy
        > ocean.model-tuning-catalog.v1 (RAM tier) > OLLAMA_NUM_CTX > safe_baseline (4096)

Zero hard runtime dependency on `ocean-resources`: if `ocean_resources.model_tuning_catalog`
is installed, it is used directly; otherwise a sibling/configured catalog JSON or the
embedded fallback defaults are used.
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_NUM_CTX = 4096
MIN_NUM_CTX = 512
MAX_NUM_CTX = 262_144
GIB = 1024**3
CATALOG_SCHEMA = "ocean.model-tuning-catalog.v1"

# Minimal embedded mirror of empirically verified / curated defaults for offline
# single-repo runs where `ocean-resources` is not installed next to BACH.
_EMBEDDED_CATALOG: dict[str, Any] = {
    "schema": CATALOG_SCHEMA,
    "schema_version": 1,
    "updated_at": "2026-11-27",
    "default_fallback": {
        "num_ctx_safe": 4096,
        "num_ctx_max": 8192,
        "kv_cache_type": "q8_0",
        "flash_attention": True,
        "think_level": "auto",
        "recommended_max_tool_rounds": 25,
        "handoff_percent": 75,
        "kv_headroom_gb": 1.0,
        "overhead_gb": 1.0,
    },
    "models": [
        {
            "model_id": "inkling-2-mini:latest",
            "aliases": ["inkling-2-mini"],
            "confidence_tier": "measured_live",
            "tool_calling_verified": True,
            "ram_tiers": [
                {"min_ram_gib": 0, "supported": False, "num_ctx_safe": 4096, "num_ctx_max": 4096, "recommended_max_tool_rounds": 15, "handoff_percent": 75, "kv_headroom_gb": 1.0, "overhead_gb": 1.5},
                {"min_ram_gib": 32, "supported": True, "num_ctx_safe": 16384, "num_ctx_max": 16384, "recommended_max_tool_rounds": 40, "handoff_percent": 75, "kv_headroom_gb": 1.5, "overhead_gb": 1.5},
                {"min_ram_gib": 48, "supported": True, "num_ctx_safe": 24576, "num_ctx_max": 32768, "recommended_max_tool_rounds": 45, "handoff_percent": 75, "kv_headroom_gb": 3.0, "overhead_gb": 2.0},
                {"min_ram_gib": 64, "supported": True, "num_ctx_safe": 32768, "num_ctx_max": 65536, "recommended_max_tool_rounds": 50, "handoff_percent": 75, "kv_headroom_gb": 4.0, "overhead_gb": 2.0},
                {"min_ram_gib": 128, "supported": True, "num_ctx_safe": 65536, "num_ctx_max": 131072, "recommended_max_tool_rounds": 60, "handoff_percent": 75, "kv_headroom_gb": 8.0, "overhead_gb": 3.0},
            ],
        },
        {
            "model_id": "qwen3.8:27b-mlx",
            "aliases": ["qwen3.8:27b", "qwen3.5:27b"],
            "confidence_tier": "measured_live",
            "tool_calling_verified": True,
            "ram_tiers": [
                {"min_ram_gib": 0, "supported": False, "num_ctx_safe": 4096, "num_ctx_max": 4096, "recommended_max_tool_rounds": 15, "handoff_percent": 75, "kv_headroom_gb": 1.0, "overhead_gb": 1.5},
                {"min_ram_gib": 24, "supported": True, "num_ctx_safe": 8192, "num_ctx_max": 12288, "recommended_max_tool_rounds": 25, "handoff_percent": 75, "kv_headroom_gb": 1.5, "overhead_gb": 1.5},
                {"min_ram_gib": 32, "supported": True, "num_ctx_safe": 16384, "num_ctx_max": 24576, "recommended_max_tool_rounds": 30, "handoff_percent": 75, "kv_headroom_gb": 2.0, "overhead_gb": 1.5},
                {"min_ram_gib": 64, "supported": True, "num_ctx_safe": 32768, "num_ctx_max": 65536, "recommended_max_tool_rounds": 45, "handoff_percent": 75, "kv_headroom_gb": 4.0, "overhead_gb": 2.0},
            ],
        },
        {
            "model_id": "gemma4:26b",
            "aliases": ["gemma4:26b-a4b", "gemma4:26b-mlx"],
            "confidence_tier": "curated",
            "tool_calling_verified": True,
            "ram_tiers": [
                {"min_ram_gib": 0, "supported": False, "num_ctx_safe": 4096, "num_ctx_max": 4096, "recommended_max_tool_rounds": 15, "handoff_percent": 75, "kv_headroom_gb": 1.0, "overhead_gb": 1.5},
                {"min_ram_gib": 24, "supported": True, "num_ctx_safe": 8192, "num_ctx_max": 16384, "recommended_max_tool_rounds": 30, "handoff_percent": 75, "kv_headroom_gb": 1.5, "overhead_gb": 1.5},
                {"min_ram_gib": 32, "supported": True, "num_ctx_safe": 16384, "num_ctx_max": 24576, "recommended_max_tool_rounds": 40, "handoff_percent": 75, "kv_headroom_gb": 2.0, "overhead_gb": 1.5},
                {"min_ram_gib": 64, "supported": True, "num_ctx_safe": 32768, "num_ctx_max": 65536, "recommended_max_tool_rounds": 50, "handoff_percent": 75, "kv_headroom_gb": 4.0, "overhead_gb": 2.0},
            ],
        },
        {
            "model_id": "gemma4:12b",
            "aliases": ["gemma4:e4b", "gemma4:latest"],
            "confidence_tier": "curated",
            "tool_calling_verified": True,
            "ram_tiers": [
                {"min_ram_gib": 0, "supported": False, "num_ctx_safe": 4096, "num_ctx_max": 4096, "recommended_max_tool_rounds": 15, "handoff_percent": 75, "kv_headroom_gb": 1.0, "overhead_gb": 1.0},
                {"min_ram_gib": 16, "supported": True, "num_ctx_safe": 16384, "num_ctx_max": 24576, "recommended_max_tool_rounds": 30, "handoff_percent": 75, "kv_headroom_gb": 1.5, "overhead_gb": 1.0},
                {"min_ram_gib": 32, "supported": True, "num_ctx_safe": 32768, "num_ctx_max": 65536, "recommended_max_tool_rounds": 40, "handoff_percent": 75, "kv_headroom_gb": 2.5, "overhead_gb": 1.5},
            ],
        },
        {
            "model_id": "qwen3:8b",
            "aliases": ["qwen3:8b-latest"],
            "confidence_tier": "curated",
            "tool_calling_verified": True,
            "ram_tiers": [
                {"min_ram_gib": 8, "supported": True, "num_ctx_safe": 8192, "num_ctx_max": 12288, "recommended_max_tool_rounds": 20, "handoff_percent": 75, "kv_headroom_gb": 0.75, "overhead_gb": 0.75},
                {"min_ram_gib": 16, "supported": True, "num_ctx_safe": 16384, "num_ctx_max": 32768, "recommended_max_tool_rounds": 30, "handoff_percent": 75, "kv_headroom_gb": 1.5, "overhead_gb": 1.0},
                {"min_ram_gib": 32, "supported": True, "num_ctx_safe": 32768, "num_ctx_max": 40960, "recommended_max_tool_rounds": 40, "handoff_percent": 75, "kv_headroom_gb": 2.0, "overhead_gb": 1.0},
            ],
        },
        {
            "model_id": "qwen3:4b",
            "aliases": ["qwen3:4b-latest"],
            "confidence_tier": "curated",
            "tool_calling_verified": True,
            "ram_tiers": [
                {"min_ram_gib": 8, "supported": True, "num_ctx_safe": 8192, "num_ctx_max": 16384, "recommended_max_tool_rounds": 20, "handoff_percent": 75, "kv_headroom_gb": 0.5, "overhead_gb": 0.5},
                {"min_ram_gib": 16, "supported": True, "num_ctx_safe": 16384, "num_ctx_max": 32768, "recommended_max_tool_rounds": 30, "handoff_percent": 75, "kv_headroom_gb": 1.0, "overhead_gb": 0.75},
            ],
        },
    ],
}


def validate_num_ctx(raw: Any) -> int:
    """Validate an Ollama num_ctx value with the canonical BACH range and errors."""
    if type(raw) is bool:
        raise ValueError("Ollama num_ctx muss eine ganze Zahl sein")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Ollama num_ctx muss eine ganze Zahl sein") from exc
    if not MIN_NUM_CTX <= value <= MAX_NUM_CTX:
        raise ValueError("Ollama num_ctx muss zwischen 512 und 262144 liegen")
    return value


def detect_host_ram_gib() -> float:
    """Return total physical host memory in GiB using stdlib / psutil."""
    with contextlib.suppress(ImportError, OSError, ValueError, AttributeError):
        import psutil

        total = int(psutil.virtual_memory().total)
        if total > 0:
            return float(total) / GIB
    with contextlib.suppress(OSError, ValueError, subprocess.SubprocessError):
        out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True, timeout=2).strip()
        total = int(out)
        if total > 0:
            return float(total) / GIB
    return 16.0


def _load_catalog(catalog_path: Path | None = None) -> tuple[dict[str, Any], str]:
    if catalog_path is not None:
        path = Path(catalog_path).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("schema") == CATALOG_SCHEMA:
            return data, str(path)
        raise ValueError(f"Ungueltiger Modell-Katalog: {path}")

    with contextlib.suppress(ImportError, OSError, ValueError):
        from ocean_resources.model_tuning_catalog import (  # type: ignore[import-not-found]
            DEFAULT_CATALOG_PATH,
            load_model_tuning_catalog,
        )

        return load_model_tuning_catalog(), str(DEFAULT_CATALOG_PATH)

    env_path = os.environ.get("OCEAN_MODEL_TUNING_CATALOG")
    if env_path:
        p = Path(env_path).expanduser().resolve()
        if p.is_file():
            with contextlib.suppress(OSError, ValueError):
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("schema") == CATALOG_SCHEMA:
                    return data, str(p)

    return _EMBEDDED_CATALOG, "embedded"


def _find_model_entry(catalog: dict[str, Any], model: str) -> dict[str, Any] | None:
    target = str(model or "").strip().lower()
    if not target:
        return None
    bare = target.split(":", 1)[0]
    with_latest = target if ":" in target else f"{target}:latest"
    for entry in catalog.get("models") or []:
        names = {str(entry.get("model_id") or "").strip().lower()}
        for alias in entry.get("aliases") or []:
            names.add(str(alias).strip().lower())
        if target in names or with_latest in names or bare in names:
            return entry
    return None


def _select_ram_tier(tiers: list[dict[str, Any]], ram_gib: float) -> dict[str, Any]:
    ordered = sorted(tiers, key=lambda item: float(item.get("min_ram_gib", 0)))
    chosen = ordered[0]
    for tier in ordered:
        if ram_gib + 0.5 >= float(tier.get("min_ram_gib", 0)):
            chosen = tier
    return chosen


def _load_ollama_config_entry(model: str, ollama_config_path: Path | None) -> dict[str, Any] | None:
    if ollama_config_path is None or not ollama_config_path.is_file():
        return None
    try:
        raw = json.loads(ollama_config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    models = raw.get("models") if isinstance(raw, dict) else None
    if not isinstance(models, dict):
        return None
    if isinstance(models.get(model), dict):
        return models[model]
    alt = model if ":" in model else f"{model}:latest"
    if isinstance(models.get(alt), dict):
        return models[alt]
    return None


def resolve_effective_num_ctx(
    model: str,
    *,
    explicit_num_ctx: int | None = None,
    slot_override: dict[str, Any] | None = None,
    ollama_config_path: Path | None = None,
    reserve_policy: dict[str, Any] | None = None,
    host_ram_gib: float | None = None,
    env_num_ctx: str | int | None = None,
    catalog_path: Path | None = None,
) -> dict[str, Any]:
    """Resolve effective `num_ctx` and tuning metadata from the unified precedence chain."""
    ram_gib = float(host_ram_gib) if host_ram_gib is not None else detect_host_ram_gib()
    catalog, catalog_origin = _load_catalog(catalog_path)
    fallback = catalog.get("default_fallback") or {}
    entry = _find_model_entry(catalog, model)

    if entry is not None:
        tier = _select_ram_tier(entry["ram_tiers"], ram_gib)
        num_ctx_safe = validate_num_ctx(tier.get("num_ctx_safe", DEFAULT_NUM_CTX))
        num_ctx_max = validate_num_ctx(tier.get("num_ctx_max", num_ctx_safe))
        recommended_rounds = int(tier.get("recommended_max_tool_rounds", 25))
        handoff_percent = int(tier.get("handoff_percent", 75))
        supported = bool(tier.get("supported", True))
        matched_tier = int(tier.get("min_ram_gib", 0))
        base_confidence = str(entry.get("confidence_tier", "curated"))
        kv_headroom_bytes = round(float(tier.get("kv_headroom_gb", 1.5)) * GIB)
        overhead_bytes = round(float(tier.get("overhead_gb", 1.5)) * GIB)
    else:
        num_ctx_safe = validate_num_ctx(fallback.get("num_ctx_safe", DEFAULT_NUM_CTX))
        num_ctx_max = validate_num_ctx(fallback.get("num_ctx_max", 8192))
        recommended_rounds = int(fallback.get("recommended_max_tool_rounds", 25))
        handoff_percent = int(fallback.get("handoff_percent", 75))
        supported = True
        matched_tier = None
        base_confidence = "fallback"
        kv_headroom_bytes = round(float(fallback.get("kv_headroom_gb", 1.0)) * GIB)
        overhead_bytes = round(float(fallback.get("overhead_gb", 1.0)) * GIB)

    model_cfg = _load_ollama_config_entry(model, ollama_config_path)
    reserve_models = (reserve_policy or {}).get("models") if isinstance(reserve_policy, dict) else None
    reserve_entry = reserve_models.get(model) if isinstance(reserve_models, dict) else None

    confidence = base_confidence
    if explicit_num_ctx is not None:
        num_ctx = validate_num_ctx(explicit_num_ctx)
        source = "explicit"
        confidence = "manual_override"
    elif isinstance(slot_override, dict) and slot_override.get("num_ctx") is not None:
        num_ctx = validate_num_ctx(slot_override["num_ctx"])
        source = "slot_override"
        confidence = "manual_override"
    elif isinstance(model_cfg, dict) and model_cfg.get("num_ctx") is not None:
        num_ctx = validate_num_ctx(model_cfg["num_ctx"])
        source = "model_config"
        confidence = "manual_override"
    elif isinstance(reserve_entry, dict) and reserve_entry.get("num_ctx") is not None:
        num_ctx = validate_num_ctx(reserve_entry["num_ctx"])
        source = "reserve_policy"
    elif entry is not None:
        num_ctx = num_ctx_safe
        source = "catalog_default"
    else:
        raw_env = (
            env_num_ctx
            if env_num_ctx is not None
            else (os.environ.get("OLLAMA_NUM_CTX") or os.environ.get("OLLAMA_NUM_CFG"))
        )
        if raw_env is not None and str(raw_env).strip():
            num_ctx = validate_num_ctx(raw_env)
            source = "env_fallback"
        else:
            num_ctx = num_ctx_safe
            source = "safe_baseline"

    return {
        "schema": "bach.resolved-model-tuning.v1",
        "model": model,
        "catalog_origin": catalog_origin,
        "host_ram_gib": round(ram_gib, 2),
        "matched_tier_min_ram_gib": matched_tier,
        "supported_on_host": supported,
        "num_ctx": num_ctx,
        "num_ctx_source": source,
        "num_ctx_safe": num_ctx_safe,
        "num_ctx_max": num_ctx_max,
        "recommended_max_tool_rounds": recommended_rounds,
        "handoff_percent": handoff_percent,
        "kv_headroom_bytes": kv_headroom_bytes,
        "overhead_bytes": overhead_bytes,
        "confidence_tier": confidence,
    }


def apply_model_num_ctx_change(
    model: str,
    num_ctx: int,
    *,
    ollama_config_path: Path,
    reserve_policy_path: Path | None = None,
    num_ctx_recommended: int | None = None,
    backend: Any | None = None,
    unload_running_model: bool = False,
) -> dict[str, Any]:
    """Synchronize a model's `num_ctx` across `ollama_config.json`, optional reserve policy, and Ollama runner."""
    validated_ctx = validate_num_ctx(num_ctx)
    validated_rec = validate_num_ctx(num_ctx_recommended) if num_ctx_recommended is not None else None

    # 1. Update ollama_config.json
    cfg: dict[str, Any] = {}
    if ollama_config_path.is_file():
        try:
            loaded = json.loads(ollama_config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cfg = loaded
        except (OSError, ValueError):
            cfg = {}
    models = cfg.setdefault("models", {})
    entry = models.setdefault(model, {})
    entry["num_ctx"] = validated_ctx
    if validated_rec is not None:
        entry["num_ctx_recommended"] = validated_rec
    ollama_config_path.parent.mkdir(parents=True, exist_ok=True)
    ollama_config_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 2. Keep existing resource-reserve.json in lockstep (prevents model_budget_conflict)
    reserve_synced = False
    if reserve_policy_path is not None and reserve_policy_path.is_file():
        try:
            raw_reserve = json.loads(reserve_policy_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw_reserve = None
        if isinstance(raw_reserve, dict) and isinstance(raw_reserve.get("models"), dict):
            r_entry = raw_reserve["models"].get(model)
            if isinstance(r_entry, dict) and r_entry.get("num_ctx") != validated_ctx:
                r_entry["num_ctx"] = validated_ctx
                reserve_policy_path.write_text(
                    json.dumps(raw_reserve, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                reserve_synced = True

    # 3. Optional Ollama MLX runner unload so --ctx-size takes effect on next load
    unloaded = False
    if unload_running_model and backend is not None and hasattr(backend, "unload"):
        try:
            unloaded = bool(backend.unload(model))
        except (OSError, RuntimeError, ValueError, TypeError):
            unloaded = False

    return {
        "model": model,
        "num_ctx": validated_ctx,
        "num_ctx_recommended": validated_rec,
        "ollama_config_path": str(ollama_config_path),
        "reserve_policy_synced": reserve_synced,
        "runner_unloaded": unloaded,
    }
