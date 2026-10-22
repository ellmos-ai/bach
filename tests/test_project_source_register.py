import os
import subprocess
from pathlib import Path

import pytest

from hub._services import project_source_register as register

URL = "https://example.invalid/team/repo.git"


def _git(repo, *args):
    proc = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    return proc


def _make_repo(parent, *, name="repo", url=URL):
    repo = parent / name
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "bot@example.invalid")
    _git(repo, "config", "user.name", "Bot")
    _git(repo, "remote", "add", "origin", url)
    _git(repo, "commit", "--allow-empty", "-m", "init")
    return repo


@pytest.fixture(autouse=True)
def _register_db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        register, "_DB_PATH_OVERRIDE", str(tmp_path / "register.sqlite3")
    )


@pytest.fixture
def repo(tmp_path):
    return _make_repo(tmp_path)


@pytest.mark.parametrize(
    "repo_key", ["Bach", "", "-lead", "mit leer", "ümlaut", "a" * 65]
)
def test_validate_repo_key_rejects_invalid(repo_key):
    with pytest.raises(RuntimeError, match="repo_key ungültig"):
        register.validate_repo_key(repo_key)


@pytest.mark.parametrize("repo_key", ["repo", "team-1", "0start", "a" * 64])
def test_validate_repo_key_accepts_valid(repo_key):
    register.validate_repo_key(repo_key)


def test_validate_origin_requires_https():
    with pytest.raises(RuntimeError, match="origin muss eine https-URL sein"):
        register.validate_origin("http://example.invalid/team/repo.git")


def test_validate_origin_rejects_userinfo():
    with pytest.raises(
        RuntimeError, match="origin darf keine Nutzerinformationen enthalten"
    ):
        register.validate_origin("https://user@example.invalid/team/repo.git")


@pytest.mark.parametrize("origin", [f"{URL}?q=1", f"{URL}#frag"])
def test_validate_origin_rejects_query_and_fragment(origin):
    with pytest.raises(
        RuntimeError, match="origin darf keine Query- oder Fragmentanteile enthalten"
    ):
        register.validate_origin(origin)


def test_validate_origin_rejects_spaces():
    with pytest.raises(RuntimeError, match="origin darf keine Leerzeichen enthalten"):
        register.validate_origin("https://example.invalid/team/re po.git")


def test_validate_origin_strips_and_returns_url():
    assert register.validate_origin(f"  {URL} ") == URL


@pytest.mark.parametrize(
    "checkout_path", ["relative/checkout", Path("relative/checkout"), 42]
)
def test_validate_checkout_path_requires_absolute_path(checkout_path):
    with pytest.raises(
        RuntimeError, match="checkout_path muss ein absoluter Pfad sein"
    ):
        register.validate_checkout_path(checkout_path)


