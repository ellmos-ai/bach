#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
System Comparator
=================
Erstellt Synopsen und Vergleiche zwischen LLM-OS Systemen.

Usage:
    python compare_systems.py <sys1> <sys2> [sys3 ...]
    python compare_systems.py --all
    python compare_systems.py --from-results

Beispiele:
    python compare_systems.py recludOS _BATCH
    python compare_systems.py --all
    python compare_systems.py --from-results --output synopse.md
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

# Bekannte Systeme (gleich wie run_external.py)
ONEDRIVE_ROOT = Path.home() / "OneDrive"
KNOWN_SYSTEMS = {
    "recludOS": str(ONEDRIVE_ROOT / ".AI" / "recludOS"),
    "BACH": str(ONEDRIVE_ROOT / ".AI" / "BACH"),
    "_BATCH": str(ONEDRIVE_ROOT / ".SOFTWARE" / "_BATCH"),
    "_CHIAH": str(ONEDRIVE_ROOT / ".SOFTWARE" / "_CHIAH"),
    "universal-llm-os-v2": str(ONEDRIVE_ROOT / ".AI" / "Templates" / "OS" / "universal-llm-os-v2"),
}


def get_script_dir():
    return Path(__file__).parent


def load_test_results(system_name: str) -> Dict[str, Any]:
    """Laedt Testergebnisse fuer ein System."""
    results_dir = get_script_dir() / "results" / system_name
    
    if not results_dir.exists():
        return {"status": "no_results"}
    
    # Suche neueste Ergebnisse
    b_files = list(results_dir.glob("B_TEST_*.json"))
    o_files = list(results_dir.glob("O_TEST_*.json"))
    
    result = {
        "system": system_name,
        "b_tests": None,
        "o_tests": None
    }
    
    if b_files:
        latest_b = max(b_files, key=lambda p: p.stat().st_mtime)
        with open(latest_b, 'r', encoding='utf-8') as f:
            result["b_tests"] = json.load(f)
    
    if o_files:
        latest_o = max(o_files, key=lambda p: p.stat().st_mtime)
        with open(latest_o, 'r', encoding='utf-8') as f:
            result["o_tests"] = json.load(f)
    
    return result


def analyze_skill_md(system_path: str) -> Dict[str, Any]:
    """Analysiert SKILL.md eines Systems."""
    path = Path(system_path)
    
    # Suche SKILL.md
    skill_paths = [
        path / "SKILL.md",
        path / "main" / "system" / "boot" / "SKILL.md",
        path / "SKILL.txt",
    ]
    
    skill_file = None
    for sp in skill_paths:
        if sp.exists():
            skill_file = sp
            break
    
    if not skill_file:
        return {"found": False}
    
    content = skill_file.read_text(encoding='utf-8', errors='ignore')
    
    return {
        "found": True,
        "path": str(skill_file),
        "size_kb": round(len(content) / 1024, 2),
        "lines": len(content.splitlines()),
        "has_frontmatter": content.startswith("---"),
        "has_quick_start": "quick start" in content.lower() or "quickstart" in content.lower(),
        "has_bootstrap": "bootstrap" in content.lower() or "startup" in content.lower(),
    }


def count_files(system_path: str) -> Dict[str, int]:
    """Zaehlt Dateien nach Typ."""
    path = Path(system_path)
    
    counts = {
        "python": 0,
        "markdown": 0,
        "json": 0,
        "txt": 0,
        "other": 0,
        "total": 0,
        "directories": 0,
    }
    
    try:
        for item in path.rglob("*"):
            if item.is_dir():
                counts["directories"] += 1
                continue
            
            counts["total"] += 1
            ext = item.suffix.lower()
            
            if ext == ".py":
                counts["python"] += 1
            elif ext == ".md":
                counts["markdown"] += 1
            elif ext == ".json":
                counts["json"] += 1
            elif ext == ".txt":
                counts["txt"] += 1
            else:
                counts["other"] += 1
    except Exception:
        pass
    
    return counts


