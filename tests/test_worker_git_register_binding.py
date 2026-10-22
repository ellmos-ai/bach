import subprocess
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest

from hub import worker_git
from hub._services import project_source_register as register

URL = "https://example.invalid/team/repo.git"
TASK_ID = 4242


def _git(repo, *args):
    proc = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    return proc


def _make_repo(parent, *, name="repo", url=URL):
    repo = parent / name
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "bot@example.invalid")
    _git(repo, "config", "user.name", "Bot")
    _git(repo, "remote", "add", "origin", url)
    _git(repo, "commit", "--allow-empty", "-m", "init")
    return repo


@pytest.fixture(autouse=True)
def _register_db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        register, "_DB_PATH_OVERRIDE", str(tmp_path / "register.sqlite3")
    )


@pytest.fixture
def repo(tmp_path):
    return _make_repo(tmp_path)


def test_start_task_worktree_requires_private_binding():
    with pytest.raises(RuntimeError, match="Private Taskbindung fehlt"):
        worker_git.start_task_worktree(
            TASK_ID, worker_task_binding=None, task_code_capability=False
        )


def test_start_task_worktree_requires_bool_task_code_capability(repo):
    binding = SimpleNamespace(repo_key="repo", register_revision=1)
    with pytest.raises(
        RuntimeError, match="Task-Codefähigkeit ist nicht privat gebunden"
    ):
        worker_git.start_task_worktree(
            TASK_ID, worker_task_binding=binding, task_code_capability="ja"
        )


def test_start_task_worktree_requires_binding_repo_key(repo):
    binding = SimpleNamespace(repo_key=None, register_revision=1)
    with pytest.raises(
        RuntimeError, match="Taskbindung ohne Projektquellen-Registereintrag"
    ):
        worker_git.start_task_worktree(TASK_ID, worker_task_binding=binding)


def test_start_task_worktree_requires_binding_register_revision(repo):
    binding = {"repo_key": "repo", "register_revision": None}
    assert isinstance(binding, Mapping)
    with pytest.raises(
        RuntimeError, match="Taskbindung ohne Projektquellen-Registereintrag"
    ):
        worker_git.start_task_worktree(TASK_ID, worker_task_binding=binding)


def test_start_task_worktree_capability_only_for_bach_repo(repo):
    register.add_entry(actor="user", repo_key="ellmos-chat", checkout_path=repo)
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    binding = SimpleNamespace(
        repo_key="ellmos-chat", register_revision=1, pinned_sha=head
    )
    with pytest.raises(
        RuntimeError, match="Task-Codefähigkeit nur für das BACH-Repository erlaubt"
    ):
        worker_git.start_task_worktree(
            TASK_ID,
            worker_task_binding=binding,
            task_code_capability=True,
            base_branch="main",
        )


def test_start_task_worktree_rejects_divergent_repo_root(tmp_path):
    repo_a = _make_repo(tmp_path, name="repo-a")
    repo_b = _make_repo(tmp_path, name="repo-b")
    register.add_entry(actor="user", repo_key="team", checkout_path=repo_a)
    head = _git(repo_a, "rev-parse", "HEAD").stdout.strip()
    binding = SimpleNamespace(repo_key="team", register_revision=1, pinned_sha=head)
    with pytest.raises(
        RuntimeError, match="repo_root weicht vom registrierten Projekt-Checkout ab"
    ):
        worker_git.start_task_worktree(
            TASK_ID, worker_task_binding=binding, repo_root=repo_b
        )