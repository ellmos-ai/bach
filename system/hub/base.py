# SPDX-License-Identifier: MIT
"""
base.py - Basis-Handler-Klasse
==============================
Unterstuetzt Dual-Init: Legacy (base_path) und New-Style (app).
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Tuple, List


class BaseHandler(ABC):
    """Basisklasse fuer alle CHIAH Handler.

    Dual-Init:
        BaseHandler(base_path: Path)  - Legacy-Modus
        BaseHandler(app: App)         - New-Style mit App-Container
    """

    def __init__(self, base_path_or_app):
        # Duck-Typing: Wenn es base_path hat, ist es eine App
        if hasattr(base_path_or_app, 'base_path') and hasattr(base_path_or_app, 'db'):
            # New-Style: App-Instanz
            self.app = base_path_or_app
            self.base_path = base_path_or_app.base_path
        else:
            # Legacy: Path-Instanz
            self.app = None
            self.base_path = Path(base_path_or_app) if not isinstance(base_path_or_app, Path) else base_path_or_app

        try:
            from .bach_paths import BACH_DB
            self._canonical_db = BACH_DB
        except ImportError:
            self._canonical_db = self.base_path / "data" / "bach.db"
    
    @property
    @abstractmethod
    def profile_name(self) -> str:
        """Name des Profils."""
        pass
    
    @property
    @abstractmethod
    def target_file(self) -> Path:
        """Hauptdatei/Ordner des Handlers."""
        pass
    
    @abstractmethod
    def get_operations(self) -> dict:
        """Verfuegbare Operationen mit Beschreibung."""
        pass
    
    @abstractmethod
    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        """
        Fuehrt Operation aus.
        
        Returns:
            (success, message)
        """
        pass
# TEST
