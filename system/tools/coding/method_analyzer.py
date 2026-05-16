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
Tool: c_method_analyzer
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version c_method_analyzer

Description:
    [Beschreibung hinzufügen]

Usage:
    python c_method_analyzer.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

import ast
import re
import os
import sys
import pathlib
import pkgutil
import builtins
import collections
import difflib
import datetime
import json
from typing import Set, Dict, List, Tuple, Any, Optional
from dataclasses import dataclass, field
from functools import lru_cache

# ============================================================================
# WINDOWS ENCODING FIX
# ============================================================================

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

# ============================================================================
# KONSTANTEN
# ============================================================================

SIMILARITY_THRESHOLD = 0.8
BUILTINS = set(dir(builtins))

CALLBACK_SUFFIXES = (
    "_callback", "_fetch", "_stage", "_emit", "_process", "_task", "_async", "_handler"
)

COMMON_FRAMEWORK_METHODS = {
    "__enter__", "__exit__", "__eq__", "__hash__", "__init__",
    "__str__", "__repr__", "__len__", "__getitem__", "__setitem__",
    "on_start", "on_stop", "on_close", "on_refresh", "mainloop"
}

COMMON_WIDGETS = {
    "Button", "Label", "Frame", "Canvas", "Entry", "Text", "Scrollbar", "Treeview",
    "Menu", "MenuItem", "Checkbutton", "Radiobutton", "Scale", "Spinbox",
    "BooleanVar", "StringVar", "IntVar", "DoubleVar", "Listbox", "Combobox"
}

FRAMEWORK_MAP = {
    "LabelFrame": "tkinter", "Progressbar": "tkinter", "after": "tkinter",
    "after_idle": "tkinter", "grid": "tkinter", "pack": "tkinter",
    "rowconfigure": "tkinter", "columnconfigure": "tkinter",
    "update_idletasks": "tkinter", "update_menu": "tkinter", "winfo_children": "tkinter",
    "askopenfilename": "tkinter", "asksaveasfilename": "tkinter", "askyesno": "tkinter",
    "showerror": "tkinter", "showinfo": "tkinter", "showwarning": "tkinter",
    "tag_configure": "tkinter", "tag_add": "tkinter", "tag_remove": "tkinter",
    "ClientSession": "aiohttp", "ClientTimeout": "aiohttp",
    "Session": "requests", "HTTPAdapter": "requests", "raise_for_status": "requests",
    "Workbook": "openpyxl", "cell": "openpyxl", "load_workbook": "openpyxl",
    "Image": "PIL", "ImageDraw": "PIL", "Icon": "PIL", "Draw": "PIL",
    "drawString": "reportlab", "showPage": "reportlab", "setFont": "reportlab",
}

STDLIB_EXPORTS = {
    "threading": {"Thread", "Lock", "RLock", "Event", "Semaphore", "Timer", "Barrier"},
    "subprocess": {"Popen", "PIPE", "STDOUT", "DEVNULL", "run", "call", "check_call"},
    "io": {"BytesIO", "StringIO", "BufferedReader", "TextIOWrapper"},
    "asyncio": {"get_event_loop", "run", "create_task", "gather", "wait", "sleep", "Queue"},
    "collections": {"Counter", "OrderedDict", "defaultdict", "deque", "namedtuple"},
    "traceback": {"format_exc", "format_exception", "print_exc", "extract_tb"},
    "tkinter": {"Tk", "Frame", "Label", "Button", "Entry", "Text", "Canvas", "Scrollbar"},
}

