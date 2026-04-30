#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JSON Config CLI -- Wiederverwendbarer Baustein
===============================================
Generisches CLI-Modul zum Lesen und Setzen von Werten in JSON-Config-Dateien
per dot-notation. Kann als Library importiert oder standalone genutzt werden.

Standalone:
    python json_config_cli.py config.json get telegram.bridge_on_failure
    python json_config_cli.py config.json set telegram.bridge_on_failure 1
    python json_config_cli.py config.json list
    python json_config_cli.py config.json list telegram

Als Library (Baukasten fuer eigene Scripts):
    from json_config_cli import JsonConfig

    cfg = JsonConfig("config/default_config.json")
    value = cfg.get("telegram.bridge_on_failure")     # -> 2
    cfg.set("telegram.bridge_on_failure", 1)           # persistent
    entries = cfg.list_keys("telegram")                # -> alle Keys unter telegram

    # In argparse integrieren:
    cfg.add_subcommand(subparsers)                     # fuegt 'config' Subcommand hinzu
    # Dann im dispatch:
    if args.command == "config":
        return cfg.handle_args(args)

Hilfe-Texte:
    Felder mit Praefix '_' und Suffix '_help' werden als Hilfetext erkannt.
    Beispiel: {"_bridge_on_failure_help": "0=nie, 1=immer, 2=fragen"}
    -> wird bei 'get' automatisch mit angezeigt.

BACH Tool | Kategorie: json, config | Praefix: c_ (CLI-optimiert)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


