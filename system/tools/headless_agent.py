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

"""
Tool: c_headless_agent
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version c_headless_agent

Description:
    [Beschreibung hinzufügen]

Usage:
    python c_headless_agent.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

# -*- coding: utf-8 -*-
"""
c_headless_agent.py - Headless AI Session Controller v1.0
=========================================================

Automatisierte Kommunikation mit KI-Partnern im Hintergrund.
Task: AI_001 (#455)

Nutzung:
    python tools/c_headless_agent.py "Prompt Text" [--partner claude]
"""

import sys
import sqlite3
import time
from datetime import datetime
from pathlib import Path

def run_headless_query(db_path: Path, prompt: str, partner: str = "claude"):
    """Sendet Prompt und wartet auf Antwort."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    now = datetime.now().isoformat()
    
    # 1. Nachricht senden (als user an partner)
    # Direction 'outbox' da user sendet
    print(f"[HEADLESS] Sende Prompt an {partner}...")
    conn.execute("""
        INSERT INTO messages (direction, sender, recipient, body, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("outbox", "user", partner, prompt, "read", now))
    
    conn.commit()
    
    # 2. Auf Antwort warten (Polling)
    print("[HEADLESS] Warte auf Antwort (Polling)...")
    max_wait = 120 # 2 Minuten
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        # Suche nach neuerer Nachricht von partner an user (inbox)
        response = conn.execute("""
            SELECT body, created_at FROM messages 
            WHERE sender = ? AND recipient = ? AND direction = 'inbox' AND created_at > ?
            ORDER BY created_at DESC LIMIT 1
        """, (partner, "user", now)).fetchone()
        
        if response:
            print(f"[HEADLESS] Antwort empfangen ({len(response['body'])} Zeichen).")
            conn.close()
            return {"success": True, "response": response['body']}
            
        time.sleep(5)
        
    conn.close()
    return {"success": False, "error": "Timeout beim Warten auf KI-Antwort"}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python c_headless_agent.py \"Prompt\" [--prompt-file PATH] [--partner NAME]")
        sys.exit(1)

    if "--prompt-file" in sys.argv:
        prompt_file = Path(sys.argv[sys.argv.index("--prompt-file") + 1])
        prompt_text = prompt_file.read_text(encoding="utf-8")
        try:
            prompt_file.unlink()
        except OSError:
            pass
    else:
        prompt_text = sys.argv[1]

    target_partner = "claude"
    if "--partner" in sys.argv:
        target_partner = sys.argv[sys.argv.index("--partner") + 1]
        
    base_dir = Path(__file__).parent.parent
    db_file = base_dir / "data" / "bach.db"
    
    res = run_headless_query(db_file, prompt_text, target_partner)
    if res['success']:
        print("\nKI ANTWORT:")
        print("-" * 50)
        print(res['response'])
        print("-" * 50)
    else:
        print(f"Fehler: {res['error']}")