# PyQt/PySide inherited methods (not errors when used on self)
QT_INHERITED_METHODS = {
    # QWidget
    "setWindowTitle", "setMinimumSize", "setMaximumSize", "setFixedSize",
    "setMinimumWidth", "setMinimumHeight", "setMaximumWidth", "setMaximumHeight",
    "setGeometry", "resize", "move", "show", "hide", "close", "raise_", "lower",
    "setEnabled", "setDisabled", "setVisible", "setHidden", "setFocus",
    "setToolTip", "setStatusTip", "setWhatsThis", "setStyleSheet",
    "setLayout", "setCursor", "setFont", "setPalette", "setWindowIcon",
    "setSizePolicy", "setContentsMargins", "setWindowFlags",
    "width", "height", "size", "pos", "geometry", "rect",
    "update", "repaint", "adjustSize", "updateGeometry",
    # QMainWindow
    "menuBar", "statusBar", "addToolBar", "setCentralWidget", "setStatusBar",
    "addDockWidget", "removeDockWidget", "setMenuBar",
    # QDialog
    "accept", "reject", "done", "exec", "exec_", "open",
    "setModal", "setResult",
    # QLayout
    "addWidget", "addLayout", "addItem", "addStretch", "addSpacing",
    "setSpacing", "setContentsMargins", "setAlignment",
    # QToolBar
    "addAction", "addSeparator", "addWidget", "setMovable", "setIconSize",
    "setToolButtonStyle", "setFloatable",
    # QMenu/QMenuBar
    "addMenu", "addAction", "addSeparator", "setTitle",
    # QSplitter
    "addWidget", "setSizes", "setOrientation", "setHandleWidth",
    # QTabWidget
    "addTab", "insertTab", "removeTab", "setCurrentIndex", "setTabText",
    # Common widgets
    "setText", "text", "setPlaceholderText", "setReadOnly", "setEnabled",
    "setChecked", "isChecked", "setCheckable", "setValue", "value",
    "setCurrentText", "currentText", "setCurrentIndex", "currentIndex",
    "clear", "addItem", "addItems", "count", "item", "itemAt",
    # QListWidget/QTreeWidget
    "currentItem", "selectedItems", "setSelectionMode",
    # Signals
    "connect", "disconnect", "emit",
    # Common actions
    "setShortcut", "setIcon", "setPopupMode", "triggered",
    # Status
    "showMessage",
}

DYNAMIC_PATTERNS = {
    "getattr": re.compile(r"\bgetattr\s*\("),
    "setattr": re.compile(r"\bsetattr\s*\("),
    "exec": re.compile(r"\bexec\s*\("),
    "eval": re.compile(r"\beval\s*\("),
    "bind": re.compile(r"\.bind\s*\(\s*['\"]<[^>]+>['\"],?\s*(?:lambda[^:]*:\s*)?self\.(\w+)"),
    "command": re.compile(r"command\s*=\s*(?:lambda[^:]*:\s*)?self\.(\w+)"),
    "ThreadTarget": re.compile(r"Thread\s*\([^)]*target\s*=\s*self\.(\w+)"),
}

# PyQt/PySide Signal Patterns
SIGNAL_PATTERNS = {
    "connect": re.compile(r"\.connect\s*\(\s*(?:lambda[^:]*:\s*)?self\.(\w+)"),
    "disconnect": re.compile(r"\.disconnect\s*\(\s*self\.(\w+)"),
}

CASE_TRANSITION_PATTERN = re.compile(r'[a-z][A-Z]|[A-Z][a-z]')


# ============================================================================
# DATENKLASSEN
# ============================================================================

@dataclass
class AnalysisResult:
    """Struktur für Analyse-Ergebnisse."""
    calls: List[str]
    defs: List[str]
    imported_definitions: List[str]
    module_provided_attrs: List[str]
    missing_defs: List[str]
    unused_defs: List[str]
    imports: List[str]
    used_imports: List[str]
    unused_imports: List[str]
    duplicate_imports: List[str]
    missing_imports: List[str]
    dynamic_usage: List[str] = field(default_factory=list)
    dynamic_methods: List[str] = field(default_factory=list)
    framework_hooks: List[Tuple[str, str]] = field(default_factory=list)
    import_scopes: Dict[str, List[str]] = field(default_factory=dict)
    name_matches: List[Tuple[str, str]] = field(default_factory=list)
    typehints: List[str] = field(default_factory=list)
    # Neu in v2.0
    signal_callbacks: List[Tuple[str, int, bool]] = field(default_factory=list)  # (name, line, exists)
    attribute_issues: List[Tuple[str, int, int]] = field(default_factory=list)  # (attr, used_line, def_line or -1)
    underscore_mismatches: List[Tuple[str, str]] = field(default_factory=list)  # (called, should_be)

