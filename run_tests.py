import subprocess
import sys

result = subprocess.run(
    [sys.executable, "-m", "pytest", "-q", "--tb=short", "system/tests/test_free_model_pin.py"],
    cwd="/Users/lukas/services/bach-worktrees/task-2563",
    capture_output=True,
    text=True,
    timeout=120,
)
with open("test_output.txt", "w", encoding="utf-8") as f:
    f.write("=== STDOUT ===\n")
    f.write(result.stdout)
    f.write("\n=== STDERR ===\n")
    f.write(result.stderr)
    f.write(f"\n=== RETURN CODE ===\n{result.returncode}\n")
print("Test output written to test_output.txt")
print("Return code:", result.returncode)
print("STDOUT tail:", result.stdout[-500:])
