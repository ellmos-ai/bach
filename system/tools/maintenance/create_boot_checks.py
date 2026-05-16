# SPDX-License-Identifier: MIT
"""
boot_checks Tabelle erstellen - KRITISCH für Pre-Prompt Checks
Erstellt: 2026-01-21 (BACH Session)
"""
import sqlite3
import json
from pathlib import Path

try:
    from hub.bach_paths import BACH_DB
    db_path = BACH_DB
except ImportError:
    db_path = Path(__file__).parent.parent / "data" / "bach.db"

def create_boot_checks():
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # Prüfen ob Tabelle existiert
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='boot_checks'")
    if c.fetchone():
        print("[INFO] boot_checks Tabelle existiert bereits")
        c.execute("SELECT id, check_name, check_type, priority, enabled FROM boot_checks ORDER BY priority")
        rows = c.fetchall()
        print(f"\n[BOOT_CHECKS] {len(rows)} Einträge:")
        for r in rows:
            print(f"  [{r[0]}] P{r[3]} {r[1]} ({r[2]}) - enabled: {r[4]}")
        conn.close()
        return
    
    # Tabelle erstellen nach ROADMAP-Schema
    c.execute('''
    CREATE TABLE boot_checks (
        id INTEGER PRIMARY KEY,
        check_name TEXT NOT NULL,
        check_type TEXT,
        priority INTEGER DEFAULT 50,
        enabled INTEGER DEFAULT 1,
        last_run TIMESTAMP,
        last_result TEXT,
        config JSON
    )
    ''')
    print("[OK] boot_checks Tabelle erstellt")
    
    # Initiale Checks aus bootsektor.md einfügen
    initial_checks = [
        ("message_box_scan", "micro_routine", 10, 1, None, None, 
         json.dumps({"scan_dir": "user/", "patterns": ["*.msg", "messages.txt"]})),
        ("token_budget_check", "validation", 20, 1, None, None, 
         json.dumps({"warning_threshold": 0.6, "critical_threshold": 0.8})),
        ("snapshot_load", "init", 30, 1, None, None, 
         json.dumps({"auto_load": True})),
        ("daily_initialization", "init", 40, 1, None, None, 
         json.dumps({"tasks": ["calendar_sync", "backup_check"]})),
        ("path_healer_dryrun", "validation", 50, 1, None, None, 
         json.dumps({"dry_run": True, "auto_fix": False})),
    ]
    
    c.executemany('''
        INSERT INTO boot_checks (check_name, check_type, priority, enabled, last_run, last_result, config)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', initial_checks)
    print(f"[OK] {len(initial_checks)} initiale Checks eingefügt")
    
    conn.commit()
    
    # Verifizieren
    c.execute("SELECT id, check_name, check_type, priority, enabled FROM boot_checks ORDER BY priority")
    rows = c.fetchall()
    print(f"\n[BOOT_CHECKS] {len(rows)} Einträge:")
    for r in rows:
        print(f"  [{r[0]}] P{r[3]} {r[1]} ({r[2]}) - enabled: {r[4]}")
    
    conn.close()
    print("\n[FERTIG] boot_checks Tabelle ist einsatzbereit für Pre-Prompt Checks")

if __name__ == "__main__":
    create_boot_checks()
