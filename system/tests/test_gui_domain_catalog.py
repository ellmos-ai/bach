"""The GUI may expose public manifest metadata, never infer installation."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gui.api.domain_catalog import discover_domains


class DomainCatalogTests(unittest.TestCase):
    def _manifest(self, root, name, **changes):
        directory = root / ".DOMAINS" / name
        directory.mkdir(parents=True, exist_ok=True)
        data = {
            "schema": "ellmos.module.v2",
            "id": name,
            "display_name": "Förderplaner",
            "category": "domains",
            "kind": "service",
            "status": "released",
            "visibility": "public",
            "provides": ["domain.health.reports"],
        }
        data.update(changes)
        (directory / "ellmos-module.v2.json").write_text(json.dumps(data), encoding="utf-8")

    def test_missing_source_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = discover_domains(Path(tmp))
            self.assertFalse(result["source_available"])
            self.assertEqual(result["domains"], [])
            self.assertIsNone(result["installed_count"])

    def test_public_manifest_is_metadata_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._manifest(root, "foerderplaner")
            result = discover_domains(root)
            self.assertEqual(result["total"], 1)
            domain = result["domains"][0]
            self.assertEqual(domain["evidence_type"], "manifest_present")
            self.assertEqual(domain["manifest_status"], "released")
            self.assertIsNone(domain["installed"])
            self.assertIsNone(domain["running"])
            self.assertIsNone(domain["workbench_url"])
            self.assertNotIn(str(root), json.dumps(result))

    def test_private_wrong_category_and_unmanifested_directories_are_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._manifest(root, "private-domain", visibility="private")
            self._manifest(root, "task-master", category="control")
            (root / ".DOMAINS" / "empty").mkdir()
            self.assertEqual(discover_domains(root)["domains"], [])

    def test_manifest_id_is_authoritative_when_folder_slug_differs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._manifest(root, "law-checker", id="rechtsabteilung")
            self.assertEqual(discover_domains(root)["domains"][0]["id"], "rechtsabteilung")

    def test_invalid_manifest_id_is_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._manifest(root, "domain-one", id="../another-id")
            self.assertEqual(discover_domains(root)["domains"], [])

    def test_malformed_status_and_kind_do_not_break_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._manifest(root, "domain-one", status=["active"], kind={"service": True})
            self._manifest(root, "domain-two")
            result = discover_domains(root)
            self.assertEqual(result["total"], 2)
            first = next(item for item in result["domains"] if item["id"] == "domain-one")
            self.assertEqual(first["manifest_status"], "unknown")
            self.assertEqual(first["kind"], "unknown")
            self.assertIsNone(first["installed"])


if __name__ == "__main__":
    unittest.main()
