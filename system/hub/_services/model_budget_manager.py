"""Modell-Client mit Kostenbudgetierung und lokalem Fallback.

Implementiert eine budgetierte Modellkette für ellmos-scheduler, die
* Das Token-/Cost-Budget liest (über AutomationMaster.set_budget/use_budget).
* Die Modellkosten überprüft, bevor der Partner ausgelöst wird.
* Eine lokale Fallback-Route (Slots/Fackel) anbietet, wenn das Budget erschöpft ist oder
  lokale Inferenz möglich ist.
* Kosten-Telemetrie aufzeichnet (über AutomationMaster.record_metric).

Der Manager funktioniert als read-only-Seam für ellmos_scheduler's Modelldispatch,
so dass die Kernel-Richtung unverändert bleibt (fail-closed).
"""

from __future__ import annotations

import logging
from typing import Any

from system.agents_heart import use_budget, set_budget  # Kürzungspunkt für Ausgabenbudgets
from system.automation_master import record_metric

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Globale Budgetkonfiguration – wird aus der Konfiguration oder Umgebung geladen.
# Für die Bereitstellung werden wir die Konfigurationsdatei lesen, aber für den Testbetrieb
# weisen wir die Werte zu.
# ---------------------------------------------------------------------------
_MODEL_BUDGET_USD = 0.0  # Gesamtbudget in USD (oder eine andere Währung)
_MODEL_BUDGET_TOKENS = 0  # Gesamtbudget in Tokens

# ---------------------------------------------------------------------------
# Lokaler Fallback-Status – überwacht Slots/Fackel (GPU-Kapazität).
# ---------------------------------------------------------------------------
_LOCAL_FALLBACK_ENABLED = False

# ---------------------------------------------------------------------------
# Öffentliche API – aufgerufen vom ellmos_scheduler-Adaptor oder direkt durch BACH.
# ---------------------------------------------------------------------------

def initialize_model_budget(capacity_usd: float, token_limit: int) -> None:
    """Setzen Sie das Gesamtbudget für die Modellkette.

    Dieser Aufruf sollte einmal während der Systeminitialisierung erfolgen.
    Er schreibt in den AutomationMaster-CAS (set_budget).
    """
    area = "modell"
    # set_budget erwartet ein Limit als float.
    set_budget(area, float(capacity_usd))
    global _MODEL_BUDGET_USD, _MODEL_BUDGET_TOKENS
    _MODEL_BUDGET_USD = float(capacity_usd)
    _MODEL_BUDGET_TOKENS = token_limit
    logger.info(
        "Modellbudget initialisiert: %.2f USD, %d Tokens für den Bereich '%s'",
        _MODEL_BUDGET_USD,
        _MODEL_BUDGET_TOKENS,
        area,
    )

def can_afford_model(estimated_cost_usd: float, estimated_tokens: int) -> bool:
    """Überprüfen Sie, ob das Budget für eine Modellanfrage ausreicht.

    Berücksichtigt sowohl die verbleibenden USD- als auch die Token-Budgetwerte.
    Wenn die Werte nicht gesetzt sind, wird implizit True zurückgegeben (kein Budget). Dies ermöglicht es
    der externen Komponente, ihre eigene Budgetierung durchzusetzen.
    """
    # Wenn die Budgets nicht gesetzt wurden, ist kein Budgetlimit durchgesetzt.
    if _MODEL_BUDGET_USD <= 0 and _MODEL_BUDGET_TOKENS <= 0:
        return True
    if estimated_cost_usd > _MODEL_BUDGET_USD:
        return False
    if estimated_tokens > _MODEL_BUDGET_TOKENS:
        return False
    return True

