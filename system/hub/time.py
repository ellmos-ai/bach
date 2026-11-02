# SPDX-License-Identifier: MIT
"""
Time Handler - CLI fuer Zeit-System
====================================

Subcommands:
  bach clock on|off|status|interval <sek>
  bach timer start|stop|list|clear [name]
  bach countdown start|stop|pause|resume|list <name> <duration> [--after "cmd"]
  bach between on|off|status|use|profile [name]
  bach beat on|off|interval <sek>

v1.1.83: Initial Implementation (TIME-05)
"""
from pathlib import Path
from .base import BaseHandler


from hub._services.ocean_stack_bridge import deprecated_legacy_bach
@deprecated_legacy_bach("ellmos-core")
class ClockHandler(BaseHandler):
    """Handler fuer bach clock"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)

    @property
    def profile_name(self) -> str:
        return "clock"

    @property
    def target_file(self) -> Path:
        return self.base_path / "data" / ".clock_state"

    def get_operations(self) -> dict:
        return {
            "on": "Uhrzeit-Anzeige aktivieren",
            "off": "Uhrzeit-Anzeige deaktivieren",
            "status": "Status anzeigen",
            "interval": "Intervall setzen (Sekunden)"
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        try:
            from tools.time_system import ClockModule
            clock = ClockModule(self.base_path)
        except Exception as e:
            return False, f"Zeit-System nicht verfuegbar: {e}"

        if operation == "on":
            return True, clock.enable(True)

        elif operation == "off":
            return True, clock.enable(False)

        elif operation == "status" or not operation:
            return True, clock.status()

        elif operation == "interval":
            if not args:
                return False, "Usage: bach clock interval <sekunden>"
            try:
                seconds = int(args[0])
                return True, clock.set_interval(seconds)
            except ValueError:
                return False, f"Ungueltige Zahl: {args[0]}"

        elif operation == "beat":
            # Redirect to beat (v1.1.84)
            from .time import BeatHandler
            handler = BeatHandler(self.base_path)
            return handler.handle("", args, dry_run)

        else:
            return False, f"Unbekannte Operation: {operation}\nNutze: bach clock status"


class TimerHandler(BaseHandler):
    """Handler fuer bach timer"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)

    @property
    def profile_name(self) -> str:
        return "timer"

    @property
    def target_file(self) -> Path:
        return self.base_path / "data" / ".timer_state"

    def get_operations(self) -> dict:
        return {
            "start": "Timer starten [name]",
            "stop": "Timer stoppen [name]",
            "list": "Aktive Timer anzeigen",
            "clear": "Alle Timer loeschen"
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        try:
            from tools.time_system import TimerModule
            timer = TimerModule(self.base_path)
        except Exception as e:
            return False, f"Zeit-System nicht verfuegbar: {e}"

        if operation == "start":
            name = args[0] if args else "default"
            return True, timer.start(name)

        elif operation == "stop":
            name = args[0] if args else None
            return True, timer.stop(name)

        elif operation == "list" or not operation:
            return True, timer.list_timers()

        elif operation == "clear":
            return True, timer.clear()

        else:
            return False, f"Unbekannte Operation: {operation}\nNutze: bach timer list"


class CountdownHandler(BaseHandler):
    """Handler fuer bach countdown"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)

    @property
    def profile_name(self) -> str:
        return "countdown"

    @property
    def target_file(self) -> Path:
        return self.base_path / "data" / ".countdown_state"

    def get_operations(self) -> dict:
        return {
            "start": "Countdown starten: <name> <HH:MM:SS> [--after 'cmd']",
            "stop": "Countdown abbrechen: <name>",
            "pause": "Countdown pausieren: <name>",
            "resume": "Countdown fortsetzen: <name>",
            "list": "Aktive Countdowns anzeigen"
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        try:
            from tools.time_system import CountdownModule
            countdown = CountdownModule(self.base_path)
        except Exception as e:
            return False, f"Zeit-System nicht verfuegbar: {e}"

        # v1.1.84: Auto-detect 'start' if first arg is numeric
        if operation not in self.get_operations() and operation not in ("on", "off", "status"):
            import re
            if re.match(r'^\d', str(operation)):
                args = [operation] + args
                operation = "start"

        if operation == "start":
            if len(args) == 1:
                # Nur eine Zahl angegeben -> Name="timer", Duration=args[0]
                name = "timer"
                duration = args[0]
            elif len(args) >= 2:
                name = args[0]
                duration = args[1]
            else:
                return False, "Usage: bach countdown start <name> <HH:MM:SS> [--after 'befehl']"

            # --after Parameter suchen
            after_command = None
            if "--after" in args:
                idx = args.index("--after")
                if idx + 1 < len(args):
                    after_command = args[idx + 1]

            return True, countdown.start(name, duration, after_command)

        elif operation == "stop":
            if not args:
                return False, "Usage: bach countdown stop <name>"
            return True, countdown.stop(args[0])

        elif operation == "pause":
            if not args:
                return False, "Usage: bach countdown pause <name>"
            return True, countdown.pause(args[0])

        elif operation == "resume":
            if not args:
                return False, "Usage: bach countdown resume <name>"
            return True, countdown.resume(args[0])

        elif operation == "list" or not operation:
            return True, countdown.list_countdowns()

        else:
            return False, f"Unbekannte Operation: {operation}\nNutze: bach countdown list"


class BetweenHandler(BaseHandler):
    """Handler fuer bach between"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)

    @property
    def profile_name(self) -> str:
        return "between"

    @property
    def target_file(self) -> Path:
        return self.base_path / "data" / ".between_state"

    def get_operations(self) -> dict:
        return {
            "on": "Between-Checks aktivieren",
            "off": "Between-Checks deaktivieren",
            "status": "Status anzeigen",
            "use": "Profil aktivieren: <name>",
            "profile": "Profile verwalten: list|add|edit|delete|show"
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        try:
            from tools.time_system import BetweenManager
            between = BetweenManager(self.base_path)
        except Exception as e:
            return False, f"Zeit-System nicht verfuegbar: {e}"

        if operation == "on":
            return True, between.enable(True)

        elif operation == "off":
            return True, between.enable(False)

        elif operation == "status" or not operation:
            return True, between.status()

        elif operation == "use":
            if not args:
                return False, "Usage: bach between use <profil-name>"
            return True, between.use_profile(args[0])

        elif operation == "profile":
            if not args:
                return True, between.list_profiles()

            subop = args[0].lower()

            if subop == "list":
                return True, between.list_profiles()

            elif subop == "show":
                if len(args) < 2:
                    return False, "Usage: bach between profile show <name>"
                profile = between._get_profile(args[1])
                if not profile:
                    return False, f"Profil '{args[1]}' nicht gefunden"
                lines = [
                    f"[BETWEEN] Profil: {profile['name']}",
                    f"  Beschreibung: {profile['description']}",
                    f"  Trigger: {', '.join(profile.get('trigger_on', []))}",
                    f"  Message:",
                    f"    {profile['message'].replace(chr(10), chr(10) + '    ')}"
                ]
                return True, "\n".join(lines)

            elif subop in ["add", "edit", "delete"]:
                return False, f"Profile {subop} ist noch nicht implementiert. Verwende DB direkt."

            else:
                return False, f"Unbekannte Sub-Operation: {subop}"

        else:
            return False, f"Unbekannte Operation: {operation}\nNutze: bach between status"


class BeatHandler(BaseHandler):
    """Handler fuer bach beat - Unified Zeit-Anzeige"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)

    @property
    def profile_name(self) -> str:
        return "beat"

    @property
    def target_file(self) -> Path:
        return self.base_path / "data"

    def get_operations(self) -> dict:
        return {
            "": "Alle Zeit-Infos anzeigen",
            "on": "Alle Zeit-Anzeigen aktivieren",
            "off": "Alle Zeit-Anzeigen deaktivieren",
            "interval": "Globales Intervall setzen"
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        try:
            from tools.time_system import TimeManager
            manager = TimeManager(self.base_path)
        except Exception as e:
            return False, f"Zeit-System nicht verfuegbar: {e}"

        if operation == "on":
            return True, manager.enable_all()

        elif operation == "off":
            return True, manager.disable_all()

        elif operation == "interval":
            if not args:
                return False, "Usage: bach beat interval <sekunden>"
            try:
                seconds = int(args[0])
                return True, manager.set_interval(seconds)
            except ValueError:
                return False, f"Ungueltige Zahl: {args[0]}"

        elif not operation:
            return True, manager.get_beat()

        else:
            return False, f"Unbekannte Operation: {operation}\nNutze: bach beat"
