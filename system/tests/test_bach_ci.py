# Pruefungen fuer das lokale CI-Skript bach-ci (Repo-Root).
# Alle Skript-Aufrufe laufen als Subprocess mit Argumentliste (keine Shellverkettung).
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "bach-ci"


def test_script_present_and_readable() -> None:
    # Skript vorhanden und lesbar; Aufruf via 'bash bach-ci', exec-bit wird durch Werkzeuge nicht garantiert.
    assert SCRIPT.is_file()
    assert os.access(SCRIPT, os.R_OK)


def test_bash_syntax_check() -> None:
    # Werkzeugbeleg der Syntaxpruefung: bash -n meldet keine Fehler.
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_fast_run_smoke() -> None:
    # Schnell-Lauf (nur Scan + diff --check): exit 0 plus Abschlussmeldung.
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--fast"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "alle Pruefungen bestanden" in proc.stdout


def test_skip_tests_run() -> None:
    # Lauf ohne pytest-Teil (compileall + Scan + diff --check): exit 0.
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--skip-tests"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
