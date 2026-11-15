"""Tests fuer system.githubbot_ocean.budget_manager + model_budget_manager.

Neu angelegt im Rahmen von Task #2061 (Tickets #4056/#4057): deckt
BudgetController (Spend/Telemetrie/State-Persistenz) und
ModelBudgetManager (consume_budget mit Fackel-Fallback, try_model_request)
ab. Die State-JSON wird pro Test in ein temporaeres Verzeichnis umgeleitet;
FackelService wird deterministisch auf den Stub-Fallback (None) gesetzt,
die Fackel-Branch-Logik wird anschliessend per MagicMock geprueft.
"""
import inspect
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from system.githubbot_ocean import budget_manager, model_budget_manager


class _StateRedirectTest(unittest.TestCase):
    """Basis: budget_manager.STATE_PATH in ein temporaeres Verzeichnis umleiten."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        original = budget_manager.STATE_PATH
        self.addCleanup(setattr, budget_manager, "STATE_PATH", original)
        budget_manager.STATE_PATH = Path(tmp.name) / "budget_state.json"


class BudgetControllerTest(_StateRedirectTest):
    def test_initialer_budget_eintrag_wird_angelegt(self):
        bc = budget_manager.BudgetController("b1", 1000)
        self.assertTrue(budget_manager.STATE_PATH.exists())
        self.assertEqual(bc.get_balance_cents(), 0)
        self.assertEqual(bc.get_limit_cents(), 1000)

    def test_spend_bis_exakt_zum_limit(self):
        bc = budget_manager.BudgetController("b1", 1000)
        self.assertTrue(bc.spend(300))
        self.assertEqual(bc.get_balance_cents(), 300)
        self.assertTrue(bc.spend(700))
        self.assertEqual(bc.get_balance_cents(), 1000)

    def test_spend_ueber_limit_scheitert_ohne_aenderung(self):
        bc = budget_manager.BudgetController("b1", 1000)
        self.assertTrue(bc.spend(700))
        self.assertFalse(bc.spend(500))
        self.assertEqual(bc.get_balance_cents(), 700)

    def test_spend_mit_fehlendem_budget_eintrag_scheitert(self):
        bc = budget_manager.BudgetController("b1", 1000)
        with open(budget_manager.STATE_PATH, "w", encoding="utf-8") as fh:
            json.dump({"budgets": {}}, fh)
        self.assertFalse(bc.spend(100))

    def test_telemetry_erfasst_alle_spends(self):
        bc = budget_manager.BudgetController("b1", 1000)
        bc.spend(300)
        bc.spend(200)
        telemetry = bc.get_telemetry()
        self.assertEqual(len(telemetry), 2)
        self.assertEqual(telemetry[0]["amount_cents"], 300)
        self.assertEqual(telemetry[0]["limit_after_spend"], 300)
        self.assertEqual(telemetry[1]["amount_cents"], 200)
        self.assertEqual(telemetry[1]["limit_after_spend"], 500)

    def test_create_or_fetch_behaelt_bestehenden_stand(self):
        first = budget_manager.BudgetController.create_or_fetch("b1", 1000)
        self.assertIsInstance(first, budget_manager.BudgetController)
        self.assertEqual(first.budget_id, "b1")
        self.assertTrue(first.spend(150))
        second = budget_manager.BudgetController.create_or_fetch("b1", 1000)
        self.assertEqual(second.get_balance_cents(), 150)


class ModelBudgetManagerTest(_StateRedirectTest):
    def setUp(self):
        super().setUp()
        # FackelService deterministisch auf den Stub-Fallback zwingen, damit
        # die Tests unabhaengig davon laufen, ob hub._services importierbar ist.
        patcher = patch.object(model_budget_manager, "FackelService", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_consume_innerhalb_des_budgets(self):
        mgr = model_budget_manager.ModelBudgetManager("m1", 500)
        self.assertTrue(mgr.consume_budget(100))
        self.assertEqual(mgr.get_balance_cents(), 100)
        self.assertEqual(mgr.get_limit_cents(), 500)
        self.assertEqual(len(mgr.get_telemetry()), 1)
        self.assertEqual(mgr.get_telemetry()[0]["amount_cents"], 100)

    def test_consume_erschoepft_budget_ohne_fackel(self):
        mgr = model_budget_manager.ModelBudgetManager("m1", 500)
        self.assertTrue(mgr.consume_budget(500))
        self.assertFalse(mgr.consume_budget(100))
        self.assertEqual(mgr.get_balance_cents(), 500)

    def test_fackel_fallback_uebernimmt_bei_erschoepftem_budget(self):
        mgr = model_budget_manager.ModelBudgetManager("m1", 500)
        self.assertTrue(mgr.consume_budget(500))
        mgr.fackel = MagicMock()
        mgr.fackel.acquire.return_value = True
        self.assertTrue(mgr.consume_budget(100))
        mgr.fackel.acquire.assert_called_once_with(100)
        mgr.fackel.acquire.return_value = False
        self.assertFalse(mgr.consume_budget(100))

    def test_try_model_request_entscheidet_ueber_kosten(self):
        self.assertTrue(model_budget_manager.try_model_request("t1", 500, 100))
        self.assertFalse(model_budget_manager.try_model_request("t2", 100, 500))

    def test_fackel_service_ist_none_oder_klasse(self):
        value = model_budget_manager.FackelService
        self.assertTrue(value is None or inspect.isclass(value))


if __name__ == "__main__":
    unittest.main()