def spend_model_budget(cost_usd: float, tokens: int) -> bool:
    """Verbuchen Sie Kosten und Tokens für eine abgeschlossene Modellanfrage.

    Gibt True zurück, wenn das Budget ausreichend war; sonst wird nichts aufgezeichnet und False zurückgegeben.
    """
    if not can_afford_model(cost_usd, tokens):
        logger.warning(
            "Kann Modellanfrage nicht finanzieren: %.2f USD, %d Tokens – Budgeterschöpfung",
            cost_usd,
            tokens,
        )
        return False
    # Reduzieren Sie das interne (in-memory) und den AutomationMaster-CAS.
    # Da set_budget und use_budget die Budgets pro Bereich sind, benötigen wir den Bereich "modell".
    # use_budget reduziert den "used"-Teil des Budgets.
    use_budget("modell", cost_usd)
    # Für Tokens gibt es kein integriertes Budget, aber wir können die interne Token-Budgetzählung verfolgen.
    global _MODEL_BUDGET_USD, _MODEL_BUDGET_TOKENS
    _MODEL_BUDGET_USD -= cost_usd
    _MODEL_BUDGET_TOKENS -= tokens
    # Aufzeichnen der Telemetrie.
    record_metric(
        name="model_request_cost",
        value=cost_usd,
        unit="USD",
        tags={"service": "ellmos_scheduler", "model": "unknown"},
    )
    logger.debug("Modellbudget ausgegeben: %.2f USD, %d Tokens übrig – %.2f USD, %d Tokens", _MODEL_BUDGET_USD, _MODEL_BUDGET_TOKENS, _MODEL_BUDGET_USD, _MODEL_BUDGET_TOKENS)
    return True

def enable_local_fallback() -> None:
    """Aktivieren Sie den lokalen Fallback-Pfad (Slots/Fackel).

    In der echten Bereitstellung wird dieser Aufruf durch das Überprüfen von GPU-/Metal-Kapazität ausgelöst
    (z. B. über `fackel.gpu_available()`). Für das Testen setzen wir einen einfachen Flag.
    """
    global _LOCAL_FALLBACK_ENABLED
    _LOCAL_FALLBACK_ENABLED = True
    logger.info("Lokaler Fallback (Slots/Fackel) aktiviert")

def should_use_local_fallback(required_tokens: int) -> bool:
    """Entscheiden Sie, ob die lokale Inferenz verwendet werden soll.

    Dies kann basierend auf Budget und verfügbaren lokalen Ressourcen erfolgen.
    """
    if not _LOCAL_FALLBACK_ENABLED:
        return False
    # Wenn das Budget nicht ausreicht, verwenden Sie den Fallback, wenn er aktiviert ist.
    if not can_afford_model(0.0, required_tokens):
        logger.debug("Budget nicht ausreichend, verwende lokalen Fallback für %d Tokens", required_tokens)
        return True
    # Weitere Kriterien könnten GPU-Kapazität oder Slots-Verfügbarkeit sein.
    return False

def get_model_or_fallback(preferred_partner: dict[str, Any] | None = None) -> dict[str, Any]:
    """Wählen Sie den Partner aus oder geben Sie einen Platzhalter für lokale Inferenz an.

    Die Implementierung priorisiert den bevorzugten Partner, überprüft die Kosten und greift auf den lokalen
    Fallback zurück, wenn das Budget nicht ausreicht oder der lokale Modus aktiviert ist.
    """
    if preferred_partner:
        cost = preferred_partner.get("token_cost_usd", 0.0)
        tokens = preferred_partner.get("token_cost_tokens", 0)
        if can_afford_model(cost, tokens):
            spend_model_budget(cost, tokens)
            return {**preferred_partner, "source": "external", "provider": preferred_partner.get("name")}
    # Kein Partner geeignet – Fallback.
    if should_use_local_fallback(preferred_partner.get("token_cost_tokens", 0) if preferred_partner else 0):
        return {
            "source": "local_fallback",
            "provider": "bach-local",
            "capabilities": ["text-generation"],
        }
    # Wenn nichts möglich ist, geben Sie einen symbolischen Platzhalter zurück.
    return {
        "source": "none",
        "provider": None,
        "reason": "budget exhausted or unavailable",
    }

# ---------------------------------------------------------------------------
# Hilfsfunktionen für das Testen – ermöglichen es, Budgets ohne tatsächliche CAS zu manipulieren.
# ---------------------------------------------------------------------------

class _BudgetOverride:
    def __init__(self) -> None:
        self.original = (_MODEL_BUDGET_USD, _MODEL_BUDGET_TOKENS)

    def set(self, usd: float, tokens: int) -> None:
        global _MODEL_BUDGET_USD, _MODEL_BUDGET_TOKENS
        _MODEL_BUDGET_USD = usd
        _MODEL_BUDGET_TOKENS = tokens

    def restore(self) -> None:
        global _MODEL_BUDGET_USD, _MODEL_BUDGET_TOKENS
        _MODEL_BUDGET_USD, _MODEL_BUDGET_TOKENS = self.original

_budget_override = _BudgetOverride()

def _override_budget(usd: float, tokens: int) -> None:
    _budget_override.set(usd, tokens)

def _restore_budget() -> None:
    _budget_override.restore()