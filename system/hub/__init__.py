# SPDX-License-Identifier: MIT
"""
handlers - CHIAH Handler Package
================================
"""

from __future__ import annotations

import importlib
from types import ModuleType

from .base import BaseHandler

__all__ = ["BaseHandler"]


def __getattr__(name: str) -> ModuleType:
    """Lazy-load handler submodules for package attribute access."""
    module_name = f"{__name__}.{name}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    globals()[name] = module
    return module
