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
printf 'git %s%s\\n' "$*" "${GIT_INDEX_FILE:+ [tmp-index]}" >> "$FAKE_CALLS"
case "$1 $2" in
  "read-tree "*|"add -A") ;;
  "write-tree ") echo "${FAKE_TREE:-cccccccccccccccccccccccccccccccccccccccc}" ;;
  "diff --name-only") printf '%b' "${FAKE_SNAPSHOT_PATHS:-}"; exit "${FAKE_NAMES_RC:-0}" ;;
  "add --pathspec-from-file="*)
    tr '\\0' '\\n' < "${2#--pathspec-from-file=}" | sed 's/^/staged /' >> "$FAKE_CALLS"
    printf 'literal-pathspecs=%s\\n' "${GIT_LITERAL_PATHSPECS:-}" >> "$FAKE_CALLS" ;;
  "diff --cached")
    if [[ "$3" == "--name-only" ]]; then printf '%s' "${FAKE_SNAPSHOT_PATHS:-}";
    else printf '%s' "${FAKE_SNAPSHOT_DIFF:-}"; exit "${FAKE_DIFF_RC:-0}"; fi ;;
  "show -s") echo "2026-09-21T10:00:00+02:00" ;;
  "commit-tree "*) echo "${FAKE_SNAPSHOT_COMMIT:-dddddddddddddddddddddddddddddddddddddddd}" ;;
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

    for tool in (fake_git, fake_gh):
        tool.chmod(0o755)  # POSIX runs need the fakes executable; Git Bash on Windows does not check.

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
    # T-20260927-448662565: 10 Aufrufe dieser Funktion in der Datei x 45s ergab
    # exakt die im CI-Inventar gemeldeten ">450s" -- kein Deadlock, sondern jeder
    # git-bash.exe-Aufruf lief unter Host-Last regulaer in TimeoutExpired.
    # Normalzeit pro Aufruf gemessen: 1-7s. Engerer Wert begrenzt den Worst-Case
    # auf 150s statt 450s, bei weiterhin >2x Sicherheitsmarge.
    result = subprocess.run(
        [bash, SCRIPT.as_posix(), mode],
        text=True,
        capture_output=True,
        env=env,
        timeout=15,
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


SNAPSHOT_COMMIT = "d" * 40
SNAPSHOT_BRANCH = "mac/test-host-live-" + "c" * 12
RESCUED = "system/hub/rescued.py"
# Snapshot switched on, one tracked modified file, no committed work ahead.
SNAP = {"BACH_HARVEST_SNAPSHOT": "1", "FAKE_AHEAD": "0", "FAKE_DIRTY": " M " + RESCUED,
        "FAKE_SNAPSHOT_PATHS": RESCUED + "\\0"}


def live_file(fake_tools, relative, data=b"print('rescued')\n"):
    path = Path(fake_tools[1]["BACH_HARVEST_ROOT"]) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def staged(calls):
    return [line.removeprefix("staged ") for line in calls.splitlines() if line.startswith("staged ")]


def test_dirty_tree_is_pushed_as_snapshot_without_touching_live_tree(fake_tools):
    live_file(fake_tools, RESCUED)
    result, calls = run_harvester(
        fake_tools, "--run", **SNAP, FAKE_PR_HEAD=SNAPSHOT_BRANCH, FAKE_PR_OID=SNAPSHOT_COMMIT,
    )
    assert result.returncode == 0, result.stderr
    assert "[DIRTY] 1 uncommittete Pfade" in result.stdout
    for step in ("git read-tree", "git add --pathspec-from-file", "git write-tree"):
        line = next(line for line in calls.splitlines() if line.startswith(step))
        assert line.endswith("[tmp-index]"), line
    assert f"git commit-tree {'c' * 40} -p {DEFAULT_HEAD}" in calls
    assert f"git push --porcelain origin {SNAPSHOT_COMMIT}:refs/heads/{SNAPSHOT_BRANCH}" in calls
    for forbidden in ("git commit ", "git stash", "git checkout", "git reset", "refs/heads/main"):
        assert forbidden not in calls
    assert f"--head {SNAPSHOT_BRANCH}" in calls


def test_dirty_status_reports_without_push(fake_tools):
    result, calls = run_harvester(fake_tools, "--status", FAKE_DIRTY="?? rescued.py",
                                  FAKE_AHEAD="0")
    assert result.returncode == 0, result.stderr
    assert "[DIRTY] 1 uncommittete Pfade" in result.stdout
    assert "git push" not in calls
    assert "gh pr" not in calls


def test_snapshot_diff_failure_blocks_before_push(fake_tools):
    live_file(fake_tools, RESCUED)
    result, calls = run_harvester(fake_tools, "--run", **SNAP, FAKE_DIFF_RC="7")
    assert result.returncode == 1
    assert "Snapshot-Diff konnte nicht" in result.stderr
    assert "git commit-tree" not in calls
    assert "git push" not in calls


# Synthetic credential shapes, assembled at runtime so no real-looking token sits in the source.
SYNTHETIC_SECRETS = {
    "telegram-bot": "123456789:" + "A" * 35,
    "anthropic": "sk-ant-" + "api03-" + "x" * 24,
    "openrouter": "sk-or-v1-" + "0" * 64,
    "google": "AIza" + "B" * 35,
    "github-classic": "ghp_" + "c" * 36,
    "github-fine-grained": "github_pat_" + "d" * 30,
    "private-key": "-----BEGIN RSA " + "PRIVATE KEY-----",
    "aws": "AKIA" + "E" * 16,
    "bearer": "Authorization: Bearer " + "f" * 32,
    "slack": "xoxb-" + "1" * 12,
}


@pytest.mark.parametrize("kind", sorted(SYNTHETIC_SECRETS))
def test_snapshot_with_credential_pattern_blocks_before_push_without_echo(fake_tools, kind):
    secret = SYNTHETIC_SECRETS[kind]
    live_file(fake_tools, RESCUED)
    result, calls = run_harvester(fake_tools, "--run", **SNAP, FAKE_SNAPSHOT_DIFF=f"+VALUE = '{secret}'\n")
    assert result.returncode == 1
    assert "Zugangsdaten" in result.stderr
    assert "git commit-tree" not in calls
    assert "git push" not in calls
    receipt = Path(fake_tools[1]["BACH_HARVEST_RECEIPT"]).read_text(encoding="utf-8")
    for output in (result.stdout, result.stderr, receipt):
        assert secret not in output


@pytest.mark.parametrize("line", ["+name = 'sk-ant'  # docs\n", "+ratio = 12345678:short\n", "+header = 'Bearer'\n"])
def test_benign_lines_near_credential_shapes_do_not_block(fake_tools, line):
    live_file(fake_tools, RESCUED)
    result, calls = run_harvester(fake_tools, "--run", **SNAP, FAKE_SNAPSHOT_DIFF=line,
                                  FAKE_PR_HEAD=SNAPSHOT_BRANCH, FAKE_PR_OID=SNAPSHOT_COMMIT)
    assert result.returncode == 0, result.stderr
    assert f"{SNAPSHOT_COMMIT}:refs/heads/{SNAPSHOT_BRANCH}" in calls


def test_snapshot_is_off_by_default(fake_tools):
    live_file(fake_tools, RESCUED)
    overrides = {key: value for key, value in SNAP.items() if key != "BACH_HARVEST_SNAPSHOT"}
    result, calls = run_harvester(fake_tools, "--run", **overrides)
    assert result.returncode == 0, result.stderr
    assert "Snapshot aus" in result.stdout
    for forbidden in ("git diff --name-only", "git read-tree", "git add", "git push", "gh pr"):
        assert forbidden not in calls


def test_snapshot_off_still_harvests_committed_work(fake_tools):
    live_file(fake_tools, RESCUED)
    result, calls = run_harvester(fake_tools, "--run", FAKE_DIRTY=" M " + RESCUED)
    assert result.returncode == 0, result.stderr
    assert f"{DEFAULT_HEAD}:refs/heads/{DEFAULT_BRANCH}" in calls
    assert "git read-tree" not in calls
    assert "git commit-tree" not in calls


def test_snapshot_stages_only_tracked_modified_allowlisted_files(fake_tools):
    names = ["system/hub/a.py", "docs/notes.md", "system/data/state.json", "system/gui/data/cache.py",
             "bach.db", "system/logs/run.py", "system/hub/settings.json"]
    for name in names:
        live_file(fake_tools, name)
    result, calls = run_harvester(fake_tools, "--run", **{**SNAP, "FAKE_SNAPSHOT_PATHS": "".join(n + "\\0" for n in names)},
                                  FAKE_PR_HEAD=SNAPSHOT_BRANCH, FAKE_PR_OID=SNAPSHOT_COMMIT)
    assert result.returncode == 0, result.stderr
    assert staged(calls) == ["system/hub/a.py", "docs/notes.md"]
    assert "literal-pathspecs=1" in calls
    assert "git diff --name-only -z --diff-filter=M" in calls
    assert "git add -A" not in calls
    assert "[SNAPSHOT] 2 getrackte Allowlist-Dateien, 5 ausgelassen" in result.stdout


def test_snapshot_without_allowlisted_files_pushes_nothing(fake_tools):
    live_file(fake_tools, "system/data/state.json")
    result, calls = run_harvester(fake_tools, "--run", **{**SNAP, "FAKE_SNAPSHOT_PATHS": "system/data/state.json\\0"})
    assert result.returncode == 0, result.stderr
    for forbidden in ("git read-tree", "git push", "gh pr create"):
        assert forbidden not in calls


@pytest.mark.parametrize(("size", "returncode"), [(5 * 1024 * 1024, 0), (5 * 1024 * 1024 + 1, 1)])
def test_size_limit_is_byte_exact_for_non_ascii_paths(fake_tools, size, returncode):
    name = "system/hub/größe_über.py"
    live_file(fake_tools, name, b"#" * size)
    result, calls = run_harvester(fake_tools, "--run", **{**SNAP, "FAKE_SNAPSHOT_PATHS": name + "\\0"},
                                  FAKE_PR_HEAD=SNAPSHOT_BRANCH, FAKE_PR_OID=SNAPSHOT_COMMIT)
    assert result.returncode == returncode, result.stderr
    if returncode:
        assert "über 5 MB" in result.stderr
        assert "git push" not in calls
    else:
        assert staged(calls) == [name]


def test_listed_but_missing_snapshot_path_fails_closed(fake_tools):
    result, calls = run_harvester(fake_tools, "--run", **SNAP)
    assert result.returncode == 1
    assert "keine reguläre Datei" in result.stderr
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
