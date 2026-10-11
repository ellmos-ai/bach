"""Explicit local token sources for the Control API client."""

import pytest

from hub._services.chat import control_auth


def test_token_file_is_used_only_when_explicitly_configured(tmp_path, monkeypatch):
    token_file = tmp_path / "control-token.txt"
    token_file.write_text("file-secret\n", encoding="utf-8")
    monkeypatch.delenv("BACH_CONTROL_API_TOKEN", raising=False)
    monkeypatch.setenv("BACH_CONTROL_API_TOKEN_FILE", str(token_file))

    assert control_auth.get_control_api_auth_header() == "Bearer file-secret"
    monkeypatch.setenv("BACH_CONTROL_API_TOKEN", "environment-secret")
    assert control_auth.get_control_api_auth_header() == "Bearer environment-secret"


def test_explicit_missing_token_file_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("BACH_CONTROL_API_TOKEN", raising=False)
    monkeypatch.setenv("BACH_CONTROL_API_TOKEN_FILE", str(tmp_path / "missing"))

    assert control_auth.get_control_api_token() == ""

@pytest.fixture(autouse=True)
def isolated_control_credentials(tmp_path, monkeypatch):
    """No assertion or failure log may read an operator's actual credential."""
    monkeypatch.setattr(control_auth.Path, "home", classmethod(lambda cls: tmp_path))
    from hub import secrets_handler
    monkeypatch.setattr(secrets_handler, "get_secret_value", lambda _name: "")
    from gui import device_auth
    monkeypatch.setattr(device_auth, "validate_token", lambda _token: None)


@pytest.mark.parametrize("kind", ["missing", "empty", "blank", "undecodable", "directory"])
def test_explicit_unusable_file_never_falls_back(kind, tmp_path, monkeypatch):
    configured = tmp_path / "configured"
    if kind == "directory":
        configured.mkdir()
    elif kind != "missing":
        configured.write_bytes({"empty": b"", "blank": b" \n", "undecodable": b"\xff"}[kind])
    fallback = tmp_path / ".credentials" / "bach_control_api_token"
    fallback.parent.mkdir()
    fallback.write_text("unrelated-fixture-default", encoding="utf-8")
    calls = []
    from hub import secrets_handler
    monkeypatch.setattr(secrets_handler, "get_secret_value",
                        lambda name: calls.append(name) or "unrelated-fixture-keyring")
    monkeypatch.delenv(control_auth.CONTROL_API_TOKEN_ENV, raising=False)
    monkeypatch.setenv(control_auth.CONTROL_API_TOKEN_FILE_ENV, str(configured))
    assert control_auth.get_control_api_token() == ""
    assert calls == []
    assert not control_auth.is_control_api_authorized({"Authorization": "Bearer unrelated-fixture-default"})


def test_environment_token_has_priority_over_unusable_explicit_file(tmp_path, monkeypatch):
    monkeypatch.setenv(control_auth.CONTROL_API_TOKEN_ENV, "explicit-environment-fixture")
    monkeypatch.setenv(control_auth.CONTROL_API_TOKEN_FILE_ENV, str(tmp_path / "missing"))
    assert control_auth.get_control_api_token() == "explicit-environment-fixture"


def test_default_file_remains_available_without_explicit_configuration(tmp_path, monkeypatch):
    fallback = tmp_path / ".credentials" / "bach_control_api_token"
    fallback.parent.mkdir()
    fallback.write_text("default-fixture", encoding="utf-8")
    monkeypatch.delenv(control_auth.CONTROL_API_TOKEN_ENV, raising=False)
    monkeypatch.delenv(control_auth.CONTROL_API_TOKEN_FILE_ENV, raising=False)
    assert control_auth.get_control_api_token() == "default-fixture"
