# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Zentrale Stelle fuer die Laufzeit-Grenzen von BACH & Ocean (Standalone-Modul)."""
from __future__ import annotations

import os
from typing import Any, Dict

__version__ = "1.0.0"

DEFAULTS = {
    "BACH_LLM_TIMEOUT": 300,
    "BACH_LLM_TIMEOUT_FAST": 120,
    "BACH_CLI_MAX_TURNS": 30,
    "BACH_CLI_IDLE_TIMEOUT": 300,
    "BACH_CMD_TIMEOUT": 30,
    "BACH_DELEGATE_TIMEOUT": 120,
    "BACH_MAX_TOOL_ROUNDS": 25,
    "BACH_MAX_CONTEXT_CHARS": 24000,
    "BACH_SUMMARIZE_THRESHOLD": 16000,
    "BACH_MAX_MESSAGES": 40,
    "BACH_AUTO_CONTINUE": 0,
    "BACH_CONTEXT_LIMIT": 32768,
    "BACH_HANDOFF_PERCENT": 75,
    "BACH_HOOK_EVERY": 3,
    "BACH_LLM_IDLE_TIMEOUT": 300,
    "BACH_LLM_IDLE_GRACE": 10,
    "BACH_LLM_PING_TIMEOUT": 10,
    "BACH_LLM_TOTAL_CAP": 7200,
    "BACH_CLOUD_MAX_TOOL_ROUNDS": 90,
    "BACH_CLOUD_MAX_TOOL_ROUNDS_CAP": 360,
    "BACH_FACKEL_KAPAZITAET_MB": 0,
}


def limit(name: str, default: int | None = None) -> int:
    """Wert aus der Umgebung, sonst der bisherige Default.

    Ein leerer oder unlesbarer Wert faellt auf den Default zurueck.
    """
    if default is None:
        default = DEFAULTS.get(name, 0)
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def get_all_limits() -> Dict[str, int]:
    """Liefert alle aktuell wirksamen Grenzen als Dictionary."""
    return {name: limit(name) for name in DEFAULTS}


def report() -> str:
    """Zeigt, welche Grenzen gerade gelten und welche gesetzt wurden."""
    lines = [f"{'Grenze':26} {'gilt':>8}  {'Default':>8}  Quelle"]
    for name, dflt in sorted(DEFAULTS.items()):
        val = limit(name)
        src = "ENV" if os.environ.get(name) else "-"
        lines.append(f"{name:26} {val:>8}  {dflt:>8}  {src}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(report())
