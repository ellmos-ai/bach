"""Referenz-Check: Verdachts-Tests aus den Parallel-Laeufen einzeln laufen lassen.
Startet pytest entkoppelt (start_new_session), damit execute_command sofort zurueckkehrt.
Output: /Users/lukas/services/bach/data/temp/pytest_refcheck.out
PID:    /Users/lukas/services/bach/data/temp/pytest_refcheck.pid
"""
import subprocess
import sys

OUT = "/Users/lukas/services/bach/data/temp/pytest_refcheck.out"
PIDF = "/Users/lukas/services/bach/data/temp/pytest_refcheck.pid"

TESTS = [
    # Echte Defekt-Kandidaten
    "system/tests/test_working_memory_failure_trails.py",
    "system/tests/test_skills_projection.py::test_counts_parity",
    "system/tests/test_startspine.py",
    "system/tests/test_migration_baseline_check.py",
    # Kollisions-Kontrolle (grosse lastfailed-Cluster)
    "system/tests/test_gui_server_smoke.py",
    "system/tests/test_sandbox_handler.py",
    "system/tests/test_injector_parity.py",
]

cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly"] + TESTS
fh = open(OUT, "w")
p = subprocess.Popen(
    cmd,
    cwd="/Users/lukas/services/bach",
    stdin=subprocess.DEVNULL,
    stdout=fh,
    stderr=subprocess.STDOUT,
    start_new_session=True,
)
with open(PIDF, "w") as pf:
    pf.write(str(p.pid))
print("STARTED PID:", p.pid)
print("CMD:", " ".join(cmd))
