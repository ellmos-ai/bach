#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: debug_scan
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version debug_scan

Description:
    Debug-Scan der BACH-Verzeichnisstruktur

Usage:
    python debug_scan.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

from pathlib import Path
import os

BACH_ROOT = Path(__file__).parent.parent
SKILLS_ROOT = BACH_ROOT / "skills"


if __name__ == "__main__":
    print(f"BACH_ROOT: {BACH_ROOT}")
    print(f"SKILLS_ROOT: {SKILLS_ROOT}")

    dirs = ["_agents", "_experts", "_workflows", "_services"]
    for d in dirs:
        path = SKILLS_ROOT / d
        print(f"Check {d}: {path} exists={path.exists()}")
        if path.exists():
            files = list(os.walk(path))
            print(f"  Walk: {len(files)} subdirs info")
            for root, _, fs in files:
                print(f"  Root: {root}")
                print(f"  Files: {fs}")
