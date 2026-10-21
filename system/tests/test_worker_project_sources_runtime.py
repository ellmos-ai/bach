"""Actual two-repository Git/TaskDB paths; provider metadata is a fixture."""
import json
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from hub import worker_git
from hub._services import worker_scope_evidence
from hub._services.chat import worker_project_sources as sources
from hub._services.chat import worker_write_guard as guard

from system.tests import test_worker_project_sources as source_fixtures

projects = source_fixtures.projects
git = source_fixtures.git
source_task = source_fixtures.source_task
_REAL_FRESH_LOCKS = guard._fresh_locks


@pytest.mark.parametrize("project", ["bach", "chat"])
def test_start_read_write_and_result_scope_use_same_repository(projects, tmp_path, project):
    client, binding, database = source_task(projects, tmp_path, project)
    records, _ = projects
    target = worker_git.start_task_worktree(1, worker_task_binding=binding,
                                            require_task_binding=True, task_code_capability=True)
    assert target == Path(records[project]["worktrees_root"]) / "task-1"
    started = guard.snapshot_task_start_scope(binding, task_root=target, source_pin_required=True)
    assert started["availability"] == "available", started
    assert started["project_source"]["repository"] == records[project]["repository"]
    read = guard.authorize_task_read(binding, "README.md", secret_check=lambda _: False)
    assert read.requested == target / "README.md"
    assert read.requested.read_text(encoding="utf-8").startswith(project)
    _, (changed,) = guard.authorize_mutation(binding, paths=("README.md",))
    changed.write_text(project + " updated fixture\n", encoding="utf-8")
    assert guard.snapshot_task_scope(1, binding=binding)["reason"] == "git_dirty"
    git(target, "add", "README.md")
    git(target, "commit", "-m", "fixture update")
    snapshot = guard.snapshot_task_scope(1, binding=binding)
    assert snapshot["availability"] == "available"
    assert snapshot["schema"] == "bach.task-scope-snapshot.v2"
    assert worker_scope_evidence._snapshot_valid(snapshot, 1)
    assert snapshot["repository"] == records[project]["repository"]
    assert snapshot["project_source"] == sources.project_for_binding(binding).public_binding()
    binding.execute_task_manage({"action": "submit_result", "task_id": 1,
                                "result": "Changed fixture README and checked its physical Git scope."})
    with sqlite3.connect(database) as conn:
        assert worker_scope_evidence.capture_scope_evidence(conn, binding)
    observed = client.task_result_snapshot(1)
    assert observed["status"] == "review" and not client.read(1).leased
    scope = observed["result"]["scope"]
    assert scope["availability"] == "available"
    assert scope["snapshot"] == snapshot
    assert observed["result"]["accepted"] is False


def test_identical_task_paths_in_another_repo_never_receive_writes(projects, tmp_path):
    _, binding, _ = source_task(projects, tmp_path)
    records, _ = projects
    chat = worker_git.start_task_worktree(1, worker_task_binding=binding, task_code_capability=True)
    other = Path(records["bach"]["worktrees_root"]) / "task-1"
    other.parent.mkdir()
    git(Path(records["bach"]["repo_root"]), "worktree", "add", str(other), "-b", "bach-task/1", "main")
    original = (other / "README.md").read_bytes()
    with pytest.raises((guard.WorkerWriteGuardError, sources.ProjectSourceError)):
        guard.authorize_mutation(binding, paths=(other / "README.md",))
    with pytest.raises(sources.ProjectSourceError):
        worker_git.start_task_worktree(1, repo_root=Path(records["bach"]["repo_root"]),
                                      worker_task_binding=binding, task_code_capability=True)
    assert (other / "README.md").read_bytes() == original
    assert guard.authorize_mutation(binding)[0] == chat


def test_result_projection_uses_recorded_source_not_current_bach_default(projects, tmp_path, monkeypatch):
    _, binding, _ = source_task(projects, tmp_path)
    target = worker_git.start_task_worktree(1, worker_task_binding=binding, task_code_capability=True)
    snapshot = guard.snapshot_task_scope(1, binding=binding)
    assert snapshot["availability"] == "available"
    monkeypatch.setenv("BACH_ROOT", projects[0]["bach"]["repo_root"])
    monkeypatch.setenv("BACH_WORKTREES_DIR", projects[0]["bach"]["worktrees_root"])
    repeated = guard.snapshot_task_scope(1, project_source=snapshot["project_source"])
    assert repeated == snapshot
    assert repeated["head_oid"] == git(target, "rev-parse", "HEAD")
    catalogue = json.loads(projects[1].read_text())
    catalogue["entries"]["chat"]["retired"] = True
    projects[1].write_text(json.dumps(catalogue), encoding="utf-8")
    assert guard.snapshot_task_scope(1, project_source=snapshot["project_source"])["availability"] == "unavailable"


