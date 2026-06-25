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
Tool: c_python_cli_editor
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version c_python_cli_editor

Description:
    [Beschreibung hinzufügen]

Usage:
    python c_python_cli_editor.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

import argparse
import ast
import sys
import os
import re
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, Union
from dataclasses import dataclass, field


# ============ AFTER-EDIT FIXES ============

try:
    from ftfy import fix_text as ftfy_fix
    FTFY_AVAILABLE = True
except ImportError:
    ftfy_fix = None
    FTFY_AVAILABLE = False

try:
    import emoji as emoji_pkg
    EMOJI_AVAILABLE = True
except ImportError:
    emoji_pkg = None
    EMOJI_AVAILABLE = False

EMOJI_ASCII_MAP = {
    '\U0001F7E2': '[GRUEN]', '\U0001F7E1': '[GELB]', '\U0001F534': '[ROT]',
    '\U0001F527': '[TOOL]', '\U0001F4C1': '[FOLDER]', '\U0001F4C4': '[FILE]',
    '\u2705': '[OK]', '\u274C': '[X]', '\u26A0': '[WARN]', '\u2757': '[!]',
    '\U0001F4DD': '[MEMO]', '\U0001F4CB': '[CLIPBOARD]', '\U0001F4BE': '[SAVE]',
    '\U0001F50D': '[SEARCH]', '\U0001F4E6': '[PACKAGE]', '\U0001F680': '[ROCKET]',
    '\U0001F9EA': '[TEST]', '\U0001F41B': '[BUG]', '\u2728': '[SPARKLE]',
    '\U0001F504': '[REFRESH]', '\U0001F6E0': '[WRENCH]', '\u2699': '[GEAR]',
    '\u2192': '->', '\u2190': '<-', '\u2194': '<->', '\u21D2': '=>',
    '\U0001F4CA': '[CHART]', '\U0001F4C8': '[GRAPH]', '\U0001F4C9': '[DOWN]',
}

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F9FF"
    "\U00002702-\U000027B0"
    "\U00002190-\U000021FF"
    "\U00002600-\U000026FF"
    "]+"
)


def fix_encoding(content: str) -> Tuple[str, bool]:
    if not FTFY_AVAILABLE:
        return content, False
    try:
        fixed = ftfy_fix(content)
        return fixed, fixed != content
    except Exception:
        return content, False


def fix_emojis(content: str, use_package: bool = True) -> Tuple[str, int]:
    emoji_count = 0
    result = content
    
    for emoji, replacement in EMOJI_ASCII_MAP.items():
        if emoji in result:
            count = result.count(emoji)
            emoji_count += count
            result = result.replace(emoji, replacement)
    
    if EMOJI_AVAILABLE and use_package:
        remaining = EMOJI_PATTERN.findall(result)
        for emoji_char in remaining:
            if emoji_char in result:
                try:
                    name = emoji_pkg.demojize(emoji_char)
                    if name != emoji_char:
                        name = name.strip(':').upper()[:20]
                        result = result.replace(emoji_char, f"[{name}]")
                        emoji_count += 1
                except (ValueError, TypeError):
                    pass

    return result, emoji_count


def run_after_edit_fixes(filepath: Path, encoding_fix: bool = True, emoji_fix: bool = True) -> Dict[str, Any]:
    result = {"encoding_fixed": False, "emojis_replaced": 0, "errors": []}
    
    try:
        content = filepath.read_text(encoding="utf-8")
        modified = False
        
        if encoding_fix:
            fixed_content, was_changed = fix_encoding(content)
            if was_changed:
                content = fixed_content
                modified = True
                result["encoding_fixed"] = True
                print(f"  [AfterEdit] Encoding korrigiert")
        
        if emoji_fix:
            fixed_content, count = fix_emojis(content)
            if count > 0:
                content = fixed_content
                modified = True
                result["emojis_replaced"] = count
                print(f"  [AfterEdit] {count} Emojis ersetzt")
        
        if modified:
            filepath.write_text(content, encoding="utf-8")
    
    except Exception as e:
        result["errors"].append(str(e))
        print(f"  [AfterEdit] Fehler: {e}")
    
    return result


# ============ DATENSTRUKTUREN ============

@dataclass
class MethodInfo:
    name: str
    lineno: int
    end_lineno: int
    decorators: List[str] = field(default_factory=list)
    args: List[str] = field(default_factory=list)
    docstring: Optional[str] = None
    is_async: bool = False
    
@dataclass
class ClassInfo:
    name: str
    lineno: int
    end_lineno: int
    bases: List[str] = field(default_factory=list)
    methods: List[MethodInfo] = field(default_factory=list)
    decorators: List[str] = field(default_factory=list)
    docstring: Optional[str] = None

@dataclass
class ImportInfo:
    lineno: int
    end_lineno: int
    module: str
    names: List[str] = field(default_factory=list)
    is_from: bool = False
    alias: Optional[str] = None

@dataclass
class GlobalInfo:
    lineno: int
    end_lineno: int
    content: str
    element_type: str


# ============ PARSER ============

