#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
BACH Distribution Manager v2.0.0
================================

Einheitliches Distribution-System basierend auf dist_type (0/1/2).
Konsolidiert aus dem ehemaligen Tier-System (distribution_system.py).

Features:
- Identity Management (System-Identitaet + JSON-Datei)
- Siegel-System (Integritaetspruefung ueber CORE-Dateien)
- Snapshots (Point-in-Time Backups via distribution_manifest)
- Releases (Offizielle Versionen als ZIP)
- Restore (Wiederherstellung aus Distribution-ZIP)
- Status (dist_type-basierte Statistiken)

Datum: 2026-02-18
"""

import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Windows Console UTF-8 Support
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass


class DistributionManager:
    """Einheitlicher Distribution Manager auf dist_type-Basis."""

    def __init__(self, db_path=None, root_path=None):
        """
        Args:
            db_path: Pfad zur bach.db (default: aus bach_paths)
            root_path: BACH Root-Verzeichnis (default: aus bach_paths)
        """
        try:
            from hub.bach_paths import BACH_DB, BACH_ROOT, DATA_DIR
            self.db_path = Path(db_path) if db_path else BACH_DB
            self.root = Path(root_path) if root_path else BACH_ROOT
            self.data_dir = DATA_DIR
        except ImportError:
            # Fallback: Pfade relativ berechnen
            script_dir = Path(__file__).parent
            system_root = script_dir.parent
            self.root = system_root.parent
            self.data_dir = system_root / "data"
            self.db_path = self.data_dir / "bach.db"
            if db_path:
                self.db_path = Path(db_path)
            if root_path:
                self.root = Path(root_path)

        self.identity_file = self.data_dir / "identity.json"
        self.version_file = self.data_dir / "version.json"

    # =========================================================================
    # IDENTITY MANAGEMENT
    # =========================================================================

    def init_identity(self, name: str = "BACH-Instanz") -> Dict:
        """Initialisiert oder laedt System-Identitaet."""
        if self.identity_file.exists():
            return self.load_identity()

        instance_id = self._generate_instance_id()
        now = datetime.now().isoformat()

        identity = {
            "instance": {
                "id": instance_id,
                "name": name,
                "created": now,
                "forked_from": None
            },
            "seal": {
                "status": "intact",
                "broken_at": None,
                "broken_by": None,
                "broken_reason": None,
                "kernel_hash": None,
                "kernel_version": None,
                "last_verified": None
            },
            "origin": {
                "release": None,
                "release_date": None
            }
        }

        identity["seal"]["kernel_hash"] = self._calculate_kernel_hash()
        identity["seal"]["last_verified"] = now

        if self.version_file.exists():
            try:
                v_data = json.loads(self.version_file.read_text(encoding='utf-8'))
                identity["seal"]["kernel_version"] = v_data.get("version", "1.0.0")
            except (json.JSONDecodeError, OSError):
                pass

        self._save_identity(identity)
        self._save_identity_to_db(identity)

        print(f"[OK] Identitaet erstellt: {instance_id}")
        return identity

    def load_identity(self) -> Optional[Dict]:
        """Laedt bestehende Identitaet aus JSON-Datei."""
        if not self.identity_file.exists():
            return None
        try:
            return json.loads(self.identity_file.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            return None

    def _save_identity(self, identity: Dict):
        """Speichert Identitaet in JSON-Datei."""
        self.identity_file.write_text(
            json.dumps(identity, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )

    def _save_identity_to_db(self, identity: Dict):
        """Speichert Identitaet in Datenbank."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO instance_identity (
                    instance_id, instance_name, created, forked_from,
                    seal_status, seal_broken_at, seal_broken_by, seal_broken_reason,
                    kernel_hash, kernel_version, seal_last_verified,
                    base_release, base_release_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                identity["instance"]["id"],
                identity["instance"]["name"],
                identity["instance"]["created"],
                identity["instance"].get("forked_from"),
                identity["seal"]["status"],
                identity["seal"].get("broken_at"),
                identity["seal"].get("broken_by"),
                identity["seal"].get("broken_reason"),
                identity["seal"].get("kernel_hash"),
                identity["seal"].get("kernel_version"),
                identity["seal"].get("last_verified"),
                identity["origin"].get("release"),
                identity["origin"].get("release_date")
            ))
            conn.commit()

    def _generate_instance_id(self) -> str:
        """Generiert eindeutige Instanz-ID."""
        return f"bach-{datetime.now().strftime('%Y-%m-%d')}-{secrets.token_hex(2)}"

    # =========================================================================
    # SEAL (SIEGEL) MANAGEMENT
    # =========================================================================

    def _calculate_kernel_hash(self) -> str:
        """Berechnet SHA256 ueber alle CORE-Dateien (dist_type=2) aus distribution_manifest."""
        sha256 = hashlib.sha256()
        kernel_files = sorted(self._get_kernel_files())

        for filepath in kernel_files:
            if filepath.exists():
                sha256.update(str(filepath.relative_to(self.root)).encode())
                sha256.update(filepath.read_bytes())

        return f"sha256:{sha256.hexdigest()}"

    def _get_kernel_files(self) -> List[Path]:
        """Gibt Liste aller CORE-Dateien (dist_type=2) aus distribution_manifest zurueck."""
        kernel_files = []
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.execute(
                    "SELECT path FROM distribution_manifest WHERE dist_type = 2 ORDER BY path"
                )
                for (rel_path,) in cursor:
                    # Wildcards ueberspringen
                    if '*' in rel_path:
                        continue
                    # Pfad ist relativ zu system/ (BACH_ROOT/system/)
                    system_root = self.root / "system"
                    filepath = system_root / rel_path
                    if not filepath.exists():
                        # Alternativ: relativ zu BACH_ROOT
                        filepath = self.root / rel_path
                    if filepath.exists() and filepath.is_file():
                        kernel_files.append(filepath)
        except sqlite3.OperationalError:
            # Fallback: Hardcoded Kernel-Dateien
            fallback_files = [
                "SKILL.md", "bach.py", "bach_api.py",
                "data/version.json", "data/identity.json"
            ]
            system_root = self.root / "system"
            for rel in fallback_files:
                fp = system_root / rel
                if not fp.exists():
                    fp = self.root / rel
                if fp.exists():
                    kernel_files.append(fp)

        return kernel_files

    def verify_seal(self) -> Tuple[bool, str]:
        """Prueft ob Siegel intakt ist."""
        identity = self.load_identity()
        if not identity:
            return False, "Keine Identitaet gefunden"

        if identity["seal"]["status"] == "broken":
            return False, f"Siegel gebrochen am {identity['seal']['broken_at']}"

        current_hash = self._calculate_kernel_hash()
        stored_hash = identity["seal"].get("kernel_hash")

        if current_hash != stored_hash:
            return False, "Kernel-Hash abweichend"

        identity["seal"]["last_verified"] = datetime.now().isoformat()
        self._save_identity(identity)

        return True, "Siegel intakt"

    def break_seal(self, reason: str, who: str = "user", force: bool = False) -> bool:
        """Bricht das Siegel - macht aus offizieller Version einen Fork."""
        identity = self.load_identity()
        if not identity:
            print("[ERR] Keine Identitaet gefunden")
            return False

        if identity["seal"]["status"] == "broken":
            print("[INFO] Siegel bereits gebrochen")
            return True

        if not force:
            print("\n" + "=" * 60)
            print("WARNUNG: Du brichst das Siegel!")
            print("=" * 60)
            print(f"\nDiese Installation wird als Fork markiert.")
            print(f"Grund: {reason}")
            confirm = input("\nFortfahren? [j/N]: ").strip().lower()
            if confirm != 'j':
                print("[ABBRUCH] Siegel bleibt intakt")
                return False

        now = datetime.now().isoformat()
        old_id = identity["instance"]["id"]
        new_id = self._generate_instance_id()

        identity["seal"]["status"] = "broken"
        identity["seal"]["broken_at"] = now
        identity["seal"]["broken_by"] = who
        identity["seal"]["broken_reason"] = reason
        identity["instance"]["forked_from"] = old_id
        identity["instance"]["id"] = new_id

        self._save_identity(identity)
        self._save_identity_to_db(identity)

        print(f"\n[OK] Siegel gebrochen -> Fork erstellt: {new_id}")
        return True

    # =========================================================================
    # SNAPSHOTS
    # =========================================================================

    def create_snapshot(self, name: str, description: str = None,
                        snapshot_type: str = 'manual') -> Optional[int]:
        """Erstellt benannten Snapshot basierend auf distribution_manifest."""
        now = datetime.now().isoformat()

        with sqlite3.connect(str(self.db_path)) as conn:
            # Pruefen ob Name schon existiert
            if conn.execute("SELECT id FROM distribution_snapshots WHERE name = ?", (name,)).fetchone():
                print(f"[ERR] Snapshot '{name}' existiert bereits")
                return None

            # Snapshot erstellen
            cursor = conn.execute("""
                INSERT INTO distribution_snapshots (name, snapshot_date, description, snapshot_type)
                VALUES (?, ?, ?, ?)
            """, (name, now, description, snapshot_type))
            snapshot_id = cursor.lastrowid

            # Dateien aus distribution_manifest erfassen
            system_root = self.root / "system"
            file_count = 0
            total_size = 0

            manifest_rows = conn.execute(
                "SELECT id, path FROM distribution_manifest WHERE dist_type >= 1"
            ).fetchall()

            for manifest_id, rel_path in manifest_rows:
                if '*' in rel_path:
                    continue

                filepath = system_root / rel_path
                if not filepath.exists():
                    filepath = self.root / rel_path
                if not filepath.exists() or not filepath.is_file():
                    continue

                try:
                    file_size = filepath.stat().st_size
                    file_checksum = f"sha256:{hashlib.sha256(filepath.read_bytes()).hexdigest()}"
                except OSError:
                    continue

                conn.execute("""
                    INSERT INTO distribution_snapshot_files
                    (snapshot_id, manifest_id, file_checksum, file_size)
                    VALUES (?, ?, ?, ?)
                """, (snapshot_id, manifest_id, file_checksum, file_size))

                file_count += 1
                total_size += file_size

            conn.execute(
                "UPDATE distribution_snapshots SET file_count = ?, total_size = ? WHERE id = ?",
                (file_count, total_size, snapshot_id)
            )
            conn.commit()

        print(f"[OK] Snapshot '{name}' erstellt ({file_count} Dateien)")
        return snapshot_id

    def list_snapshots(self, limit: int = 20) -> List[Dict]:
        """Listet alle Snapshots."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM distribution_snapshots ORDER BY snapshot_date DESC LIMIT ?",
                (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def auto_daily_snapshot(self) -> Optional[int]:
        """Erstellt automatischen taeglichen Snapshot."""
        today = datetime.now().strftime("%Y-%m-%d")
        name = f"daily-{today}"

        with sqlite3.connect(str(self.db_path)) as conn:
            if conn.execute("SELECT id FROM distribution_snapshots WHERE name = ?", (name,)).fetchone():
                return None

        return self.create_snapshot(name, f"Automatischer taeglicher Snapshot fuer {today}", "daily")

    # =========================================================================
    # RELEASES
    # =========================================================================

    def create_release(self, version: str, description: str = None,
                       changelog: str = None) -> Optional[int]:
        """Erstellt neues Release."""
        with sqlite3.connect(str(self.db_path)) as conn:
            # Pruefen ob Version schon existiert
            if conn.execute("SELECT id FROM distribution_releases WHERE version = ?", (version,)).fetchone():
                print(f"[ERR] Release '{version}' existiert bereits")
                return None

            # Kernel-Hash berechnen
            kernel_hash = self._calculate_kernel_hash()

            # Snapshot fuer Release erstellen
            snapshot_name = f"release-{version}"
            snapshot_id = self.create_snapshot(snapshot_name, f"Release {version}", "release")

            cursor = conn.execute("""
                INSERT INTO distribution_releases
                (version, description, changelog, kernel_hash, snapshot_id, status)
                VALUES (?, ?, ?, ?, ?, 'draft')
            """, (version, description, changelog, kernel_hash, snapshot_id))
            release_id = cursor.lastrowid
            conn.commit()

        print(f"[OK] Release erstellt: {version} (ID: {release_id})")
        return release_id

    def list_releases(self, limit: int = 20) -> List[Dict]:
        """Listet alle Releases."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM distribution_releases ORDER BY release_date DESC LIMIT ?",
                (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def build_release(self, release_id: int, output_dir: Path = None) -> Optional[Path]:
        """Baut Release als ZIP-Archiv."""
        if output_dir is None:
            try:
                from hub.bach_paths import DIST_DIR
                output_dir = DIST_DIR
            except ImportError:
                output_dir = self.root / "system" / "dist"

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute(
                "SELECT version, status FROM distribution_releases WHERE id = ?",
                (release_id,)
            )
            row = cursor.fetchone()
            if not row:
                print(f"[ERR] Release nicht gefunden: {release_id}")
                return None

            version, status = row

            # Alle CORE- und TEMPLATE-Dateien aus distribution_manifest
            cursor = conn.execute(
                "SELECT path, dist_type FROM distribution_manifest WHERE dist_type >= 1"
            )
            files = cursor.fetchall()

        system_root = self.root / "system"
        zip_name = f"BACH_{version}_{datetime.now().strftime('%Y%m%d')}.zip"
        zip_path = output_dir / zip_name

        included = 0
        with zipfile.ZipFile(str(zip_path), 'w', zipfile.ZIP_DEFLATED) as zf:
            for rel_path, dist_type in files:
                if '*' in rel_path:
                    continue

                # Root-Dateien (ohne Slash) zuerst im Root suchen, dann in system/
                # System-Dateien (mit Slash) zuerst in system/ suchen, dann im Root
                if '/' not in rel_path and '\\' not in rel_path:
                    # Root-Datei (z.B. "setup.py", "bach.py", "README.md")
                    src = self.root / rel_path
                    if not src.exists():
                        src = system_root / rel_path  # Fallback
                else:
                    # Unterverzeichnis (z.B. "system/bach.py", "hub/settings.py")
                    src = system_root / rel_path
                    if not src.exists():
                        src = self.root / rel_path

                if src.exists() and src.is_file():
                    zf.write(str(src), f"BACH/{rel_path}")
                    included += 1

        # ZIP-Pfad in Release speichern
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "UPDATE distribution_releases SET dist_zip_path = ? WHERE id = ?",
                (str(zip_path), release_id)
            )
            conn.commit()

        print(f"[OK] Release gebaut: {zip_path} ({included} Dateien)")
        return zip_path

    def extract_to_folder(self, release_id: int, output_dir: Path,
                          dry_run: bool = False) -> Dict:
        """
        Extrahiert Release direkt in einen Ordner (ohne ZIP zu erstellen).

        Für Build-Prozesse wo das ZIP nicht benötigt wird.

        Args:
            release_id: ID des Release aus distribution_releases
            output_dir: Zielordner (wird erstellt falls nicht vorhanden)
            dry_run: Wenn True, zeigt nur was kopiert würde

        Returns:
            Dict mit Statistiken: {'copied': [...], 'skipped': [...], 'errors': [...]}
        """
        output_dir = Path(output_dir)
        result = {
            "release_id": release_id,
            "output_dir": str(output_dir),
            "dry_run": dry_run,
            "copied": [],
            "skipped": [],
            "errors": []
        }

        # Release-Info aus DB holen
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute(
                "SELECT version, status FROM distribution_releases WHERE id = ?",
                (release_id,)
            )
            row = cursor.fetchone()
            if not row:
                result["errors"].append(f"Release nicht gefunden: {release_id}")
                return result

            version, status = row

            # Alle CORE- und TEMPLATE-Dateien aus distribution_manifest
            cursor = conn.execute(
                "SELECT path, dist_type FROM distribution_manifest WHERE dist_type >= 1"
            )
            files = cursor.fetchall()

        system_root = self.root / "system"

        if dry_run:
            print(f"\n[DRY-RUN] Würde Release {version} nach {output_dir} extrahieren:")
            for rel_path, dist_type in files[:10]:
                if '*' not in rel_path:
                    print(f"  {rel_path}")
            if len(files) > 10:
                print(f"  ... und {len(files) - 10} weitere")
            return result

        # Zielordner erstellen
        output_dir.mkdir(parents=True, exist_ok=True)

        # Dateien kopieren
        for rel_path, dist_type in files:
            if '*' in rel_path:
                result["skipped"].append({"path": rel_path, "reason": "Wildcard"})
                continue

            # Quelle finden
            # Root-Dateien (ohne Slash) zuerst im Root suchen, dann in system/
            # System-Dateien (mit Slash) zuerst in system/ suchen, dann im Root
            if '/' not in rel_path and '\\' not in rel_path:
                # Root-Datei (z.B. "setup.py", "bach.py", "README.md")
                src = self.root / rel_path
                if not src.exists():
                    src = system_root / rel_path  # Fallback
            else:
                # Unterverzeichnis (z.B. "system/bach.py", "hub/settings.py")
                src = system_root / rel_path
                if not src.exists():
                    src = self.root / rel_path

            if not src.exists() or not src.is_file():
                result["skipped"].append({"path": rel_path, "reason": "Nicht gefunden"})
                continue

            # Ziel
            dest = output_dir / rel_path

            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dest))
                result["copied"].append(rel_path)
            except Exception as e:
                result["errors"].append({"path": rel_path, "error": str(e)})

        print(f"\n=== Release Extraction ===")
        print(f"Release: {version} (ID {release_id})")
        print(f"Ziel: {output_dir}")
        print(f"Kopiert: {len(result['copied'])}")
        print(f"Übersprungen: {len(result['skipped'])}")
        print(f"Fehler: {len(result['errors'])}")

        return result

    # =========================================================================
    # RESTORE FROM DISTRIBUTION ZIP
    # =========================================================================

    def restore_from_dist(self, zip_path: Path, target_dir: Path = None,
                          create_backup: bool = True, dry_run: bool = False) -> Dict:
        """Stellt BACH aus einem Distribution-ZIP wieder her."""
        zip_path = Path(zip_path)
        target_dir = Path(target_dir) if target_dir else self.root

        result = {
            "zip_path": str(zip_path),
            "target_dir": str(target_dir),
            "dry_run": dry_run,
            "restored": [],
            "skipped": [],
            "errors": [],
            "backup_snapshot": None
        }

        if not zip_path.exists():
            result["errors"].append(f"ZIP nicht gefunden: {zip_path}")
            return result

        if not zipfile.is_zipfile(str(zip_path)):
            result["errors"].append(f"Keine gueltige ZIP-Datei: {zip_path}")
            return result

        # Backup-Snapshot erstellen
        if create_backup and not dry_run:
            backup_name = f"pre-dist-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            try:
                self.create_snapshot(backup_name, f"Vor Distribution-Restore aus {zip_path.name}", "pre-update")
                result["backup_snapshot"] = backup_name
            except Exception as e:
                print(f"[WARN] Backup-Snapshot fehlgeschlagen: {e}")

        # ZIP analysieren und extrahieren
        with zipfile.ZipFile(str(zip_path), 'r') as zf:
            members = zf.namelist()

            # Praefix ermitteln
            prefix = ""
            if members and "/" in members[0]:
                prefix = members[0].split("/")[0] + "/"

            if dry_run:
                print(f"\n[DRY-RUN] Wuerde {len(members)} Eintraege aus {zip_path.name} extrahieren:")
                for member in members[:10]:
                    rel_path = member[len(prefix):] if member.startswith(prefix) else member
                    if rel_path:
                        print(f"  {rel_path}")
                if len(members) > 10:
                    print(f"  ... und {len(members) - 10} weitere")
                return result

            # Extrahieren
            for member in members:
                if member.endswith("/"):
                    continue

                rel_path = member[len(prefix):] if member.startswith(prefix) else member
                if not rel_path:
                    continue

                dest = target_dir / rel_path

                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src:
                        content = src.read()
                        dest.write_bytes(content)
                    result["restored"].append(rel_path)
                except Exception as e:
                    result["errors"].append({"file": rel_path, "error": str(e)})

        print(f"\n=== Distribution Restore ===")
        print(f"Quelle: {zip_path.name}")
        print(f"Ziel: {target_dir}")
        print(f"Wiederhergestellt: {len(result['restored'])}")
        print(f"Fehler: {len(result['errors'])}")

        return result

    def list_dist_zips(self, dist_dir: Path = None) -> List[Dict]:
        """Listet verfuegbare Distribution-ZIPs."""
        if dist_dir is None:
            try:
                from hub.bach_paths import DIST_DIR
                dist_dir = DIST_DIR
            except ImportError:
                dist_dir = self.root / "system" / "dist"

        dist_dir = Path(dist_dir)
        if not dist_dir.exists():
            return []

        zips = []
        for zp in dist_dir.glob("*.zip"):
            try:
                stat = zp.stat()
                with zipfile.ZipFile(str(zp), 'r') as zf:
                    file_count = len([m for m in zf.namelist() if not m.endswith("/")])
                zips.append({
                    "name": zp.name,
                    "path": str(zp),
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "file_count": file_count
                })
            except Exception:
                pass

        return sorted(zips, key=lambda x: x["modified"], reverse=True)

    # =========================================================================
    # STATUS & CLASSIFY
    # =========================================================================

    def status(self) -> Dict:
        """Gibt aktuellen System-Status zurueck (dist_type-basiert)."""
        identity = self.load_identity()
        seal_ok, seal_msg = self.verify_seal() if identity else (False, "Keine Identitaet")

        with sqlite3.connect(str(self.db_path)) as conn:
            # dist_type Statistiken aus v_distribution_stats
            try:
                stats_rows = conn.execute("SELECT * FROM v_distribution_stats").fetchall()
                dist_stats = {}
                for row in stats_rows:
                    dist_stats[row[0]] = {
                        "total": row[1], "core": row[2],
                        "template": row[3], "user_data": row[4]
                    }
            except sqlite3.OperationalError:
                dist_stats = {}

            # Manifest-Anzahl
            try:
                manifest_count = conn.execute("SELECT COUNT(*) FROM distribution_manifest").fetchone()[0]
            except sqlite3.OperationalError:
                manifest_count = 0

            # Snapshot-Anzahl
            try:
                snapshot_count = conn.execute("SELECT COUNT(*) FROM distribution_snapshots").fetchone()[0]
            except sqlite3.OperationalError:
                snapshot_count = 0

            # Release-Anzahl
            try:
                release_count = conn.execute(
                    "SELECT COUNT(*) FROM distribution_releases WHERE status = 'final'"
                ).fetchone()[0]
                release_total = conn.execute("SELECT COUNT(*) FROM distribution_releases").fetchone()[0]
            except sqlite3.OperationalError:
                release_count = 0
                release_total = 0

        return {
            "identity": identity,
            "seal": {"intact": seal_ok, "message": seal_msg},
            "dist_stats": dist_stats,
            "manifest_count": manifest_count,
            "snapshots": snapshot_count,
            "releases_final": release_count,
            "releases_total": release_total,
        }

    def classify(self) -> Dict:
        """Zeigt dist_type-Verteilung aus v_distribution_stats."""
        with sqlite3.connect(str(self.db_path)) as conn:
            try:
                rows = conn.execute("SELECT * FROM v_distribution_stats").fetchall()
            except sqlite3.OperationalError:
                return {}

        result = {}
        for row in rows:
            result[row[0]] = {
                "total": row[1], "core": row[2],
                "template": row[3], "user_data": row[4]
            }
        return result

    def print_status(self):
        """Gibt formatierten Status aus."""
        s = self.status()

        print("\n" + "=" * 60)
        print("  BACH Distribution System - Status (dist_type)")
        print("=" * 60)

        if s["identity"]:
            inst = s["identity"].get("instance", {})
            print(f"\n  Identitaet:")
            print(f"    ID:   {inst.get('id', 'unbekannt')}")
            print(f"    Name: {inst.get('name', 'unbekannt')}")

        seal = s["seal"]
        seal_icon = "[OK]" if seal["intact"] else "[!!]"
        print(f"\n  Siegel: {seal_icon} {seal['message']}")

        print(f"\n  Manifest: {s['manifest_count']} Eintraege")
        print(f"  Snapshots: {s['snapshots']}")
        print(f"  Releases: {s['releases_final']} final / {s['releases_total']} gesamt")

        dist_stats = s.get("dist_stats", {})
        if dist_stats:
            print(f"\n  dist_type Verteilung:")
            print(f"    {'Tabelle':<12} {'Gesamt':>8} {'CORE(2)':>8} {'TMPL(1)':>8} {'USER(0)':>8}")
            print(f"    {'-'*44}")
            for table_name, vals in dist_stats.items():
                print(f"    {table_name:<12} {vals['total']:>8} {vals['core']:>8} {vals['template']:>8} {vals['user_data']:>8}")

        print("\n" + "=" * 60)
