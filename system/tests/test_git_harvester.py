'Contract tests for the branch-only Mac commit harvester.'

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "bin" / "harvest-local-commits.sh"
DEFAULT_HEAD = "a" * 40
DEFAULT_BRANCH = f"mac/test-host-{DEFAULT_HEAD}"


@pytest.fixture
def fake_tools(tmp_path: Path):
    git_bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
    bash = str(git_bash) if git_bash.exists() else shutil.which("bash")
    if not bash:
        pytest.skip("bash is required for the macOS harvester contract")

    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"

    fake_lock_scan = bin_dir / "lock_scan.py"
    fake_lock_scan.write_text(
        '''import os, sys
with open(os.environ["FAKE_CALLS"], "a", encoding="utf-8") as handle:
    handle.write("lock " + " ".join(sys.argv[1:]) + "\\n")
sys.exit(int(os.environ.get("FAKE_LOCK_RC", "0")))
''',
        encoding="utf-8",
    )

    fake_git = bin_dir / "git"
    fake_git.write_text(
        '''#!/usr/bin/env bash
set -e
printf 'git %s\\n' "$*" >> "$FAKE_CALLS"
case "$1 $2" in
  "symbolic-ref --quiet") echo "${FAKE_BRANCH:-main}" ;;
  "rev-parse --git-path") echo ".git/MERGE_HEAD" ;;
  "remote get-url") echo "${FAKE_REMOTE:-https://github.com/ellmos-ai/bach.git}" ;;
  "fetch --prune") ;;
  "rev-parse --verify") echo "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" ;;
  "rev-list --count")
    if [[ "$3" == refs/remotes/* ]]; then echo "${FAKE_AHEAD:-2}"; else echo "${FAKE_BEHIND:-4}"; fi ;;
  "rev-parse HEAD") echo "${FAKE_HEAD:-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}" ;;
  "status --porcelain") printf '%s' "${FAKE_DIRTY:-}" ;;
  "push --porcelain") ;;
  *) echo "unexpected git call: $*" >&2; exit 90 ;;
esac
''',
        encoding="utf-8",
    )
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(
        '''#!/usr/bin/env bash
set -e
printf 'gh %s\\n' "$*" >> "$FAKE_CALLS"
if [[ "$1 $2" == "auth status" ]]; then exit 0; fi
if [[ "$1 $2" == "pr list" ]]; then printf '%s\\n' "${FAKE_PR_NUMBER:-}"; exit 0; fi
if [[ "$1 $2" == "pr create" ]]; then echo "https://github.com/ellmos-ai/bach/pull/91"; exit 0; fi
if [[ "$1 $2" == "pr view" ]]; then
  number="${FAKE_VIEW_NUMBER:-91}"
  state="${FAKE_PR_STATE:-OPEN}"
  draft="${FAKE_PR_DRAFT:-true}"
  head="${FAKE_PR_HEAD:-mac/test-host-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}"
  oid="${FAKE_PR_OID:-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}"
  merged="${FAKE_PR_MERGED_AT:-}"
  echo "${number}|https://github.com/ellmos-ai/bach/pull/${number}|${state}|${draft}|${head}|${oid}|main|${merged}"
  exit 0
fi
exit 91
''',
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "HOME": tmp_path.as_posix(),
            "BACH_HARVEST_ROOT": checkout.as_posix(),
            "BACH_HARVEST_GIT_BIN": fake_git.as_posix(),
            "BACH_HARVEST_GH_BIN": fake_gh.as_posix(),
            "BACH_HARVEST_PYTHON": Path(sys.executable).as_posix(),
            "BACH_HARVEST_LOCK_SCAN": fake_lock_scan.as_posix(),
            "BACH_HARVEST_RECEIPT": (tmp_path / "receipt.jsonl").as_posix(),
            "BACH_HARVEST_HOST": "test-host",
            "BACH_HARVEST_DATE": "20260921",
            "FAKE_CALLS": calls.as_posix(),
        }
    )
    return bash, env, calls


def run_harvester(fake_tools, mode: str, **overrides):
    bash, base_env, calls = fake_tools
    env = base_env.copy()
    env.update({key: str(value) for key, value in overrides.items()})
    result = subprocess.run(
        [bash, SCRIPT.as_posix(), mode],
        text=True,
        capture_output=True,
        env=env,
        timeout=45,
    )
    return result, calls.read_text(encoding="utf-8") if calls.exists() else ""


def test_status_checks_locks_but_never_pushes_or_opens_pr(fake_tools):
    result, calls = run_harvester(fake_tools, "--status")
    assert result.returncode == 0, result.stderr
    assert "ahead=2" in result.stdout
    assert "lock --check-dir" in calls
    assert "git push" not in calls
    assert "gh pr" not in calls


