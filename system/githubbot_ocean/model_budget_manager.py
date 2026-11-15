# SPDX-License-Identifier: MIT
"""Budgetierte Modellkette und lokaler Fallback für GitHubBot-OCEAN.

Stellt modelldienste hinter einem Kostenlimit bereit, mit localem Slot/Fackel-Fallback
und Kosten-Telemetrie.
"""

from __future__ import annotations

import logging
from typing import Any

from .budget_manager import BudgetController

# Optionaler lokaler Fallback-Service (Slots / Fackel)
try:
    from hub._services.claude_bridge.fackel import FackelService  # Typischer Import
except ImportError:
    FackelService = None

logger = logging.getLogger(__name__)
class ModelBudgetManager:
    """Orchestriert Modellanfragen hinter einem Budget, mit Fallback über lokale Slots.

    Nutzt BudgetController für zentrale Kostentracking und Telemetrie.
    Wenn das Budget erschöpft ist, nutzt es `FackelService` (lokaler Slot) als Fallback.
    """

    def __init__(self, budget_id: str, limit_cents: int) -> None:
        self.budget_id = budget_id
        self.controller = BudgetController(budget_id, limit_cents)
        self.fackel = FackelService() if FackelService else None

    def consume_budget(self, amount_cents: int) -> bool:
        """Versucht, amount_cents vom Budget zu verwenden.

        Gibt wahr zurück, wenn das Budget ausreichende Mittel hat; andernfalls wird ein Fallback
        versucht, wenn ein Fackel-Service verfügbar ist.
        """
        if self.controller.spend(amount_cents):
            logger.debug(
                "Budget verwendet für budget_id=%s, amount=%d",
                self.budget_id,
                amount_cents,
            )
            return True
        # Budget erschöpft – versuchen Sie Fallback
        if self.fackel and self.fackel.acquire(amount_cents):
            logger.warning(
                "Budget erschöpft, Fallback über Fackel für budget_id=%s genutzt, amount=%d",
                self.budget_id,
                amount_cents,
            )
            # Optional: Protokollieren Sie einen speziellen Fallback-Eintrag in der Budget-Telemetrie
            return True
        logger.error(
            "Budget und Fallback sind erschöpft für budget_id=%s, benötigte Kosten=%d",
            self.budget_id,
            amount_cents,
        )
        return False

    def get_balance_cents(self) -> int:
        """Aktuell ausgegebene Kosten aus dem Budget."""
        return self.controller.get_balance_cents()

    def get_limit_cents(self) -> int:
        """Budgetlimit in Cent."""
        return self.controller.get_limit_cents()

    def get_telemetry(self) -> list[Any]:
        """Gibt die Budget-Telemetrie zurück (einschließlich Fallback-Einträge)."""
        return self.controller.get_telemetry()

    def __repr__(self) -> str:
        return (
            f"ModelBudgetManager(budget_id={self.budget_id}, "
            f"used={self.get_balance_cents()}, limit={self.get_limit_cents()})"
        )

# Kurze Hilfsfunktionen für Common Workflows
def try_model_request(budget_id: str, limit_cents: int, cost_cents: int) -> bool:
    """Convenience: Erstellt einen Manager, versucht eine Anfrage und gibt den Erfolg zurück.

    Für kurze Lived-Aufrufe nützlich, bei denen ein Manager nicht persistent benötigt wird.
    """
    mgr = ModelBudgetManager(budget_id, limit_cents)
    return mgr.consume_budget(cost_cents)

__all__ = ["ModelBudgetManager", "try_model_request"]