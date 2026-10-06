"""Consumer branding must remain validated display metadata."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from gui.branding import SCHEMA, read_gui_brand


class BrandingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / "brand.json"

    def write(self, **changes):
        data = {
            "schema": SCHEMA,
            "label": "Ocean",
            "product": "BACH/Ocean GUI",
            "logo_text": "🌊",
            "logo_path": "/static/branding/ocean.webp",
            "theme": "ocean",
        }
        data.update(changes)
        self.config.write_text(json.dumps(data), encoding="utf-8")

    def test_branding_is_not_restricted_to_two_labels(self):
        self.write(label="Mein System")
        result = read_gui_brand(self.config)
        self.assertEqual(result["label"], "Mein System")
        self.assertEqual(result["logo_path"], "/static/branding/ocean.webp")
        self.assertEqual(result["source"], "validated_consumer_config")

    def test_invalid_text_or_url_falls_back(self):
        for changes in ({"label": "<script>"}, {"logo_path": "https://evil.example/logo.png"},
                        {"logo_path": "/static/branding/../private.png"}, {"theme": "evil"}):
            with self.subTest(changes=changes):
                self.write(**changes)
                self.assertEqual(read_gui_brand(self.config)["source"], "backend_default")

    def test_missing_config_uses_backend_default(self):
        self.assertEqual(read_gui_brand(self.config)["label"], "BACH")


if __name__ == "__main__":
    unittest.main()
