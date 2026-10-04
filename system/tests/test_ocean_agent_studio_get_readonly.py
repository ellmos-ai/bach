"""Agent-Studio GET endpoints inspect schema and never initialize or seed it."""
import asyncio
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from gui.api import unified_api


class AgentStudioReadOnlyTest(unittest.TestCase):
    def test_ready_schema_preserves_responses_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "bach.db"
            with closing(sqlite3.connect(db)) as conn:
                conn.execute("CREATE TABLE agent_blueprints (id INTEGER, name TEXT, title TEXT, persona_role TEXT, skills_json TEXT, contractus_json TEXT, governance_json TEXT, is_template INTEGER, is_materialized INTEGER, animus_type TEXT, modus TEXT)")
                conn.execute("CREATE TABLE partner_presence (partner_name TEXT, status TEXT, current_task TEXT, last_heartbeat TEXT)")
                conn.execute("CREATE TABLE marblerun_chains (name TEXT, steps_json TEXT, is_active INTEGER)")
                conn.execute("INSERT INTO agent_blueprints VALUES (1, 'mueller', 'Müller', 'Prüfer', '[]', '{}', '{}', 1, 1, 'cli', 'casualis')")
                conn.execute("INSERT INTO partner_presence VALUES ('mueller', 'offline', NULL, NULL)")
                conn.execute("INSERT INTO marblerun_chains VALUES ('probe', '[]', 1)")
                conn.commit()
            before = db.stat().st_mtime_ns
            statements = []
            original = unified_api._get_agent_studio_ro_conn

            def traced_connection():
                conn = original()
                conn.set_trace_callback(statements.append)
                return conn

            with patch.object(unified_api, "BACH_DB", db), \
                    patch.object(unified_api, "_get_agent_studio_ro_conn", side_effect=traced_connection), \
                    patch.object(unified_api, "_find_existing_path", return_value=None):
                blueprints = asyncio.run(unified_api.list_agent_blueprints())
                living = asyncio.run(unified_api.get_living_agents())
                graph = asyncio.run(unified_api.get_agents_map())
            self.assertEqual(blueprints["templates"][0]["title"], "Müller")
            self.assertEqual(living["living_agents"][0]["title"], "Müller")
            self.assertEqual(graph["nodes"][0]["label"], "Müller")
            self.assertEqual(db.stat().st_mtime_ns, before)
            self.assertFalse(any(stmt.lstrip().upper().startswith(
                ("CREATE", "ALTER", "INSERT", "UPDATE", "DELETE", "REPLACE", "DROP"))
                for stmt in statements))

    def test_missing_schema_returns_503_without_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "bach.db"
            sqlite3.connect(db).close()
            before = db.stat().st_mtime_ns
            with patch.object(unified_api, "BACH_DB", db):
                for endpoint in (unified_api.list_agent_blueprints,
                                 unified_api.get_living_agents, unified_api.get_agents_map):
                    with self.assertRaises(HTTPException) as result:
                        asyncio.run(endpoint())
                    self.assertEqual(result.exception.status_code, 503)
            with closing(sqlite3.connect(db)) as conn:
                tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            self.assertEqual(tables, [])
            self.assertEqual(db.stat().st_mtime_ns, before)

    def test_missing_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "missing.db"
            with patch.object(unified_api, "BACH_DB", db):
                with self.assertRaises(HTTPException) as result:
                    asyncio.run(unified_api.list_agent_blueprints())
            self.assertEqual(result.exception.status_code, 503)
            self.assertFalse(db.exists())


if __name__ == "__main__":
    unittest.main()
