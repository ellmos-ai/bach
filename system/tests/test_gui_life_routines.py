"""Personal routine API access without starting GUI lifespan or live DB."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from gui import server


class LifeRoutineAuthTests(unittest.TestCase):
    def test_personal_routines_require_a_real_device_token(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "user.db"
            with closing(sqlite3.connect(database)) as conn:
                conn.execute("CREATE TABLE routines(id INTEGER PRIMARY KEY, name TEXT, category TEXT, interval_type TEXT, priority INTEGER, is_active INTEGER, next_due_at TEXT)")
                conn.commit()
            with (
                patch.object(server, "get_user_db", side_effect=lambda: sqlite3.connect(database)),
                patch.object(server, "validate_token", side_effect=lambda token: {"name": "fixture"} if token == "valid-fixture" else None),
            ):
                client = TestClient(server.app)  # No context: do not start the file watcher.
                try:
                    self.assertEqual(client.get("/api/routines").status_code, 401)
                    self.assertEqual(client.get("/api/routines", headers={"Authorization": "Bearer invalid-fixture"}).status_code, 403)
                    response = client.get("/api/routines", headers={"Authorization": "Bearer valid-fixture"})
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.json()["success"])
                finally:
                    client.close()


if __name__ == "__main__":
    unittest.main()
