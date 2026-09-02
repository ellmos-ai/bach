# SPDX-License-Identifier: MIT
"""Optionales Einhaengen der ellmos-unified-gui Operator-Konsole.

Der Import bleibt lazy und die Abhaengigkeit ist nur ueber
``pip install -e ".[console]"`` erforderlich. BACH uebergibt bewusst keine
eigene Unified-GUI-Konfiguration und baut keine zweite Authentifizierung auf:
``unified_gui.mount()`` verwendet den bestehenden Adapter-/Konfigurationsvertrag.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

logger = logging.getLogger(__name__)


def mount_console(app: FastAPI, prefix: str = "/control") -> bool:
    """Haengt die Operator-Konsole ein und degradiert bei Fehlern graziös."""
    try:
        import unified_gui
    except ImportError:
        logger.info(
            "Console-Mount übersprungen: Paket 'unified_gui' nicht installiert "
            "(Extra fehlt -- 'pip install -e \".[console]\"')."
        )
        return False

    try:
        unified_gui.mount(app, prefix=prefix)
    except Exception:  # noqa: BLE001 -- ein optionales Extra darf BACH nie stoppen
        logger.exception("Unified GUI konnte nicht unter %s eingebunden werden.", prefix)
        return False

    logger.info("Operator-Konsole (ellmos-unified-gui) unter %s eingebunden.", prefix)
    return True
