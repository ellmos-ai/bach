# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for host-wide non-embargo hook_guards handling (#4243/#4241) and PB-27 Option A deprecation."""

from __future__ import annotations

import json
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub import bach_paths  # noqa: E402
from hub._services import skill_source_service  # noqa: E402
from hub._services.chat import worker_write_guard as guard  # noqa: E402
from hub._services.document import foerderbericht_pipeline as fp  # noqa: E402
from hub._services.document import report_workflow_service as rws  # noqa: E402


FORWARDER_BODY = (
    "#!/bin/sh\n"
    "# Global core.hooksPath hides each repo's .git/hooks. This forwarder is installed\n"
    "# under every other hook name and runs the repo's own hook unchanged.\n"
    'own="$(git rev-parse --git-common-dir)/hooks/$(basename "$0")"\n'
    'if [ -x "$own" ]; then exec "$own" "$@"; fi\n'
    "exit 0\n"
)

DATA_GATE_BODY = (
    "#!/bin/sh\n"
    "# Host-wide pre-push data gate (SEC-bach-rescue-tag-2026-11-22).\n"
    "exit 0\n"
)


def _setup_global_hooks(root: Path) -> Path:
    hooks_dir = root / ".config" / "git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    (hooks_dir / "pre-commit").write_text(FORWARDER_BODY, encoding="utf-8")
    (hooks_dir / "pre-receive").write_text(FORWARDER_BODY, encoding="utf-8")
    (hooks_dir / "pre-push").write_text(DATA_GATE_BODY, encoding="utf-8")
    return hooks_dir


def _global_guards_payload(hooks_dir: Path, checked: Path) -> dict:
    return {
        "checked": str(checked),
        "locks": [],
        "twin_status": "ok",
        "descendants_complete": True,
        "hook_guards": [
            {
                "hook": "pre-push",
                "path": str(hooks_dir / "pre-push"),
                "hint": "# Host-wide pre-push data gate (SEC-bach-rescue-tag-2026-11-22).",
                "embargo": False,
            },
            {
                "hook": "pre-commit",
                "path": str(hooks_dir / "pre-commit"),
                "hint": "# Global core.hooksPath hides each repo's .git/hooks.",
                "embargo": False,
            },
            {
                "hook": "pre-receive",
                "path": str(hooks_dir / "pre-receive"),
                "hint": "# Global core.hooksPath hides each repo's .git/hooks.",
                "embargo": False,
            },
        ],
    }


def test_hook_guards_empty_and_malformed_cases(tmp_path):
    assert guard.has_blocking_hook_guards({"locks": []}, tmp_path) is False
    assert guard.has_blocking_hook_guards({"locks": [], "hook_guards": []}, tmp_path) is False
    assert guard.has_blocking_hook_guards("not-a-dict", tmp_path) is True  # type: ignore[arg-type]
    assert guard.has_blocking_hook_guards({"hook_guards": "invalid"}, tmp_path) is True
    assert guard.has_blocking_hook_guards({"hook_guards": ["locked"]}, tmp_path) is True
    assert guard.has_blocking_hook_guards(
        {"hook_guards": [{"hook": None, "path": str(tmp_path), "embargo": False}]},
        tmp_path,
    ) is True


def test_global_non_embargo_hooks_pass_when_repo_has_no_local_hooks(tmp_path):
    hooks_dir = _setup_global_hooks(tmp_path / "home")
    repo = tmp_path / "repo"
    (repo / ".git" / "hooks").mkdir(parents=True)
    (repo / ".git" / "hooks" / "pre-push.sample").write_text("# sample", encoding="utf-8")

    payload = _global_guards_payload(hooks_dir, repo)
    assert guard.has_blocking_hook_guards(payload, repo, global_hooks_dir=hooks_dir) is False


def test_global_hooks_still_block_when_repo_local_hook_exists_behind_forwarder(tmp_path):
    hooks_dir = _setup_global_hooks(tmp_path / "home")
    repo = tmp_path / "repo"
    (repo / ".git" / "hooks").mkdir(parents=True)
    (repo / ".git" / "hooks" / "pre-push").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")

    payload = _global_guards_payload(hooks_dir, repo)
    assert guard.has_blocking_hook_guards(payload, repo, global_hooks_dir=hooks_dir) is True


