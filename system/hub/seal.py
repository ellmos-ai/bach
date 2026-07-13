#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Kernel Seal Handler (SQ021)
============================

Siegelsystem fuer BACH-Integritaet.

Das Siegel:
- Berechnet SHA256-Hash ueber alle CORE-Dateien (dist_type=2)
- Warnt bei Veraenderungen
- Ermoeglicht Restore/Repair

CLI:
    bach seal check       Vollstaendige Hash-Pruefung
    bach seal repair      Neuen Hash berechnen und speichern
    bach seal status      Zeige aktuellen Seal-Status

Author: BACH Development Team
Created: 2026-02-20 (SQ021, Runde 4)
"""

import hashlib
import sqlite3
from pathlib import Path
from typing import List, Tuple

# Doppelter Importweg mit Absicht: bach.py laedt diesen Handler als TOP-LEVEL-Modul
# (`from seal import SealHandler`, nachdem es hub/ auf den sys.path gelegt hat) — ein rein
# relativer Import scheitert dort und wuerde als "seal.py nicht gefunden" durchschlagen.
try:
    from .bach_paths import BACH_DB          # als Paketmodul: hub.seal
except ImportError:                          # pragma: no cover
    from bach_paths import BACH_DB           # als Top-Level-Modul: seal


class SealHandler:
    """Handler fuer Kernel-Siegelsystem."""

    def __init__(self, base_path: Path):
        """
        Args:
            base_path: BACH Root-Verzeichnis
        """
        self.base_path = Path(base_path)
        self.system_root = self.base_path / "system" if (self.base_path / "system").exists() else self.base_path
        # Kanonisch ist die zentrale Registry (BACH_DB, Import am Modulkopf) — die frueher
        # hier stehende Kaskade baute base_path/data/bach.db und traf damit die veraltete
        # OneDrive-Kopie. ABER: base_path ist zugleich der Injektionsmechanismus der Tests
        # (tmp-Verzeichnis mit eigener DB). Zeigt base_path nicht auf den echten Root und
        # liegt dort eine DB, ist sie gemeint. Muster wie hub/base.py::_canonical_db.
        _injected_db = self.base_path / "data" / "bach.db"
        _real_root = Path(__file__).resolve().parent.parent
        if _injected_db.exists() and self.base_path.resolve() != _real_root:
            self.db_path = _injected_db
        else:
            self.db_path = BACH_DB

    def _get_conn(self):
        """DB-Verbindung."""
        return sqlite3.connect(str(self.db_path))

    def _get_core_files(self) -> List[str]:
        """Liest alle CORE-Dateien (dist_type=2) aus DB."""
        conn = self._get_conn()
        cursor = conn.execute("""
            SELECT path
            FROM distribution_manifest
            WHERE dist_type = 2
            ORDER BY path
        """)
        files = [row[0] for row in cursor.fetchall()]
        conn.close()
        return files

    def _calculate_file_hash(self, file_path: Path) -> str:
        """Berechnet SHA256-Hash einer Datei."""
        hasher = hashlib.sha256()
        try:
            with open(file_path, 'rb') as f:
                while chunk := f.read(8192):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception:
            return ""

    def _calculate_kernel_hash(self) -> Tuple[str, int, int]:
        """
        Berechnet Kernel-Hash ueber alle CORE-Dateien.

        Returns:
            (kernel_hash, processed_count, skipped_count)
        """
        core_files = self._get_core_files()

        if not core_files:
            return "", 0, 0

        combined_hasher = hashlib.sha256()
        processed = 0
        skipped = 0

        for relative_path in core_files:
            # Pfade sind relativ zu system/
            if not relative_path.startswith('system/'):
                file_path = self.system_root / relative_path
            else:
                file_path = self.base_path / relative_path

            if not file_path.exists():
                skipped += 1
                continue

            file_hash = self._calculate_file_hash(file_path)
            if file_hash:
                # Hash + Pfad kombinieren
                combined_hasher.update(file_hash.encode('utf-8'))
                combined_hasher.update(relative_path.encode('utf-8'))
                processed += 1

        kernel_hash = combined_hasher.hexdigest()
        return kernel_hash, processed, skipped

    def _get_stored_hash(self) -> str:
        """Liest gespeicherten kernel_hash aus DB."""
        try:
            conn = self._get_conn()
            cursor = conn.execute("SELECT kernel_hash FROM instance_identity LIMIT 1")
            row = cursor.fetchone()
            conn.close()
            return row[0] if row and row[0] else ""
        except Exception:
            return ""

    def _update_kernel_hash(self, kernel_hash: str) -> bool:
        """Aktualisiert kernel_hash in instance_identity."""
        try:
            conn = self._get_conn()

            # Pruefen ob instance_identity existiert
            cursor = conn.execute("SELECT COUNT(*) FROM instance_identity")
            count = cursor.fetchone()[0]

            if count == 0:
                conn.close()
                return False

            # kernel_hash aktualisieren
            conn.execute("""
                UPDATE instance_identity
                SET kernel_hash = ?,
                    seal_status = 'intact'
                WHERE rowid = 1
            """, (kernel_hash,))

            conn.commit()
            conn.close()
            return True
        except Exception:
            return False

    def check(self, verbose: bool = False) -> int:
        """
        Vollstaendige Hash-Pruefung.

        Args:
            verbose: Detaillierte Ausgabe

        Returns:
            0 = INTACT, 1 = MODIFIED, 2 = NO_SEAL, 3 = ERROR
        """
        stored_hash = self._get_stored_hash()

        if not stored_hash:
            print("[KERNEL SEAL]")
            print("Status: NO_SEAL")
            print("")
            print("Kein Kernel-Hash gespeichert.")
            print("Nutze 'bach seal repair' um Hash zu erstellen.")
            return 2

        print("[KERNEL SEAL CHECK]")
        print("")
        print(f"Gespeicherter Hash: {stored_hash[:16]}...")
        print("")

        # Aktuellen Hash berechnen
        print("Berechne Kernel-Hash...")
        current_hash, processed, skipped = self._calculate_kernel_hash()

        if not current_hash:
            print("[ERROR] Kernel-Hash konnte nicht berechnet werden!")
            return 3

        print(f"Verarbeitet: {processed} CORE-Dateien")
        if skipped:
            print(f"Uebersprungen: {skipped} (fehlen oder Lesefehler)")
        print("")

        print(f"Aktueller Hash:     {current_hash[:16]}...")
        print("")

        # Vergleich
        if current_hash == stored_hash:
            print("Status: ✓ INTACT")
            print("")
            print("Alle CORE-Dateien sind unveraendert.")
            return 0
        else:
            print("Status: ✗ MODIFIED")
            print("")
            print("WARNUNG: Kernel-Hash stimmt nicht ueberein!")
            print("")
            print("Moegliche Ursachen:")
            print("  - CORE-Dateien wurden manuell geaendert")
            print("  - System-Update ohne seal repair")
            print("  - Datei-Korruption")
            print("")
            print("Naechste Schritte:")
            print("  bach seal repair     Neuen Hash erstellen (nach bewusster Aenderung)")
            print("  bach restore --full  System wiederherstellen")
            return 1

    def repair(self) -> int:
        """
        Neuen Kernel-Hash berechnen und speichern.

        Returns:
            0 = SUCCESS, 1 = ERROR
        """
        print("[KERNEL SEAL REPAIR]")
        print("")
        print("Berechne neuen Kernel-Hash...")

        kernel_hash, processed, skipped = self._calculate_kernel_hash()

        if not kernel_hash:
            print("[ERROR] Kernel-Hash konnte nicht berechnet werden!")
            return 1

        print(f"Verarbeitet: {processed} CORE-Dateien")
        if skipped:
            print(f"Uebersprungen: {skipped} (fehlen)")
        print("")
        print(f"Neuer Hash: {kernel_hash[:16]}...")
        print("")

        # In DB speichern
        if self._update_kernel_hash(kernel_hash):
            print("✓ Kernel-Hash in DB aktualisiert")
            print("")
            print("Siegel repariert. System als 'intact' markiert.")
            return 0
        else:
            print("[ERROR] Konnte Hash nicht in DB speichern!")
            print("        Existiert instance_identity?")
            return 1

    def status(self) -> int:
        """
        Zeigt aktuellen Seal-Status.

        Returns:
            0 = SUCCESS
        """
        stored_hash = self._get_stored_hash()

        print("[KERNEL SEAL STATUS]")
        print("")

        if not stored_hash:
            print("Status: NO_SEAL")
            print("")
            print("Kein Kernel-Hash gespeichert.")
            return 0

        print(f"Gespeicherter Hash: {stored_hash[:16]}...")
        print("")

        # Anzahl CORE-Dateien
        core_files = self._get_core_files()
        print(f"CORE-Dateien: {len(core_files)}")
        print("")
        print("Nutze 'bach seal check' fuer vollstaendige Pruefung.")
        return 0
