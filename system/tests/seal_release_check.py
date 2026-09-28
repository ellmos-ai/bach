#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
seal_release_check.py - Seal System Verification (Release Pipeline Integration)
================================================================================

Testet das Siegelsystem (SQ021) - Integriert in Release-Pipeline (SQ027).

T-20260927-807838815: umbenannt von test_seal.py. Das war nie ein
pytest-Test: die Klasse (vormals SealSystemTests) verlangt einen
Pflicht-Parameter im __init__, den pytest beim Sammeln nicht mitgibt
-- pytest sammelte deshalb 0 Tests, obwohl die Datei "pytest
tests/test_seal.py" als Aufrufweg bewarb. Zusaetzlich braucht dieses
Skript eine bereits mit distribution_manifest/dist_file_versions
befuellte Release-DB (>= 200 CORE-Eintraege) -- in einem frischen
Checkout ohne Release-Lauf schlicht nicht vorhanden. Das ist ein
manuelles Release-Verifikationswerkzeug, kein CI-taugliicher Unit-Test;
ohne eine Seed-DB mit Testdaten wird daraus kein CI-Gate gebaut.

Tests:
1. Kernel-Scope: Prüft ob alle dist_type=2 CORE-Dateien erfasst sind
2. Hash-Berechnung: Verifiziert dass Hashes berechnet werden können
3. dist_file_versions: Prüft ob Versionen populated sind
4. Startup-Check: Simuliert Stichproben-Check

Verwendung:
  python tests/seal_release_check.py         # Standalone, nach einem Release-Lauf