class PythonAnalyzer:
    
    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        self.source = ""
        self.lines = []
        self.tree = None
        self.classes: List[ClassInfo] = []
        self.global_functions: List[MethodInfo] = []
        self.imports: List[ImportInfo] = []
        self.globals: List[GlobalInfo] = []
        self.import_end_line = 0  # Letzte Import-Zeile
        
    def parse(self) -> bool:
        try:
            self.source = self.filepath.read_text(encoding="utf-8")
            self.lines = self.source.splitlines()
            self.tree = ast.parse(self.source, filename=str(self.filepath))
            self._extract_structures()
            return True
        except SyntaxError as e:
            print(f"Syntaxfehler in {self.filepath}: {e}")
            return False
        except Exception as e:
            print(f"Fehler beim Parsen von {self.filepath}: {e}")
            return False
    
    def _extract_structures(self):
        for node in ast.iter_child_nodes(self.tree):
            if isinstance(node, ast.ClassDef):
                self.classes.append(self._parse_class(node))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.global_functions.append(self._parse_function(node))
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                imp = self._parse_import(node)
                self.imports.append(imp)
                self.import_end_line = max(self.import_end_line, imp.end_lineno)
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                self.globals.append(self._parse_global(node, "assignment"))
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                if node.lineno == 1 or (node.lineno <= 3 and isinstance(node.value.value, str)):
                    continue
                self.globals.append(self._parse_global(node, "constant"))
    
    def _parse_class(self, node: ast.ClassDef) -> ClassInfo:
        methods = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(self._parse_function(item))
        
        return ClassInfo(
            name=node.name,
            lineno=node.lineno,
            end_lineno=node.end_lineno or node.lineno,
            bases=[self._get_name(b) for b in node.bases],
            methods=methods,
            decorators=[self._get_decorator_name(d) for d in node.decorator_list],
            docstring=ast.get_docstring(node)
        )
    
    def _parse_function(self, node) -> MethodInfo:
        args = [arg.arg for arg in node.args.args]
        return MethodInfo(
            name=node.name,
            lineno=node.lineno,
            end_lineno=node.end_lineno or node.lineno,
            decorators=[self._get_decorator_name(d) for d in node.decorator_list],
            args=args,
            docstring=ast.get_docstring(node),
            is_async=isinstance(node, ast.AsyncFunctionDef)
        )
    
    def _parse_import(self, node) -> ImportInfo:
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
            return ImportInfo(
                lineno=node.lineno,
                end_lineno=node.end_lineno or node.lineno,
                module=names[0] if names else "",
                names=names,
                is_from=False
            )
        else:
            names = [alias.name for alias in node.names]
            return ImportInfo(
                lineno=node.lineno,
                end_lineno=node.end_lineno or node.lineno,
                module=node.module or "",
                names=names,
                is_from=True
            )
    
    def _parse_global(self, node, element_type: str) -> GlobalInfo:
        start = node.lineno - 1
        end = (node.end_lineno or node.lineno)
        content = "\n".join(self.lines[start:end])
        return GlobalInfo(
            lineno=node.lineno,
            end_lineno=node.end_lineno or node.lineno,
            content=content,
            element_type=element_type
        )
    
    def _get_name(self, node) -> str:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_name(node.value)}.{node.attr}"
        elif isinstance(node, ast.Subscript):
            return f"{self._get_name(node.value)}[...]"
        return str(node)
    
    def _get_decorator_name(self, node) -> str:
        if isinstance(node, ast.Name):
            return f"@{node.id}"
        elif isinstance(node, ast.Attribute):
            return f"@{self._get_name(node)}"
        elif isinstance(node, ast.Call):
            return f"@{self._get_name(node.func)}(...)"
        return "@?"
    
    def get_source_lines(self, start: int, end: int) -> str:
        return "\n".join(self.lines[start-1:end])
    
    def find_element(self, name: str) -> Optional[Tuple[str, Any]]:
        """Findet Element nach Name. Returns (typ, element, parent_class)"""
        # Klassen
        for cls in self.classes:
            if cls.name == name:
                return ("class", cls, None)
            # Methoden in Klasse
            for method in cls.methods:
                if method.name == name or f"{cls.name}.{method.name}" == name:
                    return ("method", method, cls)
        
        # Globale Funktionen
        for func in self.global_functions:
            if func.name == name:
                return ("function", func, None)
        
        return None
    
    def get_class_by_name(self, name: str) -> Optional[ClassInfo]:
        for cls in self.classes:
            if cls.name == name:
                return cls
        return None
    
    def get_insert_position(self, position_type: str, target: str = None) -> int:
        """Berechnet Einfuegeposition (0-basierte Zeilennummer)"""
        
        if position_type == "at-start":
            # Nach Imports und Docstring
            return max(self.import_end_line, 1)
        
        elif position_type == "at-end":
            return len(self.lines)
        
        elif position_type == "at-imports":
            return self.import_end_line
        
        elif position_type == "in-class" and target:
            cls = self.get_class_by_name(target)
            if cls:
                # Am Ende der Klasse einfuegen (nach der letzten Methode)
                if cls.methods:
                    last_method = max(cls.methods, key=lambda m: m.end_lineno)
                    return last_method.end_lineno
                else:
                    # Klasse ohne Methoden - nach Docstring/class-Zeile
                    return cls.lineno + 1
            print(f"  Warnung: Klasse '{target}' nicht gefunden")
            return len(self.lines)
        
        elif position_type == "before" and target:
            result = self.find_element(target)
            if result:
                _, elem, _ = result
                return elem.lineno - 1
            print(f"  Warnung: Element '{target}' nicht gefunden")
            return len(self.lines)
        
        elif position_type == "after" and target:
            result = self.find_element(target)
            if result:
                _, elem, _ = result
                return elem.end_lineno
            print(f"  Warnung: Element '{target}' nicht gefunden")
            return len(self.lines)
        
        return len(self.lines)


