#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: theme_packet_generator
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version theme_packet_generator

Description:
    [Beschreibung hinzufügen]

Usage:
    python theme_packet_generator.py [args]
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
SKILL_FILE = BASE_DIR / "SKILL.md"

def parse_skill_md():
    """Extrahiert Themen-Pakete aus SKILL.md."""
    if not SKILL_FILE.exists():
        return []

    with open(SKILL_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # Sektion suchen
    if "## THEMEN-PAKETE" not in content:
        return []

    section = content.split("## THEMEN-PAKETE")[1]
    # In Themen aufteilen
    themes = section.split("### THEMA: ")
    
    packets = []
    
    for t in themes[1:]: # Überspringe Header
        try:
            # Name und Paket-Name
            header_line = t.split("\n")[0]
            theme_name = header_line.split("(PAKET: ")[0].strip()
            packet_name = header_line.split("(PAKET: ")[1].replace(")", "").strip()
            
            # Keywords finden (beim "Wann lesen:" Teil)
            # Einfache Heuristik: Wir nehmen den Namen und Paketnamen als Trigger
            # plus Wörter aus "Wann lesen"
            triggers = {theme_name.lower(), packet_name.lower()}
            
            if "Wann lesen:" in t:
                wann_lesen = t.split("Wann lesen:")[1].split("\n")[0].strip()
                # Wörter extrahieren
                words = re.findall(r'\w{4,}', wann_lesen.lower())
                triggers.update(words)
            
            # Hilfe-Befehle extrahieren
            # Wir suchen nach `bach help ...` Blöcken
            cmds = re.findall(r'bach docs\docs\docs\help\s+([a-zA-Z0-9_\-]+)', t)
            if cmds:
                hint_cmds = ", ".join(f"help {c}" for c in cmds)
                hint = f"[THEMA-PAKET: {theme_name}] Relevante Hilfe: bach {hint_cmds}"
                packets.append({
                    'name': packet_name,
                    'triggers': list(triggers),
                    'hint': hint
                })
        except (IndexError, ValueError, KeyError):
            pass
            
    return packets

def sync_to_db(packets):
    if not DB_PATH.exists():
        return

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    print("Synchronisiere Themen-Pakete...")
    added = 0
    
    for p in packets:
        for trig in p['triggers']:
            try:
                # Wir löschen alte Themen-Trigger für dieses Keyword um Updates zu ermöglichen
                # oder wir prüfen auf source='theme'
                cursor.execute("""
                    INSERT OR REPLACE INTO context_triggers 
                    (trigger_phrase, hint_text, source, is_protected)
                    VALUES (?, ?, 'theme', 1)
                """, (trig, p['hint']))
                added += 1
            except sqlite3.Error as e:
                print(f"[WARN] Fehler bei Paket-Trigger '{trig}': {e}")

    conn.commit()
    conn.close()
    print(f"[OK] {added} Themen-Paket-Trigger synchronisiert.")

if __name__ == "__main__":
    packets = parse_skill_md()
    if packets:
        sync_to_db(packets)
    else:
        print("[WARN] Keine Themen-Pakete in SKILL.md gefunden.")