def compare_systems(system_names: List[str]) -> Dict[str, Any]:
    """Vergleicht mehrere Systeme."""
    
    comparison = {
        "date": datetime.now().isoformat(),
        "systems": {},
        "ranking": [],
    }
    
    for name in system_names:
        path = KNOWN_SYSTEMS.get(name)
        if not path or not Path(path).exists():
            comparison["systems"][name] = {"status": "not_found"}
            continue
        
        # Sammle Daten
        system_data = {
            "path": path,
            "skill_md": analyze_skill_md(path),
            "file_counts": count_files(path),
            "test_results": load_test_results(name),
        }
        
        # Berechne Scores
        b_score = 0
        o_score = 0
        
        if system_data["test_results"].get("b_tests"):
            b_score = system_data["test_results"]["b_tests"].get("summary", {}).get("avg_score", 0)
        
        if system_data["test_results"].get("o_tests"):
            o_score = system_data["test_results"]["o_tests"].get("summary", {}).get("avg_score", 0)
        
        system_data["scores"] = {
            "b_score": b_score,
            "o_score": o_score,
            "total": round((b_score + o_score) / 2, 2) if b_score or o_score else 0
        }
        
        comparison["systems"][name] = system_data
    
    # Ranking erstellen
    ranked = sorted(
        [(name, data["scores"]["total"]) for name, data in comparison["systems"].items() 
         if data.get("scores")],
        key=lambda x: x[1],
        reverse=True
    )
    comparison["ranking"] = [{"rank": i+1, "system": name, "score": score} 
                             for i, (name, score) in enumerate(ranked)]
    
    return comparison


def generate_markdown_report(comparison: Dict[str, Any]) -> str:
    """Generiert Markdown-Bericht."""
    
    lines = [
        "# System-Vergleich (Synopse)",
        "",
        f"**Erstellt:** {comparison['date'][:10]}",
        f"**Systeme:** {len(comparison['systems'])}",
        "",
        "---",
        "",
        "## Ranking",
        "",
        "| Rang | System | Score |",
        "|:----:|--------|:-----:|",
    ]
    
    for item in comparison["ranking"]:
        lines.append(f"| {item['rank']} | **{item['system']}** | {item['score']}/5.0 |")
    
    lines.extend([
        "",
        "---",
        "",
        "## Detail-Vergleich",
        "",
        "| Aspekt |" + "|".join(f" {name} " for name in comparison["systems"].keys()) + "|",
        "|--------|" + "|".join(":------:" for _ in comparison["systems"]) + "|",
    ])
    
    # SKILL.md Groesse
    row = "| SKILL.md Groesse |"
    for name, data in comparison["systems"].items():
        if data.get("status") == "not_found":
            row += " N/A |"
        else:
            size = data.get("skill_md", {}).get("size_kb", "?")
            row += f" {size} KB |"
    lines.append(row)
    
    # Python-Dateien
    row = "| Python-Dateien |"
    for name, data in comparison["systems"].items():
        if data.get("status") == "not_found":
            row += " N/A |"
        else:
            count = data.get("file_counts", {}).get("python", 0)
            row += f" {count} |"
    lines.append(row)
    
    # B-Score
    row = "| B-Score |"
    for name, data in comparison["systems"].items():
        score = data.get("scores", {}).get("b_score", "N/A")
        row += f" {score} |"
    lines.append(row)
    
    # O-Score
    row = "| O-Score |"
    for name, data in comparison["systems"].items():
        score = data.get("scores", {}).get("o_score", "N/A")
        row += f" {score} |"
    lines.append(row)
    
    lines.extend([
        "",
        "---",
        "",
        "## Empfehlung",
        "",
    ])
    
    if comparison["ranking"]:
        winner = comparison["ranking"][0]
        lines.append(f"**Testsieger:** {winner['system']} mit {winner['score']}/5.0")
    
    lines.extend([
        "",
        "---",
        "",
        "*Generiert von BACH compare_systems.py*",
    ])
    
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    arg = sys.argv[1]
    output_file = None
    
    # Output-Parameter
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_file = sys.argv[idx + 1]
    
    if arg == "--all":
        systems = list(KNOWN_SYSTEMS.keys())
    elif arg == "--from-results":
        # Lade alle Systeme mit Ergebnissen
        results_dir = get_script_dir() / "results"
        systems = [d.name for d in results_dir.iterdir() if d.is_dir()]
    else:
        # Spezifische Systeme
        systems = [a for a in sys.argv[1:] if not a.startswith("--")]
    
    print(f"Vergleiche Systeme: {', '.join(systems)}")
    
    comparison = compare_systems(systems)
    report = generate_markdown_report(comparison)
    
    print("\n" + report)
    
    # Speichern
    if output_file:
        output_path = Path(output_file)
    else:
        output_path = get_script_dir() / "results" / f"SYNOPSE_{datetime.now().strftime('%Y-%m-%d')}.md"
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding='utf-8')
    print(f"\nGespeichert: {output_path}")
    
    # JSON auch speichern
    json_path = output_path.with_suffix(".json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(comparison, f, indent=2, ensure_ascii=False)
    print(f"JSON: {json_path}")


if __name__ == "__main__":
    main()
