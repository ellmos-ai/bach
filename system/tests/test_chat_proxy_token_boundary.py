"""The GUI proxy forwards Control credentials without treating them as device tokens."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from gui import server


class ChatProxyTokenBoundaryTests(unittest.TestCase):
    def test_bridge_only_discovery_requires_typed_chat_identity(self):
        class Upstream:
            typed = True

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, _url, headers=None):
                return httpx.Response(200, json={"service": "bach-chat-control" if self.typed else "other",
                                                 "telegram_verified": False})

            async def request(self, _method, _url, **_kwargs):
                return httpx.Response(200, json={"available": True})

        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            discovery = runtime / "discovery.json"
            discovery.write_text(json.dumps({"root": str(server.BACH_DIR.parent),
                                             "services": {"bridge": {"actual_port": 9999}}}), encoding="utf-8")
            upstream = Upstream()
            with patch.object(server, "_startspine_runtime_dir", return_value=runtime), patch.dict(
                "os.environ", {"BACH_CONTROL_PORT": "18181"}
            ), patch.object(server, "has_active_devices", return_value=True), patch.object(
                httpx, "AsyncClient", side_effect=lambda **_kwargs: upstream
            ):
                self.assertEqual(server._chat_control_base_url(), "http://127.0.0.1:18181/api")
                client = TestClient(server.app)
                self.assertEqual(client.get("/api/chat-control/readiness").status_code, 200)
                upstream.typed = False
                self.assertEqual(client.get("/api/chat-control/readiness").status_code, 503)
                discovery.write_text(json.dumps({"root": str(server.BACH_DIR.parent),
                                                 "services": {"chat": {"host": "evil.example", "actual_port": 18181}}}),
                                     encoding="utf-8")
                self.assertIsNone(server._chat_control_base_url())
                discovery.write_text(json.dumps({"root": str(runtime / "other"),
                                                 "services": {"bridge": {}}}), encoding="utf-8")
                self.assertIsNone(server._chat_control_base_url())

    def test_get_and_post_use_distinct_control_authority(self):
        seen = []

        class Upstream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, url, headers=None):
                if url.endswith("/auth/check"):
                    if (headers or {}).get("authorization") == "Bearer control-secret":
                        return httpx.Response(200, json={"service": "bach-chat-control", "authenticated": True})
                    return httpx.Response(401, json={"authenticated": False})
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
            for path in ("history?chat_id=gui-web", "sessions?limit=1", "session?id=1"):
                url = "/api/chat-control/" + path
                self.assertEqual(client.get(url).status_code, 401)
                self.assertEqual(client.get(url, headers={"Authorization": "Bearer fake"}).status_code, 401)
                self.assertEqual(client.get(url, headers=headers).status_code, 200)
            self.assertEqual(client.get("/api/agents/runtime", headers=headers).status_code, 401)
        self.assertEqual(seen[:2], [
            ("GET", "http://127.0.0.1:8127/api/history", "Bearer control-secret"),
            ("POST", "http://127.0.0.1:8127/api/chat", "Bearer control-secret"),
        ])


if __name__ == "__main__":
    unittest.main()
