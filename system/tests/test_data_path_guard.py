# -*- coding: utf-8 -*-
"""SEC-bach-rescue-tag-2026-11-22: runtime data must not reach commits or pushes.

Covers the three layers of the fix: .gitignore, the worker staging in
hub/worker_git.py (no ``git add -A`` any more) and the CI guard script.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "system" / "hub" / "data_path_guard.py"

# One example per path pattern of the leaked tag (BEFUND.md, sections 1 and 5).
LEAKED_EXAMPLES = [
    "data/bach.db",
    r"system/C:\_Local_DEV\CREDENTIALS\umbruchmail\mails.db",
    "system/data/abo_export.csv",
    "exports/AUTONOME_RUNDENBERICHT_1.md",
    "system/exports/EXECUTIVE_SUMMARY_24H_BRIDGE_FACKEL_1.md",
    "data/temp/msg_dump_1033_1197.txt",
    "system/scripts/search_telegram_ids_output.txt",
    "system/scripts/out2.txt",
    "system/data/inbox_config.json",
    "system/data/inbox_folders.txt",
    "system/data/slots_config.json.pre-1711-20260928T012124Z",
    "system/staging/1672-onesync-deschedule/backup/onedrive_pinner.py.bak",
    "system/gui/server.py.bak.20261001",
    "TO-DECIDE-USER.txt",
    "exports2/db_dump.sql",
    "system/data/telegram_dump",
    "system/.pytest_tmp/run1/out.txt",
]

LEGIT_TRACKED = [
    "system/hub/worker_git.py",
    "system/data/skill_sources.json",
    "system/data/config/delivery_preferences.json",
    "system/exports/translations/locales/de.json",
    "system/exports/.gitkeep",
    "system/logs/daily/2026-02-21.md",
    "system/tools/inbox_watcher.py",
    "system/docs/help/inbox_en.txt",
    # Code with "dump" in its name is not data (ext-merge note on #770).
    "system/hub/json_dump.py",
    "system/tools/dump_helpers.ts",
    "docs/how-to-dump.md",
]


def _git(cwd, *args, check=True):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=check, timeout=30)


@pytest.mark.parametrize("path", LEAKED_EXAMPLES)
def test_gitignore_excludes_every_leaked_path_pattern(path):
    res = _git(REPO_ROOT, "check-ignore", "--no-index", "-q", path, check=False)
    assert res.returncode == 0, f".gitignore lässt {path!r} durch"


@pytest.mark.parametrize("path", LEAKED_EXAMPLES)
def test_guard_refuses_every_leaked_path(path):
    from hub.data_path_guard import is_data_path
    assert is_data_path(path)


@pytest.mark.parametrize("path", LEGIT_TRACKED)
def test_guard_keeps_tracked_code_and_release_files(path):
    from hub.data_path_guard import is_data_path
    assert not is_data_path(path)


def test_no_tracked_file_trips_the_guard():
    from hub.data_path_guard import data_paths
    tracked = _git(REPO_ROOT, "ls-files", "-z").stdout.split("\x00")
    assert data_paths(tracked) == []


@pytest.fixture
def task_tree(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "base.txt").write_text("basis\n", encoding="utf-8")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-q", "-m", "basis")
    root = tmp_path / "worktrees"
    root.mkdir()
    _git(repo, "worktree", "add", "-q", "-b", "bach-task/4711", str(root / "task-4711"))
    monkeypatch.setenv("BACH_WORKTREES_DIR", str(root))
    return root / "task-4711", tmp_path / "leer.db"


def test_auto_commit_refuses_data_paths_and_commits_nothing(task_tree):
    from hub import worker_git
    wt, db = task_tree
    (wt / "fix.py").write_text("x = 1\n", encoding="utf-8")
    (wt / "data" / "temp").mkdir(parents=True)
    (wt / "data" / "temp" / "msg_dump_1.txt").write_text("chat\n", encoding="utf-8")
    before = _git(wt, "rev-parse", "HEAD").stdout
    result = worker_git.auto_commit_task_worktree(4711, db_path=db)
    assert result.get("committed") is False and "Datenpfade" in result.get("error", ""), result
    assert _git(wt, "rev-parse", "HEAD").stdout == before
    assert _git(wt, "diff", "--cached", "--name-only").stdout == ""


def test_auto_commit_stages_task_paths_including_deletions(task_tree):
    from hub import worker_git
    wt, db = task_tree
    (wt / "base.txt").unlink()
    (wt / "sub").mkdir()
    (wt / "sub" / "neu [1].py").write_text("y = 2\n", encoding="utf-8")
    result = worker_git.auto_commit_task_worktree(4711, db_path=db)
    assert result.get("committed") is True, result
    assert _git(wt, "status", "--porcelain").stdout.strip() == ""
    assert _git(wt, "ls-files").stdout.splitlines() == ["sub/neu [1].py"]


def test_pre_staged_data_file_is_refused_before_commit(task_tree):
    from hub import worker_git
    wt, db = task_tree
    (wt / "TO-DECIDE-USER.txt").write_text("privat\n", encoding="utf-8")
    _git(wt, "add", "TO-DECIDE-USER.txt")
    (wt / "TO-DECIDE-USER.txt").unlink()  # only in the index now
    before = _git(wt, "rev-parse", "HEAD").stdout
    result = worker_git.auto_commit_task_worktree(4711, db_path=db)
    assert result.get("committed") is False and "Datenpfade" in result.get("error", ""), result
    assert _git(wt, "rev-parse", "HEAD").stdout == before


def test_worker_git_has_no_blanket_add_any_more():
    source = (REPO_ROOT / "system" / "hub" / "worker_git.py").read_text(encoding="utf-8")
    assert '"add", "-A"' not in source and '"add", "."' not in source


def _run_guard(cwd, *args):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, str(GUARD), *args], cwd=str(cwd), capture_output=True,
                          text=True, check=False, timeout=60, env=env)


def test_ci_guard_fails_on_data_in_diff_and_passes_deletions(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    (repo / "a.py").write_text("a\n", encoding="utf-8")
    (repo / "x.bak").write_text("alt\n", encoding="utf-8")
    _git(repo, "add", "a.py", "x.bak")
    _git(repo, "commit", "-q", "-m", "basis")
    _git(repo, "checkout", "-q", "-b", "feature")
    _git(repo, "rm", "-q", "x.bak")  # removing a leaked file is allowed
    (repo / "b.py").write_text("b\n", encoding="utf-8")
    _git(repo, "add", "b.py")
    _git(repo, "commit", "-q", "-m", "ok")
    assert _run_guard(repo, "--base", "main").returncode == 0
    (repo / "system" / "data").mkdir(parents=True)
    (repo / "system" / "data" / "abo_export.csv").write_text("anbieter;betrag\n", encoding="utf-8")
    _git(repo, "add", "-f", "system/data/abo_export.csv")
    assert _run_guard(repo, "--staged").returncode == 1
    _git(repo, "commit", "-q", "-m", "leak")
    res = _run_guard(repo, "--base", "main")
    assert res.returncode == 1 and "abo_export.csv" in res.stderr
    assert _run_guard(repo, "--base", "does-not-exist").returncode == 2
