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
Handler Registry - Auto-Discovery und Command Routing
=====================================================
Scannt hub/ Verzeichnis und registriert alle BaseHandler-Subklassen.
Unterstuetzt Multi-Handler-Dateien (time.py, tuev.py).
"""

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Optional

from .base import ParsedArgs, Result, parse_args


def _canonical_handler_for_host_conflict(py_file: Path) -> Optional[Path]:
    """Return the canonical handler for a ``name-HOST.py`` conflict copy."""
    parts = py_file.stem.split("-")
    for split_at in range(1, len(parts)):
        suffix = "-".join(parts[split_at:])
        if (
            not any(char.isalpha() for char in suffix)
            or suffix != suffix.upper()
            or not all(char.isalnum() or char == "-" for char in suffix)
        ):
            continue
        canonical = py_file.with_name("-".join(parts[:split_at]) + py_file.suffix)
        if canonical.is_file():
            return canonical
    return None


class HandlerRegistry:
    """Verwaltet alle verfuegbaren Handler via Auto-Discovery."""

    def __init__(self):
        self._handlers: dict[str, dict] = {}  # name -> {class, module_name, file}
        self._instances: dict[str, object] = {}

    def discover(self, hub_dir: Path, aliases: dict = None) -> int:
        """Scannt hub/ Verzeichnis und registriert Handler-Klassen.

        Args:
            hub_dir: Pfad zum hub/ Verzeichnis
            aliases: Optionale Alias-Map (wird nach Discovery angewendet)

        Returns:
            Anzahl gefundener Handler
        """
        count = 0
        if not hub_dir.exists():
            return 0

        for py_file in sorted(hub_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue

            canonical = _canonical_handler_for_host_conflict(py_file)
            if canonical is not None:
                print(
                    f"[WARN] Handler conflict copy {py_file.name} ignored; "
                    f"using {canonical.name}"
                )
                continue

            found = self._load_handlers_from_file(py_file, hub_dir)
            count += found

        # Aliases anwenden (mem -> memory, etc.)
        if aliases:
            for alias, target in aliases.items():
                if target in self._handlers and alias not in self._handlers:
                    self._handlers[alias] = self._handlers[target]

        return count

    def _load_handlers_from_file(self, py_file: Path, hub_dir: Path) -> int:
        """Laedt alle Handler-Klassen aus einer Python-Datei.

        Unterstuetzt Multi-Handler-Dateien (z.B. time.py mit 5 Handlern).

        Returns:
            Anzahl registrierter Handler
        """
        module_name = f"hub.{py_file.stem}"
        count = 0

        try:
            # sys.path sicherstellen
            parent = str(hub_dir.parent)
            if parent not in sys.path:
                sys.path.insert(0, parent)

            # Bereits geladenes Modul wiederverwenden (verhindert doppeltes Laden)
            if module_name in sys.modules:
                module = sys.modules[module_name]
            else:
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if not spec or not spec.loader:
                    return 0

                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

            # BaseHandler aus hub.base importieren
            from hub.base import BaseHandler

            # Alle BaseHandler-Subklassen finden (nur lokal definierte, keine Imports/Aliase)
            seen_classes = set()
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type)
                        and issubclass(attr, BaseHandler)
                        and attr is not BaseHandler
                        and not getattr(attr, '__abstract__', False)
                        and getattr(attr, '__module__', None) == module_name
                        and id(attr) not in seen_classes):
                    seen_classes.add(id(attr))
                    # profile_name extrahieren
                    name = self._extract_profile_name(attr, py_file)
                    if name:
                        if name in self._handlers:
                            old_file = self._handlers[name]["file"].name
                            print(f"[WARN] Handler '{name}' aus {old_file} wird von {py_file.name} ueberschrieben!")
                        self._handlers[name] = {
                            "class": attr,
                            "module_name": module_name,
                            "file": py_file,
                        }
                        count += 1

        except Exception as e:
            # Leises Warnen - nicht crashen bei defekten Handlern
            print(f"[WARN] Handler {py_file.name}: {e}")

        return count

    def _extract_profile_name(self, handler_class, py_file: Path) -> Optional[str]:
        """Extrahiert profile_name aus Handler-Klasse."""
        # Methode 1: property direkt lesen (Klassen-Level)
        prop = handler_class.__dict__.get("profile_name")
        if prop and hasattr(prop, "fget"):
            try:
                # Manche properties brauchen keine Instanz
                name = prop.fget(None)
                if name:
                    return name
            except (TypeError, AttributeError):
                pass

        # Methode 2: Klassen-Attribut (nicht property)
        if hasattr(handler_class, '_profile_name'):
            return handler_class._profile_name

        # Methode 3: Aus Klassennamen ableiten
        # TaskHandler -> task, MemoryHandler -> memory
        class_name = handler_class.__name__
        if class_name.endswith("Handler"):
            return class_name[:-7].lower()

        # Methode 4: Dateiname als Fallback
        return py_file.stem

    def reload(self, hub_dir: Path, aliases: dict = None) -> int:
        """Hot-Reload: Cleared alle Handler und entdeckt neu.

        Ermoeglicht das Hinzufuegen neuer Handler ohne Neustart.

        Args:
            hub_dir: Pfad zum hub/ Verzeichnis
            aliases: Optionale Alias-Map

        Returns:
            Anzahl gefundener Handler
        """
        self._handlers.clear()
        self._instances.clear()
        return self.discover(hub_dir, aliases)

    def register(self, name: str, handler_class, **kwargs):
        """Manuell einen Handler registrieren."""
        self._handlers[name] = {
            "class": handler_class,
            "module_name": kwargs.get("module_name", ""),
            "file": kwargs.get("file"),
        }

    def get(self, name: str, base_path: Path = None, app=None):
        """Holt oder erstellt Handler-Instanz.

        Args:
            name: Handler-Name (z.B. "task", "memory")
            base_path: Legacy base_path (fuer alte Handler)
            app: App-Instanz (fuer neue Handler)

        Returns:
            Handler-Instanz oder None
        """
        if name in self._instances:
            return self._instances[name]

        entry = self._handlers.get(name)
        if not entry:
            return None

        handler_class = entry["class"]

        try:
            # Versuche zuerst mit app (neuer Stil)
            if app:
                try:
                    instance = handler_class(app)
                    self._instances[name] = instance
                    return instance
                except TypeError:
                    pass

            # Fallback: Legacy base_path
            if base_path:
                instance = handler_class(base_path)
                self._instances[name] = instance
                return instance

        except Exception as e:
            print(f"[WARN] Handler '{name}' Instanziierung: {e}")

        return None

    def has(self, name: str) -> bool:
        """Prueft ob Handler registriert ist."""
        return name in self._handlers

    @property
    def names(self) -> list:
        """Alle registrierten Handler-Namen (sortiert)."""
        return sorted(self._handlers.keys())

    @property
    def count(self) -> int:
        """Anzahl registrierter Handler."""
        return len(self._handlers)

    def suggest(self, input_name: str) -> list:
        """Schlaegt aehnliche Handler-Namen vor bei Tippfehlern."""
        suggestions = []
        for name in self._handlers:
            if input_name in name or name in input_name:
                suggestions.append(name)
            elif self._levenshtein(input_name, name) <= 2:
                suggestions.append(name)
        return suggestions[:3]

    @staticmethod
    def _levenshtein(s1: str, s2: str) -> int:
        """Einfache Levenshtein-Distanz."""
        if len(s1) < len(s2):
            return HandlerRegistry._levenshtein(s2, s1)
        if len(s2) == 0:
            return len(s1)

        prev_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            curr_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = prev_row[j + 1] + 1
                deletions = curr_row[j] + 1
                substitutions = prev_row[j] + (c1 != c2)
                curr_row.append(min(insertions, deletions, substitutions))
            prev_row = curr_row

        return prev_row[-1]


def route_command(argv: list, registry: "HandlerRegistry",
                  base_path: Path = None, app=None) -> Result:
    """Routet CLI-Argumente zum passenden Handler.

    Unterstuetzt:
    - bach task list        (command ohne --)
    - bach --task list      (command mit --)
    - bach help             (Hilfe-Shortcut)

    Args:
        argv: sys.argv[1:] (ohne Programmname)
        registry: Handler-Registry
        base_path: Legacy base_path
        app: App-Instanz

    Returns:
        Result oder None wenn kein Handler gefunden
    """
    if not argv:
        return None

    command = argv[0]
    rest = argv[1:]

    # -- Prefix entfernen
    if command.startswith("--"):
        command = command[2:]

    # Handler suchen
    handler = registry.get(command, base_path=base_path, app=app)
    if not handler:
        suggestions = registry.suggest(command)
        if suggestions:
            msg = f"Unbekannter Befehl: {command}\n  Meintest du: {', '.join(suggestions)}?"
        else:
            msg = f"Unbekannter Befehl: {command}"
        return Result(False, msg)

    # Operation bestimmen
    operation = rest[0] if rest else ""
    op_args = rest[1:] if rest else []

    try:
        success, message = handler.handle(operation, op_args)
        return Result(success, message)
    except Exception as e:
        return Result(False, f"Fehler in {command} {operation}: {e}")