# ============================================================================
# AST VISITOR KLASSEN
# ============================================================================

class ImportScopeAnalyzer(ast.NodeVisitor):
    """Analysiert Imports nach Scope."""
    def __init__(self):
        self.top_level: Set[str] = set()
        self.class_level: Dict[str, Set[str]] = collections.defaultdict(set)
        self.method_level: Dict[str, Set[str]] = collections.defaultdict(set)
        self.scope_stack: List[Tuple[str, str]] = []

    def visit_Import(self, node): 
        names = {alias.name.split(".")[0] for alias in node.names}
        self._assign_imports(names)
        self.generic_visit(node)
    
    def visit_ImportFrom(self, node):
        if node.module:
            self._assign_imports({node.module.split(".")[0]})
        self.generic_visit(node)
    
    def visit_ClassDef(self, node):
        self.scope_stack.append(("class", node.name))
        self.generic_visit(node)
        self.scope_stack.pop()
    
    def visit_FunctionDef(self, node):
        self.scope_stack.append(("func", node.name))
        self.generic_visit(node)
        self.scope_stack.pop()
    
    visit_AsyncFunctionDef = visit_FunctionDef
    
    def _assign_imports(self, names):
        if not self.scope_stack:
            self.top_level |= names
        else:
            scope_type, scope_name = self.scope_stack[-1]
            if scope_type == "class":
                self.class_level[scope_name] |= names
            else:
                self.method_level[scope_name] |= names


class CodeAnalyzer(ast.NodeVisitor):
    """Analysiert Aufrufe, Definitionen und Imports."""
    def __init__(self):
        self.calls: Set[str] = set()
        self.defs: Set[str] = set()
        self.imports: List[str] = []
        self.import_names: Set[str] = set()
        self.imported_definitions: Set[str] = set()
        self.used_names: Set[str] = set()
        self.module_attribute_calls: Dict[str, Set[str]] = collections.defaultdict(set)
        self.imported_modules: Set[str] = set()

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute):
            self.calls.add(node.func.attr)
            if isinstance(node.func.value, ast.Name):
                self.module_attribute_calls[node.func.value.id].add(node.func.attr)
        elif isinstance(node.func, ast.Name):
            self.calls.add(node.func.id)
        self.generic_visit(node)
    
    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name):
            self.module_attribute_calls[node.value.id].add(node.attr)
        self.generic_visit(node)
    
    def visit_FunctionDef(self, node):
        self.defs.add(node.name)
        self.generic_visit(node)
    
    visit_AsyncFunctionDef = visit_FunctionDef
    
    def visit_ClassDef(self, node):
        self.defs.add(node.name)
        self.generic_visit(node)
    
    def visit_Import(self, node):
        for alias in node.names:
            module_base = alias.name.split(".")[0]
            self.imports.append(module_base)
            import_name = alias.asname if alias.asname else module_base
            self.import_names.add(import_name)
            self.imported_definitions.add(import_name)
            if not alias.asname:
                self.imported_modules.add(module_base)
    
    def visit_ImportFrom(self, node):
        if node.module:
            self.imports.append(node.module.split(".")[0])
        for alias in node.names:
            if alias.name != '*':
                import_name = alias.asname if alias.asname else alias.name
                self.import_names.add(import_name)
                self.imported_definitions.add(import_name)
    
    def visit_Name(self, node):
        self.used_names.add(node.id)
        self.generic_visit(node)


