#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Test-Skript für sqlite-vec Installation und Funktionalität (SQ064)
===================================================================

Prüft:
1. Ob sqlite-vec installiert ist
2. Ob sqlite-vec mit sqlite3 kompatibel ist
3. Basis-Vektorsuche Funktionalität

Installation:
    pip install sqlite-vec

Referenz: https://github.com/asg017/sqlite-vec
"""

import sqlite3
from pathlib import Path


def test_sqlite_vec_import():
    """Test 1: Prüft ob sqlite-vec importierbar ist."""
    import sqlite_vec
    assert hasattr(sqlite_vec, 'load')


def test_sqlite_vec_extension():
    """Test 2: Prüft ob sqlite-vec Extension geladen werden kann."""
    import sqlite_vec
    conn = sqlite3.connect(":memory:")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    cursor = conn.cursor()
    cursor.execute("SELECT vec_version()")
    version = cursor.fetchone()[0]
    assert version is not None
    conn.close()


def test_basic_vector_search():
    """Test 3: Basis-Vektorsuche Test."""
    import sqlite_vec
    conn = sqlite3.connect(":memory:")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE VIRTUAL TABLE vec_items USING vec0(
            id INTEGER PRIMARY KEY,
            embedding FLOAT[3]
        )
    """)
    cursor.execute("INSERT INTO vec_items(id, embedding) VALUES (1, '[1.0, 0.0, 0.0]')")
    cursor.execute("INSERT INTO vec_items(id, embedding) VALUES (2, '[0.0, 1.0, 0.0]')")
    cursor.execute("INSERT INTO vec_items(id, embedding) VALUES (3, '[0.0, 0.0, 1.0]')")
    conn.commit()
    cursor.execute("""
        SELECT id, distance
        FROM vec_items
        WHERE embedding MATCH ?
        ORDER BY distance
        LIMIT 3
    """, ("[1.0, 0.0, 0.0]",))
    results = cursor.fetchall()
    assert len(results) == 3
    assert results[0][0] == 1
    conn.close()


def test_bach_db_integration():
    """Test 4: Integration mit bach.db (falls vorhanden)."""
    import pytest
    import sqlite_vec

    db_path = Path(__file__).parent.parent / "data" / "bach.db"
    if not db_path.exists():
        pytest.skip("bach.db nicht gefunden")

    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    cursor = conn.cursor()
    cursor.execute("SELECT vec_version()")
    version = cursor.fetchone()[0]
    assert version is not None
    conn.close()


def run_all_tests():
    """Führt alle Tests aus."""
    print("=" * 60)
    print("sqlite-vec Installation & Funktionstest (SQ064)")
    print("=" * 60)
    print()

    results = []

    # Test 1: Import
    results.append(("Import", test_sqlite_vec_import()))

    # Nur weitermachen wenn Import erfolgreich
    if results[0][1]:
        results.append(("Extension laden", test_sqlite_vec_extension()))
        results.append(("Basis-Vektorsuche", test_basic_vector_search()))
        results.append(("bach.db Integration", test_bach_db_integration()))
    else:
        print("\n[SKIP] Weitere Tests übersprungen (sqlite-vec nicht installiert)")

    # Zusammenfassung
    print()
    print("=" * 60)
    print("Zusammenfassung:")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "[OK]" if result else "[FAIL]"
        print(f"{status} {name}")

    print()
    print(f"Ergebnis: {passed}/{total} Tests bestanden")

    if passed == total:
        print("[SUCCESS] Alle Tests erfolgreich!")
        return 0
    else:
        print("[PARTIAL] Einige Tests fehlgeschlagen")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(run_all_tests())
