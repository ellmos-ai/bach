import os
import subprocess
import tempfile
import unittest
from pathlib import Path


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, check=False, timeout=30)


class AutoCommitTaskWorktreeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _git(["init", "-q"], self.repo)
        _git(["config", "user.email", "test@example.com"], self.repo)
        _git(["config", "user.name", "Test"], self.repo)
        (self.repo / "base.txt").write_text("basis\n", encoding="utf-8")
        _git(["add", "-A"], self.repo)
        _git(["commit", "-q", "-m", "basis"], self.repo)
        self.wt_root = self.tmp / "worktrees"
        self.wt_root.mkdir()
        res = _git(["worktree", "add", "-q", "-b", "bach-task/4711",
                    str(self.wt_root / "task-4711")], self.repo)
        self.assertEqual(res.returncode, 0, res.stderr)
        self._old = os.environ.get("BACH_WORKTREES_DIR")
        os.environ["BACH_WORKTREES_DIR"] = str(self.wt_root)
        self.db_path = self.tmp / "leer.db"

    def tearDown(self):
        if self._old is None:
            os.environ.pop("BACH_WORKTREES_DIR", None)
        else:
            os.environ["BACH_WORKTREES_DIR"] = self._old
        self._tmp.cleanup()

    def test_commit_bei_offenen_aenderungen(self):
        from hub import worker_git
        wt = self.wt_root / "task-4711"
        (wt / "neu.txt").write_text("neu\n", encoding="utf-8")
        result = worker_git.auto_commit_task_worktree(4711, db_path=self.db_path)
        self.assertTrue(result.get("committed"), result)
        self.assertTrue(result.get("commit"))
        log = _git(["log", "--oneline", "-1"], wt)
        self.assertIn("Auto-Commit", log.stdout)
        self.assertEqual(_git(["status", "--porcelain"], wt).stdout.strip(), "")

    def test_kein_worktree(self):
        from hub import worker_git
        result = worker_git.auto_commit_task_worktree(9999, db_path=self.db_path)
        self.assertFalse(result.get("committed"), result)
        self.assertEqual(result.get("reason"), "kein-worktree")

    def test_keine_aenderungen(self):
        from hub import worker_git
        wt = self.wt_root / "task-4711"
        before = _git(["rev-parse", "HEAD"], wt).stdout
        result = worker_git.auto_commit_task_worktree(4711, db_path=self.db_path)
        self.assertFalse(result.get("committed"), result)
        self.assertEqual(result.get("reason"), "keine-änderungen")
        self.assertEqual(_git(["rev-parse", "HEAD"], wt).stdout, before)

    def test_ungueltige_task_id(self):
        from hub import worker_git
        result = worker_git.auto_commit_task_worktree("abc")
        self.assertFalse(result.get("committed"), result)
        self.assertEqual(result.get("reason"), "ungültige-task-id")


if __name__ == "__main__":
    unittest.main()