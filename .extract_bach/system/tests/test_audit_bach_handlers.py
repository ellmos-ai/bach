import json
import tempfile
import unittest
from pathlib import Path

from tools.audit_bach_handlers import audit, compare_baseline


BASE_HANDLER = """
from abc import ABC, abstractmethod
class BaseHandler(ABC):
    @property
    @abstractmethod
    def profile_name(self): ...
    @property
    @abstractmethod
    def target_file(self): ...
    @abstractmethod
    def get_operations(self): ...
    @abstractmethod
    def handle(self, operation, args, dry_run=False): ...
"""


class AuditBachHandlersTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.hub = self.root / "system" / "hub"
        self.core = self.root / "system" / "core"
        self.hub.mkdir(parents=True)
        self.core.mkdir(parents=True)
        (self.hub / "base.py").write_text(BASE_HANDLER, encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def _write_aliases(self, mapping):
        (self.core / "aliases.py").write_text(
            "COMMAND_ALIASES = " + repr(mapping) + "\n", encoding="utf-8"
        )

    def test_audit_mirrors_concrete_handlers_and_effective_aliases(self):
        (self.hub / "alpha.py").write_text(
            """
from .base import BaseHandler
class AlphaHandler(BaseHandler):
    @property
    def profile_name(self): return "alpha"
    @property
    def target_file(self): return None
    def get_operations(self): return {"show": "Show", "reset": "Reset"}
    def handle(self, operation, args, dry_run=False): return True, "ok"
""",
            encoding="utf-8",
        )
        (self.hub / "incomplete.py").write_text(
            """
from .base import BaseHandler
class IncompleteHandler(BaseHandler):
    @property
    def profile_name(self): return "incomplete"
""",
            encoding="utf-8",
        )
        self._write_aliases({"a": "alpha", "alpha": "alpha", "old": "missing"})

        result = audit(self.root)

        self.assertEqual(result["canonical_profiles"], ["alpha"])
        self.assertEqual(result["effective_aliases"], {"a": "alpha"})
        self.assertEqual(result["registered_names"], ["a", "alpha"])
        self.assertEqual(result["handlers"][0]["operations"], ["reset", "show"])
        self.assertEqual(
            result["diagnostics"]["abstract_handler_classes"],
            ["incomplete.py:IncompleteHandler"],
        )
        self.assertEqual(result["diagnostics"]["dangling_aliases"], {"old": "missing"})

    def test_catalog_fingerprint_and_baseline_comparison(self):
        (self.hub / "alpha.py").write_text(
            """
from .base import BaseHandler
class AlphaHandler(BaseHandler):
    profile_name = "ignored-by-runtime-name-extractor"
    @property
    def target_file(self): return None
    def get_operations(self): return {}
    def handle(self, operation, args, dry_run=False): return True, "ok"
""",
            encoding="utf-8",
        )
        self._write_aliases({})
        catalog = self.root / "modules.catalog.json"
        catalog.write_text(
            json.dumps({"schema": "catalog.v1", "module_count": 1, "modules": [{"id": "x"}]}),
            encoding="utf-8",
        )

        result = audit(self.root, catalog)
        expected = {
            "source_audit": {
                "counts": result["counts"],
                "registered_name_set": result["registered_names"],
                "known_dangling_aliases": {},
            }
        }
        self.assertEqual(result["canonical_profiles"], ["alpha"])
        self.assertEqual(result["module_catalog"]["parsed_module_count"], 1)
        self.assertEqual(compare_baseline(result, expected), [])


if __name__ == "__main__":
    unittest.main()