Teil von SQ021 (Seal System) + SQ027 (Release Pipeline Integration)
"""

from pathlib import Path
import hashlib
import sqlite3
import sys

# Kanonischer BACH_DB-Pfad statt eines selbstgebauten system/data/bach.db
# (T-20260927-807838815, gleiches Muster wie in bach#111/#112 gefixt --
# ein selbstgebauter Pfad prueft sonst beim naechsten Release die falsche,
# potenziell veraltete Datei statt der tatsaechlich aktiven BACH_DB).
_SYSTEM_ROOT = next(
    p for p in Path(__file__).resolve().parents
    if (p / "hub" / "bach_paths.py").exists()
)
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))
from hub.bach_paths import BACH_DB  # noqa: E402


class SealSystemTests:
    """Seal System Test Suite."""

    def __init__(self, bach_root: Path):
        self.bach_root = Path(bach_root)
        self.system_root = self.bach_root / "system"
        self.db_path = BACH_DB
        self.tests_passed = 0
        self.tests_failed = 0

    def run_all(self):
        """Führt alle Tests aus."""
        print("=" * 70)
        print("SEAL SYSTEM TESTS")
        print("=" * 70)
        print()

        self.test_kernel_scope()
        self.test_hash_calculation()
        self.test_file_versions_populated()
        self.test_startup_check_sampling()

        print()
        print("=" * 70)
        print(f"ERGEBNIS: {self.tests_passed} PASS, {self.tests_failed} FAIL")
        print("=" * 70)

        return 0 if self.tests_failed == 0 else 1

    def test_kernel_scope(self):
        """Test 1: Kernel-Scope (alle CORE-Dateien erfasst)."""
        print("[TEST 1] Kernel-Scope (CORE-Dateien)")
        print("-" * 70)

        conn = self._ro_connect()
        cursor = conn.execute("""
            SELECT COUNT(*)
            FROM distribution_manifest
            WHERE dist_type = 2
        """)
        core_count = cursor.fetchone()[0]
        conn.close()

        # Erwartung: Mindestens 200 CORE-Dateien (aus Runde 5: 250)
        if core_count >= 200:
            print(f"✓ PASS: {core_count} CORE-Dateien im Manifest")
            self.tests_passed += 1
        else:
            print(f"✗ FAIL: Nur {core_count} CORE-Dateien (erwartet >= 200)")
            self.tests_failed += 1

        print()

    def test_hash_calculation(self):
        """Test 2: Hash-Berechnung."""
        print("[TEST 2] Hash-Berechnung")
        print("-" * 70)

        # Wähle eine bekannte Datei
        test_file = self.system_root / "hub" / "base.py"

        if not test_file.exists():
            print(f"✗ FAIL: Test-Datei nicht gefunden: {test_file}")
            self.tests_failed += 1
            print()
            return

        # Berechne Hash
        try:
            content = test_file.read_bytes()
            file_hash = hashlib.sha256(content).hexdigest()
            print(f"✓ PASS: Hash berechnet für {test_file.name}")
            print(f"  Hash: {file_hash[:16]}...")
            self.tests_passed += 1
        except Exception as e:
            print(f"✗ FAIL: Hash-Berechnung fehlgeschlagen: {e}")
            self.tests_failed += 1

        print()

    def test_file_versions_populated(self):
        """Test 3: dist_file_versions befüllt."""
        print("[TEST 3] dist_file_versions Tabelle")
        print("-" * 70)

        conn = self._ro_connect()
        cursor = conn.execute("SELECT COUNT(*) FROM dist_file_versions")
        version_count = cursor.fetchone()[0]
        conn.close()

        # Erwartung: Mindestens 200 Versionen (aus Runde 5: 293)
        if version_count >= 200:
            print(f"✓ PASS: {version_count} Einträge in dist_file_versions")
            self.tests_passed += 1
        else:
            print(f"✗ FAIL: Nur {version_count} Einträge (erwartet >= 200)")
            self.tests_failed += 1

        print()

    def test_startup_check_sampling(self):
        """Test 4: Startup-Check Stichproben-Logik.
        Simuliert die Stichproben-Pruefung aus system/hub/startup.py (SQ021):
        5 zufaellige CORE-Dateien werden gezogen und auf Dateipraesenz geprueft.
        Zusaetzlich wird bei vorhandenem Release-Hash die Hash-Berechnung getestet.
        """
        print("[TEST 4] Startup-Check Stichproben")
        print("-" * 70)

        conn = self._ro_connect()

        # Waehle 5 zufaellige CORE-Dateien aus distribution_manifest mit aktuellem Hash
        cursor = conn.execute("""
            SELECT m.path, COALESCE(
                (SELECT v.file_hash FROM dist_file_versions v
                 WHERE v.file_path = m.path
                 ORDER BY v.id DESC LIMIT 1),
                m.template_hash
            ) as stored_hash
            FROM distribution_manifest m
            WHERE m.dist_type = 2
            ORDER BY RANDOM()
            LIMIT 5
        """)
        samples = cursor.fetchall()
        conn.close()

        if len(samples) < 5:
            print(f"✗ FAIL: Nicht genug CORE-Dateien für Stichprobe (nur {len(samples)})")
            self.tests_failed += 1
            print()
            return

        verified_exists = 0
        verified_hash = 0
        for path, stored_hash in samples:
            abs_path = self._resolve_path(path)

            if not abs_path.exists():
                print(f"  - {path}: Datei nicht gefunden")
                continue

            verified_exists += 1

            if stored_hash:
                try:
                    content = abs_path.read_bytes()
                    current_hash = hashlib.sha256(content).hexdigest()
                    if current_hash == stored_hash:
                        verified_hash += 1
                except Exception as e:
                    print(f"  - {path}: Fehler beim Hash-Check: {e}")

        # Startup-Check prueft Existenz der Stichproben (>=4/5 Praesenz-Schwelle)
        if verified_exists >= 4:
            print(f"✓ PASS: {verified_exists}/5 Stichproben verifiziert (Dateipraesenz: {verified_exists}/5, Hash-Match: {verified_hash}/{verified_exists})")
            self.tests_passed += 1
        else:
            print(f"✗ FAIL: Nur {verified_exists}/5 Stichproben gefunden")
            self.tests_failed += 1

        print()

    def _resolve_path(self, relative_path: str) -> Path:
        """Konvertiert relativen Pfad in absoluten Pfad.
        Unterstuetzt sowohl system/-Prefix als auch Repo-Root-Pfade
        (z.B. start/bach.bat, .gitignore, README.md, requirements.txt).
        Muster wie in system/tools/fs_protection.py::_resolve_manifest_path.
        """
        relative = Path(relative_path)
        if relative.parts and relative.parts[0] == "system":
            return self.bach_root / relative
        system_candidate = self.system_root / relative
        if system_candidate.exists():
            return system_candidate
        root_candidate = self.bach_root / relative
        if root_candidate.exists():
            return root_candidate
        return system_candidate

    def _ro_connect(self) -> sqlite3.Connection:
        """Oeffnet BACH_DB read-only per URI (mode=ro): dieses Tool ist eine
        Verifikation, keine Schreiboperation -- es darf die DB nicht per
        Seiteneffekt anlegen/veraendern (z.B. wenn db_path noch nicht
        existiert, wuerde ein normales sqlite3.connect() eine leere Datei
        erzeugen)."""
        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        return sqlite3.connect(uri, uri=True)


def main():
    """CLI Entry Point."""
    bach_root = Path(__file__).parent.parent.parent
    tests = SealSystemTests(bach_root)
    exit_code = tests.run_all()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
