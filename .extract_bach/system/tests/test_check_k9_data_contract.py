import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.check_k9_data_contract import (
    create_database,
    extract_operations,
    validate_contract,
    validate_specs,
)


ROOT = Path(__file__).parent.parent
CONTRACT = ROOT / "architecture" / "bach-k9-data-contract.v1.json"


class K9DataContractTests(unittest.TestCase):
    def test_contract_has_complete_nonaccepted_operation_matrices(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

        self.assertEqual([], validate_contract(contract))
        self.assertEqual([], validate_specs(contract, ROOT))
        self.assertEqual(
            {"backup", "cleanup", "disable", "enable", "init", "pull", "push", "status", "sync"},
            {item["name"] for item in contract["profiles"]["dbsync"]["operations"]},
        )
        self.assertEqual(
            {"create", "delete", "list", "load"},
            {item["name"] for item in contract["profiles"]["snapshot"]["operations"]},
        )
        self.assertTrue(
            all(
                item["parity"] == "not-accepted"
                for profile in contract["profiles"].values()
                for item in profile["operations"]
            )
        )

    def test_operation_extraction_is_static_and_literal(self):
        with tempfile.TemporaryDirectory() as temp_name:
            path = Path(temp_name) / "handler.py"
            path.write_text(
                """
class ExampleHandler:
    @property
    def profile_name(self):
        return "example"
    def get_operations(self):
        return {"zeta": "Z", "alpha": "A"}
""",
                encoding="utf-8",
            )

            self.assertEqual(["alpha", "zeta"], extract_operations(path, "example"))

    def test_sql_fixtures_are_anonymized_and_form_the_expected_start_state(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        fixture = contract["fixtures"]
        payload = "\n".join(
            (ROOT / fixture[key]).read_text(encoding="utf-8")
            for key in ("source_sql", "target_sql")
        )
        forbidden = ("C:\\Users", "OneDrive", "bach.db", "@")
        self.assertTrue(all(value not in payload for value in forbidden))

        with tempfile.TemporaryDirectory() as temp_name:
            source = Path(temp_name) / "source.sqlite"
            target = Path(temp_name) / "target.sqlite"
            create_database(source, ROOT / fixture["source_sql"])
            create_database(target, ROOT / fixture["target_sql"])
            connection = sqlite3.connect(source)
            try:
                self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM items").fetchone()[0])
                self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM secrets").fetchone()[0])
            finally:
                connection.close()
            connection = sqlite3.connect(target)
            try:
                self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM items").fetchone()[0])
                self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM secrets").fetchone()[0])
            finally:
                connection.close()

    def test_session_checkpoint_fixture_is_anonymized_and_matches_the_payload_contract(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        fixture_path = ROOT / contract["fixtures"]["session_checkpoint_input"]
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        encoded = json.dumps(fixture, ensure_ascii=False)
        forbidden = ("C:\\Users", "OneDrive", "bach.db", "@", "ASUS" + "-GEI")
        self.assertTrue(all(value not in encoded for value in forbidden))
        self.assertEqual(
            {
                "session_id",
                "open_tasks",
                "recent_memory",
                "active_files",
                "token_usage",
                "created_at",
            },
            set(fixture["payload"]),
        )
        self.assertEqual(2, len(fixture["payload"]["open_tasks"]))
        self.assertEqual(2, len(fixture["payload"]["recent_memory"]))
        self.assertEqual(2, len(fixture["payload"]["active_files"]))
        self.assertEqual(4242, fixture["payload"]["token_usage"])

    def test_adapter_specs_cover_exact_handler_surfaces_without_accepting_parity(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        dbsync = json.loads(
            (ROOT / contract["profiles"]["dbsync"]["adapter_spec"]).read_text(
                encoding="utf-8"
            )
        )
        checkpoint = json.loads(
            (ROOT / contract["profiles"]["snapshot"]["capability_spec"]).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            {item["name"] for item in contract["profiles"]["dbsync"]["operations"]},
            {item["name"] for item in dbsync["operations"]},
        )
        self.assertEqual(
            {item["name"] for item in contract["profiles"]["snapshot"]["operations"]},
            {item["bach_operation"] for item in checkpoint["operation_mapping"]},
        )
        self.assertTrue(all(item["parity"] == "not-accepted" for item in dbsync["operations"]))
        self.assertTrue(
            all(item["parity"] == "not-accepted" for item in checkpoint["operation_mapping"])
        )
        self.assertIn(
            "No Ocean restore adapter is implemented.",
            next(
                item["adapter_work"]
                for item in checkpoint["operation_mapping"]
                if item["bach_operation"] == "load"
            ),
        )


if __name__ == "__main__":
    unittest.main()
