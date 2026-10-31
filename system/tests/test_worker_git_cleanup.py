# -*- coding: utf-8 -*-
"""Tests für das sichere Aufräumen abgeschlossener Task-Worktrees und GC (Task #2227)."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import subprocess

import pytest

from hub.worker_git import (
    cleanup_completed_task_worktree,
    cleanup_task_worktree,
    gc_completed_task_worktrees,
    inspect_task_worktree_cleanup,
    start_task_worktree,
)


class TestCompletedWorktreeCleanupAndGC:
    @staticmethod
    def _init_repo(tmp_path: Path) -> tuple[Path, Path]:
        fake_repo = tmp_path / "repo"
        fake_repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=str(fake_repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(fake_repo), check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(fake_repo), check=True)
        (fake_repo / "README.md").write_text("# Hello\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(fake_repo), check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(fake_repo), check=True, capture_output=True)
        main_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(fake_repo), check=True, capture_output=True, text=True
        ).stdout.strip()
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/main", main_sha],
            cwd=str(fake_repo), check=True, capture_output=True,
        )
        fake_worktrees = tmp_path / "worktrees"
        fake_worktrees.mkdir()
        return fake_repo, fake_worktrees

    @staticmethod
    def _init_db(tmp_path: Path):
        db_file = tmp_path / "cleanup_test.db"
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'pending',
                claimed_by TEXT,
                claim_id TEXT,
                claim_fence INTEGER DEFAULT 1
            );
        """)
        conn.commit()
        return conn, db_file

    @staticmethod
    def _head_oid(worktree: Path) -> str:
        return subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD^{commit}"],
            cwd=str(worktree), check=True, capture_output=True, text=True,
        ).stdout.strip()

    @staticmethod
    def _stub_read_result(monkeypatch, mapping: dict[int, dict]):
        from hub._services import task_result_service
        monkeypatch.setattr(
            task_result_service,
            "read_result",
            lambda conn, tid, **kw: mapping.get(
                int(tid),
                {"schema": "bach.task-result-readback.v1", "task_id": int(tid), "status": "done", "result": None},
            ),
        )

    @staticmethod
    def _accepted_readback(task_id: int, head_oid: str, *, accepted: bool = True, scope_avail: str = "recorded") -> dict:
        return {
            "schema": "bach.task-result-readback.v1",
            "task_id": task_id,
            "status": "done",
            "verified": True,
            "result": {
                "schema": "bach.worker-result.v1",
                "result_id": 100 + task_id,
                "task_id": task_id,
                "accepted": accepted,
                "reason": "accepted" if accepted else "awaiting_review",
                "scope": {
                    "schema": "bach.worker-scope-evidence.v1",
                    "availability": scope_avail,
                    "reason": "recorded" if scope_avail in {"recorded", "available"} else "scope_not_recorded",
                    "snapshot": {
                        "task_id": task_id,
                        "branch": f"refs/heads/bach-task/{task_id}",
                        "head_oid": head_oid,
                    },
                },
            },
        }

    def test_rejects_open_review_active_lease_and_whitelist(self, tmp_path, monkeypatch):
        from hub._services.chat import worker_write_guard
        monkeypatch.setattr(worker_write_guard, "_fresh_locks", lambda *a, **k: None)
        fake_repo, fake_worktrees = self._init_repo(tmp_path)
        monkeypatch.setenv("BACH_WORKTREES_DIR", str(fake_worktrees))
        conn, db_file = self._init_db(tmp_path)

        for tid, status, claim_id in [
            (101, "review", None),
            (102, "in_progress", None),
            (103, "done", "lease-secret-103"),
            (104, "done", None),
        ]:
            start_task_worktree(tid, base_branch="main", repo_root=fake_repo)
            conn.execute(
                "INSERT INTO tasks (id, title, status, claim_id) VALUES (?, ?, ?, ?)",
                (tid, f"Task {tid}", status, claim_id),
            )
        conn.commit()
        conn.close()

        r_review = cleanup_completed_task_worktree(101, db_path=db_file, repo_root=fake_repo, worktrees_dir=fake_worktrees)
        assert r_review["eligible"] is False and r_review["reason"] == "status_review"
        assert (fake_worktrees / "task-101").exists()

        r_prog = cleanup_completed_task_worktree(102, db_path=db_file, repo_root=fake_repo, worktrees_dir=fake_worktrees)
        assert r_prog["eligible"] is False and r_prog["reason"] == "status_in_progress"
        assert (fake_worktrees / "task-102").exists()

        r_lease = cleanup_completed_task_worktree(103, db_path=db_file, repo_root=fake_repo, worktrees_dir=fake_worktrees)
        assert r_lease["eligible"] is False and r_lease["reason"] == "active_lease"
        assert (fake_worktrees / "task-103").exists()

        r_white = cleanup_completed_task_worktree(
            104, db_path=db_file, repo_root=fake_repo, worktrees_dir=fake_worktrees, whitelist_task_ids={104}
        )
        assert r_white["eligible"] is False and r_white["reason"] == "whitelisted"
        assert (fake_worktrees / "task-104").exists()

    def test_rejects_done_without_accepted_result_or_scope_evidence(self, tmp_path, monkeypatch):
        from hub._services.chat import worker_write_guard
        monkeypatch.setattr(worker_write_guard, "_fresh_locks", lambda *a, **k: None)
        fake_repo, fake_worktrees = self._init_repo(tmp_path)
        monkeypatch.setenv("BACH_WORKTREES_DIR", str(fake_worktrees))
        conn, db_file = self._init_db(tmp_path)

        wt_no_acc = start_task_worktree(201, base_branch="main", repo_root=fake_repo)
        wt_no_scope = start_task_worktree(202, base_branch="main", repo_root=fake_repo)
        conn.execute("INSERT INTO tasks (id, title, status) VALUES (201, 'No Acceptance', 'done')")
        conn.execute("INSERT INTO tasks (id, title, status) VALUES (202, 'No Scope', 'done')")
        conn.commit()
        conn.close()

        self._stub_read_result(monkeypatch, {
            201: self._accepted_readback(201, self._head_oid(wt_no_acc), accepted=False, scope_avail="recorded"),
            202: self._accepted_readback(202, self._head_oid(wt_no_scope), accepted=True, scope_avail="unavailable"),
        })

        res_201 = cleanup_completed_task_worktree(201, db_path=db_file, repo_root=fake_repo, worktrees_dir=fake_worktrees)
        assert res_201["eligible"] is False and res_201["reason"] == "missing_result_acceptance"
        assert wt_no_acc.exists()

        res_202 = cleanup_completed_task_worktree(202, db_path=db_file, repo_root=fake_repo, worktrees_dir=fake_worktrees)
        assert res_202["eligible"] is False and res_202["reason"] == "missing_scope_evidence"
        assert wt_no_scope.exists()

    def test_rejects_dirty_tree_unpushed_commits_and_scope_mismatch(self, tmp_path, monkeypatch):
        from hub._services.chat import worker_write_guard
        monkeypatch.setattr(worker_write_guard, "_fresh_locks", lambda *a, **k: None)
        fake_repo, fake_worktrees = self._init_repo(tmp_path)
        monkeypatch.setenv("BACH_WORKTREES_DIR", str(fake_worktrees))
        conn, db_file = self._init_db(tmp_path)

        wt_dirty = start_task_worktree(301, base_branch="main", repo_root=fake_repo)
        (wt_dirty / "dirty.txt").write_text("untracked\n", encoding="utf-8")

        wt_unpushed = start_task_worktree(302, base_branch="main", repo_root=fake_repo)
        (wt_unpushed / "local_only.txt").write_text("unpushed commit\n", encoding="utf-8")
        subprocess.run(["git", "add", "local_only.txt"], cwd=str(wt_unpushed), check=True)
        subprocess.run(["git", "commit", "-m", "Local unpushed"], cwd=str(wt_unpushed), check=True, capture_output=True)
        unpushed_head = self._head_oid(wt_unpushed)

        wt_mismatch = start_task_worktree(303, base_branch="main", repo_root=fake_repo)

        conn.execute("INSERT INTO tasks (id, title, status) VALUES (301, 'Dirty', 'done')")
        conn.execute("INSERT INTO tasks (id, title, status) VALUES (302, 'Unpushed', 'done')")
        conn.execute("INSERT INTO tasks (id, title, status) VALUES (303, 'Mismatch', 'done')")
        conn.commit()
        conn.close()

        self._stub_read_result(monkeypatch, {
            301: self._accepted_readback(301, self._head_oid(wt_dirty)),
            302: self._accepted_readback(302, unpushed_head),
            303: self._accepted_readback(303, "f" * 40),
        })

        res_301 = cleanup_completed_task_worktree(301, db_path=db_file, repo_root=fake_repo, worktrees_dir=fake_worktrees)
        assert res_301["eligible"] is False and res_301["reason"] == "dirty_worktree"
        assert wt_dirty.exists()

        res_302 = cleanup_completed_task_worktree(302, db_path=db_file, repo_root=fake_repo, worktrees_dir=fake_worktrees)
        assert res_302["eligible"] is False and res_302["reason"] == "unpushed_commits"
        assert wt_unpushed.exists()
        assert cleanup_task_worktree(302, repo_root=fake_repo, worktrees_dir=fake_worktrees) is False
        assert wt_unpushed.exists()

        res_303 = inspect_task_worktree_cleanup(303, db_path=db_file, repo_root=fake_repo, worktrees_dir=fake_worktrees)
        assert res_303["eligible"] is False and res_303["reason"] == "scope_head_mismatch"

    def test_cleans_completed_task_and_runs_gc_with_whitelist(self, tmp_path, monkeypatch):
        from hub._services.chat import worker_write_guard
        monkeypatch.setattr(worker_write_guard, "_fresh_locks", lambda *a, **k: None)
        fake_repo, fake_worktrees = self._init_repo(tmp_path)
        monkeypatch.setenv("BACH_WORKTREES_DIR", str(fake_worktrees))
        conn, db_file = self._init_db(tmp_path)

        wt_ok = start_task_worktree(401, base_branch="main", repo_root=fake_repo)
        (wt_ok / "feature.txt").write_text("shipped\n", encoding="utf-8")
        subprocess.run(["git", "add", "feature.txt"], cwd=str(wt_ok), check=True)
        subprocess.run(["git", "commit", "-m", "Shipped"], cwd=str(wt_ok), check=True, capture_output=True)
        ok_head = self._head_oid(wt_ok)
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/bach-task/401", ok_head],
            cwd=str(fake_repo), check=True, capture_output=True,
        )

        wt_leased = start_task_worktree(402, base_branch="main", repo_root=fake_repo)
        leased_head = self._head_oid(wt_leased)

        conn.execute("INSERT INTO tasks (id, title, status, claim_id) VALUES (401, 'Done Task', 'done', NULL)")
        conn.execute("INSERT INTO tasks (id, title, status, claim_id) VALUES (402, 'Active Lease', 'in_progress', 'lease-402')")
        conn.commit()
        conn.close()

        self._stub_read_result(monkeypatch, {
            401: self._accepted_readback(401, ok_head),
            402: self._accepted_readback(402, leased_head),
        })

        dry = gc_completed_task_worktrees(
            db_path=db_file, repo_root=fake_repo, worktrees_dir=fake_worktrees, dry_run=True
        )
        assert dry["dry_run"] is True
        assert dry["eligible_task_ids"] == [401]
        assert dry["cleaned_task_ids"] == []
        assert 402 in dry["whitelist_task_ids"]
        assert wt_ok.exists() and wt_leased.exists()

        applied = gc_completed_task_worktrees(
            db_path=db_file, repo_root=fake_repo, worktrees_dir=fake_worktrees, dry_run=False, delete_branch=True
        )
        assert applied["dry_run"] is False
        assert applied["eligible_task_ids"] == [401]
        assert applied["cleaned_task_ids"] == [401]
        assert not wt_ok.exists()
        assert wt_leased.exists()

        branch_check = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", "refs/heads/bach-task/401"],
            cwd=str(fake_repo), capture_output=True, check=False,
        )
        assert branch_check.returncode != 0

    def test_historical_receipt_accepted_only_when_unmodified_after_acceptance(self, tmp_path, monkeypatch):
        import hashlib
        import json
        from hub._services.chat import worker_write_guard
        from hub._services.worker_scope_evidence import _digest as scope_digest

        monkeypatch.setattr(worker_write_guard, "_fresh_locks", lambda *a, **k: None)
        fake_repo, fake_worktrees = self._init_repo(tmp_path)
        monkeypatch.setenv("BACH_WORKTREES_DIR", str(fake_worktrees))
        conn, db_file = self._init_db(tmp_path)
        conn.executescript("""
            CREATE TABLE task_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                field_changed TEXT,
                old_value TEXT,
                new_value TEXT,
                changed_by TEXT,
                changed_at TEXT
            );
            CREATE TABLE worker_task_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                fence INTEGER NOT NULL,
                generation TEXT NOT NULL,
                task_version TEXT NOT NULL,
                result TEXT NOT NULL,
                result_sha256 TEXT NOT NULL,
                submitted_by TEXT NOT NULL,
                submitted_at TEXT NOT NULL,
                submission_event_id INTEGER,
                accepted_by TEXT,
                accepted_at TEXT,
                accepted_status_event_id INTEGER,
                acceptance_event_id INTEGER
            );
            CREATE TABLE worker_scope_evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                result_id INTEGER NOT NULL UNIQUE,
                fence INTEGER NOT NULL,
                generation TEXT NOT NULL,
                task_version TEXT NOT NULL,
                submission_revision TEXT NOT NULL,
                receipt TEXT NOT NULL,
                receipt_sha256 TEXT NOT NULL,
                event_id INTEGER NOT NULL,
                captured_at TEXT NOT NULL
            );
        """)

        wt_hist = start_task_worktree(501, base_branch="main", repo_root=fake_repo)
        head_501 = self._head_oid(wt_hist)
        tree_501 = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=str(wt_hist), check=True, capture_output=True, text=True
        ).stdout.strip()

        old_ver = "a" * 64
        res_text = "Vollständiger Ergebnisbericht für Task 501."
        res_sha = hashlib.sha256(res_text.encode("utf-8")).hexdigest()
        sub_rev = "sha256:" + "b" * 64

        conn.execute(
            "INSERT INTO tasks (id, title, status, claim_fence) VALUES (501, 'Hist Task', 'done', 2)"
        )
        cur_sub = conn.execute(
            "INSERT INTO task_history (task_id, action, field_changed, new_value, changed_by, changed_at) "
            "VALUES (501, 'status_change', 'status', 'review', 'worker@mac', '2026-10-19T10:00:00')"
        )
        sub_status_ev = cur_sub.lastrowid
        cur_sc = conn.execute(
            "INSERT INTO task_history (task_id, action, field_changed, new_value, changed_by, changed_at) "
            "VALUES (501, 'worker_result_scope_capture', 'lease', '{}', 'native-scope-controller', '2026-10-19T10:00:01')"
        )
        scope_ev = cur_sc.lastrowid
        cur_st = conn.execute(
            "INSERT INTO task_history (task_id, action, field_changed, new_value, changed_by, changed_at) "
            "VALUES (501, 'status_change', 'status', 'done', 'native-worker-completion-policy', '2026-10-19T10:00:05')"
        )
        done_status_ev = cur_st.lastrowid
        acc_json = json.dumps({
            "result_id": 1,
            "result_sha256": res_sha,
            "task_version": old_ver,
            "status_revision": done_status_ev,
        })
        cur_acc = conn.execute(
            "INSERT INTO task_history (task_id, action, field_changed, new_value, changed_by, changed_at) "
            "VALUES (501, 'result_acceptance', 'lease', ?, 'native-worker-completion-policy', '2026-10-19T10:00:05')",
            (acc_json,),
        )
        acc_ev = cur_acc.lastrowid

        conn.execute(
            "INSERT INTO worker_task_results "
            "(id, task_id, fence, generation, task_version, result, result_sha256, submitted_by, submitted_at, "
            "submission_event_id, accepted_by, accepted_at, accepted_status_event_id, acceptance_event_id) "
            "VALUES (1, 501, 2, 'gen501', ?, ?, ?, 'worker@mac', '2026-10-19T10:00:00', ?, "
            "'native-worker-completion-policy', '2026-10-19T10:00:05', ?, ?)",
            (old_ver, res_text, res_sha, sub_status_ev, done_status_ev, acc_ev),
        )

        empty_sha = hashlib.sha256(b"").hexdigest()
        snap = {
            "schema": "bach.task-scope-snapshot.v1",
            "availability": "available",
            "task_id": 501,
            "repository": "ellmos-ai/bach",
            "origin": "https://github.com/ellmos-ai/bach",
            "branch": "refs/heads/bach-task/501",
            "head_oid": head_501,
            "tree_oid": tree_501,
            "repo_path_sha256": "1" * 64,
            "worktree_path_sha256": "2" * 64,
            "common_dir_sha256": "3" * 64,
            "source_pin": None,
            "clean_scope": "porcelain-v1-z-all-untracked-no-ignored",
            "status_sha256": empty_sha,
            "index_sha256": "4" * 64,
            "project_state_ref": scope_digest({
                "repository": "ellmos-ai/bach",
                "origin": "https://github.com/ellmos-ai/bach",
                "source_pin": None,
                "head_oid": head_501,
            }),
            "workspace_fingerprint": scope_digest({
                "worktree_path_sha256": "2" * 64,
                "common_dir_sha256": "3" * 64,
                "branch": "refs/heads/bach-task/501",
                "tree_oid": tree_501,
                "clean_scope": "porcelain-v1-z-all-untracked-no-ignored",
                "status_sha256": empty_sha,
                "index_sha256": "4" * 64,
            }),
        }
        receipt = {
            "schema": "bach.worker-scope-receipt.v1",
            "task_id": 501,
            "result_id": 1,
            "fence": 2,
            "generation": "gen501",
            "task_scope_version": old_ver,
            "result_sha256": res_sha,
            "submission_revision": sub_rev,
            "submission_event_id": sub_status_ev,
            "submitted_status_event_id": sub_status_ev,
            "snapshot": snap,
            "captured_at": "2026-10-19T10:00:01Z",
        }
        r_sha = scope_digest(receipt)
        conn.execute(
            "INSERT INTO worker_scope_evidence "
            "(task_id, result_id, fence, generation, task_version, submission_revision, receipt, receipt_sha256, event_id, captured_at) "
            "VALUES (501, 1, 2, 'gen501', ?, ?, ?, ?, ?, '2026-10-19T10:00:01Z')",
            (old_ver, sub_rev, json.dumps(receipt, sort_keys=True, separators=(",", ":")), r_sha, scope_ev),
        )
        conn.commit()

        # Simulate schema-induced task_content_changed in read_result
        self._stub_read_result(monkeypatch, {
            501: {
                "schema": "bach.task-result-readback.v1",
                "task_id": 501,
                "status": "done",
                "verified": True,
                "result": {
                    "schema": "bach.worker-result.v1",
                    "result_id": 1,
                    "task_id": 501,
                    "accepted": False,
                    "reason": "task_content_changed",
                },
            }
        })

        diag_ok = inspect_task_worktree_cleanup(501, db_path=db_file, repo_root=fake_repo, worktrees_dir=fake_worktrees)
        assert diag_ok["eligible"] is True

        # Now add a post-acceptance mutation event -> must fail closed!
        conn.execute(
            "INSERT INTO task_history (task_id, action, field_changed, new_value, changed_by, changed_at) "
            "VALUES (501, 'field_change', 'description', 'edited after done', 'user', '2026-10-20T00:00:00')"
        )
        conn.commit()
        conn.close()

        diag_after_edit = inspect_task_worktree_cleanup(
            501, db_path=db_file, repo_root=fake_repo, worktrees_dir=fake_worktrees
        )
        assert diag_after_edit["eligible"] is False
        assert diag_after_edit["reason"] == "missing_result_acceptance"
