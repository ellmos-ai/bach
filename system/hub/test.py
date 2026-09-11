# SPDX-License-Identifier: MIT
"""
BACH Test Handler
=================
CLI-Handler fuer Test- und QA-Funktionen.

Befehle:
    bach --test self [PROFIL] [--native]   Selbsttest (QUICK/STANDARD/FULL)
    bach --test run <path> [PROFIL]        System testen
    bach --test compare <path> [PROFIL]    Mit BACH vergleichen
    bach --test profiles                   Profile anzeigen
    bach --test results [system]           Letzte Ergebnisse anzeigen

Adapter:
    Bevorzugt wird das externe ellmos-tests-Modul verwendet, falls es
    lokal erreichbar ist (Umgebungsvariable ELLMOS_TESTS_PATH, Geschwister-
    checkout oder Git-Root-Erkennung).  Ist ellmos-tests nicht verfuegbar
    oder wird --native angegeben, laeuft der legacy test_runner.py aus
    tools/testing/ (Rollback-Pfad).
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

# ellmos-tests Profile, die 1:1 uebernommen werden koennen
ELLMOS_PROFILES = {"QUICK", "STANDARD", "FULL", "OBSERVATION", "OUTPUT"}


class TestHandler(BaseHandler):
    """Handler fuer --test Befehle"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.testing_dir = base_path / "tools" / "testing"
        self.results_dir = self.testing_dir / "results"
        self._force_native = False
        self._ellmos_path: Path | None = None

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
            "compare": "Mit BACH vergleichen: compare <path> [PROFIL]",
            "profiles": "Verfuegbare Profile anzeigen",
            "results": "Testergebnisse anzeigen"
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if not operation:
            return True, self._show_help()

        op = operation.lower()

        # Globale Flags aus args entfernen, bevor sie an Unterkommandos gehen
        self._force_native = "--native" in args or "--legacy" in args
        args = [a for a in args if a not in ("--native", "--legacy")]
        self._ellmos_path = self._find_ellmos_tests()

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

    def _find_ellmos_tests(self) -> Path | None:
        """Loesst den ellmos-tests-Checkout auf.

        Reihenfolge:
        1. ELLMOS_TESTS_PATH Umgebungsvariable
        2. Geschwisterverzeichnis zum BACH-Root (../ellmos-tests)
        3. Git-Root-Erkennung ausgehend vom BACH-Root
        """
        env_path = os.environ.get("ELLMOS_TESTS_PATH")
        if env_path:
            candidate = Path(env_path).expanduser().resolve()
            if self._is_valid_ellmos_tests(candidate):
                return candidate

        # Geschwisterverzeichnis BACH-Root / ellmos-tests
        bach_root = self.base_path.parent if self.base_path.name == "system" else self.base_path
        sibling = (bach_root.parent / "ellmos-tests").resolve()
        if self._is_valid_ellmos_tests(sibling):
            return sibling

        # Git-Root-Erkennung: BACH-Root selbst kann in einem Workspace liegen
        try:
            git_root = subprocess.run(
                ["git", "-C", str(bach_root), "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
            )
            if git_root.returncode == 0:
                workspace_root = Path(git_root.stdout.strip()).parent
                candidate = workspace_root / "ellmos-tests"
                if self._is_valid_ellmos_tests(candidate):
                    return candidate
        except Exception:
            pass

        return None

    @staticmethod
    def _is_valid_ellmos_tests(path: Path) -> bool:
        """Prueft, ob der Pfad ein benutzbares ellmos-tests enthaelt."""
        return (
            path.exists()
            and path.is_dir()
            and (path / "system_diff_tests" / "testing" / "run_external.py").exists()
        )

    def _use_ellmos_tests(self) -> bool:
        """True, wenn ellmos-tests verwendet werden soll."""
        if self._force_native:
            return False
        return self._ellmos_path is not None

    def _ellmos_runner(self) -> Path:
        """Pfad zum ellmos-tests runner."""
        return self._ellmos_path / "system_diff_tests" / "testing" / "run_external.py"

    def _legacy_runner(self) -> Path:
        """Pfad zum legacy BACH test_runner."""
        return self.testing_dir / "test_runner.py"

    def _run_self_test(self, args: list) -> tuple:
        """Fuehrt Selbsttest auf BACH aus."""
        profile = args[0].upper() if args else "QUICK"
        if profile not in PROFILES:
            return False, f"Unbekanntes Profil: {profile}\nVerfuegbar: {', '.join(PROFILES)}"

        if self._use_ellmos_tests():
            if profile not in ELLMOS_PROFILES:
                return False, f"Profil '{profile}' wird von ellmos-tests nicht unterstuetzt.\n"
                              f"Nutze eines von: {', '.join(sorted(ELLMOS_PROFILES))}"
            return self._run_external_runner(str(self.base_path), profile)

        runner = self._legacy_runner()
        if not runner.exists():
            return False, f"Test-Runner nicht gefunden: {runner}"

        try:
            result = subprocess.run(
                [sys.executable, str(runner), str(self.base_path), "-p", profile],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
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

        if self._use_ellmos_tests():
            if profile not in ELLMOS_PROFILES:
                return False, f"Profil '{profile}' wird von ellmos-tests nicht unterstuetzt.\n"
                              f"Nutze eines von: {', '.join(sorted(ELLMOS_PROFILES))}"
            return self._run_external_runner(system_path, profile)

        runner = self._legacy_runner()
        try:
            result = subprocess.run(
                [sys.executable, str(runner), system_path, "-p", profile],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
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

        if self._use_ellmos_tests():
            if profile not in ELLMOS_PROFILES:
                return False, f"Profil '{profile}' wird von ellmos-tests nicht unterstuetzt.\n"
                              f"Nutze eines von: {', '.join(sorted(ELLMOS_PROFILES))}"
            # ellmos-tests unterstuetzt kein direktes Compare; wir fuehren beide
            # Systeme nacheinander aus und geben die beiden Ergebnisse aus.
            ok1, out1 = self._run_external_runner(str(self.base_path), profile)
            ok2, out2 = self._run_external_runner(other_path, profile)
            header = (
                "VERGLEICH (ellmos-tests Adapter)\n"
                f"BACH:     {self.base_path}\n"
                f"Anderes:  {other_path}\n"
                f"Profil:   {profile}\n"
                "=" * 70 + "\n"
            )
            return ok1 and ok2, header + "\n--- BACH ---\n" + out1 + "\n--- ANDERES ---\n" + out2

        runner = self._legacy_runner()
        try:
            result = subprocess.run(
                [sys.executable, str(runner), str(self.base_path), "--compare", other_path, "-p", profile],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600
            )
            output = result.stdout + (result.stderr if result.returncode != 0 else "")
            return result.returncode == 0, output
        except Exception as e:
            return False, f"Fehler: {e}"

    def _run_external_runner(self, system_path: str, profile: str) -> tuple:
        """Ruft ellmos-tests run_external.py auf."""
        runner = self._ellmos_runner()
        try:
            result = subprocess.run(
                [sys.executable, str(runner), system_path, "--profile", profile],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600
            )
            output = result.stdout + (result.stderr if result.returncode != 0 else "")
            return result.returncode == 0, output
        except subprocess.TimeoutExpired:
            return False, "TIMEOUT: ellmos-tests hat zu lange gedauert (> 10 Min)"
        except Exception as e:
            return False, f"Fehler bei ellmos-tests: {e}"

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
            "MEMORY_FOCUS": "Memory-Fokus (~10 Min) - legacy only",
            "TASK_FOCUS": "Task-Fokus (~10 Min) - legacy only"
        }

        for name, desc in profile_info.items():
            lines.append(f"  {name:<15} {desc}")

        lines.append("")
        if self._use_ellmos_tests():
            lines.append(f"Adapter: ellmos-tests ({self._ellmos_path})")
        else:
            lines.append("Adapter: legacy test_runner.py (Fallback)")
        lines.append("Nutzung: bach --test self <PROFIL>")

        return "\n".join(lines)

    def _show_results(self, args: list) -> str:
        """Zeigt Testergebnisse."""
        system_filter = args[0] if args else None
        lines = []
        lines.append("=" * 70)
        lines.append("TESTERGEBNISSE")
        lines.append("=" * 70)
        found = False

        # 1) ellmos-tests Ergebnisse
        if self._ellmos_path is not None:
            ellmos_output = self._ellmos_path / "system_diff_tests" / "output"
            if ellmos_output.exists():
                lines.append("\n--- ellmos-tests output ---")
                for system_dir in sorted(ellmos_output.iterdir()):
                    if not system_dir.is_dir():
                        continue
                    if system_filter and system_filter.lower() not in system_dir.name.lower():
                        continue
                    lines.append(f"\n{system_dir.name}")
                    for result_file in sorted(system_dir.glob("*.json"), reverse=True)[:3]:
                        try:
                            with open(result_file, 'r', encoding='utf-8') as f:
                                data = json.load(f)
                            profile = data.get("profile", "?")
                            overall = data.get("summary", {}).get("avg_score", data.get("summary", {}).get("overall", 0))
                            lines.append(f"  {result_file.name} - Profil: {profile}, Score: {overall}/5.0")
                            found = True
                        except (json.JSONDecodeError, OSError, KeyError):
                            pass

        # 2) legacy Ergebnisse
        if self.results_dir.exists():
            lines.append("\n--- legacy output ---")
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
        adapter = "ellmos-tests"
        adapter_path = str(self._ellmos_path) if self._ellmos_path else "nicht gefunden"
        fallback = "legacy test_runner.py" if self._ellmos_path is None else "--native fuer legacy"
        return f"""BACH Test-System
================

Adapter: {adapter} ({adapter_path})
Fallback: {fallback}

Befehle:
  bach --test self [PROFIL] [--native]  Selbsttest (default: QUICK)
  bach --test run <path> [PROFIL]       Anderes System testen
  bach --test compare <path> [PROFIL]  Mit BACH vergleichen
  bach --test profiles                   Profile anzeigen
  bach --test results [system]           Ergebnisse anzeigen

Profile: QUICK, STANDARD, FULL, OBSERVATION, OUTPUT
          MEMORY_FOCUS, TASK_FOCUS (nur legacy)

Umgebungsvariablen:
  ELLMOS_TESTS_PATH   Pfad zum ellmos-tests-Checkout

Beispiele:
  bach --test self              # Schneller Selbsttest via ellmos-tests
  bach --test self STANDARD     # Standard-Selbsttest
  bach --test self --native     # Legacy-Runner erzwingen
  bach --test run "C:\\...\\sys" # Anderes System testen
  bach --test compare "C:\\..."  # Mit BACH vergleichen

Agent: agents/test-agent.txt
Tools: tools/testing/"""
