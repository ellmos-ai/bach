# SPDX-License-Identifier: MIT
"""Laufzeitkonfiguration des BACH-Web-Dashboards.

Die Einstellungen in diesem Modul steuern nur die Einbettung optionaler
Host-Komponenten. Die eingebettete Komponente behaelt ihre eigene kanonische
Konfiguration; BACH fuehrt dafuer keine zweite Konfigurationsdatei ein.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _read_bool(environ: Mapping[str, str], name: str, default: bool) -> bool:
    raw = environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(
        f"{name} muss einer der Werte "
        f"{', '.join(sorted(_TRUE_VALUES | _FALSE_VALUES))} sein."
    )


def _read_mount_prefix(environ: Mapping[str, str], name: str, default: str) -> str:
    prefix = environ.get(name, default).strip().rstrip("/")
    if not prefix.startswith("/") or prefix == "":
        raise ValueError(f"{name} muss ein nicht-leerer absoluter URL-Pfad sein.")
    return prefix


@dataclass(frozen=True)
class Settings:
    """Host-Einstellungen fuer optionale BACH-GUI-Komponenten."""

    console_enabled: bool = False
    console_prefix: str = "/control"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        source = os.environ if environ is None else environ
        return cls(
            console_enabled=_read_bool(
                source, "BACH_GUI_CONSOLE_ENABLED", cls.console_enabled
            ),
            console_prefix=_read_mount_prefix(
                source, "BACH_GUI_CONSOLE_PREFIX", cls.console_prefix
            ),
        )


settings = Settings.from_env()
