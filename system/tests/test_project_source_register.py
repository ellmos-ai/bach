"""Tests für das Projektquellen-Register (hub._services.project_source_register).

Task #2400a — ergänzt docs/architecture/PROJECT-SOURCE-REGISTER-v1.md.
"""

import subprocess

import pytest

from hub._services import project_source_register as psr

ORIGIN = "https://github.com/ellmos-ai/bach"


@pytest.fixture(autouse=True)
def _register_db(tmp_path, monkeypatch):
    """Register-DB pro Test nach tmp_path umlenken."""
    monkeypatch.setattr(psr, "_DB_PATH_OVERRIDE", str(tmp_path / "register.db"))


def _fake_checkout(tmp_path, name="checkout"):
    """Checkout-Attrappe: Verzeichnis mit .git-Unterordner, ohne echtes git."""
    checkout = tmp_path / name
    (checkout / ".git").mkdir(parents=True)
    return checkout


def _git_checkout(tmp_path, name="repo", origin=ORIGIN):
    """Echtes git init (optional mit remote origin), ohne Commit."""
    checkout = tmp_path / name
    checkout.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
    if origin is not None:
        subprocess.run(
            ["git", "remote", "add", "origin", origin], cwd=checkout, check=True
        )
    return checkout


def _add_bach(checkout, tmp_path, repo_key="bach", origin=ORIGIN):
    return psr.add_entry(
        actor="user",
        repo_key=repo_key,
        checkout_path=str(checkout),
        origin=origin,
        approved_ref="a" * 40,
        worktrees_root=str(tmp_path),
    )


# --- validate_repo_key ---------------------------------------------------


def test_validate_repo_key_accepts_lowercase():
    psr.validate_repo_key("bach")
    psr.validate_repo_key("a")
    psr.validate_repo_key("a-b-2")
    psr.validate_repo_key("a" * 64)


@pytest.mark.parametrize(
    "bad", ["", "Bach", "-abc", "a b", "ba/ch", "a" * 65, "bach_2"]
)
def test_validate_repo_key_rejects_invalid(bad):
    with pytest.raises(RuntimeError):
        psr.validate_repo_key(bad)


# --- validate_origin -----------------------------------------------------


def test_validate_origin_accepts_https():
    psr.validate_origin(ORIGIN)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "http://github.com/ellmos-ai/bach",
        "https://user@github.com/ellmos-ai/bach",
        "https://user:pw@github.com/ellmos-ai/bach",
        "https://github.com/ellmos-ai/bach?ref=main",
        "https://github.com/ellmos-ai/bach#section",
        "git@github.com:ellmos-ai/bach.git",
        "ssh://git@github.com/ellmos-ai/bach.git",
        "ftp://example.com/x.git",
    ],
)
def test_validate_origin_rejects_invalid(bad):
    with pytest.raises(RuntimeError):
        psr.validate_origin(bad)


# --- validate_checkout_path ---------------------------------------------


def test_validate_checkout_path_accepts_real_dir(tmp_path):
    checkout = _fake_checkout(tmp_path)
    psr.validate_checkout_path(str(checkout))


def test_validate_checkout_path_accepts_git_checkout(tmp_path):
    checkout = _git_checkout(tmp_path)
    psr.validate_checkout_path(str(checkout))


def test_validate_checkout_path_rejects_relative(tmp_path):
    _fake_checkout(tmp_path)
    with pytest.raises(RuntimeError):
        psr.validate_checkout_path("checkout")


def test_validate_checkout_path_rejects_missing(tmp_path):
    with pytest.raises(RuntimeError):
        psr.validate_checkout_path(str(tmp_path / "fehlt"))


def test_validate_checkout_path_rejects_without_gitdir(tmp_path):
    checkout = tmp_path / "ohne-git"
    checkout.mkdir()
    with pytest.raises(RuntimeError):
        psr.validate_checkout_path(str(checkout))


def test_validate_checkout_path_rejects_symlinked_checkout(tmp_path):
    real = _fake_checkout(tmp_path, "real")
    link = tmp_path / "checkout-link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(RuntimeError):
        psr.validate_checkout_path(str(link))


def test_validate_checkout_path_rejects_symlinked_gitdir(tmp_path):
    target = tmp_path / "git-target"
    target.mkdir()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".git").symlink_to(target, target_is_directory=True)
    with pytest.raises(RuntimeError):
        psr.validate_checkout_path(str(checkout))


# --- actor-Guard ---------------------------------------------------------


