#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Root-level shim for `from bach_api import ...` in editable installs."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_ROOT = Path(__file__).resolve().parent
_SYSTEM_API = _ROOT / "system" / "bach_api.py"

if not _SYSTEM_API.exists():
    raise ImportError(f"BACH API konnte nicht gefunden werden: {_SYSTEM_API}")

_SPEC = importlib.util.spec_from_file_location("_bach_internal_api", _SYSTEM_API)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"BACH API konnte nicht geladen werden: {_SYSTEM_API}")

_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

__all__ = list(getattr(_MODULE, "__all__", []))

for _name in __all__:
    globals()[_name] = getattr(_MODULE, _name)
