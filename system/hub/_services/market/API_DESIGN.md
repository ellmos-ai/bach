# Market Service - API Design für Agent-Zugriff

**Version:** 1.0.0
**Erstellt:** 2026-01-25
**Task:** PORT_005 / Task #365

---

## Übersicht

Dieses Dokument definiert die API-Schnittstelle, über die BACH-Agenten
auf den Market-Service zugreifen können.

## 1. Python-Interface

### 1.1 High-Level Agent API

```python
from skills._services.market import MarketService

# Singleton-Service für Agent-Zugriff
market = MarketService()

# Aktien-Daten
data = market.get_stock("AAPL", period="1mo")
price = market.get_price("NVDA")  # Aktueller Preis
info = market.get_info("MSFT")    # Unternehmensinfo

# Portfolio-Operationen
market.watchlist.add("AAPL")
market.watchlist.remove("TSLA")
stocks = market.watchlist.list()

# Analyse
analysis = market.analyze("AAPL", metrics=["rsi", "macd", "sma"])
```

### 1.2 Service-Klasse Implementation

```python
# hub/_services/market/__init__.py

from .data_provider import DataProvider
from .database import Database

class MarketService:
    """Zentraler Service für Agent-Zugriff."""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._provider = DataProvider()
            cls._instance._db = Database()
            cls._instance.watchlist = WatchlistAPI(cls._instance._db)
        return cls._instance
    
    def get_stock(self, symbol: str, period: str = "1mo") -> dict:
        """Holt Aktiendaten für Symbol."""
        return self._provider.get_stock_data(symbol, period)
    
    def get_price(self, symbol: str) -> float:
        """Aktueller Preis."""
        data = self._provider.get_stock_data(symbol, period="1d")
        return data.get("close", [None])[-1]
    
    def get_info(self, symbol: str) -> dict:
        """Unternehmens-Informationen."""
        return self._provider.get_stock_info(symbol)
    
    def analyze(self, symbol: str, metrics: list = None) -> dict:
        """Führt Analyse mit gewählten Metriken durch."""
        from .analysis.registry import AnalysisRegistry
        registry = AnalysisRegistry()
        return registry.run_analysis(symbol, metrics or ["basic"])


class WatchlistAPI:
    """Watchlist-Operationen für Agenten."""
    
    def __init__(self, db: Database):
        self._db = db
    
    def add(self, symbol: str) -> bool:
        return self._db.add_to_watchlist(symbol)
    
    def remove(self, symbol: str) -> bool:
        return self._db.remove_from_watchlist(symbol)
    
    def list(self) -> list:
        return self._db.get_watchlist()
```

## 2. CLI-Integration

### 2.1 Befehle

```bash
# Marktdaten
bach market price AAPL           # Aktueller Preis
bach market info NVDA            # Unternehmensinfo
bach market history MSFT --period 3mo  # Historische Daten

# Watchlist
bach market watchlist            # Alle anzeigen
bach market watchlist add AAPL   # Hinzufügen
bach market watchlist remove TSLA  # Entfernen

# Analyse
bach market analyze AAPL         # Standard-Analyse
bach market analyze AAPL --metrics rsi,macd,sma
```

### 2.2 Handler Implementation

```python
# hub/handlers/market.py

def handle(args):
    """Market-Service CLI Handler."""
    from skills._services.market import MarketService
    
    market = MarketService()
    subcommand = args.subcommand if hasattr(args, 'subcommand') else args[0]
    
    if subcommand == "price":
        symbol = args.symbol if hasattr(args, 'symbol') else args[1]
        price = market.get_price(symbol)
        print(f"[MARKET] {symbol}: ${price:.2f}")
    
    elif subcommand == "watchlist":
        if len(args) == 1 or args[1] == "list":
            stocks = market.watchlist.list()
            print(f"[WATCHLIST] {len(stocks)} Einträge:")
            for s in stocks:
                print(f"  - {s}")
        elif args[1] == "add":
            market.watchlist.add(args[2])
            print(f"[OK] {args[2]} zur Watchlist hinzugefügt")
        elif args[1] == "remove":
            market.watchlist.remove(args[2])
            print(f"[OK] {args[2]} aus Watchlist entfernt")
    
    elif subcommand == "analyze":
        symbol = args[1]
        metrics = args.get("--metrics", "basic").split(",")
        result = market.analyze(symbol, metrics)
        _print_analysis(result)
```

## 3. Agent-Nutzung Beispiele

### 3.1 ATI-Agent Integration

```python
# In einem ATI-Workflow:

def check_market_before_trade():
    """ATI prüft Marktdaten vor Empfehlung."""
    from skills._services.market import MarketService
    
    market = MarketService()
    
    # Watchlist durchgehen
    for symbol in market.watchlist.list():
        analysis = market.analyze(symbol, ["rsi", "sma"])
        
        if analysis["rsi"] < 30:
            print(f"[SIGNAL] {symbol} möglicherweise überverkauft (RSI={analysis['rsi']:.1f})")
        elif analysis["rsi"] > 70:
            print(f"[SIGNAL] {symbol} möglicherweise überkauft (RSI={analysis['rsi']:.1f})")
```

### 3.2 Steuer-Agent Integration

```python
# Für Kapitalertragssteuer-Berechnung:

def calculate_gains(year: int):
    """Berechnet Gewinne/Verluste für Steuererklärung."""
    from skills._services.market import MarketService
    
    market = MarketService()
    transactions = market._db.get_transactions(year=year)
    
    total_gain = 0
    for tx in transactions:
        if tx["type"] == "sell":
            buy_price = market.get_historical_price(tx["symbol"], tx["buy_date"])
            sell_price = tx["price"]
            gain = (sell_price - buy_price) * tx["quantity"]
            total_gain += gain
    
    return total_gain
```

## 4. Fehlerbehandlung

```python
from skills._services.market import MarketService, MarketError

try:
    market = MarketService()
    data = market.get_stock("INVALID_SYMBOL")
except MarketError as e:
    print(f"[ERROR] Market-Service: {e}")
    # Fallback oder Alternative
```

### Error-Typen

| Exception | Beschreibung |
|-----------|--------------|
| `MarketError` | Basis-Exception |
| `SymbolNotFound` | Symbol existiert nicht |
| `APIRateLimited` | yfinance Rate-Limit |
| `NetworkError` | Verbindungsproblem |
| `CacheExpired` | Cache-Fehler |

## 5. Konfiguration

```python
# In bach.db oder config:
{
    "market": {
        "cache_ttl": 300,        # 5 Minuten Cache
        "default_period": "1mo",
        "max_symbols_per_request": 10,
        "retry_on_error": 3
    }
}
```

---

## Implementation Status

| Komponente | Status |
|------------|--------|
| MarketService Klasse | ERLEDIGT ✓ (v1.1.57) |
| WatchlistAPI | ERLEDIGT ✓ (v1.1.57) |
| CLI Handler | DESIGN ✓ |
| Error Handling | ERLEDIGT ✓ (v1.1.57) |
| Tests | OFFEN |
| config.py | ERLEDIGT ✓ (v1.1.57) |

---

*Erstellt: BACH Session 2026-01-25*
