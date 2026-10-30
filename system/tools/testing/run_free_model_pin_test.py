#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
run_free_model_pin_test.py - Testlaeufer fuer test_free_model_pin.py

Schreibt das Ergebnis in system/tests/free_model_pin_test_result.txt,
so dass es auch bei blockiertem Agenten-execute_command im Dateisystem
gelesen werden kann.
"""

import os
import sys
import subprocess
import datetime

BACH_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
    )
)

RESULT_FILE = os.path.join(BACH_DIR, "system", "tests", "free_model_pin_test_result.txt")
TEST_FILE = os.path.join(BACH_DIR, "system", "tests", "test_free_model_pin.py")


def main() -> int:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        TEST_FILE,
    ]
    cwd = BACH_DIR
    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.join(cwd, "system") + os.pathsep + env.get("PYTHONPATH", "")

    start = datetime.datetime.now(datetime.timezone.utc)
    result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    end = datetime.datetime.now(datetime.timezone.utc)

    lines = [
        "Free-Model-Pin Test Run",
        f"Started: {start.isoformat()}",
        f"Finished: {end.isoformat()}",
        f"Command: {' '.join(cmd)}",
        f"Return code: {result.returncode}",
        "",
        "=== STDOUT ===",
        result.stdout or "(empty)",
        "",
        "=== STDERR ===",
        result.stderr or "(empty)",
    ]
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # Auch auf stdout ausgeben, falls der Aufrufer es lesen kann
    print("\n".join(lines))
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
