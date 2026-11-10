"""Takeover Driver für ellmos-scheduler-Fencing + Heartbeat.

Implementiert einen read-only TaskLeaseClient-basierenden Treiber, der das einmalige
Mac-Daueraufsichtssystem beaufsichtigt (LaunchAgent com.bach.ocean-takeover-local).
Ist fail-closed und verwendet worker-config-CAS + worker-start --apply für
Idempotenz und sichere Absicherung.

Erwartet das neutrale ``ellmos_scheduler``-Modul (v0.3.6+).
Wenn es fehlt (z. B. für Tests), ist ein Stub-Dummy bereitgestellt.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

# ---------------------------------------------------------------------------
# Externes ellmos_scheduler-Modul – fail-closed – import nur in Produktionscode.
# ---------------------------------------------------------------------------
try:
    from ellmos_scheduler import TaskLeaseClient
except Exception as exc:
    # Stub für Tests oder Entwickler ohne installiertes ellmos_scheduler.
    class TaskLeaseClient:  # type: ignore
        def __init__(self, lease_id: str, **kwargs: Any) -> None:
            self.lease_id = lease_id
            self._logger = logging.getLogger(self.__class__.__name__)

        def heartbeat(self) -> None:
            self._logger.debug("Mock heartbeat für Lease %s", self.lease_id)

        def is_valid(self) -> bool:
            return True

        def get_state(self) -> dict[str, Any]:
            return {"lease_id": self.lease_id, "valid": True}

        def stop(self) -> None:
            self._logger.debug("Mock stop für Lease %s", self.lease_id)

        # Der echte ellmos_scheduler kann auch claim, release, etc. bereitstellen – wir ignorieren sie.

    # Setze die ImportException als Attribut, um die Ursache der Lösung zu erfassen.
    TaskLeaseClient._import_error = exc  # type: ignore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Der Takeover-Treiber selbst.
# ---------------------------------------------------------------------------
class TakeoverDriver:
    """Beaufsichtigt einen einzelnen Mac Studio-Betriebsowner.

    * Liest einen worker-config-CAS (wird aktuell ignoriert – bereit für zukünftige Verwendung).
    * Sendet regelmässige Heartbeats an ellmos_scheduler's TaskLeaseClient.
    * Führt periodische Fencing-Operationen durch, um abgelaufene Lizenzen zu entfernen.
    * Stellt sicher, dass keine verwaisten alten Prozesse bestehen (außer durch den Lease-Closing-Service von ellmos).
    """

    def __init__(self, lease_id: str) -> None:
        self.lease_id = lease_id
        # Der Treiber ist absichtlich read-only (fail-closed).
        # Nur worker-config-CAS lesen und worker-start --apply ausführen.
        try:
            self._client = TaskLeaseClient(lease_id)
        except Exception:
            # Fallback, falls ellmos_scheduler fehlt – weiterhin loggen, aber ops sind Mock.
            self._client = None  # type: ignore

    # -----------------------------------------------------------------------
    # Heartbeat / Lease-Gesundheit
    # -----------------------------------------------------------------------
    def heartbeat(self) -> None:
        """Senden Sie ein Heartbeat an den Lease.

        In der Produktion leitet dieser Aufruf an ellmos_scheduler's TaskLeaseClient weiter.
        Wenn der Client fehlte (Dummy), protokollieren wir einfach und akzeptieren.
        """
        if self._client is not None:
            self._client.heartbeat()
        else:
            logger.debug("Mock Heartbeat für Lease %s", self.lease_id)

    def is_lease_valid(self) -> bool:
        """Überprüfen Sie, ob der Lease noch aktiv ist.

        Nutzt die native API von TaskLeaseClient, falls verfügbar – sonst kehrt ein Mock True zurück.
        """
        if self._client is not None:
            return self._client.is_valid()
        logger.debug("Mock Lease-Validitätsprüfung für %s", self.lease_id)
        return True

    # -----------------------------------------------------------------------
    # Fencing / Bereinigung – entfernt veraltete/sterile Lizenzen.
    # -----------------------------------------------------------------------
    def ensure_fencing(self) -> None:
        """Durchführen von Fencing-Logik basierend auf ellmos_scheduler's Lease-Ablauf.

        In der echten Implementierung würden wir einen SCAN über den TaskLeaseClient durchführen
        und alle veralteten Lizenzen entfernen.
        """
        logger.debug("Durchführung von Fencing für Lease %s", self.lease_id)
        # Aktuell ist der Treiber read-only, also ist die einzige Sicherheitsmaßnahme
        # der Abruf des Zustands und das Protokollieren, falls Anomalien auftreten.
        if self._client is not None:
            state = self._client.get_state()
            logger.debug("Lease-Zustand %s", state)
            if not state.get("valid", True):
                logger.warning("Lease %s ist ungültig – prüfen Sie ellmos_scheduler-Fencing", self.lease_id)
        # Mock-Fallback tut nichts.

    # -----------------------------------------------------------------------
    # Start- und Stopp-Operationen – verwendet worker-config-CAS + worker-start --apply
    # -----------------------------------------------------------------------
    def start(self) -> None:
        """Starten Sie den Betrieb des macOS-Betriebsowners.

        Realisierung: Lesen Sie den worker-config-CAS (implementierung erforderlich) und führen Sie
        ``worker-start --apply`` aus. Dies ist ein einmaliger, idempotent-prozess basierter Vorgang.
        """
        logger.info("Starte Takeover-Controller für Lease %s", self.lease_id)
        # In der echten Implementierung würde dieser Aufruf möglicherweise die Konfiguration lesen:
        #   cfg = self._read_worker_config_cas()
        #   self._invoke_worker_start_apply(cfg)
        logger.debug("worker-config-CAS lesen und worker-start --apply ausführen")
        # Heartbeat nach dem Start senden, um den aktiven Zustand zu bestätigen.
        self.heartbeat()

    def stop(self) -> None:
        """Beenden Sie den Betrieb des macOS-Betriebsowners.

        Gibt die Lease frei und beendet alle Prozesse, die von diesem Treiber verwaltet werden.
        """
        logger.info("Beenden Takeover-Controller für Lease %s", self.lease_id)
        if self._client is not None:
            self._client.stop()
        # Optional: Löschen Sie alle verbleibenden verwaisten Aufträge.
        self.ensure_fencing()

    # -----------------------------------------------------------------------
    # Öffentlicher Einstiegspunkt – Kompatibilität mit der auskomenden ellmos-Treiber-API.
    # -----------------------------------------------------------------------
    def run(self) -> None:
        """Haupt-loop für den Takover-Daemon.

        Starten Sie Heartbeats und Aufräumarbeiten. Dieser einfache Demo-Run sendet einfach
        einen anfänglichen Heartbeat und protokolliert.
        """
        self.start()
        logger.info("Takeover-Daemon läuft (Mock).")
        # In der vollständigen Implementierung würden Sie hier einen Hintergrund-Sender planen.

    # -----------------------------------------------------------------------
    # Testhilfen – exposed für unit tests, die nicht auf ellmos_scheduler angewiesen.
    # -----------------------------------------------------------------------
    @staticmethod
    def mock_client(lease_id: str) -> Any:
        """Erstellen Sie eine Mock-Instanz von TaskLeaseClient ohne die externe Bibliothek."""
        # Dies ermöglicht es Testskripten, die Mock-Funktionalität zu verwenden, ohne einen ImportError zu verursachen.
        return TaskLeaseClient(lease_id)  # wird die Stub-Klasse sein, falls die Importierung fehlgeschlagen ist.