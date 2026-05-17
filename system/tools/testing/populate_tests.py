# SPDX-License-Identifier: MIT
"""
BACH_STREAM Test Library - Database Population
"""
import sqlite3
import json
import os
from pathlib import Path

TEST_ROOT = Path(
    os.getenv(
        "BACH_TEST_LIBRARY_ROOT",
        Path.home() / "OneDrive" / ".AI" / "BACH_STREAM" / "DOCS" / "TESTS",
    )
)
DB_PATH = str(TEST_ROOT / "test_library.db")
SCHEMA_PATH = str(TEST_ROOT / "test_schema.sql")

# Schema laden und ausfuehren
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
    cursor.executescript(f.read())

# ═══════════════════════════════════════════════════════════════════════════
# TESTAUFGABEN
# ═══════════════════════════════════════════════════════════════════════════
test_tasks = [
    ("A001", "Task erstellen", "Task-Management", "basis", 120,
     '["task_system"]', "AUFGABEN/A001_task_create.md",
     "Erstelle einen neuen Task mit Titel, Beschreibung und Prioritaet"),
    
    ("A002", "Task finden", "Task-Management", "basis", 60,
     '["task_system"]', "AUFGABEN/A002_task_find.md",
     "Finde einen existierenden Task oder den Task-Speicherort"),
    
    ("A003", "Memory schreiben", "Memory", "basis", 90,
     '["memory_short_term", "memory_long_term"]', "AUFGABEN/A003_memory_write.md",
     "Speichere Information in Kurzzeit- und Langzeit-Memory"),
    
    ("A004", "Memory lesen (Kontext)", "Memory", "mittel", 120,
     '["memory_short_term", "memory_long_term", "memory_context_sources"]', "AUFGABEN/A004_memory_read.md",
     "Simuliere Neustart und stelle Kontext wieder her"),
    
    ("A005", "Dateisystem navigieren", "Navigation", "basis", 210,
     '["docs_system", "docs_directory_truth"]', "AUFGABEN/A005_filesystem_navigate.md",
     "Erkunde das Dateisystem und finde wichtige Bereiche"),
    
    ("A006", "Tool finden und nutzen", "Tools", "mittel", 180,
     '["tools_registry", "tools_action_hub"]', "AUFGABEN/A006_tool_use.md",
     "Finde verfuegbare Tools und nutze eines"),
    
    ("A007", "SKILL.md Lesbarkeit", "Onboarding", "basis", 240,
     '["all"]', "AUFGABEN/A007_skill_readability.md",
     "Lies und bewerte das SKILL.md des Systems"),
    
    ("A008", "Fehlerfall simulieren", "Fehlertoleranz", "fortgeschritten", 270,
     '["session_crash_recovery", "backup_trash"]', "AUFGABEN/A008_error_recovery.md",
     "Suche nach Recovery-Mechanismen und Backups"),
    
    ("A009", "Session starten", "Session-Management", "mittel", 180,
     '["session_start_protocol"]', "AUFGABEN/A009_session_start.md",
     "Fuehre den dokumentierten Start-Prozess durch"),
    
    ("A010", "Gesamteindruck", "Meta", None, 150,
     '["all"]', "AUFGABEN/A010_overall_impression.md",
     "Fasse Gesamteindruck zusammen und bewerte alle Dimensionen"),
]

cursor.executemany("""
    INSERT OR REPLACE INTO test_tasks 
    (id, name, category, difficulty, expected_time_sec, feature_tests, file_path, description)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
""", test_tasks)

# ═══════════════════════════════════════════════════════════════════════════
# TESTPROFILE
# ═══════════════════════════════════════════════════════════════════════════
test_profiles = [
    ("STANDARD", "Standard-Testprofil fuer vollstaendige Systembewertung", 30,
     '["A007", "A005", "A002", "A001", "A003", "A004", "A006", "A009", "A010"]'),
    
    ("QUICK", "Schnelltest fuer erste Eindruecke", 10,
     '["A007", "A005", "A010"]'),
    
    ("FULL", "Vollstaendiger Test inkl. Fehlertoleranz", 45,
     '["A007", "A005", "A002", "A001", "A003", "A004", "A006", "A008", "A009", "A010"]'),
    
    ("MEMORY_FOCUS", "Fokus auf Memory-System", 15,
     '["A003", "A004", "A010"]'),
    
    ("TASK_FOCUS", "Fokus auf Task-Management", 15,
     '["A001", "A002", "A010"]'),
    
    ("ONBOARDING_ONLY", "Nur Onboarding-Test", 8,
     '["A007", "A010"]'),
]

cursor.executemany("""
    INSERT OR REPLACE INTO test_profiles 
    (name, description, estimated_time_min, test_ids)
    VALUES (?, ?, ?, ?)
""", test_profiles)

conn.commit()

# Statistik
cursor.execute("SELECT COUNT(*) FROM test_tasks")
print(f"Testaufgaben: {cursor.fetchone()[0]}")

cursor.execute("SELECT COUNT(*) FROM test_profiles")
print(f"Testprofile: {cursor.fetchone()[0]}")

conn.close()
print("\nTest-Library Datenbank erstellt!")
