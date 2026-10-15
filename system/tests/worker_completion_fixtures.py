"""Real local evidence for old worker/sequence tests that finish a new V1 result.

The model response is fixture data, but execution, identity, Git registration,
submission, scope receipt, operator event, and policy decision use production APIs.
"""
from __future__ import annotations

import hashlib
import os

from hub._services import worker_policy_settings as settings
from hub._services import worker_scope_evidence
from hub._services.chat import worker_write_guard
from hub._services.task_result_service import accept_result, read_result
from hub._services.task_schema import ensure_task_result_contract_columns
from hub._services.worker_review_identity import KEY as IDENTITY_KEY
from hub import worker_git
from system.tests.test_worker_scope_snapshot import _git, _install_lock_scanner, _new_scope_repo


PRINCIPAL = "principal:completion-regression-author"
REQUESTED_MODEL = "completion-regression-model"
OBSERVED_MODEL = "completion-regression-observed"
SLOT = "completion-regression-slot"


class CompletionHarness:
    """Owns isolated registered task trees for one test, including sequence steps."""

    def __init__(self, tmp_path, monkeypatch):
        self.root = tmp_path
        self.tree = None
        self.trees = {}
        self._counter = 0
        native_env = worker_write_guard._scope_git_env

        def isolated_git_env():
            env = native_env()
            env["GIT_CONFIG_GLOBAL"] = os.devnull
            env["GIT_CONFIG_NOSYSTEM"] = "1"
            return env

        monkeypatch.setattr(worker_write_guard, "_scope_git_env", isolated_git_env)
        scanner = _install_lock_scanner(tmp_path, monkeypatch)
        # The product reader gives HARVEST_LOCK_SCAN precedence. Both test
        # locators must point at the same scoped temporary lock observation.
        monkeypatch.setenv("BACH_HARVEST_LOCK_SCAN", str(scanner))
        assert worker_write_guard._scanner_path() == scanner.resolve(strict=True)
        native_repo = worker_git.get_live_repo_root
        native_worktrees = worker_git.get_worktrees_dir
        monkeypatch.setattr(worker_git, "get_live_repo_root",
                            lambda: self.tree["repo"] if self.tree else native_repo())
        monkeypatch.setattr(worker_git, "get_worktrees_dir",
                            lambda: self.tree["worktrees"] if self.tree else native_worktrees())
        native_snapshot = worker_scope_evidence.snapshot_task_scope

        def local_snapshot(task_id, *, repo_root=None, worktrees_dir=None):
            tree = self.trees.get(task_id)
            if tree is None:
                return {"availability": "unavailable", "reason": "fixture_tree_missing"}
            return native_snapshot(task_id, repo_root=repo_root or tree["repo"],
                                   worktrees_dir=worktrees_dir or tree["worktrees"])

        monkeypatch.setattr(worker_scope_evidence, "snapshot_task_scope", local_snapshot)

    def _configure(self, conn, *, backend_id, requested_model, observed_model, route_sha256):
        ensure_task_result_contract_columns(conn)
        conn.execute("CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        existing = {row[0] for row in conn.execute(
            "SELECT key FROM system_config WHERE key IN (?,?)", (settings.GLOBAL_KEY, IDENTITY_KEY))}
        identity_row = {"principal_id": PRINCIPAL, "backend_id": backend_id,
                        "route_sha256": route_sha256,
                        "requested_models": [requested_model],
                        "reported_models": [observed_model]}
        if settings.GLOBAL_KEY not in existing:
            values = settings._defaults()
            values["policy"]["default_mode"] = "simple_task"
            values["policy"]["reviewers"] = [{"reviewer_id": PRINCIPAL, "tier": "standard"}]
            settings._persist(conn, settings.GLOBAL_KEY, values, actor="completion-test-fixture")
        else:
            current = settings._global(conn)["policy"]
            assert current["default_mode"] == "simple_task"
            assert {"reviewer_id": PRINCIPAL, "tier": "standard"} in current["reviewers"]
        if IDENTITY_KEY not in existing:
            settings._persist(conn, IDENTITY_KEY, [identity_row], actor="completion-test-fixture")
        else:
            assert identity_row in settings._stored(conn, IDENTITY_KEY)["values"]
        conn.commit()

    def prepare(self, binding, conn, *, backend_id="ollama", requested_model=REQUESTED_MODEL,
                observed_model=OBSERVED_MODEL, slot_id=SLOT):
        """Record an actual local execution before the bound worker submits."""
        route_sha256 = hashlib.sha256(f"{backend_id}|{requested_model}".encode()).hexdigest()
        original_version = binding.task_snapshot()["task_version"]
        self._configure(conn, backend_id=backend_id, requested_model=requested_model,
                        observed_model=observed_model, route_sha256=route_sha256)
        assert binding.task_snapshot()["task_version"] == original_version
        task_id = binding.task_id
        assert task_id not in self.trees
        self._counter += 1
        if self.tree is None:
            tree = _new_scope_repo(self.root / "completion-scope", task_id=task_id)
            self.tree = tree
        else:
            target = self.tree["worktrees"] / f"task-{task_id}"
            _git(["worktree", "add", str(target), "-b", f"bach-task/{task_id}",
                  self.tree["base_head"]], self.tree["repo"])
            tree = {**self.tree, "target": target}
        self.trees[task_id] = tree
        handle = binding.begin_model_execution(
            backend_id=backend_id, requested_model=requested_model, slot_id=slot_id,
            request_sha256=hashlib.sha256(f"prompt:{task_id}:{self._counter}".encode()).hexdigest(),
            route_sha256=route_sha256)
        assert handle is not None
        assert binding.finish_model_execution(handle, result={
            "model": observed_model, "provider_reported_model": observed_model,
            "content": "Verified local fixture response", "tool_calls": None,
        }, route_sha256=route_sha256) is True
        return tree

    def accept(self, binding, conn, operator_token):
        """Use the full current revision and a real personal contract attestation."""
        tree = self.trees[binding.task_id]
        paths = {"repo_root": tree["repo"], "worktrees_dir": tree["worktrees"]}
        current = read_result(conn, binding.task_id)
        if current["result"]["scope"]["availability"] != "recorded":
            assert binding.capture_confirmed_scope() is True
        observed = worker_scope_evidence.project_scope_evidence(
            read_result(conn, binding.task_id), **paths)
        record = observed["result"]
        assert record["completion_policy_version"] == 1
        assert record["execution"]["availability"] == "available"
        assert record["scope"]["availability"] == "available"
        assert isinstance(record["result_revision"], str) and len(record["result_revision"]) == 64
        return accept_result(conn, binding.task_id, record["result_id"],
            digest=record["result_sha256"], task_version=observed["task_version"],
            status_revision=observed["status_revision"],
            result_revision=record["result_revision"], task_contract_met=True,
            operator_token=operator_token, **paths)
