# coding: utf-8
"""Dünner BACH-Adapter für .MODULES/.CONTROL/ocean-resources (#2441)."""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[3] / ".MODULES/.CONTROL/ocean-resources/ram_distributor.py"
_spec = importlib.util.spec_from_file_location("ocean_control_ocean_resources", _MOD_PATH)
_mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

OceanRamDistributor = _mod.OceanRamDistributor
PRIORITY_RANK = _mod.PRIORITY_RANK