class SelfAttributeAnalyzer(ast.NodeVisitor):
    """
    Analysiert self.X Nutzung in Klassen.
    Erkennt: Attribut verwendet bevor definiert.
    """
    def __init__(self):
        self.current_class = None
        self.current_method = None
        self.class_methods: Dict[str, Set[str]] = collections.defaultdict(set)
        # {class_name: {attr_name: {'defined': [lines], 'used': [lines]}}}
        self.class_attrs: Dict[str, Dict[str, Dict[str, List[int]]]] = collections.defaultdict(
            lambda: collections.defaultdict(lambda: {'defined': [], 'used': []})
        )
    
    def visit_ClassDef(self, node):
        old_class = self.current_class
        self.current_class = node.name
        
        # Sammle Methodennamen
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.class_methods[node.name].add(item.name)
        
        self.generic_visit(node)
        self.current_class = old_class
    
    def visit_FunctionDef(self, node):
        if self.current_class:
            old_method = self.current_method
            self.current_method = node.name
            self.generic_visit(node)
            self.current_method = old_method
        else:
            self.generic_visit(node)
    
    visit_AsyncFunctionDef = visit_FunctionDef
    
    def visit_Assign(self, node):
        if self.current_class:
            for target in node.targets:
                if isinstance(target, ast.Attribute):
                    if isinstance(target.value, ast.Name) and target.value.id == 'self':
                        attr_name = target.attr
                        self.class_attrs[self.current_class][attr_name]['defined'].append(node.lineno)
        self.generic_visit(node)
    
    def visit_Attribute(self, node):
        if self.current_class:
            if isinstance(node.value, ast.Name) and node.value.id == 'self':
                attr_name = node.attr
                # Nur als "verwendet" zählen wenn nicht Ziel einer Zuweisung
                if not isinstance(node.ctx, ast.Store):
                    self.class_attrs[self.current_class][attr_name]['used'].append(node.lineno)
        self.generic_visit(node)
    
    def get_issues(self) -> List[Tuple[str, int, int]]:
        """
        Gibt Liste von (attr_name, first_use_line, first_def_line) zurück.
        first_def_line ist -1 wenn nie definiert.
        """
        issues = []
        for class_name, attrs in self.class_attrs.items():
            methods = self.class_methods.get(class_name, set())
            for attr_name, data in attrs.items():
                # Skip wenn es eine Methode ist
                if attr_name in methods:
                    continue
                
                # Skip Qt-geerbte Methoden
                if attr_name in QT_INHERITED_METHODS:
                    continue
                
                used_lines = sorted(data['used'])
                defined_lines = sorted(data['defined'])
                
                if not used_lines:
                    continue
                
                first_use = used_lines[0]
                
                if not defined_lines:
                    # Nie definiert
                    issues.append((attr_name, first_use, -1))
                else:
                    first_def = defined_lines[0]
                    if first_use < first_def:
                        # Verwendet vor Definition
                        issues.append((attr_name, first_use, first_def))
        
        return sorted(issues, key=lambda x: x[1])


# ============================================================================
# HILFSFUNKTIONEN
# ============================================================================

def has_case_transition(name: str) -> bool:
    return bool(CASE_TRANSITION_PATTERN.search(name))

def scan_dynamic_usage(code: str) -> Tuple[List[str], Set[str]]:
    dynamic_hits, dynamic_methods = [], set()
    for name, pattern in DYNAMIC_PATTERNS.items():
        matches = pattern.findall(code)
        if matches:
            dynamic_hits.append(name)
            for m in matches:
                if isinstance(m, str) and m:
                    dynamic_methods.add(m)
    return dynamic_hits, dynamic_methods


def scan_signal_callbacks(code: str, lines: List[str], method_defs: Set[str]) -> List[Tuple[str, int, bool]]:
    """
    Scannt nach .connect(self.X) und prüft ob X existiert.
    Returns: [(method_name, line_number, exists_in_defs)]
    """
    results = []
    
    for pattern_name, pattern in SIGNAL_PATTERNS.items():
        for i, line in enumerate(lines, 1):
            matches = pattern.findall(line)
            for method_name in matches:
                # Prüfe in eigenen Definitionen
                exists = method_name in method_defs
                
                # Prüfe auch mit/ohne Underscore
                if not exists:
                    alt_name = method_name.lstrip('_') if method_name.startswith('_') else f'_{method_name}'
                    exists = alt_name in method_defs
                
                # Prüfe Qt-geerbte Methoden (close, reject, accept, etc.)
                if not exists:
                    exists = method_name in QT_INHERITED_METHODS
                
                results.append((method_name, i, exists))
    
    return results