def test_run_pushes_exact_commit_only_to_stable_review_branch(fake_tools):
    result, calls = run_harvester(fake_tools, "--run")
    assert result.returncode == 0, result.stderr
    expected = f"{DEFAULT_HEAD}:refs/heads/{DEFAULT_BRANCH}"
    assert expected in calls
    assert "HEAD:refs/heads" not in calls
    assert "refs/heads/main" not in calls
    assert "--force" not in calls
    assert "gh pr create" in calls
    assert "gh pr view 91" in calls


def test_dirty_tree_fails_before_push(fake_tools):
    result, calls = run_harvester(fake_tools, "--run", FAKE_DIRTY="?? rescued.py")
    assert result.returncode == 1
    assert "nicht sauber" in result.stderr
    assert "git push" not in calls


def test_wrong_remote_fails_closed(fake_tools):
    result, calls = run_harvester(
        fake_tools, "--run", FAKE_REMOTE="https://github.com/example/not-bach.git"
    )
    assert result.returncode == 1
    assert "zeigt nicht auf" in result.stderr
    assert "git push" not in calls


def test_no_ahead_commit_is_idempotent_noop(fake_tools):
    result, calls = run_harvester(fake_tools, "--run", FAKE_AHEAD="0")
    assert result.returncode == 0
    assert "git push" not in calls
    assert "gh pr" not in calls


def test_lock_failure_blocks_before_fetch_or_push(fake_tools):
    result, calls = run_harvester(fake_tools, "--run", FAKE_LOCK_RC="1")
    assert result.returncode == 1
    assert "blockiert" in result.stderr
    assert "git fetch" not in calls
    assert "git push" not in calls


def test_review_branch_is_stable_across_days(fake_tools):
    first, first_calls = run_harvester(fake_tools, "--run", BACH_HARVEST_DATE="20260921")
    assert first.returncode == 0, first.stderr
    _, _, calls_file = fake_tools
    calls_file.write_text("", encoding="utf-8")
    second, second_calls = run_harvester(fake_tools, "--run", BACH_HARVEST_DATE="20260922")
    assert second.returncode == 0, second.stderr
    assert DEFAULT_BRANCH in first_calls
    assert DEFAULT_BRANCH in second_calls
    assert f"--head {DEFAULT_BRANCH}" in first_calls
    assert f"--head {DEFAULT_BRANCH}" in second_calls


def test_push_uses_captured_commit_instead_of_movable_head(fake_tools):
    captured = "b" * 40
    expected_branch = f"mac/test-host-{captured}"
    result, calls = run_harvester(
        fake_tools, "--run", FAKE_HEAD=captured,
        FAKE_PR_HEAD=expected_branch, FAKE_PR_OID=captured,
    )
    assert result.returncode == 0, result.stderr
    assert f"git push --porcelain origin {captured}:refs/heads/{expected_branch}" in calls
    assert "HEAD:refs/heads" not in calls


def test_pr_head_oid_mismatch_fails_readback(fake_tools):
    result, calls = run_harvester(fake_tools, "--run", FAKE_PR_OID="b" * 40)
    assert result.returncode == 1
    assert "Commit, Branch und Basis" in result.stderr
    assert "gh pr view 91" in calls


def test_existing_open_draft_pr_is_idempotent_noop(fake_tools):
    result, calls = run_harvester(fake_tools, "--run", FAKE_PR_NUMBER="91")
    assert result.returncode == 0, result.stderr
    assert "Bestehender Draft-PR #91" in result.stdout
    assert "git push" not in calls
    assert "gh pr create" not in calls


def test_existing_merged_pr_is_idempotent_noop(fake_tools):
    result, calls = run_harvester(
        fake_tools, "--run", FAKE_PR_NUMBER="91", FAKE_PR_STATE="MERGED",
        FAKE_PR_DRAFT="false", FAKE_PR_MERGED_AT="2026-09-21T12:00:00Z",
    )
    assert result.returncode == 0, result.stderr
    assert "PR #91 gemergt" in result.stdout
    assert "git push" not in calls
    assert "gh pr create" not in calls


def test_existing_unmerged_closed_pr_blocks(fake_tools):
    result, calls = run_harvester(
        fake_tools, "--run", FAKE_PR_NUMBER="91", FAKE_PR_STATE="CLOSED",
        FAKE_PR_DRAFT="false",
    )
    assert result.returncode == 1
    assert "ungemergt geschlossen" in result.stderr
    assert "git push" not in calls


@pytest.mark.parametrize(("state", "draft"), [("CLOSED", "true"), ("OPEN", "false")])
def test_created_pr_must_be_open_and_draft(fake_tools, state, draft):
    result, _ = run_harvester(
        fake_tools, "--run", FAKE_PR_STATE=state, FAKE_PR_DRAFT=draft
    )
    assert result.returncode == 1
