#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: forensic_db_scan
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version forensic_db_scan

Description:
    [Beschreibung hinzufügen]

Usage:
    python forensic_db_scan.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"


import sqlite3
import gzip
import os
import random

DB_PATH = os.environ.get("BACH_VARIANT_DB_PATH", "")
VCF_PATH = os.environ.get("BACH_VCF_GZ_PATH", "")

def parse_info(info_str):
    info_dict = {}
    for part in info_str.split(';'):
        if '=' in part:
            k, v = part.split('=', 1)
            info_dict[k] = v
        else:
            info_dict[part] = True
    return info_dict

def analyze_pollution():
    print(f"Connecting to DB: {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print("DB not found!")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 1. Global DB Statistics for suspicious values
    print("--- Global DB Statistics ---")
    try:
        c.execute("SELECT count(*) FROM variants")
        total = c.fetchone()[0]
        print(f"Total entries: {total}")

        c.execute("SELECT count(*) FROM variants WHERE af_filter_mean = 1.0")
        af_1 = c.fetchone()[0]
        print(f"Entries with AF=1.0: {af_1} ({af_1/total*100:.2f}%)")

        c.execute("SELECT count(*) FROM variants WHERE af_filter_mean = 0.5")
        af_05 = c.fetchone()[0]
        print(f"Entries with AF=0.5: {af_05} ({af_05/total*100:.2f}%)")
        
        c.execute("SELECT count(*) FROM variants WHERE af_filter_mean >= 0.01")
        common = c.fetchone()[0]
        print(f"Entries with AF>=0.01 (Common): {common} ({common/total*100:.2f}%)")
        
    except Exception as e:
        print(f"Error querying statistics: {e}")

    # 2. Correlate with VCF Samples
    print("\n--- VCF Sample Correlation (First 5000) ---")
    if not os.path.exists(VCF_PATH):
        print("VCF not found!")
        conn.close()
        return

    suspicious_matches = 0
    dp_issues = 0
    scanned = 0
    matches_in_db = 0
    
    try:
        # Determine chrom column name again because it might vary
        c.execute("PRAGMA table_info(variants)")
        cols = [r[1] for r in c.fetchall()]
        chrom_col = 'chr' if 'chr' in cols else 'chrom' # Fallback
        
        with gzip.open(VCF_PATH, 'rt', encoding='utf-8', errors='replace') as f:
            for line in f:
                if line.startswith('#'): continue
                
                parts = line.strip().split('\t')
                if len(parts) < 8: continue
                
                scanned += 1
                if scanned > 5000: break
                
                chrom = parts[0].replace('chr', '')
                pos = parts[1]
                ref = parts[3]
                alt = parts[4]
                info_str = parts[7]
                info = parse_info(info_str)
                
                # Check DB
                query = f"SELECT af_filter_mean FROM variants WHERE {chrom_col}=? AND pos=? AND ref=? AND alt=?"
                c.execute(query, (chrom, pos, ref, alt))
                row = c.fetchone()
                
                stored_af = None
                if row:
                    matches_in_db += 1
                    stored_af = row[0]
                    
                    # Check for pollution (Internal AF leaked to DB)
                    # We assume 0.5/1.0 implies internal if exactly those values
                    if stored_af == 1.0 or stored_af == 0.5:
                        # Only flagging if it looks exactly like the internal artifact
                        suspicious_matches += 1
                
                # Check Coverage
                dp = 0
                if 'DP' in info:
                    try:
                        dp = int(info['DP'])
                    except: pass
                
                if dp < 20:
                    dp_issues += 1

                if scanned <= 5:
                     print(f"Sample {scanned}: {chrom}:{pos} DP={dp} InDB={bool(row)} StoredAF={stored_af}")

        print(f"\nScanned VCF Variants: {scanned}")
        print(f"Found in DB: {matches_in_db} ({matches_in_db/scanned*100:.2f}%)")
        print(f"Legacy Pollution Suspects (AF=0.5/1.0 in DB): {suspicious_matches}")
        print(f"Low Coverage (DP<20): {dp_issues} ({dp_issues/scanned*100:.2f}%)")
        
    except Exception as e:
        print(f"Error filtering VCF: {e}")

    conn.close()

if __name__ == "__main__":
    analyze_pollution()
