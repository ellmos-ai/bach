# SPDX-License-Identifier: MIT
"""Simple budget limit and tracking for GitHubBot-OCEAN.

Behält pro-budget gedämpfte Limits und verbrauchte Beträge. Überprüft, ob
Änderungen das Budget einhalten und protokolliert die Telemetrie.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

DATA_DIR = Path(
    os.environ.get(
        "GITHUBBOT_OCEAN_DATA_DIR",
        str(Path(__file__).parent.parent / "data" / "githubbot_ocean"),
    )
)
STATE_PATH = DATA_DIR / "budget_state.json"

def _load_state() -> dict[str, Any]:
    """Lade den aktuellen Budgetstatus. Falls Datei nicht existiert, erstelle leeren Status."""
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    # Standard initial state
    return {"budgets": {}}
def _save_state(state: dict[str, Any]) -> None:
    """Speichere den Budgetstatus als JSON."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))
class BudgetController:
    """Track Budget Nutzung mit Kostenlimits.

    Verhindert das Überschreiten des Budgets und erfasst die Telemetrie-Events.
    """

    def __init__(self, budget_id: str, limit_cents: int) -> None:
        self.budget_id = budget_id
        self.limit_cents = limit_cents
        state = _load_state()
        budgets = state.setdefault("budgets", {})
        if budget_id not in budgets:
            budgets[budget_id] = {
                "limit_cents": limit_cents,
                "spent_cents": 0,
                "telemetry": [],
            }
        _save_state(state)

    def spend(self, amount_cents: int) -> bool:
        """Versuchen, den Betrag vom Budget zu verwenden; wahr falls Erfolg, falsch falls Abbruch.

        Lädt einen Snapshot, aktualisiert den spent_cents und protokolliert die Verwendung in der Telemetrie.
        """
        state = _load_state()
        budgets = state.setdefault("budgets", {})
        entry = budgets.get(self.budget_id)
        if not entry:
            return False
        new_spent = entry.get("spent_cents", 0) + amount_cents
        if new_spent > self.limit_cents:
            return False  # Budget überschritten
        entry["spent_cents"] = new_spent
        entry["telemetry"].append({
            "timestamp": self._now_iso(),
            "amount_cents": amount_cents,
            "limit_after_spend": new_spent,
        })
        _save_state(state)
        return True

    def get_balance_cents(self) -> int:
        state = _load_state()
        budgets = state.get("budgets", {})
        entry = budgets.get(self.budget_id)
        return entry.get("spent_cents", 0)

    def get_limit_cents(self) -> int:
        return self.limit_cents

    def get_telemetry(self) -> list[Any]:
        state = _load_state()
        budgets = state.get("budgets", {})
        entry = budgets.get(self.budget_id)
        return entry.get("telemetry", [])

    def _now_iso(self) -> str:
        import datetime
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    def __repr__(self) -> str:
        return f"BudgetController(id={self.budget_id}, limit={self.limit_cents}, spent={self.get_balance_cents()})"

    @staticmethod
    def create_or_fetch(budget_id: str, limit_cents: int) -> "BudgetController":
        """Erstellt oder holt den BudgetController; Singleton.
        """
        return BudgetController(budget_id, limit_cents)

__all__ = ["BudgetController"]