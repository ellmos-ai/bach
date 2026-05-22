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
import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional, Dict
from hub.base import BaseHandler


class UpgradeHandler(BaseHandler):
    """Handler fuer selektive Upgrades und Downgrades."""

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

OPTIONEN:
  --dry-run                            Vorschau ohne Aenderungen
  --force                              Ueberschreibe lokale Aenderungen
  --no-backup                          Kein Backup vor Update

DATENBANK: bach.db / dist_file_versions, distribution_releases, distribution_manifest

IMPLEMENTIERT (Phase 1-4/4):
  - Verfuegbare Versionen anzeigen (--list)
  - Status anzeigen (--status)
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
            total_tracked = conn.execute("SELECT COUNT(DISTINCT file_path) FROM dist_file_versions").fetchone()[0]
            total_versions = conn.execute("SELECT COUNT(*) FROM dist_file_versions").fetchone()[0]

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
                    "releases": release_entries,
                }
                return True, self._json_dump(payload)

            output = [
                "=== UPGRADE SYSTEM STATUS ===",
                "",
                "Statistiken:",
                f"  Nachverfolgte Dateien: {total_tracked}",
                f"  Gesamt-Versionen:      {total_versions}",
                "",
            ]

            if releases:
                output.append("Verfuegbare Releases:")
                for r in releases:
                    stable = "stable" if r['is_stable'] else r['status'] or "unstable"
                    date = r['release_date'][:10] if r['release_date'] else "unbekannt"
                    output.append(f"  {r['version']:<12}  {date}  [{stable}]")
                output.append("")

            output.extend([
                "Befehle:",
                "  bach upgrade --check              Nach Updates pruefen",
                "  bach upgrade --list <file>        Verfuegbare Versionen anzeigen",
                "  bach upgrade core                 CORE-Komponenten upgraden",
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
        finally:
            conn.close()

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
                    "upgrade_candidates": [],
                    "local_modifications": [],
                    "missing_files": [],
                    "unreadable_files": [],
                    "no_tracked_versions": True,
                }
                return True, self._json_dump(payload)

            output = [
                "=== UPGRADE-CHECK ===",
                "",
                "[INFO] Keine versionierten Dateien in dist_file_versions gefunden.",
                "",
                "Befehle:",
                "  bach upgrade --status             Upgrade-Status anzeigen",
                "  bach upgrade --list <file>        Verfuegbare Versionen anzeigen",
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

        output.extend([
            "Befehle:",
            "  bach upgrade <file>              Einzeldatei aktualisieren",
            "  bach upgrade core --dry-run      CORE-Dateien pruefen",
            "  bach upgrade docs --dry-run      Doku-Dateien pruefen",
            "  bach upgrade --list <file>       Versionshistorie anzeigen",
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
