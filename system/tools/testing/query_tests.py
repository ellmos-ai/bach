# SPDX-License-Identifier: MIT
"""
BACH_STREAM Selbsterfahrungsprotokoll - Test Runner & Query Tool
"""
import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, List

TEST_ROOT = Path(
    os.getenv(
        "BACH_TEST_LIBRARY_ROOT",
        Path.home() / "OneDrive" / ".AI" / "BACH_STREAM" / "DOCS" / "TESTS",
    )
)
DB_PATH = str(TEST_ROOT / "test_library.db")

def get_connection():
    return sqlite3.connect(DB_PATH)

# ═══════════════════════════════════════════════════════════════════════════
# TESTAUFGABEN ANZEIGEN
# ═══════════════════════════════════════════════════════════════════════════
def list_tasks(category: Optional[str] = None):
    """Liste alle Testaufgaben"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = "SELECT id, name, category, difficulty, expected_time_sec FROM test_tasks"
    if category:
        query += f" WHERE category LIKE '%{category}%'"
    query += " ORDER BY id"
    
    cursor.execute(query)
    results = cursor.fetchall()
    
    print("\n" + "="*70)
    print("TESTAUFGABEN-BIBLIOTHEK")
    print("="*70)
    print(f"{'ID':<6} {'Name':<30} {'Kategorie':<18} {'Zeit':<8}")
    print("-"*70)
    
    for row in results:
        tid, name, cat, diff, time_sec = row
        time_str = f"{time_sec}s" if time_sec else "-"
        print(f"{tid:<6} {name:<30} {cat:<18} {time_str:<8}")
    
    conn.close()

# ═══════════════════════════════════════════════════════════════════════════
# TESTPROFILE ANZEIGEN
# ═══════════════════════════════════════════════════════════════════════════
def list_profiles():
    """Liste alle Testprofile"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT name, description, estimated_time_min, test_ids FROM test_profiles")
    results = cursor.fetchall()
    
    print("\n" + "="*70)
    print("TESTPROFILE")
    print("="*70)
    
    for row in results:
        name, desc, time_min, test_ids = row
        tests = json.loads(test_ids)
        print(f"\n{name} (~{time_min} Min)")
        print(f"  {desc}")
        print(f"  Tests: {', '.join(tests)}")
    
    conn.close()

# ═══════════════════════════════════════════════════════════════════════════
# TESTLAUF STARTEN
# ═══════════════════════════════════════════════════════════════════════════
def start_run(system_name: str, profile_name: str = "STANDARD", tester: str = "Claude"):
    """Starte einen neuen Testlauf"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Profil laden
    cursor.execute("SELECT test_ids FROM test_profiles WHERE name = ?", (profile_name,))
    result = cursor.fetchone()
    if not result:
        print(f"Profil nicht gefunden: {profile_name}")
        return None
    
    test_ids = json.loads(result[0])
    
    # Run erstellen
    cursor.execute("""
        INSERT INTO test_runs (system_name, profile_name, started_at, tester)
        VALUES (?, ?, ?, ?)
    """, (system_name, profile_name, datetime.now().isoformat(), tester))
    
    run_id = cursor.lastrowid
    conn.commit()
    
    print("\n" + "="*70)
    print(f"TESTLAUF GESTARTET")
    print("="*70)
    print(f"System: {system_name}")
    print(f"Profil: {profile_name}")
    print(f"Run-ID: {run_id}")
    print(f"Tests: {', '.join(test_ids)}")
    print("\nFuehre nun die Tests der Reihe nach durch.")
    print("Nutze 'record_result' um Ergebnisse zu speichern.")
    
    conn.close()
    return run_id

# ═══════════════════════════════════════════════════════════════════════════
# ERGEBNIS SPEICHERN
# ═══════════════════════════════════════════════════════════════════════════
def record_result(
    run_id: int,
    task_id: str,
    t_total_sec: float,
    success: int,  # 0=failed, 1=partial, 2=success
    n_files_touched: int = 0,
    n_steps: int = 0,
    rating_clarity: int = 3,
    rating_simplicity: int = 3,
    rating_documentation: int = 3,
    observations: str = "",
    difficulties: str = ""
):
    """Speichere Ergebnis eines einzelnen Tests"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO test_results 
        (run_id, task_id, t_total_sec, success, n_files_touched, n_steps,
         rating_clarity, rating_simplicity, rating_documentation, observations, difficulties)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (run_id, task_id, t_total_sec, success, n_files_touched, n_steps,
          rating_clarity, rating_simplicity, rating_documentation, observations, difficulties))
    
    conn.commit()
    
    success_str = ["FAILED", "PARTIAL", "SUCCESS"][success]
    print(f"[{task_id}] {success_str} in {t_total_sec}s gespeichert")
    
    conn.close()