def test_require_user_rejects_non_user_actor():
    with pytest.raises(RuntimeError, match="Registerpflege"):
        psr._require_user("daemon")


def test_require_user_accepts_user_actor():
    psr._require_user("user")


def test_add_entry_rejects_non_user_actor(tmp_path):
    checkout = _fake_checkout(tmp_path)
    with pytest.raises(RuntimeError, match="Registerpflege"):
        psr.add_entry(
            actor="daemon",
            repo_key="bach",
            checkout_path=str(checkout),
            worktrees_root=str(tmp_path),
        )


# --- add_entry / read_entry / register_revision --------------------------


def test_add_entry_read_entry_roundtrip(tmp_path):
    checkout = _fake_checkout(tmp_path)
    result = _add_bach(checkout, tmp_path)
    assert isinstance(result, dict)
    entry = psr.read_entry("bach")
    assert entry["repo_key"] == "bach"
    assert entry["revision"] == 1
    assert entry["origin"] == ORIGIN
    assert entry["approved_ref"] == "a" * 40
    assert entry["checkout_path"]
    assert entry["worktrees_root"]


def test_register_revision_starts_at_one(tmp_path):
    checkout = _fake_checkout(tmp_path)
    _add_bach(checkout, tmp_path)
    assert psr.register_revision("bach") == 1


def test_add_entry_duplicate_key_raises(tmp_path):
    checkout = _fake_checkout(tmp_path)
    _add_bach(checkout, tmp_path)
    other = _fake_checkout(tmp_path, "checkout-2")
    with pytest.raises(RuntimeError, match="bereits registriert"):
        _add_bach(other, tmp_path)


# --- update_entry / remove_entry -----------------------------------------


def test_update_entry_bumps_revision(tmp_path):
    checkout = _fake_checkout(tmp_path)
    _add_bach(checkout, tmp_path)
    psr.update_entry(
        actor="user",
        repo_key="bach",
        checkout_path=str(checkout),
        origin=ORIGIN,
        approved_ref="b" * 40,
        worktrees_root=str(tmp_path),
    )
    assert psr.register_revision("bach") == 2
    entry = psr.read_entry("bach")
    assert entry["revision"] == 2
    assert entry["approved_ref"] == "b" * 40


def test_update_entry_missing_key_raises(tmp_path):
    checkout = _fake_checkout(tmp_path)
    with pytest.raises(RuntimeError):
        psr.update_entry(
            actor="user",
            repo_key="gibts-nicht",
            checkout_path=str(checkout),
            worktrees_root=str(tmp_path),
        )


def test_remove_entry_then_readd_starts_at_revision_one(tmp_path):
    checkout = _fake_checkout(tmp_path)
    _add_bach(checkout, tmp_path)
    psr.update_entry(
        actor="user",
        repo_key="bach",
        checkout_path=str(checkout),
        worktrees_root=str(tmp_path),
    )
    assert psr.remove_entry(actor="user", repo_key="bach") is None
    _add_bach(checkout, tmp_path)
    assert psr.read_entry("bach")["revision"] == 1


def test_remove_entry_missing_key_raises(tmp_path):
    with pytest.raises(RuntimeError):
        psr.remove_entry(actor="user", repo_key="gibts-nicht")


# --- resolve_repo ---------------------------------------------------------


def test_resolve_repo_requires_expected_revision(tmp_path):
    checkout = _git_checkout(tmp_path)
    _add_bach(checkout, tmp_path)
    with pytest.raises(RuntimeError, match="expected_revision"):
        psr.resolve_repo("bach", None)


def test_resolve_repo_revision_mismatch_raises(tmp_path):
    checkout = _git_checkout(tmp_path)
    _add_bach(checkout, tmp_path)
    with pytest.raises(RuntimeError, match="Register-Revision divergiert"):
        psr.resolve_repo("bach", 99)


def test_resolve_repo_returns_registered_checkout(tmp_path):
    checkout = _git_checkout(tmp_path)
    _add_bach(checkout, tmp_path)
    resolved = psr.resolve_repo("bach", 1)
    assert str(resolved) == str(checkout.resolve())


def test_resolve_repo_origin_mismatch_raises(tmp_path):
    checkout = _git_checkout(tmp_path, origin="https://example.com/other.git")
    _add_bach(checkout, tmp_path, origin=ORIGIN)
    with pytest.raises(RuntimeError, match="origin des Projekt-Checkouts weicht"):
        psr.resolve_repo("bach", 1)