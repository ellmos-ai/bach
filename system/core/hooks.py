# -*- coding: utf-8 -*-
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
Hook-Framework - Erweiterbare Lifecycle-Events fuer BACH
=========================================================

Hooks sind technische Einhaengepunkte im BACH-Lifecycle.
Jedes Modul kann sich auf Events registrieren und wird benachrichtigt.

WICHTIG: Hooks != Injektoren!
- Hooks = technisches Framework (dieses Modul)
- Injektoren = kognitives Subsystem (tools/injectors.py)
  Injektoren simulieren Gedanken und dienen der kognitiven Entlastung.
  Sie bleiben eigenstaendig und nutzen Hooks OPTIONAL als Transport.

Nutzung:
    from core.hooks import hooks

    # Hook registrieren
    hooks.on('after_task_done', my_handler)

    # Hook emittieren
    hooks.emit('after_task_done', {'task_id': 42, 'title': 'Aufgabe'})

    # Hook mit Prioritaet (niedrig = frueher)
    hooks.on('before_command', my_check, priority=10)

Version: 1.0.0
"""

from datetime import datetime
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .instance_messaging import InstanceMessaging
    from .instance_registry import InstanceRegistry


class HookRegistry:
    """Erweiterbare Lifecycle-Hooks fuer BACH.

    Stellt vordefinierte Events bereit, erlaubt aber auch
    custom Events ohne Vorab-Deklaration.

    Distributed Messaging (B29):
        Events in DISTRIBUTED_EVENTS koennen via broadcast=True
        an andere BACH-Instanzen weitergeleitet werden.
        Dazu muss connect_messaging() aufgerufen worden sein.
    """

    # Events die bei broadcast=True an andere Instanzen gesendet werden
    DISTRIBUTED_EVENTS = {
        'after_task_done',
        'after_memory_write',
        'after_task_create',
    }

    # Vordefinierte Events (Dokumentation, nicht Einschraenkung)
    KNOWN_EVENTS = {
        # Session-Lifecycle
        'before_startup':       'Vor dem Startup-Protokoll',
        'after_startup':        'Nach dem Startup (Session bereit)',
        'before_shutdown':      'Vor dem Shutdown-Protokoll',
        'after_shutdown':       'Nach dem Shutdown (Session beendet)',

        # Befehl-Lifecycle
        'before_command':       'Vor jedem CLI-Befehl (handler, operation, args)',
        'after_command':        'Nach jedem CLI-Befehl (handler, operation, result)',

        # Task-Lifecycle
        'after_task_create':    'Nach Task-Erstellung (task_id, title)',
        'after_task_done':      'Nach Task-Erledigung (task_id, title)',
        'after_task_delete':    'Nach Task-Loeschung (task_id)',

        # Memory-Lifecycle
        'after_memory_write':   'Nach Memory-Eintrag (content, type)',
        'after_lesson_add':     'Nach Lesson-Erstellung (title, content)',

        # Skill-Lifecycle
        'after_skill_create':   'Nach Skill-Erstellung (name, type, path)',
        'after_skill_reload':   'Nach Hot-Reload (handler_count)',

        # Plugin-Lifecycle
        'after_plugin_load':    'Nach Plugin-Laden (name, version, hooks, handlers)',
        'after_plugin_unload':  'Nach Plugin-Entladen (name)',

        # Security
        'after_capability_denied': 'Nach verweigerter Capability (plugin, capability, reason)',

        # Custom (erweiterbar)
        'after_email_send':     'Nach E-Mail-Versand (draft_id, recipient)',
    }

    def __init__(self):
        self._listeners: dict[str, list] = {}
        # Generischer Interceptor-Slot (MODULRUECKTRANSFER Stufe 6):
        # hub-seitige Provider (workflowhooker) haengen hier Callables an,
        # die in emit() laufen. Core importiert dabei nie hub -- das
        # Callable wird von aussen injiziert (Import-Richtung bleibt
        # hub -> core, AST-Waechter-Regel der Stufen 2-5).
        self._interceptors: list[dict] = []
        #: Meldungen des letzten emit()-Aufrufs, die von Interceptors kamen
        #: (Listener-Rueckgaben bewusst NICHT -- die bleiben still, Stufe 6).
        self.last_interceptor_results: list[str] = []
        self._log: list[dict] = []  # Letzte N Events fuer Debugging
        self._log_max = 50
        self._messaging: Optional['InstanceMessaging'] = None
        self._registry: Optional['InstanceRegistry'] = None

    def on(self, event: str, handler: Callable,
           priority: int = 50, name: str = None):
        """Registriert einen Handler fuer ein Event.

        Args:
            event: Event-Name (z.B. 'after_task_done')
            handler: Callable(context: dict) -> Optional[str]
            priority: Niedrigere Werte feuern frueher (default: 50)
            name: Optionaler Name fuer Debugging/Status
        """
        if event not in self._listeners:
            self._listeners[event] = []

        entry = {
            'priority': priority,
            'handler': handler,
            'name': name or getattr(handler, '__name__', str(handler)),
            'registered_at': datetime.now().isoformat(),
        }
        self._listeners[event].append(entry)
        self._listeners[event].sort(key=lambda x: x['priority'])

    def off(self, event: str, handler: Callable = None, name: str = None):
        """Entfernt Handler von einem Event.

        Args:
            event: Event-Name
            handler: Spezifischer Handler (optional)
            name: Handler-Name (optional, Alternative zu handler)
        """
        if event not in self._listeners:
            return

        if handler:
            self._listeners[event] = [
                e for e in self._listeners[event]
                if e['handler'] is not handler
            ]
        elif name:
            self._listeners[event] = [
                e for e in self._listeners[event]
                if e['name'] != name
            ]

    def register_interceptor(self, interceptor: Callable,
                             name: str = None, priority: int = 90) -> bool:
        """Registriert einen Event-Interceptor fuer emit() (Stufe 6).

        Interceptors laufen in emit() VOR den Listenern und sind fuer
        dynamisch injizierte Hooker gedacht (z.B. externer workflowhooker).
        Ein Interceptor ist ein Callable(event, context) und liefert
        None, einen str oder eine Liste von str.

        Args:
            interceptor: Callable(event: str, context: dict)
            name: Eindeutiger Name (Guard gegen Doppelregistrierung)
            priority: Niedrigere Werte frueher (default 90: nach schnellen
                      System-Listenern, vor langen)

        Returns:
            True bei Registrierung, False bei vorhandenem Namen (idempotent).
        """
        name = name or getattr(interceptor, '__name__', str(interceptor))
        if any(e['name'] == name for e in self._interceptors):
            return False
        self._interceptors.append({
            'priority': priority,
            'interceptor': interceptor,
            'name': name,
            'registered_at': datetime.now().isoformat(),
        })
        self._interceptors.sort(key=lambda x: x['priority'])
        return True

    def emit(self, event: str, context: dict = None,
             broadcast: bool = False) -> list:
        """Feuert ein Event und ruft alle registrierten Handler auf.

        Args:
            event: Event-Name
            context: Dict mit Event-spezifischen Daten
            broadcast: Wenn True UND Event in DISTRIBUTED_EVENTS,
                       wird das Event auch an andere BACH-Instanzen gesendet.
                       Erfordert vorherigen Aufruf von connect_messaging().

        Returns:
            Liste von Handler-Ergebnissen (nur non-None)
        """
        ctx = context or {}
        ctx['_event'] = event
        ctx['_timestamp'] = datetime.now().isoformat()

        results = []
        listeners = self._listeners.get(event, [])

        # Interceptor-Slot (Stufe 6): dynamisch injizierte Hooker laufen
        # vor den Listenern; jeder Fehler wird geschluckt (fail-soft), ein
        # kaputter Hooker darf keinen Befehlsfluss blockieren.
        # Interceptor-Meldungen werden zusaetzlich separat gemerkt, damit
        # Aufrufer sie sichtbar machen koennen, ohne Listener-Rueckgaben
        # (die historisch still sind) mit anzuzeigen.
        interceptor_results = []
        for entry in self._interceptors:
            try:
                result = entry['interceptor'](event, ctx)
                if result is None:
                    continue
                if isinstance(result, str):
                    results.append(result)
                    interceptor_results.append(result)
                elif isinstance(result, (list, tuple)):
                    for r in result:
                        if r is None:
                            continue
                        results.append(str(r))
                        interceptor_results.append(str(r))
                else:
                    results.append(str(result))
                    interceptor_results.append(str(result))
            except Exception as e:
                results.append(f"[HOOK-ERROR] interceptor/{entry['name']}: {e}")
        self.last_interceptor_results = interceptor_results

        for entry in listeners:
            try:
                result = entry['handler'](ctx)
                if result is not None:
                    results.append(result)
            except Exception as e:
                results.append(f"[HOOK-ERROR] {event}/{entry['name']}: {e}")

        # Distributed Broadcast (nur wenn aktiviert und nicht selbst remote)
        if (broadcast
                and event in self.DISTRIBUTED_EVENTS
                and self._messaging is not None
                and not ctx.get('_remote')):
            try:
                # Kontext fuer Serialisierung aufbereiten (interne Keys entfernen)
                broadcast_ctx = {
                    k: v for k, v in ctx.items()
                    if not k.startswith('_')
                }
                sent = self._messaging.broadcast(
                    event=event,
                    context=broadcast_ctx,
                    registry=self._registry,
                )
                if sent > 0:
                    results.append(f"[BROADCAST] {event} -> {sent} Instanz(en)")
            except Exception as e:
                results.append(f"[BROADCAST-ERROR] {event}: {e}")

        # Log fuehren
        self._log.append({
            'event': event,
            'timestamp': ctx['_timestamp'],
            'listeners': len(listeners),
            'results': len(results),
            'broadcast': broadcast and event in self.DISTRIBUTED_EVENTS,
        })
        if len(self._log) > self._log_max:
            self._log = self._log[-self._log_max:]

        return results

    def has_listeners(self, event: str) -> bool:
        """Prueft ob ein Event Listener hat."""
        return bool(self._listeners.get(event))

    def listener_count(self, event: str = None) -> int:
        """Zaehlt registrierte Listener.

        Args:
            event: Spezifisches Event (oder None fuer alle)
        """
        if event:
            return len(self._listeners.get(event, []))
        return sum(len(v) for v in self._listeners.values())

    def status(self) -> str:
        """Gibt formatierten Status aller Hooks zurueck."""
        lines = ["HOOK-FRAMEWORK STATUS", "=" * 50]

        # Registrierte Events
        active_events = {k: v for k, v in self._listeners.items() if v}
        lines.append(f"\nAktive Events: {len(active_events)}")
        lines.append(f"Listener gesamt: {self.listener_count()}")

        if active_events:
            lines.append(f"\n{'Event':<30} {'Listener':>8}")
            lines.append("-" * 40)
            for event, listeners in sorted(active_events.items()):
                lines.append(f"  {event:<28} {len(listeners):>8}")
                for entry in listeners:
                    lines.append(f"    -> {entry['name']} (prio {entry['priority']})")

        # Bekannte aber inaktive Events
        inactive = [e for e in self.KNOWN_EVENTS if e not in active_events]
        if inactive:
            lines.append(f"\nInaktive Events ({len(inactive)}):")
            for event in sorted(inactive):
                desc = self.KNOWN_EVENTS[event]
                lines.append(f"  {event:<28} {desc}")

        # Letzte Events
        if self._log:
            lines.append(f"\nLetzte Events (max {self._log_max}):")
            for entry in self._log[-10:]:
                lines.append(
                    f"  [{entry['timestamp'][:19]}] {entry['event']} "
                    f"({entry['listeners']} listener, {entry['results']} results)"
                )

        return "\n".join(lines)

    def list_events(self) -> dict:
        """Gibt alle bekannten Events mit Beschreibungen zurueck."""
        result = {}
        for event, desc in self.KNOWN_EVENTS.items():
            count = len(self._listeners.get(event, []))
            result[event] = {'description': desc, 'listeners': count}
        # Custom Events (nicht in KNOWN_EVENTS)
        for event in self._listeners:
            if event not in result:
                result[event] = {
                    'description': '(Custom Event)',
                    'listeners': len(self._listeners[event])
                }
        return result

    # ─── Distributed Messaging (B29) ────────────────────────────────

    def connect_messaging(self, messaging: 'InstanceMessaging',
                          registry: 'InstanceRegistry' = None):
        """Verbindet das Hook-System mit dem Inter-Instanz-Messaging.

        Nach dem Aufruf kann emit(broadcast=True) Nachrichten an
        andere BACH-Instanzen senden.

        Args:
            messaging: InstanceMessaging-Instanz
            registry: Optional InstanceRegistry fuer gezielte Zustellung
        """
        self._messaging = messaging
        self._registry = registry

    def disconnect_messaging(self):
        """Trennt das Messaging vom Hook-System.

        Sollte beim Shutdown aufgerufen werden.
        """
        self._messaging = None
        self._registry = None

    @property
    def messaging_connected(self) -> bool:
        """Prueft ob Messaging verbunden ist."""
        return self._messaging is not None

    def poll_messages(self) -> int:
        """Pollt eingehende Nachrichten und emittiert sie als lokale Events.

        Convenience-Methode die InstanceMessaging.process_incoming() aufruft.

        Returns:
            Anzahl verarbeiteter Nachrichten (0 wenn Messaging nicht verbunden)
        """
        if self._messaging is None:
            return 0
        return self._messaging.process_incoming(self)


# Singleton-Instanz (globaler Zugriff)
hooks = HookRegistry()