def test_global_hooks_still_block_linked_worktree_when_common_dir_has_local_hook(tmp_path):
    hooks_dir = _setup_global_hooks(tmp_path / "home")
    main_git = tmp_path / "main_repo" / ".git"
    wt_gitdir = main_git / "worktrees" / "wt1"
    (main_git / "hooks").mkdir(parents=True)
    wt_gitdir.mkdir(parents=True)
    (wt_gitdir / "commondir").write_text("../..\n", encoding="utf-8")

    wt = tmp_path / "wt1"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {wt_gitdir}\n", encoding="utf-8")

    payload = _global_guards_payload(hooks_dir, wt)
    assert guard.has_blocking_hook_guards(payload, wt, global_hooks_dir=hooks_dir) is False

    (main_git / "hooks" / "pre-commit").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    assert guard.has_blocking_hook_guards(payload, wt, global_hooks_dir=hooks_dir) is True


def test_unrecognized_or_embargo_global_hook_blocks(tmp_path):
    hooks_dir = _setup_global_hooks(tmp_path / "home")
    repo = tmp_path / "repo"
    (repo / ".git" / "hooks").mkdir(parents=True)
    payload = _global_guards_payload(hooks_dir, repo)

    # Arbitrary blocking hook without recognized host-gate header must fail closed.
    (hooks_dir / "pre-push").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    assert guard.has_blocking_hook_guards(payload, repo, global_hooks_dir=hooks_dir) is True

    # Embargo signature inside otherwise recognized header must also fail closed.
    (hooks_dir / "pre-push").write_text(
        DATA_GATE_BODY + "# operator competition embargo\n", encoding="utf-8"
    )
    assert guard.has_blocking_hook_guards(payload, repo, global_hooks_dir=hooks_dir) is True


def test_skill_source_check_write_locks_accepts_strict_rc2_only_for_verified_global_hooks(
    tmp_path, monkeypatch
):
    fake_home = tmp_path / "home"
    hooks_dir = _setup_global_hooks(fake_home)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    repo = tmp_path / "skills_repo"
    (repo / ".git" / "hooks").mkdir(parents=True)
    tools_dir = tmp_path / "lock_tools"
    tools_dir.mkdir()
    (tools_dir / "lock_scan.py").write_text("# stub\n", encoding="utf-8")
    (tools_dir / "lock_roots.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("BACH_LOCK_TOOLS_ROOT", str(tools_dir))

    payload = _global_guards_payload(hooks_dir, repo.resolve())

    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 2, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(skill_source_service.subprocess, "run", fake_run)
    skill_source_service.check_write_locks(repo)

    # If a repo-local hook appears, check_write_locks must reject rc=2.
    (repo / ".git" / "hooks" / "pre-push").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    with pytest.raises(PermissionError):
        skill_source_service.check_write_locks(repo)


def test_pb27_foerderbericht_pipeline_deprecation_and_prompt_neutralization(tmp_path):
    assert fp.DEPRECATED is True
    assert fp.DEPRECATION_REPLACEMENT == "foerderplaner.provider_contract.v1"

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        fp.FoerderberichtPipeline(base_path=tmp_path / "berichte")
    assert any(
        issubclass(w.category, DeprecationWarning) and "foerderplaner" in str(w.message)
        for w in caught
    )

    service = rws.ReportWorkflowService(base_path=tmp_path / "rws")
    session = service.start_session()
    session.profile = rws.TempAnonymProfile(
        tarnname="Tarn Klient",
        original_name="Max Beispiel",
        fake_geburtsdatum="01.01.2016",
        mappings={"names": {}, "dates": {}},
    )

    class _Bundle:
        core_text = "Synthetischer Beobachtungstext."
        stufe2_text = ""

    session.bundle = _Bundle()
    prompt = service.generate_prompt(session, include_wissensdatenbank=False)
    combined = "\n".join(
        [
            prompt,
            str(rws.TEMPLATE_PATH),
            str(rws.ICF_REF_PATH),
            str(bach_paths.BERICHT_TEMPLATE),
            " ".join(rws.DEFAULT_WHITELIST),
        ]
    ).lower()
    for personal_term in (
        "geiger",
        "händle",
        "haendle",
        "proautismus",
        "loerrach",
        "lörrach",
        "waldshut",
        "schopfheim",
        "asperger",
        "75 minuten",
    ):
        assert personal_term not in combined, f"Personal/practice term still present: {personal_term}"
