#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: tool_auto_discovery
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version tool_auto_discovery

Description:
    [Beschreibung hinzufügen]

Usage:
    python tool_auto_discovery.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

import os
import sqlite3
import re
from pathlib import Path
from datetime import datetime

# Pfade
BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "bach.db"
TOOLS_DIR = BASE_DIR / "tools"

def extract_metadata(file_path):
    """Extrahiert Beschreibung und Usage aus einem Python Script."""
    description = ""
    usage = f"python {file_path.relative_to(BASE_DIR)}"
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Docstring suchen (erstes """ oder ''')
            doc_match = re.search(r'"""(.*?)"""', content, re.DOTALL)
            if not doc_match:
                doc_match = re.search(r"'''(.*?)'''", content, re.DOTALL)
            
            if doc_match:
                doc = doc_match.group(1).strip()
                # Nur die erste Zeile oder bis zum ersten Doppelzeilenumbruch
                first_part = doc.split("\n\n")[0].strip()
                description = first_part.replace("\n", " ")
                
                # Usage im Docstring suchen?
                usage_match = re.search(r'Usage:\s*(.*)', doc, re.IGNORECASE)
                if usage_match:
                    usage = usage_match.group(1).strip()
    except (OSError, ValueError):
        pass

    return description[:200], usage[:200]

def get_keywords(name, description):
    """Generiert Keywords."""
    keywords = set()
    keywords.add(name.lower())
    
    if description:
        words = re.findall(r'\w{3,}', description.lower())
        keywords.update(words)
        
    # Stopwörter
    stop = {"und", "der", "die", "das", "für", "auf", "mit", "von", "aus", "python", "tools", "script"}
    return {k for k in keywords if k not in stop}

def process_tools():
    if not DB_PATH.exists():
        print("[ERROR] Datenbank nicht gefunden.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("Scanne tools/ Verzeichnis...")
    tool_files = list(TOOLS_DIR.rglob("*.py"))
    
    tools_added = 0
    triggers_added = 0
    triggers_updated = 0
    
    for tf_path in tool_files:
        if tf_path.name.startswith("__"): continue
        
        rel_path = str(tf_path.relative_to(BASE_DIR)).replace("\\", "/")
        name = tf_path.stem
        
        # In tools Tabelle prüfen
        cursor.execute("SELECT id, description FROM tools WHERE path = ? OR name = ?", (rel_path, name))
        row = cursor.fetchone()
        
        description, usage = extract_metadata(tf_path)
        
        if not row:
            # Neu in tools-Tabelle
            cursor.execute("""
                INSERT INTO tools (name, path, description, command, type, category, is_available, created_at)
                VALUES (?, ?, ?, ?, 'script', 'auto-discovery', 1, CURRENT_TIMESTAMP)
            """, (name, rel_path, description or name, usage))
            tools_added += 1
            current_desc = description or name
        else:
            current_desc = row['description'] or description or name

        # Trigger generieren
        hint = f"[TOOL] {name}: {current_desc} | {usage}"
        keywords = get_keywords(name, current_desc)
        
        for kw in keywords:
            try:
                cursor.execute("SELECT id, source FROM context_triggers WHERE trigger_phrase = ?", (kw,))
                t_row = cursor.fetchone()
                
                if not t_row:
                    cursor.execute("""
                        INSERT INTO context_triggers (trigger_phrase, hint_text, source)
                        VALUES (?, ?, 'tool')
                    """, (kw, hint))
                    triggers_added += 1
                elif t_row[1] == 'tool':
                    cursor.execute("""
                        UPDATE context_triggers SET hint_text = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (hint, t_row[0]))
                    triggers_updated += 1
            except sqlite3.Error:
                pass

    conn.commit()
    conn.close()
    print(f"[OK] {tools_added} neue Tools registriert.")
    print(f"[OK] {triggers_added} neue Trigger hinzugefügt, {triggers_updated} aktualisiert.")

if __name__ == "__main__":
    process_tools()
