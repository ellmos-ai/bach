# SPDX-License-Identifier: MIT
"""
BACH Test Handler
=================
CLI-Handler fuer Test- und QA-Funktionen.

Befehle:
    bach --test self           Selbsttest (QUICK)
    bach --test self STANDARD  Selbsttest mit Profil
    bach --test run <path>     System testen
    bach --test compare <path> Mit BACH vergleichen
    bach --test profiles       Profile anzeigen
    bach --test results        Letzte Ergebnisse
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime
from .base import BaseHandler

# Verfuegbare Profile
PROFILES = ["QUICK", "STANDARD", "FULL", "OBSERVATION", "OUTPUT", "MEMORY_FOCUS", "TASK_FOCUS"]


class TestHandler(BaseHandler):
    """Handler fuer --test Befehle"""
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.testing_dir = base_path / "tools" / "testing"
        self.results_dir = self.testing_dir / "results"
    
    @property
    def profile_name(self) -> str:
        return "test"
    
    @property
    def target_file(self) -> Path:
        return self.testing_dir
    
    def get_operations(self) -> dict:
        return {
            "self": "BACH selbst testen (QUICK/STANDARD/FULL)",
            "run": "System testen: run <path> [PROFIL]",
            "compare": "Mit BACH vergleichen: compare <path>",
            "profiles": "Verfuegbare Profile anzeigen",
            "results": "Testergebnisse anzeigen"
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if not operation:
            return True, self._show_help()
        
        op = operation.lower()
        
        if op == "self":
            return self._run_self_test(args)
        elif op == "run":
            return self._run_system_test(args)
        elif op == "compare":
            return self._compare_with_bach(args)
        elif op == "profiles":
            return True, self._list_profiles()
        elif op == "results":
            return True, self._show_results(args)
        elif op in ["help", "-h"]:
            return True, self._show_help()
        else:
            return False, f"Unbekannter Befehl: {op}\n\n{self._show_help()}"
    
    def _run_self_test(self, args: list) -> tuple:
        """Fuehrt Selbsttest auf BACH aus."""
        profile = args[0].upper() if args else "QUICK"
        if profile not in PROFILES:
            return False, f"Unbekanntes Profil: {profile}\nVerfuegbar: {', '.join(PROFILES)}"
        
        runner = self.testing_dir / "test_runner.py"
        if not runner.exists():
            return False, f"Test-Runner nicht gefunden: {runner}"
        
        try:
            result = subprocess.run(
                [sys.executable, str(runner), str(self.base_path), "-p", profile],
                capture_output=True,
                text=True,
                timeout=300
            )
            output = result.stdout + (result.stderr if result.returncode != 0 else "")
            return result.returncode == 0, output
        except subprocess.TimeoutExpired:
            return False, "TIMEOUT: Test hat zu lange gedauert (> 5 Min)"
        except Exception as e:
            return False, f"Fehler beim Ausfuehren: {e}"
    
    def _run_system_test(self, args: list) -> tuple:
        """Testet ein beliebiges System."""
        if not args:
            return False, r"Fehler: Pfad zum System erforderlich\nBeispiel: bach --test run C:\...\system"
        
        system_path = args[0]
        profile = args[1].upper() if len(args) > 1 else "STANDARD"
        
        if not Path(system_path).exists():
            return False, f"Pfad existiert nicht: {system_path}"
        
        runner = self.testing_dir / "test_runner.py"
        
        try:
            result = subprocess.run(
                [sys.executable, str(runner), system_path, "-p", profile],
                capture_output=True,
                text=True,
                timeout=300
            )
            output = result.stdout + (result.stderr if result.returncode != 0 else "")
            return result.returncode == 0, output
        except Exception as e:
            return False, f"Fehler: {e}"
    
    def _compare_with_bach(self, args: list) -> tuple:
        """Vergleicht ein System mit BACH."""
        if not args:
            return False, r"Fehler: Pfad zum Vergleichssystem erforderlich\nBeispiel: bach --test compare C:\...\anderes"
        
        other_path = args[0]
        profile = args[1].upper() if len(args) > 1 else "STANDARD"
        
        if not Path(other_path).exists():
            return False, f"Pfad existiert nicht: {other_path}"
        
        runner = self.testing_dir / "test_runner.py"
        
        try:
            result = subprocess.run(
                [sys.executable, str(runner), str(self.base_path), "--compare", other_path, "-p", profile],
                capture_output=True,
                text=True,
                timeout=600
            )
            output = result.stdout + (result.stderr if result.returncode != 0 else "")
            return result.returncode == 0, output
        except Exception as e:
            return False, f"Fehler: {e}"
    
    def _list_profiles(self) -> str:
        """Zeigt verfuegbare Testprofile."""
        lines = []
        lines.append("=" * 50)
        lines.append("TESTPROFILE")
        lines.append("=" * 50)
        lines.append("")
        
        profile_info = {
            "QUICK": "Schnelltest (~5 Min) - B001, O001",
            "STANDARD": "Standard (~20 Min) - B001-B005, O001-O003",
            "FULL": "Vollstaendig (~40 Min) - Alle Tests",
            "OBSERVATION": "Nur B-Tests (~15 Min)",
            "OUTPUT": "Nur O-Tests (~20 Min)",
            "MEMORY_FOCUS": "Memory-Fokus (~10 Min)",
            "TASK_FOCUS": "Task-Fokus (~10 Min)"
        }
        
        for name, desc in profile_info.items():
            lines.append(f"  {name:<15} {desc}")
        
        lines.append("")
        lines.append("Nutzung: bach --test self <PROFIL>")
        
        return "\n".join(lines)
    
    def _show_results(self, args: list) -> str:
        """Zeigt Testergebnisse."""
        if not self.results_dir.exists():
            return "Noch keine Ergebnisse vorhanden."
        
        lines = []
        lines.append("=" * 70)
        lines.append("TESTERGEBNISSE")
        lines.append("=" * 70)
        
        system_filter = args[0] if args else None
        found = False
        
        for system_dir in self.results_dir.iterdir():
            if not system_dir.is_dir():
                continue
            if system_filter and system_filter.lower() not in system_dir.name.lower():
                continue
            
            lines.append(f"\n--- {system_dir.name} ---")
            
            for result_file in sorted(system_dir.glob("*.json"), reverse=True)[:3]:
                try:
                    with open(result_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    profile = data.get("profile", "?")
                    overall = data.get("summary", {}).get("overall", 0)
                    
                    lines.append(f"  {result_file.name}")
                    lines.append(f"    Profil: {profile}, Score: {overall}/5.0")
                    found = True
                except (json.JSONDecodeError, OSError, KeyError):
                    pass

        if not found:
            lines.append("\nKeine Ergebnisse gefunden.")
        
        return "\n".join(lines)
    
    def _show_help(self) -> str:
        """Zeigt Hilfe fuer Test-Handler."""
        return """BACH Test-System
================

Befehle:
  bach --test self [PROFIL]     Selbsttest (default: QUICK)
  bach --test run <path>        System testen
  bach --test compare <path>    Mit BACH vergleichen
  bach --test profiles          Profile anzeigen
  bach --test results [system]  Ergebnisse anzeigen

Profile: QUICK, STANDARD, FULL, OBSERVATION, OUTPUT

Beispiele:
  bach --test self              # Schneller Selbsttest
  bach --test self STANDARD     # Standard-Selbsttest
  bach --test run "C:\\...\\sys" # Anderes System testen
  bach --test compare "C:\\..."  # Mit BACH vergleichen

Agent: agents/test-agent.txt
Tools: tools/testing/"""
