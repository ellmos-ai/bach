#!/usr/bin/env python3
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
UpgradeHandler - Selektive Upgrades & Downgrades (SQ020)
=========================================================

CLI-Befehle:
  bach upgrade --list <file>           Verfuegbare Versionen anzeigen
  bach upgrade --status                Upgrade-Status anzeigen
  bach upgrade --check                 Nach Updates pruefen
  bach upgrade core                    CORE-Komponenten upgraden
  bach upgrade templates               TEMPLATE-Dateien upgraden
  bach upgrade skills                  Skills upgraden
  bach upgrade hub                     Hub-Handler upgraden
  bach upgrade tools                   Tools upgraden
  bach upgrade <file>                  Einzeldatei upgraden
  bach upgrade <file> --version X      Spezifische Version
  bach downgrade <file>                Datei downgraden
  bach upgrade help                    Hilfe anzeigen

Nutzt: bach.db / dist_file_versions, distribution_releases, distribution_manifest
Referenz: BACH_Dev/docs/SQ020_SELEKTIVE_UPGRADES.md
"""

import json
import os
import hashlib
import re
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Dict
from hub.base import BaseHandler


class UpgradeHandler(BaseHandler):
    """Handler fuer selektive Upgrades und Downgrades."""

    PRIVATE_DIST_PREFIXES = (
        "user/",
        "system/user/",
        "backups/",
        "logs/",
        "system/storage/",
        "system/data/logs/",
        "system/data/messages/",
        "system/data/mail_attachments/",
        "system/dist/",
        "system/tools/agents/cache/",
        "system/tools/data/",
    )
    PRIVATE_DIST_NAMES = {
        "MEMORY.md",
        "USER.md",
        "CLAUDE.md",
        "OLLAMA.md",
        "GEMINI.md",
        "SKILLS.md",
        "CHAINS.md",
        "PARTNERS.md",
        "AGENTS.md",
        "WORKFLOWS.md",
        "USECASES.md",
        "BACH_HELP_REFERENCE.md",
    }
    PRIVATE_DIST_GLOBS = (
        ".env",
        ".env.*",
        "*.pem",
        "*.p12",
        "*.pfx",
        "*.key",
        "*.token",
        "*.secret",
        "credentials*.json",
        "secrets*.json",
        "*secret*.json",
        "id_rsa",
        "id_rsa.*",
        "id_ed25519",
        "id_ed25519.*",
        "*-ASUS-GEI*",
        "*-WORKSTATION-LG*",
        "*-WORKSTATION-*.md",
        "*-Mac Studio.*",
        "system/data/config/directory_truth-*.json",
        "system/hub/_services/claude_bridge/last_start*.txt",
        "system/tools/mcp/*/package-lock.json",
    )

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "upgrade"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "list": "Verfuegbare Versionen anzeigen",
            "status": "Upgrade-Status anzeigen",
            "check": "Nach Updates pruefen",
            "repair": "Distributions-Metadaten aus Dateisystem und Defaults reparieren",
            "core": "CORE-Komponenten upgraden",
            "templates": "TEMPLATE-Dateien upgraden",
            "agents": "Agenten-Dateien upgraden",
            "skills": "Skills upgraden",
            "hub": "Hub-Handler upgraden",
            "tools": "Tools upgraden",
            "connectors": "Connector-Dateien upgraden",
            "partners": "Partner-Dateien upgraden",
            "docs": "Dokumentation upgraden",
            "gui": "GUI-Dateien upgraden",
            "file": "Einzeldatei upgraden",
            "downgrade": "Datei downgraden",
            "help": "Hilfe anzeigen",
        }

    def _get_db(self):
        """Verbindung zur Datenbank."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _has_flag(self, args: list, *flags: str) -> bool:
        """Prueft, ob ein Flag in den CLI-Argumenten gesetzt wurde."""
        return any(arg in flags for arg in args)

    def _json_dump(self, payload: dict) -> str:
        """Formatiert JSON konsistent fuer CLI-Ausgaben."""
        return json.dumps(payload, indent=2, ensure_ascii=False)

    def _json_error(self, message: str, **extra) -> str:
        """Formatiert maschinenlesbare Fehlerantworten fuer JSON-CLI-Aufrufe."""
        payload = {
            "generated_at": datetime.now().isoformat(),
            "ok": False,
            "message": message,
        }
        payload.update(extra)
        return self._json_dump(payload)

    def _resolve_disk_path(self, file_path: str) -> Path:
        """Loest einen versionierten Dateipfad auf die lokale Datei auf."""
        if file_path.startswith("system/"):
            return self.base_path.parent / file_path

        root_candidate = self.base_path.parent / file_path
        if root_candidate.exists():
            return root_candidate

        return self.base_path / file_path

    def _hash_file(self, path: Path) -> Optional[str]:
        """Berechnet den SHA256-Hash einer lokalen Datei."""
        try:
            with path.open("rb") as handle:
                return hashlib.sha256(handle.read()).hexdigest()
        except OSError:
            return None

    def _parse_timestamp(self, raw_value: Optional[str]) -> Optional[datetime]:
        """Parst Datenbank-Zeitstempel tolerant."""
        if not raw_value:
            return None

        normalized = str(raw_value).strip()
        if not normalized:
            return None

        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"

        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            pass

        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(normalized, fmt)
            except ValueError:
                continue

        return None

    def _matches_latest_by_metadata(self, disk_path: Path, latest: dict) -> bool:
        """Nutzen einen schnellen Metadaten-Abgleich fuer unveraenderte Dateien.

        Wenn der letzte bekannte Versions-/Repair-Zeitstempel neuer als die lokale
        Datei ist, muss kein voller Hash berechnet werden.
        """
        created_at = self._parse_timestamp(latest.get("created_at"))
        if created_at is None or not latest.get("file_hash"):
            return False

        try:
            modified_at = datetime.fromtimestamp(disk_path.stat().st_mtime)
        except OSError:
            return False

        # Kleine Toleranz, damit frisch geschriebene Dateien mit derselben Sekunde
        # nicht unnötig wieder gehasht werden.
        return modified_at <= (created_at + timedelta(seconds=2))

    def _table_columns(self, conn, table_name: str) -> List[str]:
        """Liest Spaltennamen einer Tabelle."""
        try:
            rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        except sqlite3.Error:
            return []
        return [str(row[1]) for row in rows]

    def _manifest_path_column(self, conn) -> Optional[str]:
        """Ermittelt die Pfad-Spalte des Distribution-Manifests."""
        columns = self._table_columns(conn, "distribution_manifest")
        if "path" in columns:
            return "path"
        if "file_path" in columns:
            return "file_path"
        return None

    def _bach_root(self) -> Path:
        """Ermittelt das BACH-Root fuer Dateiscans."""
        if self.base_path.name == "system":
            return self.base_path.parent
        return self.base_path

    def _detect_current_version(self) -> str:
        """Leitet die aktuelle BACH-Version aus Root-Dokumenten ab."""
        bach_root = self._bach_root()

        readme_path = bach_root / "README.md"
        if readme_path.exists():
            try:
                match = re.search(
                    r"^\*\*Version:\*\*\s*([^\s]+)",
                    readme_path.read_text(encoding="utf-8"),
                    flags=re.MULTILINE,
                )
                if match:
                    return match.group(1).strip()
            except OSError:
                pass

        pyproject_path = bach_root / "pyproject.toml"
        if pyproject_path.exists():
            try:
                match = re.search(
                    r'^version\s*=\s*"([^"]+)"',
                    pyproject_path.read_text(encoding="utf-8"),
                    flags=re.MULTILINE,
                )
                if match:
                    version = match.group(1).strip()
                    return version if version.startswith("v") else f"v{version}"
            except OSError:
                pass

        return "v0.0.0-unknown"

    def _release_version_aliases(self, version: Optional[str]) -> List[str]:
        """Liefert konsistente Versions-Aliase mit und ohne `v`-Praefix."""
        if not version:
            return []

        aliases: List[str] = []
        for candidate in (version.strip(),):
            if not candidate:
                continue
            aliases.append(candidate)
            if candidate.startswith("v"):
                aliases.append(candidate[1:])
            else:
                aliases.append(f"v{candidate}")

        seen = set()
        normalized = []
        for alias in aliases:
            if alias not in seen:
                normalized.append(alias)
                seen.add(alias)
        return normalized

    def _detect_release_date(self, version: str) -> Optional[str]:
        """Leitet ein Release-Datum aus Changelog- bzw. Planungsdateien ab."""
        normalized_version = version[1:] if version.startswith("v") else version
        bach_root = self._bach_root()

        changelog_path = bach_root / "CHANGELOG.md"
        if changelog_path.exists():
            try:
                match = re.search(
                    rf"^## \[{re.escape(normalized_version)}\]\s*-\s*(\d{{4}}-\d{{2}}-\d{{2}})\s*$",
                    changelog_path.read_text(encoding="utf-8"),
                    flags=re.MULTILINE,
                )
                if match:
                    return match.group(1)
            except OSError:
                pass

        next_release_path = bach_root / ".dev" / "NEXT_RELEASE.md"
        if next_release_path.exists():
            try:
                match = re.search(
                    rf"^\*\*Vorheriger Release:\*\*\s*{re.escape(version)}\s*\((\d{{4}}-\d{{2}}-\d{{2}})\)",
                    next_release_path.read_text(encoding="utf-8"),
                    flags=re.MULTILINE,
                )
                if match:
                    return match.group(1)
            except OSError:
                pass

        return None

    def _infer_release_channel(self, version: str) -> Tuple[str, bool]:
        """Leitet Release-Status und Stable-Markierung aus der Versionsbezeichnung ab."""
        normalized = version.lower()
        if "alpha" in normalized:
            return "alpha", False
        if "beta" in normalized:
            return "beta", False
        if re.search(r"(^|[-._])rc(\d+)?($|[-._])", normalized):
            return "rc", False
        if "draft" in normalized:
            return "draft", False
        return "final", True

    def _read_kernel_hash(self, conn) -> Optional[str]:
        """Liest den aktuell bekannten Kernel-Hash aus der Instanz-Identitaet."""
        try:
            columns = set(self._table_columns(conn, "instance_identity"))
            if "kernel_hash" not in columns:
                return None
            row = conn.execute("SELECT kernel_hash FROM instance_identity LIMIT 1").fetchone()
            if not row:
                return None
            return row[0]
        except sqlite3.OperationalError:
            return None

    def _release_catalog_state(self, conn, current_version: Optional[str]) -> Dict[str, object]:
        """Liefert Release-Katalog-Zustand fuer Status-, Check- und Repair-Pfade."""
        release_total = conn.execute("SELECT COUNT(*) FROM distribution_releases").fetchone()[0]
        current_release_registered = False
        current_release_version = current_version
        current_version_known = bool(current_version and current_version != "v0.0.0-unknown")

        if release_total > 0 and current_version_known:
            aliases = self._release_version_aliases(current_version)
            placeholders = ", ".join("?" for _ in aliases)
            row = conn.execute(
                f"SELECT version FROM distribution_releases WHERE version IN ({placeholders}) LIMIT 1",
                aliases,
            ).fetchone()
            if row:
                current_release_registered = True
                current_release_version = row[0]

        return {
            "release_total": release_total,
            "current_version": current_version,
            "current_version_known": current_version_known,
            "current_release_registered": current_release_registered,
            "current_release_version": current_release_version,
        }

    def _recover_release_catalog_entry(
        self,
        conn,
        version: str,
        dry_run: bool,
    ) -> Dict[str, object]:
        """Fuegt bei Bedarf einen aktuellen Release-Katalogeintrag wieder ein."""
        release_state_before = self._release_catalog_state(conn, version)
        release_total_before = int(release_state_before["release_total"])

        if (
            not release_state_before["current_version_known"]
            and release_total_before > 0
        ):
            return {
                "release_inserted": 0,
                "release_bootstrapped": False,
                "release_skipped_reason": "unknown_current_version",
                "release_date": None,
                "release_status": None,
                "is_stable": None,
                "release_entries_before": release_total_before,
                "release_entries_after": release_total_before,
                "current_release_registered_before": bool(release_state_before["current_release_registered"]),
                "current_release_registered_after": bool(release_state_before["current_release_registered"]),
            }

        if release_state_before["current_release_registered"]:
            return {
                "release_inserted": 0,
                "release_bootstrapped": False,
                "release_skipped_reason": "already_present",
                "release_date": None,
                "release_status": None,
                "is_stable": None,
                "release_entries_before": release_total_before,
                "release_entries_after": release_total_before,
                "current_release_registered_before": True,
                "current_release_registered_after": True,
            }

        if not release_state_before["current_version_known"]:
            return {
                "release_inserted": 0,
                "release_bootstrapped": False,
                "release_skipped_reason": "unknown_current_version",
                "release_date": None,
                "release_status": None,
                "is_stable": None,
                "release_entries_before": release_total_before,
                "release_entries_after": release_total_before,
                "current_release_registered_before": False,
                "current_release_registered_after": False,
            }

        release_columns = set(self._table_columns(conn, "distribution_releases"))
        release_date = self._detect_release_date(version) or datetime.now().strftime("%Y-%m-%d")
        release_status, is_stable = self._infer_release_channel(version)
        kernel_hash = self._read_kernel_hash(conn)

        if not dry_run:
            insert_columns = ["version"]
            insert_values = [version]

            if "release_date" in release_columns:
                insert_columns.append("release_date")
                insert_values.append(release_date)
            if "description" in release_columns:
                insert_columns.append("description")
                insert_values.append("Recovered current release entry from local BACH metadata")
            if "changelog" in release_columns:
                insert_columns.append("changelog")
                insert_values.append("Recovered by `bach upgrade repair` from README/CHANGELOG metadata.")
            if "kernel_hash" in release_columns:
                insert_columns.append("kernel_hash")
                insert_values.append(kernel_hash)
            if "status" in release_columns:
                insert_columns.append("status")
                insert_values.append(release_status)
            if "is_stable" in release_columns:
                insert_columns.append("is_stable")
                insert_values.append(1 if is_stable else 0)

            placeholders = ", ".join("?" for _ in insert_columns)
            conn.execute(
                f"INSERT INTO distribution_releases ({', '.join(insert_columns)}) "
                f"VALUES ({placeholders})",
                insert_values,
            )

        release_entries_after = release_total_before + 1
        return {
            "release_inserted": 1,
            "release_bootstrapped": release_total_before == 0,
            "release_skipped_reason": None,
            "release_date": release_date,
            "release_status": release_status,
            "is_stable": is_stable,
            "release_entries_before": release_total_before,
            "release_entries_after": release_entries_after,
            "current_release_registered_before": bool(release_state_before["current_release_registered"]),
            "current_release_registered_after": True,
        }

    def _load_dist_rules(self, conn) -> Tuple[Dict[str, int], List[Tuple[str, int]]]:
        """Liest Dist-Type-Regeln aus `dist_type_defaults`."""
        columns = self._table_columns(conn, "dist_type_defaults")
        if not {"path", "dist_type", "is_file"}.issubset(columns):
            return {}, []

        rows = conn.execute(
            """
            SELECT path, dist_type, is_file
            FROM dist_type_defaults
            ORDER BY LENGTH(path) DESC, path ASC
            """
        ).fetchall()

        exact_rules: Dict[str, int] = {}
        dir_rules: List[Tuple[str, int]] = []
        for path_value, dist_type, is_file in rows:
            normalized = str(path_value).replace("\\", "/")
            if int(is_file):
                exact_rules[normalized] = int(dist_type)
            else:
                dir_rules.append((normalized, int(dist_type)))

        return exact_rules, dir_rules

    def _classify_dist_path(
        self,
        relative_path: str,
        exact_rules: Dict[str, int],
        dir_rules: List[Tuple[str, int]],
    ) -> Optional[int]:
        """Leitet den Dist-Type eines Dateipfads aus Defaults ab."""
        normalized = relative_path.replace("\\", "/")
        if normalized in exact_rules:
            return exact_rules[normalized]

        for prefix, dist_type in dir_rules:
            if normalized.startswith(prefix):
                return dist_type

        return None

    def _is_private_dist_path(self, relative_path: str) -> bool:
        """True fuer lokale/User-/Credential-Pfade, die nie Release-Metadaten werden."""
        normalized = relative_path.replace("\\", "/").lstrip("/")
        if normalized in self.PRIVATE_DIST_NAMES:
            return True
        if any(normalized.startswith(prefix) for prefix in self.PRIVATE_DIST_PREFIXES):
            return True
        if normalized.startswith("system/tools/mcp/") and "/dist/" in normalized:
            return True

        name = Path(normalized).name
        for pattern in self.PRIVATE_DIST_GLOBS:
            if Path(normalized).match(pattern) or Path(name).match(pattern):
                return True
        return False

    def _iter_distribution_files(self):
        """Iteriert ueber relevante Dateien im BACH-Root."""
        bach_root = self._bach_root()
        excluded_dirs = {
            ".git",
            "__pycache__",
            ".pytest_cache",
            "node_modules",
            ".venv",
            "venv",
            "backups",
            "logs",
        }

        for root, dirs, files in os.walk(bach_root):
            dirs[:] = [name for name in dirs if name not in excluded_dirs]
            for file_name in files:
                abs_path = Path(root) / file_name
                rel_path = abs_path.relative_to(bach_root).as_posix()
                if self._is_private_dist_path(rel_path):
                    continue
                yield rel_path, abs_path

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        json_output = self._has_flag(args, "--json")
        filtered_args = [arg for arg in args if arg != "--json"]

        if operation == "help" or not operation:
            return self._show_help()
        elif operation == "list":
            return self._list_versions(filtered_args, json_output=json_output)
        elif operation == "status":
            return self._status(json_output=json_output)
        elif operation == "check":
            return self._check_updates(json_output=json_output)
        elif operation == "repair":
            return self._repair_metadata(filtered_args, dry_run=dry_run, json_output=json_output)
        elif operation == "core":
            return self._upgrade_category("core", filtered_args, dry_run)
        elif operation == "templates":
            return self._upgrade_category("templates", filtered_args, dry_run)
        elif operation == "agents":
            return self._upgrade_category("agents", filtered_args, dry_run)
        elif operation == "skills":
            return self._upgrade_category("skills", filtered_args, dry_run)
        elif operation == "hub":
            return self._upgrade_category("hub", filtered_args, dry_run)
        elif operation == "tools":
            return self._upgrade_category("tools", filtered_args, dry_run)
        elif operation == "connectors":
            return self._upgrade_category("connectors", filtered_args, dry_run)
        elif operation == "partners":
            return self._upgrade_category("partners", filtered_args, dry_run)
        elif operation == "docs":
            return self._upgrade_category("docs", filtered_args, dry_run)
        elif operation == "gui":
            return self._upgrade_category("gui", filtered_args, dry_run)
        elif operation == "file":
            return self._upgrade_file(filtered_args, dry_run)
        elif operation == "downgrade":
            return self._downgrade_file(filtered_args, dry_run)
        else:
            # Default: Behandle als Datei-Upgrade
            if operation:
                return self._upgrade_file([operation] + filtered_args, dry_run)
            return (False, f"Unbekannte Operation: {operation}\nVerfuegbar: {', '.join(self.get_operations().keys())}")

    def _show_help(self) -> tuple:
        """Zeigt Hilfe an."""
        return (True, """UPGRADE - Selektive Upgrades & Downgrades
=========================================

BEFEHLE:
  bach upgrade --list <file>           Verfuegbare Versionen anzeigen
  bach upgrade --status                Upgrade-Status anzeigen
  bach upgrade --check                 Nach Updates pruefen

KATEGORIE-UPGRADES:
  bach upgrade core                    CORE-Komponenten upgraden (dist_type=2)
  bach upgrade templates               TEMPLATE-Dateien upgraden (dist_type=1)
  bach upgrade agents                  Agenten-Dateien upgraden
  bach upgrade skills                  Skills upgraden
  bach upgrade hub                     Hub-Handler upgraden
  bach upgrade tools                   Tools upgraden
  bach upgrade connectors              Connector-Dateien upgraden
  bach upgrade partners                Partner-Dateien upgraden
  bach upgrade docs                    Dokumentation upgraden
  bach upgrade gui                     GUI-Dateien upgraden

EINZELDATEI-UPGRADES:
  bach upgrade <file>                  Einzeldatei auf neueste Version upgraden
  bach upgrade <file> --version X      Auf spezifische Version upgraden
  bach upgrade hub/backup.py           Beispiel: Hub-Handler upgraden

DOWNGRADE:
  bach downgrade <file>                Datei zur vorherigen Version downgraden
  bach downgrade <file> --version X    Auf spezifische Version downgraden

REPAIR:
  bach upgrade repair                  Manifest + aktuelle Versionen neu aufbauen
  bach upgrade repair --dry-run        Nur Analyse, keine DB-Aenderung
  bach upgrade repair --version X      Zielversion fuer neue Versionseintraege

OPTIONEN:
  --dry-run                            Vorschau ohne Aenderungen
  --force                              Ueberschreibe lokale Aenderungen
  --no-backup                          Kein Backup vor Update

DATENBANK: bach.db / dist_file_versions, distribution_releases, distribution_manifest

IMPLEMENTIERT (Phase 1-4/4):
  - Verfuegbare Versionen anzeigen (--list)
  - Status anzeigen (--status)
  - Repair fuer Manifest/Versionen (_repair_metadata)
  - Einzeldatei-Upgrades (_upgrade_file)
  - Kategorie-Upgrades (_upgrade_category) ✓ NEU (Runde 19)
  - Downgrade-Logik (_downgrade_file) ✓ NEU (Runde 19)

FUTURE (Optional):
  - Conflict-Resolution
  - Rollback-Mechanismus bei Fehler

Referenz: BACH_Dev/docs/SQ020_SELEKTIVE_UPGRADES.md""")

    def _list_versions(self, args: list, json_output: bool = False) -> tuple:
        """Listet verfuegbare Versionen einer Datei."""
        if not args:
            if json_output:
                return (
                    False,
                    self._json_error(
                        "Fehler: Datei fehlt.",
                        error_code="missing_file",
                        file_path=None,
                        hint="bach upgrade --list hub/backup.py",
                        versions=[],
                    ),
                )
            return (False, "Fehler: Datei fehlt.\n\nBeispiel: bach upgrade --list hub/backup.py")

        file_path = args[0]

        conn = self._get_db()
        try:
            # Hole alle Versionen fuer diese Datei
            rows = conn.execute("""
                SELECT version, file_hash, dist_type, created_at
                FROM dist_file_versions
                WHERE file_path = ?
                ORDER BY created_at DESC
            """, (file_path,)).fetchall()

            if not rows:
                if json_output:
                    return (
                        False,
                        self._json_error(
                            f"[ERROR] Keine Versionen gefunden fuer: {file_path}",
                            error_code="no_versions_found",
                            file_path=file_path,
                            versions=[],
                        ),
                    )
                return (False, f"[ERROR] Keine Versionen gefunden fuer: {file_path}")

            versions = []
            for i, row in enumerate(rows):
                versions.append({
                    "version": row["version"],
                    "file_hash": row["file_hash"],
                    "dist_type": row["dist_type"],
                    "dist_type_name": {0: "USER", 1: "TEMPLATE", 2: "CORE"}.get(row["dist_type"], "?"),
                    "created_at": row["created_at"],
                    "is_current": i == 0,
                    "is_previous": i == 1,
                })

            if json_output:
                payload = {
                    "generated_at": datetime.now().isoformat(),
                    "file_path": file_path,
                    "current_version": versions[0]["version"],
                    "versions": versions,
                }
                return True, self._json_dump(payload)

            # Aktuell installierte Version ermitteln (neueste = aktuell)
            current_version = rows[0]['version'] if rows else None

            output = [
                f"=== VERFUEGBARE VERSIONEN: {file_path} ===",
                "",
            ]

            for i, row in enumerate(rows):
                v = row['version']
                created = row['created_at'][:10] if row['created_at'] else "unbekannt"
                hash_short = row['file_hash'][:8] if row['file_hash'] else "?"
                dist_type_name = {0: "USER", 1: "TEMPLATE", 2: "CORE"}.get(row['dist_type'], "?")

                # Markiere aktuelle Version
                marker = "(aktuell)" if i == 0 else ""
                marker += " <- Vorherige" if i == 1 else ""

                output.append(f"  {v:<12}  {created}  {hash_short}  [{dist_type_name}]  {marker}")

            output.extend([
                "",
                "Befehle:",
                f"  bach upgrade {file_path}                    Neueste Version",
                f"  bach upgrade {file_path} --version <v>      Spezifische Version",
                f"  bach downgrade {file_path}                  Zur vorherigen Version",
            ])

            return (True, "\n".join(output))

        finally:
            conn.close()

    def _status(self, json_output: bool = False) -> tuple:
        """Zeigt Upgrade-Status an."""
        conn = self._get_db()
        try:
            # Statistiken
            current_version = self._detect_current_version()
            total_tracked = conn.execute("SELECT COUNT(DISTINCT file_path) FROM dist_file_versions").fetchone()[0]
            total_versions = conn.execute("SELECT COUNT(*) FROM dist_file_versions").fetchone()[0]
            manifest_path_column = self._manifest_path_column(conn)
            manifest_entries = 0
            if manifest_path_column:
                manifest_entries = conn.execute("SELECT COUNT(*) FROM distribution_manifest").fetchone()[0]
            release_state = self._release_catalog_state(conn, current_version)
            release_total = int(release_state["release_total"])
            repair_recommended = (
                total_versions == 0
                or total_tracked == 0
                or (manifest_entries > 0 and manifest_entries < 10)
                or release_total == 0
                or (
                    bool(release_state["current_version_known"])
                    and not bool(release_state["current_release_registered"])
                )
            )

            # Releases
            releases = conn.execute("""
                SELECT version, release_date, status, is_stable
                FROM distribution_releases
                ORDER BY release_date DESC
                LIMIT 5
            """).fetchall()

            release_entries = [
                {
                    "version": row["version"],
                    "release_date": row["release_date"],
                    "status": row["status"],
                    "is_stable": bool(row["is_stable"]),
                    "channel": "stable" if row["is_stable"] else (row["status"] or "unstable"),
                }
                for row in releases
            ]

            if json_output:
                payload = {
                    "generated_at": datetime.now().isoformat(),
                    "tracked_files": total_tracked,
                    "total_versions": total_versions,
                    "manifest_entries": manifest_entries,
                    "release_entries": release_total,
                    "repair_recommended": repair_recommended,
                    "current_version": current_version,
                    "current_release_registered": bool(release_state["current_release_registered"]),
                    "current_release_version": release_state["current_release_version"],
                    "releases": release_entries,
                }
                return True, self._json_dump(payload)

            output = [
                "=== UPGRADE SYSTEM STATUS ===",
                "",
                "Statistiken:",
                f"  Nachverfolgte Dateien: {total_tracked}",
                f"  Gesamt-Versionen:      {total_versions}",
                f"  Manifest-Eintraege:    {manifest_entries}",
                f"  Release-Eintraege:     {release_total}",
                f"  Aktuelle Version:      {current_version}",
                "",
            ]

            if releases:
                output.append("Verfuegbare Releases:")
                for r in releases:
                    stable = "stable" if r['is_stable'] else r['status'] or "unstable"
                    date = r['release_date'][:10] if r['release_date'] else "unbekannt"
                    output.append(f"  {r['version']:<12}  {date}  [{stable}]")
                output.append("")

            if repair_recommended:
                output.extend([
                    "Hinweis:",
                    "  Die Distributions-Metadaten wirken unvollstaendig.",
                    "  bach upgrade repair --dry-run    Diagnose",
                    "  bach upgrade repair              Manifest/Versionen/Releasekatalog reparieren",
                    "",
                ])

            output.extend([
                "Befehle:",
                "  bach upgrade --check              Nach Updates pruefen",
                "  bach upgrade --list <file>        Verfuegbare Versionen anzeigen",
                "  bach upgrade core                 CORE-Komponenten upgraden",
                "  bach upgrade repair               Distributions-Metadaten reparieren",
            ])

            return (True, "\n".join(output))

        finally:
            conn.close()

    def _check_updates(self, json_output: bool = False) -> tuple:
        """Prueft nach verfuegbaren Updates."""
        conn = self._get_db()
        try:
            version_rows = conn.execute("""
                SELECT file_path, version, file_hash, dist_type, created_at
                FROM dist_file_versions
                ORDER BY file_path ASC, created_at DESC, version DESC
            """).fetchall()

            latest_release = conn.execute("""
                SELECT version, release_date, status, is_stable
                FROM distribution_releases
                ORDER BY release_date DESC, version DESC
                LIMIT 1
            """).fetchone()

            stable_release = conn.execute("""
                SELECT version, release_date, status, is_stable
                FROM distribution_releases
                WHERE is_stable = 1
                ORDER BY release_date DESC, version DESC
                LIMIT 1
            """).fetchone()
            manifest_path_column = self._manifest_path_column(conn)
            manifest_entries = 0
            if manifest_path_column:
                manifest_entries = conn.execute("SELECT COUNT(*) FROM distribution_manifest").fetchone()[0]
            current_version = self._detect_current_version()
            release_state = self._release_catalog_state(conn, current_version)
            release_total = int(release_state["release_total"])
        finally:
            conn.close()

        repair_recommended = (
            release_total == 0
            or (manifest_entries > 0 and manifest_entries < 10)
            or (
                bool(release_state["current_version_known"])
                and not bool(release_state["current_release_registered"])
            )
        )

        stable_payload = None
        if stable_release:
            stable_payload = {
                "version": stable_release["version"],
                "release_date": stable_release["release_date"],
                "status": stable_release["status"],
                "is_stable": bool(stable_release["is_stable"]),
            }
        latest_payload = None
        if latest_release:
            latest_payload = {
                "version": latest_release["version"],
                "release_date": latest_release["release_date"],
                "status": latest_release["status"],
                "is_stable": bool(latest_release["is_stable"]),
            }

        if not version_rows:
            if json_output:
                payload = {
                    "generated_at": datetime.now().isoformat(),
                    "release_status": {
                        "stable": stable_payload,
                        "latest": latest_payload,
                    },
                    "summary": {
                        "checked_files": 0,
                        "up_to_date": 0,
                        "upgrade_candidates": 0,
                        "local_modifications": 0,
                        "missing_files": 0,
                        "unreadable_files": 0,
                    },
                    "manifest_entries": manifest_entries,
                    "release_entries": release_total,
                    "repair_recommended": repair_recommended,
                    "current_version": current_version,
                    "current_release_registered": bool(release_state["current_release_registered"]),
                    "current_release_version": release_state["current_release_version"],
                    "upgrade_candidates": [],
                    "local_modifications": [],
                    "missing_files": [],
                    "unreadable_files": [],
                    "no_tracked_versions": True,
                    "hint": "bach upgrade repair --dry-run",
                }
                return True, self._json_dump(payload)

            output = [
                "=== UPGRADE-CHECK ===",
                "",
                "[INFO] Keine versionierten Dateien in dist_file_versions gefunden.",
                f"Manifest-Eintraege: {manifest_entries}",
                f"Release-Eintraege:  {release_total}",
                f"Aktuelle Version:   {current_version}",
                "",
                "Befehle:",
                "  bach upgrade --status             Upgrade-Status anzeigen",
                "  bach upgrade --list <file>        Verfuegbare Versionen anzeigen",
                "  bach upgrade repair --dry-run     Diagnose fuer Manifest/Versionen",
                "  bach upgrade repair               Manifest/Versionen neu aufbauen",
            ]
            return True, "\n".join(output)

        versions_by_file: Dict[str, List[dict]] = {}
        for row in version_rows:
            versions_by_file.setdefault(row["file_path"], []).append({
                "version": row["version"],
                "file_hash": row["file_hash"],
                "dist_type": row["dist_type"],
                "created_at": row["created_at"],
            })

        up_to_date = 0
        upgrade_candidates = []
        local_modifications = []
        missing_files = []
        unreadable_files = []

        for file_path, versions in versions_by_file.items():
            latest = versions[0]
            disk_path = self._resolve_disk_path(file_path)

            if not disk_path.exists():
                missing_files.append({
                    "file_path": file_path,
                    "latest_version": latest["version"],
                })
                continue

            if self._matches_latest_by_metadata(disk_path, latest):
                up_to_date += 1
                continue

            current_hash = self._hash_file(disk_path)
            if current_hash is None:
                unreadable_files.append(file_path)
                continue

            if current_hash == latest["file_hash"]:
                up_to_date += 1
                continue

            matched_older = next(
                (entry for entry in versions[1:] if current_hash == entry["file_hash"]),
                None,
            )
            if matched_older is not None:
                upgrade_candidates.append({
                    "file_path": file_path,
                    "current_version": matched_older["version"],
                    "latest_version": latest["version"],
                })
                continue

            local_modifications.append({
                "file_path": file_path,
                "current_version": None,
                "expected_version": latest["version"],
                "expected_hash": latest["file_hash"][:12],
                "current_hash": current_hash[:12],
            })

        if json_output:
            payload = {
                "generated_at": datetime.now().isoformat(),
                "release_status": {
                    "stable": stable_payload,
                    "latest": latest_payload,
                },
                "manifest_entries": manifest_entries,
                "release_entries": release_total,
                "repair_recommended": repair_recommended,
                "current_version": current_version,
                "current_release_registered": bool(release_state["current_release_registered"]),
                "current_release_version": release_state["current_release_version"],
                "summary": {
                    "checked_files": len(versions_by_file),
                    "up_to_date": up_to_date,
                    "upgrade_candidates": len(upgrade_candidates),
                    "local_modifications": len(local_modifications),
                    "missing_files": len(missing_files),
                    "unreadable_files": len(unreadable_files),
                },
                "upgrade_candidates": upgrade_candidates,
                "local_modifications": local_modifications,
                "missing_files": missing_files,
                "unreadable_files": unreadable_files,
                "no_tracked_versions": False,
            }
            return True, self._json_dump(payload)

        output = [
            "=== UPGRADE-CHECK ===",
            "",
        ]

        if stable_release or latest_release:
            output.append("Release-Stand:")
            if stable_release:
                stable_date = (stable_release["release_date"] or "unbekannt")[:10]
                output.append(
                    f"  Stabile Linie:        {stable_release['version']} ({stable_date})"
                )
            else:
                output.append("  Stabile Linie:        Keine stabile Release-Markierung gefunden")

            if latest_release:
                latest_date = (latest_release["release_date"] or "unbekannt")[:10]
                latest_status = "stable" if latest_release["is_stable"] else (latest_release["status"] or "unstable")
                output.append(
                    f"  Neueste bekannte:     {latest_release['version']} ({latest_date}) [{latest_status}]"
                )
            output.append("")

        output.extend([
            "Metadaten:",
            f"  Aktuelle Version:      {current_version}",
            f"  Manifest-Eintraege:    {manifest_entries}",
            f"  Release-Eintraege:     {release_total}",
            "",
        ])

        checked_files = len(versions_by_file)
        output.extend([
            "Datei-Stand:",
            f"  Gepruefte Dateien:    {checked_files}",
            f"  Aktuell:              {up_to_date}",
            f"  Upgrade-Kandidaten:   {len(upgrade_candidates)}",
            f"  Lokale Abweichungen:  {len(local_modifications)}",
            f"  Fehlende Dateien:     {len(missing_files)}",
        ])
        if unreadable_files:
            output.append(f"  Nicht lesbar:         {len(unreadable_files)}")
        output.append("")

        if upgrade_candidates:
            output.append("Upgrade-Kandidaten:")
            for item in upgrade_candidates[:10]:
                output.append(
                    f"  - {item['file_path']}  {item['current_version']} -> {item['latest_version']}"
                )
            if len(upgrade_candidates) > 10:
                output.append(f"  ... +{len(upgrade_candidates) - 10} weitere")
            output.append("")

        if local_modifications:
            output.append("Lokale Abweichungen:")
            for item in local_modifications[:10]:
                output.append(
                    f"  - {item['file_path']}  erwartet {item['expected_version']} "
                    f"(Hash {item['expected_hash']}...), lokal {item['current_hash']}..."
                )
            if len(local_modifications) > 10:
                output.append(f"  ... +{len(local_modifications) - 10} weitere")
            output.append("")

        if missing_files:
            output.append("Fehlende Dateien:")
            for item in missing_files[:10]:
                output.append(
                    f"  - {item['file_path']}  erwartet {item['latest_version']}"
                )
            if len(missing_files) > 10:
                output.append(f"  ... +{len(missing_files) - 10} weitere")
            output.append("")

        if unreadable_files:
            output.append("Nicht lesbare Dateien:")
            for file_path in unreadable_files[:10]:
                output.append(f"  - {file_path}")
            if len(unreadable_files) > 10:
                output.append(f"  ... +{len(unreadable_files) - 10} weitere")
            output.append("")

        if not upgrade_candidates and not local_modifications and not missing_files and not unreadable_files:
            output.extend([
                "[OK] Keine ausstehenden Datei-Upgrades oder Drift erkannt.",
                "",
            ])

        if repair_recommended:
            output.extend([
                "Hinweis:",
                "  Release-/Manifest-Metadaten sind noch unvollstaendig.",
                "  bach upgrade repair --dry-run     Diagnose fuer Repair-Pfad",
                "  bach upgrade repair               Releasekatalog/Manifest reparieren",
                "",
            ])

        output.extend([
            "Befehle:",
            "  bach upgrade <file>              Einzeldatei aktualisieren",
            "  bach upgrade core --dry-run      CORE-Dateien pruefen",
            "  bach upgrade docs --dry-run      Doku-Dateien pruefen",
            "  bach upgrade --list <file>       Versionshistorie anzeigen",
        ])

        return True, "\n".join(output)

    def _repair_metadata(self, args: list, dry_run: bool, json_output: bool = False) -> tuple:
        """Repariert Distribution-Manifest und aktuelle Versionsdaten."""
        dry_run = dry_run or self._has_flag(args, "--dry-run", "-n")
        version = None
        if "--version" in args:
            try:
                version = args[args.index("--version") + 1]
            except (IndexError, ValueError):
                version = None
        version = version or self._detect_current_version()

        conn = self._get_db()
        try:
            manifest_path_column = self._manifest_path_column(conn)
            if not manifest_path_column:
                message = "distribution_manifest hat keine kompatible Pfad-Spalte."
                if json_output:
                    return False, self._json_error(
                        message,
                        error_code="missing_manifest_path_column",
                    )
                return False, f"[ERROR] {message}"

            exact_rules, dir_rules = self._load_dist_rules(conn)
            if not exact_rules and not dir_rules:
                message = "dist_type_defaults ist leer oder unvollstaendig."
                if json_output:
                    return False, self._json_error(
                        message,
                        error_code="missing_dist_type_defaults",
                    )
                return False, f"[ERROR] {message}"

            manifest_columns = set(self._table_columns(conn, "distribution_manifest"))
            select_sql = (
                f"SELECT {manifest_path_column}, dist_type"
                + (", template_hash" if "template_hash" in manifest_columns else "")
                + " FROM distribution_manifest"
            )
            existing_manifest_rows = conn.execute(select_sql).fetchall()
            existing_manifest = {}
            for row in existing_manifest_rows:
                existing_manifest[str(row[0])] = {
                    "dist_type": int(row[1]) if row[1] is not None else None,
                    "template_hash": row[2] if len(row) > 2 else None,
                }

            private_manifest_paths = [
                path
                for path, entry in existing_manifest.items()
                if self._is_private_dist_path(path)
                or entry["dist_type"] == 0
                or self._classify_dist_path(path, exact_rules, dir_rules) == 0
            ]
            private_version_rows = [
                (str(row[0]), str(row[1]))
                for row in conn.execute(
                    "SELECT file_path, version, dist_type FROM dist_file_versions"
                ).fetchall()
                if self._is_private_dist_path(str(row[0]))
                or (row[2] is not None and int(row[2]) == 0)
                or self._classify_dist_path(str(row[0]), exact_rules, dir_rules) == 0
            ]

            dist_version_entries_before = conn.execute("SELECT COUNT(*) FROM dist_file_versions").fetchone()[0]
            if not dry_run:
                if private_manifest_paths:
                    conn.executemany(
                        f"DELETE FROM distribution_manifest WHERE {manifest_path_column} = ?",
                        [(path,) for path in private_manifest_paths],
                    )
                if private_version_rows:
                    conn.executemany(
                        "DELETE FROM dist_file_versions WHERE file_path = ? AND version = ?",
                        private_version_rows,
                    )

            default_rule_count = len(exact_rules) + len(dir_rules)

            candidates = []
            unmatched = 0
            skipped_user = 0
            unreadable = 0
            for relative_path, abs_path in self._iter_distribution_files():
                dist_type = self._classify_dist_path(relative_path, exact_rules, dir_rules)
                if dist_type is None:
                    unmatched += 1
                    continue
                if dist_type == 0:
                    skipped_user += 1
                    continue

                file_hash = self._hash_file(abs_path)
                if file_hash is None:
                    unreadable += 1
                    continue

                candidates.append({
                    "relative_path": relative_path,
                    "dist_type": dist_type,
                    "file_hash": file_hash,
                    "template_hash": file_hash[:16] if dist_type == 1 else None,
                })

            candidate_map = {entry["relative_path"]: entry for entry in candidates}
            stale_current_version_rows = [
                (str(row[0]), str(row[1]))
                for row in conn.execute(
                    "SELECT file_path, version FROM dist_file_versions WHERE version = ?",
                    (version,),
                ).fetchall()
                if str(row[0]) not in candidate_map
            ]
            if stale_current_version_rows and not dry_run:
                conn.executemany(
                    "DELETE FROM dist_file_versions WHERE file_path = ? AND version = ?",
                    stale_current_version_rows,
                )

            stale_current_keys = set(stale_current_version_rows)
            stale_missing_version_rows = [
                (str(row[0]), str(row[1]))
                for row in conn.execute(
                    "SELECT file_path, version FROM dist_file_versions"
                ).fetchall()
                if (str(row[0]), str(row[1])) not in stale_current_keys
                and str(row[0]) not in candidate_map
                and not self._resolve_disk_path(str(row[0])).exists()
            ]
            if stale_missing_version_rows and not dry_run:
                conn.executemany(
                    "DELETE FROM dist_file_versions WHERE file_path = ? AND version = ?",
                    stale_missing_version_rows,
                )

            current_rows = conn.execute(
                "SELECT file_path, file_hash FROM dist_file_versions WHERE version = ?",
                (version,),
            ).fetchall()
            current_version_hashes = {str(row[0]): row[1] for row in current_rows}

            manifest_inserted = 0
            manifest_updated = 0
            version_inserted = 0
            version_conflicts = 0
            now = datetime.now().isoformat()

            for relative_path, candidate in candidate_map.items():
                existing = existing_manifest.get(relative_path)
                needs_insert = existing is None
                needs_update = (
                    not needs_insert
                    and (
                        existing["dist_type"] != candidate["dist_type"]
                        or (
                            candidate["dist_type"] == 1
                            and "template_hash" in manifest_columns
                            and existing.get("template_hash") != candidate["template_hash"]
                        )
                    )
                )

                if needs_insert:
                    manifest_inserted += 1
                    if not dry_run:
                        insert_columns = [manifest_path_column, "dist_type"]
                        insert_values = [relative_path, candidate["dist_type"]]
                        if "template_hash" in manifest_columns:
                            insert_columns.append("template_hash")
                            insert_values.append(candidate["template_hash"])
                        if "description" in manifest_columns:
                            insert_columns.append("description")
                            insert_values.append("Recovered from dist_type_defaults")
                        if "created_at" in manifest_columns:
                            insert_columns.append("created_at")
                            insert_values.append(now)
                        if "updated_at" in manifest_columns:
                            insert_columns.append("updated_at")
                            insert_values.append(now)

                        placeholders = ", ".join("?" for _ in insert_columns)
                        conn.execute(
                            f"INSERT INTO distribution_manifest ({', '.join(insert_columns)}) "
                            f"VALUES ({placeholders})",
                            insert_values,
                        )
                elif needs_update:
                    manifest_updated += 1
                    if not dry_run:
                        updates = ["dist_type = ?"]
                        update_values = [candidate["dist_type"]]
                        if "template_hash" in manifest_columns:
                            updates.append("template_hash = ?")
                            update_values.append(candidate["template_hash"])
                        if "updated_at" in manifest_columns:
                            updates.append("updated_at = ?")
                            update_values.append(now)
                        update_values.append(relative_path)
                        conn.execute(
                            f"UPDATE distribution_manifest SET {', '.join(updates)} "
                            f"WHERE {manifest_path_column} = ?",
                            update_values,
                        )

                existing_hash = current_version_hashes.get(relative_path)
                if existing_hash is None:
                    version_inserted += 1
                    if not dry_run:
                        conn.execute(
                            """
                            INSERT INTO dist_file_versions (file_path, version, file_hash, dist_type, created_at)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                relative_path,
                                version,
                                candidate["file_hash"],
                                candidate["dist_type"],
                                now,
                            ),
                        )
                elif existing_hash != candidate["file_hash"]:
                    version_conflicts += 1

            release_repair = self._recover_release_catalog_entry(conn, version, dry_run)

            if not dry_run:
                conn.commit()

            manifest_entries_after = conn.execute("SELECT COUNT(*) FROM distribution_manifest").fetchone()[0]
            dist_version_entries_after = conn.execute("SELECT COUNT(*) FROM dist_file_versions").fetchone()[0]
            release_entries_after = conn.execute("SELECT COUNT(*) FROM distribution_releases").fetchone()[0]
        finally:
            conn.close()

        payload = {
            "generated_at": datetime.now().isoformat(),
            "dry_run": dry_run,
            "version": version,
            "summary": {
                "default_rules": default_rule_count,
                "candidate_files": len(candidate_map),
                "manifest_inserted": manifest_inserted,
                "manifest_updated": manifest_updated,
                "version_entries_inserted": version_inserted,
                "version_conflicts": version_conflicts,
                "private_manifest_pruned": len(private_manifest_paths),
                "private_version_rows_pruned": len(private_version_rows),
                "stale_current_version_rows_pruned": len(stale_current_version_rows),
                "stale_missing_version_rows_pruned": len(stale_missing_version_rows),
                "user_skipped": skipped_user,
                "unmatched_files": unmatched,
                "unreadable_files": unreadable,
            },
            "db": {
                "manifest_entries_before": len(existing_manifest),
                "manifest_entries_after": manifest_entries_after,
                "dist_file_versions_before": dist_version_entries_before,
                "dist_file_versions_after": dist_version_entries_after,
                "release_entries_before": release_repair["release_entries_before"],
                "release_entries_after": release_entries_after,
            },
            "release": {
                "inserted": release_repair["release_inserted"],
                "bootstrapped": release_repair["release_bootstrapped"],
                "skipped_reason": release_repair["release_skipped_reason"],
                "release_date": release_repair["release_date"],
                "status": release_repair["release_status"],
                "is_stable": release_repair["is_stable"],
                "current_release_registered_before": release_repair["current_release_registered_before"],
                "current_release_registered_after": release_repair["current_release_registered_after"],
            },
            "release_catalog_populated": release_entries_after > 0,
        }

        if json_output:
            return True, self._json_dump(payload)

        output = [
            "=== UPGRADE-REPAIR ===",
            "",
            f"Modus:                   {'DRY-RUN' if dry_run else 'LIVE'}",
            f"Aktuelle Version:        {version}",
            f"Default-Regeln:          {default_rule_count}",
            f"Kandidaten-Dateien:      {len(candidate_map)}",
            f"Manifest vorher/nachher: {len(existing_manifest)} -> {manifest_entries_after}",
            f"Versionen vorher/nachher:{dist_version_entries_before} -> {dist_version_entries_after}",
            f"Release vorher/nachher:  {release_repair['release_entries_before']} -> {release_entries_after}",
            f"Manifest neu:            {manifest_inserted}",
            f"Manifest aktualisiert:   {manifest_updated}",
            f"Versionen neu:           {version_inserted}",
            f"Versionskonflikte:       {version_conflicts}",
            f"USER-Dateien ueberspr.:  {skipped_user}",
            f"Unmatched Dateien:       {unmatched}",
            f"Nicht lesbar:            {unreadable}",
            "",
        ]

        if release_repair["release_inserted"]:
            stable_label = "stable" if release_repair["is_stable"] else release_repair["release_status"]
            output.extend([
                "Release-Recovery:",
                f"  Aktueller Release-Eintrag fuer {version} {'wuerde angelegt' if dry_run else 'angelegt'} werden.",
                f"  Datum: {release_repair['release_date']} | Kanal: {stable_label}",
                "",
            ])
        elif release_repair["release_skipped_reason"] == "unknown_current_version":
            output.extend([
                "Hinweis:",
                "  Release-Katalog konnte nicht automatisch ergaenzt werden,",
                "  weil keine aktuelle Version sicher erkannt wurde. Nutze bei Bedarf:",
                "  bach upgrade repair --version <tag>",
                "",
            ])

        output.extend([
            "Naechste Schritte:",
            "  bach upgrade --status             Upgrade-Metadaten pruefen",
            "  bach upgrade --check              Drift/Updates erneut berechnen",
            "  bach seal repair                  Kernel-Hash auf neue CORE-Basis ziehen",
        ])

        return True, "\n".join(output)

    def _upgrade_category(self, category: str, args: list, dry_run: bool) -> tuple:
        """Upgraded eine Kategorie (core/templates/skills/etc.)."""
        # Nutze RestoreHandler.restore_by_category()
        from hub.restore import RestoreHandler

        # RestoreHandler erwartet BACH_ROOT (nicht SYSTEM_ROOT)
        # In Legacy-Modus: base_path = SYSTEM_ROOT, also base_path.parent = BACH_ROOT
        bach_root = self.base_path.parent
        restore_handler = RestoreHandler(bach_root)

        # Dry-Run Flag aus args extrahieren
        dry_run_flag = "--dry-run" in args or dry_run

        # Kategorien validieren
        valid_categories = [
            "core",
            "templates",
            "agents",
            "skills",
            "hub",
            "tools",
            "connectors",
            "partners",
            "docs",
            "gui",
        ]
        if category not in valid_categories:
            return (False, f"[ERROR] Unbekannte Kategorie: {category}\n\nVerfügbar: {', '.join(valid_categories)}")

        # Führe Kategorie-Restore aus
        success, message = restore_handler.restore_by_category(category, dry_run=dry_run_flag)

        return (success, message)

    def _upgrade_file(self, args: list, dry_run: bool) -> tuple:
        """Upgraded eine einzelne Datei."""
        if not args:
            return (False, "Fehler: Datei fehlt.\n\nBeispiel: bach upgrade hub/backup.py")

        file_path = args[0]
        version = None

        # Parse --version Flag
        if "--version" in args:
            try:
                version_idx = args.index("--version")
                version = args[version_idx + 1]
            except (IndexError, ValueError):
                return (False, "Fehler: --version braucht einen Wert.\n\nBeispiel: bach upgrade hub/backup.py --version v2.6.0")

        # 1. Pruefe ob Datei in dist_file_versions existiert
        conn = self._get_db()
        try:
            rows = conn.execute("""
                SELECT version, file_hash, dist_type
                FROM dist_file_versions
                WHERE file_path = ?
                ORDER BY created_at DESC
            """, (file_path,)).fetchall()

            if not rows:
                return (False, f"[ERROR] Datei nicht in dist_file_versions: {file_path}\n\nNur versionierte Dateien koennen upgraded werden.")

            # 2. Bestimme Zielversion
            if version:
                target_row = None
                for row in rows:
                    if row['version'] == version:
                        target_row = row
                        break
                if not target_row:
                    available = ", ".join([r['version'] for r in rows])
                    return (False, f"[ERROR] Version {version} nicht gefunden.\n\nVerfuegbar: {available}")
            else:
                # Neueste Version
                target_row = rows[0]

            target_version = target_row['version']
            target_hash = target_row['file_hash']
            dist_type = target_row['dist_type']
            dist_type_name = {0: "USER", 1: "TEMPLATE", 2: "CORE"}.get(dist_type, "?")

            # 3. Pruefe aktuelle Datei
            abs_path = self.base_path / file_path if not file_path.startswith('system/') else self.base_path.parent / file_path

            if abs_path.exists():
                import hashlib
                with open(abs_path, 'rb') as f:
                    current_hash = hashlib.sha256(f.read()).hexdigest()

                if current_hash == target_hash:
                    return (True, f"✓ Datei ist bereits auf {target_version}\n\nDatei: {file_path}\nHash: {current_hash[:12]}...\nTyp: {dist_type_name}")

            # 4. Dry-Run?
            if dry_run:
                return (True, f"[DRY-RUN] Wuerde upgraden:\n\nDatei: {file_path}\nZielversion: {target_version}\nTyp: {dist_type_name}")

            # 5. Upgrade durchfuehren via RestoreHandler
            from hub.restore import RestoreHandler
            # RestoreHandler erwartet BACH_ROOT (nicht SYSTEM_ROOT)
            # In Legacy-Modus: base_path = SYSTEM_ROOT, also base_path.parent = BACH_ROOT
            bach_root = self.base_path.parent
            restore_handler = RestoreHandler(bach_root)
            success, msg = restore_handler.restore_file(file_path, target_version)

            if success:
                return (True, f"✓ UPGRADE ERFOLGREICH\n\nDatei: {file_path}\nVersion: {target_version}\nTyp: {dist_type_name}\n\n{msg}")
            else:
                return (False, f"[ERROR] Upgrade fehlgeschlagen:\n\n{msg}")

        finally:
            conn.close()

    def _downgrade_file(self, args: list, dry_run: bool) -> tuple:
        """Downgraded eine einzelne Datei zur vorherigen oder spezifizierten Version."""
        if not args:
            return (False, "Fehler: Datei fehlt.\n\nBeispiel: bach downgrade hub/backup.py")

        file_path = args[0]
        target_version = None

        # Parse --version Flag
        if "--version" in args:
            try:
                version_idx = args.index("--version")
                target_version = args[version_idx + 1]
            except (IndexError, ValueError):
                return (False, "Fehler: --version braucht einen Wert.\n\nBeispiel: bach downgrade hub/backup.py --version v2.5.0")

        # 1. Pruefe ob Datei in dist_file_versions existiert
        conn = self._get_db()
        try:
            rows = conn.execute("""
                SELECT version, file_hash, dist_type, created_at
                FROM dist_file_versions
                WHERE file_path = ?
                ORDER BY created_at DESC
            """, (file_path,)).fetchall()

            if not rows:
                return (False, f"[ERROR] Datei nicht in dist_file_versions: {file_path}\n\nNur versionierte Dateien koennen downgraded werden.")

            if len(rows) < 2 and not target_version:
                return (False, f"[ERROR] Keine aeltere Version verfuegbar fuer: {file_path}\n\nAktuell nur Version {rows[0]['version']} vorhanden.")

            # 2. Bestimme Zielversion
            if target_version:
                # Spezifische Version
                target_row = None
                for row in rows:
                    if row['version'] == target_version:
                        target_row = row
                        break
                if not target_row:
                    available = ", ".join([r['version'] for r in rows])
                    return (False, f"[ERROR] Version {target_version} nicht gefunden.\n\nVerfuegbar: {available}")
            else:
                # Vorherige Version (2. neueste)
                target_row = rows[1]
                target_version = target_row['version']

            current_version = rows[0]['version']
            target_hash = target_row['file_hash']
            dist_type = target_row['dist_type']
            dist_type_name = {0: "USER", 1: "TEMPLATE", 2: "CORE"}.get(dist_type, "?")

            # 3. Warnung
            warning = ""
            if dist_type == 2:  # CORE
                warning = "\n⚠️  WARNUNG: CORE-Datei! Downgrade kann zu Inkompatibilitaeten fuehren.\n"

            # 4. Dry-Run?
            if dry_run or "--dry-run" in args:
                return (True, f"[DRY-RUN] Wuerde downgraden:\n\nDatei: {file_path}\nAktuell: {current_version}\nZiel: {target_version}\nTyp: {dist_type_name}{warning}")

            # 5. Downgrade durchfuehren via RestoreHandler
            from hub.restore import RestoreHandler
            # RestoreHandler erwartet BACH_ROOT (nicht SYSTEM_ROOT)
            bach_root = self.base_path.parent
            restore_handler = RestoreHandler(bach_root)
            success, msg = restore_handler.restore_file(file_path, target_version)

            if success:
                return (True, f"✓ DOWNGRADE ERFOLGREICH\n\nDatei: {file_path}\nVon: {current_version}\nAuf: {target_version}\nTyp: {dist_type_name}{warning}\n{msg}")
            else:
                return (False, f"[ERROR] Downgrade fehlgeschlagen:\n\n{msg}")

        finally:
            conn.close()
