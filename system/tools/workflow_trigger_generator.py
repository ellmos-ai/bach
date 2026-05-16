#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: workflow_trigger_generator
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version workflow_trigger_generator

Description:
    [Beschreibung hinzufügen]

Usage:
    python workflow_trigger_generator.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

import os
import sqlite3
import re
from pathlib import Path

# Pfade
BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "bach.db"
WORKFLOW_DIR = BASE_DIR / "skills" / "_workflows"

def extract_metadata(file_path):
    """Extrahiert Titel und Ziel aus einer Workflow-Datei."""
    title = ""
    description = ""
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines:
                line = line.strip()
                if not title and line.startswith("# "):
                    title = line[2:].strip()
                if not description and (line.startswith("> **Ziel:**") or line.startswith(">**Ziel:**")):
                    description = line.replace("> **Ziel:**", "").replace(">**Ziel:**", "").strip()
                    # Markdown Fett entfernen
                    description = description.replace("**", "").strip()
                
                if title and description:
                    break
    except (OSError, ValueError, IndexError):
        pass

    return title, description

def get_keywords(filename, title):
    """Generiert Keywords aus Name und Titel."""
    keywords = set()
    
    # Aus Dateiname
    clean_name = filename.replace(".md", "").replace("-", " ").replace("_", " ")
    keywords.update(clean_name.split())
    keywords.add(filename.replace(".md", ""))
    
    # Aus Titel
    if title:
        # Nur wichtige Wörter (min 3 Zeichen)
        words = re.findall(r'\w{3,}', title.lower())
        keywords.update(words)
        
    # Stopwörter (sehr einfache Liste)
    stop = {"und", "der", "die", "das", "für", "auf", "mit", "von", "aus"}
    return {k for k in keywords if k not in stop}

def process_workflows():
    if not DB_PATH.exists():
        print("[ERROR] Datenbank nicht gefunden.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    print("Scanne Workflows...")
    workflows = list(WORKFLOW_DIR.glob("*.md"))
    
    added = 0
    updated = 0
    
    for wf_path in workflows:
        filename = wf_path.name
        title, goal = extract_metadata(wf_path)
        keywords = get_keywords(filename, title)
        
        # Hint Text zusammenstellen
        display_title = title if title else filename.replace(".md", "")
        hint = f"{display_title}"
        if goal:
            hint += f": {goal}"
        hint += f" | skills/workflows/{filename}"
        
        for kw in keywords:
            try:
                # Prüfen ob Trigger existiert
                cursor.execute("SELECT id, source FROM context_triggers WHERE trigger_phrase = ?", (kw,))
                row = cursor.fetchone()
                
                if not row:
                    cursor.execute("""
                        INSERT INTO context_triggers (trigger_phrase, hint_text, source)
                        VALUES (?, ?, 'workflow')
                    """, (kw, hint))
                    added += 1
                elif row[1] == 'workflow':
                    # Update vorhandenen Workflow-Trigger
                    cursor.execute("""
                        UPDATE context_triggers 
                        SET hint_text = ?, updated_at = CURRENT_TIMESTAMP 
                        WHERE id = ?
                    """, (hint, row[0]))
                    updated += 1
            except sqlite3.Error as e:
                print(f"[WARN] Fehler bei Trigger '{kw}': {e}")

    conn.commit()
    conn.close()
    print(f"[OK] {added} neue Trigger hinzugefügt, {updated} aktualisiert.")

if __name__ == "__main__":
    process_workflows()
