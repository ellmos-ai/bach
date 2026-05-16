#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: lesson_trigger_generator
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version lesson_trigger_generator

Description:
    [Beschreibung hinzufügen]

Usage:
    python lesson_trigger_generator.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

import sqlite3
import json
import re
from pathlib import Path

# Pfade
BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "bach.db"

def get_keywords(title, trigger_words_json):
    """Generiert Keywords aus Titel und trigger_words JSON."""
    keywords = set()
    
    # Aus Titel
    if title:
        words = re.findall(r'\w{3,}', title.lower())
        keywords.update(words)
    
    # Aus trigger_words (JSON Liste)
    if trigger_words_json:
        try:
            words = json.loads(trigger_words_json)
            if isinstance(words, list):
                for w in words:
                    keywords.add(w.lower())
        except (json.JSONDecodeError, ValueError):
            # Fallback falls kein JSON
            words = re.findall(r'\w{3,}', trigger_words_json.lower())
            keywords.update(words)
            
    # Stopwörter
    stop = {"und", "der", "die", "das", "für", "auf", "mit", "von", "aus"}
    return {k for k in keywords if k not in stop}

def process_lessons():
    if not DB_PATH.exists():
        print("[ERROR] Datenbank nicht gefunden.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("Verarbeite Lektionen...")
    cursor.execute("SELECT id, title, solution, trigger_words, severity FROM memory_lessons WHERE is_active = 1")
    lessons = cursor.fetchall()
    
    added = 0
    updated = 0
    
    for l in lessons:
        lesson_id = l['id']
        title = l['title']
        solution = l['solution']
        
        # Hint kürzen falls zu lang
        short_sol = solution[:80] + "..." if len(solution) > 80 else solution
        
        prefix = "[WARNUNG]" if l['severity'] in ('high', 'critical') else "[LEKTION]"
        hint = f"{prefix} {title}: {short_sol} | bach lesson show {lesson_id}"
        
        keywords = get_keywords(title, l['trigger_words'])
        
        for kw in keywords:
            try:
                # Prüfen ob Trigger existiert
                cursor.execute("SELECT id, source FROM context_triggers WHERE trigger_phrase = ?", (kw,))
                row = cursor.fetchone()
                
                if not row:
                    cursor.execute("""
                        INSERT INTO context_triggers (trigger_phrase, hint_text, source)
                        VALUES (?, ?, 'lesson')
                    """, (kw, hint))
                    added += 1
                elif row[1] == 'lesson':
                    # Update vorhandenen Lesson-Trigger
                    cursor.execute("""
                        UPDATE context_triggers 
                        SET hint_text = ?, updated_at = CURRENT_TIMESTAMP 
                        WHERE id = ?
                    """, (hint, row[0]))
                    updated += 1
                # Wenn source 'manual' oder 'workflow' ist, überschreiben wir nicht
            except sqlite3.Error as e:
                print(f"[WARN] Fehler bei Trigger '{kw}': {e}")

    conn.commit()
    conn.close()
    print(f"[OK] {added} neue Trigger hinzugefügt, {updated} aktualisiert.")

if __name__ == "__main__":
    process_lessons()