# ═══════════════════════════════════════════════════════════════════════════
# DIMENSIONSBEWERTUNG SPEICHERN
# ═══════════════════════════════════════════════════════════════════════════
def record_dimensions(
    run_id: int,
    d1_onboarding: int,
    d2_navigation: int,
    d3_memory: int,
    d4_task_management: int,
    d5_communication: int,
    d6_tools: int,
    d7_error_tolerance: int,
    overall_rating: float,
    strengths: str = "",
    weaknesses: str = "",
    recommendations: str = ""
):
    """Speichere Dimensionsbewertungen"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO dimension_ratings 
        (run_id, d1_onboarding, d2_navigation, d3_memory, d4_task_management,
         d5_communication, d6_tools, d7_error_tolerance, overall_rating,
         strengths, weaknesses, recommendations)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (run_id, d1_onboarding, d2_navigation, d3_memory, d4_task_management,
          d5_communication, d6_tools, d7_error_tolerance, overall_rating,
          strengths, weaknesses, recommendations))
    
    # Run als abgeschlossen markieren
    cursor.execute("UPDATE test_runs SET completed_at = ? WHERE id = ?",
                   (datetime.now().isoformat(), run_id))
    
    conn.commit()
    print(f"Dimensionsbewertungen fuer Run {run_id} gespeichert")
    conn.close()

# ═══════════════════════════════════════════════════════════════════════════
# ERGEBNISSE ANZEIGEN
# ═══════════════════════════════════════════════════════════════════════════
def show_results(system_name: Optional[str] = None):
    """Zeige Testergebnisse"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = """
    SELECT 
        tr.system_name,
        tr.profile_name,
        tr.started_at,
        dr.overall_rating,
        dr.d1_onboarding,
        dr.d2_navigation,
        dr.d3_memory,
        dr.d4_task_management,
        dr.d6_tools
    FROM test_runs tr
    LEFT JOIN dimension_ratings dr ON tr.id = dr.run_id
    """
    if system_name:
        query += f" WHERE tr.system_name = '{system_name}'"
    query += " ORDER BY tr.started_at DESC"
    
    cursor.execute(query)
    results = cursor.fetchall()
    
    print("\n" + "="*90)
    print("TESTERGEBNISSE")
    print("="*90)
    print(f"{'System':<15} {'Profil':<12} {'Datum':<12} {'Gesamt':<8} {'Onb':<5} {'Nav':<5} {'Mem':<5} {'Task':<5} {'Tool':<5}")
    print("-"*90)
    
    for row in results:
        sys, prof, date, overall, d1, d2, d3, d4, d6 = row
        date_short = date[:10] if date else "-"
        overall_str = f"{overall:.1f}" if overall else "-"
        print(f"{sys:<15} {prof or '-':<12} {date_short:<12} {overall_str:<8} {d1 or '-':<5} {d2 or '-':<5} {d3 or '-':<5} {d4 or '-':<5} {d6 or '-':<5}")
    
    conn.close()

# ═══════════════════════════════════════════════════════════════════════════
# SYSTEMVERGLEICH
# ═══════════════════════════════════════════════════════════════════════════
def compare_systems(systems: List[str] = None):
    """Vergleiche Durchschnittswerte mehrerer Systeme"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = """
    SELECT 
        system_name,
        n_runs,
        ROUND(avg_onboarding, 1) as onboarding,
        ROUND(avg_navigation, 1) as navigation,
        ROUND(avg_memory, 1) as memory,
        ROUND(avg_task, 1) as task,
        ROUND(avg_tools, 1) as tools,
        ROUND(avg_overall, 1) as overall
    FROM system_averages
    """
    if systems:
        sys_list = "', '".join(systems)
        query += f" WHERE system_name IN ('{sys_list}')"
    
    cursor.execute(query)
    results = cursor.fetchall()
    
    if not results:
        print("Keine Daten vorhanden. Fuehre zuerst Tests durch.")
        return
    
    print("\n" + "="*80)
    print("SYSTEMVERGLEICH (Durchschnittswerte)")
    print("="*80)
    print(f"{'System':<18} {'Runs':<6} {'Onb':<6} {'Nav':<6} {'Mem':<6} {'Task':<6} {'Tool':<6} {'Ges.':<6}")
    print("-"*80)
    
    for row in results:
        sys, runs, onb, nav, mem, task, tool, overall = row
        print(f"{sys:<18} {runs:<6} {onb or '-':<6} {nav or '-':<6} {mem or '-':<6} {task or '-':<6} {tool or '-':<6} {overall or '-':<6}")
    
    conn.close()

# ═══════════════════════════════════════════════════════════════════════════
# ZEITMESSUNGEN
# ═══════════════════════════════════════════════════════════════════════════
def show_times(system_name: Optional[str] = None):
    """Zeige Zeitmessungen pro Task"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = """
    SELECT 
        system_name,
        task_id,
        task_name,
        ROUND(avg_time_sec, 0) as avg_sec,
        expected_time_sec
    FROM task_times
    """
    if system_name:
        query += f" WHERE system_name = '{system_name}'"
    query += " ORDER BY system_name, task_id"
    
    cursor.execute(query)
    results = cursor.fetchall()
    
    if not results:
        print("Keine Zeitmessungen vorhanden.")
        return
    
    print("\n" + "="*80)
    print("ZEITMESSUNGEN")
    print("="*80)
    
    current_sys = None
    for row in results:
        sys, task_id, task_name, avg_sec, expected = row
        if sys != current_sys:
            print(f"\n--- {sys} ---")
            current_sys = sys
        
        diff = ""
        if avg_sec and expected:
            ratio = avg_sec / expected
            if ratio < 0.8:
                diff = " (schneller)"
            elif ratio > 1.5:
                diff = " (langsamer)"
        
        print(f"  {task_id}: {avg_sec or '-'}s (erwartet: {expected}s){diff}")
    
    conn.close()

# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("""
BACH_STREAM Selbsterfahrungsprotokoll - Test Tool
==================================================
Befehle:
  tasks [kategorie]        - Liste Testaufgaben
  profiles                 - Liste Testprofile
  start <system> [profil]  - Starte Testlauf
  results [system]         - Zeige Ergebnisse
  compare [sys1,sys2,...]  - Vergleiche Systeme
  times [system]           - Zeige Zeitmessungen
  
Beispiele:
  python query_tests.py tasks
  python query_tests.py profiles
  python query_tests.py start _CHIAH STANDARD
  python query_tests.py results _BATCH
  python query_tests.py compare _CHIAH,_BATCH,recludOS
""")
        sys.exit(0)
    
    cmd = sys.argv[1].lower()
    
    if cmd == "tasks":
        category = sys.argv[2] if len(sys.argv) > 2 else None
        list_tasks(category)
    elif cmd == "profiles":
        list_profiles()
    elif cmd == "start":
        if len(sys.argv) < 3:
            print("Fehler: System-Name erforderlich")
        else:
            system = sys.argv[2]
            profile = sys.argv[3] if len(sys.argv) > 3 else "STANDARD"
            start_run(system, profile)
    elif cmd == "results":
        system = sys.argv[2] if len(sys.argv) > 2 else None
        show_results(system)
    elif cmd == "compare":
        systems = sys.argv[2].split(",") if len(sys.argv) > 2 else None
        compare_systems(systems)
    elif cmd == "times":
        system = sys.argv[2] if len(sys.argv) > 2 else None
        show_times(system)
    else:
        print(f"Unbekannter Befehl: {cmd}")
