#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: custom_analysis
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version custom_analysis

Description:
    [Beschreibung hinzufügen]

Usage:
    python custom_analysis.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

import gzip
import os
import sys
import re
import requests
import time

def check_myvariant(chrom, pos, ref, alt):
    # HG38 query (assuming file is HG38 based on previous checks/filename usually implying modern)
    # Actually filename doesn't say. But previous DB fetch worked with these coords.
    # Try hg19 and hg38 query form.
    # MyVariant format: chr1:g.12345C>T
    
    # Try hg19 (GRCh37) first as default in many fields, but WGS Nebula might be hg38.
    # nebula usually hg38
    
    query = f"chr{chrom}:g.{pos}{ref}>{alt}"
    url = f"https:/myvariant.info/v1/variant/{query}?fields=gnomad_exomes.af.af,gnomad_genome.af.af,dbsnp.rsid"
    
    print(f"Querying {query}...")
    try:
        r = requests.get(url)
        if r.status_code == 200:
            res = r.json()
            if 'gnomad_genome' in res:
                print(f"  gnomad_genome AF: {res['gnomad_genome'].get('af', {}).get('af')}")
            else:
                 print("  gnomad_genome AF: Not found")
                 
            if 'gnomad_exomes' in res:
                print(f"  gnomad_exomes AF: {res['gnomad_exomes'].get('af', {}).get('af')}")
            else:
                 print("  gnomad_exomes AF: Not found")
                 
            return res
        else:
            print(f"  API Error: {r.status_code}")
    except Exception as e:
        print(f"  Fetch Error: {e}")
    return None

# Paths are intentionally supplied by environment to avoid committing private
# local health/genetics file locations.
VCF_PATH = os.environ.get("BACH_VCF_PATH", "")
VCF_GZ_PATH = os.environ.get("BACH_VCF_GZ_PATH", f"{VCF_PATH}.gz" if VCF_PATH else "")
    
def analyze_file(path, open_func):
    print(f"Analyzing {path}...")
    try:
        with open_func(path, 'rt', encoding='utf-8', errors='replace') as f:
            header_count = 0
            variant_count = 0
            af_stats = {
                'missing': 0,
                'rare (<0.01)': 0,
                'uncommon (<0.05)': 0,
                'common (>=0.05)': 0,
                'total_with_af': 0
            }
            previous_af = -1.0
            is_sorted_ascending = True
            is_sorted_descending = True
            
            for line in f:
                if line.startswith('#'):
                    header_count += 1
                    continue
                
                variant_count += 1
                parts = line.strip().split('\t')
                if len(parts) < 8:
                    continue
                
                
                if variant_count <= 5:
                    print(f"Variant {variant_count}: {parts[0]}:{parts[1]} {parts[3]}->{parts[4]}")
                    print(f"  QUAL: {parts[5]}")
                    print(f"  FILTER: {parts[6]}")
                    # Parse parts
                    chrom_raw = parts[0].replace('chr', '')
                    pos = parts[1]
                    ref = parts[3]
                    alt = parts[4]
                    
                    check_myvariant(chrom_raw, pos, ref, alt)
                
                if variant_count >= 50000:
                    break
            print(f"Total scanned: {variant_count}")

    except Exception as e:
        print(f"Error reading {path}: {e}")

def print_af_header(path, open_func):
    pass # Skipped for brevity

if __name__ == "__main__":
    if VCF_GZ_PATH and os.path.exists(VCF_GZ_PATH):
        analyze_file(VCF_GZ_PATH, gzip.open)
    elif VCF_PATH and os.path.exists(VCF_PATH):
        analyze_file(VCF_PATH, open)
    else:
        print("Set BACH_VCF_PATH or BACH_VCF_GZ_PATH to analyze a local VCF file.")
