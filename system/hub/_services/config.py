# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
BACH Skills Services - Zentrale Konfiguration

Erstellt: 2026-01-25
Task: PORT_006 (Voraussetzung)
"""
from pathlib import Path
from dataclasses import dataclass


@dataclass
class Config:
    """Zentrale Konfiguration für alle Services."""
    
    # Pfade
    BASE_DIR: Path = Path(__file__).parent
    DATA_DIR: Path = BASE_DIR / "data"
    
    # Cache-Einstellungen (in Sekunden)
    CACHE_TTL_MARKET_DATA: int = 300      # 5 Minuten für Marktdaten
    CACHE_TTL_COMPANY_INFO: int = 86400   # 24 Stunden für Firmeninfos
    CACHE_TTL_TICKER_INFO: int = 86400    # 24 Stunden für Ticker-Infos
    CACHE_TTL_NEWS: int = 900             # 15 Minuten für News
    CACHE_TTL_DEFAULT: int = 300          # Standard-Cache

    # API-Einstellungen
    API_RETRY_COUNT: int = 3
    API_RETRY_DELAY: int = 1
    API_TIMEOUT: int = 30

    # Datenbank
    DB_NAME: str = "market.db"

    @property
    def DB_PATH(self) -> Path:
        return self.DATA_DIR / self.DB_NAME

    @property
    def db_path(self) -> Path:
        return self.DATA_DIR / self.DB_NAME
    
    def ensure_dirs(self):
        """Erstellt notwendige Verzeichnisse."""
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)


# Singleton-Instanz
config = Config()
