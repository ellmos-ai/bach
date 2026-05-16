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

"""Tiefe Analyse des Tools-Ordners mit Kategorisierung und Duplikat-Erkennung"""
import re
from pathlib import Path
from collections import defaultdict


CATEGORIES = [
    "code_quality", "maintenance", "testing", "generators", "migration",
    "archive", "agents", "communication", "analysis", "data",
    "integration", "utility", "unclear",
]


def categorize_file(filepath, content):
    name = filepath.name
    if "_archive" in str(filepath):
        return "archive"
    if "test" in str(filepath).lower() or name.startswith(("B0", "O0")):
        return "testing"
    if "agent" in name.lower():
        return "agents"
    if any(x in name for x in ["sync", "registry", "boot", "migrate", "health"]):
        return "maintenance"
    if "generat" in name or "export" in name or "skill_" in name:
        return "generators"
    if "migrat" in name and "_archive" not in str(filepath):
        return "migration"
    if "communication" in str(filepath) or "partner" in name:
        return "communication"
    if any(x in str(filepath) for x in ["ocr", "rag", "ollama", "mcp"]):
        return "integration"
    if name.startswith("c_"):
        return "code_quality"
    if any(x in name for x in ["analyz", "scan", "check", "inspect", "audit"]):
        return "analysis"
    if any(x in name for x in ["import", "data_", "db_", "schema"]):
        return "data"
    if any(x in name for x in ["util", "helper", "tool"]):
        return "utility"
    return "unclear"


def extract_functions(content):
    return re.findall(r'^def\s+(\w+)\s*\(', content, re.MULTILINE)


def check_quality(filepath, content):
    metrics = {}
    metrics["has_docstring"] = '"""' in content or "'''" in content
    metrics["has_main_guard"] = 'if __name__ == "__main__"' in content
    metrics["has_argparse"] = "argparse" in content or "ArgumentParser" in content
    metrics["has_error_handling"] = bool(re.search(r'\btry\b.*?\bexcept\b', content, re.DOTALL))
    lines = content.split("\n")
    metrics["line_count"] = len(lines)
    metrics["non_empty_lines"] = len([l for l in lines if l.strip()])
    imports = re.findall(r'^\s*(?:from|import)\s+(\w+)', content, re.MULTILINE)
    metrics["imports"] = imports
    return metrics


if __name__ == "__main__":
    tools_dir = Path("tools")

    categories = {cat: [] for cat in CATEGORIES}
    function_hashes = defaultdict(list)
    similar_names = defaultdict(list)
    quality_metrics = {
        "has_docstring": 0,
        "has_main_guard": 0,
        "has_argparse": 0,
        "has_error_handling": 0,
        "imports_count": defaultdict(int),
        "total_lines": 0,
        "empty_or_minimal": [],
    }

    all_files = []
    for pyfile in sorted(tools_dir.glob("**/*.py")):
        if "node_modules" in str(pyfile) or "__pycache__" in str(pyfile):
            continue

        try:
            content = pyfile.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            try:
                content = pyfile.read_text(encoding="latin-1")
            except OSError:
                content = ""

        rel_path = str(pyfile.relative_to(tools_dir))
        category = categorize_file(pyfile, content)
        categories[category].append(rel_path)

        qm = check_quality(pyfile, content)
        if qm["has_docstring"]:
            quality_metrics["has_docstring"] += 1
        if qm["has_main_guard"]:
            quality_metrics["has_main_guard"] += 1
        if qm["has_argparse"]:
            quality_metrics["has_argparse"] += 1
        if qm["has_error_handling"]:
            quality_metrics["has_error_handling"] += 1

        quality_metrics["total_lines"] += qm["line_count"]

        if qm["non_empty_lines"] < 50:
            quality_metrics["empty_or_minimal"].append((rel_path, qm["non_empty_lines"]))

        for imp in qm["imports"]:
            quality_metrics["imports_count"][imp] += 1

        functions = extract_functions(content)
        func_sig = "_".join(sorted(functions)[:5])
        if func_sig and len(functions) >= 2:
            function_hashes[func_sig].append(rel_path)

        base_name = pyfile.stem.replace("_old", "").replace("_new", "").replace("_v2", "")
        similar_names[base_name].append(rel_path)

        all_files.append({
            "path": rel_path,
            "name": pyfile.name,
            "category": category,
            "size": pyfile.stat().st_size,
            "lines": qm["line_count"],
            "quality": qm,
        })

    print("=" * 80)
    print("DUPLIKAT-ANALYSE")
    print("=" * 80)
    print("\nDateien mit ähnlichen Funktions-Signaturen:")
    for sig, files in function_hashes.items():
        if len(files) > 1:
            print(f"\n  Signatur: {sig[:60]}...")
            for f in files:
                print(f"    - {f}")

    print("\n\nDateien mit ähnlichen Namen:")
    for base, files in similar_names.items():
        if len(files) > 1:
            print(f"\n  {base}:")
            for f in files:
                print(f"    - {f}")

    total = len(all_files)
    print("\n" + "=" * 80)
    print(f"KATEGORISIERUNG DER {total} TOOLS")
    print("=" * 80)
    for cat, files in sorted(categories.items(), key=lambda x: -len(x[1])):
        if files:
            print(f"\n{cat.upper()} ({len(files)} Dateien):")
            print("-" * 40)
            for f in sorted(files)[:10]:
                print(f"  • {f}")
            if len(files) > 10:
                print(f"  ... und {len(files) - 10} weitere")

    print("\n" + "=" * 80)
    print("QUALITÄTS-METRIKEN")
    print("=" * 80)
    if total > 0:
        print(f"Dateien mit Docstring:      {quality_metrics['has_docstring']:3d} / {total} ({quality_metrics['has_docstring']*100/total:.1f}%)")
        print(f"Dateien mit main-Guard:     {quality_metrics['has_main_guard']:3d} / {total} ({quality_metrics['has_main_guard']*100/total:.1f}%)")
        print(f"Dateien mit ArgParse:       {quality_metrics['has_argparse']:3d} / {total} ({quality_metrics['has_argparse']*100/total:.1f}%)")
        print(f"Dateien mit Error-Handling: {quality_metrics['has_error_handling']:3d} / {total} ({quality_metrics['has_error_handling']*100/total:.1f}%)")
        print(f"\nDurchschnittliche Länge:    {quality_metrics['total_lines']/total:.0f} Zeilen")
        print(f"Minimale/leere Dateien (<50 Zeilen): {len(quality_metrics['empty_or_minimal'])} Dateien")
    else:
        print("Keine Dateien gefunden.")

    if quality_metrics["imports_count"]:
        print("\n\nTop 10 meist-importierte Module:")
        for mod, count in sorted(quality_metrics["imports_count"].items(), key=lambda x: -x[1])[:10]:
            print(f"  {mod:20s}: {count:3d}x")

    print("\n" + "=" * 80)
