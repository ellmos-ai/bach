"""Explicit local token sources for the Control API client."""

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
