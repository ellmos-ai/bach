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


def test_should_disable_telegram_bot_flags(monkeypatch):
    pytest.importorskip("telegram")
    from hub._services.chat.telegram_chat import should_disable_telegram_bot

    monkeypatch.delenv("BACH_DISABLE_TELEGRAM_BOT", raising=False)
    monkeypatch.delenv("BACH_REMOTE_HOST", raising=False)
    monkeypatch.delenv("BACH_TELEGRAM_BOT_HOST", raising=False)

    disabled, reason = should_disable_telegram_bot()
    assert disabled is False

    monkeypatch.setenv("BACH_DISABLE_TELEGRAM_BOT", "1")
    disabled, reason = should_disable_telegram_bot()
    assert disabled is True
    assert "BACH_DISABLE_TELEGRAM_BOT" in reason

    monkeypatch.delenv("BACH_DISABLE_TELEGRAM_BOT", raising=False)
    monkeypatch.setenv("BACH_REMOTE_HOST", "mac")
    disabled, reason = should_disable_telegram_bot()
    assert disabled is True
    assert "Remote-Host" in reason

    monkeypatch.setenv("BACH_REMOTE_HOST", "local")
    disabled, reason = should_disable_telegram_bot()
    assert disabled is False

    monkeypatch.delenv("BACH_REMOTE_HOST", raising=False)
    monkeypatch.setenv("BACH_TELEGRAM_BOT_HOST", "some-other-machine")
    disabled, reason = should_disable_telegram_bot()
    assert disabled is True
    assert "nicht Bot-Host" in reason
