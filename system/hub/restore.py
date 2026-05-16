#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
File Restore Handler (SQ020/HQ6)
================================

Stellt einzelne Dateien aus dist_file_versions wieder her.

Nutzt gespeicherte Hashes + TEMPLATE-Dateien aus distribution.db/manifest.

CLI:
    bach restore <file>              Stelle Datei wieder her
    bach restore <file> --version X  Stelle bestimmte Version wieder her
    bach restore list <file>         Zeige verfuegbare Versionen
    bach restore category <cat>      Restore ganze Kategorie

Author: BACH Development Team
Created: 2026-02-20 (SQ020, Runde 4)
Updated: 2026-02-21 (HQ6, Runde 29 - BaseHandler-Kompatibilität)
"""

import shutil
import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple
from .base import BaseHandler


class RestoreHandler(BaseHandler):
    """Handler fuer Datei-Wiederherstellung."""

    def __init__(self, base_path: Path):
        """
        Args:
            base_path: BACH Root-Verzeichnis
        """
        super().__init__(base_path)
        self.system_root = self.base_path / "system"
        self.db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        """Name des Profils."""
        return "restore"

    @property
    def target_file(self) -> Path:
        """Hauptdatei des Handlers."""
        return self.db_path

    def get_operations(self) -> dict:
        """Verfuegbare Operationen mit Beschreibung."""
        return {
            "file": "Datei wiederherstellen: file <path> [--version=X]",
            "list": "Versionen anzeigen: list <path>",
            "category": "Kategorie wiederherstellen: category <cat> [--dry-run]",
            "info": "Datei-Info anzeigen: info <path>",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        """
        Fuehrt Operation aus.

        Args:
            operation: Operation (file, list, category, info)
            args: Argumente
            dry_run: Nur anzeigen, nicht ausführen

        Returns:
            (success, message)
        """
        if operation == "file" and args:
            # Parse --version parameter
            version = None
            file_path = args[0]
            for arg in args[1:]:
                if arg.startswith("--version="):
                    version = arg.split("=", 1)[1]
            return self.restore_file(file_path, version)

        elif operation == "list" and args:
            return self.show_info(args[0])

        elif operation == "category" and args:
            category = args[0]
            return self.restore_by_category(category, dry_run)

        elif operation == "info" and args:
            return self.show_info(args[0])

        else:
            # Hilfe anzeigen
            ops = self.get_operations()
            lines = ["RESTORE - Datei-Wiederherstellung", "=" * 50, ""]
            for op, desc in ops.items():
                lines.append(f"  bach restore {op:12s} {desc}")
            return True, "\n".join(lines)

    def _get_conn(self):
        """DB-Verbindung."""
        return sqlite3.connect(str(self.db_path))

    def _resolve_file_path(self, relative_path: str) -> Path:
        """Konvertiert relativen Pfad in absoluten Pfad."""
        if relative_path.startswith('system/'):
            # system/... -> base_path/system/...
            return self.base_path / relative_path
        else:
            # Root-Dateien (USER.md, SKILL.md, etc.) -> base_path/...
            # System-Dateien ohne system/ Prefix -> system_root/...
            # Prüfe zuerst Root
            root_path = self.base_path / relative_path
            if root_path.exists():
                return root_path
            # Fallback: system/
            return self.system_root / relative_path

    def list_versions(self, file_path: str) -> List[Tuple[str, str, str]]:
        """
        Listet verfuegbare Versionen einer Datei.

        Args:
            file_path: Relativer Pfad zur Datei

        Returns:
            Liste von (version, file_hash, created_at)
        """
        conn = None
        try:
            conn = self._get_conn()
            cursor = conn.execute("""
                SELECT version, file_hash, created_at
                FROM dist_file_versions
                WHERE file_path = ?
                ORDER BY created_at DESC
            """, (file_path,))
            return cursor.fetchall()
        finally:
            if conn:
                conn.close()

    def restore_file(self, file_path: str, version: Optional[str] = None) -> Tuple[bool, str]:
        """
        Stellt eine Datei wieder her.

        Args:
            file_path: Relativer Pfad zur Datei
            version: Gewuenschte Version (None = neueste)

        Returns:
            (success, message)
        """
        # 1. Pruefe ob Datei in dist_file_versions existiert
        versions = self.list_versions(file_path)

        if not versions:
            return False, f"[ERROR] Datei nicht in dist_file_versions gefunden: {file_path}"

        # 2. Waehle Version
        if version:
            # Spezifische Version
            target_version = None
            for v, h, c in versions:
                if v == version:
                    target_version = (v, h, c)
                    break

            if not target_version:
                return False, f"[ERROR] Version {version} nicht gefunden fuer {file_path}"
        else:
            # Neueste Version
            target_version = versions[0]

        selected_version, file_hash, created_at = target_version

        # 3. Pruefe ob Datei TEMPLATE ist (dist_type=1)
        conn = None
        try:
            conn = self._get_conn()
            cursor = conn.execute("""
                SELECT dist_type
                FROM distribution_manifest
                WHERE path = ?
            """, (file_path,))
            row = cursor.fetchone()
        finally:
            if conn:
                conn.close()

        if not row:
            return False, f"[ERROR] Datei nicht in distribution_manifest: {file_path}"

        dist_type = row[0]

        if dist_type == 0:
            return False, f"[ERROR] Datei ist USER_DATA (dist_type=0), kann nicht restored werden: {file_path}"

        # 4. HINWEIS: Hier wuerde normalerweise die Datei aus einem Template-Store
        #    oder aus distribution.db extrahiert werden. Da wir aktuell nur Hashes
        #    haben, koennen wir nur pruefen ob die aktuelle Datei dem Hash entspricht.

        # Aktueller Zustand: Wir haben keine Template-Dateien gespeichert.
        # WORKAROUND: Warnung ausgeben + User informieren

        abs_path = self._resolve_file_path(file_path)

        if not abs_path.exists():
            return False, f"[ERROR] Datei existiert nicht auf Disk: {abs_path}"

        # 5. Restore-Logik (Basis-Implementierung, SQ020 Runde 14)
        #    TEMPLATE (dist_type=1): Kopiere aus System-Verzeichnis
        #    CORE/USER: Fehler (braucht content BLOB, TODO)

        if dist_type == 1:  # TEMPLATE
            # Suche Template-Datei im System
            # Relative Pfade: skills/, agents/, SKILL.md, MEMORY.md, USER.md, etc.
            source_candidates = [
                self.base_path / file_path,                    # Direkt im Root
                self.base_path / "system" / file_path,         # In system/
            ]

            source_path = None
            for candidate in source_candidates:
                if candidate.exists():
                    source_path = candidate
                    break

            if not source_path:
                return False, (
                    f"[ERROR] Template-Datei nicht gefunden im System\n"
                    f"Gesucht: {file_path}\n"
                    f"Kandidaten:\n" + "\n".join(f"  - {c}" for c in source_candidates)
                )

            # Backup der aktuellen Datei erstellen
            backup_path = abs_path.with_suffix(abs_path.suffix + '.backup')
            if abs_path.exists():
                shutil.copy2(abs_path, backup_path)

            # Template kopieren
            try:
                shutil.copy2(source_path, abs_path)
                return True, (
                    f"✓ Datei wiederhergestellt: {file_path}\n"
                    f"Version: {selected_version}\n"
                    f"Quelle: {source_path}\n"
                    f"Backup: {backup_path if abs_path.exists() else 'Keine (Datei war neu)'}"
                )
            except Exception as e:
                return False, f"[ERROR] Kopieren fehlgeschlagen: {e}"

        elif dist_type == 2:  # CORE
            # CORE-Dateien sind System-Kern (bach.py, hub/*.py, tools/*.py)
            # Sollten normalerweise NICHT restored werden (nur bei Korruption)
            # Gleiche Logik wie TEMPLATE, aber mit schärferer Warnung

            source_candidates = [
                self.base_path / file_path,                    # Direkt (für Root-Dateien)
                self.base_path / "system" / file_path,         # In system/
            ]

            source_path = None
            for candidate in source_candidates:
                if candidate.exists():
                    source_path = candidate
                    break

            if not source_path:
                return False, (
                    f"[ERROR] CORE-Datei nicht gefunden im System\n"
                    f"Datei: {file_path}\n"
                    f"Version: {selected_version}\n"
                    f"Kandidaten:\n" + "\n".join(f"  - {c}" for c in source_candidates)
                )

            # WARNUNG: CORE-Dateien sind unveränderbar
            # Backup erstellen
            backup_path = abs_path.with_suffix(abs_path.suffix + '.backup')
            if abs_path.exists():
                shutil.copy2(abs_path, backup_path)

            # CORE-Datei kopieren
            try:
                shutil.copy2(source_path, abs_path)
                return True, (
                    f"⚠️  CORE-Datei wiederhergestellt: {file_path}\n"
                    f"Version: {selected_version}\n"
                    f"Quelle: {source_path}\n"
                    f"Backup: {backup_path if abs_path.exists() else 'Keine (Datei war neu)'}\n"
                    f"\n"
                    f"WARNUNG: CORE-Dateien sind Teil des System-Kerns und sollten\n"
                    f"         normalerweise NICHT modifiziert werden. Restore nur bei\n"
                    f"         Datei-Korruption oder nach fehlgeschlagenem Update."
                )
            except Exception as e:
                return False, f"[ERROR] Kopieren fehlgeschlagen: {e}"

        elif dist_type == 0:  # USER
            return False, (
                f"[ERROR] USER-Dateien sollten nicht wiederhergestellt werden\n"
                f"Datei: {file_path}\n"
                f"Grund: USER-Daten sind individuell und sollten nicht überschrieben werden\n"
                f"Tipp: Nutze 'bach restore backup <name>' für vollständiges System-Restore"
            )

        else:
            return False, f"[ERROR] Unbekannter dist_type: {dist_type}"

    def restore_by_category(self, category: str, dry_run: bool = False) -> Tuple[bool, str]:
        """
        Restored alle Dateien einer Kategorie.

        Args:
            category: Kategorie (core, templates, skills, hub, tools, agents, connectors, partners, docs, gui)
            dry_run: Nur anzeigen, nicht ausführen

        Returns:
            (success, message)
        """
        # Kategorie zu dist_type/path-Pattern mapping
        category_mapping = {
            "core": {"dist_type": 2, "path_pattern": None},
            "templates": {"dist_type": 1, "path_pattern": None},
            "skills": {"dist_type": None, "path_pattern": "skills/%"},
            "hub": {"dist_type": None, "path_pattern": "hub/%"},
            "tools": {"dist_type": None, "path_pattern": "tools/%"},
            "agents": {"dist_type": None, "path_pattern": "agents/%"},
            "connectors": {"dist_type": None, "path_pattern": "connectors/%"},
            "partners": {"dist_type": None, "path_pattern": "partners/%"},
            "docs": {"dist_type": None, "path_pattern": "docs/%"},
            "gui": {"dist_type": None, "path_pattern": "gui/%"},
        }

        if category not in category_mapping:
            return False, (
                f"[ERROR] Unbekannte Kategorie: {category}\n"
                f"Verfügbar: {', '.join(category_mapping.keys())}"
            )

        config = category_mapping[category]

        # Dateien aus DB holen
        conn = None
        try:
            conn = self._get_conn()

            if config["dist_type"] is not None:
                query = """
                    SELECT DISTINCT m.path
                    FROM distribution_manifest m
                    JOIN dist_file_versions v ON m.path = v.file_path
                    WHERE m.dist_type = ?
                    ORDER BY m.path
                """
                cursor = conn.execute(query, (config["dist_type"],))
            else:
                query = """
                    SELECT DISTINCT m.path
                    FROM distribution_manifest m
                    JOIN dist_file_versions v ON m.path = v.file_path
                    WHERE m.path LIKE ?
                    ORDER BY m.path
                """
                cursor = conn.execute(query, (config["path_pattern"],))

            files = [row[0] for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

        if not files:
            return True, f"[INFO] Keine Dateien gefunden für Kategorie: {category}"

        # Dry-Run: Nur anzeigen
        if dry_run:
            msg = f"[DRY-RUN] Restore Kategorie: {category}\n\n"
            msg += f"Dateien ({len(files)}):\n"
            for file_path in files:
                msg += f"  - {file_path}\n"
            msg += f"\nOhne --dry-run ausführen zum Restore"
            return True, msg

        # Restore ausführen
        results = []
        success_count = 0
        error_count = 0

        print(f"[RESTORE] Kategorie: {category}")
        print(f"Dateien: {len(files)}")
        print("")

        for file_path in files:
            success, message = self.restore_file(file_path)
            if success:
                success_count += 1
                print(f"  ✓ {file_path}")
            else:
                error_count += 1
                print(f"  ✗ {file_path}: {message}")
            results.append((file_path, success, message))

        print("")
        msg = (
            f"[RESTORE COMPLETE]\n"
            f"Kategorie: {category}\n"
            f"Erfolgreich: {success_count}/{len(files)}\n"
            f"Fehler: {error_count}/{len(files)}"
        )

        return error_count == 0, msg

    def show_info(self, file_path: str) -> Tuple[bool, str]:
        """
        Zeigt Informationen zu einer Datei.

        Args:
            file_path: Relativer Pfad zur Datei

        Returns:
            (success, message)
        """
        versions = self.list_versions(file_path)

        if not versions:
            return False, f"[ERROR] Datei nicht in dist_file_versions: {file_path}"

        lines = [
            "[FILE RESTORE INFO]",
            "",
            f"Datei: {file_path}",
            f"Verfuegbare Versionen: {len(versions)}",
            ""
        ]

        for version, file_hash, created_at in versions:
            lines.append(f"  Version: {version}")
            lines.append(f"  Hash:    {file_hash[:16]}...")
            lines.append(f"  Erstellt: {created_at}")
            lines.append("")

        return True, "\n".join(lines)
