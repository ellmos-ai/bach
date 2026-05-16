#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
O-Test Runner
=============
Fuehrt alle O-Tests (Ausgabe/Output) fuer ein System aus.

Usage:
    python run_o_tests.py <system_path> [output_dir]

Beispiel:
    python run_o_tests.py "C:\\...\\recludOS" ".\\ERGEBNISSE\\recludOS"
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

# O-Test Definitionen
O_TESTS = [
    ("O001", "task_roundtrip", "Task-Roundtrip"),
    ("O002", "memory_persistence", "Memory-Persistenz"),
    ("O003", "tool_registry", "Tool-Registry"),
    ("O004", "backup_restore", "Backup-Restore"),
    ("O005", "config_validation", "Config-Validierung"),
    ("O006", "export_import", "Export-Import"),
]

def run_o_tests(system_path: str, output_dir: str = None) -> dict:
    """Fuehrt alle O-Tests aus und sammelt Ergebnisse."""
    
    script_dir = Path(__file__).parent
    system_name = Path(system_path).name
    
    results = {
        "system": system_name,
        "system_path": system_path,
        "test_date": datetime.now().isoformat(),
        "tests": {},
        "summary": {
            "total": len(O_TESTS),
            "pass": 0,
            "partial": 0,
            "fail": 0,
            "avg_score": 0.0
        }
    }
    
    scores = []
    
    # PATH: Relativ zu diesem Skript
    o_tests_subdir = Path(__file__).resolve().parent.parent.parent / "skills" / "tools" / "testing" / "o_tests"

    for test_id, test_name, description in O_TESTS:
        script_name = f"{test_id}_{test_name}.py"
        script_path = o_tests_subdir / script_name
        
        print(f"\n[{test_id}] {description}...", end=" ")
        
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
                timeout=120
            )
            
            if proc.returncode == 0:
                test_result = json.loads(proc.stdout)
                score = test_result.get("score", 0)
                status = test_result.get("status", "UNKNOWN")
                scores.append(score)
                
                results["tests"][test_id] = {
                    "description": description,
                    "status": status,
                    "score": score,
                    "summary": test_result.get("summary", ""),
                    "data": test_result
                }
                
                # Zaehle Status
                if status == "PASS":
                    results["summary"]["pass"] += 1
                elif status == "PARTIAL":
                    results["summary"]["partial"] += 1
                else:
                    results["summary"]["fail"] += 1
                
                print(f"{status} (Score: {score})")
            else:
                results["tests"][test_id] = {
                    "status": "ERROR",
                    "error": proc.stderr[:500]
                }
                results["summary"]["fail"] += 1
                print(f"ERROR")
                
        except subprocess.TimeoutExpired:
            results["tests"][test_id] = {"status": "TIMEOUT"}
            results["summary"]["fail"] += 1
            print("TIMEOUT")
        except json.JSONDecodeError as e:
            results["tests"][test_id] = {"status": "PARSE_ERROR", "error": str(e)}
            results["summary"]["fail"] += 1
            print("PARSE ERROR")
        except Exception as e:
            results["tests"][test_id] = {"status": "EXCEPTION", "error": str(e)}
            results["summary"]["fail"] += 1
            print(f"EXCEPTION: {e}")
    
    # Durchschnitt berechnen
    if scores:
        results["summary"]["avg_score"] = round(sum(scores) / len(scores), 2)
    
    # Speichern falls output_dir
    if output_dir:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        
        filename = f"O_TEST_{system_name}_{datetime.now().strftime('%Y-%m-%d')}.json"
        out_file = out_path / filename
        
        with open(out_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"\n\nErgebnis gespeichert: {out_file}")
    
    return results

def main():
    if len(sys.argv) < 2:
        print("Usage: python run_o_tests.py <system_path> [output_dir]")
        print("\nBeispiel:")
        print('  python run_o_tests.py "C:\\...\\recludOS" ".\\ERGEBNISSE\\recludOS"')
        sys.exit(1)
    
    system_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None
    
    print(f"="*60)
    print(f"O-TEST RUNNER (Output/Funktionale Tests)")
    print(f"System: {system_path}")
    print(f"="*60)
    
    results = run_o_tests(system_path, output_dir)
    
    print(f"\n{'='*60}")
    print(f"ZUSAMMENFASSUNG")
    print(f"{'='*60}")
    print(f"PASS: {results['summary']['pass']} | PARTIAL: {results['summary']['partial']} | FAIL: {results['summary']['fail']}")
    print(f"Durchschnitt: {results['summary']['avg_score']}/5.0")

if __name__ == "__main__":
    main()
