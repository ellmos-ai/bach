"""Tests für system/hub/_services/model_budget_manager.py.

Testiert die budgetierte Modellkette, lokale Fallback-Logik und Telemetrie.
"""

from __future__ import annotations

import logging
import unittest
from unittest.mock import MagicMock, patch

from system.hub._services.model_budget_manager import (
    can_afford_model,
    spend_model_budget,
    enable_local_fallback,
    should_use_local_fallback,
    get_model_or_fallback,
    initialize_model_budget,
    _override_budget,
    _restore_budget,
)

logging.basicConfig(level=logging.DEBUG)

class TestModelBudgetManager(unittest.TestCase):
    """Testiert Budgetierung, Fallback-Logik und Telemetrie."""

    def setUp(self) -> None:
        # Setzen Sie ein Budget vor jedem Test mit Override, um einen sauberen Zustand sicherzustellen.
        _override_budget(100.0, 1000)

    def tearDown(self) -> None:
        _restore_budget()
        # Zurücksetzen des Fallback-Flags.
        # Das Modul verfügt nicht über eine öffentliche Rücksetzfunktion; wir nutzen die internen Globals über einen Mock.
        from system.hub._services import model_budget_manager as m
        m._LOCAL_FALLBACK_ENABLED = False

    # -----------------------------------------------------------------------
    # Budget-Initialisierung und Budgetierung
    # -----------------------------------------------------------------------
    def test_initialize_model_budget(self) -> None:
        # Mocken Sie set_budget und record_metric, die von initialize_model_budget aufgerufen werden.
        with patch("system.hub._services.model_budget_manager.set_budget") as mock_set:
            with patch("system.hub._services.model_budget_manager.record_metric") as mock_record:
                initialize_model_budget(50.0, 500)
                mock_set.assert_called_once_with("modell", 50.0)
                mock_record.assert_called()

    def test_can_afford_model_within_budget(self) -> None:
        self.assertTrue(can_afford_model(10.0, 200))

    def test_can_afford_model_usd_exceeded(self) -> None:
        self.assertFalse(can_afford_model(200.0, 100))

    def test_can_afford_model_tokens_exceeded(self) -> None:
        self.assertFalse(can_afford_model(10.0, 2000))

    def test_can_afford_model_no_budget(self) -> None:
        _override_budget(0.0, 0)
        self.assertTrue(can_afford_model(999.0, 9999))

    def test_spend_model_budget_success(self) -> None:
        with patch("system.hub._services.model_budget_manager.use_budget") as mock_use:
            with patch("system.hub._services.model_budget_manager.record_metric") as mock_record:
                result = spend_model_budget(20.0, 300)
                self.assertTrue(result)
                mock_use.assert_called_once_with("modell", 20.0)
                mock_record.assert_called()

    def test_spend_model_budget_failure(self) -> None:
        with patch("system.hub._services.model_budget_manager.use_budget") as mock_use:
            result = spend_model_budget(200.0, 5000)
            self.assertFalse(result)
            mock_use.assert_not_called()

    # -----------------------------------------------------------------------
    # Lokaler Fallback
    # -----------------------------------------------------------------------
    def test_enable_local_fallback(self) -> None:
        from system.hub._services import model_budget_manager as m
        enable_local_fallback()
        self.assertTrue(m._LOCAL_FALLBACK_ENABLED)

    def test_should_use_local_fallback_when_enabled_and_budget_exhausted(self) -> None:
        from system.hub._services import model_budget_manager as m
        m._LOCAL_FALLBACK_ENABLED = True
        # Überstimmen Sie das Budget, damit es nicht mehr ausreicht.
        _override_budget(0.0, 0)
        self.assertTrue(should_use_local_fallback(1))

    def test_should_use_local_fallback_disabled(self) -> None:
        from system.hub._services import model_budget_manager as m
        m._LOCAL_FALLBACK_ENABLED = False
        self.assertFalse(should_use_local_fallback(1))

    # -----------------------------------------------------------------------
    # Modell-Auswahl / Fallback
    # -----------------------------------------------------------------------
    def test_get_model_or_fallback_with_partner(self) -> None:
        partner = {
            "name": "external-ai",
            "token_cost_usd": 5.0,
            "token_cost_tokens": 50,
            "capabilities": ["text"],
        }
        with patch("system.hub._services.model_budget_manager.spend_model_budget") as mock_spend:
            result = get_model_or_fallback(partner)
            # Sollte den Partner zurückgeben und spend_model_budget aufrufen.
            self.assertEqual(result["source"], "external")
            self.assertEqual(result["provider"], "external-ai")
            mock_spend.assert_called_once_with(5.0, 50)

    def test_get_model_or_fallback_fallback_due_to_budget(self) -> None:
        partner = {
            "name": "expensive-ai",
            "token_cost_usd": 200.0,
            "token_cost_tokens": 2000,
        }
        from system.hub._services import model_budget_manager as m
        m._LOCAL_FALLBACK_ENABLED = True
        result = get_model_or_fallback(partner)
        # Sollte den lokalen Fallback verwenden, da das Budget erschöpft ist.
        self.assertEqual(result["source"], "local_fallback")
        self.assertEqual(result["provider"], "bach-local")

    def test_get_model_or_fallback_no_partner_no_fallback(self) -> None:
        from system.hub._services import model_budget_manager as m
        m._LOCAL_FALLBACK_ENABLED = False
        result = get_model_or_fallback(None)
        self.assertEqual(result["source"], "none")
        self.assertIsNone(result["provider"])

# ---------------------------------------------------------------------------
# Kein __main__-Block erforderlich – die Testsuite wird über pytest ausgeführt.
# ---------------------------------------------------------------------------