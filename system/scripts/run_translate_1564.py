#!/usr/bin/env python3
"""Startet translate_surface.py im Hintergrund und loggt Ausgaben."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "logs" / "translate_surface_1564.log"
SCRIPT = ROOT / "scripts" / "translate_surface.py"

LOG.parent.mkdir(exist_ok=True)

with open(LOG, "a", encoding="utf-8") as log_fh:
    process = subprocess.Popen(
        [sys.executable, str(SCRIPT)],
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        cwd=str(ROOT),
        start_new_session=True,
    )

print(f"translate_surface.py gestartet, PID={process.pid}, LOG={LOG}")
