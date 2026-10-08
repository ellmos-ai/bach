# SPDX-License-Identifier: MIT
"""Acceptance test suite for Shared GUI Kit, Universal Fallback & Backend Origin.

Tests GUX-001 through GUX-004 and GUX-092 for Task #1695 (Ticket T-20261003-793817309):
1. GUX-001: Pinned Kit Commit & Brand Contract (GET /api/gui/brand, kit-manifest)
2. GUX-002: Universal GUI Fallback Differentiation (ellmos-universal-gui)
3. GUX-003: Backend Origin, Instance Binding & Non-Claim Guarantee (GET /api/gui/backend-origin)
4. GUX-004: Canonical Definitions of SALT, Trithon, and Muschelgrund
5. GUX-092: Standalone Dashboard Functions & Fallback Parity
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gui.backend_origin import SCHEMA as ORIGIN_SCHEMA
from gui.backend_origin import observe_backend_origin
from gui.branding import SCHEMA as BRAND_SCHEMA
from gui.branding import read_gui_brand
from hub._services.gui_contract_service import (
    get_architectural_concepts,
    get_pinned_kit_manifest,
    verify_installed_dist,
)


class TestGuiBrandContract(unittest.TestCase):
    """GUX-001: Verifies consumer branding contract and sanitization."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config_file = Path(self.tmp.name) / "gui_brand.json"

    def write_config(self, **overrides):
        data = {
            "schema": BRAND_SCHEMA,
            "label": "BACH",
            "product": "BACH/Ocean GUI",
            "logo_text": "◆",
            "logo_path": "/static/branding/bach_logo.png",
            "theme": "dark",
        }
        data.update(overrides)
        self.config_file.write_text(json.dumps(data), encoding="utf-8")

    def test_default_brand_contract(self):
        result = read_gui_brand(self.config_file)
        self.assertEqual(result["schema"], BRAND_SCHEMA)
        self.assertEqual(result["label"], "BACH")
        self.assertEqual(result["product"], "BACH/Ocean GUI")
        self.assertEqual(result["source"], "backend_default")

    def test_customized_ocean_branding(self):
        self.write_config(
            label="Ocean",
            product="Ocean Workstation",
            logo_text="🌊",
            logo_path="/static/branding/ocean.webp",
            theme="ocean",
        )
        result = read_gui_brand(self.config_file)
        self.assertEqual(result["label"], "Ocean")
        self.assertEqual(result["product"], "Ocean Workstation")
        self.assertEqual(result["logo_text"], "🌊")
        self.assertEqual(result["logo_path"], "/static/branding/ocean.webp")
        self.assertEqual(result["theme"], "ocean")
        self.assertEqual(result["source"], "validated_consumer_config")

    def test_security_sanitization_rejects_path_traversal(self):
        self.write_config(logo_path="/static/branding/../../etc/passwd.png")
        result = read_gui_brand(self.config_file)
        self.assertEqual(result["source"], "backend_default")
        self.assertIsNone(result["logo_path"])

    def test_security_sanitization_rejects_script_injection(self):
        self.write_config(label="<script>alert(1)</script>")
        result = read_gui_brand(self.config_file)
        self.assertEqual(result["source"], "backend_default")
        self.assertEqual(result["label"], "BACH")

    def test_valid_themes_accepted(self):
        for theme in ("dark", "light", "ocean", "warm"):
            with self.subTest(theme=theme):
                self.write_config(theme=theme)
                result = read_gui_brand(self.config_file)
                self.assertEqual(result["theme"], theme)
                self.assertEqual(result["source"], "validated_consumer_config")


