# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Standalone Hooks Module
Autarkes Event-Hook-Framework für BACH und Ocean.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional


@dataclass
class HookListener:
    callback: Callable[..., Any]
    priority: int = 100
    once: bool = False
    name: str = ""


class HookRegistry:
    """Autarke Hook- und Event-Dispatching Engine."""

    def __init__(self) -> None:
        self._listeners: dict[str, list[HookListener]] = {}
        self._log: list[dict[str, Any]] = []
        self._known_events: dict[str, str] = {
            "after_task_create": "Wird nach Erstellung eines Tasks aufgerufen",
            "after_task_done": "Wird nach Erledigung eines Tasks aufgerufen",
            "before_session_start": "Wird vor Start einer Session aufgerufen",
            "after_session_end": "Wird nach Ende einer Session aufgerufen",
            "on_plugin_loaded": "Wird beim Laden eines Plugins aufgerufen",
            "on_module_updated": "Wird nach einem Modul-Update aufgerufen",
        }

    def on(
        self,
        event: str,
        callback: Callable[..., Any],
        priority: int = 100,
        once: bool = False,
        name: str = "",
    ) -> None:
        """Registriert einen Listener für ein Event."""
        if event not in self._listeners:
            self._listeners[event] = []
        listener = HookListener(
            callback=callback,
            priority=priority,
            once=once,
            name=name or getattr(callback, "__name__", "anonymous"),
        )
        self._listeners[event].append(listener)
        # Sort by priority ascending (lower number = higher priority)
        self._listeners[event].sort(key=lambda l: l.priority)

    def once(
        self,
        event: str,
        callback: Callable[..., Any],
        priority: int = 100,
        name: str = "",
    ) -> None:
        """Registriert einen einmaligen Listener."""
        self.on(event, callback, priority=priority, once=True, name=name)

    def off(self, event: str, callback_or_name: Optional[Any] = None) -> int:
        """Entfernt Listener für ein Event."""
        if event not in self._listeners:
            return 0
        if callback_or_name is None:
            count = len(self._listeners[event])
            self._listeners[event].clear()
            return count

        initial = len(self._listeners[event])
        self._listeners[event] = [
            l
            for l in self._listeners[event]
            if l.callback != callback_or_name and l.name != str(callback_or_name)
        ]
        return initial - len(self._listeners[event])

    def emit(self, event: str, payload: Optional[Any] = None) -> list[Any]:
        """Sendet ein Event an alle registrierten Listener."""
        listeners = list(self._listeners.get(event, []))
        results: list[Any] = []
        to_remove: list[HookListener] = []

        for listener in listeners:
            try:
                # Dynamische Parameteranpassung je nach Listener-Signatur
                sig = None
                try:
                    sig = inspect.signature(listener.callback)
                except (ValueError, TypeError):
                    pass

                if sig and len(sig.parameters) == 0:
                    res = listener.callback()
                else:
                    try:
                        res = listener.callback(payload)
                    except TypeError:
                        # Fallback ohne Argument falls das Callback keine Argumente nimmt
                        res = listener.callback()

                results.append(res)
            except Exception as exc:
                results.append({"error": str(exc), "listener": listener.name})

            if listener.once:
                to_remove.append(listener)

        # Clean up once listeners
        if to_remove and event in self._listeners:
            self._listeners[event] = [l for l in self._listeners[event] if l not in to_remove]

        self._record_log(event, len(listeners), len(results))
        return results

    def list_events(self) -> dict[str, dict[str, Any]]:
        """Gibt alle bekannten Events mit Listener-Anzahl zurück."""
        all_events = set(self._known_events.keys()).union(self._listeners.keys())
        out: dict[str, dict[str, Any]] = {}
        for ev in sorted(all_events):
            out[ev] = {
                "listeners": len(self._listeners.get(ev, [])),
                "description": self._known_events.get(ev, "Dynamisches Event"),
            }
        return out

    def listener_count(self, event: Optional[str] = None) -> int:
        if event is not None:
            return len(self._listeners.get(event, []))
        return sum(len(ls) for ls in self._listeners.values())

    def get_log(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._log[-limit:]

    def clear(self, event: Optional[str] = None) -> None:
        if event:
            self._listeners.pop(event, None)
        else:
            self._listeners.clear()

    def status(self) -> str:
        lines = [
            "HOOK SYSTEM STATUS",
            "=" * 50,
            f"Registrierte Events: {len(self._listeners)}",
            f"Gesamte Listener:     {self.listener_count()}",
            f"Ausgeführte Events:  {len(self._log)}",
        ]
        return "\n".join(lines)

    def _record_log(self, event: str, listeners: int, results: int) -> None:
        self._log.append({
            "event": event,
            "listeners": listeners,
            "results": results,
            "timestamp": datetime.now().isoformat(),
        })


_global_hooks = HookRegistry()


def get_hook_registry() -> HookRegistry:
    return _global_hooks


hooks = _global_hooks
