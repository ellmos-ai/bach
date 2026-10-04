"""The backend badge reports an observed binding, never a guessed host mode."""
from __future__ import annotations

import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from gui.backend_origin import SCHEMA, observe_backend_origin


class BackendOriginTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / "bach.db"
        self.manifest = self.root / "origin.json"

    def write_manifest(self, mode="server", node="fixture-node"):
        self.manifest.write_text(json.dumps({
            "schema": SCHEMA,
            "mode": mode,
            "backend_kind": "bach_sqlite",
            "instance_label": "Fixture backend",
            "expected_node_sha256": hashlib.sha256(node.encode()).hexdigest(),
        }), encoding="utf-8")

    def write_db(self, complete=True):
        with closing(sqlite3.connect(self.db)) as conn:
            with conn:
                conn.execute("CREATE TABLE tasks(id INTEGER PRIMARY KEY)")
                if complete:
                    conn.execute("CREATE TABLE bach_agents(id INTEGER PRIMARY KEY)")

    def observe(self, api_db=None):
        with patch("gui.backend_origin.platform.node", return_value="fixture-node"):
            return observe_backend_origin(self.db, api_db or self.db, self.manifest)

    def test_no_declaration_does_not_guess_or_create_database(self):
        result = self.observe()
        self.assertEqual(result["mode"], "unknown")
        self.assertEqual(result["reason_code"], "manifest_unavailable_or_invalid")
        self.assertFalse(self.db.exists())

    def test_declared_server_requires_live_matching_api_database(self):
        self.write_db()
        self.write_manifest()
        before = self.db.stat().st_mtime_ns
        result = self.observe()
        self.assertEqual(result["mode"], "server")
        self.assertEqual(result["reason_code"], "verified")
        self.assertTrue(all(result[key] for key in (
            "connection_verified", "schema_verified", "instance_verified", "adapter_binding_verified")))
        self.assertEqual(self.db.stat().st_mtime_ns, before)
        serialized = json.dumps(result)
        self.assertNotIn(str(self.db), serialized)
        self.assertNotIn("fixture-node", serialized)

    def test_declared_local_uses_same_checks(self):
        self.write_db()
        self.write_manifest(mode="local")
        self.assertEqual(self.observe()["mode"], "local")

    def test_wrong_machine_or_api_binding_is_unknown(self):
        self.write_db()
        other = self.root / "other.db"
        with closing(sqlite3.connect(other)) as conn:
            with conn:
                conn.execute("CREATE TABLE tasks(id INTEGER PRIMARY KEY)")
                conn.execute("CREATE TABLE bach_agents(id INTEGER PRIMARY KEY)")
        self.write_manifest(node="different-node")
        self.assertEqual(self.observe()["reason_code"], "instance_unverified")
        self.write_manifest()
        result = self.observe(other)
        self.assertEqual(result["mode"], "unknown")
        self.assertEqual(result["reason_code"], "adapter_binding_mismatch")

    def test_missing_schema_does_not_claim_backend(self):
        self.write_db(complete=False)
        self.write_manifest()
        result = self.observe()
        self.assertEqual(result["mode"], "unknown")
        self.assertEqual(result["reason_code"], "schema_unavailable")


if __name__ == "__main__":
    unittest.main()
