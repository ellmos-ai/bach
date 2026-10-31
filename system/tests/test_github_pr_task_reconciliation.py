#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests fuer GitHub-PR-Kopplung (#2453): Merge -> done, Closed -> Korrektur (pending)."""

import sqlite3
from hub.worker_git import reconcile_github_pr_task_state


def _make_task_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            title TEXT,
            status TEXT,
            description TEXT,
            result TEXT,
            completed_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO tasks (id, title, status, description) VALUES (42, 'PR Task', 'review', 'Initiale Beschreibung')"
    )
    conn.commit()
    return conn


def test_merged_pr_completes_task_with_receipt():
    conn = _make_task_db()
    out = reconcile_github_pr_task_state(
        42,
        {
            "number": 515,
            "state": "MERGED",
            "merged": True,
            "merge_commit_sha": "abc1234def5678",
            "merged_by": "lukisch",
            "url": "https://github.com/ellmos-ai/bach/pull/515",
        },
        db_path=conn,
    )
    assert out["status"] == "done"
    assert out["action"] == "completed_on_merge"
    assert out["github_external_review"] is True
    row = conn.execute("SELECT status, result, completed_at FROM tasks WHERE id = 42").fetchone()
    assert row[0] == "done"
    assert "PR #515 merged" in row[1]
    assert "abc1234def5678" in row[1]
    assert "lukisch" in row[1]
    assert row[2] is not None


def test_closed_unmerged_pr_returns_task_to_pending_for_correction():
    conn = _make_task_db()
    out = reconcile_github_pr_task_state(
        42,
        {
            "number": 516,
            "state": "CLOSED",
            "merged": False,
            "close_reason": "Changes requested on GitHub",
        },
        db_path=conn,
    )
    assert out["status"] == "pending"
    assert out["action"] == "reopened_for_correction"
    row = conn.execute("SELECT status, description FROM tasks WHERE id = 42").fetchone()
    assert row[0] == "pending"
    assert "[PR-KORREKTUR #516] Changes requested on GitHub" in row[1]


def test_open_pr_defaults_to_external_github_review():
    conn = _make_task_db()
    out = reconcile_github_pr_task_state(
        42,
        {"number": 517, "state": "OPEN", "merged": False},
        db_path=conn,
    )
    assert out["status"] == "review"
    assert out["action"] == "awaiting_external_pr_review"
    assert out["github_external_review"] is True