def find_underscore_mismatches(calls: Set[str], defs: Set[str]) -> List[Tuple[str, str]]:
    """
    Findet Fälle wo _method aufgerufen aber method definiert ist (oder umgekehrt).
    """
    mismatches = []
    
    for call in calls:
        if call in defs:
            continue
        
        # Prüfe ob Version mit/ohne Underscore existiert
        if call.startswith('_'):
            alt = call[1:]  # ohne underscore
            if alt in defs:
                mismatches.append((call, alt))
        else:
            alt = f'_{call}'  # mit underscore
            if alt in defs:
                mismatches.append((call, alt))
    
    return mismatches


@lru_cache(maxsize=1)
def build_stdlib_whitelist() -> Set[str]:
    wl = set(dir(builtins))
    if hasattr(sys, "stdlib_module_names"):
        wl |= sys.stdlib_module_names
    else:
        wl |= {m.name for m in pkgutil.iter_modules()}
    for t in [str, list, dict, set, tuple, int, float, bool]:
        wl |= set(dir(t))
    wl |= set(dir(datetime))
    wl |= set(dir(pathlib.Path))
    return wl

def is_valid_missing_def(name: str) -> bool:
    if name.startswith("_") or name.endswith(CALLBACK_SUFFIXES) or name in FRAMEWORK_MAP:
        return False
    if len(name) >= 3:
        return has_case_transition(name) or ('_' in name and not name.startswith('_'))
    return False


def filter_missing_defs(missing_defs, false_positives, typehints, whitelist):
    return sorted([n for n in missing_defs if n not in false_positives 
                   and n not in typehints and n not in whitelist and is_valid_missing_def(n)])

def get_available_module_attributes(analyzer):
    available = set()
    for module, attrs in analyzer.module_attribute_calls.items():
        if module in analyzer.imported_modules or module in analyzer.import_names:
            if module in STDLIB_EXPORTS:
                available.update(a for a in attrs if a in STDLIB_EXPORTS[module])
            else:
                available.update(attrs)
    return available

# ============================================================================
# HAUPTANALYSE
# ============================================================================

