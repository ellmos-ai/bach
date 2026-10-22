"""Tests für die Projekt-Bindung in worker_lease_binding (Task #2400b).

Ergänzt docs/architecture/PROJECT-SOURCE-REGISTER-v1.md; läuft gegen ein
echtes git-Checkout (init, Commit, remote origin https://...).
"""

import subprocess

import pytest

from hub._services import project_source_register as psr
from hub._services.chat.worker_lease_binding import _project_binding_for

ORIGIN = "https://github.com/ellmos-ai/bach"


@pytest.fixture(autouse=True)
def _register_db(tmp_path, monkeypatch):
    """Register-DB pro Test nach tmp_path umlenken."""
    monkeypatch.setattr(psr, "_DB_PATH_OVERRIDE", str(tmp_path / "register.db"))


@pytest.fixture
def git_checkout(tmp_path):
    checkout = tmp_path / "repo"
    checkout.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
    subprocess.run(
        ["git", "config", "user.email", "worker@example.com"],
        cwd=checkout,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Worker Test"], cwd=checkout, check=True
    )
    (checkout / "README.md").write_text("Probe-Commit\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=checkout, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=checkout, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", ORIGIN], cwd=checkout, check=True
    )
    return checkout


def _register_bach(checkout, tmp_path):
    psr.add_entry(
        actor="user",
        repo_key="bach",
        checkout_path=str(checkout),
        origin=ORIGIN,
        approved_ref="a" * 40,
        worktrees_root=str(tmp_path),
    )


def test_project_binding_for_pins_head_sha(git_checkout, tmp_path):
    _register_bach(git_checkout, tmp_path)
    result = _project_binding_for(1, {"repo_key": "bach"})
    assert result["repo_key"] == "bach"
    assert result["register_revision"] == 1
    assert "pinned_sha" in result
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=git_checkout,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert result["pinned_sha"] == head
    assert all(c in "0123456789abcdef" for c in result["pinned_sha"])


def test_project_binding_for_requires_repo_key():
    with pytest.raises(RuntimeError, match="ohne Projektquellen-Bindung"):
        _project_binding_for(1, {})