"""Private memory search rejects missing and revoked device credentials."""
import hashlib
import asyncio
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from gui.api import unified_api
from gui import server
from starlette.responses import PlainTextResponse


def request_with_token(token=None):
    headers = [] if token is None else [(b"authorization", ("Bearer " + token).encode())]
    return Request({"type": "http", "method": "GET", "path": "/api/memory/search",
                    "headers": headers, "query_string": b""})


class OceanMemoryAuthTest(unittest.TestCase):
    def test_missing_revoked_and_active_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "bach.db"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute("CREATE TABLE devices(id INTEGER PRIMARY KEY, token_hash TEXT, status TEXT)")
                conn.execute("INSERT INTO devices VALUES(1, ?, 'active')",
                             (hashlib.sha256(b"fixture-token").hexdigest(),))
                conn.execute("INSERT INTO devices VALUES(2, ?, 'revoked')",
                             (hashlib.sha256(b"revoked-token").hexdigest(),))
                conn.commit()
            before = db_path.stat().st_mtime_ns
            with patch.object(unified_api, "BACH_DB", db_path):
                with self.assertRaises(HTTPException) as missing:
                    unified_api._require_memory_device(request_with_token())
                self.assertEqual(missing.exception.status_code, 401)
                with self.assertRaises(HTTPException) as revoked:
                    unified_api._require_memory_device(request_with_token("revoked-token"))
                self.assertEqual(revoked.exception.status_code, 403)
                unified_api._require_memory_device(request_with_token("fixture-token"))
                unified_api._require_memory_device(request_with_token(" fixture-token "))
            self.assertEqual(db_path.stat().st_mtime_ns, before)

    def test_middleware_protects_legacy_memory_routes(self):
        middleware = server.DeviceAuthMiddleware(server.app)

        async def next_response(_request):
            return PlainTextResponse("ok")

        with patch.object(server, "validate_token", side_effect=lambda token: {"id": 1} if token == "active" else None):
            for path in ("/api/memory/facts", "/api/memory/facts/1", "/api/gardener/search"):
                scope = {"type": "http", "method": "GET", "path": path,
                         "headers": [], "query_string": b""}
                missing = asyncio.run(middleware.dispatch(Request(scope), next_response))
                self.assertEqual(missing.status_code, 401)
                scope["headers"] = [(b"authorization", b"Bearer revoked")]
                revoked = asyncio.run(middleware.dispatch(Request(scope), next_response))
                self.assertEqual(revoked.status_code, 403)
                scope["headers"] = [(b"authorization", b"Bearer active")]
                active = asyncio.run(middleware.dispatch(Request(scope), next_response))
                self.assertEqual(active.status_code, 200)


if __name__ == "__main__":
    unittest.main()
