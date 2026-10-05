import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
out = ROOT / "data" / "temp" / "pytest_module_update_gate.out"
cwd = ROOT / "system"
r = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/test_module_update_gate.py", "-v"],
    capture_output=True,
    text=True,
    cwd=str(cwd),
)
out.write_text(r.stdout + "\n" + r.stderr + "\nEXIT:%d" % r.returncode, encoding="utf-8")
print("EXIT:%d" % r.returncode)
