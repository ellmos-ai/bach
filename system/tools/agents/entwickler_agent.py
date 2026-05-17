#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Entwickler-Agent v1.0.0
RecludOS Software-Entwicklungs-Agent
Vollständige Implementation (Phase 1-6)

Phase 1: ✅ Projekt- & Task-Management
Phase 2: ✅ Code-Analyse & Generation
Phase 3: ✅ Service-Integration (Editor/Compiler)
Phase 4: ✅ Intelligenz (Debugging, Patterns)
Phase 5: ✅ Kollaboration (Feedback-Loop)
Phase 6: ✅ Testing & Polish
"""

import json
import logging
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
import hashlib
import difflib

from portable_base import PortableAgent, BACH_ROOT, BACH_AVAILABLE

# Coding-Module aus system/tools/coding/ importieren
_CODING_DIR = Path(__file__).parents[1] / "coding"
try:
    if str(_CODING_DIR) not in sys.path:
        sys.path.insert(0, str(_CODING_DIR))
    from code_analyzer import CodeAnalyzer, AnalysisResult
    from code_generator import CodeGenerator
    _CODING_AVAILABLE = True
except ImportError:
    _CODING_AVAILABLE = False
    CodeAnalyzer = None  # type: ignore
    AnalysisResult = None  # type: ignore
    CodeGenerator = None  # type: ignore


@dataclass
class DebugResult:
    """Ergebnis einer Debug-Session"""
    file_path: str
    errors_found: int
    errors_fixed: int
    suggestions: List[str]
    changes_made: List[Dict]
    timestamp: str


class EntwicklerAgent(PortableAgent):
    """Autonomer Software-Entwicklungs-Agent v1.0.0"""

    AGENT_NAME = "EntwicklerAgent"
    VERSION = "1.0.0"

    # Design Patterns Bibliothek (Phase 4)
    PATTERNS = {
        "singleton": {
            "name": "Singleton",
            "description": "Stellt sicher, dass nur eine Instanz existiert",
            "use_case": "Globale Konfiguration, Logger, DB-Connection"
        },
        "factory": {
            "name": "Factory",
            "description": "Erstellt Objekte ohne konkrete Klasse zu spezifizieren",
            "use_case": "Plugin-Systeme, dynamische Objekterstellung"
        },
        "observer": {
            "name": "Observer",
            "description": "Benachrichtigt abhängige Objekte bei Änderungen",
            "use_case": "Event-Systeme, UI-Updates"
        },
        "strategy": {
            "name": "Strategy",
            "description": "Kapselt Algorithmen und macht sie austauschbar",
            "use_case": "Verschiedene Sortier/Such-Algorithmen"
        },
        "decorator": {
            "name": "Decorator",
            "description": "Fügt Funktionalität dynamisch hinzu",
            "use_case": "Logging, Caching, Validierung"
        }
    }
    
    def __init__(self, config_path: str = None):
        super().__init__(config_path)
        self.base_dir = Path(__file__).parent
        self.project_registry = self._load_project_registry()
        self.task_queue = self._load_task_queue()

        # Phase 2: Code-Module (optional)
        self.analyzer = CodeAnalyzer() if _CODING_AVAILABLE else None
        self.generator = CodeGenerator() if _CODING_AVAILABLE else None

        # Phase 3: Service-Pfade
        self.services_dir = BACH_ROOT / "system" / "tools" / "services" if BACH_AVAILABLE else self.base_dir

        # Phase 5: Feedback-System
        self.feedback_log = []

        self.logger.info(f"Entwickler-Agent v{self.VERSION} initialisiert")
    
    # ========== CONFIG & REGISTRY (Phase 1) ==========

    def _load_project_registry(self) -> Dict:
        path = self.base_dir / "projects" / "project_registry.json"
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"meta": {"total_projects": 0}, "projects": {}}
    
    def _load_task_queue(self) -> Dict:
        path = self.base_dir / "tasks" / "task_queue.json"
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"meta": {"total_tasks": 0}, "queue": []}
    
    def _save_project_registry(self):
        path = self.base_dir / "projects" / "project_registry.json"
        path.parent.mkdir(exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.project_registry, f, indent=2, ensure_ascii=False)
    
    def _save_task_queue(self):
        path = self.base_dir / "tasks" / "task_queue.json"
        path.parent.mkdir(exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.task_queue, f, indent=2, ensure_ascii=False)
    
    def _generate_id(self, prefix: str = "") -> str:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"{prefix}{timestamp}" if prefix else timestamp
    
    # ========== PROJEKT-MANAGEMENT (Phase 1) ==========
    
    def create_project(self, name: str, template: str = "python_cli",
                      description: str = "") -> str:
        """Erstellt neues Projekt"""
        project_id = self._generate_id("proj_")
        project_dir = self.base_dir / "projects" / name
        project_dir.mkdir(parents=True, exist_ok=True)
        
        project_data = {
            "id": project_id,
            "name": name,
            "template": template,
            "description": description,
            "created": datetime.now().isoformat(),
            "status": "active",
            "path": str(project_dir),
            "files": [],
            "tasks": [],
            "analysis_cache": {}
        }
        
        self.project_registry['projects'][project_id] = project_data
        self.project_registry['meta']['total_projects'] += 1
        self._save_project_registry()
        
        self.logger.info(f"Projekt erstellt: {name} ({project_id})")
        return project_id
    
    def list_projects(self, status: str = None) -> List[Dict]:
        projects = list(self.project_registry['projects'].values())
        if status:
            projects = [p for p in projects if p['status'] == status]
        return projects
    
    # ========== TASK-MANAGEMENT (Phase 1) ==========
    
    def add_task(self, title: str, description: str = "",
                task_type: str = "feature", priority: str = "normal",
                project_id: str = None) -> str:
        """Fügt Task zur Queue hinzu"""
        task_id = self._generate_id("task_")
        
        task_data = {
            "id": task_id,
            "project_id": project_id,
            "title": title,
            "description": description,
            "type": task_type,
            "priority": priority,
            "status": "pending",
            "created": datetime.now().isoformat()
        }
        
        self.task_queue['queue'].append(task_data)
        self.task_queue['meta']['total_tasks'] += 1
        self._save_task_queue()
        
        self.logger.info(f"Task hinzugefuegt: {title} ({task_id})")
        return task_id
    
    def get_next_task(self) -> Optional[Dict]:
        """Holt nächsten Task (höchste Priorität)"""
        pending = [t for t in self.task_queue['queue'] if t['status'] == 'pending']
        if not pending:
            return None
        priority_order = {'critical': 0, 'high': 1, 'normal': 2, 'low': 3}
        pending.sort(key=lambda t: priority_order.get(t['priority'], 2))
        return pending[0]
    
    def complete_task(self, task_id: str, artifacts: List[str] = None) -> bool:
        """Markiert Task als abgeschlossen"""
        for task in self.task_queue['queue']:
            if task['id'] == task_id:
                task['status'] = 'completed'
                task['completed'] = datetime.now().isoformat()
                if artifacts:
                    task['artifacts'] = artifacts
                self._save_task_queue()
                self.logger.info(f"Task abgeschlossen: {task_id}")
                return True
        return False
    
    # ========== CODE-ANALYSE (Phase 2) ==========
    
    def analyze_file(self, file_path: str) -> AnalysisResult:
        """Analysiert eine Code-Datei"""
        if not self.analyzer:
            raise RuntimeError("Coding-Module nicht verfuegbar (code_analyzer.py nicht gefunden)")
        result = self.analyzer.analyze_file(file_path)
        self.logger.info(f"Analyse abgeschlossen: {file_path}")
        return result
    
    def analyze_project(self, project_id: str) -> Dict:
        """Analysiert alle Dateien eines Projekts"""
        project = self.project_registry['projects'].get(project_id)
        if not project:
            raise ValueError(f"Projekt nicht gefunden: {project_id}")
        
        project_path = Path(project['path'])
        results = {}
        
        for py_file in project_path.rglob("*.py"):
            if "__pycache__" not in str(py_file):
                try:
                    result = self.analyze_file(str(py_file))
                    results[str(py_file)] = self.analyzer.to_dict(result)
                except Exception as e:
                    self.logger.error(f"Fehler bei {py_file}: {e}")
        
        # Cache aktualisieren
        project['analysis_cache'] = {
            "timestamp": datetime.now().isoformat(),
            "files_analyzed": len(results),
            "results": results
        }
        self._save_project_registry()
        
        return results
    
    # ========== CODE-GENERATION (Phase 2) ==========
    
    def generate_code(self, spec: Dict) -> str:
        """Generiert Code aus Spezifikation"""
        if not self.generator:
            raise RuntimeError("Coding-Module nicht verfuegbar (code_generator.py nicht gefunden)")
        return self.generator.generate_from_spec(spec)
    
    def create_file(self, project_id: str, filename: str, spec: Dict) -> str:
        """Erstellt eine neue Datei im Projekt"""
        project = self.project_registry['projects'].get(project_id)
        if not project:
            raise ValueError(f"Projekt nicht gefunden: {project_id}")
        
        file_path = Path(project['path']) / filename
        code = self.generate_code(spec)
        
        file_path.write_text(code, encoding='utf-8')
        project['files'].append(str(file_path))
        self._save_project_registry()
        
        self.logger.info(f"Datei erstellt: {file_path}")
        return str(file_path)
    
    # ========== SERVICE-INTEGRATION (Phase 3) ==========
    
    def call_editor(self, file_path: str = None) -> bool:
        """Öffnet Datei im Code-Editor"""
        editor_path = self.services_dir / "code-editor" / "editor.py"
        
        if not editor_path.exists():
            self.logger.error("Editor-Service nicht gefunden")
            return False
        
        try:
            cmd = [sys.executable, str(editor_path)]
            if file_path:
                cmd.append(file_path)
            subprocess.Popen(cmd)
            self.logger.info(f"Editor gestartet: {file_path or 'Neu'}")
            return True
        except Exception as e:
            self.logger.error(f"Editor-Fehler: {e}")
            return False
    
    def call_compiler(self, file_path: str, output_dir: str = None) -> Dict:
        """Kompiliert Python-Datei"""
        compiler_path = self.services_dir / "compiler" / "compiler.py"
        
        result = {
            "success": False,
            "file": file_path,
            "output": None,
            "errors": []
        }
        
        # Syntax-Check via py_compile
        try:
            import py_compile
            py_compile.compile(file_path, doraise=True)
            result['success'] = True
            result['output'] = "Syntax OK"
            self.logger.info(f"Kompilierung erfolgreich: {file_path}")
        except py_compile.PyCompileError as e:
            result['errors'].append(str(e))
            self.logger.error(f"Kompilierungsfehler: {e}")
        
        return result
    
    def run_script(self, file_path: str, args: List[str] = None) -> Dict:
        """Führt Python-Script aus"""
        result = {
            "success": False,
            "stdout": "",
            "stderr": "",
            "return_code": -1
        }
        
        try:
            cmd = [sys.executable, file_path] + (args or [])
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                timeout=30
            )
            result['stdout'] = process.stdout
            result['stderr'] = process.stderr
            result['return_code'] = process.returncode
            result['success'] = process.returncode == 0
        except subprocess.TimeoutExpired:
            result['stderr'] = "Timeout nach 30 Sekunden"
        except Exception as e:
            result['stderr'] = str(e)
        
        return result
    
    # ========== INTELLIGENZ (Phase 4) ==========
    
    def debug_file(self, file_path: str, auto_fix: bool = False) -> DebugResult:
        """Debuggt eine Datei und schlägt Fixes vor"""
        path = Path(file_path)
        content = path.read_text(encoding='utf-8')
        lines = content.split('\n')
        
        errors_found = 0
        errors_fixed = 0
        suggestions = []
        changes = []
        
        # 1. Syntax-Analyse
        analysis = self.analyze_file(file_path)
        
        # 2. Issues aus Analyse
        for issue in analysis.issues:
            errors_found += 1
            if issue['type'] == 'debug_print' and auto_fix:
                # Print-Statements entfernen
                line_idx = issue['line'] - 1
                old_line = lines[line_idx]
                lines[line_idx] = f"# REMOVED: {old_line}"
                changes.append({
                    "line": issue['line'],
                    "action": "commented_out",
                    "original": old_line
                })
                errors_fixed += 1
            else:
                suggestions.append(f"L{issue['line']}: {issue['message']}")
        
        # 3. Pattern-Analyse
        pattern_suggestions = self._suggest_patterns(content)
        suggestions.extend(pattern_suggestions)
        
        # 4. Änderungen speichern
        if auto_fix and changes:
            path.write_text('\n'.join(lines), encoding='utf-8')
        
        return DebugResult(
            file_path=file_path,
            errors_found=errors_found,
            errors_fixed=errors_fixed,
            suggestions=suggestions,
            changes_made=changes,
            timestamp=datetime.now().isoformat()
        )
    
    def _suggest_patterns(self, code: str) -> List[str]:
        """Schlägt Design Patterns vor"""
        suggestions = []
        
        # Singleton-Check: Viele globale Variablen
        global_vars = code.count('\nglobal ')
        if global_vars > 3:
            suggestions.append(
                f"💡 {global_vars} globale Variablen gefunden - Singleton Pattern erwägen"
            )
        
        # Factory-Check: Viele if/elif für Objekterstellung
        if 'if ' in code and 'isinstance' in code:
            suggestions.append(
                "💡 Typ-Checks gefunden - Factory Pattern erwägen"
            )
        
        # Observer-Check: Viele Callbacks
        callback_count = code.count('callback') + code.count('_on_')
        if callback_count > 5:
            suggestions.append(
                "💡 Viele Callbacks - Observer Pattern erwägen"
            )
        
        return suggestions
    
    def suggest_optimization(self, file_path: str) -> List[str]:
        """Schlägt Code-Optimierungen vor"""
        analysis = self.analyze_file(file_path)
        suggestions = []
        
        # Komplexität
        if analysis.complexity_score > 20:
            suggestions.append(
                f"⚠️ Hohe Komplexität ({analysis.complexity_score}): "
                "Funktionen aufteilen"
            )
        
        # Große Funktionen
        for func in analysis.functions:
            lines = func.get('end_line', 0) - func.get('line', 0)
            if lines > 50:
                suggestions.append(
                    f"📦 {func['name']}(): {lines} Zeilen - aufteilen?"
                )
        
        # Viele Imports
        if len(analysis.imports) > 20:
            suggestions.append(
                f"📚 {len(analysis.imports)} Imports - aufräumen?"
            )
        
        return suggestions
    
    def compare_files(self, file1: str, file2: str) -> List[str]:
        """Vergleicht zwei Dateien"""
        content1 = Path(file1).read_text(encoding='utf-8').splitlines()
        content2 = Path(file2).read_text(encoding='utf-8').splitlines()
        
        diff = list(difflib.unified_diff(
            content1, content2,
            fromfile=file1, tofile=file2,
            lineterm=''
        ))
        
        return diff
    
    # ========== KOLLABORATION (Phase 5) ==========
    
    def add_feedback(self, task_id: str, feedback: str, rating: int = 3):
        """Speichert User-Feedback zu einem Task"""
        self.feedback_log.append({
            "task_id": task_id,
            "feedback": feedback,
            "rating": rating,
            "timestamp": datetime.now().isoformat()
        })
        self.logger.info(f"Feedback erhalten fuer {task_id}: {rating}/5")
    
    def get_task_feedback(self, task_id: str) -> List[Dict]:
        """Holt Feedback für einen Task"""
        return [f for f in self.feedback_log if f['task_id'] == task_id]
    
    def interactive_task(self, task_id: str, callback: Callable = None) -> Dict:
        """Bearbeitet Task interaktiv mit User-Feedback"""
        task = next((t for t in self.task_queue['queue'] 
                    if t['id'] == task_id), None)
        
        if not task:
            return {"error": "Task nicht gefunden"}
        
        result = {
            "task_id": task_id,
            "status": "in_progress",
            "steps": [],
            "awaiting_feedback": True
        }
        
        # Schritt 1: Analyse
        result['steps'].append({
            "step": "analyse",
            "status": "pending",
            "message": "Analysiere Aufgabe..."
        })
        
        if callback:
            callback(result)
        
        return result
    
    def sync_with_editor(self, project_id: str) -> Dict:
        """Synchronisiert Projekt mit Editor"""
        project = self.project_registry['projects'].get(project_id)
        if not project:
            return {"error": "Projekt nicht gefunden"}
        
        # Prüfe geänderte Dateien
        changes = []
        for file_path in project.get('files', []):
            path = Path(file_path)
            if path.exists():
                current_hash = hashlib.md5(
                    path.read_bytes()
                ).hexdigest()
                
                cached_hash = project.get('file_hashes', {}).get(file_path)
                if cached_hash and cached_hash != current_hash:
                    changes.append(file_path)
        
        return {
            "project_id": project_id,
            "files_changed": changes,
            "sync_time": datetime.now().isoformat()
        }
    
    # ========== TESTING (Phase 6) ==========
    
    def run_tests(self, project_id: str) -> Dict:
        """Führt Tests für ein Projekt aus"""
        project = self.project_registry['projects'].get(project_id)
        if not project:
            return {"error": "Projekt nicht gefunden"}
        
        project_path = Path(project['path'])
        test_files = list(project_path.rglob("test_*.py"))
        
        results = {
            "project_id": project_id,
            "tests_found": len(test_files),
            "tests_passed": 0,
            "tests_failed": 0,
            "details": []
        }
        
        for test_file in test_files:
            test_result = self.run_script(str(test_file))
            
            if test_result['success']:
                results['tests_passed'] += 1
            else:
                results['tests_failed'] += 1
            
            results['details'].append({
                "file": str(test_file),
                "success": test_result['success'],
                "output": test_result['stdout'][:500]
            })
        
        return results
    
    def generate_test(self, file_path: str) -> str:
        """Generiert Test-Datei für eine Python-Datei"""
        if not self.generator:
            raise RuntimeError("Coding-Module nicht verfuegbar (code_generator.py nicht gefunden)")
        analysis = self.analyze_file(file_path)
        tests = []
        
        for func in analysis.functions:
            if not func['name'].startswith('_'):
                test = self.generator.generate_test(
                    name=func['name'],
                    target=func['name'],
                    arrange=f"# Setup für {func['name']}",
                    act=f"result = {func['name']}()",
                    assertions=f"assert result is not None  # TODO: Echte Assertions"
                )
                tests.append(test)
        
        # Test-Modul zusammenbauen
        module = self.generator.generate_module(
            module_name=f"test_{Path(file_path).stem}",
            description=f"Tests für {Path(file_path).name}",
            imports=[
                "import pytest",
                f"from {Path(file_path).stem} import *"
            ],
            content="\n\n".join(tests)
        )
        
        return module
    
    # ========== REPORTING ==========
    
    def status_report(self) -> str:
        """Generiert Status-Bericht"""
        report = []
        report.append(f"=== ENTWICKLER-AGENT v{self.VERSION} ===\n")
        report.append(f"BACH: {'verfuegbar' if self.bach_available else 'nicht verfuegbar'}")
        report.append(f"Coding-Module: {'geladen' if _CODING_AVAILABLE else 'nicht verfuegbar'}")

        # Projekte
        total = self.project_registry['meta']['total_projects']
        active = len([p for p in self.list_projects() if p['status'] == 'active'])
        report.append(f"Projekte: {total} (Aktiv: {active})")

        # Tasks
        pending = len([t for t in self.task_queue['queue'] if t['status'] == 'pending'])
        completed = len([t for t in self.task_queue['queue'] if t['status'] == 'completed'])
        report.append(f"Tasks: {pending} offen, {completed} erledigt")

        return "\n".join(report)

    # --- PortableAgent Interface ---

    def run(self, **kwargs) -> Any:
        """Hauptfunktion: naechsten Task bearbeiten oder Kommando ausfuehren."""
        command = kwargs.get("command", "status")
        if command == "status":
            return self.status()
        if command == "analyze" and kwargs.get("file"):
            return self.analyze_file(kwargs["file"])
        return self.status()

    def status(self) -> Dict:
        return {
            "agent": self.AGENT_NAME,
            "version": self.VERSION,
            "bach_available": self.bach_available,
            "coding_available": _CODING_AVAILABLE,
            "projects": self.project_registry['meta']['total_projects'],
            "tasks_pending": len([t for t in self.task_queue['queue'] if t['status'] == 'pending']),
        }

    def config(self) -> Dict:
        return self._config

    def standalone_config_template(self) -> Dict:
        return {
            "meta": {"version": self.VERSION, "created": datetime.now().isoformat()},
            "paths": {"projects": "projects", "tasks": "tasks", "reports": "reports"},
            "settings": {
                "auto_save": True,
                "max_complexity": 20,
                "code_style": "pep8"
            }
        }


def main():
    """CLI Entry Point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Entwickler-Agent v1.0.0")
    parser.add_argument('command', choices=[
        'status', 'analyze', 'debug', 'generate', 'test', 'optimize'
    ])
    parser.add_argument('--file', '-f', help="Datei-Pfad")
    parser.add_argument('--project', '-p', help="Projekt-ID")
    parser.add_argument('--auto-fix', action='store_true', help="Auto-Fix aktivieren")
    
    args = parser.parse_args()
    agent = EntwicklerAgent()
    
    if args.command == 'status':
        print(agent.status_report())
    
    elif args.command == 'analyze' and args.file:
        result = agent.analyze_file(args.file)
        print(agent.analyzer.to_json(result))
    
    elif args.command == 'debug' and args.file:
        result = agent.debug_file(args.file, args.auto_fix)
        print(f"Errors: {result.errors_found}, Fixed: {result.errors_fixed}")
        for s in result.suggestions:
            print(f"  {s}")
    
    elif args.command == 'optimize' and args.file:
        suggestions = agent.suggest_optimization(args.file)
        for s in suggestions:
            print(s)
    
    elif args.command == 'test' and args.project:
        results = agent.run_tests(args.project)
        print(f"Tests: {results['tests_passed']} passed, {results['tests_failed']} failed")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
