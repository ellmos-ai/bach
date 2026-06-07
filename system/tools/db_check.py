#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: db_check
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version db_check

Description:
    [Beschreibung hinzufügen]

Usage:
    python db_check.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"


import sqlite3
import os
from pathlib import Path

DB_PATH = Path(
    os.environ.get(
        "BACH_VARIANT_DB",
        str(Path.home() / ".bach" / "data" / "variant_fusion.sqlite"),
    )
).expanduser()

def check_db():
    if not os.path.exists(DB_PATH):
        print(f"DB not found at {DB_PATH}")
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        c.execute("PRAGMA table_info(variants)")
        columns = [r[1] for r in c.fetchall()]
        print(f"Columns: {columns}")
        
        # Check specific variant
        chrom = 'chr1' # Or just '1'
        pos = 13273
        ref = 'G'
        alt = 'C'
        
        # Adjust query based on columns
        chrom_col = 'chr'
            
        print(f"Using chrom column: {chrom_col}")
        
        query = f"SELECT af_filter_mean, meanAF_last_fetch, meanAF_fetch_success FROM variants WHERE {chrom_col}=? AND pos=? AND ref=? AND alt=?"
        c.execute(query, (chrom, pos, ref, alt))
        row = c.fetchone()
        
        if row:
            print(f"Variant {chrom}:{pos} {ref}->{alt} found:")
            print(f"  af_filter_mean: {row[0]}")
            print(f"  meanAF_last_fetch: {row[1]}")
            print(f"  meanAF_fetch_success: {row[2]}")
        else:
            print(f"Variant {chrom}:{pos} {ref}->{alt} NOT found in DB.")
            
            # Try just '1' instead of 'chr1'
            chrom = '1'
            c.execute(query, (chrom, pos, ref, alt))
            row = c.fetchone()
            if row:
                 print(f"Variant {chrom}:{pos} {ref}->{alt} found:")
                 print(f"  af_filter_mean: {row[0]}")
                 print(f"  meanAF_last_fetch: {row[1]}")
                 print(f"  meanAF_fetch_success: {row[2]}")
            else:
                 print(f"Variant {chrom}:{pos} {ref}->{alt} NOT found in DB.")
            
        conn.close()
    except Exception as e:
        print(f"Error querying DB: {e}")

if __name__ == "__main__":
    check_db()
