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

from __future__ import annotations

"""
Path Handler - strukturierte Pfadoberfläche für BACH
====================================================

Nutzt ``bach_paths.py`` als Single Source of Truth und macht die Pfade
maschinenlesbar für CLI, API und Automationen.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

from . import bach_paths as bp
from .base import BaseHandler


SUMMARY_GROUPS = {
    "core": ("root", "system", "hub", "data", "db"),
    "runtime": ("logs", "backups", "messages", "instances", "prosync_transit"),
    "workspace": ("user", "docs", "exports", "skills", "tools", "agents", "experts"),
    "domains": ("foerderplanung", "berichte", "berichte_output", "steuer", "belege"),
}

VALIDATION_GROUPS = {
    "error": ("root", "system", "hub", "data", "db"),
    "warn": ("skills", "tools", "help", "user"),
    "info": ("partners", "connectors", "agents", "logs", "berichte"),
}


class PathHandler(BaseHandler):
    """Handler für `bach path`."""

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.repo_root = self.base_path.parent

    @property
    def profile_name(self) -> str:
        return "path"

    @property
    def target_file(self) -> Path:
        return self.base_path / "hub" / "bach_paths.py"

    def get_operations(self) -> dict:
        return {
            "status": "Wichtige Pfade zusammengefasst anzeigen (Standard)",
            "list": "Alle registrierten Pfade anzeigen",
            "get": "Einen spezifischen Pfad anzeigen",
            "resolve": "Relativen Pfad gegen system/ oder Repo-Root auflösen",
            "overrides": "DB-Pfad-Overrides anzeigen",
            "set": "Pfad-Override setzen: bach path set <name> <pfad>",
            "validate": "Wichtige Pfade validieren",
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        json_output = self._has_flag(args, "--json")
        clean_args = self._strip_flags(args, "--json")

        if operation in {"help", "--help", "-h"}:
            return self._show_help(json_output=json_output)
        if operation in {"--json", "-j"}:
            return self._show_summary(json_output=True)
        if operation in {"", "status", "show", "all"}:
            return self._show_summary(json_output=json_output)
        if operation == "list":
            return self._list_paths(json_output=json_output)
        if operation == "get":
            if not clean_args:
                return False, "[FEHLER] Nutzung: bach path get <name>"
            return self._show_path(clean_args[0], json_output=json_output)
        if operation == "resolve":
            return self._resolve_path(args, json_output=json_output)
        if operation == "overrides":
            return self._show_overrides(json_output=json_output)
        if operation == "validate":
            return self._validate_paths(json_output=json_output)
        if operation == "set":
            return self._set_override(clean_args, dry_run=dry_run, json_output=json_output)

        # Kurzform: `bach path db`
        return self._show_path(operation, json_output=json_output)

    def _has_flag(self, args: Iterable[str], *flags: str) -> bool:
        return any(arg in flags for arg in args)

    def _strip_flags(self, args: Iterable[str], *flags: str) -> list[str]:
        blocked = set(flags)
        return [arg for arg in args if arg not in blocked]

    def _json_dump(self, payload: dict) -> str:
        return json.dumps(payload, indent=2, ensure_ascii=False)

    def _normalize_name(self, name: str) -> str:
        return name.lower().replace("-", "_").replace(" ", "_")

    def _active_db_path(self) -> Path:
        """Aktive DB für den aktuellen Runtime-Root."""
        local_db = (self.base_path / "data" / "bach.db").resolve(strict=False)
        if self.base_path.resolve() != bp.SYSTEM_ROOT.resolve():
            return local_db
        return self._canonical_db.resolve(strict=False)

    def _runtime_registry(self) -> Dict[str, Path]:
        """Spiegelt die zentrale Registry auf den aktiven base_path."""
        registry: Dict[str, Path] = {}
        actual_system = bp.SYSTEM_ROOT.resolve()
        actual_root = bp.BACH_ROOT.resolve()
        runtime_system = self.base_path.resolve()
        runtime_root = self.repo_root.resolve()

        for name, raw_path in bp._PATH_REGISTRY.items():
            candidate = Path(raw_path)
            remapped = candidate

            try:
                remapped = runtime_system / candidate.resolve(strict=False).relative_to(actual_system)
            except ValueError:
                try:
                    remapped = runtime_root / candidate.resolve(strict=False).relative_to(actual_root)
                except ValueError:
                    remapped = candidate

            registry[name] = remapped

        return registry

    def _load_overrides(self) -> Dict[str, Path]:
        """Lädt Pfad-Overrides aus der kanonischen DB des aktuellen Roots."""
        db_path = self._active_db_path()
        if not db_path.exists():
            return {}

        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='system_config'"
            )
            if not cursor.fetchone():
                conn.close()
                return {}

            cursor.execute(
                "SELECT key, value FROM system_config WHERE key LIKE 'path.%' ORDER BY key"
            )
            rows = cursor.fetchall()
            conn.close()
        except sqlite3.Error:
            return {}

        overrides: Dict[str, Path] = {}
        for key, value in rows:
            normalized = self._normalize_name(str(key).replace("path.", "", 1))
            overrides[normalized] = Path(value)
        return overrides

    def _get_registry_entry(self, name: str) -> Tuple[str, Path, str]:
        normalized = self._normalize_name(name)
        if normalized in {"db", "bach_db", "archive_db"}:
            return normalized, self._active_db_path(), "default"

        registry = self._runtime_registry()
        if normalized not in registry:
            available = ", ".join(sorted(registry.keys())[:20]) + ", ..."
            raise KeyError(
                f"Unbekannter Pfad: '{name}'\n"
                f"Verfügbar: {available}\n\n"
                "Nutze `bach path list` für alle Pfadnamen."
            )

        overrides = self._load_overrides()
        if normalized in overrides:
            return normalized, overrides[normalized], "override"
        return normalized, registry[normalized], "default"

    def _serialize_path(self, name: str, path: Path, source: str) -> dict:
        exists = path.exists()
        record = {
            "name": name,
            "path": str(path),
            "exists": exists,
            "source": source,
            "kind": "missing",
        }

        if exists:
            if path.is_dir():
                record["kind"] = "directory"
                try:
                    record["entry_count"] = sum(1 for _ in path.iterdir())
                except OSError:
                    record["entry_count"] = None
            elif path.is_file():
                record["kind"] = "file"
                try:
                    record["size_bytes"] = path.stat().st_size
                except OSError:
                    record["size_bytes"] = None

        for label, base in (("relative_to_system", self.base_path), ("relative_to_root", self.repo_root)):
            try:
                record[label] = str(path.resolve(strict=False).relative_to(base.resolve()))
            except ValueError:
                continue

        return record

    def _format_record(self, record: dict) -> str:
        status = "✓" if record["exists"] else "✗"
        source = "override" if record["source"] == "override" else "default "
        return f"  {record['name']:18} {status} {source} {record['path']}"

    def _show_help(self, json_output: bool = False) -> tuple:
        payload = {
            "command": "bach path",
            "operations": self.get_operations(),
            "examples": [
                "bach path",
                "bach path db",
                "bach path list --json",
                "bach path resolve docs/README.md --from-root",
                "bach path set wissensdatenbank D:\\Daten\\Wiki",
            ],
        }
        if json_output:
            return True, self._json_dump(payload)

        lines = [
            "BACH PATH",
            "=========",
            "",
            "Befehle:",
            "  bach path                        Wichtige Pfade zusammengefasst",
            "  bach path <name>                 Einzelnen Pfad anzeigen",
            "  bach path get <name>             Einzelnen Pfad explizit anzeigen",
            "  bach path list [--json]          Alle registrierten Pfade",
            "  bach path resolve <pfad>         Relativen Pfad auflösen",
            "  bach path overrides [--json]     Aktive DB-Overrides",
            "  bach path validate [--json]      Pfade validieren",
            "  bach path set <name> <pfad>      DB-Override setzen",
            "",
            "Beispiele:",
        ]
        lines.extend(f"  {example}" for example in payload["examples"])
        return True, "\n".join(lines)

    def _show_summary(self, json_output: bool = False) -> tuple:
        payload = {
            "generated_at": datetime.now().isoformat(),
            "override_count": len(self._load_overrides()),
            "groups": {},
        }

        lines = ["BACH Pfadoberfläche", "=" * 60]
        for group_name, names in SUMMARY_GROUPS.items():
            records = []
            lines.extend(["", f"[{group_name.upper()}]"])
            for name in names:
                normalized, path, source = self._get_registry_entry(name)
                record = self._serialize_path(normalized, path, source)
                records.append(record)
                lines.append(self._format_record(record))
            payload["groups"][group_name] = records

        if json_output:
            return True, self._json_dump(payload)

        lines.extend(
            [
                "",
                "Hinweis: `bach path list --json` liefert die vollständige Registry.",
            ]
        )
        return True, "\n".join(lines)

    def _list_paths(self, json_output: bool = False) -> tuple:
        names = sorted(self._runtime_registry().keys())
        records = []
        for name in names:
            normalized, path, source = self._get_registry_entry(name)
            records.append(self._serialize_path(normalized, path, source))

        payload = {
            "generated_at": datetime.now().isoformat(),
            "count": len(records),
            "paths": records,
        }
        if json_output:
            return True, self._json_dump(payload)

        lines = ["Verfügbare BACH-Pfade", "=" * 60]
        lines.extend(self._format_record(record) for record in records)
        return True, "\n".join(lines)

    def _show_path(self, name: str, json_output: bool = False) -> tuple:
        normalized, path, source = self._get_registry_entry(name)
        record = self._serialize_path(normalized, path, source)

        if json_output:
            return True, self._json_dump(record)

        lines = [
            f"{normalized}: {record['path']}",
            f"  Quelle:     {'DB-Override' if source == 'override' else 'Standard-Registry'}",
            f"  Existiert:  {'Ja' if record['exists'] else 'Nein'}",
            f"  Typ:        {record['kind']}",
        ]
        if "entry_count" in record and record["entry_count"] is not None:
            lines.append(f"  Einträge:   {record['entry_count']}")
        if "size_bytes" in record and record["size_bytes"] is not None:
            lines.append(f"  Größe:      {record['size_bytes']} Bytes")
        if "relative_to_system" in record:
            lines.append(f"  Rel. system:{record['relative_to_system']}")
        if "relative_to_root" in record:
            lines.append(f"  Rel. root:  {record['relative_to_root']}")
        return True, "\n".join(lines)

    def _resolve_path(self, raw_args: list[str], json_output: bool = False) -> tuple:
        from_root = self._has_flag(raw_args, "--from-root", "--root")
        args = self._strip_flags(raw_args, "--json", "--from-root", "--root")
        if not args:
            return False, "[FEHLER] Nutzung: bach path resolve <pfad> [--from-root]"

        raw_path = " ".join(args)
        path = Path(raw_path)
        base = self.repo_root if from_root else self.base_path
        resolved = path if path.is_absolute() else (base / path)
        resolved = resolved.resolve(strict=False)

        payload = {
            "input": raw_path,
            "base": str(base),
            "from_root": from_root,
            "resolved_path": str(resolved),
            "exists": resolved.exists(),
        }
        if json_output:
            return True, self._json_dump(payload)

        lines = [
            f"Eingabe:   {raw_path}",
            f"Basis:     {base}",
            f"Aufgelöst: {resolved}",
            f"Existiert: {'Ja' if resolved.exists() else 'Nein'}",
        ]
        return True, "\n".join(lines)

    def _show_overrides(self, json_output: bool = False) -> tuple:
        overrides = self._load_overrides()
        records = [
            self._serialize_path(name, path, "override")
            for name, path in sorted(overrides.items())
        ]

        payload = {
            "generated_at": datetime.now().isoformat(),
            "count": len(records),
            "overrides": records,
            "db_path": str(self._active_db_path()),
        }
        if json_output:
            return True, self._json_dump(payload)

        if not records:
            return True, "Keine Pfad-Overrides gesetzt."

        lines = ["DB-Pfad-Overrides", "=" * 60]
        lines.extend(self._format_record(record) for record in records)
        lines.append(f"\nDB: {self._active_db_path()}")
        return True, "\n".join(lines)

    def _validate_paths(self, json_output: bool = False) -> tuple:
        warnings = []
        checked = []

        for level, names in VALIDATION_GROUPS.items():
            for name in names:
                normalized, path, source = self._get_registry_entry(name)
                record = self._serialize_path(normalized, path, source)
                checked.append(record)
                if not record["exists"]:
                    warnings.append(
                        {
                            "level": level,
                            "name": normalized,
                            "path": record["path"],
                            "source": source,
                        }
                    )

        payload = {
            "generated_at": datetime.now().isoformat(),
            "valid": not any(item["level"] == "error" for item in warnings),
            "warnings": warnings,
            "checked": checked,
        }
        if json_output:
            return True, self._json_dump(payload)

        if not warnings:
            return True, "[OK] Alle kritischen Pfade sind vorhanden."

        lines = ["Pfad-Validierung", "=" * 60]
        for item in warnings:
            lines.append(
                f"  [{item['level'].upper()}] {item['name']}: {item['path']}"
            )
        return True, "\n".join(lines)

    def _set_override(self, args: list[str], dry_run: bool = False, json_output: bool = False) -> tuple:
        if len(args) < 2:
            return False, "[FEHLER] Nutzung: bach path set <name> <pfad>"

        name = self._normalize_name(args[0])
        value = " ".join(args[1:])
        payload = {
            "name": name,
            "path": value,
            "db_path": str(self._active_db_path()),
            "dry_run": dry_run,
        }

        if dry_run:
            if json_output:
                return True, self._json_dump(payload)
            return True, f"[DRY-RUN] Würde Override setzen: {name} -> {value}"

        db_path = self._active_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS system_config (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                INSERT OR REPLACE INTO system_config (key, value, updated_at)
                VALUES (?, ?, datetime('now'))
                """,
                (f"path.{name}", value),
            )
            conn.commit()
            conn.close()
        except sqlite3.Error as exc:
            return False, f"[FEHLER] Override konnte nicht gespeichert werden: {exc}"

        payload["saved"] = True
        if json_output:
            return True, self._json_dump(payload)

        return True, f"[OK] Override gesetzt: {name} -> {value}"
