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
Tool: c_import_diagnose
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version c_import_diagnose

Description:
    [Beschreibung hinzufügen]

Usage:
    python c_import_diagnose.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

# -*- coding: utf-8 -*-
"""
Import-Diagnose-Tool für Python-Projekte
=========================================
Systematische Analyse von Import-Problemen und Access Violations.

Führt folgende Tests durch:
1. Einzelne Module isoliert importieren
2. Import-Reihenfolge variieren
3. Circular Import Detection
4. __init__.py Analyse
5. Timing-Tests mit Delays
6. Crash-Punkt lokalisieren

Verwendung:
    python c_import_diagnose.py <projekt_src_pfad> [--json] [--modules module1:Class1,module2:Class2]
    
Beispiel:
    python c_import_diagnose.py C:\\MeinProjekt\\src --json
    python c_import_diagnose.py . --modules core.app:App,gui.main:MainWindow
"""

import sys
import os
import time
import subprocess
import json
import argparse
from pathlib import Path
from datetime import datetime

# Fix Windows Console Encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

class ImportDiagnostics:
    """Hauptklasse für Import-Diagnose"""
    
    def __init__(self, project_path: str, modules: list = None, json_output: bool = False):
        self.project_path = Path(project_path).resolve()
        self.json_output = json_output
        self.modules_to_test = modules or self._auto_discover_modules()
        
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "python_version": sys.version,
            "project_path": str(self.project_path),
            "single_imports": [],
            "sequential_imports": [],
            "circular_imports": [],
            "init_files": [],
            "timing_tests": [],
            "crash_point": None,
            "recommendations": []
        }
    
    def _auto_discover_modules(self) -> list:
        """Entdeckt automatisch importierbare Module"""
        modules = []
        
        for py_file in self.project_path.rglob("*.py"):
            if "__pycache__" in str(py_file) or py_file.name.startswith("_"):
                continue
            if py_file.name == "__init__.py":
                continue
                
            relative = py_file.relative_to(self.project_path)
            module_path = str(relative).replace("\\", ".").replace("/", ".").replace(".py", "")
            
            # Versuche Klasse zu finden
            try:
                content = py_file.read_text(encoding='utf-8', errors='ignore')
                for line in content.split('\n'):
                    if line.startswith('class ') and '(' in line:
                        class_name = line.split('class ')[1].split('(')[0].strip()
                        modules.append((module_path, class_name))
                        break
            except OSError:
                pass
        
        return modules[:20]  # Max 20 Module
    
    def log(self, message: str):
        """Ausgabe (respektiert JSON-Modus)"""
        if not self.json_output:
            print(message)
    
    def run_isolated_import(self, module_name: str, class_name: str = None):
        """Führt Import in separatem Prozess aus"""
        if class_name:
            import_stmt = f"from {module_name} import {class_name}"
        else:
            import_stmt = f"import {module_name}"
        
        code = f'''
import sys
sys.path.insert(0, r"{self.project_path}")
try:
    {import_stmt}
    print("SUCCESS")
except Exception as e:
    print(f"ERROR: {{type(e).__name__}}: {{e}}")
'''
        
        try:
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                timeout=10
            )
            output = result.stdout.strip() + result.stderr.strip()
            success = result.returncode == 0 and "SUCCESS" in result.stdout
            return success, result.returncode, output
        except subprocess.TimeoutExpired:
            return False, -1, "TIMEOUT"
        except Exception as e:
            return False, -1, str(e)
    
    def test_single_imports(self):
        """Test 1: Jedes Modul einzeln"""
        self.log("\n" + "="*60)
        self.log("TEST 1: Einzelne Module isoliert importieren")
        self.log("="*60)
        
        for module, class_name in self.modules_to_test:
            success, exit_code, output = self.run_isolated_import(module, class_name)
            status = "✅" if success else "❌"
            
            result = {
                "module": module,
                "class": class_name,
                "success": success,
                "exit_code": exit_code,
                "output": output[:200] if output else ""
            }
            self.results["single_imports"].append(result)
            
            exit_info = f"(Exit: {exit_code})" if exit_code != 0 else ""
            self.log(f"  {status} {module}.{class_name} {exit_info}")
            
            if exit_code == 3221225725:
                self.log(f"      ⚠️ ACCESS VIOLATION (0xC0000005)!")
                self.results["recommendations"].append(
                    f"ACCESS VIOLATION bei {module} - Prüfe ob QObject vor QApplication erstellt wird"
                )
    
    def find_crash_point(self):
        """Test 2: Crash-Punkt lokalisieren"""
        self.log("\n" + "="*60)
        self.log("TEST 2: Crash-Punkt lokalisieren")
        self.log("="*60)
        
        for i in range(1, len(self.modules_to_test) + 1):
            modules_subset = self.modules_to_test[:i]
            
            imports = "\n    ".join([f"from {m} import {c}" for m, c in modules_subset])
            code = f'''
import sys
sys.path.insert(0, r"{self.project_path}")
try:
    {imports}
    print("SUCCESS")
except Exception as e:
    print(f"ERROR: {{type(e).__name__}}: {{e}}")
'''
            
            try:
                result = subprocess.run(
                    [sys.executable, "-c", code],
                    capture_output=True,
                    text=True,
                    encoding='utf-8', errors='replace',
                    timeout=15
                )
                
                if result.returncode != 0:
                    last_module = modules_subset[-1]
                    self.log(f"  ❌ Crash bei Modul #{i}: {last_module[0]}.{last_module[1]}")
                    self.log(f"     Exit Code: {result.returncode}")
                    
                    self.results["crash_point"] = {
                        "index": i,
                        "module": last_module[0],
                        "class": last_module[1],
                        "exit_code": result.returncode
                    }
                    
                    if result.returncode == 3221225725:
                        self.log(f"     ⚠️ ACCESS VIOLATION - DLL/Memory Problem")
                        self.results["recommendations"].append(
                            f"Crash bei {last_module[0]} - Lazy Loading empfohlen"
                        )
                    break
                else:
                    self.log(f"  ✅ Module 1-{i} OK")
                    
            except subprocess.TimeoutExpired:
                self.log(f"  ❌ Timeout bei Modul #{i}")
                break
    
    def analyze_init_files(self):
        """Test 3: __init__.py Dateien analysieren"""
        self.log("\n" + "="*60)
        self.log("TEST 3: __init__.py Dateien analysieren")
        self.log("="*60)
        
        for init_file in self.project_path.rglob("__init__.py"):
            if "__pycache__" in str(init_file):
                continue
                
            relative = init_file.relative_to(self.project_path)
            
            try:
                content = init_file.read_text(encoding='utf-8')
                lines = content.split('\n')
                
                direct_imports = [l for l in lines if l.strip().startswith(('from .', 'import '))]
                has_lazy = '__getattr__' in content
                
                status = "🔄 Lazy" if has_lazy else f"📦 {len(direct_imports)} direkte Imports"
                
                result = {
                    "file": str(relative),
                    "has_lazy_imports": has_lazy,
                    "direct_import_count": len(direct_imports),
                    "size": len(content)
                }
                self.results["init_files"].append(result)
                
                self.log(f"  {relative}: {status}")
                
                if len(direct_imports) > 3 and not has_lazy:
                    self.log(f"    ⚠️ Viele direkte Imports - könnte Problem sein!")
                    self.results["recommendations"].append(
                        f"Lazy Imports für {relative} empfohlen ({len(direct_imports)} direkte Imports)"
                    )
                    
            except Exception as e:
                self.log(f"  {relative}: ❌ Fehler: {e}")
    
    def detect_circular_imports(self):
        """Test 4: Circular Import Detection"""
        self.log("\n" + "="*60)
        self.log("TEST 4: Circular Import Detection")
        self.log("="*60)
        
        imports_map = {}
        
        for py_file in self.project_path.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
                
            relative = str(py_file.relative_to(self.project_path))
            module_name = relative.replace("\\", ".").replace("/", ".").replace(".py", "")
            
            try:
                content = py_file.read_text(encoding='utf-8', errors='ignore')
                imports = []
                
                for line in content.split('\n'):
                    line = line.strip()
                    if line.startswith('from ') and ' import ' in line:
                        parts = line.split(' import ')[0].replace('from ', '').strip()
                        imports.append(parts)
                    elif line.startswith('import ') and not line.startswith('import '):
                        parts = line.replace('import ', '').split(',')
                        for p in parts:
                            imports.append(p.strip().split(' as ')[0])
                
                imports_map[module_name] = imports
            except OSError:
                pass
        
        # Vereinfachte Circular Detection
        circular = []
        for module, imports in imports_map.items():
            for imp in imports:
                if imp.startswith('.'):
                    base = '.'.join(module.split('.')[:-1])
                    imp = imp[1:] if imp.startswith('.') else imp
                    full_imp = f"{base}.{imp}" if base else imp
                else:
                    full_imp = imp
                
                if full_imp in imports_map:
                    their_imports = imports_map.get(full_imp, [])
                    for their_imp in their_imports:
                        if module in their_imp or their_imp.endswith(module.split('.')[-1]):
                            if (module, full_imp) not in circular and (full_imp, module) not in circular:
                                circular.append((module, full_imp))
        
        if circular:
            self.log(f"  ⚠️ Mögliche zirkuläre Abhängigkeiten:")
            for a, b in circular[:10]:
                self.log(f"    {a} ↔ {b}")
                self.results["circular_imports"].append({"module_a": a, "module_b": b})
        else:
            self.log("  ✅ Keine offensichtlichen zirkulären Imports")
    
    def run_all_tests(self):
        """Führt alle Tests aus"""
        self.log("="*60)
        self.log("Python Import-Diagnose-Tool")
        self.log("="*60)
        self.log(f"Projekt: {self.project_path}")
        self.log(f"Python: {sys.version.split()[0]}")
        self.log(f"Module: {len(self.modules_to_test)} gefunden")
        
        if not self.modules_to_test:
            self.log("\n❌ Keine Module zum Testen gefunden!")
            return self.results
        
        self.test_single_imports()
        self.find_crash_point()
        self.analyze_init_files()
        self.detect_circular_imports()
        
        self.log("\n" + "="*60)
        self.log("DIAGNOSE ABGESCHLOSSEN")
        self.log("="*60)
        
        # Zusammenfassung
        success_count = sum(1 for r in self.results["single_imports"] if r["success"])
        total_count = len(self.results["single_imports"])
        self.log(f"\nErgebnis: {success_count}/{total_count} Module OK")
        
        if self.results["recommendations"]:
            self.log("\n💡 Empfehlungen:")
            for rec in self.results["recommendations"]:
                self.log(f"  - {rec}")
        
        return self.results
    
    def save_report(self, output_path: str = None):
        """Speichert Report als JSON und MD"""
        if output_path is None:
            output_path = self.project_path / "DIAGNOSE_REPORT"
        else:
            output_path = Path(output_path)
        
        # JSON
        json_path = str(output_path) + ".json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        self.log(f"\n✅ JSON Report: {json_path}")
        
        # Markdown
        md_path = str(output_path) + ".md"
        md_content = self._generate_markdown()
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        self.log(f"✅ MD Report: {md_path}")
    
    def _generate_markdown(self) -> str:
        """Generiert Markdown-Report"""
        success_count = sum(1 for r in self.results["single_imports"] if r["success"])
        total_count = len(self.results["single_imports"])
        
        md = f"""# 🔬 Python Import-Diagnose Report

**Generiert:** {self.results['timestamp']}  
**Python:** {self.results['python_version'].split()[0]}  
**Projekt:** {self.results['project_path']}

---

## 📊 Zusammenfassung

- **{success_count}/{total_count}** Module erfolgreich importiert
"""
        
        # Fehlgeschlagene
        failed = [r for r in self.results["single_imports"] if not r["success"]]
        if failed:
            md += "\n### ❌ Fehlgeschlagene Imports\n"
            for r in failed:
                md += f"- `{r['module']}.{r['class']}` (Exit: {r['exit_code']})\n"
        
        # Crash-Punkt
        if self.results["crash_point"]:
            cp = self.results["crash_point"]
            md += f"\n### 🔴 Crash-Punkt\n"
            md += f"- Modul #{cp['index']}: `{cp['module']}.{cp['class']}`\n"
            md += f"- Exit Code: {cp['exit_code']}\n"
        
        # Init Files
        md += "\n### 📁 __init__.py Analyse\n"
        for r in self.results["init_files"]:
            lazy = "🔄 Lazy" if r["has_lazy_imports"] else f"📦 {r['direct_import_count']} Imports"
            md += f"- `{r['file']}`: {lazy}\n"
        
        # Circular
        if self.results["circular_imports"]:
            md += "\n### ⚠️ Mögliche Circular Imports\n"
            for r in self.results["circular_imports"]:
                md += f"- `{r['module_a']}` ↔ `{r['module_b']}`\n"
        
        # Empfehlungen
        if self.results["recommendations"]:
            md += "\n---\n\n## 💡 Empfehlungen\n\n"
            for rec in self.results["recommendations"]:
                md += f"- {rec}\n"
        
        md += "\n---\n*Report generiert mit c_import_diagnose.py*\n"
        return md


def main():
    parser = argparse.ArgumentParser(
        description="Python Import-Diagnose-Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  python c_import_diagnose.py C:\\MeinProjekt\\src
  python c_import_diagnose.py . --json
  python c_import_diagnose.py ./src --modules core.app:App,gui.main:MainWindow
        """
    )
    parser.add_argument("project_path", help="Pfad zum Python-Projektverzeichnis")
    parser.add_argument("--json", action="store_true", help="Nur JSON-Ausgabe")
    parser.add_argument("--modules", help="Module zum Testen (format: module:Class,module:Class)")
    parser.add_argument("--save", action="store_true", help="Report-Dateien speichern")
    
    args = parser.parse_args()
    
    # Module parsen
    modules = None
    if args.modules:
        modules = []
        for m in args.modules.split(','):
            if ':' in m:
                mod, cls = m.split(':')
                modules.append((mod.strip(), cls.strip()))
    
    # Diagnose ausführen
    diag = ImportDiagnostics(args.project_path, modules, args.json)
    results = diag.run_all_tests()
    
    if args.save:
        diag.save_report()
    
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    
    # Exit Code basierend auf Ergebnis
    failed = [r for r in results["single_imports"] if not r["success"]]
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
