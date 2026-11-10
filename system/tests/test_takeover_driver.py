"""Tests für system/hub/takeover_driver.py – ellmos-scheduler-Fencing + Heartbeat.

Führt grundlegende Checks für den Takeover-Treiber aus und validiert die
Implementierung von owner/lease-expiry fencing + heartbeat.

Verwendet Mocks, um das fehlende ellmos_scheduler-Modul zu umgehen und es
so zu gestalten, als ob es installiert wäre, falls es nicht vorhanden ist.
"""

from __future__ import annotations

import logging
import sys
import unittest
from unittest.mock import MagicMock, patch

# Stellen Sie sicher, dass wir innerhalb des Codes importieren können, unabhängig vom Importstatus von ellmos_scheduler.
sys.path.insert(0, str(sys.path[0]))

# Importieren Sie den TakeoverDriver – wir stubben den TaskLeaseClient vorab.
# Wir werden Mock -> TaskLeaseClient-Patching später vornehmen.
from system.hub.takeover_driver import TakeoverDriver

logging.basicConfig(level=logging.DEBUG)

# ---------------------------------------------------------------------------
# Unit-Test-Suite
# ---------------------------------------------------------------------------
class TestTakeoverDriver(unittest.TestCase):
    """Testiert die Kern-Funktionen von TakeoverDriver:
    * Heartbeat sendet
    * Lease-Validitätsprüfung
    * Fencing-Operation
    * Start- und Stopp-Operation
    """

    def setUp(self) -> None:
        # Mocken Sie den TaskLeaseClient, bevor wir TakeoverDriver instanziieren.
        # Das Modul, das von takeover_driver importiert wird, ist system.hub.takeover_driver.
        # Wir patchen system.hub.takeover_driver.TaskLeaseClient.
        self.mock_client_patcher = patch("system.hub.takeover_driver.TaskLeaseClient")
        self.mock_client_class = self.mock_client_patcher.start()
        # Erstellen Sie ein Mock-Instance.
        self.mock_client_instance = MagicMock()
        self.mock_client_class.return_value = self.mock_client_instance

        # Erstellen Sie den Driver für einen Dummy-Lease.
        self.driver = TakeoverDriver(lease_id="test-lease-123")
        # Setzen Sie das interne Client-Attribut, falls vorhanden (abhängig von der Implementierung).
        self.driver._client = self.mock_client_instance

    def tearDown(self) -> None:
        self.mock_client_patcher.stop()

    # -----------------------------------------------------------------------
    # Heartbeat
    # -----------------------------------------------------------------------
    def test_heartbeat(self) -> None:
        self.driver.heartbeat()
        # Überprüfen Sie, dass der Client heartbeat aufgerufen hat.
        self.mock_client_instance.heartbeat.assert_called_once()

    # -----------------------------------------------------------------------
    # Lease-Validitätsprüfung
    # -----------------------------------------------------------------------
    def test_is_lease_valid(self) -> None:
        # Das Mock gibt True zurück, wenn aufgerufen.
        self.mock_client_instance.is_valid.return_value = True
        result = self.driver.is_lease_valid()
        self.mock_client_instance.is_valid.assert_called_once()
        self.assertTrue(result)

    # -----------------------------------------------------------------------
    # Fencing stellt sicher
    # -----------------------------------------------------------------------
    def test_ensure_fencing_calls_get_state(self) -> None:
        self.mock_client_instance.get_state.return_value = {"valid": True}
        self.driver.ensure_fencing()
        self.mock_client_instance.get_state.assert_called_once()

    def test_ensure_fencing_logs_warning_when_invalid(self) -> None:
        self.mock_client_instance.get_state.return_value = {"valid": False}
        # Erfassen Sie das Logging
        with self.assertLogs("system.hub.takeover_driver", level="WARNING") as cm:
            self.driver.ensure_fencing()
        self.assertIn("Lease test-lease-123 ist ungültig", " ".join(cm.output))
        self.mock_client_instance.get_state.assert_called_once()

    # -----------------------------------------------------------------------
    # Start- und Stopp-Operation
    # -----------------------------------------------------------------------
    def test_start(self) -> None:
        self.driver.start()
        # heartbeat sollte einmal aufgerufen werden (durch start)
        self.mock_client_instance.heartbeat.assert_called_once()

    def test_stop(self) -> None:
        # Verwenden Sie einen Patch, um ensure_fencing während des Aufrufs von stop zu erfassen.
        with patch.object(self.driver, 'ensure_fencing') as mock_ensure_fencing:
            self.driver.stop()
        # Stop sollte nur einmal aufgerufen werden.
        self.mock_client_instance.stop.assert_called_once()
        # ensure_fencing sollte auch einmal aufgerufen werden (ermittelt vom Mock).
        mock_ensure_fencing.assert_called_once()

    # -----------------------------------------------------------------------
    # Run (Einzelaufruf)
    # -----------------------------------------------------------------------
    def test_run_calls_start(self) -> None:
        self.driver.start = MagicMock()
        self.driver.run()
        self.driver.start.assert_called_once()

    # -----------------------------------------------------------------------
    # Mock-Hilfsfunktion
    # -----------------------------------------------------------------------
    def test_mock_client_static_method(self) -> None:
        # Der statische Mock-Methodenaufruf gibt eine Mock-Instanz zurück (oder die Stub-Klasse)
        mock = TakeoverDriver.mock_client("some-lease")
        self.assertIsNotNone(mock)
        # Da wir die Klasse patchen, sollte sie eine Mock-Instanz sein, wenn sie importiert wird.
        # Diese Überprüfung ist locker – im Grunde stellen wir sicher, dass es keine Exceptions gibt.

# ---------------------------------------------------------------------------
# Keine __main__-Block erforderlich – die Test-Suite wird über pytest/unittest aufgerufen.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()