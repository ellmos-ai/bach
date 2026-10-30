# coding: utf-8
"""Dünner BACH-Adapter für das Ocean-Modul .MODULES/.CONTROL/persona-routing (#2446)."""
from __future__ import annotations
import importlib.util
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[3] / ".MODULES/.CONTROL/persona-routing/persona_routing.py"
_spec = importlib.util.spec_from_file_location("ocean_control_persona_routing", _MOD_PATH)
_mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_mod)

DEFAULT_ACTIVE_SYSTEM_AGENTS = _mod.DEFAULT_ACTIVE_SYSTEM_AGENTS
LEGACY_BACH_PERSONA_TEMPLATES = _mod.LEGACY_BACH_PERSONA_TEMPLATES
list_persona_catalog = _mod.list_persona_catalog
resolve_persona_route = _mod.resolve_persona_route

__all__ = [
    "DEFAULT_ACTIVE_SYSTEM_AGENTS",
    "LEGACY_BACH_PERSONA_TEMPLATES",
    "list_persona_catalog",
    "resolve_persona_route",
]
