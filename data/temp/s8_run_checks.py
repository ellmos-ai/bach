import os
import subprocess
import sys

REPO = "/Users/lukas/ocean-workspaces/MAC-FULL-INSTALL-01/src/open-ocean"
OUT_PATH = "/Users/lukas/services/bach/data/temp/s8_run_checks_output.txt"

os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)


def run_and_log(cmd, out):
    result = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    header = "CMD: " + " ".join(cmd)
    block = (
        header + "\n"
        + "returncode: " + str(result.returncode) + "\n"
        + "--- stdout ---\n"
        + (result.stdout or "")
        + "\n--- stderr ---\n"
        + (result.stderr or "")
        + "\n"
        + "=" * 70 + "\n"
    )
    print(block)
    out.write(block)
    return result


with open(OUT_PATH, "w") as out:
    checker = run_and_log(
        [sys.executable, "tools/check_skills_workflow_projection.py"], out
    )
    pytest = run_and_log(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_check_skills_workflow_projection.py",
            "tests/test_check_memory_task_transit.py",
            "-v",
        ],
        out,
    )

print("SUMMARY checker_rc=%d pytest_rc=%d" % (checker.returncode, pytest.returncode))