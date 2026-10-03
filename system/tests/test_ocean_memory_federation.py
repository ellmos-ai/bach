"""Fixture-only checks for read-only Ocean memory source separation."""
import importlib.util
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


MODULE = Path(__file__).resolve().parents[1] / "gui" / "api" / "memory_federation.py"
spec = importlib.util.spec_from_file_location("ocean_memory_federation", MODULE)
memory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(memory)


class OceanMemoryFederationTest(unittest.TestCase):
    def test_separate_sources_and_missing_source_are_honest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bach = root / "bach.db"
            gardener = root / "gardener"
            gardener.mkdir()
            usmc = root / "usmc.db"
            with closing(sqlite3.connect(bach)) as db:
                db.execute("CREATE TABLE memory_facts(id INTEGER PRIMARY KEY, category TEXT, key TEXT, value TEXT)")
                db.execute("INSERT INTO memory_facts VALUES(1,'test','alpha','BACH result')")
                db.commit()
            with closing(sqlite3.connect(gardener / "user.db")) as db:
                db.execute("CREATE TABLE everything(id INTEGER PRIMARY KEY, type TEXT, name TEXT, content TEXT, updated TEXT)")
                db.execute("INSERT INTO everything VALUES(1,'memory','alpha user','Gardener result','2026-10-03')")
                db.commit()
            with closing(sqlite3.connect(usmc)) as db:
                db.execute("CREATE TABLE usmc_facts(id INTEGER PRIMARY KEY, category TEXT, key TEXT, value TEXT)")
                db.execute("CREATE TABLE usmc_lessons(id INTEGER PRIMARY KEY, category TEXT, title TEXT, solution TEXT, is_active INTEGER)")
                db.execute("CREATE TABLE usmc_working(id INTEGER PRIMARY KEY, type TEXT, content TEXT, priority INTEGER, is_active INTEGER)")
                db.execute("INSERT INTO usmc_facts VALUES(1,'test','alpha','USMC result')")
                db.commit()
            before = {p: p.stat().st_mtime_ns for p in (bach, gardener / "user.db", usmc)}
            with patch.dict(os.environ, {"GARDENER_DATA": str(gardener), "USMC_DB_PATH": str(usmc)}):
                report = memory.search_memory("alpha", 10, bach)
            self.assertEqual(report["availability"], "partial")
            self.assertEqual([source["availability"] for source in report["sources"]],
                             ["available", "available", "unavailable", "available"])
            self.assertEqual({hit["id"] for hit in report["results"]},
                             {"bach:fact:1", "gardener:user:1", "usmc:fact:1"})
            self.assertEqual(before, {p: p.stat().st_mtime_ns for p in before})
            self.assertFalse(any(root.rglob("*-wal")))
            self.assertFalse(any(root.rglob("*-shm")))

    def test_search_input_is_parameterized(self):
        with tempfile.TemporaryDirectory() as tmp:
            bach = Path(tmp) / "bach.db"
            with closing(sqlite3.connect(bach)) as db:
                db.execute("CREATE TABLE memory_facts(id INTEGER PRIMARY KEY, category TEXT, key TEXT, value TEXT)")
                db.execute("INSERT INTO memory_facts VALUES(1,'test','alpha','result')")
                db.commit()
            with patch.dict(os.environ, {"GARDENER_DATA": str(Path(tmp) / "missing"),
                                          "USMC_DB_PATH": str(Path(tmp) / "missing.db")}):
                report = memory.search_memory("' OR 1=1 --", 10, bach)
            self.assertEqual(report["results"], [])
            self.assertEqual(report["sources"][0]["availability"], "available")


if __name__ == "__main__":
    unittest.main()
