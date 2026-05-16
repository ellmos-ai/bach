#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
External System Tester
======================
Fuehrt B/O/E-Tests auf externen LLM-OS Systemen aus.

Usage:
    python run_external.py <system_path> [--profile STANDARD]
    python run_external.py --list-known
    python run_external.py --all

Beispiele:
    python run_external.py "C:\\...\\recludOS"
    python run_external.py "C:\\...\\recludOS" --profile QUICK
    python run_external.py --all --profile STANDARD
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

# Bekannte Systeme
KNOWN_SYSTEMS = {
    # Pfade werden aus Umgebungsvariablen oder relativ aufgeloest
    # Beispiel: BACH_EXTERNAL_SYSTEMS=recludOS:/pfad/zu/recludOS,...
}

# Test-Profile
PROFILES = {
    "QUICK": {"b_tests": True, "o_tests": False, "e_tests": False},
    "STANDARD": {"b_tests": True, "o_tests": True, "e_tests": False},
    "FULL": {"b_tests": True, "o_tests": True, "e_tests": True},
}


def get_script_dir():
    return Path(__file__).parent


def run_b_tests(system_path: str, output_dir: Path) -> dict:
    """Fuehrt B-Tests aus."""
    script = get_script_dir() / "b_tests" / "run_b_tests.py"
    if not script.exists():
        # Fallback auf alten Pfad
        script = get_script_dir() / "run_b_tests.py"
    
    if not script.exists():
        return {"status": "skip", "error": "B-Test runner not found"}
    
    try:
        proc = subprocess.run(
            [sys.executable, str(script), system_path, str(output_dir)],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        # Lade Ergebnis-JSON
        system_name = Path(system_path).name
        result_file = output_dir / f"B_TEST_{system_name}_{datetime.now().strftime('%Y-%m-%d')}.json"
        
        if result_file.exists():
            with open(result_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        return {"status": "error", "stdout": proc.stdout, "stderr": proc.stderr}
        
    except Exception as e:
        return {"status": "exception", "error": str(e)}


def run_o_tests(system_path: str, output_dir: Path) -> dict:
    """Fuehrt O-Tests aus."""
    script = get_script_dir() / "o_tests" / "run_o_tests.py"
    if not script.exists():
        script = get_script_dir() / "run_o_tests.py"
    
    if not script.exists():
        return {"status": "skip", "error": "O-Test runner not found"}
    
    try:
        proc = subprocess.run(
            [sys.executable, str(script), system_path, str(output_dir)],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        system_name = Path(system_path).name
        result_file = output_dir / f"O_TEST_{system_name}_{datetime.now().strftime('%Y-%m-%d')}.json"
        
        if result_file.exists():
            with open(result_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        return {"status": "error", "stdout": proc.stdout, "stderr": proc.stderr}
        
    except Exception as e:
        return {"status": "exception", "error": str(e)}


def test_system(system_path: str, profile: str = "STANDARD") -> dict:
    """Testet ein externes System mit dem angegebenen Profil."""
    
    system_name = Path(system_path).name
    profile_config = PROFILES.get(profile, PROFILES["STANDARD"])
    
    # Output-Verzeichnis
    output_dir = get_script_dir() / "results" / system_name
    output_dir.mkdir(parents=True, exist_ok=True)
    
    results = {
        "system": system_name,
        "system_path": system_path,
        "profile": profile,
        "test_date": datetime.now().isoformat(),
        "b_tests": None,
        "o_tests": None,
        "e_tests": None,
        "summary": {}
    }
    
    print(f"\n{'='*60}")
    print(f"TESTE: {system_name}")
    print(f"Profil: {profile}")
    print(f"{'='*60}")
    
    # B-Tests
    if profile_config["b_tests"]:
        print("\n[B-TESTS] Beobachtungstests...")
        results["b_tests"] = run_b_tests(system_path, output_dir)
        b_score = results["b_tests"].get("summary", {}).get("avg_score", 0)
        print(f"  → Score: {b_score}/5.0")
    
    # O-Tests
    if profile_config["o_tests"]:
        print("\n[O-TESTS] Ausgabetests...")
        results["o_tests"] = run_o_tests(system_path, output_dir)
        o_score = results["o_tests"].get("summary", {}).get("avg_score", 0)
        print(f"  → Score: {o_score}/5.0")
    
    # E-Tests (manuell - nur Hinweis)
    if profile_config["e_tests"]:
        print("\n[E-TESTS] Erfahrungstests...")
        print("  → E-Tests erfordern manuelle Durchfuehrung durch Claude")
        results["e_tests"] = {"status": "manual", "note": "Requires Claude interaction"}
    
    # Zusammenfassung
    scores = []
    if results["b_tests"] and "summary" in results["b_tests"]:
        scores.append(results["b_tests"]["summary"].get("avg_score", 0))
    if results["o_tests"] and "summary" in results["o_tests"]:
        scores.append(results["o_tests"]["summary"].get("avg_score", 0))
    
    if scores:
        results["summary"]["avg_score"] = round(sum(scores) / len(scores), 2)
        results["summary"]["test_count"] = len(scores)
    
    # Speichern
    result_file = output_dir / f"EXTERNAL_TEST_{system_name}_{datetime.now().strftime('%Y-%m-%d')}.json"
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*60}")
    print(f"ERGEBNIS: {system_name}")
    print(f"Gesamt-Score: {results['summary'].get('avg_score', 'N/A')}/5.0")
    print(f"Gespeichert: {result_file}")
    print(f"{'='*60}")
    
    return results


def test_all_known(profile: str = "STANDARD") -> dict:
    """Testet alle bekannten Systeme."""
    results = {}
    
    for name, path in KNOWN_SYSTEMS.items():
        if Path(path).exists():
            results[name] = test_system(path, profile)
        else:
            print(f"\n[SKIP] {name}: Pfad nicht gefunden")
            results[name] = {"status": "not_found", "path": path}
    
    return results


def print_comparison(results: dict):
    """Druckt Vergleichstabelle."""
    print("\n" + "="*60)
    print("VERGLEICH ALLER SYSTEME")
    print("="*60)
    
    print(f"\n{'System':<25} {'B-Score':>10} {'O-Score':>10} {'Gesamt':>10}")
    print("-"*60)
    
    for name, data in results.items():
        if data.get("status") == "not_found":
            print(f"{name:<25} {'---':>10} {'---':>10} {'N/A':>10}")
            continue
        
        b_score = data.get("b_tests", {}).get("summary", {}).get("avg_score", "---")
        o_score = data.get("o_tests", {}).get("summary", {}).get("avg_score", "---")
        total = data.get("summary", {}).get("avg_score", "---")
        
        print(f"{name:<25} {str(b_score):>10} {str(o_score):>10} {str(total):>10}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    arg = sys.argv[1]
    profile = "STANDARD"
    
    # Profile aus Argumenten
    if "--profile" in sys.argv:
        idx = sys.argv.index("--profile")
        if idx + 1 < len(sys.argv):
            profile = sys.argv[idx + 1].upper()
    
    if arg == "--list-known":
        print("Bekannte Systeme:")
        for name, path in KNOWN_SYSTEMS.items():
            exists = "✓" if Path(path).exists() else "✗"
            print(f"  {exists} {name}: {path}")
    
    elif arg == "--all":
        results = test_all_known(profile)
        print_comparison(results)
    
    elif arg in KNOWN_SYSTEMS:
        test_system(KNOWN_SYSTEMS[arg], profile)
    
    elif Path(arg).exists():
        test_system(arg, profile)
    
    else:
        print(f"Fehler: Pfad nicht gefunden: {arg}")
        sys.exit(1)


if __name__ == "__main__":
    main()
