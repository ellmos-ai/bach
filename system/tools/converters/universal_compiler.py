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
Tool: c_universal_compiler
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version c_universal_compiler

Description:
    [Beschreibung hinzufügen]

Usage:
    python c_universal_compiler.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

"""
UNIVERSAL COMPILER v2.0
Kompiliert Python-Projekte zu EXE mit PyInstaller.
Liest Konfiguration aus AUFGABEN.txt oder nutzt Auto-Detect.

Erstellt: 03.01.2026
"""

import subprocess
import os
import sys
import json
import re
from pathlib import Path
from datetime import datetime

# Fix für Windows Console Unicode
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SCRIPT_DIR = Path(__file__).parent
BASE_PATH = Path(r"C:\Users\User\OneDrive\.SOFTWARE")
LOG_FILE = SCRIPT_DIR / "_logs" / "compile_log.txt"

# ==================== HELPER ====================

def log(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {msg}\n")

def find_main_py(folder: Path) -> Path:
    """Findet die Haupt-Python-Datei."""
    # Priorität: main.py > *_main.py > größte .py Datei
    candidates = list(folder.glob("*.py"))
    
    # Ignorieren
    ignore = ["setup.py", "test_", "__", "config"]
    candidates = [c for c in candidates if not any(i in c.name.lower() for i in ignore)]
    
    # main.py?
    for c in candidates:
        if c.name.lower() == "main.py":
            return c
    
    # *_main.py oder *main*.py?
    for c in candidates:
        if "main" in c.name.lower():
            return c
    
    # Größte Datei (vermutlich Haupt-App)
    if candidates:
        return max(candidates, key=lambda x: x.stat().st_size)
    
    return None

def find_icon(folder: Path) -> Path:
    """Findet Icon-Datei."""
    for pattern in ["*.ico", "ICO.ico", "icon.ico", "app.ico"]:
        icons = list(folder.glob(pattern))
        if icons:
            return icons[0]
    return None

def parse_aufgaben_for_compile_info(folder: Path) -> dict:
    """Liest Compile-Info aus AUFGABEN.txt falls vorhanden."""
    info = {}
    aufgaben = folder / "AUFGABEN.txt"
    if not aufgaben.exists():
        aufgaben = folder / "Aufgaben.txt"
    
    if aufgaben.exists():
        content = aufgaben.read_text(encoding='utf-8', errors='ignore')
        
        # EXE-Name suchen
        match = re.search(r'EXE[:\s]+([^\s\n]+)', content, re.IGNORECASE)
        if match:
            info['exe_name'] = match.group(1).replace('.exe', '')
        
        # Main-Datei suchen
        match = re.search(r'Main[:\s]+([^\s\n]+\.py)', content, re.IGNORECASE)
        if match:
            info['main'] = match.group(1)
    
    return info

# ==================== COMPILER ====================

class UniversalCompiler:
    def __init__(self):
        self.results = []
    
    def compile_single(self, py_file: Path, output_dir: Path = None, exe_name: str = None,
                       icon: str = None, console: bool = False) -> bool:
        """
        Kompiliert eine einzelne .py Datei direkt zu EXE.
        Kein build/dist Ordner - EXE landet direkt im output_dir.
        
        Args:
            py_file: Pfad zur .py Datei
            output_dir: Zielordner für EXE (default: gleicher Ordner wie .py)
            exe_name: Name der EXE (default: Name der .py ohne Extension)
            icon: Pfad zu .ico Datei (optional)
            console: True = Konsolen-App, False = GUI-App (default)
        """
        import tempfile
        import shutil
        
        py_file = Path(py_file).resolve()
        if not py_file.exists():
            log(f"[FEHLER] Datei nicht gefunden: {py_file}")
            return False
        
        if not py_file.suffix == '.py':
            log(f"[FEHLER] Keine Python-Datei: {py_file}")
            return False
        
        # Defaults
        if not output_dir:
            output_dir = py_file.parent
        output_dir = Path(output_dir).resolve()
        
        if not exe_name:
            exe_name = py_file.stem
        
        log(f"=== Quick-Compile: {py_file.name} ===")
        log(f"  Ziel: {output_dir / (exe_name + '.exe')}")
        
        # Temporärer Build-Ordner
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            cmd = [
                sys.executable, "-m", "PyInstaller",
                "--noconfirm",
                "--onefile",
                f"--name={exe_name}",
                f"--distpath={temp_path}",
                f"--workpath={temp_path / 'build'}",
                f"--specpath={temp_path}",
            ]
            
            if icon:
                icon_path = Path(icon)
                if icon_path.exists():
                    cmd.append(f"--icon={icon_path}")
            
            if console:
                cmd.append("--console")
            else:
                cmd.append("--windowed")
            
            cmd.append(str(py_file))
            
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                
                if result.returncode == 0:
                    temp_exe = temp_path / f"{exe_name}.exe"
                    if temp_exe.exists():
                        # EXE ins Zielverzeichnis kopieren
                        output_dir.mkdir(parents=True, exist_ok=True)
                        final_exe = output_dir / f"{exe_name}.exe"
                        shutil.copy2(temp_exe, final_exe)
                        
                        size_mb = final_exe.stat().st_size / (1024*1024)
                        log(f"  [OK] {final_exe.name} ({size_mb:.1f} MB)")
                        self.results.append({
                            "tool": py_file.name, 
                            "status": "OK", 
                            "exe": str(final_exe),
                            "size_mb": size_mb
                        })
                        return True
                
                log(f"  [FEHLER] PyInstaller fehlgeschlagen")
                if result.stderr:
                    # Nur relevante Fehler zeigen
                    for line in result.stderr.split('\n'):
                        if 'error' in line.lower() or 'Error' in line:
                            log(f"  {line.strip()}")
                self.results.append({"tool": py_file.name, "status": "FEHLER"})
                
            except subprocess.TimeoutExpired:
                log(f"  [FEHLER] Timeout nach 5 Minuten")
                self.results.append({"tool": py_file.name, "status": "TIMEOUT"})
            except Exception as e:
                log(f"  [FEHLER] {e}")
                self.results.append({"tool": py_file.name, "status": "FEHLER", "msg": str(e)})
        
        return False
        
    def compile_tool(self, tool_path: Path, exe_name: str = None, main_file: str = None, 
                     icon: str = None, add_data: list = None, one_file: bool = True):
        """Kompiliert ein einzelnes Tool."""
        log(f"=== Kompiliere: {tool_path.name} ===")
        
        # Auto-detect wenn nicht angegeben
        compile_info = parse_aufgaben_for_compile_info(tool_path)
        
        if not main_file:
            main_file = compile_info.get('main') or find_main_py(tool_path)
            if isinstance(main_file, str):
                main_file = tool_path / main_file
        else:
            main_file = tool_path / main_file
            
        if not main_file or not main_file.exists():
            log(f"  [FEHLER] Keine Python-Datei gefunden!")
            self.results.append({"tool": tool_path.name, "status": "FEHLER", "msg": "Keine .py gefunden"})
            return False
        
        if not exe_name:
            exe_name = compile_info.get('exe_name') or tool_path.name.replace(" ", "_")
        
        if not icon:
            icon = find_icon(tool_path)
        elif isinstance(icon, str):
            icon = tool_path / icon
            if not icon.exists():
                icon = None
        
        # PyInstaller Command bauen
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm",
            "--clean",
            f"--name={exe_name}",
            f"--distpath={tool_path / 'dist'}",
            f"--workpath={tool_path / 'build'}",
            f"--specpath={tool_path}",
        ]
        
        if one_file:
            cmd.append("--onefile")
        
        if icon:
            cmd.append(f"--icon={icon}")
        
        if add_data:
            for data in add_data:
                cmd.append(f"--add-data={data}")
        
        # Windowed (kein Konsolen-Fenster)
        cmd.append("--windowed")
        
        cmd.append(str(main_file))
        
        log(f"  Main: {main_file.name}")
        log(f"  EXE:  {exe_name}.exe")
        log(f"  Icon: {icon.name if icon else 'keins'}")
        
        try:
            result = subprocess.run(cmd, cwd=tool_path, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                exe_path = tool_path / "dist" / f"{exe_name}.exe"
                if exe_path.exists():
                    size_mb = exe_path.stat().st_size / (1024*1024)
                    log(f"  [OK] Erstellt: {exe_path.name} ({size_mb:.1f} MB)")
                    self.results.append({"tool": tool_path.name, "status": "OK", "exe": str(exe_path), "size_mb": size_mb})
                    return True
                else:
                    log(f"  [FEHLER] EXE nicht erstellt")
                    self.results.append({"tool": tool_path.name, "status": "FEHLER", "msg": "EXE nicht erstellt"})
            else:
                log(f"  [FEHLER] PyInstaller fehlgeschlagen")
                log(f"  Stderr: {result.stderr[:500]}")
                self.results.append({"tool": tool_path.name, "status": "FEHLER", "msg": result.stderr[:200]})
                
        except subprocess.TimeoutExpired:
            log(f"  [FEHLER] Timeout nach 5 Minuten")
            self.results.append({"tool": tool_path.name, "status": "TIMEOUT"})
        except Exception as e:
            log(f"  [FEHLER] {e}")
            self.results.append({"tool": tool_path.name, "status": "FEHLER", "msg": str(e)})
        
        return False
    
    def compile_from_todo(self, status_filter: str = "NUR KOMPILIEREN"):
        """Kompiliert alle Tools mit bestimmtem Status aus TODO.md."""
        todo_file = SCRIPT_DIR / "TODO.md"
        if not todo_file.exists():
            log("Keine TODO.md gefunden - erst scanner.py ausführen!")
            return
        
        content = todo_file.read_text(encoding='utf-8')
        
        # Tools mit Status finden
        current_status = None
        tools_to_compile = []
        
        for line in content.split('\n'):
            if line.startswith("### "):
                current_status = line.replace("### ", "").strip()
            elif current_status and status_filter.lower() in current_status.lower():
                # Pfad extrahieren
                match = re.search(r'\*Pfad:\s*([^*]+)\*', line)
                if match:
                    path = Path(match.group(1).strip())
                    if path.exists() and path not in tools_to_compile:
                        tools_to_compile.append(path)
        
        log(f"Gefunden: {len(tools_to_compile)} Tools zum Kompilieren")
        
        for tool_path in tools_to_compile:
            self.compile_tool(tool_path)
        
        self.print_summary()
    
    def print_summary(self):
        """Druckt Zusammenfassung."""
        log("\n=== ZUSAMMENFASSUNG ===")
        ok = [r for r in self.results if r['status'] == 'OK']
        fail = [r for r in self.results if r['status'] != 'OK']
        
        log(f"Erfolgreich: {len(ok)}")
        for r in ok:
            log(f"  [OK] {r['tool']} -> {r.get('size_mb', 0):.1f} MB")
        
        if fail:
            log(f"Fehlgeschlagen: {len(fail)}")
            for r in fail:
                log(f"  [FAIL] {r['tool']}: {r.get('msg', r['status'])}")

# ==================== CLI ====================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Universal Python-zu-EXE Compiler")
    parser.add_argument("path", nargs="?", help="Pfad zur .py Datei oder Tool-Ordner")
    parser.add_argument("--todo", action="store_true", help="Kompiliere aus TODO.md")
    parser.add_argument("--status", default="NUR KOMPILIEREN", help="Status-Filter für TODO")
    parser.add_argument("--exe", help="EXE-Name")
    parser.add_argument("--main", help="Haupt-Python-Datei (nur bei Ordner)")
    parser.add_argument("--icon", help="Icon-Datei")
    parser.add_argument("--output", "-o", help="Ausgabe-Ordner für EXE")
    parser.add_argument("--console", "-c", action="store_true", help="Konsolen-App (zeigt CMD-Fenster)")
    
    args = parser.parse_args()
    
    compiler = UniversalCompiler()
    
    if args.todo:
        compiler.compile_from_todo(args.status)
    elif args.path:
        path = Path(args.path)
        if not path.exists():
            log(f"Pfad nicht gefunden: {args.path}")
            return
        
        # Einzelne .py Datei?
        if path.is_file() and path.suffix == '.py':
            output_dir = Path(args.output) if args.output else None
            compiler.compile_single(
                py_file=path,
                output_dir=output_dir,
                exe_name=args.exe,
                icon=args.icon,
                console=args.console
            )
        # Ordner (Projekt)?
        elif path.is_dir():
            compiler.compile_tool(path, exe_name=args.exe, main_file=args.main, icon=args.icon)
        else:
            log(f"Unbekannter Pfad-Typ: {path}")
        
        compiler.print_summary()
    else:
        print("Universal Compiler - Python zu EXE")
        print()
        print("Einzelne Datei (Quick-Compile):")
        print("  python universal_compiler.py script.py")
        print("  python universal_compiler.py script.py -o C:\\Output")
        print("  python universal_compiler.py script.py --exe MeinTool --console")
        print()
        print("Projekt-Ordner:")
        print("  python universal_compiler.py <ordner>")
        print("  python universal_compiler.py <ordner> --main app.py --exe AppName")
        print()
        print("Aus TODO.md:")
        print("  python universal_compiler.py --todo")
        print("  python universal_compiler.py --todo --status 'VALIDIERT'")

if __name__ == "__main__":
    main()
