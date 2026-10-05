import subprocess
import sys

with open("/Users/lukas/services/bach/data/temp/pytest_1414.out", "w") as fh:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "system/tests/test_connectors_and_tray.py"],
        cwd="/Users/lukas/services/bach",
        stdout=fh,
        stderr=subprocess.STDOUT,
    )
print("EXIT:%d" % proc.returncode)