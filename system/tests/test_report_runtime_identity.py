# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""T-20261111-107529991: Veralteter gitloser Spiegel darf den Cloud-Weg nicht oeffnen.

Echte Git-Repos in tmp_path, nur erfundene Dateien, kein Netz, kein Modell.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.document import report_runtime_identity as rid  # noqa: E402
from hub._services.document import report_workflow_service as rws  # noqa: E402

REL = Path(rid._REL)


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True)


@pytest.fixture
def clone(tmp_path):
    repo = tmp_path / "clone"
    (repo / REL).mkdir(parents=True)
    (repo / REL / "gate.py").write_text("def require_cloud_ner(): ...\n", encoding="utf-8", newline="\n")
    (repo / REL / "sub").mkdir()
    (repo / REL / "sub" / "x.py").write_text("X = 1\n", encoding="utf-8", newline="\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


def _mirror(tmp_path, clone, monkeypatch):
    mirror = tmp_path / "mirror"
    shutil.copytree(clone / REL, mirror / REL)
    (mirror / "REPO.pointer.json").write_text(
        json.dumps({"default_branch": "main", "onedrive_mirror": {"source_commit": "abc123456789"}}), encoding="utf-8")
    monkeypatch.setenv("BACH_CANONICAL_CLONE", str(clone))
    return mirror


def test_identical_mirror_is_ok(tmp_path, clone, monkeypatch):
    assert rid.check_identity(_mirror(tmp_path, clone, monkeypatch))["status"] == "ok"


def test_crlf_mirror_is_still_ok(tmp_path, clone, monkeypatch):
    mirror = _mirror(tmp_path, clone, monkeypatch)
    gate = mirror / REL / "gate.py"
    gate.write_bytes(gate.read_bytes().replace(b"\n", b"\r\n"))
    assert rid.check_identity(mirror)["status"] == "ok"


def test_old_gate_file_is_stale_and_named(tmp_path, clone, monkeypatch):
    mirror = _mirror(tmp_path, clone, monkeypatch)
    (mirror / REL / "gate.py").write_text("# alter Stand ohne Sperre\n", encoding="utf-8")
    result = rid.check_identity(mirror)
    assert result["status"] == "stale"
    assert result["differing"] == ["gate.py"]
    assert result["source_commit"] == "abc123456789"


def test_missing_and_extra_files_are_stale(tmp_path, clone, monkeypatch):
    mirror = _mirror(tmp_path, clone, monkeypatch)
    (mirror / REL / "sub" / "x.py").unlink()
    (mirror / REL / "extra.py").write_text("Y = 2\n", encoding="utf-8")
    assert rid.check_identity(mirror)["differing"] == ["extra.py", "sub/x.py"]


def test_no_clone_is_unverified_not_stale(tmp_path, clone, monkeypatch):
    mirror = _mirror(tmp_path, clone, monkeypatch)
    monkeypatch.setenv("BACH_CANONICAL_CLONE", str(tmp_path / "nirgends"))
    assert rid.check_identity(mirror)["status"] == "unverified"


def test_git_checkout_never_blocks(clone):
    (clone / REL / "gate.py").write_text("# Entwicklungsstand\n", encoding="utf-8")
    result = rid.check_identity(clone)
    assert result["status"] == "checkout" and result["differing"] == ["gate.py"]


def test_cloud_gate_refuses_stale_runtime(monkeypatch):
    monkeypatch.setattr(rid, "runtime_identity", lambda: {
        "status": "stale", "differing": ["gate.py"], "source_commit": "29eb713", "canonical_commit": "9ce0c89"})
    with pytest.raises(rws.PromptPrivacyError) as exc:
        rws.require_cloud_ner()  # Identitaet kommt vor der NER-Pruefung
    assert exc.value.code == "runtime_stale"
    assert "29eb713" in str(exc.value)


def test_cloud_gate_passes_identity_when_ok(monkeypatch):
    monkeypatch.setattr(rid, "runtime_identity", lambda: {"status": "ok"})
    rws.require_runtime_identity()  # wirft nicht


def test_this_checkout_is_not_stale():
    assert rid.check_identity()["status"] in ("checkout", "ok", "unverified")


def test_empty_dot_git_dir_does_not_hide_stale_mirror(tmp_path, clone, monkeypatch):
    """Reale OneDrive-Projektion: leeres .git-Verzeichnis darf nicht als Checkout gelten."""
    mirror = _mirror(tmp_path, clone, monkeypatch)
    (mirror / ".git").mkdir()
    (mirror / REL / "gate.py").write_text("# alter Stand ohne Sperre\n", encoding="utf-8")
    assert rid.check_identity(mirror)["status"] == "stale"


def test_conflict_copy_is_not_an_extra_module(tmp_path, clone, monkeypatch):
    mirror = _mirror(tmp_path, clone, monkeypatch)
    (mirror / REL / "gate-WORKSTATION-LG.py").write_text("# Konfliktkopie\n", encoding="utf-8")
    assert rid.check_identity(mirror)["status"] == "ok"
