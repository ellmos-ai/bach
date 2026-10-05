# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
Test: InboxHandler als BaseHandler-Subklasse (Fix #1670, Zyklus 424)

Vorher war InboxHandler eine eigenstaendige Klasse und wurde von der
Registry-Discovery (core/registry.py: issubclass(BaseHandler)-Filter)
stillschweigend ignoriert -> "Handler nicht gefunden" via bach_command.
"""

import sys
from pathlib import Path

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.base import BaseHandler  # noqa: E402
from hub.inbox import InboxHandler, get_handler  # noqa: E402


def test_inbox_is_base_handler_subclass():
    """Kern des Fixes: InboxHandler erbt von BaseHandler."""
    assert issubclass(InboxHandler, BaseHandler)


def test_get_handler_returns_base_handler_instance():
    """get_handler() liefert eine BaseHandler-Instanz (Registry-Inspektion kompatibel)."""
    handler = get_handler()
    assert handler is not None
    assert isinstance(handler, BaseHandler)


def test_handle_status_returns_tuple():
    """handle('status', []) -> (bool, str); Watcher laeuft nicht = normal (STOPPED)."""
    handler = InboxHandler()
    ok, msg = handler.handle("status", [])
    assert isinstance(ok, bool)
    assert isinstance(msg, str)


def test_profile_name_and_operations():
    """Registry-Interface: profile_name 'inbox' + Standard-Operationen."""
    handler = InboxHandler()
    assert handler.profile_name == "inbox"
    ops = handler.get_operations()
    assert set(ops.keys()) == {"start", "stop", "status", "scan", "config"}


def test_registry_discovery_finds_inbox():
    """core/registry.py muss 'inbox' nach discover() registrieren.

    Vor dem Fix wurde InboxHandler vom issubclass(BaseHandler)-Filter
    stillschweigend ignoriert und fehlte deshalb in der Registry.
    """
    from core.registry import HandlerRegistry

    registry = HandlerRegistry()
    registry.discover(SYSTEM_ROOT / "hub")
    assert "inbox" in registry._handlers
    assert registry._handlers["inbox"]["class"] is InboxHandler