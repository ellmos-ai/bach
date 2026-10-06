"""Regression tests for the BACH Control API authentication boundary."""

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("telegram", reason="braucht python-telegram-bot (T-20260927-232943082)")

from hub._services.chat import control_auth
from hub._services.chat.telegram_chat import ControlHandler, _control_bind_host


def _handler(headers, path):
    handler = ControlHandler.__new__(ControlHandler)
    handler.headers = headers
    handler.path = path
    handler.wfile = MagicMock()
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    return handler


def test_bearer_token_comparison_fails_closed():
    with patch.object(control_auth, "get_control_api_token", return_value="control-secret"):
        assert control_auth.is_control_api_authorized(
            {"Authorization": "Bearer control-secret"}
        ) is True
        assert control_auth.is_control_api_authorized(
            {"Authorization": "Bearer wrong-secret"}
        ) is False
        assert control_auth.is_control_api_authorized({}) is False
        assert control_auth.is_control_api_authorized(
            {"Authorization": "Basic control-secret"}
        ) is False

    with patch.object(control_auth, "get_control_api_token", return_value=""):
        assert control_auth.is_control_api_authorized(
            {"Authorization": "Bearer control-secret"}
        ) is False


def test_post_without_token_is_rejected_before_sink():
    handler = _handler({"Content-Type": "application/json"}, "/api/fackel")
    with patch.object(control_auth, "get_control_api_token", return_value=""), \
         patch.object(handler, "_json") as response, \
         patch.object(handler, "_read_body") as read_body, \
         patch("hub._services.chat.telegram_chat.set_fackel_preference") as set_pref:
        handler.do_POST()

    response.assert_called_once_with(
        {"error": "Control-API-Token erforderlich oder ungültig"}, 401
    )
    read_body.assert_not_called()
    set_pref.assert_not_called()


def test_delete_without_token_is_rejected_before_sink():
    handler = _handler({}, "/api/workers?id=worker-1")
    with patch.object(control_auth, "get_control_api_token", return_value=""), \
         patch.object(handler, "_json") as response, \
         patch("hub._services.chat.telegram_chat.remove_worker") as remove_worker:
        handler.do_DELETE()

    response.assert_called_once_with(
        {"error": "Control-API-Token erforderlich oder ungültig"}, 401
    )
    remove_worker.assert_not_called()


def test_valid_token_allows_json_post_guard(monkeypatch):
    monkeypatch.setattr(control_auth, "get_control_api_token", lambda: "control-secret")
    handler = _handler(
        {
            "Authorization": "Bearer control-secret",
            "Content-Type": "application/json; charset=utf-8",
        },
        "/api/fackel",
    )
    assert handler._allow_json_post() is True


def test_remote_bind_requires_configured_token(monkeypatch):
    monkeypatch.setenv("BACH_CONTROL_HOST", "0.0.0.0")
    monkeypatch.setenv("BACH_CONTROL_ALLOW_REMOTE", "1")
    monkeypatch.setattr(
        "hub._services.chat.telegram_chat.get_control_api_token",
        lambda: "",
    )

    try:
        _control_bind_host()
    except ValueError as exc:
        assert "Bearer-Token" in str(exc)
    else:
        raise AssertionError("Remote-Bind darf ohne Token nicht zugelassen werden")


@pytest.mark.parametrize("authorization", [None, "", "Bearer wrong", "Basic control-secret"])
def test_auth_check_rejects_missing_or_invalid_token(monkeypatch, authorization):
    monkeypatch.setattr(control_auth, "get_control_api_token", lambda: "control-secret")
    headers = {"Authorization": authorization} if authorization is not None else {}
    handler = _handler(headers, "/api/auth/check")
    with patch.object(handler, "_json") as response, \
         patch("hub._services.chat.telegram_chat.runtime") as runtime, \
         patch("hub._services.chat.telegram_chat.add_worker") as add_worker, \
         patch("hub._services.chat.telegram_chat.remove_worker") as remove_worker:
        handler.do_GET()
    response.assert_called_once_with(
        {"error": "Control-API-Token erforderlich oder ungültig"}, 401
    )
    assert runtime.mock_calls == []
    add_worker.assert_not_called()
    remove_worker.assert_not_called()


