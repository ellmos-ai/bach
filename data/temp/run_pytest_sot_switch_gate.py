# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Runner: pytest fuer system/tests/test_sot_switch_gate.py (Task #1356)."""
import subprocess
import sys
from pathlib import Path

BACH_ROOT = Path(__file__).resolve().parents[2]
ABS_OUT = "/Users/lukas/services/bach/data/temp/pytest_sot_switch_gate.out"

with open(ABS_OUT, "w") as fh:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_sot_switch_gate.py", "-v"],
        cwd=BACH_ROOT / "system",
        stdout=fh,
        stderr=subprocess.STDOUT,
    )
print("EXIT:%d" % proc.returncode)