def test_validate_checkout_path_requires_git_directory(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(RuntimeError, match=r"checkout_path enthält kein \.git"):
        register.validate_checkout_path(empty)


def test_validate_checkout_path_rejects_symlink(tmp_path, repo):
    link = tmp_path / "repo-link"
    os.symlink(repo, link)
    with pytest.raises(RuntimeError, match="checkout_path darf kein Symlink sein"):
        register.validate_checkout_path(link)


def test_validate_checkout_path_accepts_checkout(repo):
    assert register.validate_checkout_path(repo) == repo


def test_register_maintenance_is_user_only(repo):
    with pytest.raises(RuntimeError, match="Registerpflege"):
        register.add_entry(actor="system", repo_key="repo", checkout_path=repo)
    entry = register.add_entry(actor="user", repo_key="repo", checkout_path=repo)
    assert entry["repo_key"] == "repo"
    with pytest.raises(RuntimeError, match="Registerpflege"):
        register.update_entry(actor="assistant", repo_key="repo")
    with pytest.raises(RuntimeError, match="Registerpflege"):
        register.remove_entry(actor="worker", repo_key="repo")


def test_add_entry_populates_fields(repo):
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    entry = register.add_entry(actor="user", repo_key="repo", checkout_path=repo)
    assert entry["origin"] == URL
    assert entry["approved_ref"] == head
    assert entry["revision"] == 1
    assert Path(entry["checkout_path"]) == repo
    assert entry["worktrees_root"] == str(Path.home() / "services" / "repo-worktrees")
    assert register.register_revision("repo") == 1


def test_list_entries_returns_multiple_entries(tmp_path):
    repo_a = _make_repo(
        tmp_path, name="repo-a", url="https://example.invalid/team/repo-a.git"
    )
    repo_b = _make_repo(
        tmp_path, name="repo-b", url="https://example.invalid/team/repo-b.git"
    )
    register.add_entry(actor="user", repo_key="alpha", checkout_path=repo_a)
    register.add_entry(actor="user", repo_key="beta", checkout_path=repo_b)
    entries = register.list_entries()
    assert len(entries) == 2
    assert {entry["repo_key"] for entry in entries} == {"alpha", "beta"}
    assert register.read_entry("alpha")["revision"] == 1


def test_add_entry_rejects_duplicate(repo):
    register.add_entry(actor="user", repo_key="repo", checkout_path=repo)
    with pytest.raises(RuntimeError, match="ist bereits registriert"):
        register.add_entry(actor="user", repo_key="repo", checkout_path=repo)


def test_update_entry_bumps_revision(repo):
    register.add_entry(actor="user", repo_key="repo", checkout_path=repo)
    entry = register.update_entry(actor="user", repo_key="repo")
    assert entry["revision"] == 2
    assert register.register_revision("repo") == 2


def test_remove_entry_deletes_entry_once(repo):
    register.add_entry(actor="user", repo_key="repo", checkout_path=repo)
    assert register.remove_entry(actor="user", repo_key="repo") is None
    with pytest.raises(RuntimeError, match="Kein Projektquellen-Registereintrag"):
        register.remove_entry(actor="user", repo_key="repo")


def test_resolve_repo_requires_registered_entry(repo):
    register.add_entry(actor="user", repo_key="repo", checkout_path=repo)
    with pytest.raises(RuntimeError, match="Kein Projektquellen-Registereintrag"):
        register.resolve_repo("missing", 1)


def test_resolve_repo_requires_expected_revision(repo):
    register.add_entry(actor="user", repo_key="repo", checkout_path=repo)
    with pytest.raises(RuntimeError, match="expected_revision erforderlich"):
        register.resolve_repo("repo", None)
    with pytest.raises(RuntimeError, match="expected_revision muss eine Ganzzahl sein"):
        register.resolve_repo("repo", "abc")
    assert register.resolve_repo("repo", "1") == repo


def test_resolve_repo_detects_revision_divergence(repo):
    register.add_entry(actor="user", repo_key="repo", checkout_path=repo)
    register.update_entry(actor="user", repo_key="repo")
    with pytest.raises(RuntimeError, match="Register-Revision divergiert"):
        register.resolve_repo("repo", 1)


def test_resolve_repo_checks_live_origin_and_expected_origin(repo):
    register.add_entry(actor="user", repo_key="repo", checkout_path=repo)
    _git(repo, "remote", "set-url", "origin", "https://example.invalid/other.git")
    with pytest.raises(RuntimeError, match="origin des Projekt-Checkouts weicht"):
        register.resolve_repo("repo", 1)
    _git(repo, "remote", "set-url", "origin", URL)
    with pytest.raises(RuntimeError, match="expected_origin weicht"):
        register.resolve_repo(
            "repo", 1, expected_origin="https://example.invalid/other.git"
        )
    assert register.resolve_repo("repo", 1, expected_origin=URL) == repo


def test_resolve_repo_rejects_symlinked_checkout(tmp_path, repo):
    register.add_entry(actor="user", repo_key="repo", checkout_path=repo)
    moved = tmp_path / "repo-moved"
    repo.rename(moved)
    os.symlink(moved, repo)
    with pytest.raises(RuntimeError, match="checkout_path darf kein Symlink sein"):
        register.resolve_repo("repo", 1)