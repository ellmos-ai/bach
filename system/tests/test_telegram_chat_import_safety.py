# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""T-20260927-232943082: telegram_chat.py darf bei fehlender Abhaengigkeit
den Prozess nicht per sys.exit() beenden -- das riss frueher jeden
Importeur mit (z.B. pytest beim Sammeln von Testmodulen: INTERNALERROR
statt eines gewoehnlichen Testfehlers). Ein Bibliotheksmodul muss eine
normale Exception werfen, die der Aufrufer abfangen kann.
"""

import importlib
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

MODULE_NAME = "hub._services.chat.telegram_chat"


def _reload_without(monkeypatch, missing_name: str):
    """Erzwingt einen frischen Import von telegram_chat, waehrend `missing_name`
    (und alles darunter) als 'nicht installiert' erscheint."""
    monkeypatch.delitem(sys.modules, MODULE_NAME, raising=False)
    for name in list(sys.modules):
        if name == missing_name or name.startswith(missing_name + "."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    real_import = __import__

    def _blocking_import(name, *args, **kwargs):
        if name == missing_name or name.startswith(missing_name + "."):
            raise ImportError(f"No module named '{missing_name}' (simuliert)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _blocking_import)


def test_missing_telegram_raises_importerror_not_systemexit(monkeypatch):
    _reload_without(monkeypatch, "telegram")
    with pytest.raises(ImportError):
        importlib.import_module(MODULE_NAME)


def test_missing_httpx_raises_importerror_not_systemexit(monkeypatch):
    pytest.importorskip("telegram", reason="braucht python-telegram-bot (T-20260927-232943082)")
    _reload_without(monkeypatch, "httpx")
    with pytest.raises(ImportError):
        importlib.import_module(MODULE_NAME)