def test_auth_check_valid_token_is_readonly(monkeypatch):
    monkeypatch.setattr(control_auth, "get_control_api_token", lambda: "control-secret")
    handler = _handler({"Authorization": "Bearer control-secret"}, "/api/auth/check")
    with patch.object(handler, "_json") as response, \
         patch("hub._services.chat.telegram_chat.runtime") as runtime, \
         patch("hub._services.chat.telegram_chat.add_worker") as add_worker, \
         patch("hub._services.chat.telegram_chat.remove_worker") as remove_worker:
        handler.do_GET()
    response.assert_called_once_with(
        {"service": "bach-chat-control", "authenticated": True}
    )
    assert runtime.mock_calls == []
    add_worker.assert_not_called()
    remove_worker.assert_not_called()


def test_auth_check_retains_origin_policy(monkeypatch):
    monkeypatch.setattr(control_auth, "get_control_api_token", lambda: "control-secret")
    handler = _handler({"Authorization": "Bearer control-secret",
                        "Host": "127.0.0.1:8081", "Origin": "https://foreign.invalid"},
                       "/api/auth/check")
    with patch.object(handler, "_json") as response:
        handler.do_GET()
    response.assert_called_once_with({"error": "Fremd-Origin nicht erlaubt"}, 403)


def test_cors_preserves_ipv6_origin():
    handler = _handler(
        {"Host": "[::1]:8081", "Origin": "http://[::1]:8081"},
        "/api/status",
    )

    handler._cors()

    handler.send_header.assert_any_call(
        "Access-Control-Allow-Origin", "http://[::1]:8081"
    )


@pytest.mark.parametrize("origin", ["http://localhost:abc", "http://localhost:99999"])
def test_cors_ignores_origins_with_malformed_ports(origin):
    handler = _handler(
        {"Host": "localhost:8081", "Origin": origin},
        "/api/status",
    )

    handler._cors()

    assert not any(
        call.args[0] == "Access-Control-Allow-Origin"
        for call in handler.send_header.call_args_list
    )


def test_auth_check_without_server_token_fails_closed(monkeypatch):
    monkeypatch.setattr(control_auth, "get_control_api_token", lambda: "")
    handler = _handler({"Authorization": "Bearer control-secret"}, "/api/auth/check")
    with patch.object(handler, "_json") as response:
        handler.do_GET()
    response.assert_called_once_with(
        {"error": "Control-API-Token erforderlich oder ungültig"}, 401
    )


def test_active_device_token_authorizes_control_api(monkeypatch):
    monkeypatch.setattr(control_auth, "get_control_api_token", lambda: "")
    with patch("gui.device_auth.validate_token", return_value={"id": 1, "name": "browser", "status": "active"}):
        assert control_auth.is_control_api_authorized(
            {"Authorization": "Bearer active-device-token"}
        ) is True


def test_revoked_device_token_is_rejected(monkeypatch):
    monkeypatch.setattr(control_auth, "get_control_api_token", lambda: "")
    with patch("gui.device_auth.validate_token", return_value={"id": 1, "name": "browser", "status": "revoked"}):
        assert control_auth.is_control_api_authorized(
            {"Authorization": "Bearer revoked-device-token"}
        ) is False


def test_auth_check_accepts_valid_device_token(monkeypatch):
    monkeypatch.setattr(control_auth, "get_control_api_token", lambda: "")
    handler = _handler({"Authorization": "Bearer active-device-token"}, "/api/auth/check")
    with patch("gui.device_auth.validate_token", return_value={"id": 1, "name": "browser", "status": "active"}), \
         patch.object(handler, "_json") as response:
        handler.do_GET()
    response.assert_called_once_with(
        {"service": "bach-chat-control", "authenticated": True}
    )

