#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
BACH Sync Utilities v1.0
========================
Zentrale Funktionen fuer Datei-Hashing und Aenderungserkennung.

Verwendung:
  from tools.sync_utils import file_hash, content_hash, has_changed, SyncTracker
"""

import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Tuple


def file_hash(filepath: Path, algorithm: str = 'sha256') -> str:
    """
    Berechnet Hash einer Datei.

    Args:
        filepath: Pfad zur Datei
        algorithm: 'md5', 'sha256' (Standard), 'sha1'

    Returns:
        Hash-String im Format 'algorithm:hexdigest'
    """
    if not filepath.exists():
        raise FileNotFoundError(f"Datei nicht gefunden: {filepath}")

    hasher = hashlib.new(algorithm)
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            hasher.update(chunk)

    return f"{algorithm}:{hasher.hexdigest()}"


def content_hash(content: str, algorithm: str = 'md5') -> str:
    """
    Berechnet Hash eines Strings.

    Args:
        content: Text-Inhalt
        algorithm: 'md5' (Standard), 'sha256', 'sha1'

    Returns:
        Hash-String im Format 'algorithm:hexdigest'
    """
    hasher = hashlib.new(algorithm)
    hasher.update(content.encode('utf-8'))
    return f"{algorithm}:{hasher.hexdigest()}"


def quick_hash(filepath: Path) -> str:
    """
    Schneller Hash basierend auf Groesse + mtime.
    Fuer schnelle Vorab-Pruefung ob Datei geaendert wurde.

    Returns:
        String aus size:mtime
    """
    if not filepath.exists():
        return "missing"

    stat = filepath.stat()
    return f"{stat.st_size}:{int(stat.st_mtime)}"


def has_changed(filepath: Path, stored_hash: str) -> bool:
    """
    Prueft ob Datei sich geaendert hat.

    Args:
        filepath: Pfad zur Datei
        stored_hash: Gespeicherter Hash zum Vergleich

    Returns:
        True wenn geaendert, False wenn gleich
    """
    if not filepath.exists():
        return stored_hash != "missing"

    # Extrahiere Algorithmus aus gespeichertem Hash
    if ':' in stored_hash:
        algo, _ = stored_hash.split(':', 1)
        if algo in ('md5', 'sha256', 'sha1'):
            current = file_hash(filepath, algo)
        else:
            # Quick hash format (size:mtime)
            current = quick_hash(filepath)
    else:
        # Fallback: MD5
        current = file_hash(filepath, 'md5').split(':')[1]

    return current != stored_hash


class SyncTracker:
    """
    Verfolgt Datei-Aenderungen mit Hash-Vergleich.
    Nutzt files_truth Tabelle in bach.db.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_table()

    def _ensure_table(self):
        """Stellt sicher dass files_truth Tabelle existiert."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS files_truth (
                    id INTEGER PRIMARY KEY,
                    path TEXT UNIQUE NOT NULL,
                    type TEXT DEFAULT 'file',
                    file_exists INTEGER DEFAULT 1,
                    checksum TEXT,
                    size INTEGER,
                    created_at TEXT,
                    modified_at TEXT,
                    last_scan TEXT
                )
            """)
            conn.commit()

    def track(self, filepath: Path, use_quick: bool = False) -> Dict:
        """
        Registriert/aktualisiert eine Datei im Tracker.

        Args:
            filepath: Pfad zur Datei
            use_quick: Nutze quick_hash statt vollstaendigem Hash

        Returns:
            Dict mit 'changed', 'new', 'old_hash', 'new_hash'
        """
        filepath = Path(filepath).resolve()
        path_str = str(filepath)
        now = datetime.now().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Existierenden Eintrag suchen
            existing = conn.execute(
                "SELECT * FROM files_truth WHERE path = ?",
                (path_str,)
            ).fetchone()

            if not filepath.exists():
                # Datei geloescht
                if existing:
                    conn.execute(
                        "UPDATE files_truth SET file_exists = 0, last_scan = ? WHERE path = ?",
                        (now, path_str)
                    )
                    conn.commit()
                    return {
                        'changed': True,
                        'new': False,
                        'deleted': True,
                        'old_hash': existing['checksum'],
                        'new_hash': None
                    }
                return {'changed': False, 'new': False, 'deleted': True}

            # Hash berechnen
            if use_quick:
                new_hash = quick_hash(filepath)
            else:
                new_hash = file_hash(filepath)

            stat = filepath.stat()
            size = stat.st_size

            if existing:
                old_hash = existing['checksum']
                changed = old_hash != new_hash

                if changed:
                    conn.execute("""
                        UPDATE files_truth
                        SET checksum = ?, size = ?, modified_at = ?, last_scan = ?, file_exists = 1
                        WHERE path = ?
                    """, (new_hash, size, now, now, path_str))
                else:
                    conn.execute(
                        "UPDATE files_truth SET last_scan = ? WHERE path = ?",
                        (now, path_str)
                    )
                conn.commit()

                return {
                    'changed': changed,
                    'new': False,
                    'old_hash': old_hash,
                    'new_hash': new_hash
                }
            else:
                # Neue Datei
                conn.execute("""
                    INSERT INTO files_truth (path, type, file_exists, checksum, size, created_at, modified_at, last_scan)
                    VALUES (?, 'file', 1, ?, ?, ?, ?, ?)
                """, (path_str, new_hash, size, now, now, now))
                conn.commit()

                return {
                    'changed': True,
                    'new': True,
                    'old_hash': None,
                    'new_hash': new_hash
                }

    def check(self, filepath: Path) -> Tuple[bool, Optional[str]]:
        """
        Prueft ob Datei geaendert wurde ohne zu aktualisieren.

        Returns:
            (has_changed, stored_hash)
        """
        filepath = Path(filepath).resolve()

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT checksum FROM files_truth WHERE path = ?",
                (str(filepath),)
            ).fetchone()

            if not row:
                return (True, None)  # Unbekannte Datei = geaendert

            stored = row[0]
            return (has_changed(filepath, stored), stored)

    def get_changed_files(self, folder: Path, pattern: str = "*") -> List[Path]:
        """
        Findet alle geaenderten Dateien in einem Ordner.

        Args:
            folder: Ordner zum Scannen
            pattern: Glob-Pattern (z.B. "*.txt")

        Returns:
            Liste der geaenderten Dateien
        """
        changed = []
        folder = Path(folder)

        for filepath in folder.rglob(pattern):
            if filepath.is_file():
                is_changed, _ = self.check(filepath)
                if is_changed:
                    changed.append(filepath)

        return changed

    def sync_folder(self, folder: Path, pattern: str = "*", use_quick: bool = True) -> Dict:
        """
        Synchronisiert alle Dateien eines Ordners.

        Returns:
            Dict mit 'total', 'new', 'changed', 'unchanged', 'files'
        """
        result = {
            'total': 0,
            'new': 0,
            'changed': 0,
            'unchanged': 0,
            'files': []
        }

        folder = Path(folder)

        for filepath in folder.rglob(pattern):
            if filepath.is_file():
                info = self.track(filepath, use_quick=use_quick)
                result['total'] += 1

                if info.get('new'):
                    result['new'] += 1
                elif info.get('changed'):
                    result['changed'] += 1
                else:
                    result['unchanged'] += 1

                if info.get('changed') or info.get('new'):
                    result['files'].append(str(filepath))

        return result


# Convenience-Funktionen
def get_tracker(db_path: Path = None) -> SyncTracker:
    """Erstellt SyncTracker mit Standard-DB-Pfad."""
    if db_path is None:
        try:
            from hub.bach_paths import BACH_DB
            db_path = BACH_DB
        except ImportError:
            db_path = Path(__file__).parent.parent / "data" / "bach.db"
    return SyncTracker(db_path)


if __name__ == "__main__":
    # Test
    import sys

    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        if path.is_file():
            print(f"File: {path}")
            print(f"  Quick Hash: {quick_hash(path)}")
            print(f"  MD5:        {file_hash(path, 'md5')}")
            print(f"  SHA256:     {file_hash(path, 'sha256')}")
        elif path.is_dir():
            tracker = get_tracker()
            result = tracker.sync_folder(path)
            print(f"Synced {result['total']} files:")
            print(f"  New:       {result['new']}")
            print(f"  Changed:   {result['changed']}")
            print(f"  Unchanged: {result['unchanged']}")
    else:
        print("Usage: python sync_utils.py <file|folder>")
