# SPDX-License-Identifier: MIT
"""Side-effect-free local provider configuration shared by CLI and controller."""
from __future__ import annotations

import json
import os
from pathlib import Path


def effective_chat_backend(config):
    backend = dict(config.get("backend", {
        "type": "ollama", "base_url": "http://localhost:11434",
        "default_model": "qwen3.8:27b-mlx",
    }))
    kind = backend.get("type", "ollama")
    prefix = "OLLAMA" if kind == "ollama" else (
        "LM_STUDIO" if kind in {"lmstudio", "lm-studio", "lm_studio"} else None)
    # Apply only the selected provider's overrides. OLLAMA_URL must never
    # retarget an unrelated external provider or an LM Studio backend.
    if prefix:
        if os.environ.get(prefix + "_MODEL"):
            backend["default_model"] = os.environ[prefix + "_MODEL"]
        if os.environ.get(prefix + "_URL"):
            backend["base_url"] = os.environ[prefix + "_URL"]
    return backend


def local_backend_configs(config=None):
    """Resolve native provider presets; no credentials, sessions or DB initialized.

    A matching chat provider supplies its explicit settings. Provider-specific
    environment variables retain precedence; legacy defaults are fallback only.
    No URL can be supplied by a catalog request or model configuration write.
    """
    if config is None:
        path = Path.home() / ".config" / "bach" / "telegram_chat.json"
        config = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(config, dict):
        raise TypeError("Ungültige Chat-Anbieterkonfiguration")
    chat = config.get("backend", {})
    if not isinstance(chat, dict):
        raise TypeError("Ungültige Chat-Anbieterkonfiguration")
    result = {}
    for provider, url_env, model_env, default_url, default_model in (
        ("ollama", "OLLAMA_URL", "OLLAMA_MODEL", "http://localhost:11434", "qwen3.8:27b-mlx"),
        ("lmstudio", "LM_STUDIO_URL", "LM_STUDIO_MODEL", "http://localhost:1234/v1", "auto"),
    ):
        kind = chat.get("type", "ollama")
        if kind in {"lm-studio", "lm_studio"}:
            kind = "lmstudio"
        selected = chat if kind == provider else {}
        result[provider] = {
            "type": provider,
            "base_url": os.environ.get(url_env) or selected.get("base_url") or default_url,
            "default_model": os.environ.get(model_env) or selected.get("default_model") or default_model,
        }
        if provider == "lmstudio" and selected.get("api_key"):
            result[provider]["api_key"] = selected["api_key"]
    return result