# ============ AUSGABE-FUNKTIONEN ============

def format_line_number(lineno: int, total_lines: int, show_lines: bool) -> str:
    """Formatiert Zeilennummer-Prefix"""
    if not show_lines:
        return ""
    width = len(str(total_lines))
    return f"{lineno:>{width}} | "


def show_classes(analyzer: PythonAnalyzer, details: bool = False, show_lines: bool = True):
    if not analyzer.classes:
        print("Keine Klassen gefunden.")
        return
    
    total = len(analyzer.lines)
    print(f"\n=== KLASSEN ({len(analyzer.classes)}) ===\n")
    
    for cls in analyzer.classes:
        decorators = " ".join(cls.decorators) + " " if cls.decorators else ""
        bases = f"({', '.join(cls.bases)})" if cls.bases else ""
        line_info = f"[L{cls.lineno}-{cls.end_lineno}]"
        print(f"  {decorators}class {cls.name}{bases}  {line_info}")
        
        if details:
            if cls.docstring:
                doc_preview = cls.docstring.split('\n')[0][:60]
                print(f"      \"\"\"{doc_preview}...\"\"\"")
            print(f"      Methoden: {len(cls.methods)}")
            print()
            print("    " + "-" * 60)
            for lineno in range(cls.lineno, cls.end_lineno + 1):
                prefix = format_line_number(lineno, total, show_lines)
                line_content = analyzer.lines[lineno-1] if lineno <= len(analyzer.lines) else ""
                print(f"    {prefix}{line_content}")
            print("    " + "-" * 60)
            print()


def show_all(analyzer: PythonAnalyzer, details: bool = False, show_lines: bool = True):
    total = len(analyzer.lines)
    print(f"\n=== STRUKTUR: {analyzer.filepath.name} ({total} Zeilen) ===\n")
    
    if analyzer.classes:
        print(f"--- KLASSEN ({len(analyzer.classes)}) ---\n")
        for cls in analyzer.classes:
            decorators = " ".join(cls.decorators) + " " if cls.decorators else ""
            bases = f"({', '.join(cls.bases)})" if cls.bases else ""
            line_info = f"[L{cls.lineno}-{cls.end_lineno}]"
            print(f"  {decorators}class {cls.name}{bases}  {line_info}")
            
            if details and cls.docstring:
                doc_preview = cls.docstring.split('\n')[0][:60]
                print(f"      \"\"\"{doc_preview}...\"\"\"")
            
            for method in cls.methods:
                async_prefix = "async " if method.is_async else ""
                deco = " ".join(method.decorators) + " " if method.decorators else ""
                args_str = ", ".join(method.args[:3])
                if len(method.args) > 3:
                    args_str += ", ..."
                line_info = f"[L{method.lineno}-{method.end_lineno}]"
                print(f"      {deco}{async_prefix}def {method.name}({args_str})  {line_info}")
                
                if details and method.docstring:
                    doc_preview = method.docstring.split('\n')[0][:50]
                    print(f"          \"\"\"{doc_preview}...\"\"\"")
            print()
    
    if analyzer.global_functions:
        print(f"--- GLOBALE FUNKTIONEN ({len(analyzer.global_functions)}) ---\n")
        for func in analyzer.global_functions:
            async_prefix = "async " if func.is_async else ""
            deco = " ".join(func.decorators) + " " if func.decorators else ""
            args_str = ", ".join(func.args[:4])
            if len(func.args) > 4:
                args_str += ", ..."
            line_info = f"[L{func.lineno}-{func.end_lineno}]"
            print(f"  {deco}{async_prefix}def {func.name}({args_str})  {line_info}")
            
            if details and func.docstring:
                doc_preview = func.docstring.split('\n')[0][:60]
                print(f"      \"\"\"{doc_preview}...\"\"\"")
        print()


def show_global(analyzer: PythonAnalyzer, details: bool = False, show_lines: bool = True):
    if not analyzer.global_functions:
        print("Keine globalen Funktionen gefunden.")
        return
    
    total = len(analyzer.lines)
    print(f"\n=== GLOBALE FUNKTIONEN ({len(analyzer.global_functions)}) ===\n")
    
    for func in analyzer.global_functions:
        async_prefix = "async " if func.is_async else ""
        deco = " ".join(func.decorators) + " " if func.decorators else ""
        args_str = ", ".join(func.args)
        line_info = f"[L{func.lineno}-{func.end_lineno}]"
        print(f"  {deco}{async_prefix}def {func.name}({args_str})  {line_info}")
        
        if details:
            if func.docstring:
                print(f"      \"\"\"{func.docstring}\"\"\"")
            print()
            print("    " + "-" * 60)
            for lineno in range(func.lineno, func.end_lineno + 1):
                prefix = format_line_number(lineno, total, show_lines)
                line_content = analyzer.lines[lineno-1] if lineno <= len(analyzer.lines) else ""
                print(f"    {prefix}{line_content}")
            print("    " + "-" * 60)
            print()


