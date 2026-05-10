# SPDX-License-Identifier: MIT
"""
Clutch-Bridge Handler - Intelligentes Task-Routing
===================================================

--clutch status       Gesamtstatus aller clutch-bridge Komponenten
--clutch analyse      Task analysieren (StreckenAnalyse + Gas/Bremse)
--clutch metriken     Fahrtenbuch-Metriken anzeigen
--clutch fitness      Fahrschule Fitness-Übersicht
--clutch health       Bordcomputer Health-Status
"""

import sys
from pathlib import Path
from typing import List, Tuple
from .base import BaseHandler

# clutch-bridge Imports
sys.path.insert(0, str(Path(__file__).parent / "_services" / "delegation"))
try:
    from strecken_analyse import get_analyser
    from gas_bremse import get_gas_bremse
    from bordcomputer import get_bordcomputer
    from fahrschule import get_fahrschule
    from fahrtenbuch import get_fahrtenbuch
    HAS_CLUTCH = True
except ImportError:
    HAS_CLUTCH = False


class ClutchHandler(BaseHandler):
    """Handler fuer --clutch Operationen (clutch-bridge)."""

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "clutch"

    @property
    def target_file(self) -> Path:
        return self.base_path / "hub" / "_services" / "delegation"

    def get_operations(self) -> dict:
        return {
            "status": "Gesamtstatus aller clutch-bridge Komponenten",
            "analyse": "Task analysieren (StreckenAnalyse + Gas/Bremse)",
            "metriken": "Fahrtenbuch-Metriken anzeigen",
            "fitness": "Fahrschule Fitness-Übersicht",
            "health": "Bordcomputer Health-Status",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        """Haupteinstiegspunkt."""
        if not HAS_CLUTCH:
            return False, "[CLUTCH] clutch-bridge Module nicht verfügbar."

        ops = {
            "status": lambda: self._status(),
            "analyse": lambda: self._analyse(args),
            "metriken": lambda: self._metriken(args),
            "fitness": lambda: self._fitness(),
            "health": lambda: self._health(),
        }

        if not operation or operation == "status":
            return self._status()

        if operation in ops:
            return ops[operation]()
        return False, f"Unbekannte Operation: {operation}\n\nVerfügbar: {', '.join(ops.keys())}"

    def _status(self) -> tuple:
        """Gesamtstatus aller clutch-bridge Komponenten."""
        lines = [
            "[CLUTCH-BRIDGE] Gesamtstatus",
            "=" * 50,
            "",
            "  Komponenten:",
            "    ✓ StreckenAnalyse    (10 Streckentypen)",
            "    ✓ Gas/Bremse         (3 Strategien: direkt/ausgewogen/gründlich)",
            "    ✓ Bordcomputer       (Circuit-Breaker + Overkill + Token-Alerts)",
            "    ✓ Fahrschule         (Epsilon-Greedy Lern-Loop)",
            "    ✓ Fahrtenbuch        (Metriken-Erfassung)",
        ]

        # Bordcomputer Status
        bc = get_bordcomputer()
        bc_status = bc.status()
        lines.append(f"\n  Bordcomputer: {len(bc_status['circuits'])} Provider überwacht")
        if bc_status['overkill_alerts'] > 0:
            lines.append(f"    ! {bc_status['overkill_alerts']} Overkill-Alerts")
        if bc_status['token_alerts'] > 0:
            lines.append(f"    ! {bc_status['token_alerts']} Token-Explosions")

        # Fahrschule Status
        fs = get_fahrschule(db_path=self.db_path)
        fs_status = fs.status()
        lines.append(f"\n  Fahrschule: {fs_status['total_kombinationen']} Model×Strecke Kombinationen gelernt")

        # Fahrtenbuch Status
        fb = get_fahrtenbuch(db_path=self.db_path)
        fb_metriken = fb.metriken(tage=7)
        lines.append(f"\n  Fahrtenbuch: {fb_metriken['total_delegations']} Delegations (7 Tage)")

        return True, "\n".join(lines)

    def _analyse(self, args: list) -> tuple:
        """Analysiert einen Task-Text."""
        if not args:
            return False, "Nutzung: bach clutch analyse 'Task-Beschreibung'"

        task_text = " ".join(args)

        # StreckenAnalyse
        profil = get_analyser().analysiere(task_text)

        # Gas/Bremse
        gas = get_gas_bremse().berechne(
            strecken_schwierigkeit=profil.schwierigkeit,
            strecken_typ_code=profil.typ_code,
        )

        lines = [
            "[CLUTCH] Task-Analyse",
            "=" * 50,
            f"  Task: {task_text}",
            "",
            f"  Strecke: {profil.typ} (Code {profil.typ_code})",
            f"  Tempo:        {profil.tempo}/5",
            f"  Schwierigkeit: {profil.schwierigkeit}/5",
            f"  Etappen:      {profil.etappen}",
            f"  Gang:         {profil.empfohlener_gang}",
            f"  Budget-Faktor: {profil.token_budget_faktor}x",
            "",
            f"  Gas-Level:    {gas.level}%",
            f"  Strategie:    {gas.strategie.value}",
            f"  Token-Multi:  {gas.token_multiplikator}x",
        ]

        if gas.prompt_prefix:
            lines.append(f"  Prompt-Prefix: {gas.prompt_prefix[:60]}...")
        if gas.prompt_suffix:
            lines.append(f"  Prompt-Suffix: {gas.prompt_suffix[:60]}...")

        return True, "\n".join(lines)

    def _metriken(self, args: list) -> tuple:
        """Zeigt Fahrtenbuch-Metriken."""
        tage = 7
        if args:
            try:
                tage = int(args[0])
            except ValueError:
                pass

        fb = get_fahrtenbuch(db_path=self.db_path)
        return True, fb.format_metriken(tage)

    def _fitness(self) -> tuple:
        """Zeigt Fahrschule Fitness-Übersicht."""
        fs = get_fahrschule(db_path=self.db_path)
        return True, fs.format_status()

    def _health(self) -> tuple:
        """Zeigt Bordcomputer Health-Status."""
        bc = get_bordcomputer()
        return True, bc.format_status()
