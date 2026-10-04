"""Sessions route never serves Chat as a substitute for a missing Astro page."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, PlainTextResponse

from gui import server


class OceanSessionsPageTest(unittest.TestCase):
    def test_missing_build_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(server, "ASTRO_DIST_DIR", Path(tmp)):
                with self.assertRaises(HTTPException) as result:
                    asyncio.run(server.agenten_sessions_page())
        self.assertEqual(result.exception.status_code, 503)

    def test_existing_build_is_served(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "agenten" / "sessions.html"
            page.parent.mkdir()
            page.write_text("fixture", encoding="utf-8")
            with patch.object(server, "ASTRO_DIST_DIR", Path(tmp)):
                response = asyncio.run(server.agenten_sessions_page())
        self.assertIsInstance(response, FileResponse)
        self.assertEqual(Path(response.path).resolve(), page.resolve())

    def test_session_api_requires_device(self):
        middleware = server.DeviceAuthMiddleware(server.app)
        request = Request({"type": "http", "method": "GET", "path": "/api/memory/sessions",
                           "headers": [], "query_string": b""})

        async def next_response(_request):
            return PlainTextResponse("fixture")

        response = asyncio.run(middleware.dispatch(request, next_response))
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