class JsonConfig:
    """Generischer JSON-Config-Manager mit dot-notation Zugriff."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _load(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, data: dict) -> None:
        self.path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _resolve(self, data: dict, keys: list[str]) -> tuple[dict, str] | None:
        """Navigiert zum Eltern-Dict und gibt (parent, last_key) zurueck."""
        current = data
        for k in keys[:-1]:
            if not isinstance(current, dict) or k not in current:
                return None
            current = current[k]
        if not isinstance(current, dict):
            return None
        return current, keys[-1]

    def get(self, key: str):
        """Liest einen Wert per dot-notation. Gibt (value, help_text|None) zurueck."""
        data = self._load()
        keys = key.split(".")
        current = data
        for k in keys:
            if not isinstance(current, dict) or k not in current:
                return None, None
            current = current[k]

        # Hilfe-Text suchen
        result = self._resolve(data, keys)
        help_text = None
        if result:
            parent, last_key = result
            help_key = f"_{last_key}_help"
            if help_key in parent:
                help_text = parent[help_key]

        return current, help_text

    def set(self, key: str, value) -> tuple:
        """Setzt einen Wert per dot-notation. Gibt (old_value, new_value) zurueck."""
        data = self._load()
        keys = key.split(".")

        # Zum richtigen Knoten navigieren, fehlende Ebenen anlegen
        current = data
        for k in keys[:-1]:
            if k not in current or not isinstance(current[k], dict):
                current[k] = {}
            current = current[k]

        old_value = current.get(keys[-1])
        current[keys[-1]] = value
        self._save(data)
        return old_value, value

    def list_keys(self, prefix: str = "") -> list[tuple[str, str]]:
        """Listet alle Keys (optional unter einem Prefix). Gibt [(key, value_repr)] zurueck."""
        data = self._load()

        if prefix:
            for k in prefix.split("."):
                if not isinstance(data, dict) or k not in data:
                    return []
                data = data[k]

        results = []
        self._collect_keys(data, prefix, results)
        return results

    def _collect_keys(self, data, prefix: str, results: list) -> None:
        if not isinstance(data, dict):
            return
        for k, v in data.items():
            if k.startswith("_"):
                continue
            full_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                self._collect_keys(v, full_key, results)
            else:
                results.append((full_key, json.dumps(v)))

    def add_subcommand(self, subparsers) -> None:
        """Fuegt einen 'config' Subcommand zu einem argparse SubParsers-Objekt hinzu."""
        p = subparsers.add_parser(
            "config",
            help="Einstellungen lesen/aendern (persistent)",
        )
        p.add_argument(
            "key",
            nargs="?",
            default="",
            help="Config-Schluessel (dot-notation). Ohne Key: alle anzeigen.",
        )
        p.add_argument(
            "value",
            nargs="?",
            default=None,
            help="Neuer Wert (ohne = nur anzeigen)",
        )

    def handle_args(self, args) -> int:
        """Verarbeitet die args vom config-Subcommand. Return: Exit-Code."""
        key = getattr(args, "key", "") or ""
        value = getattr(args, "value", None)

        # Kein Key -> alle auflisten
        if not key:
            entries = self.list_keys()
            if not entries:
                print("Keine Einstellungen gefunden.")
                return 0
            max_k = max(len(k) for k, _ in entries)
            for k, v in entries:
                print(f"  {k:<{max_k}}  =  {v}")
            return 0

        # Nur lesen
        if value is None:
            # Pruefen ob es ein Prefix ist (zeigt Sub-Keys)
            entries = self.list_keys(key)
            if entries:
                # Wenn genau der Key selbst existiert: Einzelwert anzeigen
                val, help_text = self.get(key)
                if val is not None and not isinstance(val, dict):
                    print(f"{key} = {json.dumps(val)}")
                    if help_text:
                        print(f"  ({help_text})")
                    return 0
                # Sonst: Sub-Keys auflisten
                max_k = max(len(k) for k, _ in entries)
                for k, v in entries:
                    print(f"  {k:<{max_k}}  =  {v}")
                return 0

            val, help_text = self.get(key)
            if val is None:
                print(f"Schluessel '{key}' nicht gefunden.")
                return 1
            print(f"{key} = {json.dumps(val)}")
            if help_text:
                print(f"  ({help_text})")
            return 0

        # Setzen -- Wert parsen
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = value

        old, new = self.set(key, parsed)
        print(f"{key}: {json.dumps(old)} -> {json.dumps(new)}")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="JSON Config CLI -- Werte lesen/setzen per dot-notation",
    )
    parser.add_argument("file", type=Path, help="Pfad zur JSON-Config-Datei")
    parser.add_argument(
        "action",
        choices=["get", "set", "list"],
        help="get=lesen, set=schreiben, list=alle Keys auflisten",
    )
    parser.add_argument("key", nargs="?", default="", help="Key (dot-notation)")
    parser.add_argument("value", nargs="?", default=None, help="Neuer Wert (nur bei set)")

    args = parser.parse_args()

    if not args.file.exists():
        print(f"Datei nicht gefunden: {args.file}", file=sys.stderr)
        return 1

    cfg = JsonConfig(args.file)

    if args.action == "list":
        entries = cfg.list_keys(args.key)
        if not entries:
            print("Keine Eintraege gefunden.")
            return 0
        max_k = max(len(k) for k, _ in entries)
        for k, v in entries:
            print(f"  {k:<{max_k}}  =  {v}")
        return 0

    if args.action == "get":
        if not args.key:
            print("Key erforderlich fuer 'get'.", file=sys.stderr)
            return 1
        val, help_text = cfg.get(args.key)
        if val is None:
            print(f"Schluessel '{args.key}' nicht gefunden.")
            return 1
        print(f"{args.key} = {json.dumps(val)}")
        if help_text:
            print(f"  ({help_text})")
        return 0

    if args.action == "set":
        if not args.key or args.value is None:
            print("Key und Value erforderlich fuer 'set'.", file=sys.stderr)
            return 1
        try:
            parsed = json.loads(args.value)
        except json.JSONDecodeError:
            parsed = args.value
        old, new = cfg.set(args.key, parsed)
        print(f"{args.key}: {json.dumps(old)} -> {json.dumps(new)}")
        return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
