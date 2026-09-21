"""Contract tests for the branch-only Mac commit harvester."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "bin" / "harvest-local-commits.sh"


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

    fake_git = bin_dir / "git"
    fake_git.write_text(
        """#!/usr/bin/env bash
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
  "rev-parse HEAD") echo "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" ;;
  "rev-parse --short=12") echo "aaaaaaaaaaaa" ;;
  "status --porcelain") printf '%s' "${FAKE_DIRTY:-}" ;;
  "push --porcelain") ;;
  *) echo "unexpected git call: $*" >&2; exit 90 ;;
esac
""",
        encoding="utf-8",
    )
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -e
printf 'gh %s\\n' "$*" >> "$FAKE_CALLS"
if [[ "$1 $2" == "auth status" ]]; then exit 0; fi
if [[ "$1 $2" == "pr list" ]]; then printf '%s\\n' "${FAKE_PR_NUMBER:-}"; exit 0; fi
if [[ "$1 $2" == "pr create" ]]; then echo "https://github.com/ellmos-ai/bach/pull/91"; exit 0; fi
if [[ "$1 $2" == "pr view" ]]; then
  echo -e "91\\thttps://github.com/ellmos-ai/bach/pull/91\\tOPEN\\ttrue\\tmac/test-host-20260921-aaaaaaaaaaaa\\tmain"
  exit 0
fi
exit 91
""",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "BACH_HARVEST_ROOT": checkout.as_posix(),
            "BACH_HARVEST_GIT_BIN": fake_git.as_posix(),
            "BACH_HARVEST_GH_BIN": fake_gh.as_posix(),
            "BACH_HARVEST_RECEIPT": (tmp_path / "receipt.jsonl").as_posix(),
            "BACH_HARVEST_HOST": "test-host",
            "BACH_HARVEST_DATE": "20260921",
            "FAKE_CALLS": calls.as_posix(),
        }
    )
    return bash, env, calls


def run_harvester(fake_tools, mode: str, **overrides):
    bash, env, calls = fake_tools
    env.update({key: str(value) for key, value in overrides.items()})
    result = subprocess.run(
        [bash, SCRIPT.as_posix(), mode],
        text=True,
        capture_output=True,
        env=env,
        timeout=15,
    )
    return result, calls.read_text(encoding="utf-8") if calls.exists() else ""


def test_status_never_pushes_or_opens_pr(fake_tools):
    result, calls = run_harvester(fake_tools, "--status")
    assert result.returncode == 0
    assert "ahead=2" in result.stdout
    assert "git push" not in calls
    assert "gh pr" not in calls


def test_run_pushes_only_review_branch_and_reads_back_pr(fake_tools):
    result, calls = run_harvester(fake_tools, "--run")
    assert result.returncode == 0, result.stderr
    assert "HEAD:refs/heads/mac/test-host-20260921-aaaaaaaaaaaa" in calls
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
