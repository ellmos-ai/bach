#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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

"""Migration 010: Bridge Session Lock (Fackelträger-System)"""

import sqlite3
from pathlib import Path

def upgrade(db_path: Path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    with open(Path(__file__).with_suffix('.sql'), encoding='utf-8') as f:
        cur.executescript(f.read())

    conn.commit()
    conn.close()
    print("[OK] Migration 010: bridge_session_lock Tabelle erstellt")

def downgrade(db_path: Path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS bridge_session_lock")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    # Pfad zur Datenbank
    try:
        from hub.bach_paths import BACH_DB
        db_path = BACH_DB
    except ImportError:
        db_path = Path(__file__).parent.parent.parent / "data" / "bach.db"
    upgrade(db_path)
