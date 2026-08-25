#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
B001 - Datei-Inventar
=====================
Zaehlt und kategorisiert alle Dateien eines Systems.

Output: JSON mit Datei-Statistiken nach Typ
"""

import os
import json
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime

def analyze_system(root_path: str) -> dict:
    """Analysiert ein System und erstellt Datei-Inventar."""
    
    root = Path(root_path)
    if not root.exists():
        return {"error": f"Pfad existiert nicht: {root_path}"}
    
    # Zaehler
    stats = {
        "test_id": "B001",
        "test_name": "Datei-Inventar",
        "system_path": str(root),
        "scan_date": datetime.now().isoformat(),
        # B001 beobachtet den Bestand. Der Score bewertet daher ausschliesslich,
        # ob das Inventar vollständig erstellt werden konnte, nicht die Qualität
        # des untersuchten Systems.
        "status": "PASS",
        "score": 5.0,
        "score_explanation": "Das Inventar wurde vollständig erstellt; der Score ist keine Qualitätsbewertung des Systems.",
        "total_files": 0,
        "total_dirs": 0,
        "total_size_bytes": 0,
        "by_extension": defaultdict(lambda: {"count": 0, "size": 0}),
        "by_category": defaultdict(lambda: {"count": 0, "size": 0, "files": []}),
        "special_files": []
    }
    
    # Kategorien-Mapping
    categories = {
        ".md": "documentation",
        ".txt": "documentation",
        ".json": "config",
        ".yaml": "config",
        ".yml": "config",
        ".toml": "config",
        ".py": "code",
        ".js": "code",
        ".ts": "code",
        ".sh": "code",
        ".bat": "code",
        ".ps1": "code",
        ".sql": "data",
        ".db": "data",
        ".sqlite": "data",
        ".csv": "data",
        ".log": "logs",
    }
    
    # Spezielle Dateien die wir tracken wollen
    special_names = ["SKILL.md", "SKILL.txt", "README.md", "CHANGELOG", 
                     "config.json", "settings.json", ".env"]
    
    # Durchlaufe Verzeichnisbaum
    for item in root.rglob("*"):
        # Ignoriere versteckte und temporaere
        if any(part.startswith('.') for part in item.parts[len(root.parts):]):
            if item.name not in special_names:
                continue
        if "__pycache__" in str(item) or "node_modules" in str(item):
            continue
            
        if item.is_file():
            stats["total_files"] += 1
            try:
                size = item.stat().st_size
                stats["total_size_bytes"] += size
            except:
                size = 0
            
            ext = item.suffix.lower() or "(keine)"
            stats["by_extension"][ext]["count"] += 1
            stats["by_extension"][ext]["size"] += size
            
            category = categories.get(ext, "other")
            stats["by_category"][category]["count"] += 1
            stats["by_category"][category]["size"] += size
            
            # Spezielle Dateien merken
            if item.name in special_names:
                stats["special_files"].append({
                    "name": item.name,
                    "path": str(item.relative_to(root)),
                    "size": size
                })
                
        elif item.is_dir():
            stats["total_dirs"] += 1
    
    # Konvertiere defaultdicts zu normalen dicts
    stats["by_extension"] = dict(stats["by_extension"])
    stats["by_category"] = {k: {"count": v["count"], "size": v["size"]} 
                            for k, v in stats["by_category"].items()}
    
    # Berechne Metriken
    stats["metrics"] = {
        "files_per_dir": round(stats["total_files"] / max(stats["total_dirs"], 1), 2),
        "avg_file_size": round(stats["total_size_bytes"] / max(stats["total_files"], 1), 2),
        "doc_ratio": round(stats["by_category"].get("documentation", {}).get("count", 0) 
                          / max(stats["total_files"], 1) * 100, 1),
        "code_ratio": round(stats["by_category"].get("code", {}).get("count", 0) 
                           / max(stats["total_files"], 1) * 100, 1),
    }
    stats["summary"] = f"Inventar für {stats['total_files']} Dateien und {stats['total_dirs']} Verzeichnisse erstellt"
    
    return stats

def main():
    if len(sys.argv) < 2:
        print("Usage: python B001_file_inventory.py <system_path> [output_json]")
        sys.exit(1)
    
    system_path = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    result = analyze_system(system_path)
    
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"Ergebnis gespeichert: {output_file}")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