class TestBackendOriginContract(unittest.TestCase):
    """GUX-003: Verifies live backend-origin probe and non-claim guarantee."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "bach.db"
        self.manifest_path = self.root / "origin.json"

    def write_db(self):
        from contextlib import closing
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT)")
            conn.execute("CREATE TABLE bach_agents (id INTEGER PRIMARY KEY, name TEXT)")

    def write_manifest(self, mode="server", node="lead-node", read_only_observation=False):
        data = {
            "schema": ORIGIN_SCHEMA,
            "mode": mode,
            "backend_kind": "bach_sqlite",
            "instance_label": "Mac Studio Lead",
            "expected_node_sha256": hashlib.sha256(node.encode()).hexdigest(),
            "read_only_observation": read_only_observation,
            "offline_cache_active": False,
        }
        self.manifest_path.write_text(json.dumps(data), encoding="utf-8")

    def test_verified_server_mode(self):
        self.write_db()
        self.write_manifest(mode="server", node="test-node")
        with patch("gui.backend_origin.platform.node", return_value="test-node"):
            result = observe_backend_origin(self.db_path, self.db_path, self.manifest_path)

        self.assertEqual(result["mode"], "server")
        self.assertEqual(result["declared_mode"], "server")
        self.assertEqual(result["instance_label"], "Mac Studio Lead")
        self.assertEqual(result["reason_code"], "verified")
        self.assertTrue(result["connection_verified"])
        self.assertTrue(result["schema_verified"])
        self.assertTrue(result["instance_verified"])
        self.assertTrue(result["adapter_binding_verified"])
        self.assertTrue(result["has_claim_authority"])
        self.assertFalse(result["cache_active"])

    def test_read_only_observation_denies_claim_authority(self):
        """GUX-003: Pure read status must not claim Lead TaskDB claim functionality."""
        self.write_db()
        self.write_manifest(mode="server", node="test-node", read_only_observation=True)
        with patch("gui.backend_origin.platform.node", return_value="test-node"):
            result = observe_backend_origin(self.db_path, self.db_path, self.manifest_path)

        self.assertEqual(result["mode"], "server")
        self.assertFalse(result["has_claim_authority"], "Read-only observer must not claim authority")

    def test_adapter_binding_mismatch_fails_closed(self):
        from contextlib import closing
        self.write_db()
        other_db = self.root / "other.db"
        with closing(sqlite3.connect(other_db)) as conn:
            conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY)")
            conn.execute("CREATE TABLE bach_agents (id INTEGER PRIMARY KEY)")

        self.write_manifest(node="test-node")
        with patch("gui.backend_origin.platform.node", return_value="test-node"):
            result = observe_backend_origin(self.db_path, other_db, self.manifest_path)

        self.assertEqual(result["mode"], "unknown")
        self.assertEqual(result["reason_code"], "adapter_binding_mismatch")
        self.assertFalse(result["has_claim_authority"])


class TestPinnedKitManifest(unittest.TestCase):
    """GUX-001: Verifies pinned kit manifest and release distribution integrity."""

    def test_pinned_kit_manifest_content(self):
        manifest = get_pinned_kit_manifest()
        self.assertTrue(manifest.get("verified"), f"Manifest failed: {manifest.get('error')}")
        self.assertEqual(manifest.get("schema"), "ellmos-system-gui.kit-manifest.v1")
        self.assertEqual(manifest.get("pinned_source_commit"), "dc880878bd0416ab8c14108c74e8911a15f10f8d")
        self.assertEqual(manifest.get("version"), "0.2.3")
        self.assertEqual(manifest.get("expected_page_count"), 20)
        self.assertEqual(manifest.get("release_archive"), "ellmos-system-gui-0.2.3-dc880878bd04.zip")
        self.assertEqual(
            manifest.get("release_archive_sha256"),
            "2d5d15f5b7df7f929f557ee2bbe557f1b0eeb60820dca79e6b0a764759cffeef",
        )

    def test_dist_manifest_verification_against_local_repo(self):
        import os
        configured = os.environ.get("GUI_RELEASE_TEST_DIST")
        if not configured:
            self.skipTest("Explicit release distribution was not supplied")
        dist_path = Path(configured)
        if dist_path.exists():
            verification = verify_installed_dist(dist_path, expected_commit="dc880878bd0416ab8c14108c74e8911a15f10f8d")
            self.assertTrue(verification["installed"])
            self.assertTrue(verification["verified"])
            self.assertEqual(verification["reason_code"], "verified")
            self.assertEqual(verification["page_count"], 20)


class TestUniversalGuiDifferentiation(unittest.TestCase):
    """GUX-002: Verifies standalone fallback GUI package and manifest identity."""

    def test_universal_gui_repo_and_manifest(self):
        universal_repo = Path("C:/_Local_DEV/repos/ellmos-unified-gui")
        if universal_repo.exists():
            manifest_path = universal_repo / "ellmos-module.v2.json"
            self.assertTrue(manifest_path.exists(), "ellmos-module.v2.json must exist in fallback repo")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest.get("schema"), "ellmos.module.v2")
            self.assertEqual(manifest.get("id"), "ellmos-unified-gui")
            self.assertIn("operator.ui", manifest.get("provides", []))
            self.assertIn("unified-gui.host", manifest.get("provides", []))

            pyproject_path = universal_repo / "pyproject.toml"
            self.assertTrue(pyproject_path.exists())
            pyproject_content = pyproject_path.read_text(encoding="utf-8")
            self.assertIn('name = "ellmos-unified-gui"', pyproject_content)
            self.assertIn("fastapi", pyproject_content.lower())


class TestArchitecturalConcepts(unittest.TestCase):
    """GUX-004: Verifies canonical definitions for SALT, Trithon, and Muschelgrund."""

    def test_concepts_structure_and_scope(self):
        data = get_architectural_concepts()
        self.assertTrue(data.get("verified"))
        self.assertEqual(data.get("schema"), "ellmos.architecture.concepts.v1")

        concepts = data.get("concepts", {})
        self.assertIn("salt", concepts)
        self.assertIn("trithon", concepts)
        self.assertIn("muschelgrund", concepts)

        salt = concepts["salt"]
        self.assertEqual(salt["role"], "Task-Claim- & Ressourcen-Sperrkoordination")
        self.assertIn("task_leases", salt["scope"])
        self.assertIn("fencing", salt["scope"])

        trithon = concepts["trithon"]
        self.assertEqual(trithon["role"], "Verteilte Ausführungs- & Scheduler-Abstraktion")
        self.assertIn("intent_dispatch", trithon["scope"])
        self.assertIn("execution_receipt", trithon["scope"])

        muschelgrund = concepts["muschelgrund"]
        self.assertEqual(muschelgrund["role"], "Kognitiver Langzeitspeicher & Episodisches Gedächtnis")
        self.assertIn("deep_memory", muschelgrund["scope"])
        self.assertIn("session_memory", muschelgrund["scope"])


class TestGuiServerEndpoints(unittest.TestCase):
    """Verifies that FastAPI routes for GUI contract respond with valid schemas."""

    @classmethod
    def setUpClass(cls):
        import os
        os.environ["BACH_GUI_ALLOWED_HOSTS"] = "testserver,localhost,127.0.0.1"
        from gui.server import app
        from starlette.testclient import TestClient
        cls.client = TestClient(app, base_url="http://testserver", raise_server_exceptions=False)

    def test_route_gui_brand(self):
        resp = self.client.get("/api/gui/brand")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("schema"), "ellmos-system-gui.brand.v1")
        self.assertTrue(len(data.get("label", "")) > 0)
        self.assertTrue(len(data.get("product", "")) > 0)

    def test_route_gui_backend_origin(self):
        resp = self.client.get("/api/gui/backend-origin")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("schema"), "ellmos-system-gui.backend-origin.v1")
        self.assertIn("mode", data)
        self.assertIn("declared_mode", data)
        self.assertIn("has_claim_authority", data)

    def test_route_gui_kit_manifest(self):
        resp = self.client.get("/api/gui/kit-manifest")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("schema"), "ellmos-system-gui.kit-manifest.v1")
        self.assertEqual(data.get("pinned_source_commit"), "dc880878bd0416ab8c14108c74e8911a15f10f8d")
        self.assertIn("installed_dist", data)

    def test_route_gui_architecture_concepts(self):
        resp = self.client.get("/api/gui/architecture/concepts")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("schema"), "ellmos.architecture.concepts.v1")
        self.assertIn("salt", data.get("concepts", {}))
        self.assertIn("trithon", data.get("concepts", {}))
        self.assertIn("muschelgrund", data.get("concepts", {}))

    def test_route_gui_capabilities(self):
        resp = self.client.get("/api/gui/capabilities")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("schema"), "ellmos.gui.capabilities.v1")
        self.assertIn("kit", data)
        self.assertEqual(data["kit"].get("revision"), "dc880878bd0416ab8c14108c74e8911a15f10f8d")
        self.assertIn("brand", data)
        self.assertIn("modules", data)


if __name__ == "__main__":
    unittest.main()
