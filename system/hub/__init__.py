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


def _install_external_workflow_interceptor() -> None:
    """MODULRUECKTRANSFER Stufe 6: workflowhooker an HookRegistry.emit haengen.

    Idempotent und komplett fail-soft: Fehlt das externe Modul, ist der
    Rollback-Schalter gesetzt oder fehlt der Registry-Slot, passiert nichts.
    Der Interceptor prueft den Rollback live pro Aufruf, ein Umlegen von
    BACH_USE_EXTERNAL_WORKFLOWHOOKS stoppt ihn daher ohne Neustart.
    """
    try:
        from core.hooks import hooks
        from .workflow_hook_provider import install_workflow_interceptor
        install_workflow_interceptor(hooks)
    except Exception:
        pass


_install_external_workflow_interceptor()


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
