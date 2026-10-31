# -*- coding: utf-8 -*-
"""Unittest-Belege fuer Pickup-Category (Task 2696) ohne pytest-Fixtures.

Eigener Ausfuehrungskanal (keine conftest-Abhaengigkeit, sys.path-Selffix):
python -m unittest discover -s system/tests -p "test_pickup_category_unittest.py"
"""
import hashlib
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hub import agent_runners, pickup_category

EXCL = [
    "food", "clothing", "electronics", "toys", "books", "media",
    "health", "finance", "utilities", "home", "gardening", "travel",
    "automotive", "construction",
]


class TestPickupCategoryLogik(unittest.TestCase):

    def test_exakt_14_ausschluesse(self):
        self.assertEqual(len(pickup_category.PICKUP_CATEGORY_EXCLUSIONS), 14)
        self.assertEqual(
            sorted(pickup_category.PICKUP_CATEGORY_EXCLUSIONS), sorted(EXCL))

    def test_resolve_category_bach_ocean_general(self):
        self.assertEqual(pickup_category.resolve_category("BACH-OCEAN"), "general")

    def test_resolve_priority_p2_default_normal(self):
        self.assertEqual(pickup_category.resolve_priority("P2"), "normal")
        self.assertEqual(pickup_category.DEFAULT_PRIORITY, "normal")

    def test_main_bach_ocean_p2(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = pickup_category.main(["pickup_category.py", "BACH-OCEAN", "P2"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data, {
            "pickup_category": "general",
            "priority": "normal",
            "priority_level": 2,
            "excluded": False,
        })

    def test_runner_registrierung(self):
        spec = agent_runners.BUILTIN["pickup_category"]
        self.assertIn("pickup_category", spec["match"])
        self.assertEqual(spec["cmd"][0], sys.executable)
        self.assertEqual(Path(spec["cmd"][1]).name, "pickup_category.py")
        self.assertEqual(spec["priority"], "high")

    def test_beleglage_dokumentiert(self):
        # Beleglage (Korrektur 88): Kein Ausführungskanal wurde bestätigt,
        # daher ist die SHA256-Attestierung nicht möglich. Quellen werden
        # auf Existenz und Nichtleere geprüft; Hashes werden berechnet und
        # ausgegeben, aber nicht via Dump-Datei/Assertion attestiert.
        base = Path(__file__).resolve().parent.parent / "hub"
        lines = []
        for name in ("pickup_category.py", "agent_runners.py"):
            raw = (base / name).read_bytes()
            self.assertTrue(raw, "%s ist leer" % name)
            digest = hashlib.sha256(raw).hexdigest()
            self.assertEqual(len(digest), 64)
            lines.append("SHA256 %s=%s" % (name, digest))
        print("\n".join(lines))


if __name__ == "__main__":
    unittest.main()