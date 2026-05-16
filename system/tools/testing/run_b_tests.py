#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
B-Test Runner
=============
Fuehrt alle B-Tests (Beobachtung) fuer ein System aus.

Usage:
    python run_b_tests.py <system_path> [output_dir]

Beispiel:
    python run_b_tests.py "C:\\...\\recludOS" ".\\ERGEBNISSE\\recludOS"
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

# B-Test Definitionen
B_TESTS = [
    ("B001", "file_inventory", "Datei-Inventar"),
    ("B002", "format_consistency", "Format-Konsistenz"),
    ("B003", "directory_depth", "Verzeichnistiefe"),
    ("B004", "naming_analysis", "Naming-Analyse"),
    ("B005", "documentation_check", "Dokumentations-Check"),
    ("B006", "code_metrics", "Code-Metriken"),
    ("B007", "dependencies", "Abhaengigkeiten"),
    ("B008", "age_analysis", "Alter-Analyse"),
]

def run_b_tests(system_path: str, output_dir: str = None) -> dict:
    """Fuehrt alle B-Tests aus und sammelt Ergebnisse."""
    
    script_dir = Path(__file__).parent
    system_name = Path(system_path).name
    
    results = {
        "system": system_name,
        "system_path": system_path,
        "test_date": datetime.now().isoformat(),
        "tests": {},
        "summary": {
            "total": len(B_TESTS),
            "success": 0,
            "failed": 0,
            "avg_score": 0.0
        }
    }
    
    scores = []
    
    # PATH: Relativ zu diesem Skript
    b_tests_subdir = Path(__file__).resolve().parent.parent.parent / "skills" / "tools" / "testing" / "b_tests"
    
    for test_id, test_name, description in B_TESTS:
        script_name = f"{test_id}_{test_name}.py"
        script_path = b_tests_subdir / script_name
        
        print(f"\n[{test_id}] {description}...", end=" ")
        print(f"DEBUG: Checking {script_path.resolve()}")
        
        if not script_path.exists():
            print("SKIP (Script nicht gefunden)")
            results["tests"][test_id] = {"status": "skip", "error": "Script not found"}
            continue
        
        try:
            # Fuehre Test aus
            proc = subprocess.run(
                [sys.executable, str(script_path), system_path],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if proc.returncode == 0:
                test_result = json.loads(proc.stdout)
                score = test_result.get("score", 0)
                scores.append(score)
                
                results["tests"][test_id] = {
                    "status": "success",
                    "description": description,
                    "score": score,
                    "data": test_result
                }
                results["summary"]["success"] += 1
                print(f"OK (Score: {score})")
            else:
                results["tests"][test_id] = {
                    "status": "error",
                    "error": proc.stderr[:500]
                }
                results["summary"]["failed"] += 1
                print(f"FEHLER")
                
        except subprocess.TimeoutExpired:
            results["tests"][test_id] = {"status": "timeout"}
            results["summary"]["failed"] += 1
            print("TIMEOUT")
        except json.JSONDecodeError as e:
            results["tests"][test_id] = {"status": "parse_error", "error": str(e)}
            results["summary"]["failed"] += 1
            print("PARSE ERROR")
        except Exception as e:
            results["tests"][test_id] = {"status": "exception", "error": str(e)}
            results["summary"]["failed"] += 1
            print(f"EXCEPTION: {e}")
    
    # Durchschnitt berechnen
    if scores:
        results["summary"]["avg_score"] = round(sum(scores) / len(scores), 2)
    
    # Speichern falls output_dir
    if output_dir:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        
        filename = f"B_TEST_{system_name}_{datetime.now().strftime('%Y-%m-%d')}.json"
        out_file = out_path / filename
        
        with open(out_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"\n\nErgebnis gespeichert: {out_file}")
    
    return results

def main():
    if len(sys.argv) < 2:
        print("Usage: python run_b_tests.py <system_path> [output_dir]")
        print("\nBeispiel:")
        print('  python run_b_tests.py "C:\\...\\recludOS" ".\\ERGEBNISSE\\recludOS"')
        sys.exit(1)
    
    system_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None
    
    print(f"="*60)
    print(f"B-TEST RUNNER")
    print(f"System: {system_path}")
    print(f"="*60)
    
    results = run_b_tests(system_path, output_dir)
    
    print(f"\n{'='*60}")
    print(f"ZUSAMMENFASSUNG")
    print(f"{'='*60}")
    print(f"Tests: {results['summary']['success']}/{results['summary']['total']} erfolgreich")
    print(f"Durchschnitt: {results['summary']['avg_score']}/5.0")

if __name__ == "__main__":
    main()
