"""
Unit tests for module_gate_check PR-base diffing and gate logic.
Verifies T-20261107-689438510.
"""

from pathlib import Path
import os
import subprocess
import pytest

from system.tools.testing.module_gate_check import (
    get_changed_files,
    get_git_changed_files,
    check_path_compliance,
    check_header_compliance,
    check_line_ratchet,
    main,
)


@pytest.fixture
def clean_feature_repo(tmp_path, monkeypatch):
    """
    Creates a temporary git repository with:
    - Base branch: 'main'
    - Feature branch: 'feat/test' with 1 committed module file
    - Completely clean working tree (git status is clean)
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    # Clear env vars that could affect diffing
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    monkeypatch.delenv("BACH_MODULE_GATE_BASE", raising=False)
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)

    def run_git(*args):
        return subprocess.run(
            ["git", *args],
            cwd=str(repo),
            check=True,
            capture_output=True,
            text=True,
        )

    run_git("init", "-b", "main")
    run_git("config", "user.name", "Tester")
    run_git("config", "user.email", "tester@example.com")

    # Initial commit on main
    (repo / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    run_git("add", "README.md")
    run_git("commit", "-m", "initial commit on main")

    # Create feature branch and add a module file
    run_git("checkout", "-b", "feat/test")
    module_dir = repo / "system" / "hub"
    module_dir.mkdir(parents=True, exist_ok=True)
    module_file = module_dir / "test_module.py"
    module_file.write_text("# BACH Adapter: test_module\n\ndef run():\n    return 42\n", encoding="utf-8")

    run_git("add", "system/hub/test_module.py")
    run_git("commit", "-m", "feat(hub): add test_module")

    # Verify working tree is clean
    res = run_git("status", "--porcelain")
    assert res.stdout.strip() == "", "Working tree must be clean"

    return repo


def test_without_base_diff_clean_tree_sees_zero_files(clean_feature_repo):
    """
    Proves that without base diff (old git diff HEAD behavior),
    0 files are seen when the working tree is clean on a feature branch.
    """
    files = get_changed_files(base_ref=None, repo_root=clean_feature_repo)
    assert files == [], f"Expected 0 changed files without base diff, but got: {files}"


def test_with_github_base_ref_detects_committed_feature_file(clean_feature_repo, monkeypatch):
    """
    Proves that with GITHUB_BASE_REF=main,
    module_gate_check detects the committed file change on the feature branch.
    """
    monkeypatch.setenv("GITHUB_BASE_REF", "main")
    files = get_changed_files(repo_root=clean_feature_repo)
    assert "system/hub/test_module.py" in files
    assert get_git_changed_files(repo_root=clean_feature_repo) == files


def test_with_explicit_base_arg_detects_committed_feature_file(clean_feature_repo):
    """
    Proves that passing base_ref='main' (e.g. from --base main)
    detects the committed file change on the feature branch.
    """
    files = get_changed_files(base_ref="main", repo_root=clean_feature_repo)
    assert "system/hub/test_module.py" in files


def test_with_bach_module_gate_base_env_detects_committed_feature_file(clean_feature_repo, monkeypatch):
    """
    Proves that setting BACH_MODULE_GATE_BASE=main
    detects the committed file change deterministically.
    """
    monkeypatch.setenv("BACH_MODULE_GATE_BASE", "main")
    files = get_changed_files(repo_root=clean_feature_repo)
    assert "system/hub/test_module.py" in files


def test_uncommitted_changes_detected_with_or_without_base(clean_feature_repo):
    """
    Proves that uncommitted modifications are detected first,
    and combined with committed base diffs if base is specified.
    """
    uncommitted_file = clean_feature_repo / "system" / "hub" / "uncommitted.py"
    uncommitted_file.write_text("# uncommitted\n", encoding="utf-8")
    subprocess.run(["git", "add", "system/hub/uncommitted.py"], cwd=str(clean_feature_repo), check=True)

    # Without base: only uncommitted file
    files_no_base = get_changed_files(base_ref=None, repo_root=clean_feature_repo)
    assert files_no_base == ["system/hub/uncommitted.py"]

    # With base: both uncommitted and committed feature file
    files_with_base = get_changed_files(base_ref="main", repo_root=clean_feature_repo)
    assert "system/hub/test_module.py" in files_with_base
    assert "system/hub/uncommitted.py" in files_with_base


def test_main_cli_execution_with_base_flag(clean_feature_repo):
    """
    Proves that running main(['--base', 'main', '--repo', str(repo)]) succeeds (exit 0)
    and produces .gate_report.txt documenting the detected file.
    """
    code = main(["--base", "main", "--repo", str(clean_feature_repo)])
    assert code == 0, f"Expected main() to return 0, got {code}"

    report_path = clean_feature_repo / ".gate_report.txt"
    assert report_path.exists()
    report_content = report_path.read_text(encoding="utf-8")
    assert "system/hub/test_module.py" in report_content
    assert "Modul-Gate bestanden" in report_content or "PASS" in report_content
