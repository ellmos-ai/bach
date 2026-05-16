#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: bach_auto_discovery
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version bach_auto_discovery

Description:
    [Beschreibung hinzufügen]

Usage:
    python bach_auto_discovery.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

import os
import sqlite3
import re
import json
from pathlib import Path
from datetime import datetime

# Pfade
BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "bach.db"
SKILLS_DIR = BASE_DIR / "skills"
TOOLS_DIR = BASE_DIR / "tools"

def extract_skill_metadata(path):
    """Extrahiert Metadaten aus SKILL.md oder manifest.json."""
    description = ""
    version = "1.0.0"
    
    # 1. Check manifest.json
    manifest_path = path / "manifest.json" if path.is_dir() else path.with_suffix(".json")
    if manifest_path.exists():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                description = data.get("description", "")
                version = data.get("version", "1.0.0")
        except (json.JSONDecodeError, OSError):
            pass
            
    # 2. Check SKILL.md
    if not description:
        skill_md = path / "SKILL.md" if path.is_dir() else (path if path.name == "SKILL.md" else None)
        if skill_md and skill_md.exists():
            try:
                with open(skill_md, "r", encoding="utf-8") as f:
                    content = f.read()
                    # Erste Überschrift oder Text unter Überschrift
                    match = re.search(r'#.*?\n(.*?)(?=\n#|$)', content, re.DOTALL)
                    if match:
                        description = match.group(1).strip().replace("\n", " ")[:200]
            except OSError:
                pass
                
    # 3. Fallback for .txt experts
    if not description and path.suffix == ".txt":
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read(500)
                # Erste Zeile oder Docstring-artig
                description = content.split("\n")[0].strip()[:200]
        except OSError:
            pass
            
    return description, version

def get_keywords(name, description):
    """Generiert Keywords."""
    keywords = set()
    keywords.add(name.lower())
    if description:
        words = re.findall(r'\w{3,}', description.lower())
        keywords.update(words)
    stop = {"und", "der", "die", "das", "für", "auf", "mit", "von", "aus", "python", "script", "agent", "experte"}
    return {k for k in keywords if k not in stop}

def process_skills():
    if not DB_PATH.exists(): return
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    categories = ["_agents", "_experts", "_services", "_workflows"]
    skills_added = 0
    
    for cat in categories:
        cat_dir = SKILLS_DIR / cat
        if not cat_dir.exists(): continue
        
        # Scan directories and files
        items = list(cat_dir.iterdir())
        for item in items:
            if item.name.startswith("_") or item.name == "README.md": continue
            
            name = item.stem
            rel_path = str(item.relative_to(BASE_DIR)).replace("\\", "/")
            stype = cat[1:-1] # agents -> agent
            
            # Metadata
            desc, ver = extract_skill_metadata(item)
            
            # Check DB
            cursor.execute("SELECT id FROM skills WHERE name = ?", (name,))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO skills (name, type, category, path, version, description, created_at, dist_type)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 2)
                """, (name, stype, cat, rel_path, ver, desc or name))
                skills_added += 1
                
                # Add context triggers
                keywords = get_keywords(name, desc)
                hint = f"[{stype.upper()}] {name}: {desc or name}"
                for kw in keywords:
                    cursor.execute("INSERT OR IGNORE INTO context_triggers (trigger_phrase, hint_text, source) VALUES (?, ?, 'skill')", (kw, hint))
    
    conn.commit()
    conn.close()
    print(f"[OK] {skills_added} neue Skills registriert.")

def run_tool_discovery():
    import subprocess
    import sys
    tool_script = BASE_DIR / "tools" / "tool_auto_discovery.py"
    if tool_script.exists():
        subprocess.run([sys.executable, str(tool_script)])

if __name__ == "__main__":
    print("Starte BACH Auto-Discovery...")
    process_skills()
    run_tool_discovery()
