#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gas/Bremse Reasoning - Reasoning-Level für Delegation
=====================================================

Steuert das Reasoning-Level (0-100%) als Parameter bei Delegation.
Gas-Stellung bestimmt:
- prompt_strategie: direkt (0-30), ausgewogen (31-70), gründlich (71-100)
- token_multiplikator: 0.5x bis 3.0x

Einhängepunkt: partner.py _delegate()
Abwärtskompatibel: ohne Gas-Parameter bleibt Verhalten identisch.

Teil der clutch-bridge (BACH Task [1075]).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class PromptStrategie(Enum):
    """Drei Prompt-Strategien basierend auf Gas-Stellung."""
    DIREKT = "direkt"           # 0-30%: Kurz, knapp, keine Erklärung
    AUSGEWOGEN = "ausgewogen"   # 31-70%: Standard-Verhalten
    GRUENDLICH = "gründlich"    # 71-100%: Chain-of-Thought, Validierung


@dataclass
class GasStellung:
    """Ergebnis der Gas/Bremse-Berechnung."""
    level: int                          # 0-100%
    strategie: PromptStrategie          # direkt/ausgewogen/gründlich
    token_multiplikator: float          # 0.5 - 3.0
    prompt_prefix: str                  # Prefix für Delegation-Prompt
    prompt_suffix: str                  # Suffix für Delegation-Prompt

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "strategie": self.strategie.value,
            "token_multiplikator": self.token_multiplikator,
            "prompt_prefix": self.prompt_prefix,
            "prompt_suffix": self.prompt_suffix,
        }


# ─── Strategie-Definitionen ────────────────────────────────────────

STRATEGIE_CONFIG = {
    PromptStrategie.DIREKT: {
        "token_multi_range": (0.5, 0.8),
        "prefix": "Antworte kurz und direkt. Keine Erklärung nötig.",
        "suffix": "",
    },
    PromptStrategie.AUSGEWOGEN: {
        "token_multi_range": (0.8, 1.5),
        "prefix": "",
        "suffix": "",
    },
    PromptStrategie.GRUENDLICH: {
        "token_multi_range": (1.5, 3.0),
        "prefix": "Denke gründlich nach. Erkläre dein Reasoning Schritt für Schritt.",
        "suffix": "Validiere dein Ergebnis bevor du antwortest.",
    },
}


class GasBremseReasoning:
    """Berechnet Gas-Stellung und daraus resultierende Prompt-Strategie."""

    def berechne(
        self,
        gas_level: Optional[int] = None,
        strecken_schwierigkeit: Optional[int] = None,
        strecken_typ_code: Optional[int] = None,
    ) -> GasStellung:
        """
        Berechnet die Gas-Stellung.

        Args:
            gas_level: Explizites Level (0-100). Wenn None, wird aus
                       Strecken-Daten abgeleitet.
            strecken_schwierigkeit: Schwierigkeit aus StreckenAnalyse (1-5)
            strecken_typ_code: Streckentyp-Code (1-10)

        Returns:
            GasStellung mit Strategie und Token-Multiplikator
        """
        # Level bestimmen
        if gas_level is not None:
            level = max(0, min(100, gas_level))
        elif strecken_schwierigkeit is not None:
            # Ableitung aus Strecken-Schwierigkeit
            level = self._level_from_strecke(
                strecken_schwierigkeit, strecken_typ_code
            )
        else:
            # Default: ausgewogen (50%)
            level = 50

        # Strategie bestimmen
        strategie = self._strategie_from_level(level)
        config = STRATEGIE_CONFIG[strategie]

        # Token-Multiplikator interpolieren
        low, high = config["token_multi_range"]
        if strategie == PromptStrategie.DIREKT:
            ratio = level / 30.0
        elif strategie == PromptStrategie.AUSGEWOGEN:
            ratio = (level - 30) / 40.0
        else:
            ratio = (level - 70) / 30.0
        ratio = max(0.0, min(1.0, ratio))
        token_multi = round(low + (high - low) * ratio, 2)

        return GasStellung(
            level=level,
            strategie=strategie,
            token_multiplikator=token_multi,
            prompt_prefix=config["prefix"],
            prompt_suffix=config["suffix"],
        )

    def _strategie_from_level(self, level: int) -> PromptStrategie:
        """Mappt Level auf Strategie."""
        if level <= 30:
            return PromptStrategie.DIREKT
        elif level <= 70:
            return PromptStrategie.AUSGEWOGEN
        else:
            return PromptStrategie.GRUENDLICH

    def _level_from_strecke(
        self,
        schwierigkeit: int,
        typ_code: Optional[int] = None,
    ) -> int:
        """Leitet Gas-Level aus Strecken-Dimensionen ab."""
        # Basis: Schwierigkeit (1-5) → Level (20-100)
        level = schwierigkeit * 20

        # Typ-Adjustierung
        if typ_code is not None:
            if typ_code <= 2:      # Feldweg/Ortsstraße → weniger Gas
                level = max(10, level - 15)
            elif typ_code >= 9:    # Rallye/Langstrecke → mehr Gas
                level = min(100, level + 10)

        return level


# ─── Singleton ──────────────────────────────────────────────────────

_instance: Optional[GasBremseReasoning] = None


def get_gas_bremse() -> GasBremseReasoning:
    """Gibt Singleton-Instanz zurück."""
    global _instance
    if _instance is None:
        _instance = GasBremseReasoning()
    return _instance


def berechne_gas(
    gas_level: Optional[int] = None,
    strecken_schwierigkeit: Optional[int] = None,
    strecken_typ_code: Optional[int] = None,
) -> GasStellung:
    """Convenience-Funktion."""
    return get_gas_bremse().berechne(gas_level, strecken_schwierigkeit, strecken_typ_code)
