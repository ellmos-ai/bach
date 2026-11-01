"""Diagnostic unittest for Task #3718: inspect current worktree git state."""
import subprocess
import unittest

REPO = "/Users/lukas/services/bach-worktrees/task-3718"


class TestGitStatus3718(unittest.TestCase):
    def run_git(self, args):
        result = subprocess.run(
            ["git", "-C", REPO] + args,
            capture_output=True,
            text=True,
            check=False,
        )
        return result

    def test_status(self):
        r = self.run_git(["status", "--short", "--branch"])
        print("\n--- git status ---")
        print(r.stdout)
        print(r.stderr)
        self.assertEqual(r.returncode, 0, f"git status failed: {r.stderr}")

    def test_current_branch(self):
        r = self.run_git(["symbolic-ref", "--short", "HEAD"])
        print("\n--- current branch ---")
        print(r.stdout.strip())
        self.assertEqual(r.returncode, 0)

    def test_diff_check(self):
        r = self.run_git(["diff", "--check"])
        print("\n--- git diff --check ---")
        print(r.stdout)
        print(r.stderr)
        self.assertEqual(r.returncode, 0, f"git diff --check failed: {r.stderr}")

    def test_diff_stat(self):
        r = self.run_git(["diff", "--stat"])
        print("\n--- git diff --stat ---")
        print(r.stdout)
        self.assertEqual(r.returncode, 0)

    def test_remote_url(self):
        r = self.run_git(["config", "--get", "remote.origin.url"])
        print("\n--- remote.origin.url ---")
        print(r.stdout.strip())

    def test_log_oneline(self):
        r = self.run_git(["log", "--oneline", "-3"])
        print("\n--- git log -3 ---")
        print(r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