def show_imports(analyzer: PythonAnalyzer, show_lines: bool = True):
    if not analyzer.imports:
        print("Keine Imports gefunden.")
        return
    
    total = len(analyzer.lines)
    print(f"\n=== IMPORTS ({len(analyzer.imports)}) ===\n")
    
    STDLIB = {'os', 'sys', 'json', 're', 'ast', 'pathlib', 'datetime', 'typing', 
              'subprocess', 'shutil', 'argparse', 'collections', 'functools',
              'itertools', 'copy', 'time', 'threading', 'multiprocessing', 'io',
              'dataclasses', 'enum', 'abc', 'contextlib', 'logging', 'unittest',
              'hashlib', 'base64', 'uuid', 'random', 'math', 'statistics', 'csv',
              'sqlite3', 'socket', 'http', 'urllib', 'email', 'html', 'xml',
              'tkinter', 'configparser', 'tempfile', 'glob', 'fnmatch', 'pickle'}
    
    standard, third_party, local = [], [], []
    
    for imp in analyzer.imports:
        module_root = imp.module.split('.')[0] if imp.module else ""
        line = analyzer.get_source_lines(imp.lineno, imp.end_lineno)
        line_info = f"[L{imp.lineno}]"
        
        if module_root in STDLIB:
            standard.append((imp.lineno, line, line_info))
        elif module_root.startswith('.') or imp.module.startswith('.'):
            local.append((imp.lineno, line, line_info))
        else:
            third_party.append((imp.lineno, line, line_info))
    
    if standard:
        print("  [Standard Library]")
        for lineno, line, info in sorted(standard):
            prefix = format_line_number(lineno, total, show_lines)
            print(f"    {prefix}{line.strip()}  {info}")
        print()
    
    if third_party:
        print("  [Third-Party]")
        for lineno, line, info in sorted(third_party):
            prefix = format_line_number(lineno, total, show_lines)
            print(f"    {prefix}{line.strip()}  {info}")
        print()
    
    if local:
        print("  [Lokal/Relativ]")
        for lineno, line, info in sorted(local):
            prefix = format_line_number(lineno, total, show_lines)
            print(f"    {prefix}{line.strip()}  {info}")
    
    print(f"\n  Import-Bereich endet bei Zeile {analyzer.import_end_line}")


def show_globals_non_func(analyzer: PythonAnalyzer, show_lines: bool = True):
    if not analyzer.globals:
        print("Keine globalen Zuweisungen/Konstanten gefunden.")
        return
    
    total = len(analyzer.lines)
    print(f"\n=== GLOBALE ZUWEISUNGEN ({len(analyzer.globals)}) ===\n")
    
    for glob in analyzer.globals:
        content_preview = glob.content.split('\n')[0][:70]
        if len(glob.content) > 70 or '\n' in glob.content:
            content_preview += "..."
        line_info = f"[L{glob.lineno}]"
        print(f"  [{glob.element_type}] {content_preview}  {line_info}")


def show_lines_range(analyzer: PythonAnalyzer, start: int, end: int):
    """Zeigt Zeilen im Bereich start-end (1-basiert)"""
    total = len(analyzer.lines)
    start = max(1, start)
    end = min(total, end)
    
    print(f"\n=== ZEILEN {start}-{end} von {total} ===\n")
    
    for lineno in range(start, end + 1):
        prefix = format_line_number(lineno, total, True)
        line_content = analyzer.lines[lineno-1] if lineno <= total else ""
        print(f"  {prefix}{line_content}")


# ============ MODIFIKATIONS-FUNKTIONEN ============

def insert_code(source_path: Path, code: str, position: int, 
                indent: int = 0, save: bool = False, test: bool = False) -> Optional[Path]:
    """
    Fuegt Code an Position ein.
    position: 0-basierte Zeilennummer
    indent: Einrueckung in Spaces
    Returns: Pfad zur (Test-)Datei oder None bei Fehler
    """
    content = source_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    
    # Code vorbereiten
    if indent > 0:
        code_lines = code.splitlines()
        code_lines = [" " * indent + line if line.strip() else line for line in code_lines]
        code = "\n".join(code_lines)
    
    # Einfuegen
    new_lines = lines[:position] + code.splitlines() + lines[position:]
    new_content = "\n".join(new_lines)
    
    # Syntax-Check
    try:
        ast.parse(new_content)
    except SyntaxError as e:
        print(f"  [FEHLER] Syntax-Fehler nach Einfuegen: {e}")
        return None
    
    # Speichern
    if test:
        test_path = source_path.with_suffix(".test.py")
        test_path.write_text(new_content, encoding="utf-8")
        print(f"  [TEST] Testdatei erstellt: {test_path}")
        return test_path
    
    if save:
        # Backup erstellen
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = source_path.with_suffix(f".backup_{timestamp}.py")
        shutil.copy2(source_path, backup_path)
        print(f"  [BACKUP] {backup_path}")
        
        source_path.write_text(new_content, encoding="utf-8")
        print(f"  [SAVED] {source_path}")
        return source_path
    
    # Nur Preview
    print(f"  [PREVIEW] Wuerde {len(code.splitlines())} Zeilen bei Position {position+1} einfuegen")
    print(f"  Nutze --save oder --test zum Anwenden")
    return None


