#!/usr/bin/env python3
# coding: utf-8
# SPDX-License-Identifier: MIT
"""
DecisionClicker Writer – Stern-Lease-gesicherte Atomizität für decide/undo/append.

Plan-B-Modul für die Entscheidungsclicker-Komponente. Dieser Code ist für
Das Zielrepository hat einen Star-Lease-Lock zur Verfügung (den
Das Modul system/hub/star_lease.py).

Verwendet star_lease für die Exklusivität; der Fence-Token stellt sicher, dass
Der Fence-Wert pro Decide-Operation überprüft wird.

Einklinkpunkte (in star_lease_INTEGRATION.md) beschreiben,
wie man diese APIs verwendet, um decide/undo/append zu implementieren.
"""

import time
from pathlib import Path

from system.hub.star_lease import StarLease, LeaseDeniedError, LeaseUnavailableError, LeaseViolation


class DecisionWriter:
    """Atomarer Writer für eine einzelne Entscheidung mit Stern-Lease-Fence."""

    def __init__(
        self,
        resource_dir: str | None = None,
        lock_name: str = "LOCK.txt",
        ttl: float = 30.0,
        holder: str | None = None,
    ):
        self._resource_dir = Path(resource_dir).resolve() if resource_dir else None
        self._lock_name = lock_name
        self._ttl = ttl
        self._lease = StarLease(resource_dir=resource_dir, lock_name=lock_name)
        # Optionaler Standard-Inhabername; decide(holder=...) hat Vorrang.
        self._holder = holder

    # ---------------------------------------------------------------------
    # Öffentliche Aktionen (werdende)
    # ---------------------------------------------------------------------
    def decide(self, holder: str | None = None) -> str:
        """
        Beginnt einen geschützten Schreibvorgang. Erhält einen Stern-Lease-Lock und gibt
        den Fence-Token zurück, den der Aufrufer für nachfolgende Operationen speichern muss.

        Args:
            holder: Optionaler Anzeigename für den Lock-Inhaber.

        Returns:
            fence (str): Der eindeutige Fence-Token für diese Lease.

        Raises:
            LeaseDeniedError: Wenn der Lock von einem anderen Writer gehalten wird.
            LeaseUnavailableError: Wenn die Lease nicht erlangt werden kann (Fehler, Zugriff verweigert).
        """
        # Wenn wir bereits einen Lock haben, ist dies ein Fehler.
        if self._lease.is_held:
            raise LeaseViolation("[VIOLATION] Bereits vorhandener Lease-Lock; starten Sie zuerst release().")
        self._lease.acquire(holder=holder or self._holder, ttl=self._ttl)
        self._holder = holder or self._holder or f"pid-{self._lease.holder}"
        fence = self._lease.fence
        # Beim „Decide“ haben wir den Lock erfolgreich gehalten.
        # Return des Fences zur späteren Validierung.
        return fence

    def append(self, fence: str, data: str) -> None:
        """
        Atomarer Schreibvorgang der Daten in eine Zieldatei innerhalb der
        Ressource. Die Fence-Prüfung stellt sicher, dass der Schreibvorgang mit dem
        zuvor erhaltenen decide-Fence durchgeführt wird.

        Args:
            fence: Der Fence-Token, der von decide abgerufen wurde.
            data: Der zu schreibende Inhalt.

        Raises:
            LeaseViolation: Wenn die Fence-Prüfung fehlschlägt (Lock-Inhalt
                verändert, abgelaufen oder Fence-Mismatch).
        """
        self._lease.check_fence()
        # Stellen Sie sicher, dass der Fence-Token übereinstimmt.
        if self._lease.fence != fence:
            raise LeaseViolation(
                f"[VIOLATION] Fence mismatch: erwartet {fence}, erhalten {self._lease.fence}"
            )
        # Schreiben Sie die Daten in eine deterministische Datei (z. B. decision.txt).
        target = self._lease.lock_path.parent / "decision.txt"
        target.write_text(data, encoding="utf-8")
        # Erfolgreich.

    def undo(self) -> None:
        """Geben Sie den Lock frei und kehren Sie in den Zustand ohne Lease zurück.
        Dies führt zu einem endgültigen Release; ein erneuter Decide kann später acquire.
        """
        self._lease.release()
        self._holder = None

    # ---------------------------------------------------------------------
    # Hilfs-/Informationen
    # ---------------------------------------------------------------------
    def status(self) -> dict:
        """Geben Sie den aktuellen Status des Locks zurück (für Überwachung)."""
        return self._lease.status()

    # ---------------------------------------------------------------------
    # Kontextmanager (optional)
    # ---------------------------------------------------------------------
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Eine Ausnahme führt immer noch zum Release (semantisch wie undo).
        self._lease.release()
        return False


# Schnellzugriff (optional).
def write_decision(resource_dir: str | None = None, holder: str | None = None) -> DecisionWriter:
    """Geben Sie einen neuen DecisionWriter für resource_dir zurück."""
    return DecisionWriter(resource_dir=resource_dir, holder=holder)