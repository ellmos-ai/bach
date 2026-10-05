#!/usr/bin/env python3
"""Startet scripts/monitor_1564.py im Hintergrund und gibt die PID aus."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "monitor_1564.py"
LOG = ROOT / "logs" / "monitor_1564_nohup.out"

LOG.parent.mkdir(exist_ok=True)

process = subprocess.Popen(
    [sys.executable, str(SCRIPT)],
    stdout=open(LOG, "a", encoding="utf-8"),
    stderr=subprocess.STDOUT,
    cwd=str(ROOT),
    start_new_session=True,
)

print(f"monitor_1564.py gestartet, PID={process.pid}, LOG={LOG}")
