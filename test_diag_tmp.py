"""Temporary pytest wrapper for diag_skill.py."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIAG = ROOT / "diag_skill.py"


def test_diag_skill_runs_cleanly():
    result = subprocess.run(
        [sys.executable, str(DIAG)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"diag_skill.py failed with {result.returncode}:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
