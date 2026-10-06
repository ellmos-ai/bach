"""Tests für worker_git.py und den Schutz des Live-Ordners (Task #1361)."""
from __future__ import annotations

import sqlite3
import subprocess

import pytest

from hub._services.chat.chat_runtime import TOOLS_FULL, exec_tool
from hub.task_audit import apply_task_field_changes
from hub.worker_git import (
    cleanup_task_worktree,
    is_live_path_blocked,
    record_task_file_change,
    scan_for_secrets,
    start_task_worktree,
    task_has_file_changes,
)


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

        # Cleanup
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
