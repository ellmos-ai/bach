#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: injectors
Version: 2.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-11-10
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version injectors

Description:
    Dünner Adapter auf memory_hook_provider HOOKER_INJECTORS.
    Beibehaltung der Fassaden InjectorConfig, TimeInjector und Kern-API.

    Die Injektoren Strategy, Context, Tool-Warnung, Between delegieren an den externen
    memoryhooker (source-strategic). Output-Formate bleiben gleich:
    [STRATEGIE], Kontext-Hinweise, [TOOL-REMINDER], [BETWEEN-TASKS].

    CLI-Pfad: Between nur im CLI (source='between'), CLI-Hinweise gefiltert.
    Rollback-Schalter: BACH_USE_EXTERNAL_MEMORYHOOKS=0 deaktiviert den Seam.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set, FrozenSet

from hub.memory_hook_provider import get_shared_memory_hook

log = logging.getLogger(__name__)

# ---------- InjectorConfig (unverändert) ----------
class InjectorConfig:
    """Konfiguration für Injektoren."""

    def __init__(self, config_file: Path):
        self.config_file = config_file
        self.config = self._load()

    def _load(self) -> dict:
        """Lädt Konfiguration."""
        default = {
            "strategy_injector": True,
            "context_injector": True,
            "time_injector": True,
            "between_injector": True,
            "timebeat_interval": 60,
        }
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    default.update(loaded.get("injectors", {}))
            except (json.JSONDecodeError, OSError):
                pass
        return default

    def save(self):
        """Speichert Konfiguration."""
        try:
            full_config = {}
            if self.config_file.exists():
                with open(self.config_file, "r", encoding="utf-8") as f:
                    full_config = json.load(f)
            full_config["injectors"] = self.config
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(full_config, f, ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, OSError):
            pass

    def toggle(self, injector: str) -> bool:
        """Schaltet Injektor um."""
        if injector in self.config:
            self.config[injector] = not self.config[injector]
            self.save()
            return self.config[injector]
        return False

    def is_enabled(self, injector: str) -> bool:
        """Prüft ob Injektor aktiv."""
        return self.config.get(injector, False)

# ---------- TimeInjector (Proxy auf time_system) ----------
class TimeInjector:
    """Proxy auf tools.time_system.TimeManager (TIME-07)."""

    def __init__(self, interval: int = 60, base_path: Path = None):
        self.interval = interval
        self.base_path = base_path
        self.manager = None
        if base_path:
            try:
                from tools.time_system import TimeManager
                self.manager = TimeManager(base_path)
                self.manager.set_interval(interval)
            except (ImportError, AttributeError):
                pass

    def check(self) -> Optional[str]:
        """Timebeat-Proxy."""
        if not self.manager:
            return None
        return self.manager.timebeat()

# ---------- InjectorSystem (dünner Adapter) ----------
class InjectorSystem:
    """Zentrales Interface – delegiert auf memory_hook_provider HOOKER_INJECTORS."""

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.config = InjectorConfig(base_path / "config.json")
        self.time_injector = TimeInjector(
            self.config.config.get("timebeat_interval", 60), base_path)
        self._shared_hook = get_shared_memory_hook()
        self._tool_reminder_shown = False

    # ----------------------------------------------------
    # Öffentliche Fassaden (für bach_api, Legacy-CLI usw.)
    # ----------------------------------------------------
    def toggle(self, injector: str):
        """Schaltet einen Injektor ein/aus."""
        return self.config.toggle(injector)

    def is_enabled(self, injector: str) -> bool:
        """Prüft ob ein Injektor aktiviert ist."""
        return self.config.is_enabled(injector)

    def status(self) -> dict:
        """Status aller Injektoren."""
        return self.config.config.copy()

    def check_before_create(self, text: str) -> Optional[str]:
        """Tool-Warnung vor Tool-Erstellung – delegiert auf den Seam."""
        # Im Adapter-Pfad übernimmt der externe Hook die gesamte Tool-Logic.
        # Keine eigene Berechnungen.
        return None

    # ----------------------------------------------------
    # Prozess (Chat-Runtime & API)
    # ----------------------------------------------------
    def process(self, text: str, context: dict = None, skip=(), cli_hints: bool = True) -> List[str]:
        """Verarbeitet Text durch alle aktiven Injektoren.

        Delegiert vollständig an memoryhooker (external provider) – der externe
        Hook erhält alle Injektoren, die nicht von CLI-only (between) übernommen werden.
        """
        if not self._shared_hook:
            return []
        # Dummy-Chat-ID – pro Sitzung wäre ideal; hier ein globaler Platzhalter.
        chat_id = "adapter"
        # Gesperrte Injektoren – keine; der Hook entscheidet selbst.
        disabled: FrozenSet[str] = frozenset()
        try:
            injection = self._shared_hook.hook_context(
                text=text, chat_id=chat_id, cli_hints=cli_hints, disabled=disabled)
        except Exception:
            injection = None
        if injection:
            # hook_context kann einen einzelnen String zurückgeben, der eine ganze Injektion enthält.
            return [injection]
        return []

    def get_tool_reminder(self) -> Optional[str]:
        """Tool-Erinnerung – wird nun vom externen Hook gesteuert."""
        # Der externe Hook verwendet eine separate Startnachricht.
        return None

    # ----------------------------------------------------
    # Between-Tasks (nur CLI)
    # ----------------------------------------------------
    def check_between(self, last_command: str, session_ending: bool = False) -> Optional[str]:
        """Prüft Between-Tasks Erinnerung (CLI-only).

        Ruft die CLI-Seite von memoryhooker für den Between-Injektor auf.
        """
        if not self._shared_hook:
            return None
        # Für die CLI-Nutzung verwenden wir die CLI-API – sie erwartet die letzte Befehlsausgabe,
        # aber zwischen wird auf dem Befehl selbst bewertet.
        try:
            _, between = self._shared_hook.cli_injections(
                output="", last_command=last_command, disabled=frozenset())
            if between:
                return between[0]
        except Exception:
            pass
        return None

    # ----------------------------------------------------
    # Kühlmanagement & ältere Funktionen (für Kompatibilität)
    # ----------------------------------------------------
    # Diese Methoden wurden für die Legacy-Aktivitätsverfolgung beibehalten – sie sind jetzt
    # No-Ops, weil die externe Hook den gesamten Cooldown verwaltet.
    def get_cooldown_state(self, injector: str) -> dict:
        return {"remaining": 0, "last_shown": None}

    def mark_shown(self, injector: str):
        pass

    def is_on_cooldown(self, injector: str) -> bool:
        return False

# ---------- Alte Injektionsklassen – jetzt nur Platzhalter (No-OP) ----------
class StrategyInjector:
    @classmethod
    def check(cls, text: str, context: dict = None) -> Optional[str]:
        return None

class ContextInjector:
    @classmethod
    def check(cls, text: str, cli_hints: bool = True) -> Optional[str]:
        return None

class ToolInjector:
    @classmethod
    def check_before_create(cls, text: str) -> Optional[str]:
        return None
    @classmethod
    def get_startup_reminder(cls, base_path: Path) -> Optional[str]:
        return None

class BetweenInjector:
    @classmethod
    def check_task_done(cls, last_command: str) -> Optional[str]:
        return None

# Das Modulschließende __all__, falls benötigt (geizig)
__all__ = ["InjectorConfig", "TimeInjector", "InjectorSystem"]