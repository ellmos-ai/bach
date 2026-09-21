---
name: market
version: 1.0.0
type: service
author: BACH Team
created: 2026-02-06
updated: 2026-09-18
anthropic_compatible: true
status: active

dependencies:
  tools: []
  services: []
  workflows: []

description: >
  Marktdaten-Service (yfinance) - Aktien, ETFs, Crypto
---
# Market Data Service

> Finanzmarkt-Daten über yfinance API mit Caching und Fehlerbehandlung.

## Module

| Modul | Beschreibung |
|-------|--------------|
| `data_provider.py` | yfinance Wrapper mit TTL-Cache |
| `database.py` | SQLite für Portfolios, Watchlists, Transaktionen |

## Verwendung

```python
from skills._services.market.data_provider import DataProvider
from skills._services.market.database import Database

# Marktdaten abrufen
provider = DataProvider()
data = provider.get_stock_data("AAPL", period="1y")

# Portfolio-Datenbank
db = Database()
db.add_to_watchlist("NVDA")
```

## Abhängigkeiten

- `yfinance` - Yahoo Finance API
- `pandas` - Datenverarbeitung
- `numpy` - Berechnungen

## Migration Status

| Task | Beschreibung | Status |
|------|--------------|--------|
| PORT_001a | core/ Module migrieren | ✅ DONE |
| PORT_001b | analysis/ Ordner migrieren | ✅ DONE |
| PORT_001c | indicators/ Modul migrieren | OFFEN (Quelle nicht gefunden) |
| PORT_001d | jobs/ Modul migrieren | OFFEN (Quelle nicht gefunden) |
| PORT_002 | SKILL.md aktualisieren | ✅ DONE |
| PORT_005 | API-Design für Agent-Zugriff | ✅ DONE (API_DESIGN.md) |

## Hinweis

**Namenskonflikt vermieden:** `financial/` Service ist für Mail-Analyse (Rechnungen, Abos).
Dieser `market/` Service ist für Finanzmarkt-Daten (Aktien, ETFs, Crypto).
