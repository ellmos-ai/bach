"""
CLI Interface Template -- ATI Standard-Modul
=============================================
Wiederverwendbares CLI-Interface fuer PySide6-Desktop-Apps.
Ermoeglicht Headless-Steuerung ohne GUI.

Verwendung:
    1. Diese Datei in das Projekt kopieren (z.B. src/cli/cli_interface.py)
    2. COMMANDS anpassen (siehe unten)
    3. In main.py einbinden:

        import sys
        if "--cli" in sys.argv or any(a.startswith("--") for a in sys.argv[1:]):
            from cli.cli_interface import run_cli
            sys.exit(run_cli())
        else:
            # Normale GUI starten

Abhaengigkeiten:
    Keine externen -- nutzt nur Python-stdlib (argparse, json)

Lizenz: MIT (Teil des BACH ATI Systems)
"""

import argparse
import json
import sys
from typing import Any, Callable, Dict, List, Optional


class CLIInterface:
    """
    Generisches CLI-Interface mit Subcommands.

    Beispiel:
        cli = CLIInterface("meinapp", "Meine App CLI")
        cli.add_command("status", handler_status, help="Status anzeigen")
        cli.add_command("list", handler_list, help="Eintraege auflisten",
                        args=[("--format", {"choices": ["json", "table"], "default": "table"})])
        cli.run()
    """

    def __init__(self, prog: str, description: str):
        self.parser = argparse.ArgumentParser(
            prog=prog,
            description=description,
            formatter_class=argparse.RawDescriptionHelpFormatter
        )
        self.subparsers = self.parser.add_subparsers(dest="command", help="Verfuegbare Befehle")
        self._handlers: Dict[str, Callable] = {}

    def add_command(self, name: str, handler: Callable,
                    help: str = "", args: List[tuple] = None):
        """
        Registriert einen CLI-Befehl.

        Args:
            name: Befehlsname (z.B. "status")
            handler: Funktion(args: argparse.Namespace) -> Any
            help: Hilfetext
            args: Liste von (name_or_flags, kwargs) fuer add_argument
        """
        sub = self.subparsers.add_parser(name, help=help)
        for arg_name, arg_kwargs in (args or []):
            if isinstance(arg_name, tuple):
                sub.add_argument(*arg_name, **arg_kwargs)
            else:
                sub.add_argument(arg_name, **arg_kwargs)
        self._handlers[name] = handler

    def run(self, argv: List[str] = None) -> int:
        """
        Parst Argumente und fuehrt den Befehl aus.

        Returns: Exit-Code (0 = OK, 1 = Fehler)
        """
        args = self.parser.parse_args(argv)

        if not args.command:
            self.parser.print_help()
            return 0

        handler = self._handlers.get(args.command)
        if not handler:
            print(f"Unbekannter Befehl: {args.command}", file=sys.stderr)
            return 1

        try:
            result = handler(args)
            if result is not None:
                if isinstance(result, (dict, list)):
                    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
                else:
                    print(result)
            return 0
        except Exception as e:
            print(f"Fehler: {e}", file=sys.stderr)
            return 1


def output_table(data: List[dict], columns: List[str] = None):
    """Einfache Tabellenausgabe fuer CLI."""
    if not data:
        print("(keine Eintraege)")
        return

    if not columns:
        columns = list(data[0].keys())

    # Spaltenbreiten berechnen
    widths = {col: max(len(col), max(len(str(row.get(col, ""))) for row in data))
              for col in columns}

    # Header
    header = " | ".join(col.ljust(widths[col]) for col in columns)
    print(header)
    print("-+-".join("-" * widths[col] for col in columns))

    # Zeilen
    for row in data:
        line = " | ".join(str(row.get(col, "")).ljust(widths[col]) for col in columns)
        print(line)
