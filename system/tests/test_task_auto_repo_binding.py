# SPDX-License-Identifier: MIT
"""Automatic default worker_repo_registry binding on task creation."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from hub._services.chat import worker_repo_registry as registry
from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
from hub._services.task_lease import task_content_version


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _create_public_clone(tmp_path: Path, repo_id: str, label: str, commit_ts: int | None = None) -> tuple[str, Path]:
    origin_dir = tmp_path / f"origin-{repo_id.replace('/', '_')}-{label}"
    origin_dir.mkdir(parents=True, exist_ok=True)
    (origin_dir / "README.md").write_bytes(f"{repo_id} {label}\n".encode())
    _git(origin_dir, "init", "-b", "main")
    _git(origin_dir, "config", "core.autocrlf", "false")
    _git(origin_dir, "config", "user.name", "Fixture")
    _git(origin_dir, "config", "user.email", "fixture@example.invalid")
    _git(origin_dir, "add", "README.md")
    env = os.environ.copy()
    if commit_ts is not None:
        env["GIT_AUTHOR_DATE"] = f"{commit_ts} +0000"
        env["GIT_COMMITTER_DATE"] = f"{commit_ts} +0000"
    subprocess.run(
        ["git", "-C", str(origin_dir), "commit", "-m", f"Commit {label}"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    sha = _git(origin_dir, "rev-parse", "HEAD")
    _git(origin_dir, "remote", "add", "origin", f"https://github.com/{repo_id}")

    source = registry.source_clone_path(repo_id, sha)
    source.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(registry.source_root(), 0o700)
    subprocess.run(
        ["git", "clone", "-c", "core.autocrlf=false", "--no-local", str(origin_dir), str(source)],
        capture_output=True,
        text=True,
        check=True,
    )
    _git(source, "remote", "set-url", "origin", f"https://github.com/{repo_id}")
    return sha, source


@pytest.fixture
def canonical_env(tmp_path, monkeypatch):
    from hub import worker_git
    from hub._services.chat import worker_write_guard

    home = tmp_path.resolve() / "home"
    bach_dir = home / ".bach"
    bach_dir.mkdir(parents=True, mode=0o700)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("BACH_RHEINGOLD_DISABLED", "1")
    monkeypatch.delenv("BACH_DEFAULT_TASK_REPOSITORY", raising=False)

    bach_sha, bach_source = _create_public_clone(tmp_path, "ellmos-ai/bach", "v1", commit_ts=1760000100)
    ocean_sha, ocean_source = _create_public_clone(tmp_path, "ellmos-ai/open-ocean", "v1", commit_ts=1760000200)

    monkeypatch.setattr(worker_git, "get_live_repo_root", lambda: tmp_path / "no-live-repo")
    monkeypatch.setattr(worker_write_guard, "_scan_locks", lambda _p, **_kw: {"locks": [], "hook_guards": []})

    reg_path = registry.registry_path()
    reg_path.write_text(
        json.dumps(
            {
                "schema": registry.REGISTRY_SCHEMA,
                "repositories": {
                    "ellmos-ai/bach": {
                        "origin": "https://github.com/ellmos-ai/bach",
                        "default_branch": "main",
                        "visibility": "public",
                    },
                    "ellmos-ai/open-ocean": {
                        "origin": "https://github.com/ellmos-ai/open-ocean",
                        "default_branch": "main",
                        "visibility": "public",
                    },
                },
                "tasks": {},
            }
        ),
        encoding="utf-8",
    )
    if os.name != "nt":
        reg_path.chmod(0o600)

    db_path = bach_dir / "bach.db"
    schema_sql = (Path(__file__).parents[1] / "data" / "schema" / "schema.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema_sql)

    def fetch_task(task_id: int) -> dict:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            assert row is not None
            return dict(row)

    return SimpleNamespace(
        home=home,
        bach_dir=bach_dir,
        db_path=db_path,
        reg_path=reg_path,
        bach_sha=bach_sha,
        bach_source=bach_source,
        ocean_sha=ocean_sha,
        ocean_source=ocean_source,
        fetch_task=fetch_task,
    )


def _gui_client(canonical_env, monkeypatch):
    from gui import server

    monkeypatch.setattr(server, "BACH_DB", canonical_env.db_path)
    monkeypatch.setattr(server, "USER_DB", canonical_env.db_path)
    monkeypatch.setattr(
        server,
        "validate_token",
        lambda token: {"id": 1, "device_id": "auto-bind-test"} if token == "auto-bind-token" else None,
    )
    return TestClient(server.app, headers={"Authorization": "Bearer auto-bind-token"})


def test_gui_post_tasks_auto_binds_default_repo_and_passes_worker_gate(canonical_env, monkeypatch):
    with _gui_client(canonical_env, monkeypatch) as client:
        resp = client.post(
            "/api/tasks",
            json={"title": "Buddha soll arbeiten", "description": "Standardbindung prüfen", "priority": "P2"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    task_id = body["id"]
    assert body["repository_binding"]["state"] == "enrolled"
    assert body["repository_binding"]["repository"] == "ellmos-ai/bach"
    assert body["repository_binding"]["source_sha"] == canonical_env.bach_sha

    bound = registry.resolve_task_repository(task_id)
    row = canonical_env.fetch_task(task_id)
    assert bound.repository == "ellmos-ai/bach"
    assert bound.source_sha == canonical_env.bach_sha
    assert bound.task_version == task_content_version(row)
    assert WorkerLeaseBinding._repository_rejection_reason(row, {"allowed_repositories": ["ellmos-ai/bach"]}) is None


def test_gui_post_tasks_supports_explicit_repo_and_opt_out_and_rejects_unregistered(canonical_env, monkeypatch):
    with _gui_client(canonical_env, monkeypatch) as client:
        ocean_resp = client.post(
            "/api/tasks",
            json={"title": "Ocean Task", "repository": "ellmos-ai/open-ocean"},
        )
        assert ocean_resp.status_code == 200
        ocean_id = ocean_resp.json()["id"]
        assert registry.resolve_task_repository(ocean_id).repository == "ellmos-ai/open-ocean"

        opt_out_resp = client.post(
            "/api/tasks",
            json={"title": "Ungebundener Task", "bind_repository": False},
        )
        assert opt_out_resp.status_code == 200
        opt_out_id = opt_out_resp.json()["id"]
        assert opt_out_resp.json()["repository_binding"]["state"] == "skipped"
        with pytest.raises(registry.RepositoryBindingError):
            registry.resolve_task_repository(opt_out_id)

        bad_resp = client.post(
            "/api/tasks",
            json={"title": "Ungültiges Repo", "repository": "ellmos-ai/does-not-exist"},
        )
        assert bad_resp.status_code == 422
        assert bad_resp.json()["detail"]["code"] == "repository_not_registered"

    with sqlite3.connect(canonical_env.db_path) as conn:
        titles = [r[0] for r in conn.execute("SELECT title FROM tasks").fetchall()]
    assert "Ungültiges Repo" not in titles


def test_headless_post_tasks_auto_binds_and_rejects_unregistered(canonical_env, monkeypatch):
    from gui.api import headless

    monkeypatch.setattr(headless, "BACH_DB", str(canonical_env.db_path))
    headless.app.dependency_overrides[headless.verify_auth] = lambda: True
    try:
        with TestClient(headless.app) as client:
            resp = client.post("/api/v1/tasks", json={"title": "Headless Task", "priority": "P2"})
            assert resp.status_code == 201
            body = resp.json()
            assert body["repository_binding"]["state"] == "enrolled"
            assert registry.resolve_task_repository(body["id"]).repository == "ellmos-ai/bach"

            bad = client.post(
                "/api/v1/tasks",
                json={"title": "Unbekanntes Repo", "repository": "evil/private-repo"},
            )
            assert bad.status_code == 422
    finally:
        headless.app.dependency_overrides.pop(headless.verify_auth, None)


def test_chat_tool_task_manage_add_auto_binds_default_repo(canonical_env, monkeypatch):
    from hub._services.chat import bach_tools

    monkeypatch.setattr(bach_tools, "RUNTIME_BACH_DB", canonical_env.db_path)
    output = bach_tools.exec_tool(
        "task_manage",
        {"action": "add", "title": "Chat-Task für Buddha", "priority": "P2"},
        "safe",
    )
    assert "Task #" in output
    assert "[Repo: ellmos-ai/bach]" in output
    with sqlite3.connect(canonical_env.db_path) as conn:
        tid = conn.execute("SELECT id FROM tasks WHERE title='Chat-Task für Buddha'").fetchone()[0]
    bound = registry.resolve_task_repository(tid)
    assert bound.repository == "ellmos-ai/bach"
    assert bound.source_sha == canonical_env.bach_sha
    assert WorkerLeaseBinding._repository_rejection_reason(
        canonical_env.fetch_task(tid), {"allowed_repositories": ["ellmos-ai/bach"]}
    ) is None

    denied = bach_tools.exec_tool(
        "task_manage",
        {"action": "add", "title": "Darf nicht angelegt werden", "repository": "unknown/repo"},
        "safe",
    )
    assert isinstance(denied, bach_tools.ToolErrorText)
    assert getattr(denied, "_code", None) == "invalid_task_arguments"
    assert "nicht kanonisch registriert" in str(denied)


def test_cli_task_handler_add_auto_binds_and_supports_flags(canonical_env):
    from hub.task import TaskHandler

    handler = TaskHandler(Path(__file__).parents[1])
    handler.db_path = canonical_env.db_path
    ok, msg = handler._add(["CLI Task Standard", "--priority", "P2"])
    assert ok is True
    assert "(Repo: ellmos-ai/bach)" in msg

    ok2, msg2 = handler._add(["CLI Task Ocean", "--repository", "ellmos-ai/open-ocean"])
    assert ok2 is True
    assert "(Repo: ellmos-ai/open-ocean)" in msg2

    ok3, _ = handler._add(["CLI Task Ohne Bindung", "--no-repo-bind"])
    assert ok3 is True

    ok4, _ = handler._add(["CLI Task Ungültig", "--repository", "not/registered"])
    assert ok4 is False

    with sqlite3.connect(canonical_env.db_path) as conn:
        rows = dict(conn.execute("SELECT title, id FROM tasks").fetchall())
    assert registry.resolve_task_repository(rows["CLI Task Standard"]).repository == "ellmos-ai/bach"
    assert registry.resolve_task_repository(rows["CLI Task Ocean"]).repository == "ellmos-ai/open-ocean"
    with pytest.raises(registry.RepositoryBindingError):
        registry.resolve_task_repository(rows["CLI Task Ohne Bindung"])
    assert "CLI Task Ungültig" not in rows


def test_auto_enroll_picks_newest_clean_clone_and_skips_dirty_clone(canonical_env, tmp_path):
    newer_sha, _newer_source = _create_public_clone(tmp_path, "ellmos-ai/bach", "v2", commit_ts=1760000500)
    dirty_sha, dirty_source = _create_public_clone(tmp_path, "ellmos-ai/bach", "v3-dirty", commit_ts=1760000900)
    (dirty_source / "UNTRACKED.txt").write_text("tampered\n", encoding="utf-8")

    with sqlite3.connect(canonical_env.db_path) as conn:
        cur = conn.execute("INSERT INTO tasks (title, status, priority) VALUES ('Neuester sauberer Clone', 'pending', 'P2')")
        tid = cur.lastrowid
        conn.commit()

    receipt = registry.auto_enroll_created_task(tid, db_path=canonical_env.db_path)
    assert receipt["state"] == "enrolled"
    assert receipt["source_sha"] == newer_sha
    assert receipt["source_sha"] != dirty_sha
    assert registry.resolve_task_repository(tid).source_sha == newer_sha


def test_non_canonical_db_and_missing_registry_never_touch_host_registry(canonical_env, tmp_path):
    before = canonical_env.reg_path.read_bytes()
    other_db = tmp_path / "temp_test.db"
    other_db.write_bytes(canonical_env.db_path.read_bytes())

    skipped_other = registry.try_auto_enroll_created_task(1, db_path=other_db)
    assert skipped_other["state"] == "skipped"
    assert skipped_other["reason_code"] == "non_canonical_db"
    assert canonical_env.reg_path.read_bytes() == before

    skipped_mem = registry.try_auto_enroll_created_task(1, db_path="")
    assert skipped_mem["state"] == "skipped"
    assert skipped_mem["reason_code"] == "non_canonical_db"
    assert canonical_env.reg_path.read_bytes() == before

    canonical_env.reg_path.unlink()
    skipped_absent = registry.try_auto_enroll_created_task(1, db_path=canonical_env.db_path)
    assert skipped_absent["state"] == "skipped"
    assert skipped_absent["reason_code"] == "registry_absent"


def test_lock_fence_failure_fails_closed_without_breaking_task_creation(canonical_env, monkeypatch):
    from hub._services.chat import worker_write_guard

    def locked(_path, **_kw):
        raise RuntimeError("active lock")

    monkeypatch.setattr(worker_write_guard, "_scan_locks", locked)
    before = canonical_env.reg_path.read_bytes()

    with _gui_client(canonical_env, monkeypatch) as client:
        resp = client.post("/api/tasks", json={"title": "Task während Lock"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["repository_binding"]["state"] == "unavailable"
    assert body["repository_binding"]["reason_code"] == "registry_fence_unavailable"
    assert canonical_env.reg_path.read_bytes() == before


def _blocked_origin_with_resolver(canonical_env, repository):
    from hub import task_audit

    with sqlite3.connect(canonical_env.db_path) as conn:
        origin = conn.execute(
            "INSERT INTO tasks (title, status, priority) VALUES ('Ursprung', 'pending', 'P2')").lastrowid
        conn.commit()
    assert registry.auto_enroll_created_task(origin, repository=repository)["state"] == "enrolled"
    with sqlite3.connect(canonical_env.db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (origin,)).fetchone())
        resolver = task_audit._ensure_block_resolver(
            conn, origin, row, reason="test block", changed_by="test", now="2026-11-28T10:00:00+00:00")
        conn.commit()
    assert resolver is not None
    return origin, resolver


def test_resolver_task_inherits_origin_repository(canonical_env):
    _origin, resolver = _blocked_origin_with_resolver(canonical_env, "ellmos-ai/open-ocean")
    with pytest.raises(registry.RepositoryBindingError):
        registry.resolve_task_repository(resolver)

    receipt = registry.enroll_resolver_task_repository(resolver)
    assert receipt["state"] == "enrolled"
    bound = registry.resolve_task_repository(resolver)
    assert bound.repository == "ellmos-ai/open-ocean"
    assert bound.source_sha == canonical_env.ocean_sha
    assert WorkerLeaseBinding._repository_rejection_reason(
        canonical_env.fetch_task(resolver), {"allowed_repositories": []}) is None


def test_resolver_sweep_binds_pending_resolvers_once(canonical_env):
    _origin, resolver = _blocked_origin_with_resolver(canonical_env, "ellmos-ai/bach")
    first = registry.enroll_pending_resolver_tasks(limit=3)
    assert first["enrolled"] == [resolver]
    assert registry.resolve_task_repository(resolver).repository == "ellmos-ai/bach"
    second = registry.enroll_pending_resolver_tasks(limit=3)
    assert second == {"enrolled": [], "skipped": {}}


def test_spoofed_resolver_without_native_receipt_is_not_bound(canonical_env):
    with sqlite3.connect(canonical_env.db_path) as conn:
        origin = conn.execute(
            "INSERT INTO tasks (title, status, priority) VALUES ('Ursprung', 'pending', 'P2')").lastrowid
        conn.commit()
    registry.auto_enroll_created_task(origin, repository="ellmos-ai/open-ocean")
    with sqlite3.connect(canonical_env.db_path) as conn:
        spoof = conn.execute(
            "INSERT INTO tasks (title, status, priority, created_by, source) "
            "VALUES ('Gefälscht', 'pending', 'P2', 'auto-resolver', ?)", (f"resolver:task:{origin}",)).lastrowid
        conn.commit()
    before = canonical_env.reg_path.read_bytes()
    with pytest.raises(registry.RepositoryBindingError) as exc:
        registry.enroll_resolver_task_repository(spoof)
    assert exc.value.reason_code == "resolver_provenance_unavailable"
    assert registry.enroll_pending_resolver_tasks()["skipped"] == {spoof: "resolver_provenance_unavailable"}
    assert canonical_env.reg_path.read_bytes() == before


def test_resolver_of_unbound_origin_stays_unbound(canonical_env):
    from hub import task_audit

    with sqlite3.connect(canonical_env.db_path) as conn:
        conn.row_factory = sqlite3.Row
        origin = conn.execute(
            "INSERT INTO tasks (title, status, priority) VALUES ('Ohne Repo', 'pending', 'P2')").lastrowid
        row = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (origin,)).fetchone())
        resolver = task_audit._ensure_block_resolver(
            conn, origin, row, reason="x", changed_by="test", now="2026-11-28T10:00:00+00:00")
        conn.commit()
    with pytest.raises(registry.RepositoryBindingError) as exc:
        registry.enroll_resolver_task_repository(resolver)
    assert exc.value.reason_code == "parent_binding_missing"


def test_heal_hook_skips_borrowed_connections_and_throttles(canonical_env, monkeypatch):
    from hub._services.chat import worker_lease_binding as wlb

    calls = []
    monkeypatch.setattr(registry, "enroll_pending_resolver_tasks", lambda **kw: calls.append(kw) or {})
    monkeypatch.setattr(wlb, "_resolver_heal_last", [0.0])
    borrowed = SimpleNamespace(mode="local", _conn=object(), _db_path=None)
    assert wlb._heal_resolver_repository_bindings(borrowed, monotonic=lambda: 1000.0) is None
    assert calls == []

    monkeypatch.setattr(registry, "_canonical_review_client", lambda _c: (None, None))
    canonical = SimpleNamespace(mode="local")
    wlb._heal_resolver_repository_bindings(canonical, monotonic=lambda: 1000.0)
    wlb._heal_resolver_repository_bindings(canonical, monotonic=lambda: 1050.0)
    assert calls == [{"limit": wlb._RESOLVER_HEAL_LIMIT}]
    wlb._heal_resolver_repository_bindings(canonical, monotonic=lambda: 1200.0)
    assert len(calls) == 2
