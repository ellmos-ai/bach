"""The GUI proxy forwards Control credentials without treating them as device tokens."""

import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from gui import server


class ChatProxyTokenBoundaryTests(unittest.TestCase):
    def test_get_and_post_use_distinct_control_authority(self):
        seen = []

        class Upstream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, _url, headers=None):
                return httpx.Response(200, json={"service": "bach-chat-control", "telegram_verified": False})

            async def request(self, method, url, **kwargs):
                token = kwargs["headers"].get("authorization")
                seen.append((method, url, token))
                if token != "Bearer control-secret":
                    return httpx.Response(401, json={"error": "Control-Token erforderlich"})
                return httpx.Response(200, json={"ok": True})

        with patch.object(server, "has_active_devices", return_value=True), patch.object(
            server, "validate_token", side_effect=lambda token: {"id": 1} if token == "device-secret" else None
        ), patch.object(server, "_chat_control_base_url", return_value="http://127.0.0.1:8127/api"), patch.object(
            httpx, "AsyncClient", side_effect=lambda **_kwargs: Upstream()
        ):
            client = TestClient(server.app)
            headers = {"Authorization": "Bearer control-secret"}
            get_response = client.get("/api/chat-control/history?chat_id=agent%3A1%3Aa&agent_id=1", headers=headers)
            post_response = client.post("/api/chat-control/chat", json={"prompt": "Hallo"}, headers=headers)
            self.assertEqual(get_response.status_code, 200)
            self.assertEqual(post_response.status_code, 200)
            self.assertEqual(client.post("/api/chat-control/chat", json={"prompt": "Hallo"}).status_code, 401)
            self.assertEqual(client.get("/api/agents/runtime", headers=headers).status_code, 401)
        self.assertEqual(seen[:2], [
            ("GET", "http://127.0.0.1:8127/api/history", "Bearer control-secret"),
            ("POST", "http://127.0.0.1:8127/api/chat", "Bearer control-secret"),
        ])


if __name__ == "__main__":
    unittest.main()