def delete_element(source_path: Path, element_name: str, 
                   save: bool = False, test: bool = False) -> Optional[Path]:
    """
    Loescht ein Element (Klasse, Funktion, Methode).
    Returns: Pfad zur (Test-)Datei oder None bei Fehler
    """
    analyzer = PythonAnalyzer(str(source_path))
    if not analyzer.parse():
        return None
    
    result = analyzer.find_element(element_name)
    if not result:
        print(f"  [FEHLER] Element '{element_name}' nicht gefunden")
        return None
    
    elem_type, elem, parent = result
    
    content = source_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    
    start_line = elem.lineno - 1
    end_line = elem.end_lineno
    
    # Bei Methoden: Einrueckung beachten
    if elem_type == "method" and parent:
        print(f"  [DELETE] Methode {parent.name}.{elem.name} (Zeilen {elem.lineno}-{elem.end_lineno})")
    else:
        print(f"  [DELETE] {elem_type.title()} {elem.name} (Zeilen {elem.lineno}-{elem.end_lineno})")
    
    # Zeilen loeschen
    new_lines = lines[:start_line] + lines[end_line:]
    
    # Leere Zeilen bereinigen (max 2 aufeinanderfolgende)
    cleaned_lines = []
    empty_count = 0
    for line in new_lines:
        if not line.strip():
            empty_count += 1
            if empty_count <= 2:
                cleaned_lines.append(line)
        else:
            empty_count = 0
            cleaned_lines.append(line)
    
    new_content = "\n".join(cleaned_lines)
    
    # Syntax-Check
    try:
        ast.parse(new_content)
    except SyntaxError as e:
        print(f"  [FEHLER] Syntax-Fehler nach Loeschen: {e}")
        return None
    
    if test:
        test_path = source_path.with_suffix(".test.py")
        test_path.write_text(new_content, encoding="utf-8")
        print(f"  [TEST] Testdatei erstellt: {test_path}")
        return test_path
    
    if save:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = source_path.with_suffix(f".backup_{timestamp}.py")
        shutil.copy2(source_path, backup_path)
        print(f"  [BACKUP] {backup_path}")
        
        source_path.write_text(new_content, encoding="utf-8")
        print(f"  [SAVED] {source_path}")
        return source_path
    
    print(f"  [PREVIEW] Wuerde Zeilen {elem.lineno}-{elem.end_lineno} loeschen")
    print(f"  Nutze --save oder --test zum Anwenden")
    return None


def change_line(source_path: Path, line_number: int, new_content: str,
                save: bool = False, test: bool = False) -> Optional[Path]:
    """
    Aendert eine einzelne Zeile.
    line_number: 1-basiert
    """
    content = source_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    
    if line_number < 1 or line_number > len(lines):
        print(f"  [FEHLER] Zeile {line_number} existiert nicht (1-{len(lines)})")
        return None
    
    old_line = lines[line_number - 1]
    lines[line_number - 1] = new_content
    
    print(f"  [CHANGE] Zeile {line_number}:")
    print(f"    ALT: {old_line}")
    print(f"    NEU: {new_content}")
    
    new_file_content = "\n".join(lines)
    
    # Syntax-Check
    try:
        ast.parse(new_file_content)
    except SyntaxError as e:
        print(f"  [FEHLER] Syntax-Fehler: {e}")
        return None
    
    if test:
        test_path = source_path.with_suffix(".test.py")
        test_path.write_text(new_file_content, encoding="utf-8")
        print(f"  [TEST] Testdatei erstellt: {test_path}")
        return test_path
    
    if save:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = source_path.with_suffix(f".backup_{timestamp}.py")
        shutil.copy2(source_path, backup_path)
        print(f"  [BACKUP] {backup_path}")
        
        source_path.write_text(new_file_content, encoding="utf-8")
        print(f"  [SAVED] {source_path}")
        return source_path
    
    print(f"  [PREVIEW] Nutze --save oder --test zum Anwenden")
    return None


# ============ EDIT-FUNKTIONEN (bestehend) ============

