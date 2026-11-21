"""Tests für worker_git.py und den Schutz des Live-Ordners (Task #1361)."""
from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from hub._services.chat.chat_runtime import TOOLS_FULL, exec_tool
from hub.task_audit import apply_task_field_changes
from hub import worker_git
from hub.worker_git import (
    check_git_diff,
    cleanup_task_worktree,
    is_live_path_blocked,
    record_task_file_change,
    scan_for_secrets,
    start_task_worktree,
    task_has_file_changes,
)


@pytest.mark.parametrize("allow", [True, False])
def test_macos_source_provisioning_stages_outside_live_root(tmp_path, monkeypatch, allow):
    from hub._services.chat import worker_repo_registry as registry

    home = tmp_path.resolve()
    sha = "a" * 40
    repo_id = "ellmos-ai/bach"
    origin = "https://github.com/" + repo_id
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(worker_git, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(registry, "load_registry", lambda: {"repositories": {
        repo_id: {"origin": origin, "default_branch": "main"}
    }})
    monkeypatch.setattr(worker_git, "_trusted_commit_identity", lambda repo: None)
    monkeypatch.setattr(worker_git, "_public_default_branch_metadata", lambda *a: {"source_sha": sha})
    monkeypatch.setattr(worker_git, "_public_main_source", lambda *a: {"source_sha": sha, "origin": origin})
    monkeypatch.setattr(worker_git, "_seed_staged_commit_identity", lambda *a: None)
    monkeypatch.setattr(worker_git, "_require_source_commit_identity", lambda *a: None)

    def clone(argv, **kwargs):
        assert argv[:2] == ["git", "clone"]
        stage = Path(argv[-1])
        assert stage.parent.parent == home
        assert home / ".bach" not in stage.parents
        (stage / "system").mkdir(parents=True)
        return SimpleNamespace(returncode=0)

    def guard(root, stage, missing_parents):
        assert root == home / ".bach"
        assert (stage / "system").is_dir()
        assert missing_parents == 3
        if not allow:
            raise RuntimeError("Sperrscan mit Verzeichnisreserve nicht bestätigt")

    monkeypatch.setattr(worker_git.subprocess, "run", clone)
    monkeypatch.setattr(worker_git, "_guard_public_source_capacity", guard)
    if allow:
        result = worker_git.provision_public_source_clone(repo_id)
        assert result["created"] is True
        assert (Path(result["path"]) / "system").is_dir()
        assert worker_git.provision_public_source_clone(repo_id)["created"] is False
    else:
        with pytest.raises(RuntimeError, match="Verzeichnisreserve"):
            worker_git.provision_public_source_clone(repo_id)
        assert not (home / ".bach" / "task-repo-sources").exists()
    assert not list(home.glob(".bach-source-*"))


@pytest.mark.parametrize("complete", [True, False])
def test_public_source_capacity_only_reduces_scanner_limit(tmp_path, monkeypatch, complete):
    from hub._services.chat import worker_write_guard as guard

    root = tmp_path / ".bach"
    root.mkdir()
    stage = tmp_path / "staging" / "clone"
    (stage / "system" / "hub").mkdir(parents=True)
    (stage / ".git" / "objects" / "pack").mkdir(parents=True)
    scanner = tmp_path / "locktools" / "lock_scan.py"
    scanner.parent.mkdir()
    config = scanner.with_name("lock_roots.json")
    original = {"check_dir_max_descendants": 10, "twin_resolution": {"no_mirror_manifests": []}}
    config.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(guard, "_scanner_path", lambda: scanner)
    monkeypatch.setattr(guard, "_scan_locks", lambda path: {"descendants_complete": path == stage})

    def scan(argv, **kwargs):
        applied = Path(argv[argv.index("--roots-file") + 1])
        assert applied.parent == stage.parent
        assert json.loads(applied.read_text(encoding="utf-8")) == {**original, "check_dir_max_descendants": 5}
        return SimpleNamespace(returncode=0 if complete else 1, stdout=json.dumps({
            "checked": str(root), "descendants_complete": complete, "twin_status": "not-applicable",
            "locks": [], "hook_guards": [],
        }))

    monkeypatch.setattr(worker_git.subprocess, "run", scan)
    if complete:
        worker_git._guard_public_source_capacity(root, stage, 2)
    else:
        with pytest.raises(RuntimeError, match="Verzeichnisreserve"):
            worker_git._guard_public_source_capacity(root, stage, 2)
    assert json.loads(config.read_text(encoding="utf-8")) == original


class TestLivePathProtection:
    def test_live_path_blocked_rejects_paths_under_live_repo(self, tmp_path, monkeypatch):
        fake_live = tmp_path / "services" / "bach"
        fake_worktrees = tmp_path / "services" / "bach-worktrees"
        fake_live.mkdir(parents=True)
        fake_worktrees.mkdir(parents=True)

        monkeypatch.setenv("BACH_ROOT", str(fake_live))
        monkeypatch.setenv("BACH_WORKTREES_DIR", str(fake_worktrees))

        # Pfad unter dem Live-Repo -> blockiert
        blocked = is_live_path_blocked(fake_live / "system" / "test.py")
        assert blocked == "Nutze start_task_worktree()"

        # Pfad unter worktrees -> erlaubt
        assert is_live_path_blocked(fake_worktrees / "task-100" / "system" / "test.py") is None

        # Pfad völlig außerhalb -> erlaubt
        assert is_live_path_blocked(tmp_path / "other" / "file.txt") is None

    def test_live_path_override_allows_writes(self, tmp_path, monkeypatch):
        fake_live = tmp_path / "services" / "bach"
        fake_live.mkdir(parents=True)
        monkeypatch.setenv("BACH_ROOT", str(fake_live))
        monkeypatch.setenv("BACH_ALLOW_LIVE_WRITE", "1")

        assert is_live_path_blocked(fake_live / "system" / "test.py") is None

    def test_exec_tool_edit_file_blocks_live_repo(self, tmp_path, monkeypatch):
        fake_live = tmp_path / "services" / "bach"
        fake_worktrees = tmp_path / "services" / "bach-worktrees"
        fake_live.mkdir(parents=True)
        fake_worktrees.mkdir(parents=True)
        test_file = fake_live / "system" / "file.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("orig", encoding="utf-8")

        monkeypatch.setenv("BACH_ROOT", str(fake_live))
        monkeypatch.setenv("BACH_WORKTREES_DIR", str(fake_worktrees))

        res = exec_tool("edit_file", {"path": str(test_file), "old_text": "orig", "new_text": "mod"}, mode="full")
        assert res == "Nutze start_task_worktree()"

    def test_exec_tool_write_file_blocks_live_repo(self, tmp_path, monkeypatch):
        fake_live = tmp_path / "services" / "bach"
        fake_worktrees = tmp_path / "services" / "bach-worktrees"
        fake_live.mkdir(parents=True)
        fake_worktrees.mkdir(parents=True)

        monkeypatch.setenv("BACH_ROOT", str(fake_live))
        monkeypatch.setenv("BACH_WORKTREES_DIR", str(fake_worktrees))

        res = exec_tool("write_file", {"path": str(fake_live / "system" / "evil.py"), "content": "x = 1"}, mode="full")
        assert res == "Nutze start_task_worktree()"

    def test_exec_tool_execute_command_blocks_git_mutation_in_live_repo(self, tmp_path, monkeypatch):
        fake_live = tmp_path / "services" / "bach"
        fake_worktrees = tmp_path / "services" / "bach-worktrees"
        fake_live.mkdir(parents=True)
        fake_worktrees.mkdir(parents=True)

        monkeypatch.setenv("BACH_ROOT", str(fake_live))
        monkeypatch.setenv("BACH_WORKTREES_DIR", str(fake_worktrees))

        res = exec_tool("execute_command", {"command": "git commit -m 'direct to main'", "cwd": str(fake_live)}, mode="full")
        assert res == "Nutze start_task_worktree()"


class TestWorktreeLifecycle:
    def test_start_task_worktree_and_cleanup(self, tmp_path, monkeypatch):
        fake_repo = tmp_path / "repo"
        fake_repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=str(fake_repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(fake_repo), check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(fake_repo), check=True)
        (fake_repo / "README.md").write_text("# Hello", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(fake_repo), check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(fake_repo), check=True)

        fake_worktrees = tmp_path / "worktrees"
        monkeypatch.setenv("BACH_WORKTREES_DIR", str(fake_worktrees))

        wt = start_task_worktree(42, base_branch="main", repo_root=fake_repo)
        assert wt.exists()
        assert (wt / "README.md").exists()
        assert wt == fake_worktrees / "task-42"

        # Worktree erneut aufrufen liefert denselben Pfad
        wt2 = start_task_worktree(42, base_branch="main", repo_root=fake_repo)
        assert wt2 == wt

        # Cleanup refuses to discard a dirty task tree.
        from hub._services.chat import worker_write_guard
        monkeypatch.setattr(worker_write_guard, "_fresh_locks", lambda *a, **k: None)
        dirty = wt / "uncommitted.txt"
        dirty.write_text("preserve me", encoding="utf-8")
        assert cleanup_task_worktree(42, repo_root=fake_repo) is False
        assert dirty.read_text(encoding="utf-8") == "preserve me"
        dirty.unlink()
        ok = cleanup_task_worktree(42, repo_root=fake_repo)
        assert ok is True
        assert not wt.exists()


class TestSecretsAndDiffScan:
    def test_scan_for_secrets_detects_api_keys(self, tmp_path):
        fake_repo = tmp_path / "repo"
        fake_repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(fake_repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(fake_repo), check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(fake_repo), check=True)
        (fake_repo / "clean.txt").write_text("no secrets", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(fake_repo), check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(fake_repo), check=True)

        assert scan_for_secrets(fake_repo) == []

        # Secret einfügen
        (fake_repo / "clean.txt").write_text("api_key = 'sk-123456789012345678901234'", encoding="utf-8")
        findings = scan_for_secrets(fake_repo)
        assert len(findings) > 0

    def test_scan_and_diff_gate_include_untracked_files(self, tmp_path):
        fake_repo = tmp_path / "repo"
        fake_repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=str(fake_repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(fake_repo), check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(fake_repo), check=True)
        (fake_repo / "clean.txt").write_text("clean\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(fake_repo), check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(fake_repo), check=True, capture_output=True)
        (fake_repo / "new_untracked.py").write_text(
            "value = 'sk-000000000000000000000000'  \n", encoding="utf-8")
        findings = scan_for_secrets(fake_repo)
        assert findings and "Muster erkannt" in findings[0]
        whitespace = check_git_diff(fake_repo)
        assert any("trailing whitespace" in finding for finding in whitespace)

    def test_secret_and_diff_git_read_errors_fail_closed(self, tmp_path, monkeypatch):
        def failed_git_read(*args, **kwargs):
            return type("Result", (), {"returncode": 128, "stdout": b"", "stderr": b"synthetic"})()
        monkeypatch.setattr(worker_git.subprocess, "run", failed_git_read)
        assert scan_for_secrets(tmp_path)
        assert check_git_diff(tmp_path)


class TestTaskCompletionGuard:
    @pytest.fixture
    def test_db(self, tmp_path):
        db_file = tmp_path / "test.db"
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'pending',
                due_date TEXT,
                claimed_by TEXT,
                claimed_at TEXT,
                started_at TEXT,
                completed_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE task_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                field_changed TEXT,
                old_value TEXT,
                new_value TEXT,
                changed_by TEXT DEFAULT 'user',
                changed_at TEXT NOT NULL
            );
        """)
        conn.commit()
        return conn, db_file

    def test_task_without_code_changes_can_be_completed(self, test_db):
        conn, _ = test_db
        conn.execute("INSERT INTO tasks (id, title, status) VALUES (1, 'Dokumentation schreiben', 'in_progress')")
        conn.commit()

        row = dict(conn.execute("SELECT * FROM tasks WHERE id = 1").fetchone())
        # Ohne Codeänderungen -> darf completed werden
        ok = apply_task_field_changes(conn, 1, row, {"status": "done"}, changed_by="test")
        assert ok is True
        row_after = dict(conn.execute("SELECT * FROM tasks WHERE id = 1").fetchone())
        assert row_after["status"] == "done"

    def test_task_with_code_changes_requires_pr_url(self, test_db):
        conn, db_path = test_db
        conn.execute("INSERT INTO tasks (id, title, status) VALUES (2, 'Feature implementieren', 'in_progress')")
        conn.commit()

        # Registriere Dateiänderung
        record_task_file_change(2, "system/hub/core.py", db_path=db_path)
        assert task_has_file_changes(2, conn) is True

        row = dict(conn.execute("SELECT * FROM tasks WHERE id = 2").fetchone())

        # Versuch auf done zu setzen ohne PR -> schlägt fehl
        with pytest.raises(ValueError, match="hat Codeänderungen.*eingetragenem PR"):
            apply_task_field_changes(conn, 2, row, {"status": "done"}, changed_by="test")

        # Mit eingetragener PR-URL -> erfolgreich!
        row["description"] = "PR: https://github.com/ellmos-ai/bach/pull/999"
        ok = apply_task_field_changes(conn, 2, row, {"status": "done", "description": row["description"]}, changed_by="test")
        assert ok is True
        row_after = dict(conn.execute("SELECT * FROM tasks WHERE id = 2").fetchone())
        assert row_after["status"] == "done"


class TestWorkerToolsExposure:
    def test_worker_git_tools_present_in_tools_full(self):
        tool_names = [t["function"]["name"] for t in TOOLS_FULL]
        assert "start_task_worktree" in tool_names
        assert "finish_task" in tool_names
        assert "cleanup_task_worktree" in tool_names
