#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
run_pytest.py - Minimaler pytest-Wrapper fuer BACH

Usage:
    python run_pytest.py [PATH ...] [pytest options]

Beispiele:
    python run_pytest.py system/tests/test_free_model_pin.py
    python run_pytest.py system/tests -v
"""

import argparse
import os
import sys
import subprocess

# BACH-Wurzelverzeichnis: system/tools/testing/run_pytest.py -> 4 Ebenen hoch
BACH_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
    )
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fuehrt pytest im BACH-Projekt aus.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Test-Dateien oder -Verzeichnisse (Standard: system/tests)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Detaillierte Ausgabe",
    )
    parser.add_argument(
        "-k",
        dest="keyword",
        default=None,
        help="Nur Tests mit passendem Keyword-Filter ausfuehren",
    )

    args, extra = parser.parse_known_args()

    cmd = [sys.executable, "-m", "pytest"]
    if args.verbose:
        cmd.append("-v")
    if args.keyword:
        cmd.extend(["-k", args.keyword])
    cmd.extend(extra)
    cmd.extend(args.paths if args.paths else ["system/tests"])

    # Sicherstellen, dass der Worktree als Arbeitsverzeichnis verwendet wird
    cwd = BACH_DIR

    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.join(cwd, "system") + os.pathsep + env.get("PYTHONPATH", "")

    print(f"[run_pytest] cwd={cwd}")
    print(f"[run_pytest] {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, env=env)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