def create_edit_file(analyzer: PythonAnalyzer, elements: List[str], output_path: Path) -> bool:
    content_parts = []
    content_parts.append(f"# EDIT FILE - Generiert aus {analyzer.filepath.name}")
    content_parts.append(f"# Datum: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    content_parts.append(f"# Elemente: {', '.join(elements)}")
    content_parts.append("#")
    content_parts.append("# Bearbeite den Code zwischen den Markern.")
    content_parts.append("# Speichere mit --merge um zu mergen.")
    content_parts.append("#" + "=" * 60)
    content_parts.append("")
    
    for elem_name in elements:
        result = analyzer.find_element(elem_name)
        if not result:
            for cls in analyzer.classes:
                if cls.name == elem_name:
                    result = ("class", cls, None)
                    break
        
        if not result:
            print(f"  Warnung: Element '{elem_name}' nicht gefunden")
            continue
        
        elem_type, elem, parent = result
        
        if elem_type == "class":
            source = analyzer.get_source_lines(elem.lineno, elem.end_lineno)
            content_parts.append(f"# === CLASS: {elem.name} [Zeile {elem.lineno}-{elem.end_lineno}] ===")
            content_parts.append(source)
            content_parts.append("")
            
        elif elem_type == "function":
            source = analyzer.get_source_lines(elem.lineno, elem.end_lineno)
            content_parts.append(f"# === FUNCTION: {elem.name} [Zeile {elem.lineno}-{elem.end_lineno}] ===")
            content_parts.append(source)
            content_parts.append("")
            
        elif elem_type == "method":
            source = analyzer.get_source_lines(elem.lineno, elem.end_lineno)
            content_parts.append(f"# === METHOD: {parent.name}.{elem.name} [Zeile {elem.lineno}-{elem.end_lineno}] ===")
            content_parts.append(source)
            content_parts.append("")
    
    try:
        output_path.write_text("\n".join(content_parts), encoding="utf-8")
        print(f"  Edit-Datei erstellt: {output_path}")
        return True
    except Exception as e:
        print(f"  Fehler beim Erstellen: {e}")
        return False


def merge_edit_file(source_path: Path, edit_path: Path, 
                    save: bool = False, test: bool = False,
                    encoding_fix: bool = True, emoji_fix: bool = True) -> Optional[Path]:
    """Merged Edit-Datei zurueck in Original."""
    if not edit_path.exists():
        print(f"  Edit-Datei nicht gefunden: {edit_path}")
        return None
    
    edit_content = edit_path.read_text(encoding="utf-8")
    source_content = source_path.read_text(encoding="utf-8")
    source_lines = source_content.splitlines()
    
    pattern = r'# === (CLASS|FUNCTION|METHOD): ([^\[]+) \[Zeile (\d+)-(\d+)\] ==='
    
    replacements = []
    current_elem = None
    current_lines = []
    
    for line in edit_content.splitlines():
        match = re.match(pattern, line)
        if match:
            if current_elem:
                replacements.append((current_elem, current_lines))
            
            elem_type = match.group(1)
            elem_name = match.group(2).strip()
            start_line = int(match.group(3))
            end_line = int(match.group(4))
            current_elem = (elem_type, elem_name, start_line, end_line)
            current_lines = []
        elif current_elem and not line.startswith('#'):
            current_lines.append(line)
    
    if current_elem:
        replacements.append((current_elem, current_lines))
    
    replacements.sort(key=lambda x: x[0][2], reverse=True)
    
    for (elem_type, elem_name, start_line, end_line), new_lines in replacements:
        while new_lines and not new_lines[-1].strip():
            new_lines.pop()
        source_lines[start_line-1:end_line] = new_lines
        print(f"  Ersetzt: {elem_type} {elem_name} (Zeilen {start_line}-{end_line})")
    
    new_content = "\n".join(source_lines)
    
    # Syntax-Check
    try:
        ast.parse(new_content)
    except SyntaxError as e:
        print(f"  [FEHLER] Syntax-Fehler nach Merge: {e}")
        return None
    
    if test:
        test_path = source_path.with_suffix(".test.py")
        test_path.write_text(new_content, encoding="utf-8")
        print(f"  [TEST] Testdatei erstellt: {test_path}")
        return test_path
    
    if save:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = source_path.with_suffix(f".backup_{timestamp}.py")
        shutil.copy2(source_path, backup_path)
        print(f"  [BACKUP] {backup_path}")
        
        source_path.write_text(new_content, encoding="utf-8")
        print(f"  [SAVED] {source_path}")
        
        if encoding_fix or emoji_fix:
            run_after_edit_fixes(source_path, encoding_fix=encoding_fix, emoji_fix=emoji_fix)
        
        # Edit-Datei loeschen
        edit_path.unlink()
        print(f"  Edit-Datei geloescht: {edit_path}")
        
        return source_path
    
    print(f"  [PREVIEW] Nutze --save oder --test zum Anwenden")
    return None


# ============ EXPORT ============

def export_to_txt(analyzer: PythonAnalyzer, elements: List[str], output_path: Path, 
                  details: bool = False, show_lines: bool = True) -> bool:
    lines = []
    lines.append(f"Python Code Export: {analyzer.filepath.name}")
    lines.append(f"Generiert: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"Gesamt: {len(analyzer.lines)} Zeilen")
    lines.append("=" * 70)
    lines.append("")
    
    if not elements:
        elements = [cls.name for cls in analyzer.classes]
        elements += [func.name for func in analyzer.global_functions]
    
    total = len(analyzer.lines)
    
    for elem_name in elements:
        result = analyzer.find_element(elem_name)
        if not result:
            for cls in analyzer.classes:
                if cls.name == elem_name:
                    result = ("class", cls, None)
                    break
        
        if not result:
            lines.append(f"[!] Element nicht gefunden: {elem_name}")
            continue
        
        elem_type, elem, parent = result
        
        if elem_type == "class":
            lines.append(f"CLASS: {elem.name} [L{elem.lineno}-{elem.end_lineno}]")
            lines.append(f"  Bases: {', '.join(elem.bases) if elem.bases else '-'}")
            lines.append(f"  Methoden: {len(elem.methods)}")
            for m in elem.methods:
                lines.append(f"    - {m.name}({', '.join(m.args)}) [L{m.lineno}]")
            
            if details:
                lines.append("")
                lines.append("  Code:")
                lines.append("  " + "-" * 50)
                for lineno in range(elem.lineno, elem.end_lineno + 1):
                    prefix = format_line_number(lineno, total, show_lines)
                    code_line = analyzer.lines[lineno-1] if lineno <= total else ""
                    lines.append(f"  {prefix}{code_line}")
                lines.append("  " + "-" * 50)
            lines.append("")
            
        elif elem_type == "function":
            lines.append(f"FUNCTION: {elem.name}({', '.join(elem.args)}) [L{elem.lineno}-{elem.end_lineno}]")
            if elem.docstring:
                lines.append(f"  Docstring: {elem.docstring.split(chr(10))[0][:60]}...")
            
            if details:
                lines.append("")
                lines.append("  Code:")
                lines.append("  " + "-" * 50)
                for lineno in range(elem.lineno, elem.end_lineno + 1):
                    prefix = format_line_number(lineno, total, show_lines)
                    code_line = analyzer.lines[lineno-1] if lineno <= total else ""
                    lines.append(f"  {prefix}{code_line}")
                lines.append("  " + "-" * 50)
            lines.append("")
    
    try:
        output_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  Export erstellt: {output_path}")
        return True
    except Exception as e:
        print(f"  Export-Fehler: {e}")
        return False


# ============ HILFSFUNKTIONEN ============

def load_code_from_source(source: str) -> str:
    """Laedt Code aus Datei oder String."""
    source_path = Path(source)
    if source_path.exists() and source_path.suffix == ".py":
        return source_path.read_text(encoding="utf-8")
    return source


def cleanup_files(source_path: Path, pattern: str = "*.test*.py"):
    """Bereinigt temporaere Dateien."""
    for f in source_path.parent.glob(pattern):
        if source_path.stem in f.stem:
            f.unlink()
            print(f"  Geloescht: {f}")


# ============ MAIN ============

def main():
    parser = argparse.ArgumentParser(
        description="Python CLI Editor v2.0 - Analysiert und bearbeitet Python-Dateien",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  # Struktur anzeigen
  python python_cli_editor.py script.py --show-all --lines
  python python_cli_editor.py script.py --show-imports
  
  # Code hinzufuegen
  python python_cli_editor.py script.py --add new_func.py --at-end --save
  python python_cli_editor.py script.py --add "import os" --at-imports --save
  python python_cli_editor.py script.py --add method.py --in-class MyClass --save
  
  # Element loeschen
  python python_cli_editor.py script.py --delete old_function --save
  
  # Zeile aendern
  python python_cli_editor.py script.py --change-line 42 --content "x = 100" --save
  
  # Edit-Workflow
  python python_cli_editor.py script.py --edit MyClass process_data
  python python_cli_editor.py script.py --merge --save
        """
    )
    
    parser.add_argument("tool", help="Python-Datei zum Analysieren/Bearbeiten")
    
    # Anzeige-Modi
    show_group = parser.add_argument_group("Anzeige-Modi")
    show_group.add_argument("--show-classes", action="store_true", 
                           help="Zeigt alle Klassen")
    show_group.add_argument("--show-all", action="store_true",
                           help="Zeigt Klassen mit Methoden und globale Funktionen")
    show_group.add_argument("--show-global", action="store_true",
                           help="Zeigt alle globalen Funktionen")
    show_group.add_argument("--show-imports", action="store_true",
                           help="Zeigt alle Imports (gruppiert)")
    show_group.add_argument("--show-globals", action="store_true",
                           help="Zeigt globale Zuweisungen")
    show_group.add_argument("--show-lines", type=str, metavar="RANGE",
                           help="Zeigt Zeilenbereich (z.B. '1-50' oder '100-150')")
    
    # Zeilennummern
    line_group = parser.add_mutually_exclusive_group()
    line_group.add_argument("--lines", action="store_true", default=True,
                           help="Zeilennummern anzeigen (Default)")
    line_group.add_argument("--no-lines", action="store_true",
                           help="Zeilennummern ausblenden")
    
    # Details
    parser.add_argument("--details", nargs="*", metavar="NAME",
                       help="Zeigt Details/Code. Ohne Namen: fuer alle")
    
    # Einfuegen
    add_group = parser.add_argument_group("Einfuegen")
    add_group.add_argument("--add", metavar="CODE_OR_FILE",
                          help="Code einfuegen (Datei.py oder direkter Code)")
    add_group.add_argument("--at-start", action="store_true",
                          help="Am Dateianfang (nach Imports)")
    add_group.add_argument("--at-end", action="store_true",
                          help="Am Dateiende")
    add_group.add_argument("--at-imports", action="store_true",
                          help="Im Import-Bereich")
    add_group.add_argument("--at-line", type=int, metavar="N",
                          help="An Zeile N einfuegen")
    add_group.add_argument("--in-class", metavar="CLASS",
                          help="In Klasse einfuegen (am Ende)")
    add_group.add_argument("--before", metavar="NAME",
                          help="Vor Element NAME einfuegen")
    add_group.add_argument("--after", metavar="NAME",
                          help="Nach Element NAME einfuegen")
    
    # Loeschen
    del_group = parser.add_argument_group("Loeschen")
    del_group.add_argument("--delete", metavar="NAME",
                          help="Element loeschen (Klasse/Funktion/Methode)")
    
    # Zeile aendern
    change_group = parser.add_argument_group("Zeile aendern")
    change_group.add_argument("--change-line", type=int, metavar="N",
                             help="Zeile N aendern")
    change_group.add_argument("--content", metavar="CODE",
                             help="Neuer Inhalt fuer --change-line")
    
    # Edit-Workflow
    edit_group = parser.add_argument_group("Edit-Workflow")
    edit_group.add_argument("--edit", nargs="+", metavar="NAME",
                           help="Erstellt Edit-Datei fuer Elemente")
    edit_group.add_argument("--merge", action="store_true",
                           help="Merged Edit-Datei zurueck")
    
    # Speichern
    save_group = parser.add_argument_group("Speichern")
    save_group.add_argument("--test", action="store_true",
                           help="Erstellt Testdatei ohne Original zu aendern")
    save_group.add_argument("--save", action="store_true",
                           help="Speichert direkt mit Backup")
    save_group.add_argument("--no-backup", action="store_true",
                           help="Kein Backup erstellen")
    
    # After-Edit
    fix_group = parser.add_argument_group("After-Edit Fixes")
    fix_group.add_argument("--encodingfix", choices=["on", "off"], default="on",
                          help="Encoding-Fix nach Save. Default: on")
    fix_group.add_argument("--emojifix", choices=["on", "off"], default="on",
                          help="Emoji-Fix nach Save. Default: on")
    
    # Export
    parser.add_argument("--txt", metavar="FILE",
                       help="Exportiert als .txt Datei")
    
    # Cleanup
    parser.add_argument("--cleanup", action="store_true",
                       help="Loescht temporaere Test-Dateien")
    
    args = parser.parse_args()
    
    # Tool-Pfad validieren
    tool_path = Path(args.tool)
    if not tool_path.exists():
        print(f"Fehler: Datei nicht gefunden: {tool_path}")
        sys.exit(1)
    
    # Cleanup
    if args.cleanup:
        cleanup_files(tool_path)
        sys.exit(0)
    
    # Analyzer erstellen
    analyzer = PythonAnalyzer(str(tool_path))
    if not analyzer.parse():
        sys.exit(1)
    
    show_lines = not args.no_lines
    show_details = args.details is not None
    
    print(f"\n[*] {tool_path.name}: {len(analyzer.classes)} Klassen, "
          f"{len(analyzer.global_functions)} Funktionen, {len(analyzer.lines)} Zeilen")
    
    # === ANZEIGE-MODI ===
    
    if args.show_lines:
        try:
            if '-' in args.show_lines:
                start, end = map(int, args.show_lines.split('-'))
            else:
                start = int(args.show_lines)
                end = start + 20
            show_lines_range(analyzer, start, end)
        except ValueError:
            print(f"  [FEHLER] Ungueltiger Bereich: {args.show_lines}")
    
    if args.show_classes:
        show_classes(analyzer, show_details, show_lines)
    
    if args.show_all:
        show_all(analyzer, show_details, show_lines)
    
    if args.show_global:
        show_global(analyzer, show_details, show_lines)
    
    if args.show_imports:
        show_imports(analyzer, show_lines)
    
    if args.show_globals:
        show_globals_non_func(analyzer, show_lines)
    
    # === EINFUEGEN ===
    
    if args.add:
        code = load_code_from_source(args.add)
        
        # Position bestimmen
        position = len(analyzer.lines)  # Default: Ende
        indent = 0
        
        if args.at_start:
            position = analyzer.get_insert_position("at-start")
        elif args.at_end:
            position = analyzer.get_insert_position("at-end")
        elif args.at_imports:
            position = analyzer.get_insert_position("at-imports")
        elif args.at_line:
            position = args.at_line - 1
        elif args.in_class:
            position = analyzer.get_insert_position("in-class", args.in_class)
            # Einrueckung nur wenn Code nicht bereits eingerueckt ist
            if not code.startswith("    "):
                indent = 4
        elif args.before:
            position = analyzer.get_insert_position("before", args.before)
        elif args.after:
            position = analyzer.get_insert_position("after", args.after)
        
        print(f"\n[ADD] Fuege {len(code.splitlines())} Zeilen bei Position {position+1} ein")
        insert_code(tool_path, code, position, indent=indent, 
                   save=args.save, test=args.test)
    
    # === LOESCHEN ===
    
    if args.delete:
        print(f"\n[DELETE] Loesche Element: {args.delete}")
        delete_element(tool_path, args.delete, save=args.save, test=args.test)
    
    # === ZEILE AENDERN ===
    
    if args.change_line:
        if not args.content:
            # Zeige aktuelle Zeile
            if 1 <= args.change_line <= len(analyzer.lines):
                current = analyzer.lines[args.change_line - 1]
                print(f"\n[CHANGE] Zeile {args.change_line}: {current}")
                print("  Nutze --content 'neuer inhalt' zum Aendern")
            else:
                print(f"  [FEHLER] Zeile {args.change_line} existiert nicht")
        else:
            print(f"\n[CHANGE] Aendere Zeile {args.change_line}")
            change_line(tool_path, args.change_line, args.content,
                       save=args.save, test=args.test)
    
    # === EDIT-WORKFLOW ===
    
    if args.edit:
        edit_path = tool_path.with_suffix(".edit.py")
        create_edit_file(analyzer, args.edit, edit_path)
    
    if args.merge:
        edit_path = tool_path.with_suffix(".edit.py")
        encoding_fix = args.encodingfix == "on"
        emoji_fix = args.emojifix == "on"
        merge_edit_file(tool_path, edit_path, 
                       save=args.save, test=args.test,
                       encoding_fix=encoding_fix, emoji_fix=emoji_fix)
    
    # === EXPORT ===
    
    if args.txt:
        output_path = Path(args.txt)
        elements = args.details if args.details else []
        export_to_txt(analyzer, elements, output_path, show_details, show_lines)
    
    # === FALLBACK ===
    
    if not any([args.show_classes, args.show_all, args.show_global, 
                args.show_imports, args.show_globals, args.show_lines,
                args.add, args.delete, args.change_line,
                args.edit, args.merge, args.txt, args.cleanup]):
        print("\nKeine Aktion angegeben. Nutze --help fuer Optionen.")
        print("\nSchnell-Uebersicht:")
        show_all(analyzer, details=False, show_lines=show_lines)


if __name__ == "__main__":
    main()
