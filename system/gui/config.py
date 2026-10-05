# SPDX-License-Identifier: MIT
"""Laufzeitkonfiguration des BACH-Web-Dashboards.

Die Einstellungen in diesem Modul steuern nur die Einbettung optionaler
Host-Komponenten. Die eingebettete Komponente behaelt ihre eigene kanonische
Konfiguration; BACH fuehrt dafuer keine zweite Konfigurationsdatei ein.

Seit P1-Task #1641 enthaelt das Modul zusaetzlich die Konfiguration fuer den
Cluster-Task-Connector. Tasks koennen damit gegen einen entfernten BACH-Node
synchronisiert werden; bei Fehlen oder Nichterreichbarkeit des Clusters wird
automatisch auf die lokale SQLite-Datenbank zurueckgefallen.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}

CLUSTER_TOKEN_ENV = "BACH_GUI_CLUSTER_TOKEN"
CLUSTER_TOKEN_FILE_ENV = "BACH_GUI_CLUSTER_TOKEN_FILE"
CLUSTER_TOKEN_KEYRING_SECRET = "bach_gui_cluster_token"


class ClusterMode(Enum):
    """Betriebsmodus fuer die Cluster-Task-Synchronisation."""

    ONLINE = "online"
    OFFLINE = "offline"
    AUTO = "auto"

    def __str__(self) -> str:
        return self.value


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


def _read_int(environ: Mapping[str, str], name: str, default: int, *, min_value: int | None = None) -> int:
    raw = environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"{name} muss eine ganze Zahl sein.") from exc
    if min_value is not None and value < min_value:
        raise ValueError(f"{name} muss mindestens {min_value} sein.")
    return value


def _read_float(environ: Mapping[str, str], name: str, default: float, *, min_value: float | None = None) -> float:
    raw = environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw.strip())
    except ValueError as exc:
        raise ValueError(f"{name} muss eine Zahl sein.") from exc
    if min_value is not None and value < min_value:
        raise ValueError(f"{name} muss mindestens {min_value} sein.")
    return value


def _read_mode(environ: Mapping[str, str], name: str, default: ClusterMode) -> ClusterMode:
    raw = environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return ClusterMode(raw.strip().lower())
    except ValueError as exc:
        raise ValueError(
            f"{name} muss einer der Werte "
            f"{', '.join(m.value for m in ClusterMode)} sein."
        ) from exc


def _read_url(environ: Mapping[str, str], name: str, default: str) -> str:
    raw = environ.get(name, default).strip()
    if raw == "":
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"{name} muss eine http:// oder https:// URL sein.")
    if not parsed.netloc:
        raise ValueError(f"{name} muss Host (und optional Port) enthalten.")
    # Normalisiere: kein abschliessender Schraegstrich, damit die API-Pfade
    # deterministisch zusammengesetzt werden koennen.
    return raw.rstrip("/")


def _get_cluster_token_from_keyring() -> str:
    """Letzter Fallback: Token aus dem OS-Schluesselbund lesen."""
    try:
        from hub.secrets_handler import get_secret_value

        value = get_secret_value(CLUSTER_TOKEN_KEYRING_SECRET)
    except Exception:
        return ""
    return str(value or "").strip()


def get_cluster_token(environ: Mapping[str, str] | None = None) -> str:
    """Aufloesen des Cluster-Bearer-Tokens.

    Reihenfolge:
      1. ``BACH_GUI_CLUSTER_TOKEN`` (env)
      2. ``BACH_GUI_CLUSTER_TOKEN_FILE`` (Dateiinhalt)
      3. OS-Keyring (``bach_gui_cluster_token``)

    Fehlt das Token in allen Quellen, wird ein leerer String zurueckgegeben.
    Der Wert wird nicht geloggt oder ausgegeben.
    """
    source = os.environ if environ is None else environ

    configured = str(source.get(CLUSTER_TOKEN_ENV) or "").strip()
    if configured:
        return configured

    token_file = str(source.get(CLUSTER_TOKEN_FILE_ENV) or "").strip()
    if token_file:
        try:
            configured = Path(token_file).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return ""
        return configured

    return _get_cluster_token_from_keyring()


@dataclass(frozen=True)
class ClusterSettings:
    """Konfiguration fuer die Cluster-Task-Synchronisation."""

    url: str = ""
    token: str = ""
    mode: ClusterMode = ClusterMode.AUTO
    timeout: float = 10.0
    retries: int = 2

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "ClusterSettings":
        source = os.environ if environ is None else environ
        return cls(
            url=_read_url(source, "BACH_GUI_CLUSTER_URL", cls.url),
            token=get_cluster_token(source),
            mode=_read_mode(source, "BACH_GUI_CLUSTER_MODE", cls.mode),
            timeout=_read_float(
                source, "BACH_GUI_CLUSTER_TIMEOUT", cls.timeout, min_value=0.01
            ),
            retries=_read_int(
                source, "BACH_GUI_CLUSTER_RETRIES", cls.retries, min_value=0
            ),
        )

    @property
    def is_online(self) -> bool:
        """Gibt an, ob der Cluster-Connector aktiv sein soll.

        * ``online`` -> immer aktiv (auch wenn URL/Token fehlen; der Aufruf
          wird dann scheitern und auf SQLite zurueckfallen).
        * ``offline`` -> nie aktiv.
        * ``auto`` -> aktiv, wenn URL und Token konfiguriert sind.
        """
        if self.mode is ClusterMode.OFFLINE:
            return False
        if self.mode is ClusterMode.ONLINE:
            return True
        return bool(self.url) and bool(self.token)

    @property
    def has_credentials(self) -> bool:
        return bool(self.url) and bool(self.token)


@dataclass(frozen=True)
class Settings:
    """Host-Einstellungen fuer optionale BACH-GUI-Komponenten."""

    # T-20260927-896356881: sicherer Default. Wer die Kontroll-Konsole will,
    # setzt BACH_GUI_CONSOLE_ENABLED=1 explizit (from_env liest das weiterhin).
    console_enabled: bool = False
    console_prefix: str = "/control"
    cluster: ClusterSettings = ClusterSettings()

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
            cluster=ClusterSettings.from_env(source),
        )


settings = Settings.from_env()