def analyze_file(path: str) -> AnalysisResult:
    """Führt komplette Analyse einer Python-Datei durch."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Datei nicht gefunden: {path}")
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()
    except UnicodeDecodeError:
        with open(path, "r", encoding="latin-1") as f:
            code = f.read()
    
    lines = code.split('\n')
    
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise RuntimeError(f"Syntax-Fehler in Zeile {e.lineno}: {e.msg}")

    analyzer = CodeAnalyzer()
    analyzer.visit(tree)
    scope_analyzer = ImportScopeAnalyzer()
    scope_analyzer.visit(tree)
    
    # NEU: Self-Attribut-Analyse
    attr_analyzer = SelfAttributeAnalyzer()
    attr_analyzer.visit(tree)
    attribute_issues = attr_analyzer.get_issues()
    
    dynamic_hits, dynamic_methods = scan_dynamic_usage(code)
    typehints = _extract_typehints(tree)
    
    calls = analyzer.calls | dynamic_methods
    defs = analyzer.defs | analyzer.imported_definitions
    imports_unique = set(analyzer.imports)
    module_provided = get_available_module_attributes(analyzer)
    
    framework_widgets = COMMON_FRAMEWORK_METHODS | COMMON_WIDGETS | set(FRAMEWORK_MAP.keys())
    missing_defs = (calls - defs) - BUILTINS - framework_widgets - module_provided
    unused_defs = analyzer.defs - calls
    unused_imports = analyzer.import_names - analyzer.used_names
    
    whitelist = build_stdlib_whitelist()
    false_positives = {n for n in calls if (n.startswith("__") and n.endswith("__")) 
                       or n.isupper() or len(n) <= 2 or n in whitelist 
                       or n in framework_widgets or n.startswith("_") 
                       or n.endswith(CALLBACK_SUFFIXES)}
    
    name_matches = [(c, difflib.get_close_matches(c, defs, n=1, cutoff=SIMILARITY_THRESHOLD)[0])
                    for c in calls if c not in defs 
                    and difflib.get_close_matches(c, defs, n=1, cutoff=SIMILARITY_THRESHOLD)]
    
    # NEU: Signal-Callback-Analyse
    signal_callbacks = scan_signal_callbacks(code, lines, analyzer.defs)
    
    # NEU: Underscore-Mismatches
    underscore_mismatches = find_underscore_mismatches(calls, analyzer.defs)
    
    return AnalysisResult(
        calls=sorted(calls), defs=sorted(analyzer.defs),
        imported_definitions=sorted(analyzer.imported_definitions),
        module_provided_attrs=sorted(module_provided),
        missing_defs=filter_missing_defs(missing_defs, false_positives, typehints, whitelist),
        unused_defs=sorted(unused_defs), imports=sorted(imports_unique),
        used_imports=sorted(analyzer.import_names & analyzer.used_names),
        unused_imports=sorted(unused_imports),
        duplicate_imports=[i for i, c in collections.Counter(analyzer.imports).items() if c > 1],
        missing_imports=sorted((analyzer.used_names - defs - imports_unique - calls - BUILTINS - framework_widgets)),
        dynamic_usage=dynamic_hits, dynamic_methods=sorted(dynamic_methods),
        framework_hooks=[(n, "magic" if n.startswith("__") else "handler") for n in sorted(defs) 
                         if n.startswith("__") or n.startswith("on_")],
        name_matches=name_matches, typehints=sorted(typehints),
        # NEU
        signal_callbacks=signal_callbacks,
        attribute_issues=attribute_issues,
        underscore_mismatches=underscore_mismatches
    )


def _extract_typehints(tree) -> Set[str]:
    hints = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.annotation, ast.Name):
            hints.add(node.annotation.id)
        elif isinstance(node, ast.arg) and node.annotation and isinstance(node.annotation, ast.Name):
            hints.add(node.annotation.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns and isinstance(node.returns, ast.Name):
                hints.add(node.returns.id)
    return hints

# ============================================================================
# AUSGABEFORMATE
# ============================================================================

def generate_report(result: AnalysisResult) -> str:
    """Generiert formatierten Text-Report."""
    lines = ["=" * 70, "PYTHON CODE ANALYSE - ERGEBNISSE (v2.0)", "=" * 70, ""]
    
    # Kritische Fehler zuerst
    has_critical = False
    
    # Signal-Callbacks ohne Definition
    missing_signals = [(name, line) for name, line, exists in result.signal_callbacks if not exists]
    if missing_signals:
        has_critical = True
        lines.extend(["[KRITISCH] FEHLENDE SIGNAL-CALLBACKS", "-" * 70])
        for name, line in missing_signals:
            lines.append(f"  Zeile {line}: .connect(self.{name}) - Methode nicht gefunden!")
        lines.append("")
    
    # Attribut vor Init
    if result.attribute_issues:
        has_critical = True
        lines.extend(["[KRITISCH] ATTRIBUT VOR DEFINITION VERWENDET", "-" * 70])
        for attr, used_line, def_line in result.attribute_issues:
            if def_line == -1:
                lines.append(f"  self.{attr} (Zeile {used_line}): Nie definiert!")
            else:
                lines.append(f"  self.{attr} (Zeile {used_line}): Erst in Zeile {def_line} definiert")
        lines.append("")
    
    # Underscore-Mismatches
    if result.underscore_mismatches:
        has_critical = True
        lines.extend(["[KRITISCH] UNDERSCORE-INKONSISTENZ", "-" * 70])
        for called, should_be in result.underscore_mismatches:
            lines.append(f"  '{called}' aufgerufen, aber '{should_be}' definiert")
        lines.append("")
    
    if has_critical:
        lines.extend(["=" * 70, ""])
    
    # Standard-Analyse
    lines.extend([
        "HAUPTERGEBNISSE", "-" * 70,
        f"Fehlende Definitionen ({len(result.missing_defs)}): {', '.join(result.missing_defs) or '(keine)'}",
        f"Ungenutzte Definitionen ({len(result.unused_defs)}): {', '.join(result.unused_defs) or '(keine)'}",
        f"Ungenutzte Imports ({len(result.unused_imports)}): {', '.join(result.unused_imports) or '(keine)'}"])
    
    if result.duplicate_imports:
        lines.extend(["", "DOPPELTE IMPORTS", f"  {', '.join(result.duplicate_imports)}"])
    if result.dynamic_usage:
        lines.extend(["", "DYNAMISCHE AUFRUFE", f"  Patterns: {', '.join(result.dynamic_usage)}"])
    if result.name_matches:
        lines.extend(["", "AEHNLICHE NAMEN (moegliche Tippfehler)"])
        lines.extend([f"  '{c}' -> vielleicht '{m}'?" for c, m in result.name_matches])
    
    # Signal-Stats
    if result.signal_callbacks:
        ok_count = sum(1 for _, _, exists in result.signal_callbacks if exists)
        total = len(result.signal_callbacks)
        lines.extend(["", "SIGNAL-VERBINDUNGEN", f"  {ok_count}/{total} Callbacks gefunden"])
    
    lines.extend(["", "STATISTIK", "-" * 70,
                  f"  Aufrufe: {len(result.calls)}", f"  Definitionen: {len(result.defs)}",
                  f"  Imports: {len(result.imports)}", "=" * 70])
    return "\n".join(lines)


def get_summary(result: AnalysisResult) -> Dict[str, Any]:
    """Gibt kompakte Zusammenfassung als Dictionary zurück (für programmatische Nutzung)."""
    missing_signals = [(name, line) for name, line, exists in result.signal_callbacks if not exists]
    
    return {
        "issues": {
            "missing_definitions": result.missing_defs,
            "unused_definitions": result.unused_defs,
            "unused_imports": result.unused_imports,
            "duplicate_imports": result.duplicate_imports,
            "possible_typos": [{"called": c, "similar_to": m} for c, m in result.name_matches],
            # NEU
            "missing_signal_callbacks": [{"method": n, "line": l} for n, l in missing_signals],
            "attribute_before_init": [{"attr": a, "used_line": u, "def_line": d} 
                                       for a, u, d in result.attribute_issues],
            "underscore_mismatches": [{"called": c, "should_be": s} 
                                       for c, s in result.underscore_mismatches]
        },
        "stats": {
            "total_calls": len(result.calls),
            "total_definitions": len(result.defs),
            "total_imports": len(result.imports),
            "signal_callbacks_checked": len(result.signal_callbacks),
            "dynamic_patterns_found": result.dynamic_usage
        },
        "has_issues": bool(result.missing_defs or result.unused_defs or 
                          result.unused_imports or result.duplicate_imports or
                          missing_signals or result.attribute_issues or
                          result.underscore_mismatches),
        "has_critical": bool(missing_signals or result.attribute_issues or result.underscore_mismatches)
    }

# ============================================================================
# CLI INTERFACE
# ============================================================================

def cli_main():
    """Command-line Interface für direkten Aufruf."""
    if len(sys.argv) < 2:
        print("Usage: python c_method_analyzer.py <python_file> [--json]")
        print("")
        print("Options:")
        print("  --json    Output as JSON instead of text report")
        print("")
        print("Checks (v2.0):")
        print("  - Missing/unused definitions and imports")
        print("  - Duplicate imports")
        print("  - Possible typos (similar names)")
        print("  - Signal callbacks (.connect(self.X) existence)")
        print("  - Attribute used before definition (self.X)")
        print("  - Underscore mismatches (_method vs method)")
        sys.exit(1)
    
    path = sys.argv[1]
    use_json = "--json" in sys.argv
    
    try:
        result = analyze_file(path)
        if use_json:
            print(json.dumps(get_summary(result), indent=2, ensure_ascii=False))
        else:
            print(generate_report(result))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    cli_main()