def test_finish_push_and_pr_are_routed_to_the_same_project(projects, tmp_path, monkeypatch):
    client, binding, _ = source_task(projects, tmp_path)
    target = worker_git.start_task_worktree(1, worker_task_binding=binding, task_code_capability=True)
    (target / "README.md").write_text("chat changed fixture\n", encoding="utf-8")
    git(target, "config", "commit.gpgsign", "false")
    original_run = subprocess.run
    publication = []
    def isolated_publication(argv, **kwargs):
        if argv[:2] == ["git", "push"] or argv[:3] == ["gh", "pr", "create"]:
            publication.append((argv, Path(kwargs["cwd"])))
            return SimpleNamespace(returncode=0, stdout="https://github.com/ellmos-ai/ellmos-chat/pull/1\n",
                                   stderr="")
        return original_run(argv, **kwargs)
    monkeypatch.setattr(subprocess, "run", isolated_publication)
    result = worker_git.finish_task(1, "fixture change", worker_task_binding=binding,
                                   require_task_binding=True)
    assert result["success"], result
    assert len(publication) == 2
    assert all(cwd == target for _, cwd in publication)
    assert publication[1][0][publication[1][0].index("--base") + 1] == "main"
    assert client.task_snapshot(1)["status"] == "review" and not client.read(1).leased


def test_scope_preserves_host_line_endings_without_importing_host_filters(projects, tmp_path, monkeypatch):
    host_home = tmp_path / "scope-host"
    host_home.mkdir()
    (host_home / ".gitconfig").write_text(
        '[core]\n\tautocrlf = true\n[filter "unrelated"]\n\tclean = exit 47\n', encoding="utf-8")
    monkeypatch.setenv("HOME", str(host_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(host_home / "xdg"))
    _, binding, _ = source_task(projects, tmp_path)
    target = worker_git.start_task_worktree(1, worker_task_binding=binding, task_code_capability=True)
    assert b"\r\n" in (target / "README.md").read_bytes()
    snapshot = guard.snapshot_task_scope(1, binding=binding)
    assert snapshot["availability"] == "available", snapshot
    # A repository-local executable filter must still deny a clean-scope claim.
    git(target, "config", "filter.local.clean", "exit 48")
    assert guard.snapshot_task_scope(1, binding=binding)["reason"] == "git_unavailable"


@pytest.mark.parametrize("blocked", [None, "lock", "hook", "incomplete", "missing_complete", "missing_guards", "unknown_twin"])
def test_foreign_repository_keeps_native_lock_checks_without_bach_twin_requirement(
        projects, tmp_path, monkeypatch, blocked):
    _, binding, _ = source_task(projects, tmp_path)
    target = worker_git.start_task_worktree(1, worker_task_binding=binding, task_code_capability=True)
    scanner = tmp_path / "registered-project-scanner.py"
    scanner.write_text(
        'import json,sys\n'
        'p=sys.argv[sys.argv.index("--check-dir")+1]\n'
        'value={"checked":p,"twin_status":"not-applicable","descendants_complete":True,'
        '"locks":[],"hook_guards":[]}\n'
        + ('value["locks"]=[{"path":p,"scope":"foreign"}]\n' if blocked == "lock" else '')
        + ('value["hook_guards"]=[{"path":p}]\n' if blocked == "hook" else '')
        + ('value["descendants_complete"]=False\n' if blocked == "incomplete" else '')
        + ('del value["descendants_complete"]\n' if blocked == "missing_complete" else '')
        + ('del value["hook_guards"]\n' if blocked == "missing_guards" else '')
        + ('value["twin_status"]="unknown"\n' if blocked == "unknown_twin" else '')
        + 'print(json.dumps(value))\n', encoding="utf-8")
    monkeypatch.setattr(guard, "_scanner_path", lambda: scanner)
    monkeypatch.setattr(guard, "_fresh_locks", _REAL_FRESH_LOCKS)
    if blocked:
        with pytest.raises(guard.WorkerWriteGuardError):
            guard.authorize_mutation(binding, paths=("README.md",))
        return
    assert guard.authorize_start(binding, 1) == target
    assert guard.authorize_mutation(binding)[0] == target
    observed = guard.snapshot_task_scope(1, binding=binding)
    assert observed["availability"] == "available", observed
    # The same scanner result cannot silently relax the canonical BACH rule.
    with pytest.raises(guard.WorkerWriteGuardError):
        guard._fresh_locks(Path(projects[0]["bach"]["repo_root"]),
                           Path(projects[0]["bach"]["worktrees_root"]), None)
