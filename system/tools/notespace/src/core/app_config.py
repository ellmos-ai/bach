#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
App Config - Local application-level settings for NoteSpaceLLM
===============================================================

Stores global LLM defaults (provider, model, URL, API key) in a local
config file (~/.notespacellm/config.json). API keys are stored here
instead of in project files to prevent accidental sharing.

Includes a profile system for quick switching between connection setups.
"""

import os
import json
from pathlib import Path
from typing import Optional, Dict, List

# Config lives outside synced project folders.
# BACH On-Board: Ist BACH_NOTESPACE_HOME gesetzt, liegt der gesamte Zustand
# isoliert unter dem BACH-Datenpfad (data/notespace/) -- getrennt von der
# eigenstaendigen internen Quellversion (~/.notespacellm/).
_NS_HOME = os.environ.get("BACH_NOTESPACE_HOME")
CONFIG_DIR = (Path(_NS_HOME) / "config") if _NS_HOME else (Path.home() / ".notespacellm")
CONFIG_FILE = CONFIG_DIR / "config.json"


class AppConfig:
    """Persistent app-level configuration stored locally."""

    DEFAULTS = {
        "llm_provider": "ollama",
        "llm_model": "llama3",
        "ollama_base_url": "http://localhost:11434",
        "ollama_api_key": "",
        "embedding_model": "nomic-embed-text",
        "claude_code_mode": "api",
        "active_profile": "",
        "profiles": {},
    }

    # Vordefinierte Profile
    BUILTIN_PROFILES = {
        "Lokal (Standard)": {
            "llm_provider": "ollama",
            "llm_model": "llama3",
            "ollama_base_url": "http://localhost:11434",
            "ollama_api_key": "",
            "embedding_model": "nomic-embed-text",
        },
    }

    def __init__(self):
        self._data: dict = dict(self.DEFAULTS)
        self._load()

    def _load(self):
        """Load config from disk."""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    stored = json.load(f)
                # Merge with defaults (new keys get default values)
                for key, default in self.DEFAULTS.items():
                    self._data[key] = stored.get(key, default)
            except Exception:
                pass

    def save(self):
        """Write config to disk."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    # --- Properties ---

    @property
    def llm_provider(self) -> str:
        return self._data["llm_provider"]

    @llm_provider.setter
    def llm_provider(self, value: str):
        self._data["llm_provider"] = value

    @property
    def llm_model(self) -> str:
        return self._data["llm_model"]

    @llm_model.setter
    def llm_model(self, value: str):
        self._data["llm_model"] = value

    @property
    def ollama_base_url(self) -> str:
        return self._data["ollama_base_url"]

    @ollama_base_url.setter
    def ollama_base_url(self, value: str):
        self._data["ollama_base_url"] = value

    @property
    def ollama_api_key(self) -> str:
        return self._data["ollama_api_key"]

    @ollama_api_key.setter
    def ollama_api_key(self, value: str):
        self._data["ollama_api_key"] = value

    @property
    def embedding_model(self) -> str:
        return self._data.get("embedding_model", "nomic-embed-text")

    @embedding_model.setter
    def embedding_model(self, value: str):
        self._data["embedding_model"] = value

    @property
    def claude_code_mode(self) -> str:
        return self._data.get("claude_code_mode", "api")

    @claude_code_mode.setter
    def claude_code_mode(self, value: str):
        self._data["claude_code_mode"] = value

    # --- Profile System ---

    @property
    def profiles(self) -> Dict[str, dict]:
        """Alle gespeicherten Profile (Built-in + User)."""
        all_profiles = dict(self.BUILTIN_PROFILES)
        all_profiles.update(self._data.get("profiles", {}))
        return all_profiles

    @property
    def active_profile(self) -> str:
        return self._data.get("active_profile", "")

    @active_profile.setter
    def active_profile(self, value: str):
        self._data["active_profile"] = value

    def save_profile(self, name: str) -> None:
        """Speichert aktuelle Einstellungen als Profil."""
        profile = {
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "ollama_base_url": self.ollama_base_url,
            "ollama_api_key": self.ollama_api_key,
            "embedding_model": self.embedding_model,
        }
        if "profiles" not in self._data:
            self._data["profiles"] = {}
        self._data["profiles"][name] = profile
        self._data["active_profile"] = name
        self.save()

    def load_profile(self, name: str) -> bool:
        """Laedt ein Profil und setzt alle Einstellungen."""
        all_profiles = self.profiles
        if name not in all_profiles:
            return False

        profile = all_profiles[name]
        self._data["llm_provider"] = profile.get("llm_provider", self.DEFAULTS["llm_provider"])
        self._data["llm_model"] = profile.get("llm_model", self.DEFAULTS["llm_model"])
        self._data["ollama_base_url"] = profile.get("ollama_base_url", self.DEFAULTS["ollama_base_url"])
        self._data["ollama_api_key"] = profile.get("ollama_api_key", self.DEFAULTS["ollama_api_key"])
        self._data["embedding_model"] = profile.get("embedding_model", self.DEFAULTS["embedding_model"])
        self._data["active_profile"] = name
        self.save()
        return True

    def delete_profile(self, name: str) -> bool:
        """Löscht ein benutzerdefiniertes Profil."""
        if name in self.BUILTIN_PROFILES:
            return False  # Built-ins nicht löschbar
        profiles = self._data.get("profiles", {})
        if name in profiles:
            del profiles[name]
            if self._data.get("active_profile") == name:
                self._data["active_profile"] = ""
            self.save()
            return True
        return False

    def list_profile_names(self) -> List[str]:
        """Gibt alle Profilnamen zurück."""
        return list(self.profiles.keys())


# Singleton instance
_instance: Optional[AppConfig] = None


def get_app_config() -> AppConfig:
    """Get the global app config (singleton)."""
    global _instance
    if _instance is None:
        _instance = AppConfig()
    return _instance
