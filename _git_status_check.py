import subprocess
import sys

result = subprocess.run(
    ["git", "status", "--porcelain"],
    cwd="/Users/lukas/services/bach-worktrees/task-2579",
    capture_output=True,
    text=True,
    check=False,
    timeout=10,
)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)
print("RC:", result.returncode)
sys.exit(0)