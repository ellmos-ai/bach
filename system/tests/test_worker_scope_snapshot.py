"""Behavioral tests for the read-only worker task-scope Git snapshot."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from hub._services.chat import worker_write_guard as guard


TASK_ID = 41
ORIGIN = "https://github.com/ellmos-ai/bach"


def _git(args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True,
        text=True, encoding="utf-8", timeout=10, env=guard._scope_git_env(),
    )


def _new_scope_repo(base, *, task_id=TASK_ID, pinned=False, suffix="", monkeypatch=None):
    """Create a real, isolated origin-shaped repository and registered task tree."""
    base.mkdir(parents=True, exist_ok=True)
    if monkeypatch is not None:
        home = base / "home"
        local_bach = home / ".bach"
        local_bach.mkdir(parents=True, exist_ok=True)
        local_bach.chmod(0o700)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("BACH_LOCAL_DIR", str(local_bach))
    repo = base / f"repo{suffix}"
    worktrees = base / f"worktrees{suffix}"
    repo.mkdir()
    worktrees.mkdir()

    _git(["init", "-b", "main"], repo)
    _git(["config", "user.name", "Scope Test"], repo)
    _git(["config", "user.email", "scope-test@example.invalid"], repo)
    (repo / "README.md").write_text("public base\n", encoding="utf-8")
    _git(["add", "README.md"], repo)
    _git(["commit", "-m", "public base"], repo)
    _git(["remote", "add", "origin", ORIGIN + ".git"], repo)
    base_head = _git(["rev-parse", "HEAD"], repo).stdout.strip()

    target = worktrees / f"task-{task_id}"
    _git(["worktree", "add", str(target), "-b", f"bach-task/{task_id}", base_head], repo)

    from hub import worker_git
    reg_data = {
        "schema": "bach.task-public-source.v1",
        "task_id": task_id,
        "repository": "ellmos-ai/bach",
        "origin": ORIGIN,
        "source_ref": "refs/heads/main",
        "source_sha": base_head,
    }
    if pinned:
        reg_data.update({
            "visibility": "public",
            "private": False,
            "metadata_verified": True,
            "ref_verified": True,
            "verified_at": "2026-10-15T12:00:00+00:00",
        })
        worker_git._store_public_source_registration(repo, target, task_id, reg_data)
    return {
        "repo": repo,
        "worktrees": worktrees,
        "target": target,
        "base_head": base_head,
    }


def _install_lock_scanner(tmp_path, monkeypatch, *, locks=None, twin_status="ok",
                          malformed=False, exit_code=None):
    scanner = tmp_path / "lock_scan_fixture.py"
    if malformed:
        scanner.write_text("print('not-json')\n", encoding="utf-8")
    else:
        payload = json.dumps({"twin_status": twin_status, "locks": locks or []})
        status = exit_code if exit_code is not None else (1 if locks else 0)
        scanner.write_text(
            "import json, sys\n"
            "from pathlib import Path\n"
            f"payload = json.loads({payload!r})\n"
            "target = Path(sys.argv[2]).resolve(strict=False)\n"
            "payload['checked'] = str(target)\n"
            "if sys.argv[1] == '--check-create-dir':\n"
            "    anchor = Path(sys.argv[4]).resolve(strict=True)\n"
            "    st = anchor.lstat()\n"
            "    payload.update({\n"
            "        'check_mode': 'check-create-dir-v1',\n"
            "        'creation_anchor': str(anchor),\n"
            "        'creation_anchor_identity': {'dev': st.st_dev, 'ino': st.st_ino, 'mode': st.st_mode},\n"
            "        'missing_suffix': list(target.relative_to(anchor).parts),\n"
            "        'target_exists': False,\n"
            "        'target_descendants_state': 'absent-confirmed',\n"
            "        'descendants_complete': None,\n"
            "        'twins_descendants_complete': True,\n"
            "        'checks_complete': True,\n"
            "    })\n"
            "print(json.dumps(payload))\n"
            f"raise SystemExit({status})\n",
            encoding="utf-8",
        )
    monkeypatch.setenv("BACH_LOCK_SCAN", str(scanner))
    return scanner


@pytest.fixture
def scope_repo(tmp_path, monkeypatch):
    tree = _new_scope_repo(tmp_path, pinned=False, monkeypatch=monkeypatch)
    _install_lock_scanner(tmp_path, monkeypatch)
    return tree


def _snapshot(tree, *, repo=None, worktrees=None):
    return guard.snapshot_task_scope(
        TASK_ID,
        repo_root=repo or tree["repo"],
        worktrees_dir=worktrees or tree["worktrees"],
    )


def _assert_unavailable(snapshot, reason):
    assert snapshot["schema"] == "bach.task-scope-snapshot.v1"
    assert snapshot["availability"] == "unavailable"
    assert snapshot["reason"] == reason
    assert json.loads(json.dumps(snapshot, allow_nan=False)) == snapshot


def _assert_available(snapshot, tree, *, source_pin=None):
    assert snapshot["schema"] == "bach.task-scope-snapshot.v1"
    assert snapshot["availability"] == "available"
    assert snapshot["task_id"] == TASK_ID
    assert snapshot["repository"] == "ellmos-ai/bach"
    assert snapshot["origin"] == ORIGIN
    assert snapshot["branch"] == f"refs/heads/bach-task/{TASK_ID}"
    assert re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", snapshot["head_oid"])
    assert re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", snapshot["tree_oid"])
    for key in ("repo_path_sha256", "worktree_path_sha256", "common_dir_sha256",
                "status_sha256", "index_sha256", "project_state_ref",
                "workspace_fingerprint"):
        assert re.fullmatch(r"[0-9a-f]{64}", snapshot[key])
    assert snapshot["clean_scope"] == "porcelain-v1-z-all-untracked-no-ignored"
    assert snapshot["source_pin"] == source_pin
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, allow_nan=False)
    assert str(tree["repo"]) not in encoded
    assert str(tree["target"]) not in encoded
    assert json.loads(encoded) == snapshot


def test_clean_registered_tree_returns_json_safe_git_identity_without_raw_paths(scope_repo):
    snapshot = _snapshot(scope_repo)
    _assert_available(snapshot, scope_repo)
    assert snapshot["head_oid"] == scope_repo["base_head"]
    assert snapshot["tree_oid"] == _git(["rev-parse", "HEAD^{tree}"], scope_repo["target"]).stdout.strip()


def test_optional_verified_public_source_pin_is_projected_without_extra_claims(
    tmp_path, monkeypatch
):
    tree = _new_scope_repo(tmp_path, pinned=True, monkeypatch=monkeypatch)
    _install_lock_scanner(tmp_path, monkeypatch)

    snapshot = _snapshot(tree)

    pin = snapshot["source_pin"]
    assert pin["schema"] == "bach.task-public-source.v1"
    assert pin["source_ref"] == "refs/heads/main"
    assert pin["source_sha"] == tree["base_head"]
    assert pin["verified_at"] == "2026-10-15T12:00:00+00:00"
    assert set(pin) == {"schema", "source_ref", "source_sha", "verified_at"}
    _assert_available(snapshot, tree, source_pin=pin)


def test_snapshot_tracks_task_head_and_tree_after_a_clean_commit(scope_repo):
    before = _snapshot(scope_repo)
    _assert_available(before, scope_repo)

    (scope_repo["target"] / "task-change.txt").write_text("new task content\n", encoding="utf-8")
    _git(["add", "task-change.txt"], scope_repo["target"])
    _git(["commit", "-m", "task change"], scope_repo["target"])

    after = _snapshot(scope_repo)
    _assert_available(after, scope_repo)
    assert after["head_oid"] != before["head_oid"]
    assert after["tree_oid"] != before["tree_oid"]
    assert after["project_state_ref"] != before["project_state_ref"]
    assert after["workspace_fingerprint"] != before["workspace_fingerprint"]


@pytest.mark.parametrize("dirty_kind", ["unstaged", "staged", "untracked"])
def test_staged_unstaged_and_untracked_changes_are_not_reported_as_clean(scope_repo, dirty_kind):
    if dirty_kind == "untracked":
        (scope_repo["target"] / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    else:
        readme = scope_repo["target"] / "README.md"
        readme.write_text("changed content\n", encoding="utf-8")
        if dirty_kind == "staged":
            _git(["add", "README.md"], scope_repo["target"])

    _assert_unavailable(_snapshot(scope_repo), "git_dirty")


@pytest.mark.parametrize("branch_state", ["wrong_branch", "detached"])
def test_branch_change_or_detached_head_is_not_the_registered_task_tree(scope_repo, branch_state):
    if branch_state == "wrong_branch":
        _git(["checkout", "-b", "user/other-branch"], scope_repo["target"])
    else:
        _git(["checkout", "--detach"], scope_repo["target"])

    _assert_unavailable(_snapshot(scope_repo), "registration_unavailable")


def test_worktree_from_another_git_project_is_not_accepted_as_registered(tmp_path, monkeypatch):
    canonical = _new_scope_repo(tmp_path, pinned=False, suffix="-canonical", monkeypatch=monkeypatch)
    foreign = _new_scope_repo(tmp_path, pinned=False, suffix="-foreign", monkeypatch=monkeypatch)
    _install_lock_scanner(tmp_path, monkeypatch)

    snapshot = _snapshot(canonical, repo=foreign["repo"], worktrees=canonical["worktrees"])

    _assert_unavailable(snapshot, "registration_unavailable")


def test_common_directory_mismatch_fails_closed_after_candidate_path_selection(
    tmp_path, monkeypatch
):
    canonical = _new_scope_repo(tmp_path, pinned=False, suffix="-canonical", monkeypatch=monkeypatch)
    foreign = _new_scope_repo(tmp_path, pinned=False, suffix="-foreign", monkeypatch=monkeypatch)
    _install_lock_scanner(tmp_path, monkeypatch)
    # Isolate the final common-directory proof: the returned candidate is a
    # genuine clean task worktree, but its Git common directory belongs to the
    # other temporary repository.
    monkeypatch.setattr(guard, "_registered_tree",
                        lambda _repo, _root, _task_id: foreign["target"])

    snapshot = _snapshot(canonical)

    _assert_unavailable(snapshot, "registration_unavailable")


def test_symlinked_task_worktree_redirect_is_rejected(scope_repo):
    target = scope_repo["target"]
    real_target = target.with_name("task-real")
    target.rename(real_target)
    try:
        target.symlink_to(real_target, target_is_directory=True)
    except (OSError, NotImplementedError):
        real_target.rename(target)
        pytest.skip("Directory symlink creation is unavailable")

    _assert_unavailable(_snapshot(scope_repo), "registration_unavailable")


@pytest.mark.parametrize("flag", ["assume-unchanged", "skip-worktree"])
def test_index_visibility_flags_are_rejected_even_if_worktree_looks_clean(scope_repo, flag):
    _git(["update-index", f"--{flag}", "README.md"], scope_repo["target"])

    _assert_unavailable(_snapshot(scope_repo), "index_flags")


@pytest.mark.parametrize("origin_state", ["missing", "foreign"])
def test_missing_or_noncanonical_origin_is_unavailable(scope_repo, origin_state):
    if origin_state == "missing":
        _git(["remote", "remove", "origin"], scope_repo["repo"])
    else:
        _git(["remote", "set-url", "origin", "https://example.invalid/not-bach.git"],
             scope_repo["repo"])

    _assert_unavailable(_snapshot(scope_repo), "origin_unavailable")


def test_malformed_existing_public_source_pin_is_not_treated_as_absent(scope_repo):
    from hub import worker_git

    key = worker_git._public_source_config_key(TASK_ID)
    _git(["config", "--local", "--replace-all", key, "not-json"], scope_repo["target"])

    _assert_unavailable(_snapshot(scope_repo), "source_pin_invalid")


@pytest.mark.parametrize("scanner_failure", ["foreign_lock", "malformed_json", "unknown_twin", "bad_exit"])
def test_lock_scanner_failures_and_foreign_locks_are_unavailable(
    scope_repo, tmp_path, monkeypatch, scanner_failure
):
    if scanner_failure == "foreign_lock":
        _install_lock_scanner(
            tmp_path, monkeypatch,
            locks=[{"path": str(tmp_path / "LOCK.foreign.txt"), "scope": "foreign"}],
        )
    elif scanner_failure == "malformed_json":
        _install_lock_scanner(tmp_path, monkeypatch, malformed=True)
    elif scanner_failure == "unknown_twin":
        _install_lock_scanner(tmp_path, monkeypatch, twin_status="unknown")
    else:
        _install_lock_scanner(tmp_path, monkeypatch, exit_code=2)

    _assert_unavailable(_snapshot(scope_repo), "lock_unavailable")


@pytest.mark.parametrize("task_id", [0, -1, True, "not-a-task"])
def test_invalid_task_ids_return_a_json_safe_unavailable_snapshot(scope_repo, task_id):
    snapshot = guard.snapshot_task_scope(
        task_id, repo_root=scope_repo["repo"], worktrees_dir=scope_repo["worktrees"]
    )

    _assert_unavailable(snapshot, "invalid_task_id")


def test_missing_repository_path_is_unavailable_without_git_fallback(scope_repo, tmp_path):
    snapshot = _snapshot(scope_repo, repo=tmp_path / "missing-repository")

    _assert_unavailable(snapshot, "paths_unavailable")


def test_commit_during_multi_command_observation_is_not_returned_as_a_snapshot(
    scope_repo, monkeypatch
):
    target = scope_repo["target"]
    original_scope_git = guard._scope_git
    changed = {"value": False}

    def commit_after_first_tree_read(argv, cwd, *args, **kwargs):
        result = original_scope_git(argv, cwd, *args, **kwargs)
        if (
            not changed["value"]
            and Path(cwd).resolve() == target.resolve()
            and argv == ["rev-parse", "--verify", "HEAD^{tree}"]
        ):
            changed["value"] = True
            (target / "concurrent-change.txt").write_text(
                "commit during snapshot measurement\n", encoding="utf-8"
            )
            _git(["add", "concurrent-change.txt"], target)
            _git(["commit", "-m", "concurrent task change"], target)
        return result

    monkeypatch.setattr(guard, "_scope_git", commit_after_first_tree_read)

    snapshot = _snapshot(scope_repo)

    assert changed["value"] is True
    _assert_unavailable(snapshot, "git_changed")


def test_gitlink_entry_is_rejected_before_any_status_read(scope_repo, monkeypatch):
    target = scope_repo["target"]
    local_oid = _git(["rev-parse", "HEAD"], target).stdout.strip()
    _git(
        ["update-index", "--add", "--cacheinfo",
         f"160000,{local_oid},vendor/unavailable-submodule"],
        target,
    )
    _git(["commit", "-m", "record gitlink without checkout"], target)

    original_scope_git = guard._scope_git
    observed_calls = []

    def record_scope_git(argv, cwd, *args, **kwargs):
        observed_calls.append(list(argv))
        return original_scope_git(argv, cwd, *args, **kwargs)

    monkeypatch.setattr(guard, "_scope_git", record_scope_git)

    snapshot = _snapshot(scope_repo)

    _assert_unavailable(snapshot, "submodule_scope_unsupported")
    assert not any(args and args[0] == "status" for args in observed_calls)


@pytest.fixture(autouse=True)
def hermetic_snapshot_git_environment(monkeypatch):
    """Keep unrelated host filters out while retaining local repo config checks."""
    import os

    original_sanitizer = guard._scope_git_env

    def isolated_environment():
        env = original_sanitizer()
        env["GIT_CONFIG_GLOBAL"] = os.devnull
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        return env

    monkeypatch.setattr(guard, "_scope_git_env", isolated_environment)
    # Tests can inspect the production sanitizer itself, before test-only isolation.
    return original_sanitizer


def test_repo_local_clean_filter_is_rejected_before_marker_command_runs(
    scope_repo, tmp_path, monkeypatch
):
    import shlex

    target = scope_repo["target"]
    (target / ".gitattributes").write_text(
        "README.md filter=bach-scope-local-probe\n", encoding="utf-8"
    )
    _git(["add", ".gitattributes"], target)
    _git(["commit", "-m", "bind local filter probe"], target)
    (target / "README.md").write_text("changed content for clean filter\n", encoding="utf-8")

    marker = tmp_path / "local-filter-executed.txt"
    monkeypatch.setenv("BACH_SCOPE_FILTER_MARKER", str(marker))
    script = (
        "import os,pathlib,sys; "
        "pathlib.Path(os.environ['BACH_SCOPE_FILTER_MARKER']).write_text('ran'); "
        "sys.stdout.write(sys.stdin.read())"
    )
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"
    _git(["config", "--local", "filter.bach-scope-local-probe.clean", command], target)

    snapshot = _snapshot(scope_repo)

    _assert_unavailable(snapshot, "git_unavailable")
    assert not marker.exists()


def test_original_git_environment_sanitizer_strips_host_git_vars_and_keeps_bach(
    monkeypatch, hermetic_snapshot_git_environment
):
    import os

    inherited_git_names = {key for key in os.environ if key.startswith("GIT_")} | {
        "GIT_CONFIG", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM",
        "GIT_SHALLOW_FILE", "GIT_ATTR_SOURCE",
    }
    for key in inherited_git_names:
        monkeypatch.setenv(key, "inherited-host-value")
    monkeypatch.setenv("BACH_SCOPE_TEST_PRESERVED", "bach-value")

    sanitized = hermetic_snapshot_git_environment()

    safe_git = {
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_NO_REPLACE_OBJECTS": "1",
    }
    assert {key: value for key, value in sanitized.items()
            if key.startswith("GIT_")} == safe_git
    assert sanitized["BACH_SCOPE_TEST_PRESERVED"] == "bach-value"
