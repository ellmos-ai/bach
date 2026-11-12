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
Hooks Handler - Hook-Framework Verwaltung
==========================================

bach hooks status           Zeigt alle Hooks und Listener
bach hooks events           Listet alle bekannten Events
bach hooks log              Zeigt letzte Hook-Ausfuehrungen
bach hooks test <event>     Testet ein Event (emittiert mit Testdaten)
"""
from pathlib import Path
from .base import BaseHandler


from hub._services.ocean_stack_bridge import deprecated_legacy_bach
@deprecated_legacy_bach("WORKFLOWHOOKER")
class HooksHandler(BaseHandler):
    """Handler fuer --hooks"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)

    @property
    def profile_name(self) -> str:
        return "hooks"

    @property
    def target_file(self) -> Path:
        return self.base_path / "core" / "hooks.py"

    def get_operations(self) -> dict:
        return {
            "status": "Status aller Hooks und Listener",
            "events": "Alle bekannten Events auflisten",
            "log": "Letzte Hook-Ausfuehrungen",
            "test": "Test-Event emittieren",
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        from core.hooks import hooks

        if operation == "status" or not operation:
            return True, hooks.status()

        elif operation == "events":
            events = hooks.list_events()
            lines = ["HOOK EVENTS", "=" * 60]
            lines.append(f"\n{'Event':<30} {'Listener':>8}  Beschreibung")
            lines.append("-" * 60)
            for event, info in sorted(events.items()):
                marker = "*" if info['listeners'] > 0 else " "
                lines.append(
                    f" {marker}{event:<29} {info['listeners']:>8}  {info['description']}"
                )
            lines.append(f"\n* = hat aktive Listener")
            lines.append(f"Gesamt: {len(events)} Events, {hooks.listener_count()} Listener")
            return True, "\n".join(lines)

        elif operation == "log":
            if not hooks._log:
                return True, "Keine Hook-Events aufgezeichnet."
            lines = ["HOOK LOG (letzte Events)", "=" * 50]
            for entry in hooks._log:
                lines.append(
                    f"  [{entry['timestamp'][:19]}] {entry['event']} "
                    f"({entry['listeners']}L, {entry['results']}R)"
                )
            return True, "\n".join(lines)

        elif operation == "test" and args:
            event = args[0]
            results = hooks.emit(event, {'_test': True, 'source': 'hooks test'})
            lines = [f"TEST: {event}", "=" * 40]
            lines.append(f"Listener: {hooks.listener_count(event)}")
            if results:
                lines.append("Ergebnisse:")
                for r in results:
                    lines.append(f"  {r}")
            else:
                lines.append("Keine Ergebnisse (keine Listener oder None-Returns)")
            return True, "\n".join(lines)

        else:
            return False, "Usage: bach hooks [status|events|log|test <event>]"
