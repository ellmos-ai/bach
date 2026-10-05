import subprocess, sys

ABS_OUT = "/Users/lukas/services/bach/data/temp/pytest_1416.out"

with open(ABS_OUT, "w") as fh:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "system/tests/test_composition_rules.py", "system/tests/test_gui_shell.py"],
        cwd="/Users/lukas/services/bach",
        stdout=fh,
        stderr=subprocess.STDOUT,
    )

print("EXIT:%d" % proc.returncode)